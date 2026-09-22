"""Compare per-tile and batched CreativeCore history-payload insertion."""
from __future__ import annotations

from pathlib import Path
from statistics import median
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import create_native_history_payload


def make_pairs(tile_count: int = 256, tile_size: int = 64):
    pairs = []
    for index in range(tile_count):
        before = QImage(tile_size, tile_size, QImage.Format.Format_ARGB32)
        before.fill(QColor(index % 256, (index * 3) % 256, (index * 7) % 256, 220))
        after = before.copy()
        after.setPixelColor(index % tile_size, (index * 5) % tile_size,
                            QColor("magenta"))
        pairs.append((before, after))
    return pairs


def measure_once(pairs, batched: bool) -> float:
    payload = create_native_history_payload()
    assert payload is not None
    try:
        started = perf_counter()
        if batched:
            indices = payload.append_many(pairs)
            assert indices is not None and all(index >= 0 for index in indices)
        else:
            assert all(payload.append(before, after) == 1
                       for before, after in pairs)
        assert payload.count == len(pairs)
        return (perf_counter() - started) * 1000.0
    finally:
        payload.close()


def measure_both(pairs, repetitions: int = 7):
    individual, batched = [], []
    for repetition in range(repetitions):
        order = (False, True) if repetition % 2 == 0 else (True, False)
        for use_batch in order:
            elapsed = measure_once(pairs, use_batch)
            (batched if use_batch else individual).append(elapsed)
    return median(individual), median(batched)


def main() -> None:
    pairs = make_pairs()
    per_tile, batched = measure_both(pairs)
    print(f"256 history tiles, 64x64 RGBA, median of 7: ")
    print(f"per-tile bridge calls: {per_tile:.3f} ms")
    print(f"single native batch:   {batched:.3f} ms")
    print(f"speedup:               {per_tile / batched:.2f}x")


if __name__ == "__main__":
    main()
