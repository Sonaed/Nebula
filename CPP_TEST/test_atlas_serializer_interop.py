from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from DOCUMENTS.format_atlas import AtlasFormat
from DOCUMENTS.format_nebula import NebulaFormat


class AtlasSerializerInteropTests(unittest.TestCase):
    def test_atlas_cpp_serializer_v3_fixture_imports_with_pixels_and_mask(self) -> None:
        path = Path(__file__).with_name("atlas_v3_serializer_sample.atlas")
        self.assertTrue(path.is_file())
        document = AtlasFormat.load(path)

        self.assertIsNotNone(document)
        self.assertEqual((document.width, document.height, document.dpi), (3, 2, 144))
        self.assertEqual(document.name, "Atlas Serializer Interop")
        self.assertEqual(document.author, "CreativeSystem Atlas")
        self.assertEqual(len(document.layers), 1)
        layer = document.layers[0]
        self.assertEqual(layer.name, "Fixture Layer")
        self.assertAlmostEqual(layer.opacity, 0.75)
        self.assertEqual(layer.blend_mode, "normal")
        self.assertEqual(layer.image.pixelColor(0, 0).getRgb(), (240, 20, 30, 255))
        self.assertEqual(layer.image.pixelColor(2, 1).getRgb(), (110, 120, 130, 32))

    def test_atlas_fixture_roundtrips_through_native_nebula(self) -> None:
        source = Path(__file__).with_name("atlas_v3_serializer_sample.atlas")
        document = AtlasFormat.load(source)
        self.assertIsNotNone(document)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "atlas-import.nebula"
            self.assertTrue(NebulaFormat.save(document, target))
            reopened = NebulaFormat.load(target)
            self.assertIsNotNone(reopened)
            self.assertEqual((reopened.width, reopened.height, reopened.dpi), (3, 2, 144))
            self.assertEqual(reopened.layers[0].image.pixelColor(2, 1).getRgb(),
                             (110, 120, 130, 32))


if __name__ == "__main__":
    unittest.main()
