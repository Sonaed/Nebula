"""Compare the native integer move with the former QPainter path."""
from __future__ import annotations

import sys
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter

from TOOLS.move_tool import MoveTool


def measure(callback, source, repetitions=5):
    samples = []
    for _ in range(repetitions):
        image = source.copy()
        start = perf_counter()
        callback(image)
        samples.append((perf_counter() - start) * 1000.0)
    return median(samples)


def main():
    source = QImage(2048, 2048, QImage.Format.Format_ARGB32)
    source.fill(QColor(80, 140, 210, 200))
    tool = MoveTool()

    def native(image):
        tool.apply(image, QPointF(37, -29))

    def former_qt(image):
        moved = QImage(image.size(), QImage.Format.Format_ARGB32)
        moved.fill(0)
        painter = QPainter(moved)
        painter.drawImage(37, -29, image)
        painter.end()

    print("2048x2048 integer translation, median of 5")
    print(f"CreativeCore: {measure(native, source):.3f} ms")
    print(f"Qt compatibility: {measure(former_qt, source):.3f} ms")


if __name__ == "__main__":
    main()
