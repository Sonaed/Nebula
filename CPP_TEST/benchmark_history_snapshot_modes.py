"""Compare the local edit snapshot against a full layer-structure snapshot."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DOCUMENTS.document import Document
from CANVAS.tile_history import TileHistory


def median_capture_ms(history, document, mode: str, repeats: int = 9) -> float:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        history._capture(document, include_images=False, include_objects=False,
                         mode=mode)
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def main() -> None:
    document = Document(128, 96)
    for index in range(127):
        document.add_layer(f"Layer {index + 1}")
    history = TileHistory()

    for mode in ("dirty", "structure"):
        median_capture_ms(history, document, mode, repeats=2)
    dirty = median_capture_ms(history, document, "dirty")
    structure = median_capture_ms(history, document, "structure")
    print(f"layers={len(document.layers)}")
    print(f"dirty_snapshot_ms={dirty:.4f}")
    print(f"structure_snapshot_ms={structure:.4f}")
    print(f"structure_to_dirty_ratio={structure / max(dirty, 1e-9):.2f}")


if __name__ == "__main__":
    main()
