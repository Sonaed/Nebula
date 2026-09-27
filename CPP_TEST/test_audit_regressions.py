from __future__ import annotations

import os
import re
import zipfile
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import qimage_pointer
from DOCUMENTS.layer import Layer
from CANVAS.view_state import transform_point, fit_zoom
from TOOLS.resource_manager import ResourceManager
from DOCUMENTS.adjustments import (apply_curves, apply_levels, apply_hue_saturation,
                                   CurvesAdjustment, LevelsAdjustment, HueSaturationAdjustment,
                                   ExposureAdjustment, VibranceAdjustment,
                                   ColorBalanceAdjustment, apply_exposure,
                                   apply_vibrance, apply_invert, apply_threshold,
                                   apply_posterize, apply_color_balance,
                                   ParametricCurvesAdjustment, SelectiveColorAdjustment,
                                   LuminosityMaskAdjustment, apply_parametric_curves,
                                   apply_selective_color, AdjustmentLayerSpec, apply_adjustment,
                                   apply_layer_effects)
from DOCUMENTS.selection import SelectionMask
from TOOLS.transform_tool import TransformTool, LiquifyStroke, WarpControl
from DOCUMENTS.document import Document
from DOCUMENTS.format_nebula import NebulaFormat
from DOCUMENTS.color_management import profile_from_image, SRGB, convert_to_profile
from CANVAS.canvas import Canvas
from PySide6.QtCore import QRect


