from __future__ import annotations

import unittest
import os
from unittest.mock import patch

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage
from CANVAS.gpu_renderer import CanvasGPURenderer
from CANVAS.gpu_tile_compositor import GPUTileCompositor
from DOCUMENTS.layer import Layer


class GPUDirtyTrackingTests(unittest.TestCase):

    def test_gpu_view_transform_matches_canvas_rotation_and_mirror_order(self) -> None:
        """The GPU path must mirror first and then rotate, like Canvas does."""
        viewport = QRect(0, 0, 800, 600)
        target = QRectF(100, 200, 50, 60)
        transform = CanvasGPURenderer._blit_view_transform(
            target, viewport, 90.0, True, False,
        )
        # Texture (0, 0) is the tile's bottom-left in the TopLeft blitter path.
        mapped = transform.map(QPointF(0.0, 0.0))
        # Canvas: flip x around centre, then rotate +90 degrees in screen space.
        self.assertAlmostEqual(mapped.x(), 0.10, places=5)
        self.assertAlmostEqual(mapped.y(), -1.0, places=5)

    def test_gpu_transform_preview_rotates_about_the_layer_center(self) -> None:
        transform = CanvasGPURenderer._blit_view_transform(
            QRectF(100, 200, 50, 60), QRect(0, 0, 800, 600),
            content_rotation=90.0, content_center=(400.0, 300.0),
        )
        mapped = transform.map(QPointF(0.0, 0.0))
        self.assertAlmostEqual(mapped.x(), 0.10, places=5)
        self.assertAlmostEqual(mapped.y(), 1.0, places=5)

    def test_gpu_tile_compositor_routes_supported_masks_but_rejects_parameterized_blends(self) -> None:
        from DOCUMENTS.document import Document
        document = Document(64, 64)
        layer = document.get_active_layer()
        with patch.dict("os.environ", {"CREATIVESYSTEM_EXPERIMENTAL_GPU_COMPOSITOR": "1"}):
            self.assertTrue(GPUTileCompositor.supports(document))
            layer.ensure_alpha_mask()
            # Editable raster masks are sampled by the compositor shader.
            self.assertTrue(GPUTileCompositor.supports(document))
            layer.set_alpha_mask(None)
            layer.blend_parameters = {"intensity": 0.5}
            self.assertFalse(GPUTileCompositor.supports(document))

    def test_gpu_tile_compositor_keeps_groups_on_native_projection_by_default(self) -> None:
        from DOCUMENTS.document import Document
        from DOCUMENTS.layer_group import LayerGroup
        document = Document(64, 64)
        extra = document.add_layer("Groupe")
        document.layer_groups.append(LayerGroup(layer_ids=[document.layers[0].id, extra.id]))
        self.assertFalse(GPUTileCompositor.supports(document))
        with patch.dict(os.environ, {"CREATIVESYSTEM_EXPERIMENTAL_GPU_GROUPS": "1"}):
            self.assertTrue(GPUTileCompositor.supports(document))
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
