from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import zipfile
import zlib
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSize, QSettings
from PySide6.QtGui import QColor, QFont, QImage, QImageReader
from PySide6.QtWidgets import QApplication

from DOCUMENTS.document import Document
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.recovery import RecoveryManager
from DOCUMENTS.selection import SelectionOperation
from CANVAS.tile_history import TileHistory
from TOOLS.selection_tools import SelectionTools


class CSDFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_v03_round_trip_preserves_extended_layer_and_selection(self) -> None:
        document = Document(32, 24, 144)
        layer = document.get_active_layer()
        layer.blend_mode = "multiply"
        layer.blend_parameters = {"intensity": 0.65, "gamma": 1.3}
        document.blend_presets = {"Warm Multiply": {"mode": "multiply", "intensity": 0.7}}
        layer.locked = True
        layer.lock_alpha = True
        layer.clipping = True
        candidate = SelectionTools.shape_mask(
            "select_rectangle", QSize(32, 24), [QPoint(2, 3), QPoint(12, 15)]
        )
        document.selection.combine(candidate, SelectionOperation.REPLACE)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roundtrip.csd"
            self.assertTrue(CSDFormat.save(document, path))
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("document.json"))
                self.assertEqual(manifest["schema_version"], 6)
                self.assertIn("selection/mask.png", archive.namelist())
                self.assertIn("thumbnail.png", archive.namelist())
            loaded = CSDFormat.load(path)

        self.assertIsNotNone(loaded)
        loaded_layer = loaded.get_active_layer()
        self.assertEqual(loaded_layer.id, layer.id)
        self.assertEqual(loaded_layer.blend_mode, "multiply")
        self.assertEqual(loaded_layer.blend_parameters, {"intensity": 0.65, "gamma": 1.3})
        self.assertEqual(loaded.blend_presets, {"Warm Multiply": {"mode": "multiply", "intensity": 0.7}})
        self.assertTrue(loaded_layer.locked)
        self.assertTrue(loaded_layer.lock_alpha)
        self.assertTrue(loaded_layer.clipping)
        self.assertTrue(loaded.selection.contains(5, 5))

    def test_legacy_manifest_defaults_are_supported(self) -> None:
        document = Document(8, 8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.csd"
            self.assertTrue(CSDFormat.save(document, path))
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("document.json"))
                for key in ("schema_version", "application_version", "selection", "modified_utc"):
                    manifest.pop(key, None)
                for layer in manifest["layers"]:
                    for key in ("id", "blend_mode", "locked", "lock_alpha", "clipping"):
                        layer.pop(key, None)
                entries = [(name, archive.read(name)) for name in archive.namelist() if name != "document.json"]
            migrated_path = Path(directory) / "migrated.csd"
            with zipfile.ZipFile(migrated_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries:
                    archive.writestr(name, data)
                archive.writestr("document.json", json.dumps(manifest))
            loaded = CSDFormat.load(migrated_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.get_active_layer().blend_mode, "normal")

    def test_failed_atomic_save_preserves_existing_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.csd"
            self.assertTrue(CSDFormat.save(Document(8, 8), path))
            original = path.read_bytes()
            with patch.object(CSDFormat, "_png_bytes", side_effect=OSError("simulated write failure")):
                self.assertFalse(CSDFormat.save(Document(16, 16), path))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_recovery_manager_writes_loads_and_clears_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recovery = RecoveryManager(Path(directory) / "recovery.csd")
            document = Document(12, 9)
            document.get_active_layer().name = "Recovered Layer"
            self.assertTrue(recovery.save(document))
            restored = recovery.load()
            self.assertEqual((restored.width, restored.height), (12, 9))
            self.assertEqual(restored.get_active_layer().name, "Recovered Layer")
            recovery.clear()
            self.assertIsNone(recovery.load())

    def test_document_compression_preference_is_applied(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        key = "files/compress_documents"
        existed, previous = settings.contains(key), settings.value(key)
        try:
            settings.setValue(key, False)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "stored.csd"
                self.assertTrue(CSDFormat.save(Document(8, 8), path))
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.getinfo("document.json").compress_type, zipfile.ZIP_STORED)
        finally:
            if existed:
                settings.setValue(key, previous)
            else:
                settings.remove(key)

    def test_invalid_legacy_metadata_is_rejected_cleanly(self) -> None:
        for change in ("empty_layers", "invalid_dpi", "wrong_layer_size"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source.csd"
                target = Path(directory) / "broken.csd"
                self.assertTrue(CSDFormat.save(Document(8, 8), source))
                with zipfile.ZipFile(source) as archive:
                    entries = {name: archive.read(name) for name in archive.namelist()}
                manifest = json.loads(entries["document.json"])
                if change == "empty_layers":
                    manifest["layers"] = []
                elif change == "invalid_dpi":
                    manifest["dpi"] = 0
                else:
                    manifest["width"] = 9
                entries["document.json"] = json.dumps(manifest).encode("utf-8")
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    for name, data in entries.items():
                        archive.writestr(name, data)
                self.assertIsNone(CSDFormat.load(target))

    def test_invalid_csd_objects_are_rejected_before_document_allocation(self) -> None:
        document = Document(8, 8)
        document.add_layer("Top")
        document.group_layers([0, 1])
        reference = QImage(1, 1, QImage.Format.Format_RGBA8888)
        reference.fill(QColor("red"))
        document.reference_images.append(ReferenceImage(reference))
        document.text_objects.append(EditableText("Text", QPointF(1, 2)))
        corruptions = (
            ("non-finite-reference", lambda data: data["reference_images"][0].update(x=float("nan"))),
            ("invalid-text-color", lambda data: data["text_objects"][0].update(color={"bad": 1})),
            ("invalid-group-opacity", lambda data: data["layer_groups"][0].update(opacity="bad")),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csd"
            self.assertTrue(CSDFormat.save(document, source))
            with zipfile.ZipFile(source) as archive:
                base_entries = {name: archive.read(name) for name in archive.namelist()}
            for name, corrupt in corruptions:
                with self.subTest(case=name):
                    entries = dict(base_entries)
                    manifest = json.loads(entries["document.json"])
                    corrupt(manifest)
                    entries["document.json"] = json.dumps(manifest).encode("utf-8")
                    target = Path(directory) / f"{name}.csd"
                    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                        for entry_name, payload in entries.items():
                            archive.writestr(entry_name, payload)
                    with patch("DOCUMENTS.format_csd.Document") as factory:
                        self.assertIsNone(CSDFormat.load(target))
                        factory.assert_not_called()

    def test_oversized_csd_dimensions_rejected_before_document_allocation(self) -> None:
        manifest = {
            "width": 100_000, "height": 100_000, "dpi": 300,
            "active_layer": 0, "layers": [{"name": "Layer", "image": "layer.png"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.csd"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("document.json", json.dumps(manifest))
            with patch("DOCUMENTS.format_csd.Document") as document_factory:
                self.assertIsNone(CSDFormat.load(path))
                document_factory.assert_not_called()

    def test_oversized_reference_header_is_rejected_before_image_decode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csd"
            target = Path(directory) / "reference-bomb.csd"
            self.assertTrue(CSDFormat.save(Document(8, 8), source))
            with zipfile.ZipFile(source) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            manifest = json.loads(entries["document.json"])
            manifest["reference_images"] = [{
                "id": "oversized", "image": "references/bomb.png",
                "x": 0, "y": 0, "scale": 1, "opacity": 1,
            }]
            png = bytearray(CSDFormat._png_bytes(QImage(1, 1, QImage.Format.Format_ARGB32)))
            png[16:24] = struct.pack(">II", 20_000, 20_000)
            png[29:33] = struct.pack(">I", zlib.crc32(png[12:29]) & 0xFFFFFFFF)
            entries["document.json"] = json.dumps(manifest).encode("utf-8")
            entries["references/bomb.png"] = bytes(png)
            with zipfile.ZipFile(target, "w") as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)

            original_read = QImageReader.read
            read_calls = []

            def tracked_read(reader):
                read_calls.append(1)
                return original_read(reader)

            with patch.object(QImageReader, "read", tracked_read):
                self.assertIsNone(CSDFormat.load(target))
            # The layer is decoded; the oversized reference is rejected from
            # its header before the decoder attempts a large raster allocation.
            self.assertEqual(len(read_calls), 1)

    def test_round_trip_preserves_reference_images_and_editable_text(self) -> None:
        document = Document(16, 16)
        reference = QImage(3, 2, QImage.Format.Format_RGBA8888)
        reference.fill(QColor(30, 120, 220, 255))
        document.reference_images.append(ReferenceImage(reference, QPointF(4, 5), 1.5, 0.6))
        document.text_objects.append(EditableText(
            "Editable", QPointF(2, 9), QColor(210, 40, 50), QFont("Sans Serif", 18)
        ))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "objects.csd"
            self.assertTrue(CSDFormat.save(document, path))
            loaded = CSDFormat.load(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.reference_images), 1)
        self.assertEqual(loaded.reference_images[0].position, QPointF(4, 5))
        self.assertAlmostEqual(loaded.reference_images[0].scale, 1.5)
        self.assertEqual(loaded.reference_images[0].image.pixelColor(0, 0), QColor(30, 120, 220))
        self.assertEqual(loaded.text_objects[0].text, "Editable")
        self.assertEqual(loaded.text_objects[0].position, QPointF(2, 9))

    def test_history_restores_non_destructive_objects(self) -> None:
        document = Document(8, 8)
        history = TileHistory()
        history.begin(document)
        image = QImage(2, 2, QImage.Format.Format_RGBA8888)
        image.fill(QColor(10, 20, 30))
        document.reference_images.append(ReferenceImage(image, QPointF(1, 2)))
        document.text_objects.append(EditableText("Hi", QPointF(3, 4)))
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(document.reference_images, [])
        self.assertEqual(document.text_objects, [])
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.reference_images), 1)
        self.assertEqual(document.text_objects[0].text, "Hi")


if __name__ == "__main__":
    unittest.main()
