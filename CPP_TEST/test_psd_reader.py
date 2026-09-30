"""Lecteur PSD natif de Nebula (DOCUMENTS/psd_reader.py) - sans Qt.

Construit de petits PSD en mémoire (dossiers imbriqués, écrêtage, masque,
compression RLE, calque de réglage « Courbe de transfert de dégradé » tel que
Photoshop 2026 l'écrit) et vérifie la structure décodée.
"""
from __future__ import annotations

import struct
import sys
import unittest
import zlib
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("NumPy absent")

from DOCUMENTS import psd_reader as reader  # noqa: E402
from DOCUMENTS.format_psd import PSDFormat, PSDImportCancelled  # noqa: E402

# Bloc « grdm » écrit par Photoshop 2026 (dégradé « Santa », rouge -> vert).
GRDM_PS2026 = bytes.fromhex(
    "00030000536d6f6f0000000600530061006e007400610000000200000000000000320000e1e1"
    "0000191a0000000000001000000000320000000060601b1c000000000002000000000000003200"
    "ff000010000000003200ff000210000020000036f8407500000000000008000003000000000000"
    "000080008000800080000000")


def packbits(row: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(row):
        run = 1
        while i + run < len(row) and row[i + run] == row[i] and run < 128:
            run += 1
        if run >= 2:
            out += bytes(((257 - run) & 0xFF, row[i]))
            i += run
        else:
            out += bytes((0, row[i]))
            i += 1
    return bytes(out)


def block(key: bytes, data: bytes) -> bytes:
    data += b"\0" * ((4 - len(data) % 4) % 4)
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def luni(name: str) -> bytes:
    return block(b"luni", struct.pack(">I", len(name)) + name.encode("utf-16-be"))


def layer(name, rect=(0, 0, 0, 0), pixels=None, mode=b"norm", opacity=255, clipping=0,
          hidden=False, extra=b"", mask=None, compression=1):
    """(record bytes, channel data bytes)."""
    top, left, bottom, right = rect
    w, h = right - left, bottom - top
    channels = []
    if pixels is not None:
        for cid, plane in ((-1, pixels[..., 3]), (0, pixels[..., 0]), (1, pixels[..., 1]),
                           (2, pixels[..., 2])):
            channels.append((cid, plane))
    else:
        for cid in (-1, 0, 1, 2):
            channels.append((cid, np.zeros((max(h, 0), max(w, 0)), np.uint8)))
    mask_record = struct.pack(">I", 0)
    if mask is not None:
        (mt, ml, mb, mr), default, data = mask
        mask_record = struct.pack(">I", 20) + struct.pack(">4iBBH", mt, ml, mb, mr, default, 0, 0)
        channels.append((-2, data))
    payloads = []
    for cid, plane in channels:
        if plane.size == 0:
            payloads.append((cid, struct.pack(">H", 0)))
        elif compression == 1:
            rows = [packbits(plane[y].tobytes()) for y in range(plane.shape[0])]
            payloads.append((cid, struct.pack(">H", 1) + b"".join(struct.pack(">H", len(r)) for r in rows)
                             + b"".join(rows)))
        else:
            payloads.append((cid, struct.pack(">H", 2) + zlib.compress(plane.tobytes())))
    record = struct.pack(">4iH", top, left, bottom, right, len(payloads))
    for cid, payload in payloads:
        record += struct.pack(">hI", cid, len(payload))
    record += b"8BIM" + mode + bytes((opacity, clipping, 2 if hidden else 0, 0))
    encoded = name.encode("mac_roman", "replace")[:255]
    pascal = bytes((len(encoded),)) + encoded
    pascal += b"\0" * ((4 - len(pascal) % 4) % 4)
    extra_data = mask_record + struct.pack(">I", 0) + pascal + luni(name) + extra
    record += struct.pack(">I", len(extra_data)) + extra_data
    return record, b"".join(payload for _cid, payload in payloads)


def build_psd(width, height, layers, composite=None) -> bytes:
    info = struct.pack(">h", len(layers)) + b"".join(r for r, _ in layers) + b"".join(d for _, d in layers)
    info += b"\0" * (len(info) % 2)
    section = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)
    out = b"8BPS" + struct.pack(">H", 1) + b"\0" * 6 + struct.pack(">HIIHH", 3, height, width, 8, 3)
    out += struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", len(section)) + section
    comp = composite if composite is not None else np.zeros((height, width, 3), np.uint8)
    out += struct.pack(">H", 0) + b"".join(comp[..., c].tobytes() for c in range(3))
    return out


