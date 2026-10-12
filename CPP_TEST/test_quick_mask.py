"""Sélection ▸ Masque rapide: paint a selection with any tool."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class QuickMaskTests(unittest.TestCase):
    def setUp(self):
        from CORE.application import CreativeSystem
        from DOCUMENTS.document import Document
        from DOCUMENTS.layer_manager import LayerManager
        self.window = CreativeSystem()
        self.document = Document(200, 120, 72, QColor(255, 255, 255))
        self.window.canvas.set_document(self.document)
        self.window.layer_manager = LayerManager(self.document)
        self.window.document_manager.documents.append(self.document)
        self.window.document_manager.active_document = self.document
        self.window.canvas.set_brush_setting("color", (10, 200, 30, 255))

    def tearDown(self):
        self.window.close()

    def test_painted_area_becomes_the_selection_and_the_temp_layer_goes_away(self):
        canvas = self.window.canvas
        layers_before = len(self.document.layers)
        self.window.toggle_quick_mask()
        self.assertEqual(len(self.document.layers), layers_before + 1)
        self.assertEqual(list(canvas.brush_settings.get("color"))[:3], [230, 40, 60])
        canvas.apply_lasso_fill([QPointF(20, 20), QPointF(80, 20), QPointF(80, 80), QPointF(20, 80)])
        self.window.toggle_quick_mask()
        self.assertEqual(len(self.document.layers), layers_before)
        selection = self.document.selection
        self.assertTrue(selection.contains(50, 50))
        self.assertFalse(selection.contains(150, 50))
        self.assertEqual(list(canvas.brush_settings.get("color"))[:3], [10, 200, 30])   # colour restored

    def test_existing_selection_is_loaded_into_the_mask(self):
        from DOCUMENTS.selection import SelectionOperation
        from TOOLS.selection_tools import SelectionTools
        selection = self.document.selection
        selection.combine(SelectionTools.shape_mask("select_rectangle", selection.image.size(),
                                                    [QPointF(100, 0), QPointF(200, 120)]),
                          SelectionOperation.REPLACE)
        self.window.toggle_quick_mask()
        mask_layer = self.document.get_active_layer()
        self.assertGreater(QColor.fromRgba(mask_layer.image.pixel(150, 60)).alpha(), 200)
        self.assertEqual(QColor.fromRgba(mask_layer.image.pixel(50, 60)).alpha(), 0)
        self.window.toggle_quick_mask()
        self.assertTrue(selection.contains(150, 60))
        self.assertFalse(selection.contains(50, 60))


if __name__ == "__main__":
    unittest.main()
