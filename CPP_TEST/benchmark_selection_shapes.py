"""Compare native selection-mask rasterization with the Qt compatibility path."""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QSize
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from TOOLS.selection_tools import SelectionTools
import TOOLS.selection_tools as selection_module


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


def measure_pair(shape: str, size: int, points: list[QPointF],
                 repeats: int) -> tuple[float, float]:
    samples = {True: [], False: []}
    for run in range(repeats + 2):
        order = (True, False) if run % 2 == 0 else (False, True)
        for native in order:
            started = time.perf_counter()
            if native:
                result = SelectionTools.shape_mask(shape, QSize(size, size), points)
            else:
                with patch.object(selection_module, "native_selection_shape_mask",
                                  return_value=None):
                    result = SelectionTools.shape_mask(shape, QSize(size, size), points)
            elapsed = time.perf_counter() - started
            if result.isNull():
                raise RuntimeError(f"{shape} returned an empty image")
            if run >= 2:
                samples[native].append(elapsed)
    return tuple(statistics.median(samples[native]) * 1000.0
                 for native in (True, False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1024, 2048])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--vertices", type=int, default=1024)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    if load_creative_core() is None:
        raise SystemExit("CreativeCoreBridge is not built")

    print("shape,size,native_ms,qt_compat_ms,qt_over_native")
    for size in args.sizes:
        for shape in ("select_rectangle", "select_ellipse", "lasso"):
            points = geometry(shape, size, args.vertices)
            native_ms, qt_ms = measure_pair(shape, size, points, args.repeats)
            print(f"{shape},{size},{native_ms:.3f},{qt_ms:.3f},"
                  f"{qt_ms / max(native_ms, 1e-9):.2f}x")
    app.quit()


if __name__ == "__main__":
    main()
