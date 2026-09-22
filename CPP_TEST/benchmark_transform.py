"""Benchmark affine selection transforms on the native and compatibility paths."""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from DOCUMENTS.selection import SelectionMask
from TOOLS.transform_tool import TransformSpec, TransformTool
import TOOLS.transform_tool as transform_module


def measure(native: bool, repeats: int = 5) -> float:
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
    def python_contains(mask, x, y):
        return (0 <= x < mask.width and 0 <= y < mask.height
                and mask.image.pixelColor(x, y).alpha() > 0)
    for _ in range(repeats):
        started = time.perf_counter()
        if native:
            TransformTool().apply(image, spec, selection)
        else:
            with (patch.object(transform_module, "load_creative_core", return_value=None),
                  patch.object(SelectionMask, "contains", python_contains)):
                TransformTool().apply(image, spec, selection)
        durations.append(time.perf_counter() - started)
    return statistics.median(durations) * 1000


def main() -> None:
    app = QApplication.instance() or QApplication([])
    if load_creative_core() is None:
        raise RuntimeError("CreativeCoreBridge absent")
    native_ms, fallback_ms = measure(True), measure(False)
    print(f"1024² selected transform: native={native_ms:.3f} ms, "
          f"compatibility={fallback_ms:.3f} ms, "
          f"ratio={fallback_ms / max(native_ms, 1e-9):.2f}x")
    app.quit()


if __name__ == "__main__":
    main()
