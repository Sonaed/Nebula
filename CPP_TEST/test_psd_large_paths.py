"""Pixel and work-count oracles for large PSD import paths."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from DOCUMENTS.document import Document
from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS import psd_reader as reader
from UI.docks.layers_dock import LayersDock
from CPP_TEST.test_psd_reader import build_psd, packbits
from CORE.tile_cache_manager import TileCacheManager, CacheBudgets


class ViewportDemandTests(unittest.TestCase):
    def test_stationary_view_reuses_halo_while_tiles_arrive(self):
        manager = TileCacheManager(CacheBudgets(projection_tiles=32))
        visible = {(x, y) for x in range(40) for y in range(30)}
        expected = manager.update(visible, zoom=.2)
        halo = manager.prefetch
        for tile in visible:
            manager.mark_ready(tile)
        self.assertEqual(manager.update(visible, zoom=.2), expected)
        self.assertIs(manager.prefetch, halo)
        self.assertLessEqual(len(manager.recent), 32)

    def test_cache_reacts_to_direction_zoom_and_available_tiles(self):
        manager = TileCacheManager()
        visible = {(4, 4)}
        self.assertIn((7, 4), manager.update(visible, pan_delta=(-80, 0)))
        self.assertNotIn((7, 4), manager.update(visible, pan_delta=(80, 0)))
        self.assertEqual(manager.update(visible, pan_delta=(-80, 0), zoom=.2), visible)
        self.assertEqual(manager.update(visible, all_keys=visible), visible)
        self.assertIn((5, 4), manager.update(visible, all_keys=visible | {(5, 4)}))

    def test_active_group_change_refreshes_retention(self):
        manager = TileCacheManager()
        manager.update({(1, 1)})
        manager.update({(1, 1)}, active_group_keys={(20, 20)})
        self.assertTrue(manager.should_retain((20, 20)))

    def test_pan_retains_previous_visible_before_speculative_halo(self):
        manager = TileCacheManager(CacheBudgets(projection_tiles=8))
        manager.update({(4, 4)})
        manager.update({(5, 4)}, pan_delta=(-80, 0))
        self.assertTrue(manager.should_retain((4, 4)))

class LargePSDPathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_import_exact_pixels_offsets_and_transparency(self):
        rng = np.random.default_rng(419)
        for left, top in ((0, 0), (-21, -17), (50, 40), (140, 120)):
            with self.subTest(left=left, top=top):
                doc = Document(131, 99, 72, None)
                source = rng.integers(0, 256, (170, 206, 4), dtype=np.uint8)[::2, ::2]
                source[5:30, 3:21, 3] = 0
                original = source.copy()
                PSDFormat._write_pixels(doc.layers[0], source, left, top, doc)
                expected = np.zeros((99, 131, 4), np.uint8)
                x0, y0 = max(0, left), max(0, top)
                x1, y1 = min(131, left + 103), min(99, top + 85)
                if x1 > x0 and y1 > y0:
                    expected[y0:y1, x0:x1] = source[y0-top:y1-top, x0-left:x1-left]
                expected[expected[..., 3] == 0] = 0
                actual = doc.layers[0].image.convertToFormat(QImage.Format.Format_RGBA8888)
                actual = np.frombuffer(actual.constBits(), np.uint8).reshape(99, 131, 4).copy()
                np.testing.assert_array_equal(actual, expected)
                np.testing.assert_array_equal(source, original)
                doc.layers[0].tile_store.close()

    def test_transparent_import_stays_sparse_and_rejects_nonempty_store(self):
        doc = Document(130, 97, 72, None)
        source = np.full((97, 130, 4), 200, np.uint8); source[..., 3] = 0
        PSDFormat._write_pixels(doc.layers[0], source, 0, 0, doc)
        self.assertEqual(doc.layers[0].tile_store.occupied_keys, set())
        source[1, 1] = [19, 22, 37, 1]
        PSDFormat._write_pixels(doc.layers[0], source, 0, 0, doc)
        self.assertEqual(doc.layers[0].tile_store.occupied_keys, {(0, 0)})
        with self.assertRaises(ValueError):
            PSDFormat._write_pixels(doc.layers[0], source, 0, 0, doc)

    def test_native_thumbnail_matches_existing_painter(self):
        rng = np.random.default_rng(813)
        for width, height in ((131, 99), (99, 131), (513, 367)):
            doc = Document(width, height, 72, None)
            source = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
            PSDFormat._write_pixels(doc.layers[0], source, 0, 0, doc)
            store = doc.layers[0].tile_store
            with patch.object(store, 'thumbnail', return_value=None):
                expected = LayersDock._tile_thumbnail(store)
            actual = store.thumbnail()
            self.assertIsNotNone(actual)
            self.assertEqual(actual, expected)

    def test_adjacent_composite_tiles_share_decode_and_preserve_pixels(self):
        rng = np.random.default_rng(3)
        composite = rng.integers(0, 256, (9, 23, 3), dtype=np.uint8)
        raw = build_psd(23, 9, [], composite)
        body = raw[:-(23*9*3 + 2)]
        rows = [packbits(composite[y, :, c].tobytes()) for c in range(3) for y in range(9)]
        planes = b''.join(composite[..., c].tobytes() for c in range(3))
        payloads = (raw, body + struct.pack('>H', 1) + b''.join(struct.pack('>H', len(row)) for row in rows) + b''.join(rows),
                    body + struct.pack('>H', 2) + zlib.compress(planes))
        rectangles = [(10, 0, 5, 4), (0, 0, 5, 4), (5, 0, 5, 4), (3, 0, 5, 4),
                      (20, 0, 3, 4), (0, 4, 5, 5)]
        for compression, payload in enumerate(payloads):
            with self.subTest(compression=compression), TemporaryDirectory() as directory:
                path = Path(directory) / 'sample.psd'; path.write_bytes(payload)
                with patch.object(reader, '_read_composite_region', wraps=reader._read_composite_region) as decode:
                    size, regions = reader.read_composite_regions(path, rectangles)
                self.assertEqual(size, (23, 9))
                self.assertEqual(decode.call_count, 3)
                for rect, pixels in regions.items():
                    x, y, w, h = rect
                    np.testing.assert_array_equal(pixels[..., :3], composite[y:y+h, x:x+w])
                    self.assertTrue((pixels[..., 3] == 255).all())

if __name__ == '__main__':
    unittest.main()
