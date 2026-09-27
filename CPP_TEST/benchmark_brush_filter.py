from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import filter_brush_segment
from CPP_TEST.legacy_brush_reference import filter_segments


def make_image(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    for y in range(size):
        color = QColor((y * 3) % 256, (y * 7) % 256, (y * 11) % 256, 255)
        for x in range(size):
            image.setPixelColor(x, y, color)
    return image


def measure(size: int, repeats: int) -> tuple[float, float]:
    base = make_image(size)
    settings = {"size": 24.0, "spacing": 0.16, "opacity": 0.78, "flow": 0.84}
    start = QPoint(1, 2)
    end = QPoint(size - 2, size - 3)
    samples = {"Python compatibility": [], "CreativeCore C++": []}
    for backend in samples:
        for _ in range(repeats):
            image = base.copy()
            started = time.perf_counter()
            if backend == "CreativeCore C++":
                if filter_brush_segment(
                    image, start.x(), start.y(), 0.35, end.x(), end.y(), 0.9,
                    settings["size"], settings["spacing"],
                    settings["opacity"] * settings["flow"], False,
                ) is None:
                    raise RuntimeError("Native filter API unavailable")
            else:
                filter_segments(
                    image, [(start, end)], settings, 0.35, 0.9, False
                )
            samples[backend].append((time.perf_counter() - started) * 1000.0)
    return (statistics.median(samples["Python compatibility"]),
            statistics.median(samples["CreativeCore C++"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare local brush blur filter backends.")
    parser.add_argument("--sizes", nargs="+", type=int, default=[128, 256])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print("pixels,python_ms,native_ms,speedup")
    for size in args.sizes:
        python_ms, native_ms = measure(size, args.repeats)
        print(f"{size * size},{python_ms:.3f},{native_ms:.3f},{python_ms / native_ms:.2f}x")


if __name__ == "__main__":
    main()
