from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage

from TOOLS.crop_tool import CropTool


class CropToolTests(unittest.TestCase):
    def test_normalized_crop_is_clamped_to_document(self) -> None:
        rect = CropTool.normalized_rect(QPoint(8, 7), QPoint(-2, 1), QRect(0, 0, 10, 8))
        self.assertEqual(rect, QRect(0, 1, 9, 7))

    def test_crop_geometry_requires_native_engine(self) -> None:
        with patch("TOOLS.crop_tool.native_crop_rect", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                CropTool.normalized_rect(QPoint(), QPoint(1, 1), QRect(0, 0, 10, 10))

    def test_crop_outside_document_is_empty(self) -> None:
        self.assertTrue(CropTool.normalized_rect(QPoint(-5, 2), QPoint(-1, 5),
                                                 QRect(0, 0, 10, 10)).isEmpty())

    def test_crop_preserves_pixels(self) -> None:
        image = QImage(10, 8, QImage.Format.Format_ARGB32)
        image.fill(0); image.setPixelColor(3, 2, QColor("red"))
        result = CropTool.apply(image, QRect(2, 1, 5, 4))
        self.assertEqual(result.size().width(), 5)
        self.assertEqual(result.pixelColor(1, 1), QColor("red"))

    def test_crop_pixels_do_not_fallback_to_qt(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        with patch("TOOLS.crop_tool.crop_image_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                CropTool.apply(image, QRect(1, 1, 4, 4))

    def test_empty_crop_does_not_copy_source_pixels(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        result = CropTool.apply(image, QRect())
        self.assertTrue(result.isNull())


if __name__ == "__main__":
    unittest.main()
