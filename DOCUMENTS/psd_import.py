"""Prioritized, cancellable PSD import scheduling.

The scheduler deliberately owns no Qt objects and never calls the UI thread.
It is the boundary used by the progressive importer: metadata/overview work
can be submitted first, followed by visible, nearby, and background regions.
"""
from __future__ import annotations

import time
from io import BytesIO
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import IntEnum
from threading import Event, Lock
from typing import Callable, Any
from pathlib import Path
from collections import OrderedDict


@dataclass(frozen=True)
class PSDImportBudget:
    """Conservative import working-set estimate shown before decoding begins."""
    width: int
    height: int
    channels: int
    bits_per_channel: int
    estimated_bytes: int
    source_bytes: int

    @property
    def per_full_layer_bytes(self) -> int:
        """Upper bound for one fully populated editable RGBA layer."""
        return self.width * self.height * 4

    @property
    def estimated_mib(self) -> float:
        return self.estimated_bytes / (1024 * 1024)

    @property
    def per_full_layer_mib(self) -> float:
        return self.per_full_layer_bytes / (1024 * 1024)


def estimate_import_budget(path: str | Path) -> PSDImportBudget:
    """Read only the PSD header and estimate the bounded progressive working set.

    This is intentionally not a promise about the final editable document. It
    describes the peak *import* buffers: an RGBA viewport/composite surface,
    two decoded working regions, and a small channel-row reserve.  Full layers
    remain sparse and are released after their tiles transfer.
    """
    source = Path(path)
    with source.open("rb") as stream:
        header = stream.read(26)
    if len(header) != 26 or header[:4] != b"8BPS":
        raise ValueError("Fichier PSD/PSB invalide : en-tête 8BPS absent")
    channels = int.from_bytes(header[12:14], "big")
    height = int.from_bytes(header[14:18], "big")
    width = int.from_bytes(header[18:22], "big")
    bits = int.from_bytes(header[22:24], "big")
    if width < 1 or height < 1 or channels < 1 or bits not in (1, 8, 16, 32):
        raise ValueError("Fichier PSD/PSB invalide : dimensions ou profondeur")
    rgba = width * height * 4
    # Never advertise the old full-layer-stack worst case as temporary RAM:
    # progressive decoding retains only two regions plus the overview.
    decoded_region = min(rgba, 128 * 1024 * 1024)
    reserve = min(max(channels, 4) * width * max(1, bits // 8) * 128, 32 * 1024 * 1024)
    estimate = rgba + decoded_region * 2 + reserve
    return PSDImportBudget(width, height, channels, bits, estimate, source.stat().st_size)


class ImportPriority(IntEnum):
    VISIBLE = 0
    NEAR_VIEWPORT = 1
    OVERVIEW = 2
    REST = 3
    HIDDEN = 4


@dataclass(order=True)
class ImportTask:
    priority: ImportPriority
    sequence: int
    name: str = field(compare=False)
    function: Callable[[Event], Any] = field(compare=False)


@dataclass
class ImportMetrics:
    submitted: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0
    first_result_ms: float | None = None
    peak_inflight: int = 0


class PSDRegionCache:
    """Bounded LRU of immutable decoded PSD regions.

    Keys explicitly identify the source, layer/composite owner, channel set,
    and tile rectangle.  It avoids re-decoding tiles while a user pans back
    and forth without holding a second full-document image in memory.
    """

    def __init__(self, max_bytes: int = 128 * 1024 * 1024) -> None:
        self.max_bytes = max(1024 * 1024, int(max_bytes))
        self._items: OrderedDict[tuple, bytes] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            value = self._items.pop(key, None)
            if value is not None:
                self._items[key] = value
            return value

    def put(self, key, value: bytes) -> None:
        if len(value) > self.max_bytes:
            return
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._bytes -= len(previous)
            self._items[key] = value
            self._bytes += len(value)
            while self._bytes > self.max_bytes and self._items:
                _, evicted = self._items.popitem(last=False)
                self._bytes -= len(evicted)

    @property
    def bytes(self) -> int:
        with self._lock:
            return self._bytes


_REGION_CACHE = PSDRegionCache()


class PSDImportScheduler:
    """Small worker pool with explicit priority and cooperative cancellation."""

    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(workers)), thread_name_prefix="psd-import")
        self._cancel = Event()
        self._lock = Lock()
        self._sequence = 0
        self._started = time.perf_counter()
        self._inflight = 0
        self.metrics = ImportMetrics()
        self._futures: list[Future] = []

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def submit(self, name: str, priority: ImportPriority,
               function: Callable[[Event], Any]) -> Future:
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            self.metrics.submitted += 1
        def run():
            if self._cancel.is_set():
                with self._lock: self.metrics.cancelled += 1
                return None
            with self._lock:
                self._inflight += 1
                self.metrics.peak_inflight = max(self.metrics.peak_inflight, self._inflight)
            try:
                result = function(self._cancel)
                with self._lock:
                    self.metrics.completed += 1
                    if self.metrics.first_result_ms is None:
                        self.metrics.first_result_ms = (time.perf_counter() - self._started) * 1000
                return result
            except Exception:
                with self._lock: self.metrics.failed += 1
                raise
            finally:
                with self._lock: self._inflight -= 1
        # ThreadPoolExecutor is FIFO; priority is enforced by callers using
        # submit_ordered(), while direct submit remains useful for one task.
        future = self._executor.submit(run)
        self._futures.append(future)
        return future

    def submit_ordered(self, tasks: list[ImportTask]) -> list[Future]:
        return [self.submit(task.name, task.priority, task.function)
                for task in sorted(tasks)]

    def cancel(self) -> None:
        self._cancel.set()
        for future in self._futures:
            future.cancel()
        with self._lock:
            self.metrics.cancelled += sum(not future.done() for future in self._futures)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)