def solid(h, w, color):
    array = np.zeros((h, w, 4), np.uint8)
    array[...] = color
    return array


class PSDReaderTests(unittest.TestCase):
    def build_sample(self):
        # Bas -> haut : fond, [Dossier: [Sous-dossier: base, écrêté], libre], réglage.
        records = [
            layer("Fond", (0, 0, 8, 8), solid(8, 8, (10, 20, 30, 255))),
            layer("</Layer group>", extra=block(b"lsct", struct.pack(">I", 3))),
            layer("</Layer group>", extra=block(b"lsct", struct.pack(">I", 3))),
            layer("Base", (2, 2, 6, 6), solid(4, 4, (200, 100, 50, 128)), compression=2),
            layer("Écrêté", (0, 0, 8, 8), solid(8, 8, (0, 255, 0, 255)), clipping=1,
                  mode=b"mul ", mask=((1, 1, 3, 3), 0, np.full((2, 2), 200, np.uint8))),
            layer("Sous-dossier", extra=block(b"lsct", struct.pack(">I", 1) + b"8BIMpass")),
            layer("Libre", (0, 0, 1, 1), solid(1, 1, (1, 2, 3, 255)), hidden=True),
            layer("Dossier", opacity=128, extra=block(b"lsct", struct.pack(">I", 1))),
            layer("Dégradé", mode=b"mul ", opacity=209, clipping=1,
                  extra=block(b"grdm", GRDM_PS2026) + block(b"iOpa", bytes((128, 0, 0, 0)))),
        ]
        return build_psd(8, 8, records)

    def test_structure_groups_clipping_masks(self):
        psd = reader.read_psd(self.build_sample())
        self.assertEqual([item.name for item in psd.root], ["Fond", "Dossier", "Dégradé"])
        folder = psd.root[1]
        self.assertTrue(folder.is_group)
        self.assertEqual(folder.opacity, 128)
        self.assertEqual([item.name for item in folder.children], ["Sous-dossier", "Libre"])
        sub = folder.children[0]
        self.assertEqual(sub.section_blend_key, "pass")
        base, clipped = sub.children
        self.assertEqual(base.rgba.shape, (4, 4, 4))
        self.assertEqual(tuple(base.rgba[0, 0]), (200, 100, 50, 128))       # ZIP
        self.assertTrue(clipped.clipping)
        self.assertEqual(clipped.blend_key, "mul ")
        self.assertEqual(tuple(clipped.rgba[5, 5]), (0, 255, 0, 255))        # RLE
        self.assertEqual((clipped.mask.left, clipped.mask.top, clipped.mask.default_color), (1, 1, 0))
        self.assertEqual(int(clipped.mask.data[0, 0]), 200)
        self.assertTrue(folder.children[1].hidden)
        self.assertEqual(len(psd.layers), 7)

    def test_gradient_map_as_written_by_photoshop(self):
        psd = reader.read_psd(self.build_sample())
        adjustment = psd.root[2]
        self.assertEqual(adjustment.kind, "adjustment")
        self.assertEqual(adjustment.fill_opacity, 128)
        settings = adjustment.adjustment["gradient_map"]
        self.assertEqual(settings["name"], "Santa")
        self.assertEqual([stop["color"] for stop in settings["stops"]], [[225, 0, 25], [0, 96, 27]])
        self.assertEqual([stop["location"] for stop in settings["stops"]], [0.0, 1.0])
        self.assertFalse(settings["reverse"])

    def test_gradient_table_endpoints_and_midpoint(self):
        try:
            from DOCUMENTS.adjustments import gradient_map_table
        except Exception as error:  # noqa: BLE001 - Qt absent
            self.skipTest(f"adjustments indisponible : {error}")
        table = np.frombuffer(gradient_map_table({"stops": [
            {"location": 0.0, "color": [0, 0, 0]},
            {"location": 1.0, "midpoint": 0.25, "color": [255, 255, 255]}]}), np.uint8).reshape(256, 4)
        self.assertEqual(tuple(table[0]), (0, 0, 0, 255))
        self.assertEqual(tuple(table[255]), (255, 255, 255, 255))
        self.assertAlmostEqual(int(table[64, 0]), 128, delta=2)   # 50 % atteint à 25 %

    def test_cube_lut_round_trip(self):
        axis = np.linspace(0.0, 1.0, 3)
        lines = ["TITLE \"t\"", "LUT_3D_SIZE 3"]
        for b in axis:
            for g in axis:
                for r in axis:
                    lines.append(f"{1 - r:.6f} {g:.6f} {b:.6f}")
        size, table, low, high = reader.parse_cube_lut("\n".join(lines))
        self.assertEqual(size, 3)
        self.assertAlmostEqual(float(table[0, 0, 2, 0]), 0.0)     # r = 1 -> 1 - r
        encoded = reader.encode_lut(size, table, low, high, "t.cube")
        raw = np.frombuffer(zlib.decompress(__import__("base64").b64decode(encoded["data"])), "<u2")
        self.assertEqual(raw.size, 27 * 3)
        self.assertEqual(int(raw[0]), 65535)

    def test_python_packbits_matches_reference(self):
        rng = np.random.default_rng(3)
        row = bytes(rng.integers(0, 4, 300, dtype=np.uint8))
        self.assertEqual(reader.unpackbits(packbits(row), len(row)), row)

    def test_truncated_file_is_reported(self):
        data = self.build_sample()
        with self.assertRaises(reader.PSDError):
            reader.read_psd(data[:60])

    def test_progressive_import_budget_reads_only_header(self):
        from DOCUMENTS.psd_import import estimate_import_budget
        with TemporaryDirectory() as directory:
            path = Path(directory) / "budget.psd"
            path.write_bytes(self.build_sample())
            budget = estimate_import_budget(path)
        self.assertEqual((budget.width, budget.height, budget.channels, budget.bits_per_channel), (8, 8, 3, 8))
        self.assertGreaterEqual(budget.estimated_bytes, 8 * 8 * 4)

    def test_cancelled_import_does_not_attempt_a_fallback_decoder(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(PSDImportCancelled):
            PSDFormat.load("this-file-must-not-be-opened.psd", cancel=cancel)

    def test_blend_fallback_records_a_per_layer_limitation(self):
        warnings, limitations = [], []
        self.assertEqual(PSDFormat._blend_from_key("lddg", "Lumière", warnings, limitations),
                         "screen")
        self.assertEqual(warnings, ["Lumière : linear_dodge affiché comme screen"])
        self.assertEqual(limitations, ["linear_dodge affiché comme screen"])

    def test_raw_composite_region_avoids_full_composite_decode(self):
        composite = np.zeros((8, 8, 3), np.uint8)
        composite[..., 0] = np.arange(8, dtype=np.uint8)
        composite[..., 1] = 33
        with TemporaryDirectory() as directory:
            path = Path(directory) / "region.psd"
            path.write_bytes(build_psd(8, 8, [], composite))
            with patch.object(reader, "_read_composite", side_effect=AssertionError("full decode")):
                size, regions = reader.read_composite_regions(path, [(2, 3, 3, 2)])
        self.assertEqual(size, (8, 8))
        region = regions[(2, 3, 3, 2)]
        self.assertEqual(region.shape, (2, 3, 4))
        self.assertEqual(tuple(region[0, 0]), (2, 33, 0, 255))

    def test_zip_composite_region_avoids_full_composite_decode(self):
        composite = np.zeros((8, 8, 3), np.uint8)
        composite[..., 0] = np.arange(8, dtype=np.uint8)
        composite[..., 2] = 91
        raw = build_psd(8, 8, [], composite)
        plane_bytes = 8 * 8
        encoded = b"".join(composite[..., channel].tobytes() for channel in range(3))
        payload = raw[:-(2 + 3 * plane_bytes)] + struct.pack(">H", 2) + zlib.compress(encoded)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "region-zip.psd"
            path.write_bytes(payload)
            with patch.object(reader, "_read_composite", side_effect=AssertionError("full decode")):
                _size, regions = reader.read_composite_regions(path, [(2, 3, 3, 2)])
        self.assertEqual(tuple(regions[(2, 3, 3, 2)][0, 0]), (2, 0, 91, 255))

    def test_zip_prediction_composite_region_avoids_full_composite_decode(self):
        composite = np.zeros((8, 8, 3), np.uint8)
        composite[..., 0] = np.arange(8, dtype=np.uint8)
        composite[..., 1] = 47
        raw = build_psd(8, 8, [], composite)
        plane_bytes = 8 * 8
        predicted = []
        for channel in range(3):
            plane = composite[..., channel]
            delta = plane.copy()
            delta[:, 1:] = plane[:, 1:] - plane[:, :-1]
            predicted.append(delta.tobytes())
        payload = raw[:-(2 + 3 * plane_bytes)] + struct.pack(">H", 3) + zlib.compress(b"".join(predicted))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "region-zip-prediction.psd"
            path.write_bytes(payload)
            with patch.object(reader, "_read_composite", side_effect=AssertionError("full decode")):
                _size, regions = reader.read_composite_regions(path, [(2, 3, 3, 2)])
        self.assertEqual(tuple(regions[(2, 3, 3, 2)][0, 0]), (2, 47, 0, 255))

    def test_viewport_deferral_classifies_only_distant_raster_layers(self):
        nearby = reader.PSDLayer("near", 0, 0, 20, 20)
        distant = reader.PSDLayer("far", 100, 100, 120, 120)
        hidden = reader.PSDLayer("hidden", 0, 0, 20, 20, hidden=True)
        self.assertFalse(PSDFormat._defer_raster_layer(nearby, (0, 0, 64, 64)))
        self.assertTrue(PSDFormat._defer_raster_layer(distant, (0, 0, 64, 64)))
        self.assertTrue(PSDFormat._defer_raster_layer(hidden, (0, 0, 64, 64)))

    def test_16_bit_rgb_composite_fixture_is_downconverted_predictably(self):
        width, height = 2, 1
        planes = [np.array([0x1234, 0xFFFF], dtype=">u2"),
                  np.array([0x8000, 0x0000], dtype=">u2"),
                  np.array([0xABCD, 0x0100], dtype=">u2")]
        payload = (b"8BPS" + struct.pack(">H", 1) + b"\0" * 6
                   + struct.pack(">HIIHH", 3, height, width, 16, 3)
                   + b"\0" * 8 + struct.pack(">I", 0) + struct.pack(">H", 0)
                   + b"".join(plane.tobytes() for plane in planes))
        psd = reader.read_psd(payload)
        self.assertEqual(psd.depth, 16)
        self.assertEqual(tuple(psd.composite[0, 0]), (0x12, 0x80, 0xAB, 255))
        self.assertEqual(tuple(psd.composite[0, 1]), (255, 0, 1, 255))

    def test_real_sample_if_available(self):
        import os
        path = os.environ.get("NEBULA_PSD_SAMPLE")
        if not path:
            self.skipTest("NEBULA_PSD_SAMPLE non défini")
        psd = reader.read_psd(path)
        self.assertTrue(psd.layers)
        self.assertEqual(psd.warnings, [])


if __name__ == "__main__":
    unittest.main()
