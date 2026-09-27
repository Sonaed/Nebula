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


def measure(size: int, repeats: int, library) -> float:
    samples = []
    for _ in range(repeats):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(31, 79, 143, 255))
        tool = FillTool()
        tool.cpp_library = library
        start = time.perf_counter()
        changed = tool.fill(image, QPoint(size // 2, size // 2), QColor(210, 48, 93, 255))
        samples.append((time.perf_counter() - start) * 1000.0)
        if changed.size() != image.size():
            raise RuntimeError("Fill returned incomplete bounds")
    return statistics.median(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare contiguous flood-fill paths.")
    parser.add_argument("--sizes", nargs="+", type=int, default=[128, 256])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    library = load_creative_core()
    if library is None:
        raise SystemExit("CreativeCoreBridge is not built")

    print("pixels,creativecore_exact_ms")
    for size in args.sizes:
        native_ms = measure(size, args.repeats, library)
        print(f"{size * size},{native_ms:.3f}")


if __name__ == "__main__":
    main()
