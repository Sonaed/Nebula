from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from TOOLS.brush_preset_manager import BrushPresetManager


class BrushPresetV2Tests(unittest.TestCase):
    def test_starter_pack_has_nine_read_only_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory)
            expected = {
                "Round Hard": (1.0, 1.0, 0.10),
                "Round Soft": (0.0, 1.0, 0.10),
                "Round Soft Flow": (0.0, 0.3, 0.10),
                "Flat Hard": (1.0, 1.0, 0.10),
                "Flat Soft": (0.3, 1.0, 0.10),
                "Ink Pen": (1.0, 1.0, 0.05),
                "Airbrush": (0.0, 0.2, 0.05),
                "Eraser Soft": (0.0, 1.0, 0.10),
                "Eraser Hard": (1.0, 1.0, 0.10),
            }
            for name, (hardness, flow, spacing) in expected.items():
                settings = manager.load(name)
                self.assertTrue(manager.metadata(name)["builtIn"])
                self.assertEqual(settings["hardness"], hardness)
                self.assertEqual(settings["flow"], flow)
                self.assertEqual(settings["spacing"], spacing)
                self.assertFalse(manager.delete(name))
            self.assertTrue(manager.load("Eraser Soft")["eraser"])
            self.assertTrue(manager.load("Eraser Hard")["eraser"])
            duplicate = manager.duplicate("Round Soft", "My Soft Brush")
            self.assertIsNotNone(duplicate)
            self.assertFalse(manager.metadata("My Soft Brush")["builtIn"])

    def test_metadata_duplicate_import_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory, create_builtins=False)
            manager.save("Original", {"size": 42.0, "opacity": 0.5})
            manager.set_metadata("Original", category="Inking", favorite=True)
            duplicate = manager.duplicate("Original", "Copy")
            self.assertIsNotNone(duplicate)
            self.assertEqual(manager.metadata("Copy")["category"], "Inking")
            self.assertTrue(manager.metadata("Copy")["favorite"])
            exported = Path(directory) / "outside.csb.json"
            self.assertTrue(manager.export_preset("Copy", exported))
            manager.delete("Copy")
            self.assertEqual(manager.import_preset(exported), "Copy")
            self.assertEqual(manager.load("Copy")["version"], 2)

    def test_csbr_is_a_validated_zip_with_required_png_assets(self) -> None:
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory, create_builtins=False)
            manager.save("Round Soft", {"size": 40, "hardness": 0.0, "color": [20, 30, 40, 255]})
            path = Path(directory) / "round-soft.csbr"
            self.assertTrue(manager.export_csbr("Round Soft", path))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {"brush.json", "texture.png", "preview.png"})
                self.assertTrue(archive.testzip() is None)
            imported = Path(directory) / "imported.csbr"
            imported.write_bytes(path.read_bytes())
            other = BrushPresetManager(Path(directory) / "other", create_builtins=False)
            self.assertEqual(other.import_csbr(imported), "Round Soft")
            self.assertEqual(other.load("Round Soft")["size"], 40)
            roundtrip = Path(directory) / "roundtrip.csbr"
            self.assertTrue(other.export_csbr("Round Soft", roundtrip))
            with zipfile.ZipFile(path) as before, zipfile.ZipFile(roundtrip) as after:
                self.assertEqual(before.read("texture.png"), after.read("texture.png"))
                self.assertEqual(before.read("preview.png"), after.read("preview.png"))

    def test_csbr_rejects_missing_entries_and_invalid_png(self) -> None:
        import json
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(Path(directory) / "presets", create_builtins=False)
            path = Path(directory) / "bad.csbr"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("brush.json", json.dumps({"format": "CreativeSystemBrushPreset", "name": "Bad"}))
            self.assertIsNone(manager.import_csbr(path))

    def test_csbr_round_trips_optional_full_color_bitmap_tip(self) -> None:
        import base64
        from PySide6.QtGui import QColor, QImage
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory, create_builtins=False)
            tip = QImage(8, 8, QImage.Format.Format_RGBA8888)
            tip.fill(QColor(230, 30, 50, 255))
            encoded = manager._png_bytes(tip)
            manager.save("Stamped", {
                "size": 24,
                "_csbr_bitmap_tip_png": base64.b64encode(encoded).decode("ascii"),
            })
            path = Path(directory) / "stamped.csbr"
            self.assertTrue(manager.export_csbr("Stamped", path))
            imported = BrushPresetManager(Path(directory) / "copy", create_builtins=False)
            self.assertEqual(imported.import_csbr(path), "Stamped")
            settings = imported.load("Stamped")
            self.assertEqual(
                base64.b64decode(settings["_csbr_bitmap_tip_png"], validate=True),
                encoded,
            )


if __name__ == "__main__":
    unittest.main()
