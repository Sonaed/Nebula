"""End-to-end pointer and history coverage for raster gradient gestures."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import (QColor, QImage, QInputDevice, QKeyEvent, QMouseEvent,
                          QPointingDevice, QTabletEvent)
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import fill_image_rect_native
from DOCUMENTS.selection import SelectionOperation


class GradientCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.create_new_image(64, 48)
        self.canvas.use_gpu = False
        self.canvas.zoom = 1.0
        self.canvas.offset = QPointF()
        self.canvas.tools.set_gradient()
        self.canvas.tools.gradient_tool.geometry = "radial"
        self.canvas.tools.gradient_tool.color_mode = "color"
        self.canvas.tools.gradient_tool.end_color = QColor("cyan")
        self.canvas.brush_settings.set("color", [230, 40, 70, 255])
        layer = self.canvas.get_active_layer()
        layer.image.fill(QColor(20, 40, 80, 170))
        layer.commit_image_cache()
        self.before = layer.image.copy()
        mask = QImage(64, 48, QImage.Format.Format_ARGB32)
        mask.fill(0)
        fill_image_rect_native(mask, QRect(10, 8, 35, 30), QColor(255, 255, 255, 150))
        self.canvas.document.selection.combine(mask, SelectionOperation.REPLACE)
        self.canvas._reset_history()

    def tearDown(self):
        self.canvas.close()

    def _mouse(self, event_type, point):
        move = event_type == QEvent.Type.MouseMove
        release = event_type == QEvent.Type.MouseButtonRelease
        event = QMouseEvent(event_type, QPointF(*point), QPointF(*point),
                            Qt.MouseButton.NoButton if move else Qt.MouseButton.LeftButton,
                            Qt.MouseButton.NoButton if release else Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        handler = {QEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
                   QEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
                   QEvent.Type.MouseButtonRelease: self.canvas.mouseReleaseEvent}[event_type]
        handler(event)
        self.assertTrue(event.isAccepted())

    def test_mouse_gradient_respects_selection_and_is_one_undo_step(self):
        self._mouse(QEvent.Type.MouseButtonPress, (20, 20))
        self._mouse(QEvent.Type.MouseMove, (35, 20))
        self._mouse(QEvent.Type.MouseMove, (40, 25))
        self._mouse(QEvent.Type.MouseButtonRelease, (40, 25))
        result = self.canvas.get_active_layer().image.copy()
        self.assertNotEqual(result.pixelColor(25, 20), self.before.pixelColor(25, 20))
        self.assertEqual(result.pixelColor(4, 4), self.before.pixelColor(4, 4))
        self.assertEqual(len(self.canvas.tile_history.steps), 1)
        self.canvas.undo()
        self.assertEqual(self.canvas.get_active_layer().image, self.before)
        self.canvas.redo()
        self.assertEqual(self.canvas.get_active_layer().image, result)

    def test_escape_restores_pixels_and_discards_preview_history(self):
        self._mouse(QEvent.Type.MouseButtonPress, (20, 20))
        self._mouse(QEvent.Type.MouseMove, (40, 25))
        self.assertNotEqual(self.canvas.get_active_layer().image, self.before)
        self.canvas.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.canvas.get_active_layer().image, self.before)
        self.assertFalse(self.canvas.gradient_drawing)
        self.assertIsNone(self.canvas.gradient_original)
        self.assertIsNone(self.canvas.tile_history._pending)
        self.assertEqual(len(self.canvas.tile_history.steps), 0)

    def test_tablet_gradient_keeps_alpha_lock_and_selected_region(self):
        self.canvas.get_active_layer().lock_alpha = True
        device = QPointingDevice(
            "Gradient test stylus", 731, QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Pen,
            QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 1)
        for event_type, x, y, pressure in (
            (QEvent.Type.TabletPress, 20, 20, .7),
            (QEvent.Type.TabletMove, 40, 25, .7),
            (QEvent.Type.TabletRelease, 40, 25, 0.0),
        ):
            event = QTabletEvent(
                event_type, device, QPointF(x, y), QPointF(x, y), pressure,
                0, 0, 0, 0, 0, Qt.KeyboardModifier.NoModifier,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton if pressure else Qt.MouseButton.NoButton)
            self.canvas.tabletEvent(event)
            self.assertTrue(event.isAccepted())
        image = self.canvas.get_active_layer().image
        self.assertNotEqual(image.pixelColor(25, 20), self.before.pixelColor(25, 20))
        self.assertEqual(image.pixelColor(25, 20).alpha(), 170)
        self.assertEqual(image.pixelColor(4, 4), self.before.pixelColor(4, 4))
        self.assertEqual(len(self.canvas.tile_history.steps), 1)
        self.canvas.undo()
        self.assertEqual(self.canvas.get_active_layer().image, self.before)


if __name__ == "__main__":
    unittest.main()
