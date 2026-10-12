"""Canvas lifecycle for temporary large-document visibility feedback."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CANVAS.visibility_preview import VisibilityPreview
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.document import Document
from DOCUMENTS.layer_group import LayerGroup
from DOCUMENTS.layer_manager import LayerManager


def tile(color):
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


class VisibilityCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(320, 200)
        self.canvas.use_gpu = False
        self.document = Document(4000, 2000)
        self.layer = self.document.layers[0]
        self.layer.tile_store.set_tile(0, 0, tile("blue"))
        self.canvas.set_document(self.document)
        self.canvas.zoom = 0.125
        self.canvas.offset = QPointF()
        self.canvas._visibility_renderer = VisibilityPreview(128)

    def tearDown(self):
        self.canvas.close()

    def request(self):
        self.canvas.invalidate_projection_for_layers([self.layer])
        self.assertIn("_visibility_preview_key", self.canvas.__dict__)
        self.assertIsInstance(self.document._display_preview, QImage)

    def check_before_exact_publication(self):
        # Keep exact publication from concealing a failure to discard the
        # preview when document contents or interaction state have changed.
        with patch.object(self.canvas, "visible_document_tile_keys", return_value=set()), \
             patch.object(self.canvas, "_publish_projection_frame", return_value=False):
            self.canvas._ensure_projection()

    def assert_no_preview(self):
        self.assertNotIn("_visibility_preview_key", self.canvas.__dict__)
        self.assertFalse(hasattr(self.document, "_display_preview"))

    def test_visibility_action_produces_feedback_before_exact_recomposition(self):
        manager = LayerManager(self.document)
        self.assertFalse(manager.toggle_visibility(0))
        self.request()
        self.assertEqual(self.document._display_preview.pixelColor(0, 0).alpha(), 0)
        self.assertFalse(self.canvas._projection_display_ready)
        self.assertFalse(self.canvas.projection_store.occupied_keys)
        self.assertTrue(manager.toggle_visibility(0))
        self.request()
        self.assertEqual(self.document._display_preview.pixelColor(0, 0), QColor("blue"))

    def test_zoom_stroke_gradient_and_small_document_guards(self):
        for attribute, value in (("zoom", 0.5), ("drawing", True), ("gradient_drawing", True)):
            with self.subTest(attribute=attribute):
                previous = getattr(self.canvas, attribute)
                setattr(self.canvas, attribute, value)
                with patch.object(self.canvas._visibility_renderer, "render",
                                  side_effect=AssertionError("preview during interaction")):
                    self.canvas._request_visibility_preview()
                self.assert_no_preview()
                setattr(self.canvas, attribute, previous)
        self.canvas.set_document(Document(128, 64))
        self.canvas.zoom = 0.125
        with patch.object(self.canvas._visibility_renderer, "render",
                          side_effect=AssertionError("small canvas preview")):
            self.canvas._request_visibility_preview()
        self.assertNotIn("_visibility_preview_key", self.canvas.__dict__)

    def test_exact_frame_replaces_preview_only_when_every_visible_tile_is_ready(self):
        self.request()
        preview = self.document._display_preview
        canvas = self.canvas
        canvas._projection_scan_pending = False
        canvas._projection_tile_generation = {(0, 0): 7, (1, 0): 7}
        canvas._projection_tile_signatures = {(0, 0): ("new",), (1, 0): ("new",)}
        canvas._projection_publish_keys = {(0, 0), (1, 0)}
        canvas._projection_waiting_visible = {(0, 0), (1, 0)}
        canvas._on_projected_tile(7, 0, 0, tile("red"))
        self.assertIs(self.document._display_preview, preview)
        self.assertFalse(canvas._projection_display_ready)
        self.assertFalse(canvas.projection_store.occupied_keys)
        canvas._on_projected_tile(7, 1, 0, tile("green"))
        self.assert_no_preview()
        self.assertTrue(canvas._projection_display_ready)
        self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor("red"))
        self.assertEqual(canvas.projection_store.tile(1, 0).pixelColor(0, 0), QColor("green"))

    def test_document_switch_and_close_release_preview_cache(self):
        self.request()
        renderer = self.canvas._visibility_renderer
        self.assertTrue(renderer._cache)
        self.canvas.set_document(Document(4000, 2000))
        self.assert_no_preview()
        self.assertFalse(renderer._cache)
        self.assertEqual(renderer._bytes, 0)
        self.canvas.zoom = 0.125
        self.canvas._request_visibility_preview()
        self.assertTrue(renderer._cache)
        self.canvas.close()
        self.assertFalse(renderer._cache)
        self.assertIsNone(renderer._document_ref)

    def test_undo_and_pixel_mutation_discard_stale_feedback(self):
        history = self.canvas.tile_history
        history.begin(self.document, dirty_only=True)
        history.capture_before(self.layer, QRect(0, 0, 64, 64))
        self.layer.tile_store.set_tile(0, 0, tile("red"))
        self.assertTrue(history.commit(self.document))
        self.request()
        self.canvas.undo()
        self.check_before_exact_publication()
        self.assert_no_preview()
        self.request()
        self.layer.tile_store.set_tile(0, 0, tile("green"))
        self.check_before_exact_publication()
        self.assert_no_preview()

    def test_existing_feedback_is_discarded_when_zooming_or_beginning_a_stroke(self):
        for attribute, value in (("zoom", 0.5), ("drawing", True), ("gradient_drawing", True)):
            with self.subTest(attribute=attribute):
                self.request()
                previous = getattr(self.canvas, attribute)
                setattr(self.canvas, attribute, value)
                try:
                    self.check_before_exact_publication()
                    self.assert_no_preview()
                finally:
                    setattr(self.canvas, attribute, previous)

    def test_new_unsupported_content_invalidates_existing_feedback(self):
        self.request()
        self.document.text_objects.append(EditableText("Ink", QPointF()))
        self.check_before_exact_publication()
        self.assert_no_preview()
        self.document.text_objects.clear()
        self.request()
        self.document.reference_images.append(ReferenceImage(tile("red")))
        self.check_before_exact_publication()
        self.assert_no_preview()
        self.document.reference_images.clear()
        self.request()
        self.layer.vector_mask = [{"points": []}]
        self.check_before_exact_publication()
        self.assert_no_preview()

    def test_new_group_mask_invalidates_existing_feedback(self):
        group = LayerGroup(layer_ids=[self.layer.id])
        self.document.layer_groups = [group]
        self.request()
        group.ensure_alpha_mask(self.document.width, self.document.height)
        self.check_before_exact_publication()
        self.assert_no_preview()

    def test_unsupported_visibility_action_keeps_exact_projection_path(self):
        self.layer.ensure_alpha_mask()
        self.canvas.invalidate_projection_for_layers([self.layer])
        self.assert_no_preview()
        self.assertFalse(self.canvas._projection_display_ready)
        self.canvas.visible_document_tile_keys = lambda *args: {(0, 0)}
        self.canvas._ensure_projection()
        self.assertTrue(self.canvas._projection_display_ready)
        self.assertEqual(self.canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor("blue"))

    def test_hidden_lower_layer_does_not_recompose_under_opaque_cover(self):
        """A visibility toggle below an opaque tile preserves the exact projection."""
        upper = self.document.add_layer("Opaque cover")
        self.layer.tile_store.set_tile(0, 0, tile("red"))
        upper.tile_store.set_tile(0, 0, tile("blue"))
        self.canvas.visible_document_tile_keys = lambda *args: {(0, 0)}
        self.canvas._ensure_projection()
        self.assertEqual(self.canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor("blue"))
        mutation_before = self.canvas.projection_store._mutation_count
        self.layer.visible = False
        self.document.sync_native_state()
        self.assertEqual(self.canvas.invalidate_projection_for_layers([self.layer]), 0)
        self.canvas._ensure_projection()
        self.assertEqual(self.canvas.projection_store._mutation_count, mutation_before)
        self.assertEqual(self.canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor("blue"))
        self.assertGreater(self.canvas.performance_stats_snapshot()["projection_cache"]
                           ["visibility_occlusion_skips"], 0)


if __name__ == "__main__":
    unittest.main()
