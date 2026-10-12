"""Global stylus pressure curve: maths, persistence, and use by the canvas."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from TOOLS.pressure_curve import PRESETS, PressureCurve


class PressureCurveTests(unittest.TestCase):
    def test_linear_is_identity(self):
        curve = PressureCurve()
        for p in (0.0, 0.1, 0.5, 0.93, 1.0):
            self.assertAlmostEqual(curve.map(p), p, places=3)

    def test_soft_curve_raises_light_pressure_and_stays_monotone(self):
        curve = PressureCurve(PRESETS["Doux"])
        self.assertGreater(curve.map(0.3), 0.4)
        values = [curve.map(i / 200) for i in range(201)]
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(values, values[1:])))
        self.assertAlmostEqual(curve.map(0.0), 0.0, places=4)
        self.assertAlmostEqual(curve.map(1.0), 1.0, places=4)

    def test_s_curve_never_overshoots(self):
        curve = PressureCurve(PRESETS["Courbe en S"])
        self.assertTrue(all(0.0 <= curve.map(i / 100) <= 1.0 for i in range(101)))

    def test_serialization_round_trip_and_bad_input(self):
        curve = PressureCurve(PRESETS["Ferme"])
        self.assertEqual(PressureCurve.parse(curve.serialize()).points, curve.points)
        self.assertTrue(PressureCurve.parse("garbage;;").is_linear())

    def test_canvas_applies_the_curve_to_pen_pressure(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QInputDevice, QPointingDevice, QTabletEvent
        from PySide6.QtWidgets import QApplication
        from CANVAS.canvas import Canvas
        from DOCUMENTS.document import Document
        QApplication.instance() or QApplication([])
        canvas = Canvas()
        try:
            canvas.set_document(Document(100, 100, 72, None))
            canvas.pressure_curve.set_points(PRESETS["Très doux"])
            seen = []
            canvas.live_stroke_preview.press = lambda _pos, pressure: seen.append(pressure)
            pen = QPointingDevice("curve-pen", 99, QInputDevice.DeviceType.Stylus,
                                  QPointingDevice.PointerType.Pen,
                                  QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 2)
            point = QPointF(10, 10)
            canvas.tabletEvent(QTabletEvent(QTabletEvent.Type.TabletPress, pen, point, point, 0.25,
                                            0, 0, 0, 0, 0, Qt.KeyboardModifier.NoModifier,
                                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
            self.assertAlmostEqual(seen[0], canvas.pressure_curve.map(0.25), places=4)
            self.assertGreater(seen[0], 0.5)
        finally:
            canvas.close()


if __name__ == "__main__":
    unittest.main()
