from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QRadialGradient,
                          QConicalGradient, QGradient, QPainter)

from CORE.native_bridge import apply_gradient_native, load_creative_core
from TOOLS.gradient_tool import GradientTool


class GradientToolTests(unittest.TestCase):
    def test_foreground_fades_across_the_drag_axis(self) -> None:
        image = QImage(101, 1, QImage.Format.Format_ARGB32)
        image.fill(0)

        changed = GradientTool().apply(
            image, QPoint(0, 0), QPoint(100, 0), QColor(240, 40, 20)
        )

        self.assertEqual(changed, image.rect())
        self.assertGreater(image.pixelColor(0, 0).alpha(), 240)
        self.assertGreater(image.pixelColor(50, 0).alpha(), 100)
        self.assertLess(image.pixelColor(100, 0).alpha(), 10)

    def test_zero_length_drag_is_valid(self) -> None:
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(0)
        self.assertFalse(
            GradientTool().apply(
                image, QPoint(1, 1), QPoint(1, 1), QColor("black")
            ).isEmpty()
        )

    def test_native_gradient_matches_qt_reference(self) -> None:
        library = load_creative_core()
        if library is None:
            self.skipTest("CreativeCore bridge is not built")

        for image_format in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            with self.subTest(image_format=image_format):
                expected = QImage(67, 43, image_format)
                expected.fill(QColor(30, 80, 140, 170))
                actual = expected.copy()
                start, end = QPoint(5, 39), QPoint(61, 4)
                color = QColor(230, 45, 110, 205)

                gradient = QLinearGradient(start, end)
                transparent = QColor(color)
                transparent.setAlpha(0)
                gradient.setColorAt(0.0, color)
                gradient.setColorAt(1.0, transparent)
                painter = QPainter(expected)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.fillRect(expected.rect(), gradient)
                painter.end()

                GradientTool().apply(actual, start, end, color)
                self.assertEqual(actual, expected)

    def test_gradient_requires_native_renderer_without_mutating_on_failure(self) -> None:
        image = QImage(9, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("navy"))
        before = image.copy()
        with patch("TOOLS.gradient_tool.apply_linear_gradient_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                GradientTool().apply(image, QPoint(0, 0), QPoint(8, 6), QColor("red"))
        self.assertEqual(image, before)

    def test_two_color_gradients_match_qt_for_all_geometries_and_spreads(self) -> None:
        """Exercise actual native geometry, reversal, opacity and both layouts."""
        for image_format in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            for geometry in GradientTool.GEOMETRIES:
                for spread_name, spread in (
                    ("pad", QGradient.Spread.PadSpread),
                    ("repeat", QGradient.Spread.RepeatSpread),
                    ("reflect", QGradient.Spread.ReflectSpread),
                ):
                    with self.subTest(format=image_format, geometry=geometry, spread=spread_name):
                        expected = QImage(131, 83, image_format)
                        expected.fill(QColor(30, 80, 140, 170))
                        actual = expected.copy()
                        start, end = QPointF(30, 40), QPointF(60, 40)
                        foreground, background = QColor(220, 40, 80, 210), QColor(20, 160, 200, 190)
                        if geometry == "radial":
                            reference = QRadialGradient(start, 30)
                        elif geometry == "conical":
                            reference = QConicalGradient(start, 0)
                        else:
                            reference = QLinearGradient(start, end)
                        reference.setColorAt(0.0, background)
                        reference.setColorAt(1.0, foreground)
                        reference.setSpread(spread)
                        painter = QPainter(expected)
                        painter.setOpacity(0.65)
                        painter.fillRect(expected.rect(), reference)
                        painter.end()
                        tool = GradientTool()
                        tool.geometry, tool.spread = geometry, spread_name
                        tool.color_mode, tool.end_color = "color", background
                        tool.reverse, tool.opacity = True, 0.65
                        tool.apply(actual, start, end, foreground)
                        self.assertEqual(actual, expected)

    def test_radial_distance_is_symmetric_and_reverse_flips_stops(self) -> None:
        tool = GradientTool()
        tool.geometry = "radial"
        image = QImage(101, 101, QImage.Format.Format_ARGB32)
        image.fill(0)
        tool.apply(image, QPointF(50.5, 50.5), QPointF(90.5, 50.5), QColor("red"))
        self.assertGreater(image.pixelColor(50, 50).alpha(), 250)
        self.assertEqual(image.pixelColor(30, 50), image.pixelColor(50, 30))
        self.assertEqual(image.pixelColor(90, 50).alpha(), 0)
        image.fill(0)
        tool.reverse = True
        tool.apply(image, QPointF(50.5, 50.5), QPointF(90.5, 50.5), QColor("red"))
        self.assertLess(image.pixelColor(50, 50).alpha(), 5)
        self.assertGreater(image.pixelColor(90, 50).alpha(), 250)

    def test_feathered_selection_masks_gradient_before_source_over(self) -> None:
        for image_format in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            with self.subTest(image_format=image_format):
                actual = QImage(270, 143, image_format)
                actual.fill(QColor(30, 80, 140, 170))
                actual.setPixelColor(1, 1, QColor(117, 39, 61, 0))
                actual.setPixelColor(190, 50, QColor(117, 39, 61, 0))
                expected = actual.copy()
                mask = QImage(actual.size(), QImage.Format.Format_ARGB32)
                mask.fill(0)
                # The two selected islands straddle multiple 128px tiles and
                # include feathered coverage over pre-existing translucent paint.
                painter = QPainter(mask)
                painter.fillRect(3, 3, 140, 132, QColor(255, 255, 255, 128))
                painter.fillRect(220, 20, 44, 117, QColor("white"))
                painter.end()
                gradient = QLinearGradient(QPoint(3, 3), QPoint(230, 95))
                foreground, background = QColor(230, 40, 100, 210), QColor(20, 180, 160, 150)
                gradient.setColorAt(0, foreground)
                gradient.setColorAt(1, background)
                overlay = QImage(actual.size(), QImage.Format.Format_ARGB32_Premultiplied)
                overlay.fill(0)
                painter = QPainter(overlay)
                painter.fillRect(overlay.rect(), gradient)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                painter.drawImage(0, 0, mask)
                painter.end()
                painter = QPainter(expected)
                painter.setOpacity(.7)
                painter.drawImage(0, 0, overlay)
                painter.end()
                tool = GradientTool()
                tool.color_mode, tool.end_color, tool.opacity = "color", background, .7
                tool.apply(actual, QPoint(3, 3), QPoint(230, 95), foreground, selection_mask=mask)
                # The bounded renderer translates each tile; Qt's fixed-point
                # gradient interpolation may differ by one channel unit from
                # a full-frame render. Check every selected pixel, and demand
                # exact preservation of every unselected pixel.
                for y in range(actual.height()):
                    for x in range(actual.width()):
                        if mask.pixelColor(x, y).alpha():
                            result = actual.pixelColor(x, y).getRgb()
                            reference = expected.pixelColor(x, y).getRgb()
                            self.assertLessEqual(max(abs(a - b) for a, b in zip(result, reference)), 2)
                        elif (x, y) not in ((1, 1), (190, 50)):
                            self.assertEqual(actual.pixelColor(x, y), QColor(30, 80, 140, 170))
                self.assertEqual(actual.pixelColor(1, 1), QColor(117, 39, 61, 0))
                self.assertEqual(actual.pixelColor(190, 50), QColor(117, 39, 61, 0))

    def test_empty_selection_and_zero_opacity_are_noops(self) -> None:
        image = QImage(9, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("navy"))
        before = image.copy()
        mask = QImage(image.size(), QImage.Format.Format_ARGB32)
        mask.fill(0)
        tool = GradientTool()
        tool.apply(image, QPoint(), QPoint(8, 6), QColor("red"), selection_mask=mask)
        self.assertEqual(image, before)
        tool.opacity = 0.0
        tool.apply(image, QPoint(), QPoint(8, 6), QColor("red"))
        self.assertEqual(image, before)

    def test_extended_gradient_requires_native_renderer_without_mutating(self) -> None:
        image = QImage(9, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("navy"))
        before = image.copy()
        tool = GradientTool()
        tool.geometry = "radial"
        with patch("TOOLS.gradient_tool.apply_gradient_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                tool.apply(image, QPoint(), QPoint(8, 6), QColor("red"))
        self.assertEqual(image, before)

    def test_invalid_parameters_are_rejected_before_modifying_pixels(self) -> None:
        image = QImage(9, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("navy"))
        before = image.copy()
        for attribute, value in (("geometry", "invalid"), ("spread", "invalid"),
                                 ("color_mode", "invalid"), ("opacity", float("nan")),
                                 ("opacity", 1.5)):
            tool = GradientTool()
            setattr(tool, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaises(ValueError):
                tool.apply(image, QPoint(), QPoint(8, 6), QColor("red"))
            self.assertEqual(image, before)
        self.assertFalse(apply_gradient_native(
            image, float("nan"), 0, 8, 6, QColor("red"), QColor("blue")))
        self.assertEqual(image, before)
        mask = QImage(1, 1, QImage.Format.Format_ARGB32)
        with self.assertRaises(ValueError):
            GradientTool().apply(image, QPoint(), QPoint(8, 6), QColor("red"),
                                 selection_mask=mask)
        self.assertEqual(image, before)


if __name__ == "__main__":
    unittest.main()
