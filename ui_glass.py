"""Liquid Glass design: the window *is* your wallpaper, with frosted floating panels on top.

The frost is real: each panel draws a blurred copy of the wallpaper behind it, tinted white,
so it looks like glass. Wallpaper changes cross-fade, panels slide and fade, buttons grow on hover.
"""
import time

from PIL import Image, ImageFilter
from PySide6.QtCore import (Property, QEasingCurve, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QIcon, QImage, QImageReader, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QStackedWidget, QVBoxLayout, QWidget)
from qfluentwidgets import FluentIcon as FIF

import core
from shell import ShellMixin, resource
from ui_home import FavoritesPage, Gallery, Page, heart_icon
from ui_packs import PacksPage
from ui_settings import SettingsPage
from ui_sources import SourcesPage

WHITE = QColor(255, 255, 255)
EDGE = 6          # px from the window edge that resizes it


def _cover_rect(iw, ih, W, H):
    s = max(W / iw, H / ih)
    return QRectF((W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s)


def _load(path):
    """(sharp QImage, blurred QImage) for the window background and the glass."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 2400:
        reader.setScaledSize(QSize(2400, round(size.height() * 2400 / size.width())))
    sharp = reader.read()
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((720, 720))
        im = im.filter(ImageFilter.GaussianBlur(22))
        blur = QImage(im.tobytes("raw", "RGB"), im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()
    except Exception:  # noqa: BLE001
        blur = sharp.scaledToWidth(200, Qt.SmoothTransformation) if not sharp.isNull() else QImage()
    return sharp, blur


class GlassPanel(QWidget):
    """A frosted rounded panel: blurred wallpaper behind it + a light tint + a hairline edge."""

    def __init__(self, win, radius=22, tint=QColor(255, 255, 255, 40), parent=None):
        super().__init__(parent or win)
        self.win = win
        self.radius = radius
        self.tint = tint

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.save()
        p.setClipPath(path)
        off = self.mapTo(self.win, QPoint(0, 0))
        p.translate(-off.x(), -off.y())
        self.win.draw_background(p, blurred=True)
        p.restore()
        p.fillPath(path, self.tint)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        p.drawPath(path)


class GlassButton(QAbstractButton):
    """Round glass button that grows on hover; solid white when selected."""

    def __init__(self, icon, tip="", size=40, parent=None):
        super().__init__(parent)
        self.fluent = icon
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.solid = False
        self._grow = 0.0
        self._pop = 0.0
        self.ani = QPropertyAnimation(self, b"grow", self)
        self.ani.setDuration(160)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)
        self.popAni = QPropertyAnimation(self, b"popv", self)
        self.popAni.setDuration(460)
        self.popAni.setKeyValueAt(0.0, 0.0)
        self.popAni.setKeyValueAt(0.35, 1.0)
        self.popAni.setKeyValueAt(1.0, 0.0)
        self.popAni.setEasingCurve(QEasingCurve.OutCubic)

    def getPop(self):
        return self._pop

    def setPop(self, v):
        self._pop = v
        self.update()

    popv = Property(float, getPop, setPop)

    def pop(self):
        self.popAni.stop()
        self.popAni.start()

    def setGlyph(self, icon):
        self.fluent = icon
        self.update()

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
        c = QRectF(self.rect()).center()
        rad = self.width() / 2 - 3 + 2.5 * self._grow
        on = self.isChecked() or self.solid
        p.setPen(QPen(QColor(255, 255, 255, 0 if on else 70), 1))
        p.setBrush(WHITE if on else QColor(255, 255, 255, int(46 + 34 * self._grow)))
        p.drawEllipse(c, rad, rad)
        s = int(self.width() * 0.42 * (1 + 0.45 * self._pop))
        icon = self.fluent if isinstance(self.fluent, QIcon) else self.fluent.icon(
            color=QColor(20, 20, 24) if on else WHITE)
        icon.paint(p, QRect(int(c.x() - s / 2), int(c.y() - s / 2), s, s))


class Ring(QWidget):
    """Countdown ring: fills up as the current wallpaper's time runs out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 46)
        self.frac = 0.0

    def set(self, frac):
        self.frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, 38, 38)
        p.setPen(QPen(QColor(255, 255, 255, 60), 4))
        p.drawEllipse(r)
        pen = QPen(WHITE, 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, -int(360 * 16 * self.frac))


