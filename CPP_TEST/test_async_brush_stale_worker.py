"""A finished or cancelled worker cannot overwrite a newer stroke."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class AsyncBrushStaleWorkerTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(128, 128, 72, None))

    def tearDown(self):
        self.canvas.close()

    def test_live_worker_cannot_be_replaced_by_another_begin(self):
        canvas = self.canvas
        layer = canvas.get_active_layer()
        self.assertTrue(canvas._begin_async_brush(layer, QPointF(32, 32), 0.5))
        handle, generation = canvas._async_brush_handle, canvas._async_stroke_generation
        with patch.object(canvas, "_cancel_async_brush") as cancel:
            self.assertFalse(canvas._begin_async_brush(layer, QPointF(90, 90), 0.5))
            cancel.assert_not_called()
        self.assertEqual(canvas._async_brush_handle, handle)
        self.assertEqual(canvas._async_stroke_generation, generation)

    def test_generation_is_invalidated_before_native_join(self):
        canvas = self.canvas
        self.assertTrue(canvas._begin_async_brush(canvas.get_active_layer(), QPointF(32, 32), 0.5))
        old_generation = canvas._async_stroke_generation
        native_destroy = canvas.cpp_brush_library.cs_brush_async_destroy
        def checked_destroy(handle):
            self.assertNotEqual(canvas._async_stroke_generation, old_generation)
            native_destroy(handle)
        with patch.object(canvas.cpp_brush_library, "cs_brush_async_destroy", side_effect=checked_destroy):
            canvas._cancel_async_brush()

    def test_already_queued_old_patch_is_rejected_at_ui_delivery(self):
        canvas = self.canvas
        layer = canvas.get_active_layer()
        canvas._begin_async_brush(layer, QPointF(32, 32), 0.5)
        old_generation = canvas._async_stroke_generation
        canvas._cancel_async_brush()
        canvas._begin_async_brush(layer, QPointF(90, 90), 0.5)
        image = QImage(8, 8, QImage.Format.Format_RGBA8888)
        image.fill(QColor("red"))
        with patch.object(canvas, "_apply_async_brush_patch") as apply:
            canvas._dispatch_async_brush_patch(old_generation, 0, 0, 8, 8, image, True, "")
            apply.assert_not_called()
            canvas._dispatch_async_brush_patch(canvas._async_stroke_generation, 0, 0, 8, 8, image, False, "")
            apply.assert_called_once()


if __name__ == "__main__":
    unittest.main()
