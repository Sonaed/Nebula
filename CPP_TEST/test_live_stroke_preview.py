"""Visual-contract tests for the zero-latency stroke overlay."""
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from CANVAS.live_stroke_preview import LiveStrokePreview

APP = QApplication.instance() or QApplication([])


class LiveStrokePreviewTests(unittest.TestCase):
    def test_preview_tapers_with_pressure_before_native_pixels_arrive(self):
        settings = {
            "size": 24.0, "opacity": 1.0, "color": [20, 80, 220, 255],
            "pressureSize": True, "pressureOpacity": True,
            "minimumSize": 0.05, "minimumOpacity": 0.0,
        }
        canvas = SimpleNamespace(
            tools=SimpleNamespace(current_tool="brush", brush=SimpleNamespace(smoothing=0.8)),
            drawing=True, zoom=1.0, _async_stroke_pending=0,
            get_cpp_brush_settings=lambda: settings, update=lambda: None,
        )
        preview = LiveStrokePreview(canvas)
        preview.enabled = True
        preview.press(QPointF(20, 50), 0.1)
        preview.move(QPointF(90, 50), 0.1)
        preview.move(QPointF(160, 50), 1.0)
        now = time.monotonic()
        preview.points = [(point, pressure, now) for point, pressure, _ in preview.points]
        image = QImage(200, 100, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        preview.paint(painter)
        painter.end()
        # The low-pressure first segment is narrow while the pressure ramp is
        # visibly broader before the real asynchronous patch arrives.
        self.assertEqual(image.pixelColor(50, 55).alpha(), 0)
        self.assertGreater(image.pixelColor(130, 55).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
