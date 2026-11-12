"""Home and Favorites pages: now-showing card with progress bar, and animated galleries."""
import os
import time

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FlowLayout, FluentIcon as FIF,
                            PrimaryPushButton, ProgressBar, PushButton, ScrollArea, SimpleCardWidget,
                            StrongBodyLabel, SubtitleLabel, SwitchButton, ToolTipFilter,
                            TransparentToolButton, isDarkTheme, themeColor)

import core

TILE_W, TILE_H = 224, 126      # minimum tile size; tiles grow to fill the row
THUMB = (512, 288)             # decoded once per image, scaled when drawn


_THUMBS = {}


def load_thumb(path, w, h):
    """Fast, downscaled decode (JPEG decodes at reduced size), then center-crop to w x h. Cached."""
    key = (path, w, h)
    if key not in _THUMBS:
        if len(_THUMBS) > 300:
            _THUMBS.clear()
        _THUMBS[key] = _decode(path, w, h)
    return _THUMBS[key]


def _decode(path, w, h):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        scale = max(w / size.width(), h / size.height())
        reader.setScaledSize(QSize(max(1, int(size.width() * scale + 1)), max(1, int(size.height() * scale + 1))))
    img = reader.read()
    if img.isNull():
        return QPixmap()
    pm = QPixmap.fromImage(img)
    x, y = max(0, (pm.width() - w) // 2), max(0, (pm.height() - h) // 2)
    return pm.copy(x, y, w, h)


def rounded(painter, rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)


class FadeImage(QWidget):
    """Rounded image that cross-fades when the picture changes."""

    def __init__(self, w, h, radius=8, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.radius = radius
        self.old = QPixmap()
        self.new = QPixmap()
        self._blend = 1.0
        self.ani = QPropertyAnimation(self, b"blend", self)
        self.ani.setDuration(450)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)

    def getBlend(self):
        return self._blend

    def setBlend(self, v):
        self._blend = v
        self.update()

    blend = Property(float, getBlend, setBlend)

    def setImage(self, path):
        pm = load_thumb(path, self.width() * 2, self.height() * 2) if path else QPixmap()
        self.old, self.new = self.new, pm
        self.ani.stop()
        self.ani.setStartValue(0.0)
        self.ani.setEndValue(1.0)
        self.ani.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        rounded(p, r, self.radius)
        p.fillRect(r, QColor(255, 255, 255, 13) if isDarkTheme() else QColor(0, 0, 0, 10))
        if not self.old.isNull() and self._blend < 1:
            p.setOpacity(1 - self._blend)
            p.drawPixmap(r.toRect(), self.old)
        if not self.new.isNull():
            p.setOpacity(self._blend)
            p.drawPixmap(r.toRect(), self.new)


def heart_icon(filled, size=32):
    """Heart icon: outline uses Fluent's icon, filled is painted in the accent color (white by default)."""
    if not filled:
        return FIF.HEART.icon()
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 32
    path = QPainterPath()
    path.moveTo(16 * s, 27 * s)
    path.cubicTo(5 * s, 19 * s, 3 * s, 14 * s, 3 * s, 10.5 * s)
    path.cubicTo(3 * s, 6.5 * s, 6 * s, 4 * s, 9.5 * s, 4 * s)
    path.cubicTo(12.3 * s, 4 * s, 14.6 * s, 5.6 * s, 16 * s, 8 * s)
    path.cubicTo(17.4 * s, 5.6 * s, 19.7 * s, 4 * s, 22.5 * s, 4 * s)
    path.cubicTo(26 * s, 4 * s, 29 * s, 6.5 * s, 29 * s, 10.5 * s)
    path.cubicTo(29 * s, 14 * s, 27 * s, 19 * s, 16 * s, 27 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(themeColor())
    p.drawPath(path)
    p.end()
    return QIcon(pm)


class Tile(QWidget):
    """Gallery tile: lifts and darkens on hover, accent ring when it's the current wallpaper.
    A filled heart stays visible on favorites."""
    clicked = Signal(int)
    heart = Signal(int)

    def __init__(self, index, path, favorite=False, hover_text="Set as wallpaper", parent=None):
        super().__init__(parent)
        self.index = index
        self.hover_text = hover_text
        self.tw, self.th = TILE_W, TILE_H
        self.setFixedSize(self.tw, self.th + 6)
        self.setCursor(Qt.PointingHandCursor)
        self.pm = load_thumb(path, *THUMB)
        self.current = False
        self.favorite = favorite
        self._hover = 0.0
        self.ani = QPropertyAnimation(self, b"hover", self)
        self.ani.setDuration(180)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)

        self.heartBtn = TransparentToolButton(self)
        self.heartBtn.setFixedSize(32, 32)
        self.heartBtn.setIconSize(QSize(18, 18))
        self.heartBtn.installEventFilter(ToolTipFilter(self.heartBtn))
        self.heartBtn.clicked.connect(lambda: self.heart.emit(self.index))
        self.setFavorite(favorite)
        self._place_heart()

    def setFavorite(self, on):
        self.favorite = on
        self.heartBtn.setIcon(heart_icon(on))
        self.heartBtn.setToolTip("Remove from favorites" if on else "Save to favorites")
        self.heartBtn.setVisible(on or self._hover > 0.5)
        self.update()

    def _place_heart(self):
        self.heartBtn.move(self.tw - 40, int(12 - 3 * self._hover))

    def getHover(self):
        return self._hover

    def setHover(self, v):
        self._hover = v
        self._place_heart()
        self.update()

    hover = Property(float, getHover, setHover)

    def setTileWidth(self, w):
        if w != self.tw:
            self.tw, self.th = w, round(w * 9 / 16)
            self.setFixedSize(self.tw, self.th + 6)
            self._place_heart()

    def _animate(self, to):
        self.ani.stop()
        self.ani.setStartValue(self._hover)
        self.ani.setEndValue(to)
        self.ani.start()

    def enterEvent(self, e):
        self.heartBtn.show()
        self._animate(1.0)

    def leaveEvent(self, e):
        self.heartBtn.setVisible(self.favorite)
        self._animate(0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.index)

    def setCurrent(self, on):
        self.current = on
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        lift = 3 * self._hover
        r = QRectF(0, 3 - lift + 3, self.tw, self.th - 3)
        p.save()
        rounded(p, r, 8)
        if not self.pm.isNull():
            p.drawPixmap(r.toRect(), self.pm)
        p.fillRect(r, QColor(0, 0, 0, int(90 * self._hover)))
        if self.favorite and self._hover < 0.5:     # soft shade so the heart reads on bright images
            p.setBrush(QColor(0, 0, 0, 90))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(self.tw - 38, 10, 28, 28))
        if self._hover > 0.01:
            p.setOpacity(self._hover)
            p.setPen(QColor(255, 255, 255))
            f = p.font()
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, self.hover_text)
        p.restore()
        if self.current:
            pen = p.pen()
            pen.setColor(themeColor())
            pen.setWidthF(2.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1.25, 1.25, -1.25, -1.25), 7, 7)


