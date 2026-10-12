"""Regression tests for Save → Close ordering and its cancellation paths."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from CORE.application import CreativeSystem


class DocumentCloseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _window(*, dirty=True, save_result=True):
        history = SimpleNamespace(index=4 if dirty else 1, _pending=None)
        disposed = []
        return SimpleNamespace(
            canvas=SimpleNamespace(tile_history=history),
            _last_saved_history_index=1,
            _psd_import_scheduler=None,
            save_file=lambda: save_result,
            _dispose_current_document=lambda: disposed.append(True),
            disposed=disposed,
        )

    def test_successful_save_closes_after_writer_returns(self):
        window = self._window(save_result=True)
        with patch("CORE.application.QMessageBox.question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(CreativeSystem.close_document(window))
        self.assertEqual(window.disposed, [True])

    def test_failed_or_cancelled_save_keeps_document_open(self):
        window = self._window(save_result=False)
        with patch("CORE.application.QMessageBox.question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(CreativeSystem.close_document(window))
        self.assertEqual(window.disposed, [])
        window = self._window()
        with patch("CORE.application.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(CreativeSystem.close_document(window))
        self.assertEqual(window.disposed, [])

    def test_clean_document_closes_without_prompt(self):
        window = self._window(dirty=False)
        with patch("CORE.application.QMessageBox.question") as question:
            self.assertTrue(CreativeSystem.close_document(window))
        question.assert_not_called()
        self.assertEqual(window.disposed, [True])

    def test_open_dialog_advertises_all_supported_formats(self):
        source = Path("CORE/application.py").read_text(encoding="utf-8")
        for suffix in ("*.nebula", "*.psd", "*.psb", "*.png", "*.jpg", "*.tif", "*.svg", "*.pdf"):
            self.assertIn(suffix, source)
        self.assertIn("Tous les fichiers (*)", source)


if __name__ == "__main__":
    unittest.main()
