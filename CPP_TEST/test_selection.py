from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from DOCUMENTS.selection import (SelectionMask, SelectionOperation,
                                 _native_selection_library)
from CORE.native_bridge import native_selection_combine
from TOOLS.selection_tools import SelectionTools


def _qt_shape_reference(tool, size, points):
    mask = QImage(size, QImage.Format.Format_ARGB32)
    mask.fill(0)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 255))
    if tool == "select_rectangle":
        painter.drawRect(QRectF(QPointF(points[0]), QPointF(points[-1])).normalized())
    elif tool == "select_ellipse":
        painter.drawEllipse(QRectF(QPointF(points[0]), QPointF(points[-1])).normalized())
    else:
        path = QPainterPath(QPointF(points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(point))
        path.closeSubpath()
        painter.drawPath(path)
    painter.end()
    return mask


class SelectionTests(unittest.TestCase):
    def test_native_selection_primitives_are_exposed_and_match_alpha_semantics(self) -> None:
        library = _native_selection_library()
        self.assertIsNotNone(library)
        selection = SelectionMask(17, 11)
        selection.image.setPixelColor(4, 3, QColor(255, 255, 255, 1))
        selection.image.setPixelColor(16, 10, QColor(255, 255, 255, 255))
        selection.invalidate()
        self.assertEqual(selection.bounds().getRect(), (4, 3, 13, 8))
        self.assertTrue(selection.contains(4, 3))
        self.assertFalse(selection.contains(3, 3))
        self.assertFalse(selection.contains(-1, 3))
        selection.invert()
        self.assertTrue(selection.contains(4, 3))  # alpha 1 becomes 254
        self.assertFalse(selection.contains(16, 10))
        self.assertTrue(selection.contains(0, 0))

    def test_boolean_operations(self) -> None:
        selection = SelectionMask(10, 10)
        first = SelectionTools.shape_mask(
            "select_rectangle", QSize(10, 10), [QPoint(1, 1), QPoint(5, 5)]
        )
        second = SelectionTools.shape_mask(
            "select_rectangle", QSize(10, 10), [QPoint(4, 4), QPoint(8, 8)]
        )
        selection.combine(first, SelectionOperation.REPLACE)
        selection.combine(second, SelectionOperation.INTERSECT)
        self.assertTrue(selection.contains(4, 4))
        self.assertFalse(selection.contains(2, 2))
        selection.combine(second, SelectionOperation.ADD)
        self.assertTrue(selection.contains(7, 7))
        selection.combine(second, SelectionOperation.SUBTRACT)
        self.assertFalse(selection.contains(4, 4))

    def test_selection_bridge_accepts_enum_operations(self) -> None:
        destination = QImage(4, 3, QImage.Format.Format_ARGB32)
        candidate = QImage(4, 3, QImage.Format.Format_ARGB32)
        destination.fill(0)
        candidate.fill(0)
        candidate.setPixelColor(2, 1, QColor(255, 255, 255, 255))
        self.assertTrue(native_selection_combine(
            destination, candidate, SelectionOperation.ADD
        ))
        self.assertEqual(destination.pixelColor(2, 1).alpha(), 255)

    def test_native_selection_shapes_match_qt_reference_exactly(self) -> None:
        cases = (
            ("select_rectangle", [QPointF(2.25, 1.5), QPointF(12.75, 9.25)]),
            ("select_ellipse", [QPointF(2.25, 1.5), QPointF(12.75, 9.25)]),
            ("lasso", [QPointF(1.5, 2.0), QPointF(14.25, 3.5),
                       QPointF(11.0, 12.75), QPointF(3.0, 10.5)]),
        )
        for tool, points in cases:
            with self.subTest(tool=tool):
                native = SelectionTools.shape_mask(tool, QSize(20, 16), points)
                reference = _qt_shape_reference(tool, QSize(20, 16), points)
                self.assertEqual(bytes(native.constBits()), bytes(reference.constBits()))

    def test_invert_and_select_all(self) -> None:
        selection = SelectionMask(3, 2)
        selection.select_all()
        self.assertEqual(selection.bounds(), selection.image.rect())
        selection.invert()
        self.assertTrue(selection.is_empty())

    def test_magic_wand_is_contiguous(self) -> None:
        image = QImage(5, 3, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        for y in range(3):
            image.setPixelColor(2, y, QColor("black"))
        mask = SelectionTools.magic_wand(image, QPoint(0, 1), 0)
        self.assertTrue(mask.pixelColor(1, 1).alpha() > 0)
        self.assertEqual(mask.pixelColor(3, 1).alpha(), 0)

    def test_selection_raster_tools_require_native_engine(self) -> None:
        with patch("TOOLS.selection_tools.native_selection_shape_mask",
                   return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                SelectionTools.shape_mask(
                    "select_rectangle", QSize(4, 4), [QPoint(0, 0), QPoint(2, 2)])
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        with patch("TOOLS.selection_tools.native_magic_wand", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                SelectionTools.magic_wand(image, QPoint(1, 1))

    def test_selection_model_operations_require_native_engine(self) -> None:
        selection = SelectionMask(4, 3)
        candidate = QImage(4, 3, QImage.Format.Format_ARGB32)
        candidate.fill(0)

        with patch("DOCUMENTS.selection.native_selection_contains", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                selection.contains(0, 0)
        with patch("DOCUMENTS.selection.native_selection_combine", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                selection.combine(candidate, SelectionOperation.REPLACE)
        with patch("DOCUMENTS.selection.native_selection_invert", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                selection.invert()
        selection.invalidate()
        with patch("DOCUMENTS.selection.native_selection_bounds", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                selection.bounds()


if __name__ == "__main__":
    unittest.main()
