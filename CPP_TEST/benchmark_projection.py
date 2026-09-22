"""Compare one invalidate call per tile with the native batch API."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CORE.projection_worker import ProjectionLayer, ProjectionWorker


def benchmark(tiles: int, layer_count: int, threads: int, batched: bool) -> tuple[float, float]:
    app = QApplication.instance() or QApplication([])
    worker = ProjectionWorker(native_library=ctypes.CDLL(
        str(ROOT / "build_cpp_native" / "libCreativeCoreBridge.so")
    ))
    worker.set_thread_count(threads)
    images = []
    layers = []
    for index in range(layer_count):
        image = QImage(64, 64, QImage.Format.Format_RGBA8888)
        image.fill(QColor((35 + index * 31) % 256,
                          (70 + index * 19) % 256,
                          (120 + index * 23) % 256, 255))
        images.append(image)
        layers.append(ProjectionLayer(
            image, True, 1.0, "multiply" if index else "normal",
            {"intensity": .72, "gamma": 1.2, "mix_normal": .08},
        ))

    loop = QEventLoop()
    completed = [0]
    errors = []
    def on_projected(*_args):
        completed[0] += 1
        if completed[0] >= tiles:
            loop.quit()
    worker.projected.connect(on_projected)
    worker.failed.connect(lambda *args: (errors.append(args), loop.quit()))
    tile_inputs = {(tile, 0): (64, 64, layers) for tile in range(tiles)}

    start = time.perf_counter()
    if batched:
        worker.request(tile_inputs)
    else:
        for tile, value in tile_inputs.items():
            worker.request({tile: value})
    submit_elapsed = time.perf_counter() - start
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    elapsed = time.perf_counter() - start
    worker.close()
    if errors or completed[0] != tiles:
        raise RuntimeError(f"projection incomplete: {completed[0]}/{tiles}; {errors[:1]}")
    return elapsed, submit_elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiles", type=int, default=64)
    parser.add_argument("--layers", type=int, default=5)
    args = parser.parse_args()
    for threads in (1, 4, 8):
        for batched in (False, True):
            values = [benchmark(args.tiles, args.layers, threads, batched)
                      for _ in range(3)]
            label = "batch" if batched else "per_tile"
            mean_elapsed = sum(value[0] for value in values) / len(values)
            mean_submit = sum(value[1] for value in values) / len(values)
            print(f"threads={threads} mode={label} mean_s={mean_elapsed:.6f} "
                  f"submit_ms={mean_submit*1000:.3f} tiles_per_s={args.tiles/mean_elapsed:.1f}")


if __name__ == "__main__":
    main()