class Gallery(QWidget):
    """Animated, responsive grid of tiles that stretch to fill each row."""
    clicked = Signal(int)
    heart = Signal(int)

    def __init__(self, hover_text="Set as wallpaper", parent=None):
        super().__init__(parent)
        self.hover_text = hover_text
        self.flow = FlowLayout(self, needAni=True)
        self.flow.setAnimation(260, QEasingCurve.OutCubic)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setHorizontalSpacing(12)
        self.flow.setVerticalSpacing(12)
        self.tiles = []

    def set_entries(self, entries, current=-1):
        self.flow.removeAllWidgets()
        for t in self.tiles:
            t.deleteLater()
        self.tiles = []
        for i, e in enumerate(entries):
            t = Tile(i, e["path"], core.is_favorite(e), self.hover_text, self)
            t.clicked.connect(self.clicked)
            t.heart.connect(self.heart)
            self.flow.addWidget(t)
            self.tiles.append(t)
        self.fit()
        self.mark(current)

    def mark(self, current):
        for t in self.tiles:
            t.setCurrent(t.index == current)

    def refresh_hearts(self, entries):
        for t in self.tiles:
            if t.index < len(entries):
                t.setFavorite(core.is_favorite(entries[t.index]))

    def fit(self):
        avail = self.width()
        if avail < TILE_W:
            return
        gap = 12
        cols = max(1, (avail + gap) // (TILE_W + gap))
        w = (avail - gap * (cols - 1)) // cols
        for t in self.tiles:
            t.setTileWidth(w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.fit)


class NowCard(SimpleCardWidget):
    """Slim 'now showing' strip: thumbnail, title, time left, progress bar, controls."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setBorderRadius(10)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 16, 12)
        lay.setSpacing(16)

        self.image = FadeImage(192, 108, 8, self)
        lay.addWidget(self.image)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.title = StrongBodyLabel("Fetching your first wallpaper…", self)
        self.sub = CaptionLabel("", self)
        self.sub.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        self.bar = ProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(4)
        self.time = CaptionLabel("", self)
        self.time.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        mid.addStretch(1)
        mid.addWidget(self.title)
        mid.addWidget(self.sub)
        mid.addSpacing(8)
        mid.addWidget(self.bar)
        mid.addWidget(self.time)
        mid.addStretch(1)
        lay.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.prevBtn = self._tool(FIF.LEFT_ARROW, "Previous wallpaper", ctl.previous)
        self.pauseBtn = self._tool(FIF.PAUSE, "Pause auto-change", lambda: ctl.set_running(not ctl.settings["running"]))
        self.saveBtn = self._tool(FIF.HEART, "Save to favorites", lambda: ctl.toggle_favorite(ctl.current()))
        self.saveBtn.setIconSize(QSize(16, 16))
        self.pageBtn = self._tool(FIF.LINK, "Open source page", ctl.open_page)
        for b in (self.prevBtn, self.pauseBtn, self.saveBtn, self.pageBtn):
            row.addWidget(b)
        self.nextBtn = PrimaryPushButton(FIF.SYNC, "Next wallpaper", self)
        self.nextBtn.clicked.connect(ctl.forward)
        self.interval = ComboBox(self)
        label = lambda k: k if k == core.NO_ROTATE else f"Every {k}"   # noqa: E731
        self.interval.addItems([label(k) for k in core.INTERVALS])
        self.interval.setCurrentText(label(ctl.settings["interval"]))
        self.interval.currentTextChanged.connect(lambda t: ctl.set_interval(t.replace("Every ", "")))
        right.addStretch(1)
        right.addWidget(self.nextBtn)
        right.addLayout(row)
        right.addWidget(self.interval)
        right.addStretch(1)
        lay.addLayout(right)

        ctl.current_changed.connect(self.refresh)
        ctl.favorites_changed.connect(self.refresh_heart)
        ctl.tick.connect(self.on_tick)
        ctl.busy_changed.connect(self.on_busy)
        ctl.running_changed.connect(self.on_running)
        ctl.status.connect(self.on_status)
        self.on_running(ctl.settings["running"])
        self.refresh()

    def _tool(self, icon, tip, slot):
        b = TransparentToolButton(icon, self)
        b.setToolTip(tip)
        b.installEventFilter(ToolTipFilter(b))
        b.clicked.connect(slot)
        return b

    def refresh(self):
        e = self.ctl.current()
        if not e:
            return
        self.image.setImage(e["path"])
        self.title.setText(_elide(e.get("title") or "Untitled", 70))
        when = time.strftime("%b %d, %I:%M %p", time.localtime(e.get("time", time.time())))
        self.sub.setText(f"{self.ctl.source_label(e['source'])}  ·  {when}")
        self.prevBtn.setEnabled(self.ctl.pos + 1 < len(self.ctl.history()))
        self.refresh_heart()

    def refresh_heart(self):
        fav = core.is_favorite(self.ctl.current())
        self.saveBtn.setIcon(heart_icon(fav))
        self.saveBtn.setToolTip("Remove from favorites" if fav else "Save to favorites")

    def on_tick(self, left, frac, why):
        if self.ctl.busy:
            return
        self.bar.setValue(int(frac * 1000))
        if why:
            self.time.setText(why)
        else:
            h, rem = divmod(left, 3600)
            m, s = divmod(rem, 60)
            self.time.setText(f"Next change in {h}:{m:02d}:{s:02d}" if h else f"Next change in {m}:{s:02d}")

    def on_busy(self, busy):
        self.nextBtn.setEnabled(not busy)
        self.nextBtn.setText("Fetching…" if busy else "Next wallpaper")
        if busy:
            self.bar.setValue(0)

    def on_status(self, kind, msg):
        if self.ctl.busy and kind == "info":
            self.time.setText(msg)

    def on_running(self, on):
        self.pauseBtn.setIcon(FIF.PAUSE if on else FIF.PLAY)
        self.pauseBtn.setToolTip("Pause auto-change" if on else "Resume auto-change")
        self.bar.setPaused(not on) if hasattr(self.bar, "setPaused") else None


class Page(ScrollArea):
    """Transparent, smooth-scrolling page with a padded vertical layout."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("#" + name + ",#view{background:transparent;border:none}")
        self.lay = QVBoxLayout(self.view)
        self.lay.setContentsMargins(36, 24, 36, 36)
        self.lay.setSpacing(12)

    def caption(self, text="", parent=None):
        c = CaptionLabel(text, parent or self.view)
        c.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        return c


class HomePage(Page):
    def __init__(self, ctl, parent=None):
        super().__init__("homePage", parent)
        self.ctl = ctl
        lay = self.lay
        lay.addWidget(SubtitleLabel("Home", self.view))
        self.card = NowCard(ctl, self.view)
        lay.addWidget(self.card)
        lay.addSpacing(12)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("Recent", self.view))
        self.count = self.caption()
        head.addWidget(self.count)
        head.addStretch(1)
        lay.addLayout(head)
        self.gallery = Gallery(parent=self.view)
        self.gallery.clicked.connect(ctl.pick)
        self.gallery.heart.connect(lambda i: ctl.toggle_favorite(ctl.history()[i]))
        lay.addWidget(self.gallery)
        self.empty = BodyLabel("Your recent wallpapers show up here.", self.view)
        lay.addWidget(self.empty)
        lay.addStretch(1)

        ctl.history_changed.connect(self.rebuild)
        ctl.current_changed.connect(lambda: self.gallery.mark(ctl.pos))
        ctl.favorites_changed.connect(lambda: self.gallery.refresh_hearts(ctl.history()))
        self.rebuild()

    def rebuild(self):
        h = self.ctl.history()
        self.gallery.set_entries(h, self.ctl.pos)
        n = len(h)
        self.count.setText(f"{n} wallpaper{'s' if n != 1 else ''}" if n else "")
        self.empty.setVisible(n == 0)


