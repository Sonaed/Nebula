"""Sparse CPU backing store for fixed-size document tiles."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from CORE.tile_compression import decode_record, encode_record
from CORE.native_bridge import (clone_image_native, create_native_tile_store,
                                fill_image_native, write_image_png)

from PySide6.QtCore import QObject, QRect, Signal, Slot
from PySide6.QtGui import QColor, QImage

TILE_SIZE = 64
_scratch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scratch-read")


class _ScratchReadDispatcher(QObject):
    loaded = Signal(object)

    def __init__(self):
        super().__init__()
        self.loaded.connect(self._deliver)

    @staticmethod
    def _load(store, key, path, revision):
        if store._native_handle and store._load_scratch_native(key, path, revision):
            return None
        image = TileStore._read_scratch(
            str(path), store.image_format, store.tile_rect(*key).size())
        return image

    def request(self, store, key, path, revision, callback):
        future = _scratch_executor.submit(self._load, store, key, str(path), revision)

        def done(future):
            try:
                image, error = future.result(), None
            except Exception as exc:  # forwarded to the UI thread
                image, error = None, str(exc)
            self.loaded.emit((store, key, path, revision, image, error))

        future.add_done_callback(done)

    @Slot(object)
    def _deliver(self, result):
        store, key, path, revision, image, error = result
        success = store._finish_async_load(key, path, revision, image, error)
        for callback in store._take_load_callbacks(key):
            if callback is not None:
                callback(key[0], key[1], success, error)


_scratch_dispatcher: _ScratchReadDispatcher | None = None
_scratch_dispatcher_lock = Lock()
def _get_scratch_dispatcher():
    global _scratch_dispatcher
    with _scratch_dispatcher_lock:
        if _scratch_dispatcher is None:
            _scratch_dispatcher = _ScratchReadDispatcher()
        return _scratch_dispatcher


@dataclass(frozen=True)
class TileSnapshot:
    x: int
    y: int
    revision: int
    image: QImage


class TileStore:
    """Sparse tile map; absent tiles are transparent and consume no pixel RAM."""

    def __init__(self, width: int, height: int, tile_size: int = TILE_SIZE,
                 image_format=QImage.Format.Format_ARGB32):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.tile_size = max(1, int(tile_size))
        self.image_format = image_format
        self._native_handle = create_native_tile_store(self.width, self.height, self.tile_size)
        if self._native_handle is None:
            raise RuntimeError("CreativeCore est requis pour le stockage des tuiles")
        # CreativeCore owns sparse pixels, revisions and resident-tile metadata.
        # Python keeps only Qt adapters and scratch-file bookkeeping.
        self._scratch_directory: Path | None = None
        self._swapped: dict[tuple[int, int], Path] = {}
        self.max_resident_bytes: int | None = None
        self._pending_loads: set[tuple[int, int]] = set()
        self._pending_callbacks: dict[tuple[int, int], list] = {}
        self._failed_loads: dict[tuple[int, int], str] = {}

    def close(self) -> None:
        if self._native_handle:
            self._native_handle.close()
            self._native_handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def resident_keys(self) -> set[tuple[int, int]]:
        return self._native_handle.keys() if self._native_handle else set()

    def remove_resident_tile(self, tx: int, ty: int) -> bool:
        return bool(self._native_handle and self._native_handle.remove(tx, ty))

    def _native_info(self, tx: int, ty: int):
        if not self._native_handle:
            return None
        return self._native_handle.info(tx, ty)

    def _load_scratch_native(self, key, path, revision) -> bool:
        if not self._native_handle:
            return False
        try:
            return self._native_handle.load_png(key[0], key[1], path, revision)
        except (OSError, ValueError):
            return False

    def _write_scratch_native(self, tx: int, ty: int, path: Path) -> int:
        if not self._native_handle:
            return 0
        return self._native_handle.write_png(tx, ty, path)

    @property
    def columns(self):
        return (self.width + self.tile_size - 1) // self.tile_size

    @property
    def rows(self):
        return (self.height + self.tile_size - 1) // self.tile_size

    def tile_rect(self, tx: int, ty: int) -> QRect:
        x, y = int(tx) * self.tile_size, int(ty) * self.tile_size
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return QRect()
        return QRect(x, y, min(self.tile_size, self.width-x), min(self.tile_size, self.height-y))

    def tile_key(self, x: int, y: int) -> tuple[int, int]:
        return int(x) // self.tile_size, int(y) // self.tile_size

    def keys_for_rect(self, rect: QRect | None = None):
        bounds = QRect(0, 0, self.width, self.height)
        rect = bounds if rect is None else QRect(rect).intersected(bounds)
        if rect.isEmpty():
            return set()
        return {(tx, ty)
                for ty in range(rect.top() // self.tile_size, rect.bottom() // self.tile_size + 1)
                for tx in range(rect.left() // self.tile_size, rect.right() // self.tile_size + 1)}

    def has_tile(self, tx: int, ty: int) -> bool:
        key = (int(tx), int(ty))
        info = self._native_info(*key)
        if info is not None:
            return info[0] or key in self._swapped
        return key in self._swapped

    @property
    def occupied_keys(self) -> set[tuple[int, int]]:
        """Tile coordinates with resident or scratch-backed pixel data."""
        return self.resident_keys() | self._swapped.keys()

    def tile_last_access(self, tx: int, ty: int) -> int:
        key = (int(tx), int(ty))
        info = self._native_info(*key)
        if info is not None:
            return info[2] or info[1]
        return 0

    def _touch(self, key: tuple[int, int]) -> None:
        # CreativeCore updates recency when a tile is read or written.
        return

    def set_memory_limit(self, bytes_limit: int | None) -> None:
        self.max_resident_bytes = None if bytes_limit is None else max(0, int(bytes_limit))
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        if self.max_resident_bytes is None or self._scratch_directory is None:
            return
        while self.allocated_bytes() > self.max_resident_bytes and self.resident_keys():
            resident = self.resident_keys()
            key = min(resident, key=lambda k: self.tile_last_access(*k))
            if self.evict_tile_to_scratch(*key) <= 0:
                break

    def _clear_swapped_files(self) -> None:
        for path in self._swapped.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._swapped.clear()
        self._failed_loads.clear()

    def tile_revision(self, tx: int, ty: int) -> int:
        info = self._native_info(tx, ty)
        if info is not None:
            return info[1]
        return 0

    def tile(self, tx: int, ty: int) -> QImage:
        rect = self.tile_rect(tx, ty)
        if rect.isEmpty():
            return QImage()
        if self._native_handle:
            swapped = self._swapped.get((int(tx), int(ty)))
            if swapped is not None:
                key = (int(tx), int(ty))
                try:
                    if not swapped.is_file():
                        raise FileNotFoundError(f"scratch tile is missing: {swapped}")
                    if self._load_scratch_native(key, swapped, self.tile_revision(*key)):
                        result = QImage(rect.size(), self.image_format)
                        if not fill_image_native(result, QColor(0, 0, 0, 0)):
                            raise RuntimeError("CreativeCore could not clear a tile adapter")
                        if not self._native_handle.copy(key[0], key[1], result):
                            raise OSError("CreativeCore could not copy a reloaded scratch tile")
                        return result
                    image = self._read_scratch(swapped, self.image_format, rect.size())
                    if image.isNull() or image.size() != rect.size():
                        raise ValueError("scratch tile dimensions do not match its document slot")
                    if not self.set_tile(tx, ty, image):
                        raise OSError("CreativeCore could not restore a scratch tile")
                    return self.tile(tx, ty)
                except (OSError, ValueError, RuntimeError) as error:
                    self._failed_loads[key] = str(error)
                    raise OSError(f"Unreadable scratch tile {key}: {error}") from error
            result = QImage(rect.size(), self.image_format)
            if not fill_image_native(result, QColor(0, 0, 0, 0)):
                raise RuntimeError("CreativeCore could not clear a tile adapter")
            self._native_handle.copy(tx, ty, result)
            return result
        result = QImage(rect.size(), self.image_format)
        if not fill_image_native(result, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore could not clear a tile adapter")
        return result

    def tile_is_resident(self, tx: int, ty: int) -> bool:
        info = self._native_info(tx, ty)
        return bool(info is not None and info[0])

    def request_tile_async(self, tx: int, ty: int, callback=None) -> bool:
        key = (int(tx), int(ty))
        path = self._swapped.get(key)
        if path is None:
            if callback is not None:
                callback(key[0], key[1], self.tile_is_resident(*key), None)
            return False
        failure = self._failed_loads.get(key)
        if failure is not None:
            if callback is not None:
                callback(key[0], key[1], False, failure)
            return False
        if self.tile_is_resident(*key):
            if callback is not None:
                callback(key[0], key[1], True, None)
            return False
        if key in self._pending_loads:
            self._pending_callbacks.setdefault(key, []).append(callback)
            return True
        self._pending_loads.add(key)
        self._pending_callbacks[key] = [callback]
        _get_scratch_dispatcher().request(self, key, path, self.tile_revision(*key), None)
        return True

    def _finish_async_load(self, key, path, revision, image, error=None) -> bool:
        self._pending_loads.discard(key)
        if (self._swapped.get(key) != path or self.tile_revision(*key) != revision):
            if error and self._swapped.get(key) == path:
                self._failed_loads[key] = error
            return False
        if image is None and self._native_handle:
            success = self.tile_is_resident(*key)
            if error and not success:
                self._failed_loads[key] = error
            if success:
                self._failed_loads.pop(key, None)
            return success
        if image is None:
            return False
        rect = self.tile_rect(*key)
        if image.size() != rect.size():
            return False
        if not self._native_handle or not self._native_handle.set(key[0], key[1], image):
            return False
        self._failed_loads.pop(key, None)
        return True

    @staticmethod
    def _read_scratch(path, image_format, expected_size=None):
        path = Path(path)
        with path.open("rb") as stream:
            raw = stream.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError("scratch tile exceeds the decode budget")
        if raw[:4] == b'CSLZ':
            decoded = decode_record(raw, expected_size)
            if decoded is None:
                raise RuntimeError("CreativeCore CSLZ support is unavailable")
            pixels, w, h, stride, _compressed = decoded
            source = QImage(pixels, w, h, stride, QImage.Format.Format_RGBA8888)
            rgba = clone_image_native(source)
            if rgba is None or rgba.isNull():
                raise ValueError("invalid CSLZ pixel buffer")
            return rgba.convertToFormat(image_format)
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isEmpty() or size.width() > 4096 or size.height() > 4096:
            raise ValueError("scratch image dimensions exceed the decode limit")
        if size.width() * size.height() > 16 * 1024 * 1024:
            raise ValueError("scratch image exceeds the pixel decode budget")
        if expected_size is not None and size != expected_size:
            raise ValueError("scratch tile dimensions do not match its document slot")
        image = reader.read()
        if image.isNull():
            raise ValueError(f"scratch image could not be decoded: {reader.errorString()}")
        return image.convertToFormat(image_format)

    def _take_load_callbacks(self, key):
        return self._pending_callbacks.pop(key, [])

    @staticmethod
    def _atomic_write(path: str | Path, payload: bytes) -> None:
        """Publish scratch data atomically so an interrupted write is never loaded."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def set_tile(self, tx: int, ty: int, image: QImage) -> bool:
        rect = self.tile_rect(tx, ty)
        if rect.isEmpty() or image.isNull():
            return False
        key = (int(tx), int(ty))
        self._failed_loads.pop(key, None)
        if not self._native_handle or not self._native_handle.set(key[0], key[1], image):
            return False
        previous_swap = self._swapped.pop(key, None)
        if previous_swap is not None:
            try:
                previous_swap.unlink(missing_ok=True)
            except OSError:
                pass
        self._touch(key)
        self._evict_if_needed()
        return True

    def set_tiles_batch(self, writes) -> bool:
        """Publish several history tiles with one native bridge crossing."""
        prepared = []
        for tx, ty, image in writes:
            rect = self.tile_rect(tx, ty)
            if rect.isEmpty() or image.isNull():
                return False
            prepared.append((int(tx), int(ty), image))
        if not self._native_handle or not self._native_handle.set_many(prepared):
            return False
        for tx, ty, _tile in prepared:
            key = (tx, ty)
            self._failed_loads.pop(key, None)
            previous_swap = self._swapped.pop(key, None)
            if previous_swap is not None:
                try:
                    previous_swap.unlink(missing_ok=True)
                except OSError:
                    pass
            self._touch(key)
        self._evict_if_needed()
        return True

    def write_image(self, image: QImage, rect: QRect | None = None) -> set[tuple[int, int]]:
        if image.isNull():
            return set()
        if image.width() != self.width or image.height() != self.height:
            self.width, self.height = image.width(), image.height()
            self._native_handle.resize(self.width, self.height)
            self._clear_swapped_files()
        affected = self.keys_for_rect(rect)
        if rect is not None:
            for tx, ty in affected:
                if (tx, ty) in self._swapped and not self.tile_is_resident(tx, ty):
                    try:
                        self.tile(tx, ty)
                    except OSError:
                        return set()
                    if not self.tile_is_resident(tx, ty):
                        return set()
        area = QRect(0, 0, self.width, self.height) if rect is None else QRect(rect)
        updated = self._native_handle.write_image(image, area, len(affected))
        if updated is None:
            return set()
        for key in updated:
            previous_swap = self._swapped.pop(key, None)
            if previous_swap is not None:
                try:
                    previous_swap.unlink(missing_ok=True)
                except OSError:
                    pass
            self._failed_loads.pop(key, None)
        return updated

    def materialize(self) -> QImage:
        image = QImage(self.width, self.height, self.image_format)
        if not fill_image_native(image, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore could not clear the materialized image")
        for tx, ty in list(self._swapped):
            if not self.tile_is_resident(tx, ty):
                self.tile(tx, ty)
        return image if self._native_handle.materialize(image) else QImage()

    def snapshot(self, keys=None) -> tuple[TileSnapshot, ...]:
        selected = self.occupied_keys if keys is None else keys
        return tuple(TileSnapshot(tx, ty, self.tile_revision(tx, ty), self.tile(tx, ty))
                     for tx, ty in selected)

    def copy_occupied_tiles_from(self, source: "TileStore") -> bool:
        """Copy sparse pixel data without materializing either full canvas.

        Scratch-backed tiles are loaded through the same validated path as a
        normal read. A failed tile read aborts the copy instead of silently
        producing an incomplete duplicate.
        """
        if (source.width != self.width or source.height != self.height
                or source.tile_size != self.tile_size):
            return False
        swapped = [key for key in source._swapped
                   if not source.tile_is_resident(*key)]
        try:
            for key in swapped:
                source.tile(*key)
                if not source.tile_is_resident(*key):
                    return False
            return bool(self._native_handle.copy_resident_from(source._native_handle))
        except OSError:
            return False
        finally:
            for key in swapped:
                if source.tile_is_resident(*key):
                    source.evict_tile_to_scratch(*key)

    def allocated_bytes(self) -> int:
        return self._native_handle.allocated_bytes()

    def set_scratch_directory(self, directory: str | Path | None) -> None:
        self._scratch_directory = None if directory is None else Path(directory)
        if self._scratch_directory is not None:
            self._scratch_directory.mkdir(parents=True, exist_ok=True)

    def evict_tile_to_scratch(self, tx: int, ty: int) -> int:
        key = (int(tx), int(ty))
        if self._scratch_directory is None or not self.tile_is_resident(*key):
            return 0
        self._scratch_directory.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha1(f"{id(self)}:{tx}:{ty}".encode()).hexdigest()
        path = self._scratch_directory / f"{token}.png"
        freed = self._write_scratch_native(key[0], key[1], path)
        if freed <= 0:
            return 0
        self.remove_resident_tile(*key)
        self._swapped[key] = path
        return freed

    def tile_swap_payload(self, tx: int, ty: int):
        key = (int(tx), int(ty))
        image = self.tile(*key) if self.tile_is_resident(*key) else None
        if image is None or self._scratch_directory is None:
            return None
        self._scratch_directory.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha1(f"{id(self)}:{tx}:{ty}".encode()).hexdigest()
        clone = clone_image_native(image)
        if clone is None:
            raise RuntimeError("CreativeCore is required to snapshot scratch tiles")
        return (clone, self._scratch_directory / f"{token}.png", self.tile_revision(tx, ty))

    @staticmethod
    def write_tile_payload(payload) -> int:
        image, path, _revision = payload
        written = write_image_png(path, image)
        if written > 0:
            return written
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(rgba.constBits())
        encoded = encode_record(raw, rgba.width(), rgba.height(), rgba.bytesPerLine())
        if encoded is None:
            raise RuntimeError("CreativeCore CSLZ support is unavailable")
        TileStore._atomic_write(path, encoded)
        return int(image.sizeInBytes())

    def commit_tile_eviction(self, tx: int, ty: int, path: str | Path, revision: int) -> int:
        key = (int(tx), int(ty))
        if not self.tile_is_resident(*key) or self.tile_revision(*key) != int(revision):
            return 0
        rect = self.tile_rect(*key)
        freed = rect.width() * rect.height() * 4
        self.remove_resident_tile(*key)
        self._swapped[key] = Path(path)
        return freed

    @property
    def tile_count(self) -> int:
        return self._native_handle.count()

    @property
    def swapped_tile_count(self) -> int:
        return len(self._swapped)

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = max(1, int(width)), max(1, int(height))
        self._native_handle.resize(self.width, self.height)
        self._clear_swapped_files()

    def clear_resident(self) -> None:
        self._native_handle.clear()
