"""Temporary visibility feedback must never become a stale pixel source."""
import copy
import gc
import os
import unittest
import weakref
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from CANVAS.tile_history import TileHistory
from CANVAS.visibility_preview import VisibilityPreview
from DOCUMENTS.blend_modes import composite_document_layers
from DOCUMENTS.document import Document
from DOCUMENTS.layer_group import LayerGroup


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), image.bytesPerLine())[:, :image.width() * 4].copy()


def fill(layer, color):
    image = QImage(layer.tile_store.width, layer.tile_store.height,
                   QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    layer.image = image


def reduced_reference(document, size):
    """Independent, existing compositor operating on the same reduced sources."""
    first = document.layers[0].tile_store.thumbnail(size)
    reduced = Document(first.width(), first.height())
    for index, layer in enumerate(document.layers):
        target = reduced.layers[0] if index == 0 else reduced.add_layer(layer.name)
        for name in ("id", "visible", "opacity", "blend_mode", "blend_parameters",
                     "clipping", "layer_kind", "adjustment"):
            setattr(target, name, copy.deepcopy(getattr(layer, name)))
        target.image = layer.tile_store.thumbnail(size).convertToFormat(QImage.Format.Format_ARGB32)
    reduced.layer_groups = copy.deepcopy(document.layer_groups)
    return composite_document_layers(reduced)


class VisibilityPreviewTests(unittest.TestCase):
    def test_toggle_reuses_sources_and_never_changes_authoritative_pixels(self):
        document = Document(128, 96)
        fill(document.layers[0], "white")
        top = document.add_layer("Red")
        fill(top, "red")
        renderer = VisibilityPreview(32)
        original = [layer.tile_store.materialize() for layer in document.layers]
        revisions = [layer.tile_store.resident_revisions() for layer in document.layers]
        with patch.object(top.tile_store, "thumbnail", wraps=top.tile_store.thumbnail) as thumbnail:
            self.assertEqual(renderer.render(document).pixelColor(4, 4), QColor("red"))
            top.visible = False
            self.assertEqual(renderer.render(document).pixelColor(4, 4), QColor("white"))
            top.visible = True
            self.assertEqual(renderer.render(document).pixelColor(4, 4), QColor("red"))
            top.opacity = 0.5
            self.assertNotEqual(renderer.render(document).pixelColor(4, 4), QColor("red"))
            self.assertEqual(thumbnail.call_count, 1)
        self.assertEqual(revisions, [layer.tile_store.resident_revisions() for layer in document.layers])
        self.assertEqual(original, [layer.tile_store.materialize() for layer in document.layers])

    def test_nested_groups_and_clipping_match_reduced_reference(self):
        document = Document(128, 96)
        fill(document.layers[0], "#4b5967")
        base = document.add_layer("Base")
        image = QImage(128, 96, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.fillRect(QRect(16, 8, 80, 64), QColor(220, 160, 60, 180))
        painter.end()
        base.image = image
        clipped = document.add_layer("Clipped")
        fill(clipped, "#489be0")
        clipped.clipping = True
        clipped.opacity = 0.65
        clipped.blend_mode = "multiply"
        leaf = document.add_layer("Light")
        fill(leaf, QColor(80, 20, 50, 96))
        inner = LayerGroup("Inner", layer_ids=[base.id, clipped.id], opacity=0.8)
        outer = LayerGroup("Outer", layer_ids=[base.id, clipped.id, leaf.id], opacity=0.7)
        inner.parent_id = outer.id
        document.layer_groups = [inner, outer]
        renderer = VisibilityPreview(32)
        for mode in ("normal", "multiply", "screen", "overlay"):
            for hidden in (None, base, clipped, inner, outer):
                with self.subTest(mode=mode, hidden=getattr(hidden, "name", None)):
                    outer.blend_mode = mode
                    if hidden is not None:
                        hidden.visible = False
                    try:
                        actual = renderer.render(document)
                        self.assertIsNotNone(actual)
                        difference = np.abs(pixels(actual).astype(int) -
                                            pixels(reduced_reference(document, 32)).astype(int))
                        self.assertLessEqual(int(difference.max()), 2)
                    finally:
                        if hidden is not None:
                            hidden.visible = True

    def test_native_undo_redo_invalidates_sources_without_python_mutation_counter(self):
        document = Document(128, 96)
        layer = document.layers[0]
        fill(layer, "red")
        renderer = VisibilityPreview(32)
        history = TileHistory()
        with patch.object(layer.tile_store, "thumbnail", wraps=layer.tile_store.thumbnail) as thumbnail:
            before = renderer.render(document)
            history.begin(document, dirty_only=True)
            history.capture_before(layer, QRect(0, 0, 64, 64))
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("blue"))
            layer.tile_store.set_tile(0, 0, tile)
            self.assertTrue(history.commit(document))
            after = renderer.render(document)
            self.assertNotEqual(before, after)
            count = layer.tile_store._mutation_count
            self.assertTrue(history.undo(document))
            self.assertEqual(layer.tile_store._mutation_count, count)
            self.assertEqual(renderer.render(document), before)
            self.assertTrue(history.redo(document))
            self.assertEqual(renderer.render(document), after)
            self.assertEqual(thumbnail.call_count, 4)

    def test_tile_deletion_and_store_replacement_invalidate_sources(self):
        document = Document(128, 96)
        layer = document.layers[0]
        fill(layer, "red")
        renderer = VisibilityPreview(32)
        before = renderer.render(document)
        layer.tile_store.remove_resident_tile(0, 0)
        self.assertNotEqual(renderer.render(document), before)
        replacement = Document(128, 96).layers[0].tile_store
        layer.tile_store = replacement
        self.assertEqual(renderer.render(document).pixelColor(0, 0).alpha(), 0)

    def test_pending_buffer_and_scratch_sources_fall_back_without_io_or_writes(self):
        document = Document(128, 96)
        layer = document.layers[0]
        fill(layer, "red")
        renderer = VisibilityPreview(32)
        self.assertIsNotNone(renderer.render(document))
        buffer = layer.image
        buffer.setPixelColor(0, 0, QColor("blue"))
        with patch.object(layer, "commit_image_cache", side_effect=AssertionError("source write")):
            self.assertIsNone(renderer.render(document))
        layer.commit_image_cache(release=True)
        layer.tile_store._swapped[(0, 0)] = "/nonexistent/preview-must-not-read.png"
        with patch.object(layer.tile_store, "thumbnail", side_effect=AssertionError("scratch read")):
            self.assertIsNone(renderer.render(document))
        layer.tile_store._swapped.clear()
        layer.tile_store.close()
        self.assertIsNone(renderer.render(document))

    def test_unsupported_content_falls_back(self):
        for attribute, value in (("transform_state", {"rotation": 15}),
                                 ("layer_effects", [{"kind": "stroke"}]),
                                 ("psd_effects", [{"kind": "shadow"}]),
                                 ("vector_mask", [{"points": []}]),
                                 ("blend_mode", "unknown-mode")):
            with self.subTest(attribute=attribute):
                document = Document(128, 96)
                setattr(document.layers[0], attribute, value)
                self.assertIsNone(VisibilityPreview(32).render(document))
        document = Document(128, 96)
        document.layers[0].ensure_alpha_mask()
        self.assertIsNone(VisibilityPreview(32).render(document))
        document = Document(128, 96)
        group = LayerGroup(layer_ids=[document.layers[0].id])
        group.ensure_alpha_mask(128, 96)
        document.layer_groups = [group]
        self.assertIsNone(VisibilityPreview(32).render(document))
        for attribute in ("reference_images", "text_objects"):
            document = Document(128, 96)
            getattr(document, attribute).append(object())
            self.assertIsNone(VisibilityPreview(32).render(document))
        document = Document(128, 96)
        document.layers[0].tile_store.width = 32
        self.assertIsNone(VisibilityPreview(32).render(document))
        with patch("CANVAS.visibility_preview.load_creative_core", return_value=None):
            self.assertIsNone(VisibilityPreview(32).render(Document(128, 96)))

    def test_cache_budget_removal_document_switch_and_clear(self):
        document = Document(128, 96)
        fill(document.layers[0], "red")
        top = document.add_layer("Top")
        fill(top, "blue")
        renderer = VisibilityPreview(32, budget_bytes=32 * 24 * 4)
        self.assertIsNotNone(renderer.render(document))
        self.assertLessEqual(renderer._bytes, renderer.budget_bytes)
        self.assertEqual(list(renderer._cache), [top.id])
        document.layers.pop()
        self.assertIsNotNone(renderer.render(document))
        self.assertNotIn(top.id, renderer._cache)
        other = Document(128, 96)
        other.text_objects.append(object())
        self.assertIsNone(renderer.render(other))
        self.assertFalse(renderer._cache)
        self.assertEqual(renderer._bytes, 0)
        renderer.render(document)
        renderer.clear()
        self.assertFalse(renderer._cache)
        self.assertEqual(renderer._bytes, 0)
        self.assertIsNone(renderer._document_ref)

    def test_renderer_does_not_keep_closed_document_alive(self):
        document = Document(128, 96)
        fill(document.layers[0], "red")
        renderer = VisibilityPreview(32)
        renderer.render(document)
        self.assertTrue(renderer._cache)
        reference = weakref.ref(document)
        del document
        gc.collect()
        self.assertIsNone(reference())
        self.assertFalse(renderer._cache)
        self.assertEqual(renderer._bytes, 0)


if __name__ == "__main__":
    unittest.main()