class GlassToast(GlassPanel):
    """Frosted pill that floats up above the player bar, then fades away."""

    def __init__(self, win):
        super().__init__(win, radius=22, tint=QColor(255, 255, 255, 52))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 18, 8)
        lay.setSpacing(10)
        self.icon = QLabel(self)
        self.icon.setFixedSize(20, 20)
        self.text = _label("", 14, True, parent=self)
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.hide()
        self.group = None
        self.timer = None

    def show_message(self, text, icon, anchor):
        """anchor: QRect (window coords) the toast floats above."""
        from PySide6.QtCore import QTimer
        self.text.setText(text)
        self.icon.setPixmap(icon.pixmap(20, 20))
        self.adjustSize()
        end = QPoint(anchor.center().x() - self.width() // 2, anchor.top() - self.height() - 12)
        if self.group:
            self.group.stop()
        if self.timer:
            self.timer.stop()
        self.move(end + QPoint(0, 14))
        self.fx.setOpacity(0.0)
        self.show()
        self.raise_()
        self.group = _fade_move(self, self.fx, end, 1.0, 300)
        self.timer = QTimer(self, singleShot=True, interval=1500)
        self.timer.timeout.connect(lambda: self._out(end))
        self.timer.start()

    def _out(self, end):
        self.group = _fade_move(self, self.fx, end + QPoint(0, -10), 0.0, 380)
        self.group.finished.connect(self.hide)


class GlassMenuItem(QAbstractButton):
    def __init__(self, text, checked, parent=None):
        super().__init__(parent)
        self.label = text
        self.on = checked
        self.setFixedHeight(36)
        self.setMinimumWidth(190)
        self.setCursor(Qt.PointingHandCursor)
        self._h = 0.0
        self.ani = QPropertyAnimation(self, b"hv", self)
        self.ani.setDuration(140)

    def getH(self):
        return self._h

    def setH(self, v):
        self._h = v
        self.update()

    hv = Property(float, getH, setH)

    def enterEvent(self, e):
        self.ani.stop()
        self.ani.setEndValue(1.0)
        self.ani.start()

    def leaveEvent(self, e):
        self.ani.stop()
        self.ani.setEndValue(0.0)
        self.ani.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if self.on:
            p.setBrush(QColor(255, 255, 255, 235))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 12, 12)
        elif self._h > 0:
            p.setBrush(QColor(255, 255, 255, int(46 * self._h)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 12, 12)
        p.setPen(QColor(20, 20, 24) if self.on else WHITE)
        f = p.font()
        f.setPixelSize(13)
        f.setBold(self.on)
        p.setFont(f)
        p.drawText(r.adjusted(14, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.label)


class GlassMenu(GlassPanel):
    """Frosted pop-up list. Click outside or pick an item to close."""

    def __init__(self, win, items, current, on_pick):
        super().__init__(win, radius=20, tint=QColor(30, 30, 36, 120))
        self.win = win
        self.catcher = QWidget(win)                     # invisible layer that closes the menu
        self.catcher.setGeometry(win.rect())
        self.catcher.mousePressEvent = lambda e: self.close_menu()
        self.catcher.show()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(2)
        head = _label("Change wallpaper", 11, alpha=170, parent=self)
        head.setContentsMargins(12, 0, 0, 4)
        lay.addWidget(head)
        for value, text in items:
            it = GlassMenuItem(text, value == current, self)
            it.clicked.connect(lambda _=False, v=value: (on_pick(v), self.close_menu()))
            lay.addWidget(it)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.adjustSize()
        self.group = None

    def open_above(self, anchor):
        end = QPoint(min(anchor.right() - self.width() + 20, self.win.width() - self.width() - 12),
                     anchor.top() - self.height() - 10)
        self.move(end + QPoint(0, 12))
        self.fx.setOpacity(0.0)
        self.show()
        self.raise_()
        self.group = _fade_move(self, self.fx, end, 1.0, 240)

    def close_menu(self):
        self.catcher.deleteLater()
        self.group = _fade_move(self, self.fx, self.pos() + QPoint(0, 8), 0.0, 180)
        self.group.finished.connect(self.deleteLater)


def _fade_move(widget, fx, end, opacity, ms):
    group = QParallelAnimationGroup(widget)
    a = QPropertyAnimation(fx, b"opacity", widget)
    a.setDuration(ms)
    a.setEndValue(opacity)
    m = QPropertyAnimation(widget, b"pos", widget)
    m.setDuration(ms)
    m.setEasingCurve(QEasingCurve.OutCubic)
    m.setEndValue(end)
    group.addAnimation(a)
    group.addAnimation(m)
    group.start()
    return group


def _label(text, size, bold=False, alpha=255, parent=None):
    lab = QLabel(text, parent)
    lab.setStyleSheet(f"color: rgba(255,255,255,{alpha}); font-size: {size}px; "
                      f"font-weight: {600 if bold else 400}; background: transparent;")
    return lab


class RecentPage(Page):
    def __init__(self, ctl, parent=None):
        super().__init__("recentPage", parent)
        from qfluentwidgets import SubtitleLabel
        self.ctl = ctl
        self.lay.addWidget(SubtitleLabel("Recent", self.view))
        self.gallery = Gallery(parent=self.view)
        self.gallery.clicked.connect(ctl.pick)
        self.gallery.heart.connect(lambda i: self.gallery.toggle(ctl, ctl.history()[i], i))
        self.gallery.info.connect(ctl.open_page)
        self.lay.addWidget(self.gallery)
        self.lay.addStretch(1)
        ctl.history_changed.connect(lambda: self.gallery.set_entries(ctl.history(), ctl.pos))
        ctl.current_changed.connect(lambda: self.gallery.mark(ctl.pos))
        ctl.favorites_changed.connect(lambda: self.gallery.refresh_hearts(ctl.history()))
        self.gallery.set_entries(ctl.history(), ctl.pos)


class GlassWindow(ShellMixin, QWidget):
    def __init__(self, ctl):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Wallflow")
        self.setWindowIcon(QIcon(resource("wallflow.ico")))
        self.setMouseTracking(True)
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.ctl = ctl

        self.sharp = [QImage(), QImage()]      # [old, new]
        self.blur = [QImage(), QImage()]
        self._blend = 1.0
        self.fade = QPropertyAnimation(self, b"blend", self)
        self.fade.setDuration(700)
        self.fade.setEasingCurve(QEasingCurve.InOutCubic)

        # Left: navigation
        self.nav = GlassPanel(self, radius=26)
        nl = QVBoxLayout(self.nav)
        nl.setContentsMargins(6, 6, 6, 6)
        nl.setSpacing(6)
        self.navButtons = {}
        for key, icon, tip in (("home", FIF.HOME, "Home"), ("recent", FIF.HISTORY, "Recent"),
                               ("favorites", FIF.HEART, "Favorites"), ("sources", FIF.GLOBE, "Sources"),
                               ("packs", FIF.LIBRARY, "Packs"), ("settings", FIF.SETTING, "Settings")):
            b = GlassButton(icon, tip, 42, self.nav)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            nl.addWidget(b)
            self.navButtons[key] = b

        # Top right: window buttons
        self.winBar = GlassPanel(self, radius=20)
        wl = QHBoxLayout(self.winBar)
        wl.setContentsMargins(4, 4, 4, 4)
        wl.setSpacing(4)
        for icon, tip, slot in ((FIF.MINIMIZE, "Minimize", self.showMinimized),
                                (FIF.FULL_SCREEN, "Maximize", self.toggle_max),
                                (FIF.CLOSE, "Close", self.close)):
            b = GlassButton(icon, tip, 32, self.winBar)
            b.clicked.connect(slot)
            wl.addWidget(b)

        # Bottom: now playing
        self.bar = GlassPanel(self, radius=26)
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(12)
        self.ring = Ring(self.bar)
        bl.addWidget(self.ring)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = _label("", 15, True, parent=self.bar)
        self.sub = _label("", 12, alpha=215, parent=self.bar)
        text.addStretch(1)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        text.addStretch(1)
        bl.addLayout(text, 1)
        self.prevBtn = GlassButton(FIF.LEFT_ARROW, "Previous", 40, self.bar)
        self.prevBtn.clicked.connect(ctl.previous)
        self.pauseBtn = GlassButton(FIF.PAUSE, "Pause auto-change", 40, self.bar)
        self.pauseBtn.clicked.connect(lambda: ctl.set_running(not ctl.settings["running"]))
        self.nextBtn = GlassButton(FIF.RIGHT_ARROW, "Next wallpaper", 48, self.bar)
        self.nextBtn.solid = True
        self.nextBtn.clicked.connect(ctl.forward)
        self.heartBtn = GlassButton(heart_icon(False), "Save to favorites", 40, self.bar)
        self.heartBtn.clicked.connect(self.on_heart)
        self.timeBtn = GlassButton(FIF.STOP_WATCH, "How often it changes", 40, self.bar)
        self.timeBtn.clicked.connect(self.interval_menu)
        self.darkBtn = GlassButton(FIF.QUIET_HOURS, "", 40, self.bar)
        self.darkBtn.setCheckable(True)
        self.darkBtn.setChecked(bool(ctl.settings.get("dark_enabled")))
        self.darkBtn.clicked.connect(lambda: ctl.set_dark_enabled(self.darkBtn.isChecked()))
        ctl.dark_changed.connect(self.on_dark)
        self.on_dark(bool(ctl.settings.get("dark_enabled")))
        for b in (self.prevBtn, self.pauseBtn, self.nextBtn, self.heartBtn, self.darkBtn, self.timeBtn):
            bl.addWidget(b)

        # Bottom left: where this wallpaper came from
        self.infoBtn = GlassButton(FIF.INFO, "Open source page", 36, self)
        self.infoBtn.clicked.connect(lambda: ctl.open_page())

        # Center: a frosted sheet that holds the other pages
        self.sheet = GlassPanel(self, radius=24, tint=QColor(16, 16, 20, 150))
        sl = QVBoxLayout(self.sheet)
        sl.setContentsMargins(4, 8, 4, 8)
        self.stack = QStackedWidget(self.sheet)
        self.stack.setStyleSheet("QStackedWidget{background:transparent}")
        sl.addWidget(self.stack)
        self.pages = {
            "recent": RecentPage(ctl, self.stack),
            "favorites": FavoritesPage(ctl, self.stack),
            "sources": SourcesPage(ctl, self.stack),
            "packs": PacksPage(ctl, self.stack),
            "settings": SettingsPage(ctl, self, self.stack),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.toast = GlassToast(self)
        self.sheetFx = QGraphicsOpacityEffect(self.sheet)
        self.sheet.setGraphicsEffect(self.sheetFx)
        self.sheet.hide()
        self.sheetAni = None

        ctl.current_changed.connect(self.on_current)
        ctl.favorites_changed.connect(self.refresh_heart)
        ctl.tick.connect(self.on_tick)
        ctl.busy_changed.connect(self.on_busy)
        ctl.running_changed.connect(lambda on: self.pauseBtn.setGlyph(FIF.PAUSE if on else FIF.PLAY))
        ctl.status.connect(lambda k, m: self.sub.setText(m) if ctl.busy and k == "info" else None)
        self.pauseBtn.setGlyph(FIF.PAUSE if ctl.settings["running"] else FIF.PLAY)
        self.on_current(animate=False)
        self.go("home", animate=False)
        self.setup_shell(ctl)
        self.center()

    # ------------------------------------------------------------ background
    def getBlend(self):
        return self._blend

    def setBlend(self, v):
        self._blend = v
        self.update()
        for w in (self.nav, self.bar, self.winBar, self.sheet):
            w.update()

    blend = Property(float, getBlend, setBlend)

    def draw_background(self, p, blurred=False):
        imgs = self.blur if blurred else self.sharp
        W, H = self.width(), self.height()
        old, new = imgs
        if self._blend < 1 and not old.isNull():          # old underneath, new fades in on top
            p.drawImage(_cover_rect(old.width(), old.height(), W, H), old)
            p.setOpacity(self._blend)
        if not new.isNull():
            p.drawImage(_cover_rect(new.width(), new.height(), W, H), new)
        p.setOpacity(1)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        radius = 0 if self.isMaximized() else 12
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(18, 18, 22))
        self.draw_background(p)
        g = QLinearGradient(0, self.height() * 0.55, 0, self.height())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 110))
        p.fillRect(self.rect(), g)

    def on_current(self, animate=True):
        e = self.ctl.current()
        if e:
            sharp, blur = _load(e["path"])
            self.sharp = [self.sharp[1], sharp]
            self.blur = [self.blur[1], blur]
            self.title.setText(_elide(e.get("title") or "Untitled", 60))
            when = time.strftime("%b %d, %I:%M %p", time.localtime(e.get("time", time.time())))
            self.base_sub = f"{self.ctl.source_label(e['source'])}  ·  {when}"
            self.sub.setText(self.base_sub)
            self.infoBtn.setToolTip(f"Open source: {self.ctl.source_label(e['source'])}")
        self.infoBtn.setVisible(bool(e and e.get("page")))
        self.refresh_heart()
        self.fade.stop()
        if animate:
            self.fade.setStartValue(0.0)
            self.fade.setEndValue(1.0)
            self.fade.start()
        else:
            self.setBlend(1.0)

    def refresh_heart(self):
        fav = core.is_favorite(self.ctl.current())
        self.heartBtn.setGlyph(heart_icon(fav))
        self.heartBtn.setToolTip("Remove from favorites" if fav else "Save to favorites")

    def on_tick(self, left, frac, why):
        if self.ctl.busy:
            return
        self.ring.set(frac)
        base = getattr(self, "base_sub", "")
        if why:
            self.sub.setText(f"{base}  ·  {why}" if base else why)
        else:
            h, rem = divmod(left, 3600)
            m, s = divmod(rem, 60)
            t = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            dark = "  ·  dark only" if self.ctl.dark_active() else ""
            self.sub.setText(f"{base}  ·  next in {t}{dark}")

    def on_dark(self, on):
        self.darkBtn.setChecked(on)
        self.darkBtn.setToolTip("Dark wallpapers: on. Click to turn off" if on else "Dark wallpapers: off. Click so night never gets a bright wallpaper")
        self.darkBtn.pop()

    def on_busy(self, busy):
        self.nextBtn.setEnabled(not busy)
        if busy:
            self.sub.setText("Finding a new wallpaper…")

    def interval_menu(self):
        items = [(k, k if k == core.NO_ROTATE else f"Every {k}") for k in core.INTERVALS]
        menu = GlassMenu(self, items, self.ctl.settings["interval"], self.ctl.set_interval)
        anchor = QRect(self.timeBtn.mapTo(self, QPoint(0, 0)), self.timeBtn.size())
        menu.open_above(anchor)

    def on_heart(self):
        from ui_feedback import favorite_feedback
        saved = self.ctl.toggle_favorite(self.ctl.current())
        if saved is not None:
            favorite_feedback(self.heartBtn, saved)

    def glass_toast(self, saved):
        self.toast.show_message("Saved to favorites" if saved else "Removed from favorites",
                                heart_icon(saved), self.bar.geometry())

    # ------------------------------------------------------------ pages
    def go(self, key, animate=True):
        for k, b in self.navButtons.items():
            b.setChecked(k == key)
        if key == "home":
            self._sheet(False, animate)
        else:
            self.stack.setCurrentWidget(self.pages[key])
            self._sheet(True, animate)

    def _sheet(self, show, animate):
        if self.sheetAni:
            self.sheetAni.stop()
        end = self.sheet_geometry()
        if not animate:
            self.sheet.setGeometry(end)
            self.sheetFx.setOpacity(1.0 if show else 0.0)
            self.sheet.setVisible(show)
            return
        if show and not self.sheet.isVisible():
            self.sheet.setGeometry(end.translated(0, 24))
            self.sheetFx.setOpacity(0.0)
            self.sheet.show()
        if not show and not self.sheet.isVisible():
            return
        group = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self.sheetFx, b"opacity", self)
        a.setDuration(260)
        a.setEndValue(1.0 if show else 0.0)
        g = QPropertyAnimation(self.sheet, b"geometry", self)
        g.setDuration(320)
        g.setEasingCurve(QEasingCurve.OutCubic)
        g.setEndValue(end if show else end.translated(0, 24))
        group.addAnimation(a)
        group.addAnimation(g)
        if not show:
            group.finished.connect(self.sheet.hide)
        self.sheetAni = group
        group.start()

    def sheet_geometry(self):
        left = self.nav.geometry().right() + 16
        top = self.winBar.geometry().bottom() + 12          # below the window buttons
        bottom = self.bar.geometry().top() - 14
        return QRect(left, top, self.width() - left - 16, max(200, bottom - top))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        W, H = self.width(), self.height()
        self.nav.adjustSize()
        self.nav.move(16, max(16, (H - 110 - self.nav.height()) // 2))
        self.winBar.adjustSize()
        self.winBar.move(W - self.winBar.width() - 16, 16)
        bw = min(860, W - 2 * 96)
        self.bar.setGeometry((W - bw) // 2 + 30, H - 92, bw, 72)
        self.infoBtn.move(22, H - 22 - self.infoBtn.height())
        if self.sheet.isVisible():
            self.sheet.setGeometry(self.sheet_geometry())
        self.winBar.raise_()

    def setMicaEffectEnabled(self, on):     # Settings calls this; glass has its own look
        pass

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # ------------------------------------------------------------ move and resize (frameless)
    def _edges(self, pos):
        if self.isMaximized():
            return Qt.Edges()
        r = self.rect()
        edges = Qt.Edges()
        if pos.x() <= EDGE:
            edges |= Qt.LeftEdge
        if pos.x() >= r.width() - EDGE:
            edges |= Qt.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.TopEdge
        if pos.y() >= r.height() - EDGE:
            edges |= Qt.BottomEdge
        return edges

    def mouseMoveEvent(self, e):
        edges = self._edges(e.position().toPoint())
        cursors = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
                   Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor,
                   Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor, Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
                   Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor, Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor}
        self.setCursor(cursors.get(edges, Qt.ArrowCursor))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        edges = self._edges(pos)
        if edges:
            self.windowHandle().startSystemResize(edges)
        elif self._is_drag_area(pos):
            self.windowHandle().startSystemMove()

    def _is_drag_area(self, pos):
        """Drag only from the wallpaper itself or a glass panel's own background,
        never from content inside a page (tiles, lists, text)."""
        w = self.childAt(pos)
        return w is None or w in (self.nav, self.bar, self.winBar)

    def mouseDoubleClickEvent(self, e):
        if self._is_drag_area(e.position().toPoint()):
            self.toggle_max()


def _elide(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"
