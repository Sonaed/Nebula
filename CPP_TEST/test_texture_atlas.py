from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from CANVAS.texture_atlas import TextureAtlas


class NativeTextureAtlasTests(unittest.TestCase):
    def test_packs_and_uploads_rgba_in_creativecore(self) -> None:
        atlas = TextureAtlas(size=16, padding=1)
        try:
            image = QImage(3, 2, QImage.Format.Format_RGBA8888)
            image.fill(QColor(12, 34, 56, 255))
            self.assertTrue(atlas.upload_region("dab", image))
            rect = atlas.rects["dab"]
            self.assertEqual((rect.w, rect.h), (3, 2))
            self.assertEqual(atlas.uv("dab"), (0.0, 0.0, 3 / 16, 2 / 16))
            self.assertEqual(atlas.last_upload[:4], (0, 0, 3, 2))
        finally:
            atlas.close()

    def test_native_allocator_rejects_overflow_without_python_image_store(self) -> None:
        atlas = TextureAtlas(size=8, padding=1)
        try:
            image = QImage(9, 1, QImage.Format.Format_RGBA8888)
            self.assertFalse(atlas.upload_region("too-large", image))
            self.assertNotIn("too-large", atlas.rects)
        finally:
            atlas.close()


if __name__ == "__main__":
    unittest.main()