class FavoritesPage(Page):
    def __init__(self, ctl, parent=None):
        super().__init__("favoritesPage", parent)
        self.ctl = ctl
        lay = self.lay
        head = QHBoxLayout()
        head.addWidget(SubtitleLabel("Favorites", self.view))
        head.addStretch(1)
        folder = PushButton(FIF.FOLDER, "Open folder", self.view)
        folder.clicked.connect(self.open_folder)
        head.addWidget(folder)
        lay.addLayout(head)
        self.count = self.caption()
        lay.addWidget(self.count)

        self.rotate = SimpleCardWidget(self.view)
        row = QHBoxLayout(self.rotate)
        row.setContentsMargins(16, 12, 16, 12)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(BodyLabel("Rotate through my favorites", self.rotate))
        text.addWidget(self.caption("Adds your favorites to the wallpaper rotation. "
                                    "Turn other sources off to only see these.", self.rotate))
        row.addLayout(text, 1)
        self.rotateSw = SwitchButton(self.rotate)
        self.rotateSw.setChecked(ctl.settings["sources"]["favorites"].get("enabled", False))
        self.rotateSw.checkedChanged.connect(self.set_rotate)
        row.addWidget(self.rotateSw)
        lay.addWidget(self.rotate)
        lay.addSpacing(6)

        self.items = []
        self.gallery = Gallery("Set as wallpaper", self.view)
        self.gallery.clicked.connect(lambda i: ctl.use_entry(self.items[i]))
        self.gallery.heart.connect(lambda i: ctl.toggle_favorite(self.items[i]))
        lay.addWidget(self.gallery)
        self.empty = BodyLabel("Click the heart on any wallpaper to keep it here.", self.view)
        lay.addWidget(self.empty)
        lay.addStretch(1)
        ctl.favorites_changed.connect(self.rebuild)
        self.rebuild()

    def set_rotate(self, on):
        self.ctl.settings["sources"]["favorites"]["enabled"] = on
        self.ctl.save()

    def rebuild(self):
        self.items = core.list_favorites()
        self.gallery.set_entries(self.items)
        n = len(self.items)
        self.count.setText(f"{n} saved in Pictures\\Wallflow Favorites" if n else "")
        self.empty.setVisible(n == 0)

    def open_folder(self):
        os.makedirs(core.FAVORITES_DIR, exist_ok=True)
        os.startfile(core.FAVORITES_DIR)


def _elide(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"
