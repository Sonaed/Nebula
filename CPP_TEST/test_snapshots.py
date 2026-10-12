"""History snapshots: copy of every layer's pixels, restore is undoable."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(160, 120, 72, None))

    def tearDown(self):
        self.canvas.close()

    def alpha(self, x, y):
        return QColor.fromRgba(self.canvas.get_active_layer().image.pixel(x, y)).alpha()

    def test_restore_brings_back_pixels_and_can_be_undone(self):
        square = [QPointF(10, 10), QPointF(60, 10), QPointF(60, 60), QPointF(10, 60)]
        self.canvas.apply_lasso_fill(square)
        snapshot = self.canvas.create_snapshot("Avant")
        self.canvas.apply_lasso_fill([QPointF(p.x() + 80, p.y()) for p in square])
        self.assertEqual(self.alpha(110, 30), 255)
        self.assertEqual(self.canvas.restore_snapshot(snapshot), 1)
        self.assertEqual(self.alpha(30, 30), 255)     # kept from the snapshot
        self.assertEqual(self.alpha(110, 30), 0)      # later work gone...
        self.canvas.undo()
        self.assertEqual(self.alpha(110, 30), 255)    # ...and back with one undo

    def test_snapshot_is_sparse_and_covers_masks(self):
        square = [QPointF(10, 10), QPointF(60, 10), QPointF(60, 60), QPointF(10, 60)]
        self.canvas.apply_lasso_fill(square)
        layer = self.canvas.get_active_layer()
        layer.ensure_alpha_mask()
        snapshot = self.canvas.create_snapshot()
        stored = sum(len(t[4]) for tiles in snapshot["stores"].values() for t in tiles.values())
        self.assertLess(stored, 160 * 120 * 4 // 4)      # far below a full copy
        self.assertIn(("mask", layer.id), snapshot["stores"])
        self.canvas.edit_layer_alpha_mask(0)
        self.canvas.set_brush_setting("color", [0, 0, 0, 255])
        self.canvas.apply_lasso_fill(square)              # hide through the mask
        self.canvas.edit_layer_pixels()
        self.assertEqual(QColor.fromRgba(layer.alpha_mask_coverage().pixel(30, 30)).alpha(), 0)
        self.canvas.restore_snapshot(snapshot)
        self.assertEqual(QColor.fromRgba(layer.alpha_mask_coverage().pixel(30, 30)).alpha(), 255)

    def test_navigator_preview_follows_edits(self):
        from DOCUMENTS.blend_modes import composite_preview
        self.canvas.set_document(Document(1600, 1200, 72, None))
        first = composite_preview(self.canvas.document, 160)
        self.assertEqual((first.width(), first.height()), (160, 120))
        self.canvas.set_brush_setting("color", [255, 0, 0, 255])
        self.canvas.apply_lasso_fill([QPointF(0, 0), QPointF(800, 0), QPointF(800, 600), QPointF(0, 600)])
        after = composite_preview(self.canvas.document, 160)
        self.assertEqual(QColor.fromRgba(after.pixel(40, 30)).getRgb(), (255, 0, 0, 255))
        self.assertEqual(QColor.fromRgba(after.pixel(120, 90)).alpha(), 0)

    def test_snapshots_belong_to_their_document(self):
        self.canvas.create_snapshot()
        self.assertEqual(len(self.canvas.document_snapshots()), 1)
        snapshot = self.canvas.document_snapshots()[0]
        self.canvas.set_document(Document(50, 50, 72, None))
        self.assertEqual(self.canvas.document_snapshots(), [])
        self.assertEqual(self.canvas.restore_snapshot(snapshot), 0)


if __name__ == "__main__":
    unittest.main()
