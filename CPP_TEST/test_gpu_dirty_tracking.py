from __future__ import annotations

import unittest

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from CANVAS.gpu_renderer import CanvasGPURenderer
from DOCUMENTS.layer import Layer


class GPUDirtyTrackingTests(unittest.TestCase):
    def test_dirty_regions_union_and_clip_to_texture_bounds(self) -> None:
        renderer = CanvasGPURenderer()
        layer = Layer("test", 100, 80)
        renderer.mark_layer_dirty(layer, QRect(90, 70, 20, 20))
        renderer.mark_layer_dirty(layer, QRect(4, 5, 10, 12))

        dirty = renderer.dirty_rects[id(layer)]
        self.assertEqual(dirty, QRect(4, 5, 106, 85))
        bounded = renderer.bounded_dirty_rect(dirty, 100, 80)
        self.assertEqual(bounded, QRect(4, 5, 96, 75))
        self.assertEqual(renderer.bounded_dirty_rect(None, 100, 80), QRect(0, 0, 100, 80))

    def test_missing_bounds_request_a_full_update_and_stats_reset(self) -> None:
        renderer = CanvasGPURenderer()
        layer = Layer("test", 10, 10)
        renderer.mark_layer_dirty(layer, QRect(2, 2, 3, 3))
        renderer.mark_layer_dirty(layer)
        self.assertNotIn(id(layer), renderer.dirty_rects)
        self.assertEqual(renderer.bounded_dirty_rect(None, 10, 10), QRect(0, 0, 10, 10))
        renderer.transfer_stats["dirty_staging_bytes"] = 48
        self.assertEqual(renderer.transfer_stats_snapshot(reset=True)["dirty_staging_bytes"], 48)
        self.assertEqual(renderer.transfer_stats_snapshot()["dirty_staging_bytes"], 0)

    def test_mipmap_level_count_covers_complete_chain(self) -> None:
        self.assertEqual(CanvasGPURenderer._mip_levels(1, 1), 1)
        self.assertEqual(CanvasGPURenderer._mip_levels(64, 64), 7)
        self.assertEqual(CanvasGPURenderer._mip_levels(100, 64), 7)

    def test_occlusion_requires_fully_opaque_normal_top_layer(self) -> None:
        renderer = CanvasGPURenderer()
        bottom = Layer("bottom", 64, 64)
        top = Layer("top", 64, 64)
        opaque = QImage(64, 64, QImage.Format.Format_ARGB32)
        opaque.fill(0xFFFFFFFF)
        top.tile_store.set_tile(0, 0, opaque)

        occlusion = renderer.compute_occlusion([bottom, top], 64, 64)
        self.assertEqual(occlusion[id(bottom)], {(0, 0)})

        top.blend_mode = "multiply"
        occlusion = renderer.compute_occlusion([bottom, top], 64, 64)
        self.assertEqual(occlusion[id(bottom)], set())

        top.blend_mode = "normal"
        top.opacity = 0.5
        occlusion = renderer.compute_occlusion([bottom, top], 64, 64)
        self.assertEqual(occlusion[id(bottom)], set())

    def test_partially_transparent_top_tile_does_not_occlude(self) -> None:
        renderer = CanvasGPURenderer()
        bottom = Layer("bottom", 64, 64)
        top = Layer("top", 64, 64)
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        image.setPixel(0, 0, 0x00FFFFFF)
        top.tile_store.set_tile(0, 0, image)
        occlusion = renderer.compute_occlusion([bottom, top], 64, 64)
        self.assertEqual(occlusion[id(bottom)], set())


if __name__ == "__main__":
    unittest.main()
