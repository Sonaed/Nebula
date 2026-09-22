"""Measure the native texture-atlas allocation and RGBA upload boundary.

Run from the project root with:
    QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_texture_atlas.py
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage

from CANVAS.texture_atlas import TextureAtlas


def main() -> None:
    samples = []
    for _ in range(7):
        atlas = TextureAtlas(size=2048, padding=1)
        image = QImage(32, 32, QImage.Format.Format_RGBA8888)
        image.fill(QColor(40, 110, 220, 255))
        started = time.perf_counter_ns()
        for index in range(256):
            if not atlas.upload_region(index, image):
                raise RuntimeError("Native atlas rejected a valid 32x32 region")
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
        atlas.close()
    median_ms = statistics.median(samples)
    print({
        "engine": "CreativeCore native atlas via ctypes",
        "regions": 256,
        "region": "32x32 RGBA",
        "median_upload_ms": round(median_ms, 3),
        "per_region_us": round(median_ms * 1000 / 256, 3),
        "samples": 7,
    })


if __name__ == "__main__":
    main()
