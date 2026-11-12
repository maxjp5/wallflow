"""Home page: now-showing card with progress bar, and a gallery of recent wallpapers."""
import time

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FlowLayout, FluentIcon as FIF,
                            PrimaryPushButton, ProgressBar, ScrollArea, SimpleCardWidget,
                            StrongBodyLabel, SubtitleLabel, ToolTipFilter, TransparentToolButton,
                            isDarkTheme, themeColor)

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


class Tile(QWidget):
    """Gallery tile: lifts and darkens on hover, accent ring when it's the current wallpaper."""
    clicked = Signal(int)
    save = Signal(int)

    def __init__(self, index, path, parent=None):
        super().__init__(parent)
        self.index = index
        self.tw, self.th = TILE_W, TILE_H
        self.setFixedSize(self.tw, self.th + 6)
        self.setCursor(Qt.PointingHandCursor)
        self.pm = load_thumb(path, *THUMB)
        self.current = False
        self._hover = 0.0
        self.ani = QPropertyAnimation(self, b"hover", self)
        self.ani.setDuration(180)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)

        self.saveBtn = TransparentToolButton(FIF.HEART, self)
        self.saveBtn.setFixedSize(30, 30)
        self.saveBtn.setToolTip("Save to favorites")
        self.saveBtn.installEventFilter(ToolTipFilter(self.saveBtn))
        self.saveBtn.move(self.tw - 38, 10)
        self.saveBtn.clicked.connect(lambda: self.save.emit(self.index))
        self.saveBtn.hide()

    def getHover(self):
        return self._hover

    def setHover(self, v):
        self._hover = v
        self.saveBtn.move(self.tw - 38, int(10 - 3 * v) + 3)
        self.update()

    hover = Property(float, getHover, setHover)

    def setTileWidth(self, w):
        if w != self.tw:
            self.tw, self.th = w, round(w * 9 / 16)
            self.setFixedSize(self.tw, self.th + 6)
            self.saveBtn.move(self.tw - 38, 10)

    def _animate(self, to):
        self.ani.stop()
        self.ani.setStartValue(self._hover)
        self.ani.setEndValue(to)
        self.ani.start()

    def enterEvent(self, e):
        self.saveBtn.show()
        self._animate(1.0)

    def leaveEvent(self, e):
        self.saveBtn.hide()
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
        if self._hover > 0.01:
            p.setOpacity(self._hover)
            p.setPen(QColor(255, 255, 255))
            f = p.font()
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, "Set as wallpaper")
        p.restore()
        if self.current:
            pen = p.pen()
            pen.setColor(themeColor())
            pen.setWidthF(2.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1.25, 1.25, -1.25, -1.25), 7, 7)


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
        self.saveBtn = self._tool(FIF.HEART, "Save to favorites", ctl.favorite)
        self.pageBtn = self._tool(FIF.LINK, "Open source page", ctl.open_page)
        for b in (self.prevBtn, self.pauseBtn, self.saveBtn, self.pageBtn):
            row.addWidget(b)
        self.nextBtn = PrimaryPushButton(FIF.SYNC, "Next wallpaper", self)
        self.nextBtn.clicked.connect(ctl.forward)
        self.interval = ComboBox(self)
        self.interval.addItems([f"Every {k}" for k in core.INTERVALS])
        self.interval.setCurrentText(f"Every {ctl.settings['interval']}")
        self.interval.currentTextChanged.connect(lambda t: ctl.set_interval(t.replace("Every ", "")))
        right.addStretch(1)
        right.addWidget(self.nextBtn)
        right.addLayout(row)
        right.addWidget(self.interval)
        right.addStretch(1)
        lay.addLayout(right)

        ctl.current_changed.connect(self.refresh)
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


class HomePage(ScrollArea):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setObjectName("homePage")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("#homePage,#view{background:transparent;border:none}")

        lay = QVBoxLayout(self.view)
        lay.setContentsMargins(36, 24, 36, 36)
        lay.setSpacing(12)
        lay.addWidget(SubtitleLabel("Home", self.view))
        self.card = NowCard(ctl, self.view)
        lay.addWidget(self.card)
        lay.addSpacing(12)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("Recent", self.view))
        self.count = CaptionLabel("", self.view)
        self.count.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        head.addWidget(self.count)
        head.addStretch(1)
        lay.addLayout(head)

        self.grid_host = QWidget(self.view)
        self.flow = FlowLayout(self.grid_host, needAni=True)
        self.flow.setAnimation(260, QEasingCurve.OutCubic)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setHorizontalSpacing(12)
        self.flow.setVerticalSpacing(12)
        lay.addWidget(self.grid_host)
        self.empty = BodyLabel("Your recent wallpapers show up here.", self.view)
        lay.addWidget(self.empty)
        lay.addStretch(1)

        self.tiles = []
        ctl.history_changed.connect(self.rebuild)
        ctl.current_changed.connect(self.mark_current)
        self.rebuild()

    def rebuild(self):
        self.flow.removeAllWidgets()
        for t in self.tiles:
            t.deleteLater()
        self.tiles = []
        for i, e in enumerate(self.ctl.history()):
            t = Tile(i, e["path"], self.grid_host)
            t.clicked.connect(self.ctl.pick)
            t.save.connect(self.ctl.favorite)
            self.flow.addWidget(t)
            self.tiles.append(t)
        self.fit_tiles()
        n = len(self.tiles)
        self.count.setText(f"{n} wallpaper{'s' if n != 1 else ''}" if n else "")
        self.empty.setVisible(n == 0)
        self.mark_current()

    def fit_tiles(self):
        """Pick a column count for the width, then stretch tiles to fill each row exactly."""
        avail = self.grid_host.width()
        if avail < TILE_W:
            return
        gap = 12
        cols = max(1, (avail + gap) // (TILE_W + gap))
        w = (avail - gap * (cols - 1)) // cols
        for t in self.tiles:
            t.setTileWidth(w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.fit_tiles)     # after the inner layout has its new width

    def mark_current(self):
        for t in self.tiles:
            t.setCurrent(t.index == self.ctl.pos)


def _elide(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"
