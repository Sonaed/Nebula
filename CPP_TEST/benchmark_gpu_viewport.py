"""CPU-side GPU preparation benchmark using real native tile stores.

No GL context is needed: this measures occlusion and tile revision bookkeeping,
not GPU draw throughput or end-to-end tablet latency. Run before/after a change
with the same arguments; older renderers fall back to their full-document scan.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage
from CANVAS.gpu_renderer import CanvasGPURenderer
from DOCUMENTS.tile_store import TileStore


def benchmark(size: int, layer_count: int, repeats: int) -> dict:
    columns = (size + 63) // 64
    visible = frozenset((x, y) for y in range(min(12, columns))
                        for x in range(min(16, columns)))
    image = QImage(64, 64, QImage.Format.Format_RGBA8888)
    image.fill(QColor(90, 140, 200, 255))
    counters = {"revision_reads": 0, "pixel_tile_reads": 0}
    layers = []
    for index in range(layer_count):
        store = TileStore(size, size)
        for y in range(columns):
            for x in range(columns):
                store.set_tile(x, y, image)
        original_revisions, original_tile = store.resident_revisions, store.tile

        def revisions(reader=original_revisions):
            counters["revision_reads"] += 1
            return reader()

        def tile(x, y, reader=original_tile):
            counters["pixel_tile_reads"] += 1
            return reader(x, y)

        store.resident_revisions, store.tile = revisions, tile
        layers.append(SimpleNamespace(id=str(index), tile_store=store, visible=True,
                                      opacity=1.0, blend_mode="normal",
                                      blend_parameters={}, clipping=False))
    bounded = "visible_tiles" in inspect.signature(CanvasGPURenderer.compute_occlusion).parameters
    renderer = CanvasGPURenderer()

    def frame(keys=visible):
        renderer.begin_frame()
        try:
            kwargs = {"visible_tiles": keys} if bounded else {}
            result = renderer.compute_occlusion(layers, size, size, **kwargs)
            assert set(keys).issubset(result["0"])
        finally:
            renderer.end_frame()

    scenarios = {}
    for scenario in ("cold", "idle", "single_tile_edit", "pan"):
        counters.update(dict.fromkeys(counters, 0))
        durations = []
        count = min(5, repeats) if scenario == "cold" else repeats
        for sample in range(count):
            if scenario == "cold":
                renderer = CanvasGPURenderer()
            elif scenario == "single_tile_edit":
                layers[-1].tile_store.set_tile(0, 0, image)
            keys = visible
            if scenario == "pan":
                shift = (sample % max(1, columns - 16))
                keys = frozenset((x + shift, y) for x, y in visible)
            started = time.perf_counter_ns()
            frame(keys)
            durations.append((time.perf_counter_ns() - started) / 1e6)
        scenarios[scenario] = {"median_ms": round(statistics.median(durations), 4),
                               "max_ms": round(max(durations), 4), "frames": count,
                               **counters}
    for layer in layers:
        layer.tile_store.close()
    return {"scope": "CPU GPU preparation with native tiles; excludes GL drawing and input latency",
            "document": [size, size], "layers": layer_count,
            "resident_tiles_per_layer": columns * columns,
            "visible_tiles": len(visible), "viewport_bounded": bounded,
            "scenarios": scenarios}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=4096)
    parser.add_argument("--layers", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(benchmark(args.size, args.layers, args.repeats), indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    print(result)
