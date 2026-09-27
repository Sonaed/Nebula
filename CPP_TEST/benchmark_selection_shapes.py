"""Measure native selection-mask rasterization.

The historical Qt/Python rasterizer was deliberately removed from production so
that selections use the same CreativeCore code path as the application.  This
benchmark therefore measures that exact path instead of resurrecting a fake
fallback merely to produce a comparison number.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QSize
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from TOOLS.selection_tools import SelectionTools


def geometry(shape: str, size: int, vertices: int) -> list[QPointF]:
    margin = max(8.0, size * 0.08)
    left = top = margin
    right = bottom = size - margin
    if shape == "lasso":
        center = size / 2.0
        radius = size * 0.42
        return [QPointF(center + radius * math.cos(2 * math.pi * i / vertices),
                        center + radius * math.sin(2 * math.pi * i / vertices))
                for i in range(vertices)]
    return [QPointF(left, top), QPointF(right, bottom)]


def measure_native(shape: str, size: int, points: list[QPointF],
                   repeats: int) -> float:
    samples = []
    for run in range(repeats + 2):
        started = time.perf_counter()
        result = SelectionTools.shape_mask(shape, QSize(size, size), points)
        elapsed = time.perf_counter() - started
        if result.isNull():
            raise RuntimeError(f"{shape} returned an empty image")
        if run >= 2:
            samples.append(elapsed)
    return statistics.median(samples) * 1000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1024, 2048])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--vertices", type=int, default=1024)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    if load_creative_core() is None:
        raise SystemExit("CreativeCoreBridge is not built")

    print("shape,size,native_exact_ms")
    for size in args.sizes:
        for shape in ("select_rectangle", "select_ellipse", "lasso"):
            points = geometry(shape, size, args.vertices)
            native_ms = measure_native(shape, size, points, args.repeats)
            print(f"{shape},{size},{native_ms:.3f}")
    app.quit()


if __name__ == "__main__":
    main()
