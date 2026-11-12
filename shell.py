"""Behavior shared by both designs: tray icon, close-to-tray, messages, restart."""
import os
import subprocess
import sys
import webbrowser

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import (Action, FluentIcon as FIF, InfoBar, InfoBarPosition, PushButton,
                            SystemTrayMenu)

import core

DESIGNS = ["Windows 11", "Liquid Glass"]


def resource(name):
    """Path to a bundled file, both from source and inside the packaged exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def restart_app(ctl):
    """Start a fresh copy (which opens in the newly chosen design) and quit this one."""
    ctl.save()
    core.release_instance()
    subprocess.Popen(core.relaunch_command(), close_fds=True)
    QApplication.quit()


class ShellMixin:
    """Mix into a top-level window class. Call setup_shell(ctl) at the end of __init__."""

    def setup_shell(self, ctl):
        self.ctl = ctl
        self.quitting = False
        ctl.status.connect(self.on_status)
        ctl.show_requested.connect(self.bring_up)
        ctl.quit_requested.connect(self.quit_app)
        ctl.update_found.connect(self.on_update)
        ctl.restart = lambda: restart_app(ctl)
        self.build_tray()

    def build_tray(self):
        ctl = self.ctl
        self.tray = QSystemTrayIcon(QIcon(resource("wallflow.ico")), self)
        self.tray.setToolTip("Wallflow")
        menu = SystemTrayMenu(parent=self)
        self.pauseAct = Action(FIF.PAUSE, "Pause auto-change",
                               triggered=lambda: ctl.set_running(not ctl.settings["running"]))
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

    def center(self):
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def bring_up(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not self.quitting and self.ctl.settings.get("close_to_tray", True):
            e.ignore()
            self.hide()
        else:
            self.ctl.save()
            self.tray.hide()
            e.accept()
            QApplication.quit()

    def quit_app(self):
        self.quitting = True
        self.close()

    def on_status(self, kind, msg):
        if not self.isVisible():
            return
        if kind == "error":
            InfoBar.error("Something went wrong", msg, duration=6000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def on_update(self, ver, url):
        bar = InfoBar.info(f"Wallflow {ver} is available", "A newer version is on GitHub.",
                           duration=-1, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        btn = PushButton("Download")
        btn.clicked.connect(lambda: webbrowser.open(url))
        bar.addWidget(btn)
