from __future__ import annotations

import unittest
from math import ceil, cos, pi, sin
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QRectF

from TOOLS.shape_tools import ShapeTools


def _reference_path(shape, start, end):
    first, last = QPointF(start), QPointF(end)
    if shape == "line":
        return [first, last]
    bounds = QRectF(first, last).normalized()
    if shape == "rectangle":
        a, b, c, d = (bounds.topLeft(), bounds.topRight(),
                      bounds.bottomRight(), bounds.bottomLeft())
        return [a, b, c, d, a]
    rx, ry = bounds.width() / 2.0, bounds.height() / 2.0
    center = bounds.center()
    circumference = pi * (3.0 * (rx + ry) -
        ((3.0 * rx + ry) * (rx + 3.0 * ry)) ** 0.5) if rx > 0 and ry > 0 else 0
    count = max(16, min(720, int(ceil(circumference / 3.0))))
    points = [QPointF(center.x() + rx * cos(2 * pi * i / count),
                      center.y() + ry * sin(2 * pi * i / count))
              for i in range(count)]
    points.append(QPointF(points[0]))
    return points


class ShapeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shapes = ShapeTools()

    def test_line_has_two_endpoints(self) -> None:
        self.assertEqual(
            self.shapes.path("line", QPoint(2, 3), QPoint(8, 9)),
            [QPointF(2, 3), QPointF(8, 9)],
        )

    def test_rectangle_is_closed_and_normalized(self) -> None:
        path = self.shapes.path("rectangle", QPoint(8, 9), QPoint(2, 3))
        self.assertEqual(len(path), 5)
        self.assertEqual(path[0], path[-1])
        self.assertEqual(path[0], QPointF(2, 3))

    def test_ellipse_is_closed(self) -> None:
        path = self.shapes.path("ellipse", QPoint(0, 0), QPoint(100, 50))
        self.assertGreaterEqual(len(path), 17)
        self.assertEqual(path[0], path[-1])

    def test_unknown_shape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.shapes.path("polygon", QPoint(), QPoint(1, 1))

    def test_native_paths_match_previous_geometry(self) -> None:
        cases = (
            ("line", QPointF(2.25, -3.5), QPointF(8.75, 9.125)),
            ("rectangle", QPointF(8.75, 9.125), QPointF(2.25, -3.5)),
            ("ellipse", QPointF(2.25, -3.5), QPointF(108.75, 46.125)),
            ("ellipse", QPointF(4.5, 4.5), QPointF(4.5, 44.5)),
        )
        for shape, start, end in cases:
            with self.subTest(shape=shape, start=start, end=end):
                self.assertEqual(self.shapes.path(shape, start, end),
                                 _reference_path(shape, start, end))

    def test_shape_path_requires_native_engine(self) -> None:
        with patch("TOOLS.shape_tools.native_shape_path", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                self.shapes.path("line", QPoint(), QPoint(2, 3))


if __name__ == "__main__":
    unittest.main()
