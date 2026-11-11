import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mc3000_theme import is_dark, THEME_MODES


def test_fixed_modes():
    assert is_dark("dark") is True
    assert is_dark("light") is False
    assert THEME_MODES == ["auto", "light", "dark"]
