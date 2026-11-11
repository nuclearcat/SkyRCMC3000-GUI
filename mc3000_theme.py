"""
Light / dark theme for the MC3000 GUI.

Modes:
- "auto":  follow the operating system (macOS/Windows/Linux colour scheme),
           switches live when the system setting changes
- "light": always light
- "dark":  always dark

The choice is stored with QSettings.
"""

from typing import Callable, List

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPalette, QGuiApplication
from PySide6.QtWidgets import QApplication

THEME_MODES = ["auto", "light", "dark"]
THEME_LABELS = {"auto": "Auto", "light": "Light", "dark": "Dark"}

_SETTINGS_ORG = "skyrc-mc3000-gui"
_SETTINGS_APP = "gui"
_SETTINGS_KEY = "theme"

# Plot colours per theme
PLOT_COLORS = {
    False: {"background": "w", "foreground": "k"},
    True: {"background": (30, 30, 30), "foreground": (220, 220, 220)},
}


def load_theme_mode() -> str:
    mode = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY, "auto")
    return mode if mode in THEME_MODES else "auto"


def save_theme_mode(mode: str) -> None:
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY, mode)


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # very old Qt: guess from the default palette
        return QApplication.palette().color(QPalette.Window).lightness() < 128


def is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return system_is_dark()


def dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(45, 45, 45)
    base = QColor(30, 30, 30)
    text = QColor(225, 225, 225)
    disabled = QColor(120, 120, 120)
    highlight = QColor(42, 130, 218)

    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.ToolTipBase, QColor(60, 60, 60))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, Qt.red)
    p.setColor(QPalette.Link, highlight)
    p.setColor(QPalette.Highlight, highlight)
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.PlaceholderText, disabled)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, disabled)
    p.setColor(QPalette.Disabled, QPalette.Base, QColor(40, 40, 40))
    p.setColor(QPalette.Disabled, QPalette.Button, QColor(40, 40, 40))
    return p


class ThemeManager:
    """Applies the theme to the application and notifies listeners."""

    def __init__(self, app: QApplication):
        self.app = app
        self.mode = load_theme_mode()
        self.dark = False
        self._listeners: List[Callable[[bool], None]] = []
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_changed)
        except AttributeError:
            pass

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        self._listeners.append(callback)
        callback(self.dark)

    def set_mode(self, mode: str) -> None:
        if mode not in THEME_MODES:
            mode = "auto"
        self.mode = mode
        save_theme_mode(mode)
        self.apply()

    def apply(self) -> None:
        self.dark = is_dark(self.mode)
        if self.dark:
            self.app.setPalette(dark_palette())
        else:
            self.app.setPalette(self.app.style().standardPalette())
        # Widgets with a style sheet do not pick up palette changes by themselves
        for w in self.app.allWidgets():
            if w.styleSheet():
                w.style().unpolish(w)
                w.style().polish(w)
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(**PLOT_COLORS[self.dark])
        except ImportError:
            pass
        for cb in list(self._listeners):
            cb(self.dark)

    def _on_system_changed(self, *_):
        if self.mode == "auto":
            self.apply()
