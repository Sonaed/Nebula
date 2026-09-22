"""Measure tile-sparse Merge Visible on a large document.

Run from the repository root with:
    QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_sparse_merge_visible.py
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

from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.tile_store import TILE_SIZE


def make_document(size: int, layer_count: int, tiles_per_layer: int):
    document = Document(size, size)
    colors = (QColor("red"), QColor("blue"), QColor("green"), QColor("yellow"))
    for index in range(layer_count):
        layer = (document.layers[0] if index == 0
                 else document.add_layer(f"Sparse {index}"))
        layer.discard_image_cache()
        layer.tile_store.clear_resident()
        for tile_index in range(tiles_per_layer):
            tx = (index * 11 + tile_index * 17) % max(1, size // TILE_SIZE)
            ty = (index * 7 + tile_index * 13) % max(1, size // TILE_SIZE)
            tile = QImage(TILE_SIZE, TILE_SIZE, QImage.Format.Format_ARGB32)
            tile.fill(colors[index % len(colors)])
            layer.tile_store.set_tile(tx, ty, tile)
    return document


def measure(size: int = 4096, layer_count: int = 4,
            tiles_per_layer: int = 2, repeats: int = 7):
    samples = []
    for _ in range(repeats):
        document = make_document(size, layer_count, tiles_per_layer)
        started = time.perf_counter()
        if not LayerManager(document).merge_visible():
            raise RuntimeError("Merge Visible failed")
        samples.append((time.perf_counter() - started) * 1000.0)
        if len(document.layers[0].tile_store.occupied_keys) > layer_count * tiles_per_layer:
            raise RuntimeError("Sparse merge unexpectedly expanded the tile set")
    return statistics.median(samples)


def main() -> None:
    QApplication.instance() or QApplication([])
    elapsed = measure()
    print("4096² document, 4 layers × 2 occupied 64² tiles: "
          f"Merge Visible median of 7 runs = {elapsed:.3f} ms")


if __name__ == "__main__":
    main()
