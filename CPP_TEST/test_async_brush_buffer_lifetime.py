"""Async sources stay alive until every native reader has been joined."""
import gc
import os
import unittest
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class AsyncBrushBufferLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(128, 128, 72, None))

    def tearDown(self):
        self.canvas.close()

    def test_native_tile_source_is_pinned_until_worker_is_joined(self):
        layer = self.canvas.get_active_layer()
        tile = QImage(64, 64, QImage.Format.Format_RGBA8888)
        tile.fill(QColor("red"))
        layer.tile_store.set_tile(0, 0, tile)
        self.assertTrue(self.canvas._begin_async_brush(layer, QPointF(32, 32), 0.5))
        snapshot = self.canvas._async_brush_source_store
        self.assertIsNot(snapshot, layer.tile_store)
        self.assertTrue(layer.tile_store.remove_resident_tile(0, 0))
        self.assertEqual(snapshot.tile(0, 0).pixelColor(0, 0), QColor("red"))
        self.assertIsNone(self.canvas._async_brush_source_image)
        self.canvas._cancel_async_brush()
        self.assertIsNone(self.canvas._async_brush_source_store)

    def test_fallback_image_and_raw_buffer_are_pinned_until_join(self):
        # Directly exercise the legacy image ABI, also retained for swapped
        # sources. Symmetry creates multiple native readers of that source.
        self.canvas.symmetry_horizontal = True
        self.assertTrue(self.canvas._begin_async_brush(
            self.canvas.get_active_layer(), QPointF(32, 32), 0.5))
        source = self.canvas._async_brush_source_image
        watch = weakref.ref(source)
        self.assertIsNotNone(self.canvas._async_brush_source_raw)
        self.assertEqual(len(self.canvas._async_symmetry_handles), 1)
        del source
        gc.collect()
        self.assertIsNotNone(watch())
        self.canvas._cancel_async_brush()
        gc.collect()
        self.assertIsNone(watch())
        self.assertIsNone(self.canvas._async_brush_source_raw)
        self.assertFalse(self.canvas._async_symmetry_handles)


if __name__ == "__main__":
    unittest.main()
