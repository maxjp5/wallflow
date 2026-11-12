"""Smooth cross-fade between wallpapers.

Windows has no fade for a one-off wallpaper change, so we make one: a copy of the *current*
wallpaper is placed on the desktop layer (behind icons and windows), the real wallpaper is
switched underneath it, and the copy fades out. Same idea Wallpaper Engine and Lively use.
"""
import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

import core

user32 = ctypes.windll.user32
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_POPUP = 0x40000000, 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x08000000, 0x80
LWA_ALPHA = 0x2
SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x4, 0x10, 0x40
HWND_BOTTOM = 1

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetParent.argtypes = [wt.HWND, wt.HWND]
user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND


def find_desktop_layer():
    """The WorkerW window that sits between the wallpaper and the desktop icons, or None."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None
    result = ctypes.c_size_t()
    user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, 0, 1000, ctypes.byref(result))
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(result))

    # Windows 11 24H2+: the layer is a WorkerW child of Progman.
    child = user32.FindWindowExW(progman, None, "WorkerW", None)
    if child:
        return child
    # Older builds: the top-level WorkerW right after the one that holds the icons.
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            w = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if w:
                found.append(w)
        return True

    user32.EnumWindows(each, 0)
    return found[0] if found else None


def render(img, mon, vbounds, style):
    """Paint the image the way Windows does for this monitor and fit style."""
    out = QImage(mon["w"], mon["h"], QImage.Format_RGB32)
    out.fill(QColor(0, 0, 0))
    if img.isNull():
        return out
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    iw, ih = img.width(), img.height()
    W, H = mon["w"], mon["h"]
    if style == "Span":
        vx, vy, vw, vh = vbounds
        s = max(vw / iw, vh / ih)
        dw, dh = iw * s, ih * s
        x = (vw - dw) / 2 - (mon["x"] - vx)
        y = (vh - dh) / 2 - (mon["y"] - vy)
        p.drawImage(QRectF(x, y, dw, dh), img)
    elif style == "Stretch":
        p.drawImage(QRectF(0, 0, W, H), img)
    elif style == "Fit":
        s = min(W / iw, H / ih)
        p.drawImage(QRectF((W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s), img)
    elif style == "Center":
        p.drawImage(QRectF((W - iw) / 2, (H - ih) / 2, iw, ih), img)
    elif style == "Tile":
        for x in range(0, W, iw):
            for y in range(0, H, ih):
                p.drawImage(x, y, img)
    else:  # Fill
        s = max(W / iw, H / ih)
        p.drawImage(QRectF((W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s), img)
    p.end()
    return out


class _Cover(QWidget):
    def __init__(self, image):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus |
                         Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.image = image

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)


class DesktopFade:
    """cover(old) -> switch the wallpaper -> fade_out()."""

    DURATION = 900

    def __init__(self):
        self.covers = []
        self.ani = None

    def cover(self, old_path, style):
        """Show the current wallpaper on top of the desktop layer. Returns True if it worked."""
        self.finish()
        if not old_path:
            return False
        img = QImage(old_path)
        if img.isNull():
            return False
        layer = find_desktop_layer()
        mons = core.monitors()
        vx = min(m["x"] for m in mons)
        vy = min(m["y"] for m in mons)
        vbounds = (vx, vy, max(m["x"] + m["w"] for m in mons) - vx, max(m["y"] + m["h"] for m in mons) - vy)
        try:
            for m in mons:
                w = _Cover(render(img, m, vbounds, style))
                hwnd = int(w.winId())
                ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                         ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
                if layer:
                    st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
                    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (st & ~WS_POPUP) | WS_CHILD)
                    user32.SetParent(hwnd, layer)
                    x, y = m["x"] - vx, m["y"] - vy          # the layer covers the whole virtual desktop
                    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
                    user32.SetWindowPos(hwnd, None, x, y, m["w"], m["h"], flags)
                else:                                         # no desktop layer: sit at the very bottom
                    user32.SetWindowPos(hwnd, HWND_BOTTOM, m["x"], m["y"], m["w"], m["h"],
                                        SWP_NOACTIVATE | SWP_SHOWWINDOW)
                w.show()
                w.repaint()
                self.covers.append(w)
        except Exception:  # noqa: BLE001 - never let the effect block a wallpaper change
            self.finish()
            return False
        return True

    def fade_out(self):
        if not self.covers:
            return
        self.ani = QVariantAnimation()
        self.ani.setStartValue(255)
        self.ani.setEndValue(0)
        self.ani.setDuration(self.DURATION)
        self.ani.setEasingCurve(QEasingCurve.InOutCubic)
        self.ani.valueChanged.connect(self._alpha)
        self.ani.finished.connect(self.finish)
        QTimer.singleShot(120, self.ani.start)             # let Explorer draw the new wallpaper first

    def _alpha(self, a):
        for w in self.covers:
            try:
                user32.SetLayeredWindowAttributes(int(w.winId()), 0, int(a), LWA_ALPHA)
            except RuntimeError:
                pass

    def finish(self):
        if self.ani:
            self.ani.stop()
            self.ani = None
        for w in self.covers:
            try:
                w.close()
            except RuntimeError:
                pass
        self.covers = []
