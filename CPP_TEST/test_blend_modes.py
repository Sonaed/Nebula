from __future__ import annotations

import unittest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from DOCUMENTS.document import Document
from DOCUMENTS.blend_modes import BLEND_MODES, composite_document, composite_layers
from DOCUMENTS.canvas_objects import EditableText
from CPP_TEST.legacy_blend_reference import composite_reference, _qimage_rgba
from DOCUMENTS.blend_presets import BLEND_PARAMS, BlendPresetManager
from DOCUMENTS.layer_manager import LayerManager


class BlendModeTests(unittest.TestCase):
    def test_editable_alpha_mask_is_applied_by_native_document_composition(self) -> None:
        document = Document(2, 1)
        layer = document.get_active_layer()
        layer.image.fill(QColor(220, 80, 40, 200))
        mask = QImage(2, 1, QImage.Format.Format_ARGB32)
        mask.fill(QColor(255, 255, 255, 255))
        mask.setPixelColor(0, 0, QColor(255, 255, 255, 128))
        layer.ensure_alpha_mask().set_tile(0, 0, mask)

        result = composite_document(document)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 100)
        self.assertEqual(result.pixelColor(1, 0).alpha(), 200)

    def test_clipping_layer_is_masked_by_nearest_unclipped_layer(self) -> None:
        document = Document(2, 1)
        base = document.get_active_layer()
        base.image.fill(QColor(20, 30, 40, 0))
        base.image.setPixelColor(0, 0, QColor(20, 30, 40, 128))
        top = document.add_layer("Écrêté")
        top.image.fill(QColor(240, 30, 10, 255))
        top.clipping = True

        result = composite_layers(2, 1, document.layers)
        self.assertEqual(result.pixelColor(0, 0), QColor(167, 30, 20, 128))
        self.assertEqual(result.pixelColor(1, 0).alpha(), 0)

    def test_composite_cache_invalidates_when_clipping_changes(self) -> None:
        document = Document(1, 1)
        document.get_active_layer().image.fill(QColor(20, 30, 40, 128))
        top = document.add_layer("Top")
        top.image.fill(QColor(240, 30, 10, 255))
        unclipped = composite_document(document).pixelColor(0, 0)
        top.clipping = True
        clipped = composite_document(document).pixelColor(0, 0)
        self.assertEqual(unclipped.alpha(), 255)
        self.assertEqual(clipped.alpha(), 128)
        self.assertNotEqual(unclipped, clipped)

    def test_merge_down_bakes_clipped_upper_layer_without_changing_appearance(self) -> None:
        document = Document(1, 1)
        base = document.get_active_layer()
        base.image.fill(QColor(20, 30, 40, 128))
        upper = document.add_layer("Clipped")
        upper.image.fill(QColor(240, 30, 10, 255))
        upper.clipping = True
        before = composite_document(document).pixelColor(0, 0)

        self.assertTrue(LayerManager(document).merge_down(1))
        after = composite_document(document).pixelColor(0, 0)
        self.assertEqual(after, before)
        self.assertFalse(document.layers[0].clipping)

    def test_merge_down_refuses_lower_layer_clipped_to_external_base(self) -> None:
        document = Document(1, 1)
        base = document.get_active_layer()
        base.image.fill(QColor(20, 30, 40, 128))
        clipped = document.add_layer("Clipped base")
        clipped.image.fill(QColor(240, 30, 10, 255))
        clipped.clipping = True
        upper = document.add_layer("Upper")
        upper.image.fill(QColor(10, 220, 30, 128))
        before = composite_document(document).pixelColor(0, 0)

        self.assertFalse(LayerManager(document).merge_down(2))
        self.assertEqual(len(document.layers), 3)
        self.assertEqual(composite_document(document).pixelColor(0, 0), before)

    def test_simple_merge_matches_qt_composition_for_every_mode(self) -> None:
        from DOCUMENTS.blend_modes import composition_mode

        base_color = QColor(42, 126, 213, 203)
        top_color = QColor(223, 71, 119, 177)
        # HSL modes deliberately use the parameterized color compositor even
        # without explicit parameters; this test covers the direct Qt modes.
        for mode in BLEND_MODES[:12]:
            with self.subTest(mode=mode):
                document = Document(3, 2)
                bottom = document.get_active_layer()
                bottom.image.fill(base_color)
                upper = document.add_layer("Top")
                upper.image.fill(top_color)
                upper.opacity = 0.63
                upper.blend_mode = mode

                expected = bottom.image.copy()
                painter = QPainter(expected)
                painter.setCompositionMode(composition_mode(mode))
                painter.setOpacity(upper.opacity)
                painter.drawImage(0, 0, upper.image)
                painter.end()

                self.assertTrue(LayerManager(document).merge_down(1))
                actual = document.layers[0].image
                for y in range(actual.height()):
                    for x in range(actual.width()):
                        self.assertEqual(actual.pixel(x, y), expected.pixel(x, y))

    def test_standard_composite_refuses_missing_core_without_python_renderer(self) -> None:
        layer = Document(2, 1).get_active_layer()
        layer.image.fill(QColor(90, 30, 210, 160))
        before = layer.image.copy()
        with patch("DOCUMENTS.blend_modes.composite_layers_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                composite_layers(2, 1, [layer])
        self.assertEqual(layer.image.pixelColor(0, 0), before.pixelColor(0, 0))

    def test_advanced_composite_refuses_missing_core_without_python_renderer(self) -> None:
        document = Document(1, 1)
        document.get_active_layer().image.fill(QColor(20, 30, 40, 128))
        upper = document.add_layer("Clipped")
        upper.image.fill(QColor(240, 30, 10, 255))
        upper.clipping = True
        before = [layer.image.copy() for layer in document.layers]
        with patch("DOCUMENTS.blend_modes.composite_layers_advanced", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                composite_layers(1, 1, document.layers)
        for layer, snapshot in zip(document.layers, before):
            self.assertEqual(layer.image.pixelColor(0, 0), snapshot.pixelColor(0, 0))

    def test_document_text_refuses_python_raster_fallback(self) -> None:
        document = Document(160, 80)
        document.text_objects.append(EditableText(
            "Nebula", QPointF(8, 8), QColor(240, 210, 120), QFont("Sans Serif", 18)
        ))
        with patch("DOCUMENTS.blend_modes.draw_text_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                composite_document(document)

    def test_document_text_is_rasterized_by_creative_core(self) -> None:
        _app = QApplication.instance() or QApplication([])
        document = Document(160, 80)
        document.get_active_layer().image.fill(QColor(0, 0, 0, 0))
        document.text_objects.append(EditableText(
            "Nebula", QPointF(8, 8), QColor(240, 210, 120), QFont("Sans Serif", 18)
        ))
        result = composite_document(document)
        self.assertTrue(any(
            result.pixelColor(x, y).alpha() > 0
            for y in range(result.height())
            for x in range(result.width())
        ))

    def test_native_clipping_and_parameterized_composite_matches_reference(self) -> None:
        document = Document(7, 5)
        base = document.get_active_layer()
        clipped = document.add_layer("Clipped blend")
        overlay = document.add_layer("Overlay base")
        upper_clipped = document.add_layer("Clipped color")
        layers = (base, clipped, overlay, upper_clipped)
        for index, layer in enumerate(layers):
            for y in range(document.height):
                for x in range(document.width):
                    layer.image.setPixelColor(
                        x, y,
                        QColor((x * 37 + index * 53) % 256,
                               (y * 61 + index * 29) % 256,
                               (x * 17 + y * 23 + index * 47) % 256,
                               (x * 31 + y * 43 + index * 59) % 256),
                    )
        clipped.blend_mode = "multiply"
        clipped.opacity = 0.73
        clipped.blend_parameters = {"gamma": 1.37, "intensity": 0.82,
                                    "mix_normal": 0.14, "opacity": 0.91}
        clipped.clipping = True
        overlay.blend_mode = "soft_light"
        overlay.blend_parameters = {"softness": 0.64, "intensity": 0.76}
        upper_clipped.blend_mode = "hue"
        upper_clipped.blend_parameters = {"hue_shift": 23, "saturation_boost": 1.2}
        upper_clipped.clipping = True

        native = composite_layers(document.width, document.height, layers)
        reference = composite_reference(document.width, document.height, layers)
        for y in range(document.height):
            for x in range(document.width):
                actual, expected = native.pixelColor(x, y), reference.pixelColor(x, y)
                self.assertLessEqual(max(abs(actual.red() - expected.red()),
                                         abs(actual.green() - expected.green()),
                                         abs(actual.blue() - expected.blue()),
                                         abs(actual.alpha() - expected.alpha())), 1)

    def test_all_requested_modes_are_registered(self) -> None:
        self.assertIn("multiply", BLEND_MODES)
        self.assertIn("luminosity", BLEND_MODES)

    def test_blend_parameter_definitions_include_mode_and_common_uniforms(self) -> None:
        expected_mode_keys = {
            "multiply": ["intensity", "gamma", "mix_normal"],
            "screen": ["intensity", "gamma", "mix_normal"],
            "overlay": ["intensity", "pivot", "mix_normal"],
            "hard_light": ["intensity", "pivot", "mix_normal"],
            "color_dodge": ["intensity", "clamp", "mix_normal"],
            "color_burn": ["intensity", "clamp", "mix_normal"],
            "soft_light": ["intensity", "softness", "mix_normal"],
            "hue": ["intensity", "hue_shift", "saturation_boost"],
            "saturation": ["intensity", "hue_shift", "saturation_boost"],
            "color": ["intensity", "hue_shift", "saturation_boost"],
            "luminosity": ["intensity", "hue_shift", "saturation_boost"],
            "difference": ["intensity", "offset", "mix_normal"],
            "exclusion": ["intensity", "offset", "mix_normal"],
        }
        for mode, mode_keys in expected_mode_keys.items():
            definitions = BLEND_PARAMS[mode]
            keys = [item["key"] for item in definitions]
            self.assertEqual(keys, mode_keys + ["opacity", "opposite_mix"])
            self.assertTrue(all({"name", "min", "max", "default", "uniform"} <= set(item) for item in definitions))

    def test_multiply_composes_visible_layers(self) -> None:
        document = Document(2, 2)
        bottom = document.get_active_layer(); bottom.image.fill(QColor(200, 200, 200))
        top = document.add_layer("Top"); top.image.fill(QColor(128, 128, 128)); top.blend_mode = "multiply"
        color = composite_document(document).pixelColor(0, 0)
        self.assertLess(color.red(), 150)
        self.assertEqual(color.alpha(), 255)

    def test_blend_presets_are_read_only_by_default_and_csbl_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BlendPresetManager(directory)
            self.assertTrue(manager.is_builtin("Multiply"))
            preset = manager.load("Multiply")
            self.assertEqual(preset["parameters"]["gamma"], 1.0)
            self.assertFalse(manager.save("Multiply", preset))
            self.assertTrue(manager.duplicate("Multiply", "Warm Multiply"))
            path = Path(directory) / "warm.csbl"
            self.assertTrue(manager.export_csbl("Warm Multiply", path))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {"blend.json", "preview.png"})
            other = BlendPresetManager(Path(directory) / "other")
            self.assertEqual(other.import_csbl(path), "Warm Multiply")
            self.assertEqual(other.load("Warm Multiply"), manager.load("Warm Multiply"))

    def test_blend_preset_rejects_out_of_range_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BlendPresetManager(directory)
            preset = manager.load("Multiply")
            preset["parameters"]["gamma"] = 9.0
            self.assertFalse(manager.save("Custom", preset))

    def test_layer_blend_parameters_change_composite_and_support_mix(self) -> None:
        document = Document(1, 1)
        document.get_active_layer().image.fill(QColor(200, 180, 160))
        top = document.add_layer("Top")
        top.image.fill(QColor(128, 128, 128))
        top.blend_mode = "multiply"
        default = composite_document(document).pixelColor(0, 0)
        top.blend_parameters = {"intensity": 0.0}
        normal_mix = composite_document(document).pixelColor(0, 0)
        self.assertEqual(normal_mix, QColor(128, 128, 128))
        self.assertNotEqual(default, normal_mix)
        top.blend_parameters = {"intensity": 1.0, "opposite_mix": 1.0}
        opposite = composite_document(document).pixelColor(0, 0)
        self.assertGreater(opposite.red(), default.red())

    def test_parameterized_compositor_renders_every_registered_mode(self) -> None:
        defaults = BlendPresetManager.defaults()
        document = Document(2, 2)
        document.get_active_layer().image.fill(QColor(90, 140, 210))
        top = document.add_layer("Mode")
        top.image.fill(QColor(180, 80, 120, 200))
        for mode in BLEND_MODES:
            with self.subTest(mode=mode):
                top.blend_mode = mode
                top.blend_parameters = defaults[mode.replace("_", " ").title()]["parameters"]
                result = composite_document(document)
                self.assertEqual((result.width(), result.height()), (2, 2))
                self.assertEqual(result.pixelColor(0, 0).alpha(), 255)

    def test_native_parameterized_merge_matches_python_reference(self) -> None:
        document = Document(5, 3)
        bottom = document.get_active_layer()
        top = document.add_layer("Blend")
        for y in range(3):
            for x in range(5):
                bottom.image.setPixelColor(x, y, QColor(17 + x * 31, 49 + y * 57,
                                                         230 - x * 19, 65 + x * 37))
                top.image.setPixelColor(x, y, QColor(241 - y * 43, 13 + x * 29,
                                                      33 + y * 61, 80 + y * 53))
        bottom.image.setPixelColor(0, 0, QColor(0, 0, 0, 255))
        top.image.setPixelColor(0, 0, QColor(0, 0, 0, 255))
        bottom.image.setPixelColor(1, 0, QColor(255, 255, 255, 255))
        top.image.setPixelColor(1, 0, QColor(0, 0, 0, 255))
        bottom.image.setPixelColor(2, 0, QColor(0, 0, 0, 255))
        top.image.setPixelColor(2, 0, QColor(255, 255, 255, 255))
        top.opacity = 0.73
        parameters = {
            "opacity": 0.81, "opposite_mix": 0.18, "intensity": 0.77,
            "gamma": 1.35, "mix_normal": 0.12, "pivot": 0.43,
            "clamp": 0.87, "softness": 0.62, "hue_shift": 27.0,
            "saturation_boost": 1.24, "offset": 0.08,
        }
        for mode in BLEND_MODES:
            with self.subTest(mode=mode):
                top.blend_mode = mode
                top.blend_parameters = dict(parameters)
                native = composite_document(document)
                reference = composite_reference(5, 3, [bottom, top])
                for y in range(3):
                    for x in range(5):
                        actual = native.pixelColor(x, y)
                        expected = reference.pixelColor(x, y)
                        self.assertLessEqual(max(abs(actual.red() - expected.red()),
                                                 abs(actual.green() - expected.green()),
                                                 abs(actual.blue() - expected.blue()),
                                                 abs(actual.alpha() - expected.alpha())), 2)

    def test_merge_down_preserves_parameterized_blend_appearance(self) -> None:
        document = Document(2, 2)
        document.get_active_layer().image.fill(QColor(205, 185, 160))
        upper = document.add_layer("Overlay")
        upper.image.fill(QColor(130, 170, 210, 220))
        upper.blend_mode = "soft_light"
        upper.blend_parameters = {"intensity": 0.75, "softness": 0.7, "mix_normal": 0.15}
        before = composite_document(document).pixelColor(0, 0)
        self.assertTrue(LayerManager(document).merge_down(1))
        after = composite_document(document).pixelColor(0, 0)
        self.assertLessEqual(abs(before.red() - after.red()), 1)
        self.assertLessEqual(abs(before.green() - after.green()), 1)
        self.assertLessEqual(abs(before.blue() - after.blue()), 1)

    def test_merge_down_routes_hsl_lower_layer_through_native_compositor(self) -> None:
        document = Document(2, 2)
        lower = document.get_active_layer()
        lower.image.fill(QColor(210, 70, 40, 180))
        lower.blend_mode = "hue"
        upper = document.add_layer("Upper")
        upper.image.fill(QColor(40, 130, 220, 190))
        expected = composite_layers(2, 2, [lower, upper])

        self.assertTrue(LayerManager(document).merge_down(1))
        self.assertEqual(document.layers[0].image.pixelColor(0, 0),
                         expected.pixelColor(0, 0))

    def test_tiled_blend_render_covers_canvas_edges(self) -> None:
        document = Document(520, 520)
        document.get_active_layer().image.fill(QColor(200, 100, 50))
        top = document.add_layer("Top")
        top.image.fill(QColor(80, 160, 220, 190))
        top.blend_mode = "overlay"
        top.blend_parameters = {"intensity": 0.8, "pivot": 0.4, "mix_normal": 0.1}
        result = composite_document(document)
        self.assertEqual(result.pixelColor(0, 0), result.pixelColor(519, 519))
        self.assertEqual(result.pixelColor(519, 519).alpha(), 255)

    def test_direct_qimage_pixel_reader_handles_supported_formats(self) -> None:
        color = QColor(180, 90, 30, 128)
        formats = (
            QImage.Format.Format_ARGB32,
            QImage.Format.Format_ARGB32_Premultiplied,
            QImage.Format.Format_RGB32,
            QImage.Format.Format_RGBA8888,
            QImage.Format.Format_RGBA8888_Premultiplied,
        )
        for image_format in formats:
            with self.subTest(format=image_format):
                image = QImage(3, 2, image_format)
                image.fill(color)
                pixels = _qimage_rgba(image, 1, 0, 2, 2)
                pixel = image.pixelColor(1, 0)
                expected = [pixel.redF(), pixel.greenF(), pixel.blueF(), pixel.alphaF()]
                for actual, value in zip(pixels[0, 0], expected):
                    self.assertAlmostEqual(float(actual), value, delta=0.01)


if __name__ == "__main__":
    unittest.main()
