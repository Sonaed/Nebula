"""Compare sparse tile duplication with a full-canvas compatibility copy."""
from __future__ import annotations

import sys
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage

from DOCUMENTS.tile_store import TileStore


def measure(callback, repetitions: int = 5) -> float:
    samples = []
    for _ in range(repetitions):
        start = perf_counter()
        callback()
        samples.append((perf_counter() - start) * 1000.0)
    return median(samples)


def main() -> None:
    width = height = 4096
    source = TileStore(width, height)
    tile = QImage(64, 64, QImage.Format.Format_ARGB32)
    tile.fill(QColor(200, 40, 80, 255))
    source.set_tile(60, 60, tile)

    def sparse_copy() -> None:
        target = TileStore(width, height)
        assert target.copy_occupied_tiles_from(source)
        assert target.occupied_keys == source.occupied_keys
        target.close()

    def full_image_copy() -> None:
        target = TileStore(width, height)
        image = source.materialize().copy()
        target.write_image(image)
        assert target.occupied_keys == source.occupied_keys
        target.close()

    try:
        print(f"4096x4096, one occupied 64x64 tile, median of 5")
        print(f"sparse tile copy: {measure(sparse_copy):.3f} ms")
        print(f"full image copy:  {measure(full_image_copy):.3f} ms")
    finally:
        source.close()


if __name__ == "__main__":
    main()
