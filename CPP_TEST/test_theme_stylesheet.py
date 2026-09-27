"""Régression : la feuille de style ne doit jamais contenir de propriété dupliquée.

« font-size: font-size: 10px; » faisait rejeter toute la feuille par Qt
(« Could not parse application stylesheet ») : le thème n'était jamais appliqué.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtCore  # noqa: F401
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtWidgets"):
        sys.modules[name] = mock.MagicMock(name=name)

from UI.theme.theme_manager import ThemeManager  # noqa: E402


class ThemeStylesheetTests(unittest.TestCase):
    def render(self, compact: bool) -> str:
        settings = mock.MagicMock()
        settings.value.return_value = compact
        with mock.patch("UI.theme.theme_manager.QSettings", return_value=settings):
            return ThemeManager.stylesheet()

    def test_no_property_name_is_doubled(self):
        for compact in (True, False):
            sheet = self.render(compact)
            self.assertIsNone(re.search(r"([\w-]+):\s*\1:", sheet))

    def test_base_font_size_follows_the_compact_setting(self):
        self.assertIn("font-size: 10px;", self.render(True).split("\n")[6])
        self.assertIn("font-size: 12px;", self.render(False).split("\n")[6])

    def test_braces_are_balanced_and_no_placeholder_is_left(self):
        sheet = self.render(True)
        self.assertEqual(sheet.count("{"), sheet.count("}"))
        self.assertIsNone(re.search(r"\{[a-z_]+\}", sheet))


if __name__ == "__main__":
    unittest.main()
