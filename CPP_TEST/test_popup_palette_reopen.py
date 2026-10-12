"""Right-clicking while the palette is open closes it, never re-opens it.

Re-opening during the closing click created a popup while the old one still
held the grab, which Wayland reports as a transient-parent error.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document

APP = QApplication.instance() or QApplication([])


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class PopupPaletteReopenTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(80, 60, 72, None))
        self.canvas.right_click_color_picker = True
        self.canvas.right_click_palette = True

    def tearDown(self):
        if self.canvas.popup_palette is not None:
            self.canvas.popup_palette.hide()
        self.canvas.close()

    def right_click(self):
        event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
                            Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
                            Qt.KeyboardModifier.NoModifier)
        self.canvas.mousePressEvent(event)
        APP.processEvents()

    def test_open_then_close_without_reopening(self):
        self.right_click()
        palette = self.canvas.popup_palette
        self.assertTrue(palette.isVisible())
        palette.hide()                 # Qt closes the popup on the outside click...
        self.right_click()             # ...and the same click reaches the canvas
        self.assertFalse(palette.isVisible())

    def test_right_click_while_open_closes(self):
        self.right_click()
        self.right_click()
        self.assertFalse(self.canvas.popup_palette.isVisible())


if __name__ == "__main__":
    unittest.main()
