from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from psd_tools import PSDImage
    from PIL import Image
except ImportError:
    PSDImage = None

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage

from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.document import Document
from CORE.native_bridge import fill_image_native


@unittest.skipUnless(PSDImage is not None, "psd-tools is optional")
class PSDParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_layered_psd_keeps_raster_layers_and_opacity(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.psd"
            psd = PSDImage.new("RGBA", (32, 32), color=(0, 0, 0, 0))
            psd.create_pixel_layer(Image.new("RGBA", (32, 32), (255, 0, 0, 255)),
                                   name="Red", opacity=200)
            psd.create_pixel_layer(Image.new("RGBA", (16, 16), (0, 255, 0, 255)),
                                   name="Green", top=8, left=8)
            psd.save(path)
            document = PSDFormat.load(path)
            self.assertIsNotNone(document)
            self.assertEqual([layer.name for layer in document.layers], ["Green", "Red"])
            self.assertAlmostEqual(document.layers[1].opacity, 200 / 255, places=3)
            # The smaller PSD layer must retain its own offset instead of
            # being pasted at the canvas origin.
            green = document.layers[0].tile_store.materialize()
            self.assertEqual(green.pixelColor(8, 8).green(), 255)
            self.assertEqual(green.pixelColor(0, 0).alpha(), 0)

    def test_blend_key_mapping_keeps_significant_spaces(self):
        self.assertEqual(PSDFormat._blend_mode(type("Layer", (), {"blend_mode": "mul "})(), [], "x"),
                         "multiply")
        self.assertEqual(PSDFormat._blend_mode(type("Layer", (), {"blend_mode": "lddg"})(), [], "x"),
                         "screen")

    def test_export_round_trip_keeps_group_mask_and_clipping(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "round-trip.psd"
            document = Document(16, 16, 300, None)
            document.layers.clear()
            base = document.add_layer("Fond é")
            fill_image_native(base.image, QColor(20, 30, 40, 255))
            base.mark_image_cache_dirty()
            base.commit_image_cache()
            top = document.add_layer("Lumière")
            fill_image_native(top.image, QColor(240, 80, 40, 255))
            top.mark_image_cache_dirty()
            top.commit_image_cache()
            top.opacity = 0.5
            top.blend_mode = "screen"
            top.clipping = True
            mask = QImage(16, 16, QImage.Format.Format_RGBA8888)
            mask.fill(QColor(0, 0, 0, 0))
            mask.setPixelColor(4, 4, QColor(0, 0, 0, 255))
            top.set_alpha_mask(mask)
            self.assertTrue(PSDFormat.save(document, path))
            psd = PSDImage.open(path)
            self.assertEqual([item.name for item in psd], ["Lumière", "Fond é"])
            imported = PSDFormat.load(path)
            self.assertIsNotNone(imported)
            self.assertEqual([layer.name for layer in imported.layers], ["Fond é", "Lumière"])
            self.assertEqual(imported.layers[1].blend_mode, "screen")
            self.assertTrue(imported.layers[1].clipping)
            recovered_mask = imported.layers[1].alpha_mask_store.materialize()
            self.assertEqual(recovered_mask.pixelColor(4, 4).alpha(), 255)
            self.assertEqual(recovered_mask.pixelColor(0, 0).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
