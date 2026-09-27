"""Compare standard-layer composition before/after the batched native bridge."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage, QPainter

from DOCUMENTS.blend_modes import composition_mode, composite_layers


WIDTH = 768
HEIGHT = 768
REPETITIONS = 9
MODES = ("normal", "multiply", "screen", "overlay", "soft_light")


def make_layers():
    layers = []
    for index, mode in enumerate(MODES):
        image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
        image.fill(QColor(25 + index * 35, 80 + index * 20, 210 - index * 27, 150 + index * 18))
        layers.append(SimpleNamespace(
            image=image, visible=True, opacity=0.72, blend_mode=mode,
            blend_parameters={}, clipping=False,
        ))
    return layers


def legacy_qt(layers):
    output = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    output.fill(0)
    painter = QPainter(output)
    for layer in layers:
        painter.setCompositionMode(composition_mode(layer.blend_mode))
        painter.setOpacity(layer.opacity)
        painter.drawImage(0, 0, layer.image)
    painter.end()
    return output


def median_ms(operation, layers):
    values = []
    for _ in range(REPETITIONS):
        start = time.perf_counter_ns()
        operation(WIDTH, HEIGHT, layers) if operation is composite_layers else operation(layers)
        values.append((time.perf_counter_ns() - start) / 1_000_000)
    return statistics.median(values)


def main():
    layers = make_layers()
    reference = legacy_qt(layers)
    native = composite_layers(WIDTH, HEIGHT, layers)
    if any(reference.pixel(x, y) != native.pixel(x, y)
           for x, y in ((0, 0), (WIDTH // 2, HEIGHT // 2), (WIDTH - 1, HEIGHT - 1))):
        raise SystemExit("Native composite differs from Qt reference")
    qt_ms = median_ms(legacy_qt, layers)
    native_ms = median_ms(composite_layers, layers)
    print(f"canvas={WIDTH}x{HEIGHT} layers={len(layers)} repetitions={REPETITIONS}")
    print(f"Qt reference: {qt_ms:.3f} ms")
    print(f"native batch + bridge: {native_ms:.3f} ms")
    print(f"ratio Qt/native: {qt_ms / native_ms:.2f}x")
    print("Timing is local and covers full-image composition, not UI projection.")


if __name__ == "__main__":
    main()
