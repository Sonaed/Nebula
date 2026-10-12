"""Viewport-bounded occlusion and native tile-index lifecycle regressions."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from CANVAS.gpu_renderer import CanvasGPURenderer
from CPP_TEST.test_gpu_frame_snapshot import BulkStore, FakeLayer
from DOCUMENTS.tile_store import TileStore


class ViewportOcclusionTests(unittest.TestCase):
    def setUp(self):
        self.renderer = CanvasGPURenderer()
        keys = {(x, y) for y in range(24) for x in range(32)}
        self.store = BulkStore(keys, revisions={key: 1 for key in keys}, opaque=keys)
        self.layers = [FakeLayer("bottom", BulkStore(set())), FakeLayer("top", self.store)]

    def frame(self, visible, width=2048, height=1536):
        self.renderer.begin_frame()
        try:
            return self.renderer.compute_occlusion(
                self.layers, width, height, visible_tiles=visible)["bottom"]
        finally:
            self.renderer.end_frame()

    def test_only_visible_resident_pixels_are_inspected(self):
        visible = {(0, 0), (1, 0), (1, 1)}
        self.assertEqual(self.frame(visible), visible)
        self.assertEqual(self.store.calls["tile"], len(visible))
        self.assertEqual(len(self.renderer._opaque_tile_cache), len(visible))

    def test_pan_reads_only_new_tiles_and_empty_view_reads_no_pixels(self):
        self.frame({(0, 0), (1, 0)})
        self.assertEqual(self.frame({(1, 0), (2, 0)}), {(1, 0), (2, 0)})
        self.assertEqual(self.store.calls["tile"], 3)
        self.assertEqual(self.frame(set()), set())
        self.assertEqual(self.store.calls["tile"], 3)

    def test_offscreen_edits_are_seen_when_panning_back(self):
        self.frame({(0, 0)})
        self.frame({(1, 0)})
        self.store.opaque.remove((0, 0))
        self.store.revisions[(0, 0)] = 2
        self.assertEqual(self.frame({(0, 0)}), set())

    def test_replaced_store_with_same_revisions_does_not_reuse_old_coverage(self):
        self.assertEqual(self.frame({(0, 0)}), {(0, 0)})
        # Undo and imports can replace the pixel source of a stable layer ID.
        self.layers[-1].tile_store = BulkStore(
            self.store.resident, revisions=self.store.revisions, opaque=set())
        self.assertEqual(self.frame({(0, 0)}), set())

    def test_partial_document_edge_and_invalid_keys_are_bounded(self):
        self.assertEqual(self.frame({(-1, 0), (0, 0), (1, 0), (2, 0), (0, 1)},
                                    width=100, height=50), {(0, 0), (1, 0)})

    def test_active_mask_cannot_hide_lower_layers(self):
        self.layers[-1].alpha_mask_store = object()
        self.assertEqual(self.frame({(0, 0)}), set())
        self.assertEqual(self.store.calls["tile"], 0)
        self.layers[-1].mask_disabled = True
        self.assertEqual(self.frame({(0, 0)}), {(0, 0)})
        self.layers[-1].mask_disabled = False
        self.assertEqual(self.frame({(0, 0)}), set())

    def test_swapped_tile_never_loads_for_occlusion(self):
        self.store.resident.remove((0, 0))
        self.store._swapped[(0, 0)] = "scratch.png"
        self.assertEqual(self.frame({(0, 0)}), set())
        self.assertEqual(self.store.calls["async"], 0)
        self.assertEqual(self.store.calls["tile"], 0)

    def test_compatibility_api_still_returns_whole_document(self):
        self.frame({(0, 0)})
        result = self.renderer.compute_occlusion(self.layers, 2048, 1536)
        self.assertEqual(result["bottom"], self.store.resident)


class NativeFrameIndexTests(unittest.TestCase):
    def setUp(self):
        self.renderer = CanvasGPURenderer()
        self.store = TileStore(128, 64)
        self.addCleanup(self.store.close)
        self.image = QImage(64, 64, QImage.Format.Format_RGBA8888)
        self.image.fill(QColor("white"))
        self.store.set_tile(0, 0, self.image)

    def frame(self):
        self.renderer.begin_frame()
        try:
            return self.renderer._frame_tile_state(self.store)
        finally:
            self.renderer.end_frame()

    def test_unchanged_native_store_reuses_index_without_ctypes_enumeration(self):
        first = self.frame()
        with patch.object(self.store, "resident_revisions",
                          side_effect=AssertionError("Unchanged native store was enumerated")):
            self.assertIs(self.frame(), first)
            self.assertIs(self.frame(), first)

    def test_native_pixel_and_residency_mutations_invalidate_snapshot(self):
        first = self.frame()
        self.store.set_tile(0, 0, self.image)
        second = self.frame()
        self.assertIsNot(first, second)
        self.assertNotEqual(first.revision((0, 0)), second.revision((0, 0)))
        self.store.set_tile(1, 0, self.image)
        self.assertIn((1, 0), self.frame().resident)
        self.store.remove_resident_tile(0, 0)
        self.assertNotIn((0, 0), self.frame().resident)
        self.store.clear_resident()
        self.assertFalse(self.frame().resident)

    def test_pending_scratch_load_cannot_make_an_intermediate_snapshot_stick(self):
        ready = self.frame()
        self.store._pending_loads.add((1, 0))
        loading = self.frame()
        self.assertIsNot(ready, loading)
        self.assertIsNot(loading, self.frame())
        self.store._pending_loads.clear()
        # Completion may not increment again: the native worker counted the
        # mutation before releasing the GIL to decode its scratch file.
        completed = self.frame()
        self.assertIsNot(completed, loading)
        self.assertIs(self.frame(), completed)

    def test_stores_without_mutation_contract_are_read_each_frame(self):
        legacy = BulkStore({(0, 0)}, revisions={(0, 0): 1})
        self.store.close()
        self.store = legacy
        first = self.frame()
        legacy.revisions[(0, 0)] = 2
        second = self.frame()
        self.assertIsNot(first, second)
        self.assertEqual(second.revision((0, 0)), 2)

    def test_unused_store_is_released_after_next_frame(self):
        self.frame()
        self.assertIn(id(self.store), self.renderer._previous_frame_tiles)
        self.renderer.begin_frame()
        self.renderer.end_frame()
        self.assertFalse(self.renderer._previous_frame_tiles)

    def test_cleanup_releases_cpu_snapshot_without_a_gl_context(self):
        self.frame()
        with patch("CANVAS.gpu_renderer.QOpenGLContext") as context:
            context.currentContext.return_value = None
            self.renderer.cleanup()
        self.assertFalse(self.renderer._previous_frame_tiles)


if __name__ == "__main__":
    unittest.main()
