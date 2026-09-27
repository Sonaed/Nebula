from __future__ import annotations

import tempfile
import unittest
import zipfile
import os
import json
import struct
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtWidgets import QApplication

from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.format_nebula import MAGIC, NebulaFormat, _image_tile, load_document
from DOCUMENTS.recovery import RecoveryManager


class NebulaFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _document(self) -> Document:
        document = Document(130, 70, 144)
        layer = document.get_active_layer()
        layer.name = "Couleurs"
        layer.blend_mode = "multiply"
        layer.blend_parameters = {"intensity": 0.75}
        layer.lock_alpha = True
        layer.image.setPixelColor(4, 5, QColor(220, 70, 40, 200))
        layer.image.setPixelColor(100, 65, QColor(40, 170, 220, 255))
        document.blend_presets = {"Doux": {"mode": "screen", "opacity": 0.6}}
        document.selection.image.setPixelColor(8, 9, QColor(255, 255, 255, 255))
        document.selection.invalidate()
        reference = QImage(3, 2, QImage.Format.Format_RGBA8888)
        reference.fill(QColor(20, 90, 200, 255))
        document.reference_images.append(ReferenceImage(reference, QPointF(7.5, 8.5), 1.25, 0.7))
        document.text_objects.append(EditableText(
            "Nebula", QPointF(11, 18), QColor(245, 210, 130), QFont("Sans Serif", 17)
        ))
        return document

    def test_native_binary_round_trip_preserves_document_data(self) -> None:
        document = self._document()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artwork.nbl"
            self.assertTrue(NebulaFormat.save(document, path))
            data = path.read_bytes()
            self.assertEqual(data[:4], MAGIC)
            self.assertNotEqual(data[:2], b"PK")
            loaded = NebulaFormat.load(path)

        self.assertIsNotNone(loaded)
        self.assertEqual((loaded.width, loaded.height, loaded.dpi), (130, 70, 144))
        layer = loaded.get_active_layer()
        self.assertEqual(layer.name, "Couleurs")
        self.assertEqual(layer.blend_mode, "multiply")
        self.assertEqual(layer.blend_parameters, {"intensity": 0.75})
        self.assertTrue(layer.lock_alpha)
        self.assertEqual(layer.image.pixelColor(4, 5), QColor(220, 70, 40, 200))
        self.assertEqual(layer.image.pixelColor(100, 65), QColor(40, 170, 220, 255))
        self.assertTrue(loaded.selection.contains(8, 9))
        self.assertEqual(loaded.blend_presets, document.blend_presets)
        self.assertEqual(loaded.reference_images[0].image.pixelColor(1, 1), QColor(20, 90, 200))
        self.assertEqual(loaded.reference_images[0].position, QPointF(7.5, 8.5))
        self.assertEqual(loaded.text_objects[0].text, "Nebula")

    def test_alpha_mask_round_trip_preserves_sparse_mask_and_pixels(self) -> None:
        document = Document(2, 1)
        layer = document.get_active_layer()
        layer.image.fill(QColor(220, 80, 40, 200))
        mask = QImage(2, 1, QImage.Format.Format_ARGB32)
        mask.fill(QColor(255, 255, 255, 255))
        mask.setPixelColor(0, 0, QColor(255, 255, 255, 128))
        layer.ensure_alpha_mask().set_tile(0, 0, mask)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "masked.nbl"
            self.assertTrue(NebulaFormat.save(document, path))
            loaded = NebulaFormat.load(path)
        self.assertIsNotNone(loaded)
        restored = loaded.get_active_layer()
        self.assertIsNotNone(restored.alpha_mask_store)
        restored_mask = restored.alpha_mask
        self.assertEqual(restored_mask.pixelColor(0, 0).alpha(), 128)
        self.assertEqual(restored_mask.pixelColor(1, 0).alpha(), 255)

    def test_nebula_tile_extraction_requires_native_copy(self) -> None:
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        with patch("DOCUMENTS.format_nebula.crop_image_native", return_value=None):
            with self.assertRaisesRegex(OSError, "CreativeCore"):
                _image_tile(image, QRect(0, 0, 8, 8))

    def test_legacy_csd_remains_importable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.csd"
            self.assertTrue(CSDFormat.save(self._document(), path))
            self.assertTrue(zipfile.is_zipfile(path))
            loaded = load_document(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.get_active_layer().name, "Couleurs")

    def test_blank_document_round_trip_has_no_tile_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.nebula"
            self.assertTrue(NebulaFormat.save(Document(12, 9), path))
            loaded = NebulaFormat.load(path)
        self.assertIsNotNone(loaded)
        self.assertFalse(loaded.get_active_layer().tile_store.occupied_keys)

    def test_failed_recovery_autosave_preserves_previous_valid_snapshot(self) -> None:
        document = Document(64, 64)
        layer = document.get_active_layer()
        layer.discard_image_cache()
        layer.tile_store.clear_resident()
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(QColor("magenta"))
        self.assertTrue(layer.tile_store.set_tile(0, 0, tile))

        with tempfile.TemporaryDirectory() as directory:
            recovery_path = Path(directory) / "current.nbl"
            recovery = RecoveryManager(recovery_path)
            self.assertTrue(recovery.save(document))
            valid_snapshot = recovery_path.read_bytes()

            scratch = Path(directory) / "scratch"
            layer.tile_store.set_scratch_directory(scratch)
            self.assertGreater(layer.tile_store.evict_tile_to_scratch(0, 0), 0)
            layer.tile_store._swapped[(0, 0)].write_bytes(b"truncated recovery tile")

            self.assertFalse(recovery.save(document))
            self.assertEqual(recovery_path.read_bytes(), valid_snapshot)
            restored = recovery.load()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.get_active_layer().image.pixelColor(12, 14),
                         QColor("magenta"))

    def test_save_rejects_tile_limit_before_opening_writer(self) -> None:
        document = Document(128, 64)
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(QColor("red"))
        layer = document.get_active_layer()
        layer.discard_image_cache()
        store = layer.tile_store
        self.assertTrue(store.set_tile(0, 0, tile))
        self.assertTrue(store.set_tile(1, 0, tile))
        with tempfile.TemporaryDirectory() as directory, \
                patch("DOCUMENTS.format_nebula.MAX_CHUNKS", 1), \
                patch("DOCUMENTS.format_nebula.create_nebula_writer") as writer:
            path = Path(directory) / "too-many.nebula"
            self.assertFalse(NebulaFormat.save(document, path))
        writer.assert_not_called()
        self.assertFalse(path.exists())

    def test_save_rejects_layer_grid_mismatch_instead_of_dropping_pixels(self) -> None:
        document = Document(32, 32)
        document.width = 33
        with tempfile.TemporaryDirectory() as directory, \
                patch("DOCUMENTS.format_nebula.create_nebula_writer") as writer:
            path = Path(directory) / "mismatched.nebula"
            self.assertFalse(NebulaFormat.save(document, path))
        writer.assert_not_called()
        self.assertFalse(path.exists())

    def test_corrupt_native_chunk_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.nebula"
            self.assertTrue(NebulaFormat.save(self._document(), path))
            content = bytearray(path.read_bytes())
            content[-1] ^= 0x5A
            path.write_bytes(content)
            self.assertIsNone(NebulaFormat.load(path))

    def test_native_manifest_validator_is_required_before_document_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.nebula"
            self.assertTrue(NebulaFormat.save(self._document(), path))
            with patch("DOCUMENTS.format_nebula.validate_nebula_manifest",
                       return_value=None), \
                 patch("DOCUMENTS.format_nebula.Document") as factory:
                self.assertIsNone(NebulaFormat.load(path))
                factory.assert_not_called()

    def test_invalid_tile_grid_is_rejected_before_document_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "source.nebula"
            self.assertTrue(NebulaFormat.save(self._document(), original))
            content = original.read_bytes()
            magic, version, flags, metadata_size, chunk_count = struct.unpack(
                "<4sHHII", content[:16]
            )
            metadata = json.loads(content[16:16 + metadata_size])
            tile_payload = content[16 + metadata_size:]
            for name, changes in (
                ("negative-coordinate", {"x": -1}),
                ("incorrect-edge-size", {"width": 1}),
            ):
                with self.subTest(case=name):
                    damaged_metadata = json.loads(json.dumps(metadata))
                    damaged_metadata["chunks"][0].update(changes)
                    encoded = json.dumps(damaged_metadata, separators=(",", ":")).encode()
                    path = Path(directory) / f"{name}.nebula"
                    path.write_bytes(struct.pack("<4sHHII", magic, version, flags,
                                                 len(encoded), chunk_count)
                                     + encoded + tile_payload)
                    with patch("DOCUMENTS.format_nebula.Document") as factory:
                        self.assertIsNone(NebulaFormat.load(path))
                        factory.assert_not_called()

    def test_invalid_metadata_objects_are_rejected_before_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "source.nebula"
            self.assertTrue(NebulaFormat.save(self._document(), original))
            content = original.read_bytes()
            magic, version, flags, metadata_size, chunk_count = struct.unpack(
                "<4sHHII", content[:16]
            )
            metadata = json.loads(content[16:16 + metadata_size])
            tile_payload = content[16 + metadata_size:]
            corruptions = (
                ("non-finite-reference", lambda item: item["references"][0].update(x=float("nan"))),
                ("invalid-layer-parameters", lambda item: item["layers"][0].update(blend_parameters=[])),
                ("non-numeric-layer-parameter", lambda item: item["layers"][0].update(blend_parameters={"intensity": "bad"})),
                ("non-finite-text-position", lambda item: item["texts"][0].update(y=float("nan"))),
                ("invalid-text-color", lambda item: item["texts"][0].update(color=[1, 2])),
                ("missing-layer-tile-index", lambda item: item["layers"][0].update(tiles=[])),
                ("missing-selection-tile-index", lambda item: item.update(selection_tiles=[])),
                ("missing-reference-tile-index", lambda item: item["references"][0].update(tiles=[])),
            )
            for name, corrupt in corruptions:
                with self.subTest(case=name):
                    changed = json.loads(json.dumps(metadata))
                    corrupt(changed)
                    encoded = json.dumps(changed, separators=(",", ":")).encode()
                    path = Path(directory) / f"{name}.nebula"
                    path.write_bytes(struct.pack("<4sHHII", magic, version, flags,
                                                 len(encoded), chunk_count)
                                     + encoded + tile_payload)
                    with patch("DOCUMENTS.format_nebula.Document") as factory:
                        self.assertIsNone(NebulaFormat.load(path))
                        factory.assert_not_called()

    def test_oversized_eager_canvas_is_rejected_before_document_allocation(self) -> None:
        metadata = {
            "width": 100_000, "height": 100_000, "dpi": 300,
            "layers": [{"name": "Layer"}], "chunks": [],
        }
        payload = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.nebula"
            path.write_bytes(struct.pack("<4sHHII", MAGIC, 1, 0, len(payload), 0) + payload)
            with patch("DOCUMENTS.format_nebula.Document") as document_factory:
                self.assertIsNone(NebulaFormat.load(path))
                document_factory.assert_not_called()

    def test_oversized_reference_is_rejected_before_image_allocation(self) -> None:
        metadata = {
            "width": 16, "height": 16, "dpi": 300,
            "layers": [{"name": "Layer"}], "chunks": [],
            "references": [{"width": 20_000, "height": 20_000}],
        }
        payload = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized-reference.nebula"
            path.write_bytes(struct.pack("<4sHHII", MAGIC, 1, 0, len(payload), 0) + payload)
            with patch("DOCUMENTS.format_nebula.QImage") as image_factory:
                self.assertIsNone(NebulaFormat.load(path))
                image_factory.assert_not_called()

    def test_save_keeps_evicted_layer_tiles_evicted(self) -> None:
        document = Document(64, 64)
        layer = document.get_active_layer()
        layer.discard_image_cache()
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(QColor(65, 120, 190, 255))
        layer.tile_store.set_tile(0, 0, tile)
        with tempfile.TemporaryDirectory() as directory:
            layer.tile_store.set_scratch_directory(Path(directory) / "scratch")
            self.assertGreater(layer.tile_store.evict_tile_to_scratch(0, 0), 0)
            path = Path(directory) / "swapped.nebula"
            self.assertTrue(NebulaFormat.save(document, path))
            self.assertFalse(layer.tile_store.tile_is_resident(0, 0))
            loaded = NebulaFormat.load(path)
        self.assertEqual(loaded.get_active_layer().image.pixelColor(4, 8), QColor(65, 120, 190))


if __name__ == "__main__":
    unittest.main()