__all__ = ["ImportPriority", "ImportTask", "ImportMetrics", "PSDImportScheduler", "PSDRegionCache",
           "PSDImportBudget", "estimate_import_budget"]

def _read_preview_composite(path):
    from DOCUMENTS.psd_reader import read_psd, PSDError
    try:
        with read_psd(path, composite=True, lazy_layers=True) as psd:
            if psd.composite is None:
                raise PSDError("PSD has no embedded composite")
            return psd.composite
    except PSDError:
        from psd_tools import PSDImage
        image = PSDImage.open(str(path)).composite(apply_icc=False)
        if image is None:
            raise ValueError("PSD has no embedded composite")
        return image


def build_overview(path: str, max_size: int = 1024) -> tuple[bytes, tuple[int, int]]:
    """Read the merged image without decoding the editable layer stack."""
    image = _read_preview_composite(path)
    if hasattr(image, "thumbnail"):
        original = image.size
        image.thumbnail((max_size, max_size))
        return _pil_to_png(image.convert("RGBA")), original
    return _array_to_png(image, max_size), (image.shape[1], image.shape[0])

__all__ += ["build_overview"]


def visible_tile_plan(width: int, height: int, viewport: tuple[int, int, int, int],
                      tile_size: int = 128) -> list[tuple[ImportPriority, tuple[int, int, int, int]]]:
    """Return visible tiles first, followed by a one-tile viewport halo."""
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    vx, vy, vw, vh = viewport
    vx2, vy2 = vx + max(0, vw), vy + max(0, vh)
    cols = range(max(0, vx // tile_size), min((width + tile_size - 1) // tile_size, (vx2 + tile_size - 1) // tile_size))
    rows = range(max(0, vy // tile_size), min((height + tile_size - 1) // tile_size, (vy2 + tile_size - 1) // tile_size))
    visible = {(x, y) for y in rows for x in cols}
    halo = set()
    for x, y in visible:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                tx, ty = x + dx, y + dy
                if 0 <= tx < (width + tile_size - 1) // tile_size and 0 <= ty < (height + tile_size - 1) // tile_size:
                    halo.add((tx, ty))
    halo -= visible
    def rect(tile):
        x, y = tile
        return (x * tile_size, y * tile_size, min(tile_size, width - x * tile_size), min(tile_size, height - y * tile_size))
    return [(ImportPriority.VISIBLE, rect(t)) for t in sorted(visible, key=lambda p: (p[1], p[0]))] + [(ImportPriority.NEAR_VIEWPORT, rect(t)) for t in sorted(halo, key=lambda p: (p[1], p[0]))]


def decode_composite_tiles(path: str | Path, viewport: tuple[int, int, int, int],
                           tile_size: int = 128, exclude=None) -> tuple[tuple[int, int], dict[tuple[int, int], bytes]]:
    """Decode only composite regions intersecting the viewport and its halo.

    Returned tile values are PNG bytes so they can cross the worker/UI boundary
    without retaining psd-tools or PIL objects.
    """
    from DOCUMENTS.psd_reader import PSDError, read_composite_regions
    # The native path reads only the requested raw/PackBits channel rows.  A
    # third-party fallback remains for exotic PSDs the native reader rejects.
    try:
        with open(path, "rb") as probe:
            if probe.read(4) != b"8BPS":
                raise PSDError("signature PSD absente")
        # Obtain dimensions from the metadata pass inside read_composite_regions.
        # A provisional plan is rebuilt once from the header-sized viewport.
        from DOCUMENTS.psd_reader import read_psd
        with read_psd(path, composite=False, lazy_layers=True) as metadata:
            size = (metadata.width, metadata.height)
        excluded = set(exclude or ())
        plan = [rect for _priority, rect in visible_tile_plan(*size, viewport, tile_size)
                if (rect[0], rect[1]) not in excluded]
        if not plan:
            return size, {}
        source = Path(path)
        identity = (str(source.resolve()), source.stat().st_mtime_ns, source.stat().st_size,
                    "composite", "rgba")
        result, missing = {}, []
        for rect in plan:
            key = identity + tuple(rect)
            cached = _REGION_CACHE.get(key)
            if cached is None:
                missing.append(rect)
            else:
                result[(rect[0], rect[1])] = cached
        if missing:
            _size, regions = read_composite_regions(path, missing)
            for x, y, width, height in missing:
                payload = _array_to_png(regions[(x, y, width, height)])
                _REGION_CACHE.put(identity + (x, y, width, height), payload)
                result[(x, y)] = payload
        return size, result
    except (PSDError, OSError, ValueError):
        image = _read_preview_composite(path)
        if hasattr(image, "crop"):
            size = image.size
            crop = lambda x, y, w, h: image.crop((x, y, x + w, y + h)).convert("RGBA")
        else:
            size = (image.shape[1], image.shape[0])
            crop = lambda x, y, w, h: image[y:y + h, x:x + w]
        result = {}
        excluded = set(exclude or ())
        for _priority, (x, y, width, height) in visible_tile_plan(*size, viewport, tile_size):
            if (x, y) in excluded:
                continue
            cropped = crop(x, y, width, height)
            result[(x, y)] = _array_to_png(cropped, max_size=max(width, height)) if not hasattr(cropped, "save") else _pil_to_png(cropped)
        return size, result


def _pil_to_png(image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _array_to_png(array, max_size: int | None = None) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    import numpy as np
    pixels = np.ascontiguousarray(array, dtype=np.uint8)
    image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format.Format_RGBA8888)
    if max_size and (image.width() > max_size or image.height() > max_size):
        image = image.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


__all__ += ["visible_tile_plan", "decode_composite_tiles"]
