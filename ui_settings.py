"""Settings page in the Windows 11 Settings style."""
import os
import webbrowser

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (ComboBox, FluentIcon as FIF, MessageBox, PrimaryPushButton,
                            PushButton, ScrollArea, SettingCard, SettingCardGroup, SubtitleLabel,
                            SwitchButton, Theme, setTheme)

import core
import sources
from theme import ACCENTS, DEFAULT, accent_color


class Swatch(QAbstractButton):
    """Round color swatch that grows on hover and shows a ring when selected."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFixedSize(34, 34)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{name}: {ACCENTS[name][2]}")
        self._grow = 0.0
        self.ani = QPropertyAnimation(self, b"grow", self)
        self.ani.setDuration(150)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)

    def getGrow(self):
        return self._grow

    def setGrow(self, v):
        self._grow = v
        self.update()

    grow = Property(float, getGrow, setGrow)

    def _to(self, v):
        self.ani.stop()
        self.ani.setStartValue(self._grow)
        self.ani.setEndValue(v)
        self.ani.start()

    def enterEvent(self, e):
        self._to(1.0)

    def leaveEvent(self, e):
        self._to(0.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = accent_color(self.name)
        r = 10 + 2 * self._grow
        center = QRectF(self.rect()).center()
        if self.isChecked():
            pen = QPen(c)
            pen.setWidthF(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(center, 15, 15)
        p.setPen(QPen(QColor(128, 128, 128, 90), 1))
        p.setBrush(c)
        p.drawEllipse(center, r, r)

THEMES = {"Dark": Theme.DARK, "Light": Theme.LIGHT, "System": Theme.AUTO}
FITS = ["Fill", "Fit", "Stretch", "Center", "Span"]


class SettingsPage(ScrollArea):
    def __init__(self, ctl, window, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.win = window
        self.setObjectName("settingsPage")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setStyleSheet("#settingsPage,#view{background:transparent;border:none}")
        s = ctl.settings

        lay = QVBoxLayout(self.view)
        lay.setContentsMargins(36, 24, 36, 36)
        lay.setSpacing(24)
        lay.addWidget(SubtitleLabel("Settings", self.view))

        # Wallpaper
        g = self.group("Wallpaper")
        self.add(g, FIF.DATE_TIME, "Change every", "How long each wallpaper stays",
                 self.combo(list(core.INTERVALS), s["interval"], ctl.set_interval))
        self.fit = self.combo(FITS, s["style"], self.on_fit)
        self.add(g, FIF.FIT_PAGE, "Fit on screen",
                 "Span stretches one image across all your screens", self.fit)
        self.add(g, FIF.ZOOM, "Match wallpapers to my screens",
                 "Only picks wallpapers big enough and the right shape, then crops them to your exact resolution",
                 self.switch("match_screens", True, lambda v: self.refresh_screens()))
        self.screens = SettingCard(FIF.TILES, "Your screens", "", self.view)
        btn = PushButton(FIF.SYNC, "Detect again", self.screens)
        btn.clicked.connect(self.refresh_screens)
        self._tail(self.screens, btn)
        g.addSettingCard(self.screens)

        # Startup
        g = self.group("Startup")
        startup = SwitchButton(self.view)
        startup.setChecked(s["start_with_windows"])
        startup.checkedChanged.connect(self.on_startup)
        self.add(g, FIF.POWER_BUTTON, "Start Wallflow when Windows starts",
                 "Launches automatically when you sign in", startup)
        self.add(g, FIF.HIDE, "Start hidden in the tray",
                 "When Windows starts it, Wallflow runs quietly instead of opening the window",
                 self.switch("start_hidden", True))
        self.add(g, FIF.SYNC, "New wallpaper every time Wallflow starts",
                 "A fresh desktop each time you turn on your PC", self.switch("change_on_start", False))

        # Behavior
        g = self.group("Behavior")
        self.add(g, FIF.MINIMIZE, "Keep running in the tray when closed",
                 "Closing the window keeps wallpapers changing", self.switch("close_to_tray", True))
        self.add(g, FIF.GAME, "Pause while gaming or in full screen",
                 "Waits until you leave a game, full-screen video or presentation",
                 self.switch("pause_fullscreen", True))
        self.add(g, FIF.SPEED_OFF, "Pause on battery power", "Picks up again when you plug in",
                 self.switch("pause_on_battery", False))

        # Appearance
        g = self.group("Appearance")
        self.add(g, FIF.BRUSH, "Theme", "How the Wallflow window looks",
                 self.combo(list(THEMES), s.get("theme", "Dark"), self.on_theme))
        self.accentCard = SettingCard(FIF.PALETTE, "Accent color", "", self.view)
        row = QWidget(self.accentCard)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self.swatches = []
        for name in ACCENTS:
            sw = Swatch(name, row)
            sw.clicked.connect(lambda _=False, n=name: self.on_accent(n))
            rl.addWidget(sw)
            self.swatches.append(sw)
        self._tail(self.accentCard, row)
        g.addSettingCard(self.accentCard)
        self.mark_accent()
        self.add(g, FIF.TRANSPARENT, "Window transparency",
                 "Lets your wallpaper tint the window background (Windows 11 Mica)",
                 self.switch("mica", True, lambda v: self.win.setMicaEffectEnabled(v)))

        # Storage
        g = self.group("History and storage")
        self.add(g, FIF.HISTORY, "Wallpapers to keep in history",
                 "Older ones are deleted automatically. Favorites and packs are never touched",
                 self.combo(["20", "40", "100", "200"], str(s.get("keep_history", 40)),
                            lambda v: (ctl.set_keep(int(v)), self.refresh_storage())))
        self.storage = SettingCard(FIF.DELETE, "Clear history", "", self.view)
        clear = PushButton("Clear history", self.storage)
        clear.clicked.connect(self.on_clear)
        self._tail(self.storage, clear)
        g.addSettingCard(self.storage)
        for icon, title, content, path in (
                (FIF.FOLDER, "Data folder", "Settings, cache and your original-wallpaper backup", core.DATA_DIR),
                (FIF.HEART, "Favorites folder", "Wallpapers you saved with the heart button", core.FAVORITES_DIR),
                (FIF.LIBRARY, "Packs folder", "Offline packs you downloaded", core.PACKS_DIR)):
            b = PushButton("Open", self.view)
            b.clicked.connect(lambda _=False, p=path: (os.makedirs(p, exist_ok=True), os.startfile(p)))
            self.add(g, icon, title, content, b)
        restore = PushButton("Restore", self.view)
        restore.clicked.connect(self.on_restore)
        self.add(g, FIF.RETURN, "Restore my original wallpaper",
                 "Puts back the wallpaper you had before Wallflow and pauses auto-change", restore)

        # About
        g = self.group("About")
        self.about = SettingCard(FIF.INFO, f"Wallflow {core.VERSION}", "Automatic wallpaper changer for Windows",
                                 self.view)
        gh = PushButton(FIF.GITHUB, "GitHub", self.about)
        gh.clicked.connect(lambda: webbrowser.open(f"https://github.com/{core.GITHUB_REPO}"))
        self.updBtn = PrimaryPushButton(FIF.UPDATE, "Check for updates", self.about)
        self.updBtn.clicked.connect(self.on_check)
        self.about.hBoxLayout.addWidget(gh, 0, Qt.AlignRight)
        self.about.hBoxLayout.addSpacing(8)
        self._tail(self.about, self.updBtn)
        g.addSettingCard(self.about)
        self.add(g, FIF.SYNC, "Check for updates automatically",
                 "Looks for a new version on GitHub when Wallflow starts. Nothing downloads on its own",
                 self.switch("check_updates", True))
        ctl.update_result.connect(self.on_update_result)

        lay.addStretch(1)
        ctl.history_changed.connect(self.refresh_storage)
        self.refresh_screens()
        self.refresh_storage()

    # ---------------------------------------------------------- helpers

    def group(self, title):
        g = SettingCardGroup(title, self.view)
        self.view.layout().addWidget(g)
        return g

    def _tail(self, card, widget):
        card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
        card.hBoxLayout.addSpacing(16)

    def add(self, group, icon, title, content, widget):
        card = SettingCard(icon, title, content, self.view)
        widget.setParent(card)
        self._tail(card, widget)
        group.addSettingCard(card)
        return card

    def switch(self, key, default, after=None):
        sw = SwitchButton(self.view)
        sw.setChecked(bool(self.ctl.settings.get(key, default)))

        def changed(v):
            self.ctl.set_option(key, v)
            if after:
                after(v)
        sw.checkedChanged.connect(changed)
        return sw

    def combo(self, items, current, on_change):
        c = ComboBox(self.view)
        c.addItems(items)
        c.setCurrentText(current)
        c.setMinimumWidth(150)
        c.currentTextChanged.connect(on_change)
        return c

    # ---------------------------------------------------------- actions

    def on_fit(self, v):
        self.ctl.set_style(v)
        self.refresh_screens()

    def on_theme(self, v):
        self.ctl.set_option("theme", v)
        setTheme(THEMES[v], lazy=True)
        for sw in self.swatches:
            sw.update()

    def on_accent(self, name):
        self.ctl.accent.set(name)
        self.ctl.save()
        self.mark_accent()

    def mark_accent(self):
        cur = self.ctl.settings.get("accent", DEFAULT)
        for sw in self.swatches:
            sw.setChecked(sw.name == cur)
            sw.update()
        self.accentCard.setContent(f"{cur}: {ACCENTS.get(cur, ACCENTS[DEFAULT])[2]}")

    def on_startup(self, v):
        try:
            core.set_startup(v)
            self.ctl.set_option("start_with_windows", v)
        except OSError as e:
            MessageBox("Couldn't change startup", str(e), self.window()).exec()

    def refresh_screens(self):
        mons = core.monitors()
        parts = [f"{m['w']} × {m['h']}{' (main)' if m['primary'] else ''}" for m in mons]
        tw, th = core.target_size(self.ctl.settings, mons)
        if not self.ctl.settings.get("match_screens", True):
            tail = "matching is off"
        elif self.ctl.settings.get("style") == "Span" and len(mons) > 1:
            tail = f"wallpapers are {tw} × {th}, one image across all screens"
        else:
            tail = f"wallpapers are cropped to {tw} × {th} ({sources.nearest_ratio(tw, th).replace('x', ':')})"
        self.screens.setTitle(f"Your screens · {len(mons)} detected")
        self.screens.setContent(f"{', '.join(parts)} — {tail}")

    def refresh_storage(self):
        n = len(self.ctl.history())
        mb = core.folder_size(core.CACHE_DIR) / 1024 / 1024
        self.storage.setContent(f"{n} wallpapers in history, using {mb:.0f} MB. Your current wallpaper is kept")

    def on_clear(self):
        box = MessageBox("Clear history?", "Your current wallpaper, favorites and packs are kept.", self.window())
        box.yesButton.setText("Clear history")
        box.cancelButton.setText("Cancel")
        if box.exec():
            self.ctl.clear_history()
            self.refresh_storage()

    def on_restore(self):
        box = MessageBox("Restore your original wallpaper?",
                         "Auto-change will be paused. You can turn it back on from Home.", self.window())
        box.yesButton.setText("Restore")
        box.cancelButton.setText("Cancel")
        if box.exec():
            try:
                self.ctl.restore_original()
            except Exception as e:  # noqa: BLE001
                MessageBox("Couldn't restore", str(e), self.window()).exec()

    def on_check(self):
        self.updBtn.setEnabled(False)
        self.updBtn.setText("Checking…")
        self.ctl.check_updates()

    def on_update_result(self, kind, value, url):
        self.updBtn.setEnabled(True)
        self.updBtn.setText("Check for updates")
        if kind == "new":
            self.about.setContent(f"Wallflow {value} is available")
        elif kind == "latest":
            self.about.setContent("You're on the latest version")
        else:
            self.about.setContent(f"Couldn't check: {value}")
