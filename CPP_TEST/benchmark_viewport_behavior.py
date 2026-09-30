"""Headless 26.2.2 viewport/cache qualification with a sparse 8K document."""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QPointF, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from DOCUMENTS.document import Document


def tile(color: str) -> QImage:
    image = QImage(64, 64, QImage.Format.Format_ARGB32); image.fill(QColor(color)); return image


def wait_for_projection(canvas: Canvas, timeout_ms=2500) -> bool:
    loop = QEventLoop(); timer = QTimer(); timer.setSingleShot(True)
    timer.timeout.connect(loop.quit); poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if canvas._projection_display_ready else None)
    timer.start(timeout_ms); poll.start(5); canvas._ensure_projection(); loop.exec(); poll.stop()
    return canvas._projection_display_ready


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([]); canvas = Canvas(); canvas.resize(900, 600)
    document = Document(8000, 8000)
    for index in range(7): document.add_layer(f"Layer {index}")
    for layer in document.layers:
        for key, colour in (((0, 0), "red"), ((60, 60), "blue"), ((100, 70), "green")):
            layer.tile_store.set_tile(*key, tile(colour))
    canvas.set_document(document)
    # `set_document()` fits an 8K canvas, which would intentionally request
    # every tile and defeat a viewport behaviour test. Exercise a real working
    # view instead: one screen at 100%.
    canvas.zoom = 1.0; canvas.offset = QPointF(0, 0); canvas._last_view_offset = QPointF(0, 0)
    canvas.performance_stats_snapshot(reset=True)
    scenarios = {}
    for name, delta, factor in (("slow_pan", (-8, 0), 1.0), ("fast_pan", (-180, 0), 1.0),
                                ("reverse", (200, 0), 1.0), ("zoom_in", (0, 0), 2.0), ("zoom_out", (0, 0), .25)):
        canvas.offset += QPointF(*delta)
        canvas.zoom_at(QPointF(450, 300), factor)
        started = time.perf_counter(); ready = wait_for_projection(canvas)
        scenarios[name] = {"ready": ready, "seconds": round(time.perf_counter() - started, 4),
                           "cache": canvas.tile_cache_manager.snapshot()}
    canvas.zoom = 1.0; canvas.offset = QPointF(-8, 0)
    started = time.perf_counter(); ready = wait_for_projection(canvas)
    scenarios["return_recent"] = {"ready": ready, "seconds": round(time.perf_counter() - started, 4),
                                   "cache": canvas.tile_cache_manager.snapshot()}
    result = {"scope": "headless CPU viewport policy; GPU long-session excluded", "scenarios": scenarios,
              "performance": canvas.performance_stats_snapshot(), "gpu": canvas.gpu_stats_snapshot()}
    output = json.dumps(result, indent=2)
    if args.output: args.output.write_text(output + "\n", encoding="utf-8")
    print(output); canvas.close()


if __name__ == "__main__": main()
