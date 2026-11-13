"""Wallflow: an automatic wallpaper changer for Windows 11.

Double-click to start. Closing the window keeps it running in the tray.
  --autostart   started by Windows (stays hidden if that setting is on)
  --minimized   start hidden in the tray
  --next        change to a new wallpaper (talks to the running copy if there is one)
  --quit        close the running copy cleanly (used by the installer)
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402
from controller import NEXT_FLAG, QUIT_FLAG, SHOW_FLAG  # noqa: E402


def build_window(ctl):
    """Create the window for the design chosen in Settings (Windows 11 or Liquid Glass)."""
    if ctl.settings.get("design") == "Liquid Glass":
        from ui_glass import GlassWindow
        return GlassWindow(ctl)

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from qfluentwidgets import FluentIcon as FIF, FluentWindow, NavigationItemPosition

    from shell import ShellMixin, resource
    from ui_home import FavoritesPage, HomePage
    from ui_packs import PacksPage
    from ui_settings import SettingsPage
    from ui_sources import SourcesPage

    class MainWindow(ShellMixin, FluentWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Wallflow")
            self.setWindowIcon(QIcon(resource("wallflow.ico")))
            self.resize(1180, 800)
            self.setMinimumSize(QSize(900, 620))
            self.navigationInterface.setExpandWidth(200)
            self.setMicaEffectEnabled(ctl.settings.get("mica", True))

            self.home = HomePage(ctl, self)
            self.favorites = FavoritesPage(ctl, self)
            self.sources = SourcesPage(ctl, self)
            self.packs = PacksPage(ctl, self)
            self.settings_page = SettingsPage(ctl, self, self)
            self.addSubInterface(self.home, FIF.HOME, "Home")
            self.addSubInterface(self.favorites, FIF.HEART, "Favorites")
            self.addSubInterface(self.sources, FIF.GLOBE, "Sources")
            self.addSubInterface(self.packs, FIF.LIBRARY, "Packs")
            self.addSubInterface(self.settings_page, FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)
            self.setup_shell(ctl)
            self.center()

    return MainWindow()


def main():
    if "--quit" in sys.argv:
        if not core.single_instance():                 # a copy is running: ask it to close
            os.makedirs(core.DATA_DIR, exist_ok=True)
            open(QUIT_FLAG, "w").close()
            for _ in range(50):                         # wait up to 5 s for it to exit
                time.sleep(0.1)
                if not os.path.exists(QUIT_FLAG):
                    break
            time.sleep(0.5)
        return
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
    from desktop_fade import DesktopFade
    ctl.fader = DesktopFade()
    theme = {"Light": Theme.LIGHT, "System": Theme.AUTO}.get(ctl.settings.get("theme"), Theme.DARK)
    if ctl.settings.get("design") == "Liquid Glass":
        theme = Theme.DARK                      # white text reads best on glass
    setTheme(theme)
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
