"""OpenGL integration check for the instanced round-brush path.

Run from the project root in a desktop OpenGL session:
    QT_QPA_PLATFORM=wayland python CPP_TEST/smoke_gpu_instanced_stroke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QSurfaceFormat
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
surface = QSurfaceFormat()
surface.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
surface.setVersion(3, 3)
surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
QSurfaceFormat.setDefaultFormat(surface)

from CANVAS.canvas import Canvas


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    canvas = Canvas()
    canvas.resize(900, 700)
    canvas.show()
    result = {"status": 1}

    def run_check():
        try:
            if not canvas.gpu_ready or not canvas.isValid():
                raise RuntimeError("Canvas OpenGL non initialisé")
            layer = canvas.document.get_active_layer()
            settings = {
                "size": 24.0, "spacing": 0.15, "hardness": 0.8,
                "opacity": 1.0, "flow": 1.0, "roundness": 1.0,
                "pressureSize": False, "pressureOpacity": False,
                "pressureFlow": False, "color": [220, 30, 40, 255],
            }
            canvas.set_brush_settings(settings)
            layer.image.fill(QColor(255, 255, 255, 255))
            layer.commit_image_cache(force=True)
            canvas.begin_stroke_history()
            canvas.tile_history.capture_before(layer, QRect(80, 80, 140, 40))
            canvas.makeCurrent()
            try:
                stroke = canvas.gpu_instanced_stroke
                if not stroke.begin(layer, layer.image, settings, QPoint(100, 100), 1.0):
                    raise RuntimeError("Démarrage du stroke instancié refusé")
                stroke.queue_segment(QPoint(100, 100), QPoint(200, 100),
                                     1.0, 1.0, QRect(80, 80, 140, 40))
                stroke.request_finish()
                if not stroke.process():
                    raise RuntimeError("Le stroke GPU n'a pas été finalisé")
            finally:
                canvas.doneCurrent()

            stats = stroke.last_stroke_stats
            painted = layer.image.pixelColor(150, 100)
            untouched = layer.image.pixelColor(150, 70)
            if stats.get("draw_calls") != 1 or stats.get("instances", 0) < 2:
                raise AssertionError(f"Batch d'instances invalide : {stats}")
            if (painted.red() < 218 or painted.green() > 33 or painted.blue() > 43
                    or painted.alpha() < 250 or untouched != QColor(255, 255, 255)):
                raise AssertionError(f"Pixels GPU incorrects : {painted.getRgb()}, {untouched.getRgb()}")
            canvas.undo()
            if layer.image.pixelColor(150, 100) != QColor(255, 255, 255):
                raise AssertionError("Undo n'a pas restauré les pixels avant stroke")
            canvas.redo()
            redone = layer.image.pixelColor(150, 100)
            if redone.red() < 218 or redone.green() > 33 or redone.blue() > 43:
                raise AssertionError("Redo n'a pas restauré le stroke GPU")
            print({"status": "ok", "stroke": stats, "undo_redo": "ok"})
            result["status"] = 0
        except Exception as exc:
            print({"status": "failed", "error": str(exc)})
        finally:
            canvas.close()
            app.quit()

    QTimer.singleShot(1200, run_check)
    app.exec()
    return result["status"]


if __name__ == "__main__":
    raise SystemExit(main())
