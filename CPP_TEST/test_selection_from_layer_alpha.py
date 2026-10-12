"""Sélection ▸ Depuis la transparence du calque, sur un vrai calque prémultiplié."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from DOCUMENTS.selection import SelectionMask

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class SelectionFromLayerAlphaTests(unittest.TestCase):
    def test_premultiplied_layer_alpha_becomes_the_selection(self):
        layer = QImage(64, 32, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(QColor(0, 0, 0, 0))
        painter = QPainter(layer)
        painter.fillRect(0, 0, 32, 32, QColor(200, 50, 50, 255))
        painter.end()
        selection = SelectionMask(64, 32)
        selection.select_alpha(layer)
        self.assertGreater(QColor.fromRgba(selection.image.pixel(10, 10)).alpha(), 200)
        self.assertEqual(QColor.fromRgba(selection.image.pixel(50, 10)).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
