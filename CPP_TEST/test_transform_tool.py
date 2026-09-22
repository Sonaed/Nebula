from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

from DOCUMENTS.selection import SelectionMask, SelectionOperation
from TOOLS.selection_tools import SelectionTools
from TOOLS.transform_tool import TransformSpec, TransformTool
from CORE.native_bridge import load_creative_core


def _reference_transform(image, spec, selection=None):
    use_selection = selection is not None and not selection.is_empty()
    bounds = QRectF(selection.bounds() if use_selection else image.rect())
    source = QImage(image.size(), QImage.Format.Format_ARGB32)
    source.fill(0)
    output = image.copy() if use_selection else QImage(
        image.size(), QImage.Format.Format_ARGB32)
    if not use_selection:
        output.fill(0)
    if use_selection:
        rect = selection.bounds()
        for y in range(rect.top(), rect.bottom() + 1):
            for x in range(rect.left(), rect.right() + 1):
                if selection.image.pixelColor(x, y).alpha() > 0:
                    source.setPixelColor(x, y, image.pixelColor(x, y))
                    output.setPixelColor(x, y, QColor(0, 0, 0, 0))
    else:
        source = image

    center = bounds.center()
    transform = QTransform()
    transform.translate(center.x() + spec.translate_x,
                        center.y() + spec.translate_y)
    transform.rotate(spec.rotation)
    transform.scale(spec.scale_x, spec.scale_y)
    transform.translate(-center.x(), -center.y())
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setTransform(transform)
    painter.drawImage(0, 0, source)
    painter.end()
    transformed_selection = None
    if use_selection:
        transformed_selection = QImage(selection.image.size(),
                                       QImage.Format.Format_ARGB32)
        transformed_selection.fill(0)
        painter = QPainter(transformed_selection)
        painter.setTransform(transform)
        painter.drawImage(0, 0, selection.image)
        painter.end()
    return output, transformed_selection


class TransformToolTests(unittest.TestCase):
    def test_native_selection_transform_matches_independent_reference(self) -> None:
        native = load_creative_core()
        self.assertIsNotNone(native)
        image = QImage(40, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        image.setPixelColor(4, 6, QColor(220, 35, 60, 190))
        image.setPixelColor(30, 8, QColor("blue"))
        selection = SelectionMask(40, 32)
        mask = QImage(40, 32, QImage.Format.Format_ARGB32)
        mask.fill(0)
        mask.setPixelColor(4, 6, QColor(255, 255, 255, 255))
        selection.combine(mask, SelectionOperation.REPLACE)
        spec = TransformSpec(translate_x=7, translate_y=2, scale_x=1.15,
                             scale_y=0.9, rotation=8)
        actual = TransformTool().apply(image, spec, selection)
        expected_image, expected_selection = _reference_transform(image, spec, selection)
        self.assertEqual(bytes(actual.image.constBits()), bytes(expected_image.constBits()))
        self.assertEqual(bytes(actual.selection_image.constBits()),
                         bytes(expected_selection.constBits()))

    def test_transform_requires_native_engine(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(0)
        with patch("TOOLS.transform_tool.transform_raster_native", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                TransformTool().apply(image, TransformSpec())

    def test_translate_selected_pixels_only(self) -> None:
        image = QImage(12, 8, QImage.Format.Format_ARGB32); image.fill(0)
        image.setPixelColor(2, 2, QColor("red")); image.setPixelColor(9, 2, QColor("blue"))
        selection = SelectionMask(12, 8)
        selection.combine(SelectionTools.shape_mask("select_rectangle", QSize(12, 8), [QPoint(1, 1), QPoint(4, 4)]), SelectionOperation.REPLACE)
        result = TransformTool().apply(image, TransformSpec(translate_x=3), selection)
        self.assertEqual(result.image.pixelColor(2, 2).alpha(), 0)
        self.assertGreater(result.image.pixelColor(5, 2).red(), 200)
        self.assertGreater(result.image.pixelColor(9, 2).blue(), 200)
        self.assertGreater(result.selection_image.pixelColor(5, 2).alpha(), 0)

    def test_horizontal_flip_full_layer(self) -> None:
        image = QImage(8, 4, QImage.Format.Format_ARGB32); image.fill(0)
        image.setPixelColor(1, 1, QColor("green"))
        result = TransformTool().apply(image, TransformSpec(scale_x=-1))
        self.assertGreater(result.image.pixelColor(6, 1).green(), 100)


if __name__ == "__main__":
    unittest.main()
