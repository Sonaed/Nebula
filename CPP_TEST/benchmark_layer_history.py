"""Compare general sparse-tile and structural history for layer duplication."""
from __future__ import annotations

import sys
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from CANVAS.tile_history import TileHistory
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager


def make_document():
    document = Document(1024, 1024)
    tile = QImage(64, 64, QImage.Format.Format_ARGB32)
    tile.fill(QColor(70, 140, 220, 210))
    for index in range(4):
        layer = document.add_layer(f"Sparse {index}")
        for tile_index in range(32):
            tx = (tile_index * 3 + index) % 16
            ty = (tile_index * 5 + index) % 16
            layer.tile_store.set_tile(tx, ty, tile)
    document.active_layer_index = 4
    return document


def measure(structure_only: bool, repetitions: int = 3) -> float:
    samples = []
    for _ in range(repetitions):
        document = make_document()
        history = TileHistory()
        started = perf_counter()
        history.begin(document, structure_only=structure_only)
        duplicate = LayerManager(document).duplicate_layer(document.active_layer_index)
        assert duplicate is not None and history.commit(document)
        samples.append((perf_counter() - started) * 1000.0)
        history.reset()
        for layer in document.layers:
            layer.tile_store.close()
    return median(samples)


def measure_legacy_full_image(repetitions: int = 3) -> float:
    """Reproduce the former full-canvas snapshots and tile-by-tile comparison."""
    samples = []
    tile_size = 64
    for _ in range(repetitions):
        document = make_document()
        started = perf_counter()
        before = {layer.id: QImage(layer.image) for layer in document.layers}
        selection_before = QImage(document.selection.image)
        duplicate = LayerManager(document).duplicate_layer(document.active_layer_index)
        assert duplicate is not None
        after = {layer.id: QImage(layer.image) for layer in document.layers}
        changed = 0
        for layer_id in before.keys() | after.keys():
            old_image = before.get(layer_id, QImage())
            new_image = after.get(layer_id, QImage())
            width, height = max(old_image.width(), new_image.width()), max(
                old_image.height(), new_image.height())
            for y in range(0, height, tile_size):
                for x in range(0, width, tile_size):
                    rect = QRect(x, y, tile_size, tile_size)
                    old_tile = old_image.copy(rect.intersected(old_image.rect())) \
                        if not old_image.isNull() else QImage()
                    new_tile = new_image.copy(rect.intersected(new_image.rect())) \
                        if not new_image.isNull() else QImage()
                    changed += old_tile != new_tile
        selection_after = document.selection.image
        for y in range(0, 1024, tile_size):
            for x in range(0, 1024, tile_size):
                rect = QRect(x, y, tile_size, tile_size)
                changed += selection_before.copy(rect) != selection_after.copy(rect)
        assert changed > 0
        samples.append((perf_counter() - started) * 1000.0)
        for layer in document.layers:
            layer.tile_store.close()
    return median(samples)


def main():
    print("1024x1024, 5 layers/128 occupied tiles, one duplicate, median of 3")
    print(f"sparse structural history: {measure(True):.3f} ms")
    print(f"generic sparse history:    {measure(False):.3f} ms")
    print(f"legacy full-image history: {measure_legacy_full_image():.3f} ms")


if __name__ == "__main__":
    main()
