"""Packs page: offline sets of wallpapers, plus the dialog that downloads them."""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF, LineEdit, MessageBoxBase,
                            PrimaryPushButton, ProgressBar, PushButton, ScrollArea, SegmentedWidget,
                            SettingCard, StrongBodyLabel, SubtitleLabel, SwitchButton,
                            TransparentToolButton)

import core
import sources
from ui_sources import describe


class PacksPage(ScrollArea):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setObjectName("packsPage")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setStyleSheet("#packsPage,#view{background:transparent;border:none}")

        lay = QVBoxLayout(self.view)
        lay.setContentsMargins(36, 24, 36, 36)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(SubtitleLabel("Packs", self.view))
        head.addStretch(1)
        self.dlBtn = PrimaryPushButton(FIF.DOWNLOAD, "Download a pack", self.view)
        self.dlBtn.clicked.connect(self.open_dialog)
        head.addWidget(self.dlBtn)
        lay.addLayout(head)
        lay.addWidget(BodyLabel("Download a set of wallpapers once, then rotate through it without internet.",
                                self.view))
        lay.addSpacing(10)

        cfg = ctl.settings["sources"]["packs"]
        self.useCard = SettingCard(FIF.SYNC, "Rotate through my packs",
                                   "Adds the packs you turn on below to the wallpaper rotation", self.view)
        self.useSw = SwitchButton(self.useCard)
        self.useSw.setChecked(cfg.get("enabled", False))
        self.useSw.checkedChanged.connect(self.set_enabled)
        self.useCard.hBoxLayout.addWidget(self.useSw, 0, Qt.AlignRight)
        self.useCard.hBoxLayout.addSpacing(16)
        lay.addWidget(self.useCard)
        lay.addSpacing(10)
        lay.addWidget(StrongBodyLabel("Your packs", self.view))

        self.listHost = QWidget(self.view)
        self.listLay = QVBoxLayout(self.listHost)
        self.listLay.setContentsMargins(0, 0, 0, 0)
        self.listLay.setSpacing(4)
        lay.addWidget(self.listHost)
        row = QHBoxLayout()
        folderBtn = PushButton(FIF.FOLDER, "Open packs folder", self.view)
        folderBtn.clicked.connect(self.open_folder)
        row.addWidget(folderBtn)
        row.addStretch(1)
        lay.addSpacing(8)
        lay.addLayout(row)
        lay.addStretch(1)
        self.refresh()

    def set_enabled(self, on):
        self.ctl.settings["sources"]["packs"]["enabled"] = on
        self.ctl.save()

    def refresh(self):
        while self.listLay.count():
            w = self.listLay.takeAt(0).widget()
            if w:
                w.deleteLater()
        selected = set(self.ctl.settings["sources"]["packs"].get("selected", []))
        packs = core.list_packs()
        if not packs:
            self.listLay.addWidget(CaptionLabel("No packs yet. Download one to get started.", self.listHost))
        for name, count in packs:
            card = SettingCard(FIF.LIBRARY, name, f"{count} wallpapers", self.listHost)
            sw = SwitchButton(card)
            sw.setChecked(name in selected)
            sw.checkedChanged.connect(lambda v, n=name: self.toggle_pack(n, v))
            folder = TransparentToolButton(FIF.FOLDER, card)
            folder.setToolTip("Open folder")
            folder.clicked.connect(lambda _=False, n=name: os.startfile(os.path.join(core.PACKS_DIR, n)))
            card.hBoxLayout.addWidget(folder, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(12)
            card.hBoxLayout.addWidget(sw, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(16)
            self.listLay.addWidget(card)

    def toggle_pack(self, name, on):
        sel = self.ctl.settings["sources"]["packs"].setdefault("selected", [])
        if on and name not in sel:
            sel.append(name)
        elif not on and name in sel:
            sel.remove(name)
        self.ctl.save()

    def open_folder(self):
        os.makedirs(core.PACKS_DIR, exist_ok=True)
        os.startfile(core.PACKS_DIR)

    def open_dialog(self):
        dlg = PackDialog(self.ctl, self.window())
        dlg.finished_pack.connect(self.pack_done)
        dlg.exec()

    def pack_done(self, name, got):
        self.refresh()
        if got:
            sel = self.ctl.settings["sources"]["packs"].setdefault("selected", [])
            if name not in sel:
                sel.append(name)
            self.useSw.setChecked(True)
            self.ctl.save()
            self.refresh()


class _Bridge(QObject):
    progress = Signal(int, int, str)
    done = Signal(str, str, int)


class PackDialog(MessageBoxBase):
    finished_pack = Signal(str, int)
    COUNTS = ["24", "50", "100", "200"]

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.running = False
        self.cancel = False
        self.bridge = _Bridge()
        self.bridge.progress.connect(self.on_progress)
        self.bridge.done.connect(self.on_done)

        self.viewLayout.addWidget(SubtitleLabel("Download a pack", self))
        self.viewLayout.addWidget(CaptionLabel("Uses the search and sort you set for that source on the Sources page.",
                                               self))
        self.src = SegmentedWidget(self)
        for key in sources.PACK_SOURCES:
            self.src.addItem(key, sources.SOURCES[key][0].replace(" Space Photos", ""),
                             onClick=lambda k=key: self.on_source(k))
        first = next((k for k in sources.PACK_SOURCES if ctl.settings["sources"][k].get("enabled")),
                     sources.PACK_SOURCES[0])
        self.key = first
        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.src)
        self.what = CaptionLabel("", self)
        self.viewLayout.addWidget(self.what)

        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(StrongBodyLabel("Pack name", self))
        self.name = LineEdit(self)
        self.viewLayout.addWidget(self.name)
        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(StrongBodyLabel("How many", self))
        self.count = SegmentedWidget(self)
        for c in self.COUNTS:
            self.count.addItem(c, c)
        self.count.setCurrentItem("50")
        self.viewLayout.addWidget(self.count)
        self.viewLayout.addSpacing(12)
        self.bar = ProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.viewLayout.addWidget(self.bar)
        self.msg = CaptionLabel("", self)
        self.viewLayout.addWidget(self.msg)

        self.yesButton.setText("Download")
        self.cancelButton.setText("Close")
        self.widget.setMinimumWidth(460)
        self.src.setCurrentItem(first)
        self.on_source(first)

    def on_source(self, key):
        self.key = key
        desc = describe(key, self.ctl.settings["sources"][key])
        self.what.setText(f"{sources.SOURCES[key][0]} · {desc}")
        self.name.setText(desc.replace(" · ", " - "))

    def validate(self):
        """Download button: start (or stop) instead of closing the dialog."""
        if self.running:
            self.cancel = True
            self.msg.setText("Stopping after the current image…")
            return False
        name = core.safe_name(self.name.text())
        count = int(self.count.currentRouteKey() or "50")
        cfg = dict(self.ctl.settings["sources"][self.key])
        st = self.ctl.settings
        self.running, self.cancel = True, False
        self.yesButton.setText("Stop")
        self.bar.setValue(0)

        def work():
            try:
                pack, got = core.download_pack(
                    name, self.key, cfg, core.wallpaper_size(st), count,
                    lambda d, t, m: self.bridge.progress.emit(d, t, m),
                    cancelled=lambda: self.cancel, match=st.get("match_screens", True))
                note = f"Done: {got} new wallpapers in “{pack}”." if got else "No new wallpapers found for that search."
                self.bridge.done.emit(pack, note, got)
            except Exception as e:  # noqa: BLE001
                self.bridge.done.emit(name, f"Stopped: {e}", 0)

        threading.Thread(target=work, daemon=True).start()
        return False

    def on_progress(self, done, total, msg):
        self.bar.setValue(int(1000 * done / max(1, total)))
        self.msg.setText(msg)

    def on_done(self, pack, note, got):
        self.running = False
        self.yesButton.setText("Download more")
        self.msg.setText(note + (" It's turned on in your packs." if got else ""))
        if got:
            self.bar.setValue(1000)
        self.finished_pack.emit(pack, got)

    def reject(self):
        self.cancel = True
        super().reject()
