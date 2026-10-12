"""Photoshop .abr import, on a synthetic v6.2 file built byte by byte."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from TOOLS.abr_import import AbrError, import_abr, read_abr
from TOOLS.brush_preset_manager import BrushPresetManager

APP = QApplication.instance() or QApplication([])
UUID = "11111111-2222-3333-4444-555555555555"


def _ustr(text):
    return struct.pack(">I", len(text) + 1) + (text + "\0").encode("utf-16-be")


def _key(text):
    return struct.pack(">I", 0) + text.encode("latin-1") if len(text) == 4 else \
        struct.pack(">I", len(text)) + text.encode("latin-1")


def _unit(unit, value):
    return b"UntF" + unit.encode() + struct.pack(">d", value)


def _obj(cls, items):
    body = _ustr("") + _key(cls) + struct.pack(">I", len(items))
    for name, encoded in items:
        body += _key(name) + encoded
    return body


def _packbits_row(row):
    out = b""
    for i in range(0, len(row), 128):
        chunk = row[i:i + 128]
        out += bytes([len(chunk) - 1]) + chunk
    return out


def build_abr(width=20, height=10):
    rows = [bytes((255 if 5 <= x < 15 else 0) for x in range(width)) for _ in range(height)]
    packed = [_packbits_row(r) for r in rows]
    sample = bytes([len(UUID)]) + UUID.encode() + b"\0" * (301 - 1 - len(UUID))
    sample += struct.pack(">4iH", 0, 0, height, width, 8) + b"\x01"
    sample += b"".join(struct.pack(">H", len(p)) for p in packed) + b"".join(packed)
    sample = struct.pack(">I", len(sample)) + sample + b"\0" * ((4 - len(sample) % 4) % 4)
    tip = _obj("sampledBrush", [
        ("Dmtr", _unit("#Pxl", 42.0)), ("Angl", _unit("#Ang", 30.0)),
        ("Rndn", _unit("#Prc", 80.0)), ("Spcn", _unit("#Prc", 12.0)),
        ("sampledData", b"TEXT" + _ustr(UUID))])
    pen = lambda minimum: b"Objc" + _obj("brVr", [("bVTy", b"long" + struct.pack(">i", 2)),
                                                  ("Mnm ", _unit("#Prc", minimum))])
    preset = _obj("brushPreset", [
        ("Nm  ", b"TEXT" + _ustr("Test Ink")), ("Brsh", b"Objc" + tip),
        ("useTipDynamics", b"bool\x01"), ("minimumDiameter", _unit("#Prc", 20.0)),
        ("szVr", pen(0.0)), ("usePaintDynamics", b"bool\x01"), ("opVr", pen(30.0)),
        ("dualBrush", b"Objc" + _obj("dualBrush", [
            ("useDualBrush", b"bool\x01"),
            ("Brsh", b"Objc" + _obj("computedBrush", [("Dmtr", _unit("#Pxl", 21.0)),
                                                     ("Hrdn", _unit("#Prc", 50.0)),
                                                     ("Spcn", _unit("#Prc", 80.0))])),
            ("BlnM", b"enum" + _key("BlnM") + _key("CBrn"))]))])
    desc = struct.pack(">I", 16) + _obj("null", [("Brsh", b"VlLs" + struct.pack(">I", 1) + b"Objc" + preset)])
    def section(name, data):
        return b"8BIM" + name + struct.pack(">I", len(data)) + data
    return struct.pack(">HH", 6, 2) + section(b"samp", sample) + section(b"patt", b"") + section(b"desc", desc)


class AbrImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.abr"
        self.path.write_bytes(build_abr())

    def tearDown(self):
        self.tmp.cleanup()

    def test_tip_and_settings_are_converted(self):
        brush = read_abr(self.path).brushes[0]
        settings = brush.settings
        self.assertEqual(brush.name, "Test Ink")
        self.assertEqual(settings["size"], 42.0)
        self.assertAlmostEqual(settings["spacing"], 0.12)
        self.assertAlmostEqual(settings["roundness"], 0.80)
        self.assertEqual(settings["angle"], 30.0)
        self.assertTrue(settings["pressureSize"])
        self.assertAlmostEqual(settings["minimumSize"], 0.20)
        self.assertTrue(settings["pressureOpacity"])
        self.assertAlmostEqual(settings["minimumOpacity"], 0.30)
        self.assertFalse(settings["wetMix"])          # full default state, no leftovers
        self.assertTrue(settings["dualBrush"])
        self.assertAlmostEqual(settings["dualSizeRatio"], 0.5)
        self.assertAlmostEqual(settings["dualSpacing"], 0.80)
        self.assertAlmostEqual(settings["dualHardness"], 0.50)
        self.assertEqual(settings["dualMode"], 2.0)          # colour burn
        from PySide6.QtGui import QImage
        import base64
        tip = QImage.fromData(base64.b64decode(settings["_csbr_bitmap_tip_png"]))
        self.assertEqual(tip.width(), tip.height())   # padded square, aspect kept
        self.assertEqual(tip.pixelColor(10, 10).alpha(), 255)   # centre band painted
        self.assertEqual(tip.pixelColor(2, 10).alpha(), 0)

    def test_import_into_library_with_category_and_no_clash(self):
        manager = BrushPresetManager(Path(self.tmp.name) / "lib")
        names, _report = import_abr(self.path, manager)
        again, _ = import_abr(self.path, manager)
        self.assertEqual(names, ["Test Ink"])
        self.assertEqual(again, ["Test Ink (2)"])
        self.assertEqual(manager.metadata("Test Ink")["category"], "Importé — test")

    def test_legacy_and_garbage_files_are_rejected_cleanly(self):
        legacy = Path(self.tmp.name) / "old.abr"
        legacy.write_bytes(struct.pack(">HH", 2, 3) + b"\0" * 32)
        with self.assertRaises(AbrError):
            read_abr(legacy)
        garbage = Path(self.tmp.name) / "bad.abr"
        garbage.write_bytes(b"\x00\x06\x00\x02" + b"8BIMsamp\xff\xff\xff\xff")
        try:
            read_abr(garbage)
        except AbrError:
            pass   # a clean refusal is fine; a crash is not


if __name__ == "__main__":
    unittest.main()
