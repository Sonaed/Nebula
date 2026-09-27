"""Benchmark the exact CreativeCore affine selection transform path."""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from DOCUMENTS.selection import SelectionMask
from TOOLS.transform_tool import TransformSpec, TransformTool


def measure(repeats: int = 5) -> float:
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(QColor(28, 72, 160, 255))
    selection = SelectionMask(1024, 1024)
    selection.image.fill(0)
    from PySide6.QtGui import QPainter
    painter = QPainter(selection.image)
    painter.fillRect(QRect(128, 128, 768, 768), QColor(255, 255, 255, 255))
    painter.end()
    selection.invalidate()
    spec = TransformSpec(translate_x=8, translate_y=4, scale_x=1.02,
                         scale_y=0.98, rotation=2)
    durations = []
    for _ in range(repeats):
        started = time.perf_counter()
        TransformTool().apply(image, spec, selection)
        durations.append(time.perf_counter() - started)
    return statistics.median(durations) * 1000


def main() -> None:
    app = QApplication.instance() or QApplication([])
    if load_creative_core() is None:
        raise RuntimeError("CreativeCoreBridge absent")
    native_ms = measure()
    print(f"1024² selected transform: CreativeCore exact path={native_ms:.3f} ms")
    app.quit()


if __name__ == "__main__":
    main()
