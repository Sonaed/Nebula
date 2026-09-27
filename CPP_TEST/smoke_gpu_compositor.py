"""Manual OpenGL parity smoke test for the standard GPU tile compositor.

Run with a desktop OpenGL session. It compares the compositor FBO to the
CreativeCore reference for each GPU-supported blend mode and exits non-zero on
the first mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QSurfaceFormat
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
format_ = QSurfaceFormat()
format_.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
format_.setVersion(3, 3)
format_.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
QSurfaceFormat.setDefaultFormat(format_)

from CANVAS.canvas import Canvas
from DOCUMENTS.blend_modes import BLEND_MODES, composite_layers


def main() -> int:
    app = QApplication(sys.argv)
    canvas = Canvas()
    base = canvas.document.get_active_layer()
    image = base.image
    image.fill(QColor(200, 100, 50, 255))
    base.image = image
    upper = canvas.document.add_layer("GPU parity")
    image = upper.image
    image.fill(QColor(128, 128, 128, 255))
    upper.image = image
    canvas.resize(800, 600)
    canvas.show()
    # Normal mode already draws individual GPU textures in Canvas.paintGL;
    # this smoke test exercises the shader-compositor modes.
    modes = list(BLEND_MODES[1:12])
    state = {"index": 0, "failed": False}

    def check_next() -> None:
        index = state["index"]
        if index >= len(modes):
            app.quit()
            return
        upper.blend_mode = modes[index]
        canvas.gpu_tile_compositor.tiles.clear()
        canvas.update()

        def compare() -> None:
            try:
                tile = canvas.gpu_tile_compositor.tiles[(0, 0)]
                actual = (tile.first if tile.result_first else tile.second).toImage().pixelColor(10, 10).getRgb()
                expected = composite_layers(canvas.document.width, canvas.document.height,
                                            canvas.document.layers).pixelColor(10, 10).getRgb()
                if actual != expected:
                    print(f"GPU parity mismatch {modes[index]}: {actual} != {expected}")
                    state["failed"] = True
                    app.quit()
                    return
                print(f"GPU parity OK: {modes[index]} {actual}")
                state["index"] += 1
                QTimer.singleShot(0, check_next)
            except Exception as error:
                print(f"GPU parity failed {modes[index]}: {error}")
                state["failed"] = True
                app.quit()

        QTimer.singleShot(100, compare)

    QTimer.singleShot(250, check_next)
    app.exec()
    canvas.close()
    return 1 if state["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
