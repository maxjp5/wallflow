"""Sources page: one expandable card per source, with an on/off switch in its header."""
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, ComboBox, ExpandGroupSettingCard, FluentIcon as FIF,
                            HyperlinkButton, LineEdit, PasswordLineEdit, PushButton, ScrollArea,
                            SubtitleLabel, SwitchButton)

import sources

ICONS = {"wallhaven": FIF.PHOTO, "unsplash": FIF.CAMERA, "nasa": FIF.GLOBE,
         "picsum": FIF.ALBUM, "local": FIF.FOLDER}

FIELDS = {  # key -> [(setting, title, help, kind, choices)]
    "wallhaven": [
        ("query", "Search", "Blank shows everything", "entry", None),
        ("sort", "Sort by", "Toplist, Hot and Most favorited are the popular galleries", "choice",
         list(sources.WALLHAVEN_SORTS)),
        ("range", "Toplist period", "Only used when sorting by Toplist", "choice", list(sources.WALLHAVEN_RANGES)),
        ("collection", "Collection link", "Paste wallhaven.cc/user/NAME/favorites/123 to use a gallery instead",
         "entry", None),
        ("anime", "Include anime", "Adds Wallhaven's anime category", "switch", None),
        ("api_key", "API key", "Optional", "secret", None),
    ],
    "unsplash": [
        ("mode", "Pull from", "Topic, search, a collection link, or random", "choice", sources.UNSPLASH_MODES),
        ("query", "Topic, search words or collection link", "For example wallpapers, nature or a collection URL",
         "entry", None),
        ("access_key", "Access key", "Required. Free at unsplash.com/developers", "secret", None),
    ],
    "nasa": [("query", "Search", "Blank picks random space photos", "entry", None)],
    "picsum": [],
    "local": [("folder", "Folder", "Wallflow rotates through the images in this folder", "folder", None)],
}


def describe(key, cfg):
    """Short description of what a source is set to pull."""
    if key == "wallhaven":
        if cfg.get("collection", "").strip():
            return "Collection"
        sort = cfg.get("sort", "Random")
        extra = f" ({cfg.get('range', 'Past month').replace('Past ', '').lower()})" if sort == "Toplist" else ""
        return f"{cfg.get('query', '').strip() or 'Everything'} · {sort}{extra}"
    if key == "unsplash":
        if not cfg.get("access_key", "").strip():
            return "Needs a free access key"
        return f"{cfg.get('mode', 'Topic')} · {cfg.get('query', '').strip() or 'wallpapers'}"
    if key == "nasa":
        return cfg.get("query", "").strip() or "Random space photos"
    if key == "picsum":
        return "Random photos, no setup"
    if key == "local":
        return cfg.get("folder", "").strip() or "No folder picked"
    return ""


class SourcesPage(ScrollArea):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setObjectName("sourcesPage")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setStyleSheet("#sourcesPage,#view{background:transparent;border:none}")
        self.saver = QTimer(self, singleShot=True, interval=500, timeout=ctl.save)

        lay = QVBoxLayout(self.view)
        lay.setContentsMargins(36, 24, 36, 36)
        lay.setSpacing(6)
        lay.addWidget(SubtitleLabel("Sources", self.view))
        hint = BodyLabel("Each change picks one of the sources you turn on.", self.view)
        lay.addWidget(hint)
        lay.addSpacing(10)

        self.cards = {}
        for key in FIELDS:
            card = self.build_card(key)
            lay.addWidget(card)
            self.cards[key] = card
        lay.addStretch(1)

    def build_card(self, key):
        cfg = self.ctl.settings["sources"][key]
        label = sources.SOURCES[key][0]
        card = ExpandGroupSettingCard(ICONS[key], label, describe(key, cfg), self.view)
        sw = SwitchButton(card)
        sw.setOnText("On")
        sw.setOffText("Off")
        sw.setChecked(cfg.get("enabled", False))
        sw.checkedChanged.connect(lambda v, k=key: self.set(k, "enabled", v))
        card.addWidget(sw)

        for field, title, help_, kind, choices in FIELDS[key]:
            w = self.field_widget(key, field, kind, choices, card)
            card.addGroup(FIF.EDIT if kind != "switch" else FIF.TAG, title, help_, w)
        if key == "unsplash":
            link = HyperlinkButton("https://unsplash.com/developers", "Get a free key", card)
            card.addGroup(FIF.LINK, "No key yet?", "Create a free Unsplash developer app", link)
        if key == "picsum":
            card.setExpand(False)
            card.card.expandButton.hide()
        return card

    def field_widget(self, key, field, kind, choices, parent):
        cfg = self.ctl.settings["sources"][key]
        if kind == "choice":
            w = ComboBox(parent)
            w.addItems(choices)
            w.setCurrentText(cfg.get(field) or choices[0])
            w.setMinimumWidth(180)
            w.currentTextChanged.connect(lambda v: self.set(key, field, v))
        elif kind == "switch":
            w = SwitchButton(parent)
            w.setChecked(bool(cfg.get(field)))
            w.checkedChanged.connect(lambda v: self.set(key, field, v))
        elif kind == "folder":
            w = QWidget(parent)
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            edit = LineEdit(w)
            edit.setText(cfg.get(field, ""))
            edit.setMinimumWidth(260)
            edit.textChanged.connect(lambda v: self.set(key, field, v))
            btn = PushButton(FIF.FOLDER, "Browse", w)
            btn.clicked.connect(lambda: self.pick_folder(edit))
            row.addWidget(edit)
            row.addWidget(btn)
        else:
            w = PasswordLineEdit(parent) if kind == "secret" else LineEdit(parent)
            w.setText(cfg.get(field, ""))
            w.setMinimumWidth(260)
            w.setClearButtonEnabled(kind != "secret")
            w.textChanged.connect(lambda v: self.set(key, field, v))
        return w

    def pick_folder(self, edit):
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of wallpapers")
        if folder:
            edit.setText(folder.replace("/", "\\"))

    def set(self, key, field, value):
        self.ctl.settings["sources"][key][field] = value
        self.cards[key].card.setContent(describe(key, self.ctl.settings["sources"][key])) \
            if key in self.cards else None
        self.saver.start()
