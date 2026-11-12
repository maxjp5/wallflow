"""Accent colors. Each accent has a version for dark mode and one for light mode."""
from PySide6.QtGui import QColor
from qfluentwidgets import isDarkTheme, qconfig, setThemeColor

ACCENTS = {  # name -> (dark-mode color, light-mode color, description)
    "White": ("#FFFFFF", "#1C1C1C", "Monochrome, the cleanest look"),
    "Windows": (None, None, "Follows your Windows accent color"),
    "Blue": ("#4CC2FF", "#0067C0", "Windows 11 default"),
    "Teal": ("#3DD6C6", "#00796B", "Calm and fresh"),
    "Green": ("#6CCB5F", "#0F7B0F", "Natural"),
    "Orange": ("#FF9F4A", "#C35A00", "Warm"),
    "Pink": ("#FF8AC4", "#BF0077", "Playful"),
    "Purple": ("#A391FF", "#6B4FE0", "Wallflow's original color"),
}
DEFAULT = "White"


def accent_color(name, dark=None):
    dark = isDarkTheme() if dark is None else dark
    d, l, _ = ACCENTS.get(name, ACCENTS[DEFAULT])
    if d is None:   # Windows accent
        try:
            from qframelesswindow.utils import getSystemAccentColor
            c = getSystemAccentColor()
            if c.isValid():
                return c.lighter(140) if dark else c
        except Exception:  # noqa: BLE001
            pass
        d, l = ACCENTS["Blue"][:2]
    return QColor(d if dark else l)


class AccentManager:
    """Applies the chosen accent, and re-applies it when the theme flips light/dark."""

    def __init__(self, settings):
        self.settings = settings
        qconfig.themeChangedFinished.connect(self.apply)
        self.apply()

    def set(self, name):
        self.settings["accent"] = name
        self.apply()

    def apply(self):
        setThemeColor(accent_color(self.settings.get("accent", DEFAULT)))
