import unittest
import tempfile
import struct
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEventLoop, QRect, QTimer
from PySide6.QtGui import QColor, QImage

from DOCUMENTS.tile_store import TileStore
from DOCUMENTS.layer import Layer
from CORE.projection_worker import ProjectionLayer, ProjectionWorker
from CORE.native_bridge import load_creative_core
from CORE.tile_compression import compress, decompress, encode_record, decode_record


class TileStoreTests(unittest.TestCase):
    def test_tile_store_requires_creative_core(self):
        with patch("DOCUMENTS.tile_store.create_native_tile_store", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                TileStore(32, 32)

    def test_legacy_lz4_codec_runs_through_creative_core(self):
        from CORE.native_bridge import load_creative_core
        if not load_creative_core().cs_lz4_available():
            self.skipTest("CreativeCore was built without optional LZ4")
        source = b"legacy-scratch-pixels" * 1024
        packed, compressed = compress(source)
        self.assertTrue(compressed)
        self.assertLess(len(packed), len(source))
        self.assertEqual(decompress(packed, len(source), True), source)

        raw = bytes(range(256))
        packed, compressed = compress(raw)
        self.assertFalse(compressed)
        self.assertEqual(decompress(packed, len(raw), False), raw)
        with self.assertRaises(ValueError):
            decompress(b"\x00", len(source), True)
        with self.assertRaises(ValueError):
            decompress(raw[:-1], len(raw), False)

    def test_legacy_cslz_scratch_roundtrip_and_header_validation(self):
        image = QImage(32, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor(23, 91, 207, 173))
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(rgba.constBits())
        encoded = encode_record(raw, rgba.width(), rgba.height(), rgba.bytesPerLine())
        self.assertIsNotNone(encoded)
        decoded = decode_record(encoded)
        self.assertEqual(decoded[:4], (raw, rgba.width(), rgba.height(), rgba.bytesPerLine()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tile.cslz"
            path.write_bytes(encoded)
            restored = TileStore._read_scratch(path, QImage.Format.Format_ARGB32)
            self.assertEqual(restored.pixelColor(10, 12), QColor(23, 91, 207, 173))

            path.write_bytes(struct.pack("<4s5I?", b"CSLZ", 4096, 4096,
                4096 * 4, 4096 * 4096 * 4, 1, True) + b"x")
            with self.assertRaises(ValueError):
                TileStore._read_scratch(path, QImage.Format.Format_ARGB32)

    def test_native_batch_set_updates_multiple_tiles(self):
        store = TileStore(128, 64, tile_size=64)
        self.assertIsNotNone(store._native_handle)
        red = QImage(64, 64, QImage.Format.Format_ARGB32)
        red.fill(QColor("red"))
        blue = QImage(64, 64, QImage.Format.Format_ARGB32)
        blue.fill(QColor(12, 80, 230, 170))
        self.assertTrue(store.set_tiles_batch([(0, 0, red), (1, 0, blue)]))
        self.assertEqual(store.materialize().pixelColor(10, 10), QColor("red"))
        self.assertEqual(store.materialize().pixelColor(70, 10), QColor(12, 80, 230, 170))

    def test_sparse_tiles_edges_and_materialize_round_trip(self):
        store = TileStore(70, 67, tile_size=64)
        self.assertIsNotNone(store._native_handle)
        source = QImage(70, 67, QImage.Format.Format_ARGB32)
        source.fill(QColor(200, 30, 70, 255))
        keys = store.write_image(source)
        self.assertEqual(keys, {(0, 0), (1, 0), (0, 1), (1, 1)})
        self.assertEqual(store.tile(1, 1).size(), source.copy(QRect(64, 64, 6, 3)).size())
        self.assertEqual(store.materialize().pixelColor(69, 66), QColor(200, 30, 70, 255))

    def test_dirty_rect_updates_only_intersecting_tile(self):
        store = TileStore(160, 64, tile_size=64)
        image = QImage(160, 64, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        store.write_image(image)
        revisions = [store.tile_revision(tx, 0) for tx in range(3)]
        image.fill(QColor("blue"))
        changed = store.write_image(image, QRect(70, 2, 4, 4))
        self.assertEqual(changed, {(1, 0)})
        self.assertEqual(store.tile_revision(0, 0), revisions[0])
        self.assertNotEqual(store.tile_revision(1, 0), revisions[1])
        self.assertEqual(store.tile_revision(2, 0), revisions[2])
        self.assertEqual(store.materialize().pixelColor(71, 3), QColor("blue"))
        self.assertEqual(store.materialize().pixelColor(1, 1), QColor("red"))

    def test_layer_compatibility_view_commits_and_releases(self):
        layer = Layer("test", 96, 64)
        layer.image.fill(QColor("green"))
        changed = layer.commit_image_cache(release=True)
        self.assertEqual(changed, {(0, 0), (1, 0)})
        self.assertIsNone(layer._image_cache)
        self.assertEqual(layer.image.pixelColor(80, 20), QColor("green"))

    def test_swapped_tile_reloads_losslessly_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor(20, 80, 190, 170))
            store.set_tile(0, 0, tile)
            self.assertGreater(store.evict_tile_to_scratch(0, 0), 0)
            self.assertTrue(store.has_tile(0, 0))
            self.assertEqual(store.swapped_tile_count, 1)
            reloaded = store.tile(0, 0)
            self.assertEqual(reloaded.pixelColor(10, 10), QColor(20, 80, 190, 170))
            self.assertEqual(store.materialize().pixelColor(10, 10), QColor(20, 80, 190, 170))

    def test_sparse_store_clone_runs_native_and_preserves_source_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            source = TileStore(128, 64)
            source.set_scratch_directory(directory)
            red = QImage(64, 64, QImage.Format.Format_ARGB32)
            red.fill(QColor("red"))
            blue = QImage(64, 64, QImage.Format.Format_ARGB32)
            blue.fill(QColor(20, 90, 230, 170))
            source.set_tile(0, 0, red)
            source.set_tile(1, 0, blue)
            self.assertGreater(source.evict_tile_to_scratch(1, 0), 0)
            self.assertFalse(source.tile_is_resident(1, 0))

            destination = TileStore(128, 64)
            self.assertTrue(destination.copy_occupied_tiles_from(source))

            self.assertFalse(source.tile_is_resident(1, 0))
            self.assertEqual(source.swapped_tile_count, 1)
            self.assertEqual(destination.occupied_keys, {(0, 0), (1, 0)})
            self.assertEqual(destination.tile(1, 0).pixelColor(5, 6),
                             QColor(20, 90, 230, 170))
            self.assertEqual(destination.swapped_tile_count, 0)

    def test_native_revisions_survive_residency_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("purple"))
            store.set_tile(0, 0, tile)
            revision = store.tile_revision(0, 0)
            self.assertGreater(revision, 0)
            self.assertGreater(store.tile_last_access(0, 0), 0)
            self.assertGreater(store.evict_tile_to_scratch(0, 0), 0)
            self.assertFalse(store.tile_is_resident(0, 0))
            self.assertEqual(store.tile_revision(0, 0), revision)
            self.assertTrue(store.has_tile(0, 0))
            self.assertEqual(store.tile(0, 0).pixelColor(8, 9), QColor("purple"))
            self.assertTrue(store.tile_is_resident(0, 0))

    def test_partial_write_does_not_destroy_unreadable_scratch_tile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("orange"))
            store.set_tile(0, 0, tile)
            self.assertGreater(store.evict_tile_to_scratch(0, 0), 0)
            swapped = store._swapped[(0, 0)]
            swapped.write_bytes(b"truncated scratch")
            patch = QImage(64, 64, QImage.Format.Format_ARGB32)
            patch.fill(QColor("blue"))
            self.assertEqual(store.write_image(patch, QRect(1, 1, 2, 2)), set())
            self.assertTrue(swapped.is_file())
            self.assertTrue(store.has_tile(0, 0))

    def test_corrupt_or_missing_scratch_tile_raises_instead_of_becoming_transparent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("orange"))
            store.set_tile(0, 0, tile)
            self.assertGreater(store.evict_tile_to_scratch(0, 0), 0)
            swapped = store._swapped[(0, 0)]
            swapped.write_bytes(b"truncated scratch payload")

            with self.assertRaisesRegex(OSError, "Unreadable scratch tile"):
                store.tile(0, 0)
            self.assertTrue(store.has_tile(0, 0))
            self.assertFalse(store.tile_is_resident(0, 0))
            self.assertEqual(swapped.read_bytes(), b"truncated scratch payload")

            errors = []
            store.request_tile_async(0, 0,
                                     lambda _x, _y, success, error:
                                     errors.append((success, error)))
            self.assertEqual(len(errors), 1)
            self.assertFalse(errors[0][0])
            self.assertTrue(errors[0][1])

            swapped.unlink()
            store._failed_loads.pop((0, 0), None)
            with self.assertRaisesRegex(OSError, "scratch tile is missing"):
                store.tile(0, 0)

    def test_scratch_tile_with_wrong_dimensions_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("purple"))
            store.set_tile(0, 0, tile)
            self.assertGreater(store.evict_tile_to_scratch(0, 0), 0)
            wrong = QImage(32, 32, QImage.Format.Format_ARGB32)
            wrong.fill(QColor("red"))
            self.assertTrue(wrong.save(str(store._swapped[(0, 0)]), "PNG"))

            with self.assertRaisesRegex(OSError, "dimensions do not match"):
                store.tile(0, 0)
            self.assertFalse(store.tile_is_resident(0, 0))
            self.assertTrue(store.has_tile(0, 0))

    def test_sparse_clone_refuses_corrupt_scratch_without_materializing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            source = TileStore(64, 64)
            source.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor("cyan"))
            source.set_tile(0, 0, tile)
            self.assertGreater(source.evict_tile_to_scratch(0, 0), 0)
            source._swapped[(0, 0)].write_bytes(b"broken")
            destination = TileStore(64, 64)

            self.assertFalse(destination.copy_occupied_tiles_from(source))
            self.assertEqual(destination.occupied_keys, set())
            self.assertTrue(source.has_tile(0, 0))
            self.assertFalse(source.tile_is_resident(0, 0))

    def test_native_lru_evicts_cold_tile_and_reloads_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(128, 64)
            store.set_scratch_directory(directory)
            first = QImage(64, 64, QImage.Format.Format_ARGB32)
            first.fill(QColor("red"))
            second = QImage(64, 64, QImage.Format.Format_ARGB32)
            second.fill(QColor("blue"))
            store.set_tile(0, 0, first)
            store.set_tile(1, 0, second)
            store.tile(0, 0)  # make the first tile the most recently used
            store.set_memory_limit(64 * 64 * 4)
            self.assertTrue(store.tile_is_resident(0, 0))
            self.assertFalse(store.tile_is_resident(1, 0))
            self.assertEqual(store.tile(1, 0).pixelColor(12, 12), QColor("blue"))

    def test_failed_scratch_write_keeps_tile_resident(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(QColor("cyan"))
            store.set_tile(0, 0, image)
            with patch.object(store, "_write_scratch_native", return_value=0):
                self.assertEqual(store.evict_tile_to_scratch(0, 0), 0)
            self.assertTrue(store.tile_is_resident(0, 0))
            self.assertEqual(store.swapped_tile_count, 0)
            self.assertEqual(store.tile(0, 0).pixelColor(2, 2), QColor("cyan"))

    def test_atomic_scratch_replace_preserves_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tile.bin"
            path.write_bytes(b"previous-valid-data")
            with patch("DOCUMENTS.tile_store.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    TileStore._atomic_write(path, b"partial-new-data")
            self.assertEqual(path.read_bytes(), b"previous-valid-data")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_scratch_tile_can_be_loaded_asynchronously(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = TileStore(64, 64)
            store.set_scratch_directory(directory)
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(QColor("orange"))
            store.set_tile(0, 0, image)
            store.evict_tile_to_scratch(0, 0)
            loop = QEventLoop()
            result = []
            store.request_tile_async(0, 0,
                                     lambda tx, ty, success, error:
                                     (result.append((tx, ty, success, error)), loop.quit()))
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            self.assertEqual(result, [(0, 0, True, None)])
            self.assertTrue(store.tile_is_resident(0, 0))
            self.assertEqual(store.tile(0, 0).pixelColor(2, 2), QColor("orange"))
        del app

    def test_projection_worker_uses_native_compositor_and_returns_tile(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        source = QImage(8, 8, QImage.Format.Format_ARGB32)
        source.fill(QColor("white"))
        layer = ProjectionLayer(source, True, 1.0, "multiply", {})
        worker = ProjectionWorker(native_library=load_creative_core())
        loop = QEventLoop()
        result = {}

        def receive(generation, tx, ty, image):
            result.update(generation=generation, tx=tx, ty=ty, image=image)
            loop.quit()

        worker.projected.connect(receive)
        generation = worker.request({(2, 3): (8, 8, [layer])})
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.assertEqual(result.get("generation"), generation)
        self.assertEqual((result["tx"], result["ty"]), (2, 3))
        self.assertEqual(result["image"].pixelColor(2, 2), QColor("white"))
        worker.close()
        del app


if __name__ == "__main__":
    unittest.main()
