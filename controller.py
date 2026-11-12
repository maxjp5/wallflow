"""The engine behind the window: timer, fetching, history and settings.

The UI only calls methods here and listens to signals, so pages stay simple.
"""
import os
import threading
import time
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal

import core
import sources

SHOW_FLAG = os.path.join(core.DATA_DIR, "show.flag")
NEXT_FLAG = os.path.join(core.DATA_DIR, "next.flag")


class Controller(QObject):
    current_changed = Signal()            # current wallpaper or history changed
    history_changed = Signal()
    favorites_changed = Signal()
    status = Signal(str, str)             # (kind: info|success|error, message)
    busy_changed = Signal(bool)
    tick = Signal(int, float, str)        # (seconds left, fraction elapsed, paused reason or "")
    running_changed = Signal(bool)
    show_requested = Signal()
    update_found = Signal(str, str)       # (version, url)
    update_result = Signal(str, str, str)
    _fetched = Signal(object)
    _failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = core.load_settings()
        self.pos = 0
        self.busy = False
        self.fader = None                       # DesktopFade, set by the window (needs Qt widgets)
        self.next_change = time.time() + self.interval_seconds()
        self._fetched.connect(self._on_fetched)
        self._failed.connect(self._on_failed)

        try:
            core.backup_original(self.settings)
        except Exception:  # noqa: BLE001
            pass
        if self.settings["start_with_windows"]:
            try:
                core.set_startup(True)          # keep the entry pointing at this copy
            except OSError:
                pass

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    # ---------------------------------------------------------- basics

    def interval_seconds(self):
        return core.INTERVALS.get(self.settings["interval"], 30) * 60   # 0 = don't rotate

    def save(self):
        core.save_settings(self.settings)

    def history(self):
        return self.settings["history"]

    def current(self):
        h = self.history()
        return h[self.pos] if 0 <= self.pos < len(h) else None

    def source_label(self, key):
        return sources.SOURCES.get(key, (key,))[0]

    def set_option(self, key, value):
        self.settings[key] = value
        self.save()

    # ---------------------------------------------------------- timer

    def _tick(self):
        if os.path.exists(SHOW_FLAG):
            _remove(SHOW_FLAG)
            self.show_requested.emit()
        if os.path.exists(NEXT_FLAG):
            _remove(NEXT_FLAG)
            self.next_new()

        total = self.interval_seconds()
        if not self.settings["running"]:
            self.tick.emit(0, 0.0, "Paused")
            return
        if total == 0:
            self.tick.emit(0, 0.0, "Not rotating. Press Next for a new wallpaper")
            return
        left = max(0, int(self.next_change - time.time()))
        if left == 0 and not self.busy:
            why = self.pause_reason()
            if why:
                self.next_change = time.time() + 60
                self.tick.emit(60, 1.0, why)
                return
            self.next_new()
        self.tick.emit(left, 1 - left / total if total else 0, "")

    def pause_reason(self):
        s = self.settings
        if s.get("pause_fullscreen", True) and core.fullscreen_app_running():
            return "Waiting: full-screen app open"
        if s.get("pause_on_battery") and core.on_battery():
            return "Waiting: on battery"
        return ""

    def set_running(self, on):
        self.settings["running"] = bool(on)
        self.next_change = time.time() + self.interval_seconds()
        self.save()
        self.running_changed.emit(bool(on))

    def set_interval(self, label):
        self.settings["interval"] = label
        self.next_change = time.time() + self.interval_seconds()
        self.save()

    # ---------------------------------------------------------- changing

    def next_new(self):
        """Always fetch a brand-new wallpaper (timer, tray, Next button)."""
        self.pos = 0
        if self.busy:
            return
        self.busy = True
        self.busy_changed.emit(True)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            entry = core.fetch_new(self.settings, core.wallpaper_size(self.settings),
                                   log=lambda m: self.status.emit("info", m))
            self._fetched.emit(entry)
        except Exception as e:  # noqa: BLE001
            self._failed.emit(str(e))

    def _on_fetched(self, entry):
        self.busy = False
        self.busy_changed.emit(False)
        self.apply(entry, add=True)

    def _on_failed(self, msg):
        self.busy = False
        self.busy_changed.emit(False)
        self.next_change = time.time() + 120
        self.status.emit("error", msg)

    def apply(self, entry, add=False):
        style = self.settings["style"]
        fading = False
        if self.fader and self.settings.get("smooth_transition", True):
            fading = self.fader.cover(core.shown_wallpaper(), style)   # old picture on top
        try:
            core.set_wallpaper(entry["path"], style)                    # switch underneath it
        except Exception as e:  # noqa: BLE001
            if fading:
                self.fader.finish()
            self.status.emit("error", f"Couldn't set wallpaper: {e}")
            return
        if fading:
            self.fader.fade_out()                                       # reveal the new one smoothly
        if add:
            h = self.history()
            h.insert(0, entry)
            del h[self.settings.get("keep_history", 40):]
            self.pos = 0
            core.prune_cache(self.settings)
            threading.Thread(target=core.ping_used, args=(entry,), daemon=True).start()
            self.history_changed.emit()
        self.next_change = time.time() + self.interval_seconds()
        self.save()
        self.current_changed.emit()
        self.status.emit("success", "Wallpaper set")

    def previous(self):
        if self.pos + 1 < len(self.history()):
            self.pos += 1
            self.apply(self.current())

    def forward(self):
        if self.pos > 0:
            self.pos -= 1
            self.apply(self.current())
        else:
            self.next_new()

    def pick(self, index):
        if 0 <= index < len(self.history()):
            self.pos = index
            self.apply(self.current())

    def set_style(self, style):
        self.settings["style"] = style
        self.save()
        if self.current():
            self.apply(self.current())

    def toggle_favorite(self, entry):
        """Heart button: save to favorites, or remove if it's already there.
        Returns True when saved, False when removed, None on error."""
        if not entry:
            return None
        try:
            if core.is_favorite(entry):
                core.remove_favorite(entry)
                saved = False
            else:
                core.save_favorite(entry)
                saved = True
        except OSError as e:
            self.status.emit("error", f"Couldn't update favorites: {e}")
            return None
        self.favorites_changed.emit()
        return saved

    def use_entry(self, entry):
        """Set a wallpaper that isn't in history yet (e.g. from Favorites)."""
        e = {k: v for k, v in entry.items() if k != "favorite"}
        e["time"] = time.time()
        self.apply(e, add=True)

    def open_page(self, index=None):
        h = self.history()
        entry = h[index] if index is not None and 0 <= index < len(h) else self.current()
        if not entry or not entry.get("page"):
            return
        if entry["source"] in ("local", "packs") and os.path.exists(entry["page"]):
            os.startfile(os.path.dirname(entry["page"]))
        else:
            webbrowser.open(entry["page"])

    # ---------------------------------------------------------- storage

    def set_keep(self, n):
        self.settings["keep_history"] = n
        del self.history()[n:]
        self.pos = min(self.pos, max(0, len(self.history()) - 1))
        core.prune_cache(self.settings)
        self.save()
        self.history_changed.emit()

    def clear_history(self):
        cur = self.current()
        self.settings["history"] = [cur] if cur else []
        self.pos = 0
        core.prune_cache(self.settings)
        self.save()
        self.history_changed.emit()
        self.current_changed.emit()

    def restore_original(self):
        core.restore_original(self.settings)
        self.set_running(False)

    # ---------------------------------------------------------- updates

    def check_updates(self):
        """Emits update_result(kind, version_or_error, url); kind is new|latest|error."""
        def work():
            try:
                ver, url = core.latest_release()
                if core.is_newer(ver):
                    self.update_found.emit(ver, url)
                    self.update_result.emit("new", ver, url)
                else:
                    self.update_result.emit("latest", core.VERSION, "")
            except Exception as e:  # noqa: BLE001
                self.update_result.emit("error", str(e), "")

        threading.Thread(target=work, daemon=True).start()


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
