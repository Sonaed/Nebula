"""Measure sparse merge-down against its full-canvas compatibility workflow.

Run from the repository root with:
    QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_sparse_merge_down.py
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

from CORE.native_bridge import composite_layer_in_place
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager


def make_document(size: int):
    document = Document(size, size)
    lower = document.layers[0]
    upper = document.add_layer("Upper")
    for layer, color in ((lower, QColor(200, 55, 70, 220)),
                         (upper, QColor(45, 120, 235, 190))):
        layer.discard_image_cache()
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(color)
        layer.tile_store.set_tile(0, 0, tile)
    return document


def measure(size: int = 2048, repeats: int = 5):
    sparse, full = [], []
    for _ in range(repeats):
        document = make_document(size)
        started = time.perf_counter()
        if not LayerManager(document).merge_down(1):
            raise RuntimeError("Sparse merge-down failed")
        sparse.append((time.perf_counter() - started) * 1000)

        document = make_document(size)
        lower, upper = document.layers
        started = time.perf_counter()
        target, source = lower.tile_store.materialize(), upper.tile_store.materialize()
        if not composite_layer_in_place(target, source, upper.opacity, upper.blend_mode):
            raise RuntimeError("Full-canvas compatibility compositor failed")
        lower.image = target
        full.append((time.perf_counter() - started) * 1000)
    sparse_ms, full_ms = statistics.median(sparse), statistics.median(full)
    return sparse_ms, full_ms


def main() -> None:
    QApplication.instance() or QApplication([])
    sparse, full = measure()
    print(f"2048² sparse canvas, two 64² occupied tiles: "
          f"tile merge={sparse:.3f} ms, full-canvas={full:.3f} ms, "
          f"speedup={full / max(sparse, 1e-9):.2f}x")


if __name__ == "__main__":
    main()
