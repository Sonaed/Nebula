from __future__ import annotations

import unittest

from PySide6.QtGui import QColor, QImage


class GPUAlphaEdgeTests(unittest.TestCase):
    def test_premultiplied_edge_has_no_black_rgb_contribution(self) -> None:
        image = QImage(2, 1, QImage.Format.Format_ARGB32)
        image.setPixelColor(0, 0, QColor(200, 40, 20, 128))
        image.setPixelColor(1, 0, QColor(0, 0, 0, 0))
        converted = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        edge = converted.pixelColor(0, 0)
        # Qt exposes unpremultiplied QColor values after reading back, while
        # the uploaded bytes carry the premultiplied channels.
        self.assertGreater(edge.red(), 150)
        self.assertEqual(converted.format(), QImage.Format.Format_RGBA8888_Premultiplied)


if __name__ == "__main__":
    unittest.main()