class AuditRegressionTests(unittest.TestCase):
    def test_view_transform_round_trips_with_rotation_and_flip(self):
        from PySide6.QtCore import QPointF
        point = QPointF(217.0, 143.0)
        transformed = transform_point(point, 800, 600, 37.0, True, False)
        restored = transform_point(transformed, 800, 600, 37.0, True, False, True)
        self.assertAlmostEqual(restored.x(), point.x(), places=5)
        self.assertAlmostEqual(restored.y(), point.y(), places=5)

    def test_fit_zoom_accounts_for_rotation(self):
        expected = 560.0 / (1000.0 * 2 ** -0.5 + 500.0 * 2 ** -0.5)
        self.assertAlmostEqual(fit_zoom(1000, 500, 800, 600, 45, 0.01, 10), expected, places=6)

    def test_qimage_pointer_retains_the_export_owner(self):
        image = QImage(8, 8, QImage.Format.Format_RGBA8888)
        pointer = qimage_pointer(image)
        self.assertTrue(pointer)
        self.assertIs(pointer._qimage_keepalive[0], image)
        self.assertEqual(len(pointer._qimage_keepalive), 3)

    def test_native_in_place_write_is_committed_without_cache_key_change(self):
        layer = Layer("test", 64, 64)
        image = layer.image
        before = layer.tile_store.occupied_keys.copy()
        image.fill(QColor(12, 34, 56, 255))
        layer.mark_image_cache_dirty()
        layer.commit_image_cache()
        self.assertNotEqual(before, layer.tile_store.occupied_keys)
        self.assertEqual(layer.tile_store.tile(0, 0).pixelColor(0, 0), QColor(12, 34, 56, 255))
        layer.tile_store.close()

    def test_tile_store_scratch_identity_is_not_object_address(self):
        first = Layer("first", 64, 64)
        second = Layer("second", 64, 64)
        self.assertNotEqual(first.tile_store.id, second.tile_store.id)
        first.tile_store.close()
        second.tile_store.close()

    def test_resource_manager_round_trip_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            source = Path(directory) / "brush.csbr"
            source.write_bytes(b"brush")
            manager = ResourceManager(root)
            imported = manager.import_file(source, "brushes")
            bundle = Path(directory) / "resources.csr"
            manager.export_bundle(bundle)
            restored = ResourceManager(Path(directory) / "restored")
            self.assertEqual(len(restored.import_bundle(bundle)), 1)
            self.assertEqual(len(manager.catalog("brushes")), 1)
            self.assertTrue(imported.is_file())
            hostile = Path(directory) / "hostile.csr"
            with zipfile.ZipFile(hostile, "w") as archive:
                archive.writestr("manifest.json", '{"version":1,"resources":[]}' )
                archive.writestr("resources/brushes/../../evil.csbr", b"evil")
            with self.assertRaises(ValueError):
                restored.import_bundle(hostile)

    def test_ui_colors_are_palette_tokens(self):
        pattern = re.compile(r"#[0-9a-fA-F]{6}")
        root = Path(__file__).resolve().parents[1] / "UI"
        violations = []
        for path in root.rglob("*.py"):
            if path.name == "palette.py":
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and "COLOR_LITERAL_OK" not in line:
                    violations.append(f"{path}:{line_number}")
        self.assertEqual(violations, [])

    def test_adjustments_selection_and_liquify_are_available(self):
        image = QImage(16, 16, QImage.Format.Format_RGBA8888)
        image.fill(QColor(80, 100, 120, 255))
        identity = apply_curves(image, CurvesAdjustment(((0, 0), (255, 255))))
        self.assertEqual(identity.pixelColor(0, 0), QColor(80, 100, 120, 255))
        inverted = apply_curves(image, CurvesAdjustment(((0, 255), (255, 0))))
        self.assertEqual(inverted.pixelColor(0, 0).red(), 175)
        leveled = apply_levels(image, LevelsAdjustment(gamma=1.8))
        self.assertGreater(leveled.pixelColor(0, 0).red(), 80)
        hue_shifted = apply_hue_saturation(image, HueSaturationAdjustment(hue=180, saturation=20))
        self.assertNotEqual(hue_shifted.pixelColor(0, 0).rgb(), image.pixelColor(0, 0).rgb())
        selection = SelectionMask(16, 16)
        selection.select_all()
        selection.contract(2)
        selection.feather(1)
        self.assertFalse(selection.is_empty())
        gradient = QImage(16, 16, QImage.Format.Format_RGBA8888)
        for y in range(16):
            for x in range(16):
                gradient.setPixelColor(x, y, QColor(x * 12, 0, 0, 255))
        warped = TransformTool.liquify(gradient, [LiquifyStroke(8, 8, 2, 0)])
        self.assertEqual(warped.size(), image.size())
        self.assertNotEqual(warped.pixelColor(9, 8).red(), gradient.pixelColor(9, 8).red())
        self.assertEqual(TransformTool.warp(image, [WarpControl(8, 8, 1, 1)]).size(), image.size())
        self.assertFalse(apply_layer_effects(image, [{"type": "stroke", "size": 2}]).isNull())

    def test_extended_adjustments_preserve_alpha_and_change_pixels(self):
        image = QImage(4, 1, QImage.Format.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(80, 30, 20, 77))
        image.setPixelColor(1, 0, QColor(220, 80, 30, 255))
        image.setPixelColor(2, 0, QColor(30, 180, 80, 255))
        image.setPixelColor(3, 0, QColor(120, 120, 120, 255))
        transforms = (
            apply_exposure(image, ExposureAdjustment(exposure=1.0)),
            apply_vibrance(image, VibranceAdjustment(vibrance=80.0)),
            apply_invert(image),
            apply_threshold(image, 100),
            apply_posterize(image, 3),
            apply_color_balance(image, ColorBalanceAdjustment(shadows=(20, -10, -10))),
        )
        for transformed in transforms:
            self.assertEqual(transformed.pixelColor(0, 0).alpha(), 77)
            self.assertNotEqual(transformed.pixelColor(1, 0).rgb(), image.pixelColor(1, 0).rgb())

    def test_selective_parametric_and_luminosity_adjustments(self):
        image = QImage(3, 1, QImage.Format.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(220, 40, 40, 255))
        image.setPixelColor(1, 0, QColor(120, 120, 120, 255))
        image.setPixelColor(2, 0, QColor(240, 240, 240, 255))
        selective = apply_selective_color(image, SelectiveColorAdjustment(
            channels={"reds": (0.0, 0.0, 0.0, 40.0)}))
        self.assertLess(selective.pixelColor(0, 0).red(), image.pixelColor(0, 0).red())
        parametric = apply_parametric_curves(image, ParametricCurvesAdjustment(midtones=40.0))
        self.assertNotEqual(parametric.pixelColor(1, 0).rgb(), image.pixelColor(1, 0).rgb())
        masked = apply_adjustment(image, AdjustmentLayerSpec(
            kind="invert", luminosity_mask=LuminosityMaskAdjustment(mode="shadows")))
        self.assertNotEqual(masked.pixelColor(0, 0).rgb(), image.pixelColor(0, 0).rgb())
        self.assertEqual(masked.pixelColor(2, 0), image.pixelColor(2, 0))

    def test_edit_save_reload_soak_keeps_document_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "soak.nebula"
            document = Document(64, 64, 300, None)
            for cycle in range(12):
                layer = document.get_active_layer()
                layer.image.fill(QColor(cycle * 7, 20, 40, 255))
                layer.mark_image_cache_dirty()
                layer.commit_image_cache()
                if cycle % 3 == 0:
                    document.add_adjustment_layer("levels", spec={"kind": "levels", "levels": {"gamma": 1.1}})
                self.assertTrue(NebulaFormat.save(document, path))
                reopened = NebulaFormat.load(path)
                self.assertIsNotNone(reopened)
                document = reopened
            for layer in document.layers:
                layer.tile_store.close()

    def test_color_profile_round_trip_defaults_to_srgb(self):
        image = QImage(4, 4, QImage.Format.Format_RGBA8888)
        image.fill(QColor(10, 20, 30, 255))
        self.assertEqual(profile_from_image(image).name, SRGB.name)
        self.assertFalse(convert_to_profile(image, SRGB).isNull())

    def test_adjustment_layer_changes_the_tile_projection(self):
        QApplication.instance() or QApplication([])
        canvas = Canvas()
        layer = canvas.document.get_active_layer()
        layer.image.fill(QColor(64, 64, 64, 255))
        layer.mark_image_cache_dirty()
        layer.commit_image_cache()
        canvas.document.add_adjustment_layer(
            "levels", spec={"kind": "levels", "levels": {"gamma": 2.0}})
        entries, pending = canvas._tile_projection_layers(0, 0, QRect(0, 0, 64, 64))
        self.assertFalse(pending)
        self.assertEqual(len(entries), 1)
        self.assertNotEqual(entries[0].image.pixelColor(0, 0).red(), 64)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
