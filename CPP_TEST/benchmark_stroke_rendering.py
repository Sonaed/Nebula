"""Repeatable CPU brush-stroke baseline for the instancing roadmap.

Run from the project root with:
    QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_stroke_rendering.py

The timings include Python/ctypes call setup and CreativeCore rasterization,
but exclude Qt event dispatch, tile-history capture, and GPU composition.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from CANVAS.canvas import Canvas


def make_path(points: int, width: int, height: int, pattern: str):
    result = []
    for index in range(points):
        t = index / max(1, points - 1)
        if pattern == "diagonal":
            x, y = 24 + t * (width - 48), 30 + t * (height - 60)
        elif pattern == "wave":
            import math
            x = 24 + t * (width - 48)
            y = height * 0.5 + math.sin(t * math.pi * 8) * height * 0.28
        else:
            x = 24 + t * (width - 48)
            y = height * 0.5
        result.append(QPoint(round(x), round(y)))
    return result


def measure(canvas: Canvas, name: str, size: float, spacing: float,
            points: int, pattern: str, samples: int = 7) -> dict:
    width, height = 800, 600
    path = make_path(points, width, height, pattern)
    canvas.set_brush_settings({
        "size": size,
        "spacing": spacing,
        "hardness": 0.8,
        "opacity": 0.85,
        "flow": 1.0,
        "color": [30, 90, 210, 255],
    })
    canvas._sync_cpp_brush()
    library, handle = canvas.cpp_brush_library, canvas.cpp_brush
    if not canvas.cpp_brush_enabled:
        raise RuntimeError("CreativeCore brush indisponible")

    durations_ms = []
    dab_estimate = 0
    for sample in range(samples + 1):
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(QColor(0, 0, 0, 0))
        first = path[0]
        started = time.perf_counter_ns()
        library.cs_brush_begin_stroke(handle, float(first.x()), float(first.y()), 1.0)
        # The canvas paints a zero-length segment on press after beginning the
        # brush stroke, matching its real initial stamp path.
        canvas._cpp_draw_segment_once(
            image, first, first, 1.0, 1.0, (0.0, 0.0), (0.0, 0.0)
        )
        dab_estimate += 2
        for start, end in zip(path, path[1:]):
            # With pressure fixed to 1.0, this matches the engine's spacing
            # formula for the configured fixed brush size.
            distance = ((end.x() - start.x()) ** 2 + (end.y() - start.y()) ** 2) ** 0.5
            dab_estimate += max(1, int((distance / max(0.5, size * spacing)) + 0.999999)) + 1
            canvas._cpp_draw_segment_once(
                image, start, end, 1.0, 1.0, (0.0, 0.0), (0.0, 0.0)
            )
        library.cs_brush_end_stroke(handle)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if sample:
            durations_ms.append(elapsed)

    median_ms = statistics.median(durations_ms)
    return {
        "name": name,
        "canvas_px": [width, height],
        "input_points": points,
        "native_segment_calls": points,
        "estimated_dabs_per_stroke": round(dab_estimate / (samples + 1)),
        "median_cpu_stroke_ms": round(median_ms, 3),
        "p95_cpu_stroke_ms": round(sorted(durations_ms)[int((len(durations_ms) - 1) * 0.95)], 3),
        "stamp_gpu_draw_calls_current": 0,
        "samples": samples,
    }


def main() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    cases = [
        ("fine_dense", 8.0, 0.10, 240, "wave"),
        ("medium_diagonal", 24.0, 0.15, 160, "diagonal"),
        ("large_soft_line", 64.0, 0.20, 120, "line"),
    ]
    try:
        results = [measure(canvas, *case) for case in cases]
        print(json.dumps({
            "engine": "CreativeCore QImage CPU rasterization via ctypes",
            "timing_scope": "ctypes setup + C++ stroke rasterization; excludes event dispatch/GPU composition",
            "results": results,
            "instancing_after_measurement": "not available: GPU stamp renderer/FBO not implemented",
        }, indent=2))
    finally:
        canvas.close()
        app.quit()


if __name__ == "__main__":
    main()
