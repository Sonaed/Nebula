from __future__ import annotations

import unittest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor

from DOCUMENTS.document import Document
from DOCUMENTS.format_nebula import NebulaFormat
from TOOLS.retouch_tool import RetouchTool


class RetouchToolTests(unittest.TestCase):
    def test_clone_writes_only_to_a_retouch_layer_and_honours_selection(self):
        document = Document(32, 32)
        source = document.get_active_layer()
        source.image.setPixelColor(4, 4, QColor(210, 40, 20, 255))
        document.selection.clear()
        document.selection.image.setPixelColor(12, 12, QColor("white"))
        document.selection.invalidate()
        retouch = RetouchTool().clone(document, source, QPoint(4, 4), QPoint(12, 12), 2)
        self.assertEqual(retouch.layer_kind, "retouch")
        self.assertEqual(source.image.pixelColor(12, 12).alpha(), 0)
        self.assertEqual(retouch.image.pixelColor(12, 12), QColor(210, 40, 20, 255))
        self.assertEqual(retouch.image.pixelColor(11, 12).alpha(), 0)
        self.assertEqual(retouch.retouch_operations[0]["kind"], "clone")

    def test_retouch_operation_log_round_trips(self):
        import tempfile
        from pathlib import Path
        document = Document(16, 16)
        source = document.get_active_layer()
        source.image.fill(QColor(30, 70, 110, 255))
        retouch = RetouchTool().heal(document, source, QPoint(2, 2), QPoint(8, 8), 1)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "retouch.nebula"
            self.assertTrue(NebulaFormat.save(document, target))
            loaded = NebulaFormat.load(target)
        restored = next(layer for layer in loaded.layers if layer.layer_kind == "retouch")
        self.assertEqual(restored.retouch_operations, retouch.retouch_operations)


if __name__ == "__main__":
    unittest.main()
