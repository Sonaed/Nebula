from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor, QImage

from TOOLS.move_tool import MoveTool


class MoveToolTests(unittest.TestCase):
    def test_integer_translation_clips_and_preserves_exact_pixels(self) -> None:
        image = QImage(5, 4, QImage.Format.Format_ARGB32)
        image.fill(0)
        image.setPixelColor(1, 1, QColor(240, 20, 80, 130))
        image.setPixelColor(3, 2, QColor(10, 190, 220, 255))

        MoveTool().apply(image, QPointF(1, -1))

        self.assertEqual(image.pixelColor(2, 0), QColor(240, 20, 80, 130))
        self.assertEqual(image.pixelColor(4, 1), QColor(10, 190, 220, 255))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(3, 3).alpha(), 0)

    def test_translation_beyond_canvas_returns_transparent_image(self) -> None:
        image = QImage(3, 2, QImage.Format.Format_RGBA8888)
        image.fill(QColor("red"))

        MoveTool().apply(image, QPointF(50, -20))

        self.assertTrue(all(image.pixelColor(x, y).alpha() == 0
                            for y in range(image.height())
                            for x in range(image.width())))

    def test_missing_native_engine_refuses_without_mutating_pixels(self) -> None:
        image = QImage(4, 3, QImage.Format.Format_ARGB32)
        image.fill(QColor(14, 80, 190, 127))
        before = image.copy()
        with patch("TOOLS.move_tool.translate_image_native", return_value=None):
            self.assertFalse(MoveTool().apply(image, QPointF(1, 1)))
        for y in range(image.height()):
            for x in range(image.width()):
                self.assertEqual(image.pixelColor(x, y), before.pixelColor(x, y))

    def test_failed_native_move_keeps_pointer_baseline_for_retry(self) -> None:
        tool = MoveTool()
        tool.begin(QPoint(1, 1))
        image = QImage(4, 3, QImage.Format.Format_ARGB32)
        image.fill(0)
        with patch("TOOLS.move_tool.translate_image_native", return_value=None):
            self.assertFalse(tool.move(image, QPoint(2, 1)))
        self.assertEqual(tool.last_position.x(), 1)


if __name__ == "__main__":
    unittest.main()
