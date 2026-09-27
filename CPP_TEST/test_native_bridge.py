from __future__ import annotations

import ctypes
import unittest
from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import (NebulaReaderHandle, NebulaWriterHandle,
                                restore_image_alpha_rect)


class NativeBridgeTests(unittest.TestCase):
    def test_nebula_reader_reuses_its_native_tile_buffer(self) -> None:
        addresses = []
        next_id = 0

        def next_tile(_handle, chunk_id, pixels, _capacity, raw_size):
            nonlocal next_id
            addresses.append(ctypes.addressof(pixels))
            chunk_id._obj.value = next_id + 1
            raw_size._obj.value = 2
            pixels[0], pixels[1] = next_id, next_id + 1
            next_id += 1
            return 1

        library = SimpleNamespace(cs_nebula_reader_next_tile=next_tile)
        reader = NebulaReaderHandle(library, object())
        self.assertEqual(reader.next_tile(32), (1, b"\x00\x01"))
        self.assertEqual(reader.next_tile(32), (2, b"\x01\x02"))
        self.assertEqual(addresses[0], addresses[1])

    def test_nebula_writer_reuses_buffer_after_synchronous_tile_copy(self) -> None:
        addresses = []
        contents = []

        def add_tile(_handle, _chunk_id, pixels, size):
            addresses.append(ctypes.cast(pixels, ctypes.c_void_p).value)
            contents.append(ctypes.string_at(pixels, size))
            return 1

        writer = NebulaWriterHandle(
            SimpleNamespace(cs_nebula_writer_add_tile=add_tile), object()
        )
        self.assertTrue(writer.add_tile(1, b"first-payload"))
        self.assertTrue(writer.add_tile(2, b"next"))
        self.assertEqual(contents, [b"first-payload", b"next"])
        self.assertEqual(addresses[0], addresses[1])

    def test_alpha_restore_uses_native_bridge_and_respects_rectangle(self) -> None:
        destination = QImage(4, 3, QImage.Format.Format_RGBA8888)
        snapshot = QImage(4, 3, QImage.Format.Format_RGBA8888)
        destination.fill(QColor(220, 40, 80, 20))
        snapshot.fill(QColor(12, 180, 40, 200))

        self.assertTrue(restore_image_alpha_rect(destination, snapshot, 1, 1, 2, 1))
        self.assertEqual(destination.pixelColor(1, 1), QColor(220, 40, 80, 200))
        self.assertEqual(destination.pixelColor(2, 1), QColor(220, 40, 80, 200))
        self.assertEqual(destination.pixelColor(0, 1), QColor(220, 40, 80, 20))
        self.assertEqual(destination.pixelColor(1, 0), QColor(220, 40, 80, 20))


if __name__ == "__main__":
    unittest.main()
