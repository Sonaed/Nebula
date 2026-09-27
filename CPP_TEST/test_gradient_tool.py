from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

from CORE.native_bridge import load_creative_core
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


if __name__ == "__main__":
    unittest.main()
