from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from TOOLS.brush_preset_manager import BrushPresetManager


class BrushPresetV2Tests(unittest.TestCase):
    def test_base_library_has_34_categorized_presets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory)
            names = manager.list_presets()
            self.assertEqual(len(names), 34)
            self.assertEqual(set(manager.categories()), {"01_Sketching", "02_Inking", "03_Painting", "04_Airbrush", "05_Texture", "06_Erasers", "07_Utility"})
            self.assertEqual({name for name in names if manager.metadata(name)["favorite"]}, {"Pencil HB", "Ink Pen", "Round Soft", "Oil Round", "Airbrush Soft", "Eraser Soft"})
            self.assertFalse(manager.load("Pixel")["antialiasing"])
            self.assertEqual(manager.load("G-Pen")["pressureCurve"], 2)
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
            self.assertEqual(manager.load("Copy")["version"], 3)

    def test_csbr_is_a_validated_zip_with_required_png_assets(self) -> None:
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory, create_builtins=False)
            manager.save("Round Soft", {"size": 40, "hardness": 0.0, "color": [20, 30, 40, 255]})
            path = Path(directory) / "round-soft.csbr"
            self.assertTrue(manager.export_csbr("Round Soft", path))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"brush.json", "manifest.json", "texture.png", "preview.png"},
                )
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

    def test_csbr_v3_rejects_tampered_asset(self) -> None:
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            manager = BrushPresetManager(directory, create_builtins=False)
            manager.save("Safe", {"size": 20, "hardness": 0.5})
            valid = Path(directory) / "safe.csbr"
            self.assertTrue(manager.export_csbr("Safe", valid))
            tampered = Path(directory) / "tampered.csbr"
            with zipfile.ZipFile(valid) as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    payload = source.read(info.filename)
                    target.writestr(info.filename, b"changed" if info.filename == "preview.png" else payload)
            self.assertIsNone(manager.import_csbr(tampered))

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
