from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DOCUMENTS.format_nebula import NebulaFormat, load_document
from CORE.native_bridge import read_atlas_project


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _blob(value: bytes) -> bytes:
    return struct.pack("<II", len(value), len(zlib.compress(value))) + zlib.compress(value)


def _atlas_v3_fixture(path: Path) -> None:
    width, height = 4, 3
    pixels = bytearray()
    mask = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend((220, 40, 15, 255))
            mask.extend((255, 255, 255, 0 if (x == 0 and y == 0) else 255))
    content = bytearray(b"ATLS")
    content += struct.pack("<I", 3)
    content += _string("Artwork") + _string("Test artist") + _string("0.1")
    content += struct.pack("<III", width, height, 240)
    content += _string("transparent")
    content += struct.pack("<4d", 1.0, 0.0, 0.0, 0.0)  # Atlas view state
    content += struct.pack("<I", 1)
    content += _string("Ink") + struct.pack("<fB", 0.65, 1) + _string("multiply")
    content += _blob(bytes(pixels)) + _blob(bytes(mask))
    path.write_bytes(content)


def _atlas_v2_fixture(path: Path) -> None:
    width, height = 2, 2
    pixels = bytes((30, 90, 180, 255) * (width * height))
    content = bytearray(b"ATLS") + struct.pack("<I", 2)
    content += _string("Old Atlas") + _string("") + _string("0.1")
    content += struct.pack("<II", width, height)
    content += struct.pack("<4d", 1.0, 0.0, 0.0, 0.0)
    content += struct.pack("<I", 1)
    content += _string("Layer 1") + struct.pack("<fB", 1.0, 1) + _string("normal")
    content += _blob(pixels) + _blob(b"")
    path.write_bytes(content)


class AtlasImportTests(unittest.TestCase):
    def test_atlas_v3_import_preserves_layer_properties_and_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.atlas"
            _atlas_v3_fixture(path)
            original_bytes = path.read_bytes()
            document = load_document(path)
            self.assertIsNotNone(document)
            native_path = Path(temp_dir) / "converted.nebula"
            self.assertTrue(NebulaFormat.save(document, native_path))
            converted = load_document(native_path)
            self.assertEqual(path.read_bytes(), original_bytes)

        self.assertIsNotNone(document)
        self.assertEqual((document.width, document.height, document.dpi), (4, 3, 240))
        self.assertEqual((document.name, document.author), ("Artwork", "Test artist"))
        self.assertEqual(len(document.layers), 1)
        layer = document.layers[0]
        self.assertEqual(layer.name, "Ink")
        self.assertAlmostEqual(layer.opacity, 0.65)
        self.assertTrue(layer.visible)
        self.assertEqual(layer.blend_mode, "multiply")
        self.assertEqual(layer.image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(layer.image.pixelColor(1, 0).getRgb(), (220, 40, 15, 255))
        self.assertEqual(converted.layers[0].blend_mode, "multiply")
        self.assertEqual(converted.layers[0].image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual((converted.name, converted.author), ("Artwork", "Test artist"))

    def test_invalid_or_truncated_atlas_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.atlas"
            path.write_bytes(b"ATLS\x03\x00")
            self.assertIsNone(load_document(path))

    def test_atlas_v2_without_dpi_or_mask_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "older.atlas"
            _atlas_v2_fixture(path)
            document = load_document(path)
        self.assertIsNotNone(document)
        self.assertEqual((document.width, document.height, document.dpi), (2, 2, 72))
        self.assertEqual((document.name, document.author), ("Old Atlas", ""))
        self.assertEqual(document.layers[0].image.pixelColor(1, 1).getRgb(),
                         (30, 90, 180, 255))

    def test_atlas_bridge_checks_aggregate_layer_budget_before_copy(self) -> None:
        library = SimpleNamespace()
        library.cs_atlas_reader_open = Mock(return_value=1)
        library.cs_atlas_reader_close = Mock()
        library.cs_atlas_reader_layer_info = Mock()
        library.cs_atlas_reader_copy_layer = Mock()

        def document_info(_reader, _name, _name_cap, _author, _author_cap,
                          width, height, dpi, count, _background, _background_cap):
            width._obj.value = 16_384
            height._obj.value = 16_384
            dpi._obj.value = 72
            count._obj.value = 3  # Exceeds the 512 MiB decoded layer budget.
            return 1

        library.cs_atlas_reader_document_info = Mock(side_effect=document_info)
        with patch("CORE.native_bridge.load_creative_core", return_value=library):
            self.assertIsNone(read_atlas_project("oversized.atlas"))
        library.cs_atlas_reader_layer_info.assert_not_called()
        library.cs_atlas_reader_copy_layer.assert_not_called()
        library.cs_atlas_reader_close.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
