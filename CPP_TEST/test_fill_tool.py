from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from TOOLS.fill_tool import FillTool


class FillToolTests(unittest.TestCase):
    def test_native_fill_bounds_are_read_only_and_match_fill_result(self) -> None:
        image = QImage(9, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        for x in range(9):
            image.setPixelColor(x, 3, QColor("black"))
        before = image.copy()
        tool = FillTool()
        planned = tool.preview_bounds(image, QPoint(2, 1))
        self.assertEqual(image, before)
        self.assertEqual(planned, image.rect().adjusted(0, 0, 0, -4))
        self.assertEqual(tool.fill(image, QPoint(2, 1), QColor("red")), planned)

    def test_fill_stops_at_opaque_boundary(self) -> None:
        image = QImage(7, 7, QImage.Format.Format_RGBA8888)
        image.fill(QColor("white"))
        for coordinate in range(7):
            image.setPixelColor(coordinate, 3, QColor("black"))

        changed = FillTool().fill(image, QPoint(1, 1), QColor("red"))

        self.assertEqual(changed, image.rect().adjusted(0, 0, 0, -4))
        self.assertEqual(image.pixelColor(1, 1), QColor("red"))
        self.assertEqual(image.pixelColor(1, 5), QColor("white"))
        self.assertEqual(image.pixelColor(1, 3), QColor("black"))

    def test_tolerance_includes_nearby_colors(self) -> None:
        image = QImage(3, 1, QImage.Format.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(100, 100, 100))
        image.setPixelColor(1, 0, QColor(108, 100, 100))
        image.setPixelColor(2, 0, QColor(130, 100, 100))

        FillTool(tolerance=10).fill(image, QPoint(0, 0), QColor("blue"))

        self.assertEqual(image.pixelColor(0, 0), QColor("blue"))
        self.assertEqual(image.pixelColor(1, 0), QColor("blue"))
        self.assertEqual(image.pixelColor(2, 0), QColor(130, 100, 100))

    def test_outside_click_is_a_no_op(self) -> None:
        image = QImage(2, 2, QImage.Format.Format_RGBA8888)
        image.fill(QColor("white"))
        self.assertTrue(FillTool().fill(image, QPoint(-1, 0), QColor("red")).isEmpty())

    def test_fill_requires_native_engine_instead_of_python_fallback(self) -> None:
        image = QImage(2, 2, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        tool = FillTool()
        with patch("TOOLS.fill_tool.native_flood_fill", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                tool.fill(image, QPoint(0, 0), QColor("red"))


if __name__ == "__main__":
    unittest.main()
