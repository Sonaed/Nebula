from __future__ import annotations

import ctypes
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage

from TOOLS.fill_tool import FillTool
from TOOLS.selection_tools import SelectionTools
from CORE.native_bridge import (apply_alpha_mask_native, fill_image_native,
                                fill_image_rect_native, render_brush_preset_art_native)


def load_bridge():
    path = Path(__file__).resolve().parents[1] / "build_cpp" / "libCreativeCoreBridge.so"
    if not path.exists():
        return None
    library = ctypes.CDLL(str(path))
    byte_pointer = ctypes.POINTER(ctypes.c_uint8)
    int_pointer = ctypes.POINTER(ctypes.c_int)
    library.cs_fill.argtypes = [
        byte_pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8,
        int_pointer, int_pointer, int_pointer, int_pointer,
    ]
    library.cs_fill.restype = ctypes.c_int
    library.cs_magic_wand.argtypes = [
        byte_pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, byte_pointer, ctypes.c_int,
    ]
    library.cs_magic_wand.restype = ctypes.c_int
    return library


class CppRasterToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = load_bridge()
        if cls.library is None:
            raise unittest.SkipTest("CreativeCoreBridge is not built")

    def test_native_fill_respects_boundaries_and_returns_bounds(self) -> None:
        image = QImage(7, 7, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        for x in range(7):
            image.setPixelColor(x, 3, QColor("black"))
        tool = FillTool()
        tool.cpp_library = self.library
        rect = tool.fill(image, QPoint(1, 1), QColor("red"))
        self.assertEqual(rect, image.rect().adjusted(0, 0, 0, -4))
        self.assertEqual(image.pixelColor(1, 1), QColor("red"))
        self.assertEqual(image.pixelColor(1, 5), QColor("white"))

    def test_native_magic_wand_is_contiguous(self) -> None:
        image = QImage(5, 3, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        for y in range(3):
            image.setPixelColor(2, y, QColor("black"))
        mask = SelectionTools.magic_wand(image, QPoint(0, 1), 0, self.library)
        self.assertGreater(mask.pixelColor(1, 1).alpha(), 0)
        self.assertEqual(mask.pixelColor(3, 1).alpha(), 0)

    def test_native_fill_supports_rgba8888_layers(self) -> None:
        image = QImage(3, 2, QImage.Format.Format_RGBA8888)
        image.fill(QColor("white"))
        tool = FillTool()
        tool.cpp_library = self.library
        tool.fill(image, QPoint(1, 1), QColor("blue"))
        self.assertEqual(image.pixelColor(0, 0), QColor("blue"))

    def test_native_image_fill_initializes_document_pixels(self) -> None:
        image = QImage(4, 3, QImage.Format.Format_RGBA8888)
        self.assertTrue(fill_image_native(image, QColor(12, 34, 56, 78)))
        self.assertEqual(image.pixelColor(0, 0), QColor(12, 34, 56, 78))
        self.assertEqual(image.pixelColor(3, 2), QColor(12, 34, 56, 78))

    def test_native_image_fill_rect_is_clipped_and_source_over_free(self) -> None:
        image = QImage(6, 4, QImage.Format.Format_RGBA8888)
        self.assertTrue(fill_image_native(image, QColor(1, 2, 3, 255)))
        self.assertTrue(fill_image_rect_native(image, QRect(-2, 1, 5, 4),
                                                QColor(200, 100, 50, 128)))
        self.assertEqual(image.pixelColor(0, 1), QColor(200, 100, 50, 128))
        self.assertEqual(image.pixelColor(3, 0), QColor(1, 2, 3, 255))

    def test_native_brush_preset_art_writes_tip_and_preview(self) -> None:
        texture = QImage(64, 64, QImage.Format.Format_ARGB32)
        preview = QImage(128, 64, QImage.Format.Format_ARGB32)
        self.assertTrue(render_brush_preset_art_native(
            texture, preview, 0.7, 25.0, QColor(220, 120, 40, 255)))
        self.assertGreater(texture.pixelColor(32, 32).alpha(), 0)
        self.assertEqual(preview.pixelColor(0, 0), QColor(48, 48, 48, 255))
        self.assertEqual(preview.pixelColor(14, 32), QColor(220, 120, 40, 255))

    def test_native_alpha_mask_multiplies_coverage_without_touching_rgb(self) -> None:
        image = QImage(2, 1, QImage.Format.Format_RGBA8888)
        mask = QImage(2, 1, QImage.Format.Format_RGBA8888)
        self.assertTrue(fill_image_native(image, QColor(80, 100, 120, 200)))
        self.assertTrue(fill_image_native(mask, QColor(255, 255, 255, 128)))
        self.assertTrue(apply_alpha_mask_native(image, mask))
        self.assertEqual(image.pixelColor(0, 0), QColor(80, 100, 120, 100))


if __name__ == "__main__":
    unittest.main()
