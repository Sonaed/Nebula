from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from CORE.application import CreativeSystem


class ApplicationSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_application_starts_native_canvas_and_closes_cleanly(self) -> None:
        window = CreativeSystem()
        try:
            self.assertTrue(window.canvas.cpp_brush_enabled)
            self.assertTrue(window.canvas.projection_worker.native_enabled)
            self.assertIsNotNone(window.canvas.document.get_active_layer().tile_store._native_handle)
            window.run()
            QTimer.singleShot(25, self.app.quit)
            self.assertEqual(self.app.exec(), 0)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
