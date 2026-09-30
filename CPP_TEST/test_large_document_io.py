"""Regression checks for streaming PSD import and sparse 8K documents."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from DOCUMENTS.document import Document
from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.format_nebula import NebulaFormat
from DOCUMENTS.psd_reader import read_psd, PSDError
from CPP_TEST import test_psd_reader as fixtures
from CPP_TEST.test_psd_reader import build_psd, layer, solid


class LargeDocumentIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lazy_mapped_pixels_match_eager_in_reverse_order(self):
        data = fixtures.PSDReaderTests().build_sample()
        eager = read_psd(data, composite=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.psd'
            path.write_bytes(data)
            with read_psd(path, composite=False, lazy_layers=True) as lazy:
                mapped = lazy._mapped_source
                self.assertTrue(all(item.rgba is None for item in lazy.layers))
                for actual, expected in reversed(list(zip(lazy.layers, eager.layers))):
                    actual.decode_pixels()
                    np.testing.assert_array_equal(actual.rgba, expected.rgba)
                    if expected.mask is not None:
                        np.testing.assert_array_equal(actual.mask.data, expected.mask.data)
                    actual.release_pixels()
                    self.assertIsNone(actual.rgba)
            self.assertTrue(mapped.closed)

    def test_import_clips_negative_offset_and_tile_edges(self):
        pixels = solid(135, 139, (11, 57, 213, 128))
        pixels[10, 10] = (1, 2, 3, 0)
        data = build_psd(130, 129, [layer('edges', (-3, -5, 132, 134), pixels, compression=2)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'edges.psd'
            path.write_bytes(data)
            document = PSDFormat._load_native(path)
        actual = document.layers[0].image
        self.assertEqual(actual.pixelColor(0, 0).getRgb(), (11, 57, 213, 128))
        self.assertEqual(actual.pixelColor(129, 128).getRgb(), (11, 57, 213, 128))
        self.assertEqual(actual.pixelColor(5, 7).alpha(), 0)

    def test_8k_50_layers_stay_sparse_and_round_trip(self):
        with patch('DOCUMENTS.tile_store.TileStore.materialize', side_effect=AssertionError('dense layer')):
            document = Document(8000, 8000)
            for index in range(49):
                document.add_layer(str(index))
            self.assertTrue(all(item._image_cache is None for item in document.layers))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'large.nebula'
                self.assertTrue(NebulaFormat.save(document, path))
                restored = NebulaFormat.load(path)
            self.assertIsNotNone(restored)
            self.assertEqual(len(restored.layers), 50)
            self.assertEqual((restored.width, restored.height), (8000, 8000))
            self.assertTrue(all(not item.tile_store.occupied_keys for item in restored.layers))

    def test_psd_and_psb_export_keep_order_pixels_and_sparse_masks(self):
        from PySide6.QtGui import QColor, QImage
        from DOCUMENTS.layer_group import LayerGroup
        document = Document(70, 67)
        document.layers[0].name = 'bottom'
        document.layers[0].image.fill(QColor('red'))
        top = document.add_layer('top')
        top.image.fill(QColor('blue'))
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(QColor(255, 255, 255, 128))
        top.ensure_alpha_mask().set_tile(0, 0, tile)
        document.layer_groups.append(LayerGroup(name='folder', layer_ids=[top.id]))
        with tempfile.TemporaryDirectory() as directory:
            for extension, version in [('psd', 1), ('psb', 2)]:
                path = Path(directory) / ('export.' + extension)
                self.assertTrue(PSDFormat.save(document, path))
                with read_psd(path) as result:
                    self.assertEqual(result.version, version)
                    raster = [item for item in result.layers if not item.is_group]
                    self.assertEqual([item.name for item in raster], ['bottom', 'top'])
                    self.assertEqual(tuple(raster[0].rgba[0, 0]), (255, 0, 0, 255))
                    self.assertEqual(tuple(raster[1].rgba[0, 0]), (0, 0, 255, 255))
                    self.assertEqual(int(raster[1].mask.data[0, 0]), 128)
                    self.assertEqual(int(raster[1].mask.data[66, 69]), 255)
                    self.assertEqual(result.root[1].children[0].name, 'top')
                restored = PSDFormat._load_native(path)
                self.assertEqual([item.name for item in restored.layers], ['bottom', 'top'])

    def test_curves_adjustment_exports_as_editable_psd_record(self):
        document = Document(16, 16)
        document.add_adjustment_layer('curves', 'Courbes', {
            'kind': 'curves', 'curves': {
                'points': [[0, 0], [128, 160], [255, 255]],
                'channels': {'red': [[0, 0], [255, 220]]},
            }})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'curves.psd'
            self.assertTrue(PSDFormat.save(document, path))
            restored = PSDFormat._load_native(path)
        adjustment = next(layer for layer in restored.layers if layer.layer_kind == 'adjustment')
        self.assertEqual(adjustment.adjustment['kind'], 'curves')
        self.assertEqual(adjustment.adjustment['curves']['points'], [[0, 0], [128, 160], [255, 255]])
        self.assertEqual(adjustment.adjustment['curves']['channels']['red'], [[0, 0], [255, 220]])

    def test_preview_never_decodes_layer_pixels(self):
        from DOCUMENTS.psd_import import build_overview, decode_composite_tiles
        data = fixtures.PSDReaderTests().build_sample()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.psd'
            path.write_bytes(data)
            with patch('DOCUMENTS.psd_reader._decode_layer_pixels', side_effect=AssertionError('decoded layers')):
                png, size = build_overview(path)
                self.assertEqual(size, (8, 8))
                self.assertTrue(png.startswith(b'\x89PNG'))
                size, tiles = decode_composite_tiles(path, (0, 0, 8, 8))
                self.assertEqual(size, (8, 8))
                self.assertTrue(tiles[(0, 0)].startswith(b'\x89PNG'))

    def test_save_as_dispatches_photoshop_formats_to_layered_writer(self):
        from types import SimpleNamespace
        from CORE.application import CreativeSystem
        document = Document(8, 8)
        fake = SimpleNamespace(canvas=SimpleNamespace(document=document),
            _remember_file_directory=lambda path: None,
            _remember_recent_document=lambda path: None,
            update_window_title=lambda: None)
        for extension in ('psd', 'psb'):
            path = '/tmp/save-as-test.' + extension
            with patch('CORE.application.QFileDialog.getSaveFileName', return_value=(path, '')), \
                 patch.object(PSDFormat, 'save', return_value=True) as save:
                CreativeSystem.save_file_as(fake)
                save.assert_called_once_with(document, path)
                self.assertEqual(fake.current_file, path)

    def test_gpu_cache_hit_refreshes_eviction_order(self):
        from types import SimpleNamespace
        from CANVAS.gpu_tile_compositor import GPUTileCompositor
        compositor = GPUTileCompositor(None)
        compositor._initialize = lambda: None
        compositor._revision = lambda *args: ('unchanged',)
        compositor.tiles = {
            (0, 0): SimpleNamespace(revision=('unchanged',), texture_id=101),
            (1, 0): SimpleNamespace(revision=('unchanged',), texture_id=102),
        }
        self.assertEqual(compositor.compose_tile(None, 0, 0, (), True), 101)
        self.assertEqual(list(compositor.tiles), [(1, 0), (0, 0)])

    def test_native_io_keeps_v1_crc_and_rejects_corruption(self):
        import struct
        import zlib
        from PySide6.QtGui import QColor, QImage
        from CORE.native_bridge import NebulaReaderHandle, NebulaWriterHandle
        document = Document(3, 2)
        image = QImage(3, 2, QImage.Format.Format_RGBA8888)
        image.fill(QColor(17, 83, 219, 123))
        document.layers[0].image = image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'direct.nebula'
            with patch.object(NebulaWriterHandle, 'add_tile', side_effect=AssertionError('Python tile copy')):
                self.assertTrue(NebulaFormat.save(document, path))
            data = bytearray(path.read_bytes())
            metadata_size = struct.unpack_from('<I', data, 8)[0]
            offset = 16 + metadata_size
            kind, chunk_id, raw_size, packed_size, crc = struct.unpack_from('<4sIQQI', data, offset)
            self.assertEqual(kind, b'TILE')
            raw = zlib.decompress(data[offset + 32:offset + 28 + packed_size])
            self.assertEqual(len(raw), raw_size)
            self.assertEqual(zlib.crc32(raw), crc)
            with patch.object(NebulaReaderHandle, 'next_tile', side_effect=AssertionError('Python tile copy')):
                restored = NebulaFormat.load(path)
            self.assertEqual(restored.layers[0].image.pixelColor(2, 1), QColor(17, 83, 219, 123))
            data[offset + 24] ^= 1  # break the checksum without changing the data
            path.write_bytes(data)
            self.assertIsNone(NebulaFormat.load(path))

    def test_lazy_truncated_channels_are_rejected(self):
        data = build_psd(8, 8, [layer('sample', (0, 0, 8, 8), solid(8, 8, (1, 2, 3, 255)))])
        with self.assertRaises(PSDError):
            read_psd(data[:100], composite=False, lazy_layers=True)


if __name__ == '__main__':
    unittest.main()
