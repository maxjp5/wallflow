"""Favorite feedback that matches the design: a Fluent flyout in Windows 11, a frosted toast in
Liquid Glass. Both also 'pop' the heart so the click feels alive."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, QTimer
from qfluentwidgets import Flyout, FlyoutAnimationType

_live = []      # keep animations alive until they finish


def pop(button):
    """Briefly grow the button's icon and settle back (a small bounce)."""
    if hasattr(button, "pop"):                       # glass buttons animate themselves
        button.pop()
        return
    size = button.iconSize()
    ani = QPropertyAnimation(button, b"iconSize", button)
    ani.setDuration(420)
    ani.setKeyValueAt(0.0, size)
    ani.setKeyValueAt(0.35, QSize(int(size.width() * 1.45), int(size.height() * 1.45)))
    ani.setKeyValueAt(1.0, size)
    ani.setEasingCurve(QEasingCurve.OutCubic)
    _live.append(ani)
    ani.finished.connect(lambda: _live.remove(ani) if ani in _live else None)
    ani.start()


def favorite_feedback(button, saved):
    from ui_home import heart_icon
    try:
        win = button.window()
    except RuntimeError:
        return
    pop(button)
    if hasattr(win, "glass_toast"):
        win.glass_toast(saved)
        return
    if not saved:
        return
    fly = Flyout.create(title="Saved to favorites", content="It's on your Favorites page now.",
                        icon=heart_icon(True), target=button, parent=win,
                        aniType=FlyoutAnimationType.PULL_UP)

    def close():
        try:
            fly.fadeOut()
        except RuntimeError:
            pass
    QTimer.singleShot(1700, close)
