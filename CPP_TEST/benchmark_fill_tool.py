from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import load_creative_core
from TOOLS.fill_tool import FillTool


def measure(size: int, repeats: int, library) -> tuple[float, float]:
    samples: dict[str, list[float]] = {"Python compatibility": [], "CreativeCore C++": []}
    for backend in samples:
        for _ in range(repeats):
            image = QImage(size, size, QImage.Format.Format_ARGB32)
            image.fill(QColor(31, 79, 143, 255))
            tool = FillTool()
            tool.cpp_library = library if backend == "CreativeCore C++" else None
            start = time.perf_counter()
            changed = tool.fill(image, QPoint(size // 2, size // 2), QColor(210, 48, 93, 255))
            samples[backend].append((time.perf_counter() - start) * 1000.0)
            if changed.size() != image.size():
                raise RuntimeError(f"Fill returned incomplete bounds for {backend}")
    return (statistics.median(samples["Python compatibility"]),
            statistics.median(samples["CreativeCore C++"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare contiguous flood-fill paths.")
    parser.add_argument("--sizes", nargs="+", type=int, default=[128, 256])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    library = load_creative_core()
    if library is None:
        raise SystemExit("CreativeCoreBridge is not built")

    print("pixels,python_ms,native_ms,speedup")
    for size in args.sizes:
        python_ms, native_ms = measure(size, args.repeats, library)
        print(f"{size * size},{python_ms:.3f},{native_ms:.3f},{python_ms / native_ms:.2f}x")


if __name__ == "__main__":
    main()
