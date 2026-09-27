from __future__ import annotations

import ctypes
import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QColor, QImage


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "build_cpp_native" / "libCreativeCoreBridge.so"


class BitmapBrushApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = ctypes.CDLL(str(LIBRARY))
        cls.library.cs_brush_create.restype = ctypes.c_void_p
        cls.library.cs_brush_destroy.argtypes = [ctypes.c_void_p]
        cls.library.cs_brush_set_size.argtypes = [ctypes.c_void_p, ctypes.c_float]
        cls.library.cs_brush_set_texture_strength.argtypes = [
            ctypes.c_void_p, ctypes.c_float
        ]
        cls.library.cs_brush_set_texture_path.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p
        ]
        cls.library.cs_brush_set_texture_path.restype = ctypes.c_int
        cls.library.cs_brush_set_bitmap_tip_path.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p
        ]
        cls.library.cs_brush_set_bitmap_tip_path.restype = ctypes.c_int
        cls.library.cs_brush_set_bitmap_tip_png.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint64
        ]
        cls.library.cs_brush_set_bitmap_tip_png.restype = ctypes.c_int
        cls.library.cs_brush_set_color.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8,
            ctypes.c_uint8, ctypes.c_uint8,
        ]
        cls.library.cs_brush_draw_segment.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            *([ctypes.c_float] * 6),
        ]

    def test_native_bitmap_texture_changes_stamp_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checker.png"
            texture = QImage(2, 2, QImage.Format.Format_RGBA8888)
            texture.setPixelColor(0, 0, QColor(0, 0, 0, 255))
            texture.setPixelColor(1, 0, QColor(255, 255, 255, 255))
            texture.setPixelColor(0, 1, QColor(255, 255, 255, 255))
            texture.setPixelColor(1, 1, QColor(0, 0, 0, 255))
            self.assertTrue(texture.save(str(path)))

            brush = self.library.cs_brush_create()
            self.assertTrue(brush)
            try:
                self.library.cs_brush_set_size(brush, 32.0)
                self.library.cs_brush_set_texture_strength(brush, 1.0)
                self.assertEqual(
                    self.library.cs_brush_set_texture_path(
                        brush, str(path).encode("utf-8")
                    ),
                    1,
                )

                width = height = 48
                pixels = (ctypes.c_uint8 * (width * height * 4))()
                self.library.cs_brush_draw_segment(
                    brush, pixels, width, height, width * 4,
                    24.0, 24.0, 1.0, 24.0, 24.0, 1.0,
                )
                alpha = lambda x, y: pixels[(y * width + x) * 4 + 3]
                self.assertLess(alpha(16, 16), 8)
                self.assertGreater(alpha(32, 16), 240)
            finally:
                self.library.cs_brush_destroy(brush)

    def test_native_full_color_bitmap_tip_keeps_source_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "red-tip.png"
            bitmap = QImage(8, 8, QImage.Format.Format_RGBA8888)
            bitmap.fill(QColor(240, 25, 40, 255))
            self.assertTrue(bitmap.save(str(path)))

            brush = self.library.cs_brush_create()
            self.assertTrue(brush)
            try:
                self.library.cs_brush_set_size(brush, 32.0)
                self.library.cs_brush_set_color(brush, 20, 220, 60, 255)
                self.assertEqual(self.library.cs_brush_set_bitmap_tip_path(
                    brush, str(path).encode("utf-8")
                ), 1)
                width = height = 48
                pixels = (ctypes.c_uint8 * (width * height * 4))()
                self.library.cs_brush_draw_segment(
                    brush, pixels, width, height, width * 4,
                    24.0, 24.0, 1.0, 24.0, 24.0, 1.0,
                )
                offset = (24 * width + 24) * 4
                self.assertEqual(tuple(pixels[offset:offset + 4]), (240, 25, 40, 255))
            finally:
                self.library.cs_brush_destroy(brush)

    def test_native_bitmap_tip_png_byte_api_uses_cpp_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cyan-tip.png"
            bitmap = QImage(8, 8, QImage.Format.Format_RGBA8888)
            bitmap.fill(QColor(20, 180, 230, 255))
            self.assertTrue(bitmap.save(str(path)))
            encoded_png = path.read_bytes()
            data = (ctypes.c_uint8 * len(encoded_png)).from_buffer_copy(encoded_png)
            brush = self.library.cs_brush_create()
            try:
                self.assertEqual(
                    self.library.cs_brush_set_bitmap_tip_png(brush, data, len(encoded_png)),
                    1,
                )
            finally:
                self.library.cs_brush_destroy(brush)


if __name__ == "__main__":
    unittest.main()
