"""Measure the native TileStore storage and history paths.

Run from the repository root with:
    QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_tile_store.py
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from DOCUMENTS.tile_store import TileStore


def measure(repeats: int = 5) -> float:
    durations = []
    for _ in range(repeats):
        store = TileStore(1024, 1024)
        images = []
        for index in range(256):
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(QColor(index % 255, (index * 3) % 255, 90, 220))
            images.append(image)
        started = time.perf_counter()
        for index, image in enumerate(images):
            store.set_tile(index % 16, index // 16, image)
        for index in range(256):
            store.tile(index % 16, index // 16)
        durations.append(time.perf_counter() - started)
        store.close()
    return statistics.median(durations) * 1000


def measure_document_round_trip(repeats: int = 5) -> float:
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(QColor(37, 116, 209, 220))
    durations = []
    for _ in range(repeats):
        store = TileStore(1024, 1024)
        started = time.perf_counter()
        store.write_image(image)
        store.materialize()
        durations.append(time.perf_counter() - started)
        store.close()
    return statistics.median(durations) * 1000


def measure_history_restore(batch: bool, repeats: int = 7) -> float:
    images = []
    for index in range(256):
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(QColor(index % 255, (index * 3) % 255, 90, 220))
        images.append((index % 16, index // 16, image))
    durations = []
    for _ in range(repeats):
        store = TileStore(1024, 1024)
        started = time.perf_counter()
        if batch:
            store.set_tiles_batch(images)
        else:
            for tx, ty, image in images:
                store.set_tile(tx, ty, image)
        durations.append(time.perf_counter() - started)
        store.close()
    return statistics.median(durations) * 1000


def main() -> None:
    app = QApplication.instance() or QApplication([])
    native_ms = measure()
    native_pipeline = measure_document_round_trip()
    unit_restore = measure_history_restore(False)
    batch_restore = measure_history_restore(True)
    print(f"256 single-tile set+copy pairs: native={native_ms:.3f} ms")
    print(f"1024² write+materialize: native={native_pipeline:.3f} ms")
    print(f"History restore (256 tiles): unit={unit_restore:.3f} ms, "
          f"batch={batch_restore:.3f} ms, "
          f"ratio={unit_restore / max(batch_restore, 1e-9):.2f}x")
    app.quit()


if __name__ == "__main__":
    main()
