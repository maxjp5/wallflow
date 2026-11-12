"""Wallflow — an automatic wallpaper changer for Windows 11.

Double-click to start. Closing the window keeps it running in the tray.
  --autostart   started by Windows (stays hidden if that setting is on)
  --minimized   start hidden in the tray
  --next        change to a new wallpaper (talks to the running copy if there is one)
"""
import os
import sys
import time
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402
from controller import NEXT_FLAG, SHOW_FLAG  # noqa: E402


def resource(name):
    """Path to a bundled file, both from source and inside the packaged exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def build_window(ctl):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from qfluentwidgets import (Action, FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition,
                                NavigationItemPosition, PushButton, SystemTrayMenu)

    from ui_home import HomePage
    from ui_packs import PacksPage
    from ui_settings import SettingsPage
    from ui_sources import SourcesPage

    class MainWindow(FluentWindow):
        def __init__(self):
            super().__init__()
            self.ctl = ctl
            self.quitting = False
            self.setWindowTitle("Wallflow")
            self.setWindowIcon(QIcon(resource("wallflow.ico")))
            self.resize(1180, 800)
            self.setMinimumSize(QSize(900, 620))
            self.navigationInterface.setExpandWidth(200)
            self.setMicaEffectEnabled(ctl.settings.get("mica", True))

            self.home = HomePage(ctl, self)
            self.sources = SourcesPage(ctl, self)
            self.packs = PacksPage(ctl, self)
            self.settings_page = SettingsPage(ctl, self, self)
            self.addSubInterface(self.home, FIF.HOME, "Home")
            self.addSubInterface(self.sources, FIF.GLOBE, "Sources")
            self.addSubInterface(self.packs, FIF.LIBRARY, "Packs")
            self.addSubInterface(self.settings_page, FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)

            ctl.status.connect(self.on_status)
            ctl.show_requested.connect(self.bring_up)
            ctl.update_found.connect(self.on_update)
            self.build_tray()
            self.center()

        def center(self):
            geo = QApplication.primaryScreen().availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        # ---------------------------------------------------- tray
        def build_tray(self):
            self.tray = QSystemTrayIcon(QIcon(resource("wallflow.ico")), self)
            self.tray.setToolTip("Wallflow")
            menu = SystemTrayMenu(parent=self)
            self.pauseAct = Action(FIF.PAUSE, "Pause auto-change", triggered=lambda: ctl.set_running(
                not ctl.settings["running"]))
            menu.addActions([
                Action(FIF.HOME, "Open Wallflow", triggered=self.bring_up),
                Action(FIF.SYNC, "Next wallpaper", triggered=ctl.next_new),
                self.pauseAct,
            ])
            menu.addSeparator()
            menu.addAction(Action(FIF.CLOSE, "Quit", triggered=self.quit_app))
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(
                lambda r: self.bring_up() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
            ctl.running_changed.connect(self.on_running)
            self.on_running(ctl.settings["running"])
            self.tray.show()

        def on_running(self, on):
            self.pauseAct.setText("Pause auto-change" if on else "Resume auto-change")
            self.pauseAct.setIcon(FIF.PAUSE.icon() if on else FIF.PLAY.icon())

        def bring_up(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def closeEvent(self, e):
            if not self.quitting and ctl.settings.get("close_to_tray", True):
                e.ignore()
                self.hide()
            else:
                ctl.save()
                self.tray.hide()
                e.accept()
                QApplication.quit()

        def quit_app(self):
            self.quitting = True
            self.close()

        # ---------------------------------------------------- messages
        def on_status(self, kind, msg):
            if kind == "error" and self.isVisible():
                InfoBar.error("Couldn't get a wallpaper", msg, duration=6000,
                              position=InfoBarPosition.TOP_RIGHT, parent=self)

        def on_update(self, ver, url):
            bar = InfoBar.info(f"Wallflow {ver} is available", "A newer version is on GitHub.",
                               duration=-1, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            btn = PushButton("Download")
            btn.clicked.connect(lambda: webbrowser.open(url))
            bar.addWidget(btn)

    return MainWindow()


def main():
    if not core.single_instance():
        # Hand the request to the running copy (it checks these files every second).
        os.makedirs(core.DATA_DIR, exist_ok=True)
        open(NEXT_FLAG if "--next" in sys.argv else SHOW_FLAG, "w").close()
        return

    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme

    from controller import Controller

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ctl = Controller()
    setTheme({"Light": Theme.LIGHT, "System": Theme.AUTO}.get(ctl.settings.get("theme"), Theme.DARK))
    from theme import AccentManager
    ctl.accent = AccentManager(ctl.settings)
    win = build_window(ctl)

    hidden = ("--minimized" in sys.argv or "--next" in sys.argv
              or ("--autostart" in sys.argv and ctl.settings.get("start_hidden", True)))
    if not hidden:
        win.show()
    from PySide6.QtCore import QTimer
    if "--next" in sys.argv or not ctl.history() or ctl.settings.get("change_on_start"):
        QTimer.singleShot(1200, ctl.next_new)
    if ctl.settings.get("check_updates", True):
        QTimer.singleShot(5000, ctl.check_updates)
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        os.makedirs(core.DATA_DIR, exist_ok=True)
        with open(os.path.join(core.DATA_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(time.ctime() + "\n" + traceback.format_exc() + "\n")
        raise
