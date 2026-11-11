"""Wallflow — an automatic wallpaper changer for Windows.

Double-click this file to start. Closing the window keeps it running in the tray.
"""
import os
import queue
import sys
import threading
import time
import traceback
import webbrowser
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk  # noqa: E402
import pystray  # noqa: E402
from PIL import Image, ImageDraw, ImageOps, ImageTk  # noqa: E402

import core  # noqa: E402
import sources  # noqa: E402

ACCENT = "#7c5cff"
ACCENT_HOVER = "#6a4bea"
CARD = ("#f2f2f5", "#1e1f24")
SUBTLE = ("#5b5d66", "#9a9ca6")
PREVIEW_W, PREVIEW_H = 720, 405
THUMB_W, THUMB_H = 144, 81
SHOW_FLAG = os.path.join(core.DATA_DIR, "show.flag")
NEXT_FLAG = os.path.join(core.DATA_DIR, "next.flag")


def resource(name):
    """Path to a bundled file, both from source and inside the packaged exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def set_window_icon(win):
    try:
        win.iconbitmap(resource("wallflow.ico"))
    except Exception:  # noqa: BLE001
        pass

SOURCE_FIELDS = {  # key -> list of (setting, label, kind[, choices])
    "wallhaven": [("query", "Search (blank = everything)", "entry"),
                  ("sort", "Sort by", "choice", list(sources.WALLHAVEN_SORTS)),
                  ("range", "Toplist period", "choice", list(sources.WALLHAVEN_RANGES)),
                  ("collection", "Collection link (optional, replaces search)", "entry"),
                  ("anime", "Include anime", "check"),
                  ("api_key", "API key (optional)", "secret")],
    "unsplash": [("mode", "Pull from", "choice", sources.UNSPLASH_MODES),
                 ("query", "Topic name, search words, or collection link", "entry"),
                 ("access_key", "Access key (required)", "secret")],
    "nasa": [("query", "Search (blank = random space)", "entry")],
    "picsum": [],
    "local": [("folder", "Folder", "folder")],
    "packs": [],
}


def describe(key, cfg):
    """Short human description of what a source is set to pull."""
    if key == "wallhaven":
        if cfg.get("collection", "").strip():
            return "Wallhaven · collection"
        sort = cfg.get("sort", "Random")
        extra = f" ({cfg.get('range', 'Past month').replace('Past ', '').lower()})" if sort == "Toplist" else ""
        return f"Wallhaven · {sort}{extra} · {cfg.get('query', '').strip() or 'everything'}"
    if key == "unsplash":
        return f"Unsplash · {cfg.get('mode', 'Topic')} · {cfg.get('query', '').strip() or 'wallpapers'}"
    if key == "nasa":
        return f"NASA · {cfg.get('query', '').strip() or 'random space'}"
    return sources.SOURCES[key][0]


def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=(124, 92, 255))
    s = size / 64
    d.polygon([(8 * s, 50 * s), (26 * s, 24 * s), (38 * s, 40 * s), (44 * s, 32 * s), (56 * s, 50 * s)],
              fill=(255, 255, 255))
    d.ellipse((40 * s, 12 * s, 50 * s, 22 * s), fill=(255, 214, 102))
    return img


class Wallflow(ctk.CTk):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.settings = core.load_settings()
        self.screen = core.screen_size()
        self.events = queue.Queue()
        self.busy = False
        self.pos = 0                       # index into history of the current wallpaper
        self.next_change = time.time() + self.interval_seconds()
        self.thumb_refs = []
        self.save_job = None

        self.title("Wallflow")
        self.geometry("1180x760")
        self.minsize(1000, 640)
        self.icon_img = make_icon(64)
        self._tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.after(300, lambda: set_window_icon(self))   # after customtkinter sets its own

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_main()
        self.build_sidebar()

        try:
            core.backup_original(self.settings)
        except Exception:  # noqa: BLE001
            pass
        if self.settings["start_with_windows"]:    # keep the startup entry pointing at this copy
            try:
                core.set_startup(True)
            except OSError:
                pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.start_tray()
        self.refresh_current()
        self.refresh_history()

        if start_hidden:
            self.withdraw()
        if not self.settings["history"]:
            self.after(600, self.next_wallpaper)
        self.after(200, self.pump)
        self.after(1000, self.tick)

    # ------------------------------------------------------------ layout

    def build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=20)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(main, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="Wallflow", font=ctk.CTkFont(size=26, weight="bold")).pack(side="left")
        self.countdown = ctk.CTkLabel(head, text="", text_color=SUBTLE, font=ctk.CTkFont(size=14))
        self.countdown.pack(side="right")

        card = ctk.CTkFrame(main, fg_color=CARD, corner_radius=16)
        card.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        self.preview = ctk.CTkLabel(card, text="Fetching your first wallpaper…", text_color=SUBTLE)
        self.preview.grid(row=0, column=0, padx=18, pady=(18, 8))

        self.info = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=14, weight="bold"),
                                 wraplength=PREVIEW_W, justify="center")
        self.info.grid(row=1, column=0, padx=18)
        self.subinfo = ctk.CTkLabel(card, text="", text_color=SUBTLE)
        self.subinfo.grid(row=2, column=0, padx=18)

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=3, column=0, pady=(10, 6))
        self.prev_btn = ctk.CTkButton(btns, text="◀  Previous", width=120, fg_color="transparent",
                                      border_width=1, text_color=("gray10", "gray90"), command=self.previous)
        self.prev_btn.pack(side="left", padx=5)
        self.next_btn = ctk.CTkButton(btns, text="Next wallpaper  ▶", width=170, height=36,
                                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                      font=ctk.CTkFont(size=14, weight="bold"), command=self.next_wallpaper)
        self.next_btn.pack(side="left", padx=5)
        ctk.CTkButton(btns, text="★  Save", width=100, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.favorite).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="Open page ↗", width=110, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.open_page).pack(side="left", padx=5)

        self.status = ctk.CTkLabel(card, text="", text_color=SUBTLE)
        self.status.grid(row=4, column=0, pady=(0, 12))

        ctk.CTkLabel(main, text="Recent", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=2, column=0, sticky="w", pady=(16, 4))
        self.strip = ctk.CTkScrollableFrame(main, orientation="horizontal", height=THUMB_H + 24,
                                            fg_color=CARD, corner_radius=12)
        self.strip.grid(row=3, column=0, sticky="ew")

    def build_sidebar(self):
        side = ctk.CTkScrollableFrame(self, width=330, fg_color=CARD, corner_radius=16)
        side.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=20)
        s = self.settings

        def section(text):
            ctk.CTkLabel(side, text=text, font=ctk.CTkFont(size=16, weight="bold")).pack(
                anchor="w", padx=14, pady=(16, 6))

        section("Auto-change")
        row = ctk.CTkFrame(side, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self.run_var = ctk.BooleanVar(value=s["running"])
        ctk.CTkSwitch(row, text="Change automatically", variable=self.run_var, progress_color=ACCENT,
                      command=self.on_running).pack(side="left")
        row = ctk.CTkFrame(side, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(row, text="Every").pack(side="left")
        self.interval_var = ctk.StringVar(value=s["interval"])
        ctk.CTkOptionMenu(row, values=list(core.INTERVALS), variable=self.interval_var, width=150,
                          fg_color=ACCENT, button_color=ACCENT_HOVER,
                          command=self.on_interval).pack(side="left", padx=10)

        section("Fit on screen")
        self.style_var = ctk.StringVar(value=s["style"])
        ctk.CTkSegmentedButton(side, values=["Fill", "Fit", "Stretch", "Center", "Span"],
                               variable=self.style_var, selected_color=ACCENT,
                               selected_hover_color=ACCENT_HOVER, command=self.on_style).pack(
            fill="x", padx=14)

        section("Sources")
        ctk.CTkLabel(side, text="Each change picks one of the sources you turn on.",
                     text_color=SUBTLE, wraplength=290, justify="left").pack(anchor="w", padx=14)
        self.source_vars = {}
        for key, (label, _fn) in sources.SOURCES.items():
            cfg = s["sources"][key]
            box = ctk.CTkFrame(side, corner_radius=10, fg_color=("#e6e6ec", "#2a2b31"))
            box.pack(fill="x", padx=14, pady=5)
            en = ctk.BooleanVar(value=cfg.get("enabled", False))
            ctk.CTkCheckBox(box, text=label, variable=en, font=ctk.CTkFont(weight="bold"),
                            fg_color=ACCENT, hover_color=ACCENT_HOVER,
                            command=self.schedule_save).pack(anchor="w", padx=10, pady=(8, 4))
            vars_ = {"enabled": en}
            if key == "packs":
                self.build_packs_box(box)
            for field, flabel, kind, *choices in SOURCE_FIELDS[key]:
                if kind == "choice":
                    v = ctk.StringVar(value=cfg.get(field) or choices[0][0])
                    line = ctk.CTkFrame(box, fg_color="transparent")
                    line.pack(fill="x", padx=(34, 10), pady=(0, 6))
                    ctk.CTkLabel(line, text=flabel, text_color=SUBTLE).pack(side="left")
                    ctk.CTkOptionMenu(line, values=choices[0], variable=v, width=150,
                                      fg_color=("#d4d4dc", "#3a3b42"), button_color=("#c4c4cc", "#45464e"),
                                      text_color=("gray10", "gray90"),
                                      command=lambda _v: self.schedule_save()).pack(side="right")
                elif kind == "check":
                    v = ctk.BooleanVar(value=cfg.get(field, False))
                    ctk.CTkCheckBox(box, text=flabel, variable=v, checkbox_width=18, checkbox_height=18,
                                    fg_color=ACCENT, command=self.schedule_save).pack(
                        anchor="w", padx=34, pady=(0, 6))
                else:
                    v = ctk.StringVar(value=cfg.get(field, ""))
                    v.trace_add("write", lambda *_: self.schedule_save())
                    ctk.CTkLabel(box, text=flabel, text_color=SUBTLE, height=16,
                                 font=ctk.CTkFont(size=11)).pack(anchor="w", padx=36)
                    line = ctk.CTkFrame(box, fg_color="transparent")
                    line.pack(fill="x", padx=(34, 10), pady=(0, 6))
                    ent = ctk.CTkEntry(line, textvariable=v, placeholder_text=flabel,
                                       show="•" if kind == "secret" else "")
                    ent.pack(side="left", fill="x", expand=True)
                    if kind == "folder":
                        ctk.CTkButton(line, text="Browse", width=64, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER,
                                      command=lambda var=v: self.pick_folder(var)).pack(side="left", padx=(6, 0))
                vars_[field] = v
            if key == "unsplash":
                link = ctk.CTkLabel(box, text="Get a free key ↗", text_color=ACCENT, cursor="hand2")
                link.pack(anchor="w", padx=34, pady=(0, 6))
                link.bind("<Button-1>", lambda _e: webbrowser.open("https://unsplash.com/developers"))
            ctk.CTkFrame(box, height=2, fg_color="transparent").pack()
            self.source_vars[key] = vars_

        section("Options")
        self.startup_var = ctk.BooleanVar(value=s["start_with_windows"])
        ctk.CTkCheckBox(side, text="Start with Windows", variable=self.startup_var, fg_color=ACCENT,
                        command=self.on_startup).pack(anchor="w", padx=14, pady=4)
        self.tray_var = ctk.BooleanVar(value=s["close_to_tray"])
        ctk.CTkCheckBox(side, text="Keep running in tray when closed", variable=self.tray_var,
                        fg_color=ACCENT, command=self.schedule_save).pack(anchor="w", padx=14, pady=4)
        row = ctk.CTkFrame(side, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(row, text="Theme").pack(side="left")
        ctk.CTkOptionMenu(row, values=["System", "Dark", "Light"], width=110, fg_color=ACCENT,
                          button_color=ACCENT_HOVER,
                          command=lambda m: ctk.set_appearance_mode(m)).pack(side="left", padx=10)

        for text, cmd in (("Open favorites folder", self.open_favorites),
                          ("Restore my original wallpaper", self.restore_original)):
            ctk.CTkButton(side, text=text, fg_color="transparent", border_width=1,
                          text_color=("gray10", "gray90"), command=cmd).pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(side, text=f"Wallflow {core.VERSION}", text_color=SUBTLE,
                     font=ctk.CTkFont(size=11)).pack(pady=(14, 8))

    # ------------------------------------------------------------ packs

    def build_packs_box(self, box):
        ctk.CTkLabel(box, text="Download a set once, then rotate through it without internet.",
                     text_color=SUBTLE, wraplength=250, justify="left",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=36)
        self.packs_list = ctk.CTkFrame(box, fg_color="transparent")
        self.packs_list.pack(fill="x", padx=(34, 10), pady=4)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=(34, 10), pady=(0, 8))
        ctk.CTkButton(row, text="＋ Download a pack", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.open_pack_dialog).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Folder", width=64, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.open_packs_folder).pack(side="left", padx=(6, 0))
        self.pack_vars = {}
        self.refresh_packs()

    def refresh_packs(self):
        for w in self.packs_list.winfo_children():
            w.destroy()
        selected = set(self.settings["sources"]["packs"].get("selected", []))
        self.pack_vars = {}
        packs = core.list_packs()
        if not packs:
            ctk.CTkLabel(self.packs_list, text="No packs yet.", text_color=SUBTLE).pack(anchor="w")
        for name, count in packs:
            v = ctk.BooleanVar(value=name in selected)
            ctk.CTkCheckBox(self.packs_list, text=f"{name}  ({count})", variable=v, checkbox_width=18,
                            checkbox_height=18, fg_color=ACCENT, command=self.schedule_save).pack(
                anchor="w", pady=2)
            self.pack_vars[name] = v

    def open_packs_folder(self):
        os.makedirs(core.PACKS_DIR, exist_ok=True)
        os.startfile(core.PACKS_DIR)

    def open_pack_dialog(self):
        self.collect()
        if getattr(self, "pack_dialog", None) and self.pack_dialog.winfo_exists():
            self.pack_dialog.focus()
            return
        self.pack_dialog = PackDialog(self)

    def pack_finished(self, name):
        self.collect()
        self.refresh_packs()
        if dict(core.list_packs()).get(name):
            self.pack_vars[name].set(True)
            self.source_vars["packs"]["enabled"].set(True)
        self.save()

    # ------------------------------------------------------------ settings

    def interval_seconds(self):
        return core.INTERVALS.get(self.settings["interval"], 30) * 60

    def collect(self):
        s = self.settings
        for key, vars_ in self.source_vars.items():
            for field, var in vars_.items():
                s["sources"][key][field] = var.get()
        if hasattr(self, "pack_vars"):
            s["sources"]["packs"]["selected"] = [n for n, v in self.pack_vars.items() if v.get()]
        s["close_to_tray"] = self.tray_var.get()

    def schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(500, self.save)

    def save(self):
        self.save_job = None
        self.collect()
        core.save_settings(self.settings)

    def on_running(self):
        self.settings["running"] = self.run_var.get()
        self.next_change = time.time() + self.interval_seconds()
        self.save()
        self.update_tray_menu()

    def on_interval(self, value):
        self.settings["interval"] = value
        self.next_change = time.time() + self.interval_seconds()
        self.save()

    def on_style(self, value):
        self.settings["style"] = value
        self.save()
        entry = self.current()
        if entry:
            self.apply(entry, add=False)

    def on_startup(self):
        try:
            core.set_startup(self.startup_var.get())
            self.settings["start_with_windows"] = self.startup_var.get()
            self.save()
        except OSError as e:
            messagebox.showerror("Wallflow", f"Couldn't change startup setting:\n{e}")

    def pick_folder(self, var):
        folder = filedialog.askdirectory(title="Pick a folder of wallpapers")
        if folder:
            var.set(os.path.normpath(folder))

    # ------------------------------------------------------------ actions

    def current(self):
        h = self.settings["history"]
        return h[self.pos] if 0 <= self.pos < len(h) else None

    def set_status(self, text):
        self.status.configure(text=text)

    def next_wallpaper(self):
        if self.pos > 0:                      # walking forward through history
            self.pos -= 1
            self.apply(self.current(), add=False)
            return
        if self.busy:
            return
        self.busy = True
        self.collect()
        self.next_btn.configure(state="disabled", text="Fetching…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            entry = core.fetch_new(self.settings, self.screen,
                                   log=lambda m: self.events.put(("status", m)))
            self.events.put(("fetched", entry))
        except Exception as e:  # noqa: BLE001
            self.events.put(("error", str(e)))

    def apply(self, entry, add=True):
        try:
            core.set_wallpaper(entry["path"], self.settings["style"])
        except Exception as e:  # noqa: BLE001
            self.set_status(f"Couldn't set wallpaper: {e}")
            return
        if add:
            h = self.settings["history"]
            h.insert(0, entry)
            del h[self.settings.get("keep_history", 40):]
            self.pos = 0
            core.prune_cache(self.settings)
            self.refresh_history()
            threading.Thread(target=core.ping_used, args=(entry,), daemon=True).start()
        self.next_change = time.time() + self.interval_seconds()
        self.save()
        self.refresh_current()
        self.highlight_thumb()
        self.set_status("Wallpaper set ✓")

    def previous(self):
        if self.pos + 1 < len(self.settings["history"]):
            self.pos += 1
            self.apply(self.current(), add=False)
        else:
            self.set_status("That's the oldest one in your history.")

    def pick_history(self, index):
        self.pos = index
        self.apply(self.current(), add=False)

    def favorite(self):
        entry = self.current()
        if not entry:
            return
        try:
            core.save_favorite(entry)
            self.set_status("Saved to Pictures\\Wallflow Favorites ★")
        except OSError as e:
            self.set_status(f"Couldn't save: {e}")

    def open_page(self):
        entry = self.current()
        if entry and entry.get("page"):
            if entry["source"] == "local":
                os.startfile(os.path.dirname(entry["page"]))
            else:
                webbrowser.open(entry["page"])

    def open_favorites(self):
        os.makedirs(core.FAVORITES_DIR, exist_ok=True)
        os.startfile(core.FAVORITES_DIR)

    def restore_original(self):
        if not messagebox.askyesno("Wallflow", "Put back the wallpaper you had before Wallflow?\n"
                                               "Auto-change will be paused."):
            return
        try:
            core.restore_original(self.settings)
            self.run_var.set(False)
            self.on_running()
            self.set_status("Original wallpaper restored. Auto-change paused.")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Wallflow", str(e))

    # ------------------------------------------------------------ display

    def refresh_current(self):
        entry = self.current()
        if not entry:
            return
        try:
            img = ImageOps.fit(Image.open(entry["path"]), (PREVIEW_W * 2, PREVIEW_H * 2))
            self._preview_img = ctk.CTkImage(img, size=(PREVIEW_W, PREVIEW_H))
            self.preview.configure(image=self._preview_img, text="")
        except OSError:
            self.preview.configure(image=None, text="(image missing)")
        label = sources.SOURCES.get(entry["source"], (entry["source"],))[0]
        self.info.configure(text=entry.get("title") or "Untitled")
        when = time.strftime("%b %d, %I:%M %p", time.localtime(entry.get("time", time.time())))
        self.subinfo.configure(text=f"{label}  ·  {when}")
        self.prev_btn.configure(state="normal" if self.pos + 1 < len(self.settings["history"]) else "disabled")

    def refresh_history(self):
        for w in self.strip.winfo_children():
            w.destroy()
        self.thumb_refs = []
        self.thumb_buttons = []
        for i, entry in enumerate(self.settings["history"]):
            try:
                img = ImageOps.fit(Image.open(entry["path"]), (THUMB_W * 2, THUMB_H * 2))
            except OSError:
                continue
            cimg = ctk.CTkImage(img, size=(THUMB_W, THUMB_H))
            self.thumb_refs.append(cimg)
            b = ctk.CTkButton(self.strip, image=cimg, text="", width=THUMB_W + 8, height=THUMB_H + 8,
                              fg_color="transparent", border_width=2, border_color=CARD[1],
                              hover_color=("#d8d8e0", "#33343b"),
                              command=lambda idx=i: self.pick_history(idx))
            b.pack(side="left", padx=4, pady=4)
            self.thumb_buttons.append(b)
        self.highlight_thumb()

    def highlight_thumb(self):
        for i, b in enumerate(getattr(self, "thumb_buttons", [])):
            b.configure(border_color=ACCENT if i == self.pos else CARD)

    # ------------------------------------------------------------ loop

    def pump(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "status":
                    self.set_status(data)
                elif kind == "fetched":
                    self.busy = False
                    self.next_btn.configure(state="normal", text="Next wallpaper  ▶")
                    self.apply(data)
                elif kind == "error":
                    self.busy = False
                    self.next_btn.configure(state="normal", text="Next wallpaper  ▶")
                    self.set_status(data)
                    self.next_change = time.time() + 120   # retry in 2 min
                elif kind == "call":
                    try:
                        data()
                    except Exception:  # noqa: BLE001 - e.g. a closed dialog
                        pass
        except queue.Empty:
            pass
        self.after(200, self.pump)

    def tick(self):
        if os.path.exists(SHOW_FLAG):
            try:
                os.remove(SHOW_FLAG)
            except OSError:
                pass
            self.show()
        if os.path.exists(NEXT_FLAG):
            try:
                os.remove(NEXT_FLAG)
            except OSError:
                pass
            self.tray_next()
        if self.settings["running"]:
            left = max(0, int(self.next_change - time.time()))
            if left == 0 and not self.busy:
                self.pos = 0
                self.next_wallpaper()
            h, rem = divmod(left, 3600)
            m, sec = divmod(rem, 60)
            self.countdown.configure(text=f"Next change in {h}:{m:02d}:{sec:02d}" if h
                                     else f"Next change in {m}:{sec:02d}")
        else:
            self.countdown.configure(text="Auto-change paused")
        self.after(1000, self.tick)

    # ------------------------------------------------------------ tray

    def start_tray(self):
        def call(fn):
            return lambda *_: self.events.put(("call", fn))

        def toggle():
            self.run_var.set(not self.run_var.get())
            self.on_running()

        self._tray_actions = (call(self.show), call(self.tray_next), call(toggle), call(self.quit_app))
        self.tray = pystray.Icon("Wallflow", self.icon_img, "Wallflow", self.tray_menu())
        self.tray.run_detached()

    def tray_menu(self):
        show, nxt, toggle, quit_ = self._tray_actions
        return pystray.Menu(
            pystray.MenuItem("Open Wallflow", show, default=True),
            pystray.MenuItem("Next wallpaper", nxt),
            pystray.MenuItem("Resume auto-change" if not self.settings["running"] else "Pause auto-change",
                             toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_),
        )

    def update_tray_menu(self):
        self.tray.menu = self.tray_menu()
        self.tray.update_menu()

    def tray_next(self):
        self.pos = 0
        self.next_wallpaper()

    def show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close(self):
        self.save()
        if self.tray_var.get():
            self.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        try:
            self.save()
        finally:
            self.tray.stop()
            self.destroy()


class PackDialog(ctk.CTkToplevel):
    """Download a batch of wallpapers from a source into an offline pack."""

    COUNTS = ["24", "50", "100", "200"]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.cancel_flag = False
        self.running = False
        self.title("Download a pack")
        self.geometry("480x500")
        self.resizable(False, False)
        self.transient(app)
        self.after(300, lambda: set_window_icon(self))

        labels = {sources.SOURCES[k][0]: k for k in sources.PACK_SOURCES}
        self.labels = labels
        pad = {"padx": 22}
        ctk.CTkLabel(self, text="Download a pack", font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="w", pady=(18, 2), **pad)
        ctk.CTkLabel(self, text="Uses the search and sort you set for that source in the sidebar.",
                     text_color=SUBTLE).pack(anchor="w", **pad)

        ctk.CTkLabel(self, text="From", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(14, 4), **pad)
        first = next((lbl for lbl, k in labels.items()
                      if app.settings["sources"][k].get("enabled")), next(iter(labels)))
        self.src_var = ctk.StringVar(value=first)
        ctk.CTkSegmentedButton(self, values=list(labels), variable=self.src_var, selected_color=ACCENT,
                               selected_hover_color=ACCENT_HOVER, command=self.on_source).pack(fill="x", **pad)
        self.what = ctk.CTkLabel(self, text="", text_color=SUBTLE)
        self.what.pack(anchor="w", pady=(4, 0), **pad)

        ctk.CTkLabel(self, text="Pack name", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4), **pad)
        self.name_var = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.name_var).pack(fill="x", **pad)

        ctk.CTkLabel(self, text="How many", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4), **pad)
        self.count_var = ctk.StringVar(value="50")
        ctk.CTkSegmentedButton(self, values=self.COUNTS, variable=self.count_var, selected_color=ACCENT,
                               selected_hover_color=ACCENT_HOVER).pack(fill="x", **pad)

        self.bar = ctk.CTkProgressBar(self, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(18, 4), **pad)
        self.msg = ctk.CTkLabel(self, text="", text_color=SUBTLE)
        self.msg.pack(anchor="w", **pad)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(10, 16), **pad)
        self.go = ctk.CTkButton(row, text="Download", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                command=self.start)
        self.go.pack(side="right")
        self.cancel_btn = ctk.CTkButton(row, text="Close", fg_color="transparent", border_width=1,
                                        text_color=("gray10", "gray90"), command=self.on_cancel)
        self.cancel_btn.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.on_source(first)

    def key(self):
        return self.labels[self.src_var.get()]

    def on_source(self, _value=None):
        key = self.key()
        desc = describe(key, self.app.settings["sources"][key])
        self.what.configure(text=desc)
        parts = desc.split(" · ")[1:]           # drop the source name
        self.name_var.set(" - ".join(reversed(parts)) if parts else desc)

    def post(self, fn):
        self.app.events.put(("call", fn))

    def start(self):
        key = self.key()
        cfg = dict(self.app.settings["sources"][key])
        name = core.safe_name(self.name_var.get())
        count = int(self.count_var.get())
        self.running, self.cancel_flag = True, False
        self.go.configure(state="disabled", text="Downloading…")
        self.cancel_btn.configure(text="Stop")

        def progress(done, total, msg):
            self.post(lambda: (self.bar.set(done / total), self.msg.configure(text=msg)))

        def work():
            try:
                pack, got = core.download_pack(name, key, cfg, self.app.screen, count, progress,
                                               cancelled=lambda: self.cancel_flag)
                note = f"Done: {got} new images in “{pack}”." if got else "No new images found for that search."
                self.post(lambda: self.finish(pack, note, got))
            except Exception as e:  # noqa: BLE001
                err = f"Stopped: {e}"
                self.post(lambda: self.finish(core.safe_name(name), err, 0))

        threading.Thread(target=work, daemon=True).start()

    def finish(self, pack, note, got):
        self.running = False
        self.app.pack_finished(pack)        # refresh list even if partially downloaded
        try:
            self.msg.configure(text=note + (" It's ticked in My Packs." if got else ""))
            self.go.configure(state="normal", text="Download more")
            self.cancel_btn.configure(text="Close")
            if got:
                self.bar.set(1)
        except Exception:  # noqa: BLE001 - dialog was closed
            pass

    def on_cancel(self):
        if self.running:
            self.cancel_flag = True
            self.msg.configure(text="Stopping after the current image…")
        else:
            self.destroy()


def main():
    if not core.single_instance():
        # Ask the running copy to show its window (it checks for this file every second).
        os.makedirs(core.DATA_DIR, exist_ok=True)
        open(NEXT_FLAG if "--next" in sys.argv else SHOW_FLAG, "w").close()
        return
    if "--next" in sys.argv:          # first launch with --next: start hidden and change once
        os.makedirs(core.DATA_DIR, exist_ok=True)
        open(NEXT_FLAG, "w").close()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    try:
        app = Wallflow(start_hidden="--minimized" in sys.argv or "--next" in sys.argv)
        app.mainloop()
    except Exception:  # noqa: BLE001
        os.makedirs(core.DATA_DIR, exist_ok=True)
        with open(os.path.join(core.DATA_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(time.ctime() + "\n" + traceback.format_exc() + "\n")
        raise


if __name__ == "__main__":
    main()
