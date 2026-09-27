from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage

from DOCUMENTS.blend_modes import composite_layers
from CPP_TEST.legacy_blend_reference import composite_reference


def make_layers(size: int):
    layers = []
    for color, mode, opacity in (
        (QColor(47, 105, 198, 173), "normal", 1.0),
        (QColor(225, 73, 121, 191), "soft_light", 0.76),
    ):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(color)
        layers.append(SimpleNamespace(
            image=image, visible=True, opacity=opacity, blend_mode=mode,
            blend_parameters={"intensity": 0.84, "softness": 0.64,
                              "mix_normal": 0.13, "opacity": 0.91},
        ))
    layers[0].blend_parameters = {}
    return layers


def measure(size: int, repeats: int) -> tuple[float, float]:
    layers = make_layers(size)
    backends = {
        "Python NumPy reference": lambda: composite_reference(size, size, layers),
        "CreativeCore C++ batch": lambda: composite_layers(size, size, layers),
    }
    results = {}
    for name, render in backends.items():
        samples = []
        for _ in range(repeats):
            start = time.perf_counter()
            image = render()
            elapsed = (time.perf_counter() - start) * 1000.0
            if image is None or image.size() != layers[0].image.size():
                raise RuntimeError(f"Incomplete composite from {name}")
            samples.append(elapsed)
        results[name] = statistics.median(samples)
    return results["Python NumPy reference"], results["CreativeCore C++ batch"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare parameterized layer compositors.")
    parser.add_argument("--sizes", nargs="+", type=int, default=[256, 512])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print("pixels,python_ms,native_ms,speedup")
    for size in args.sizes:
        python_ms, native_ms = measure(size, args.repeats)
        print(f"{size * size},{python_ms:.3f},{native_ms:.3f},{python_ms / native_ms:.2f}x")


if __name__ == "__main__":
    main()
