"""Compare the legacy Python input smoother with the native CreativeCore API.

This isolates point filtering and the ctypes boundary; it does not measure
stroke rasterization, tablet delivery, or UI presentation latency.
"""
from __future__ import annotations

import ctypes
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF

from CORE.native_bridge import load_creative_core
from TOOLS.brush_smoothing import BrushSmoothing


POINT_COUNT = 5000
REPETITIONS = 9
STRENGTH = 0.72


def make_points() -> list[tuple[float, float]]:
    return [(i * 0.37, 120.0 + ((i * 17) % 13) * 0.11) for i in range(POINT_COUNT)]


def median_ms(function) -> float:
    samples = []
    for _ in range(REPETITIONS):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    return statistics.median(samples)


def main() -> None:
    library = load_creative_core()
    if library is None:
        raise SystemExit("CreativeCore is required for this benchmark")
    handle = library.cs_brush_create()
    if not handle:
        raise SystemExit("Could not create native brush")
    points = make_points()
    xs, ys = ctypes.c_float(), ctypes.c_float()
    library.cs_brush_set_smoothing(handle, STRENGTH)
    native = library.cs_brush_smooth_point

    def run_native():
        library.cs_brush_end_stroke(handle)
        for x, y in points:
            if not native(handle, x, y, ctypes.byref(xs), ctypes.byref(ys)):
                raise RuntimeError("Native smoother rejected an input point")

    smoother = BrushSmoothing(strength=STRENGTH)

    def run_python():
        smoother.begin_stroke()
        for x, y in points:
            smoother.add_point(QPointF(x, y))

    try:
        run_native()
        run_python()
        native_ms = median_ms(run_native)
        python_ms = median_ms(run_python)
        print(f"points={POINT_COUNT} repetitions={REPETITIONS} strength={STRENGTH}")
        print(f"native C++ + ctypes: {native_ms:.3f} ms ({native_ms / POINT_COUNT * 1000:.3f} µs/point)")
        print(f"legacy Python:       {python_ms:.3f} ms ({python_ms / POINT_COUNT * 1000:.3f} µs/point)")
        print(f"speedup:             {python_ms / native_ms:.2f}x")
        print("Note: filtering only; full stroke/UI latency is not included.")
    finally:
        library.cs_brush_destroy(handle)


if __name__ == "__main__":
    main()
