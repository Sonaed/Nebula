from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from CANVAS.history_labels import describe_step
from CANVAS.tile_history import TileHistory
from DOCUMENTS.document import Document
from UI.docks.history_dock import HistoryDock, STATE_ROLE


class CanvasStub(QWidget):
    history_changed = Signal()
    history_restored = Signal()

    def __init__(self):
        super().__init__()
        self.document = object()
        self.tile_history = SimpleNamespace(
            steps=[SimpleNamespace(label=f"Étape {number}", detail="Calque 1") for number in range(3)],
            index=3, _pending=None,
        )
        self.free_transform = None
        self.undo_calls = 0
        self.redo_calls = 0

    def undo(self):
        self.undo_calls += 1
        self.tile_history.index = max(0, self.tile_history.index - 1)
        self.history_changed.emit()

    def redo(self):
        self.redo_calls += 1
        self.tile_history.index = min(len(self.tile_history.steps), self.tile_history.index + 1)
        self.history_changed.emit()


class HistoryDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CanvasStub()
        self.dock = HistoryDock(self.canvas)

    def tearDown(self):
        if self.dock._target is not None:
            self.dock._finish_seek()
        self.dock.close()
        self.dock.deleteLater()
        self.canvas.close()
        self.canvas.deleteLater()
        self.app.processEvents()

    def drain_seek(self):
        for _ in range(10):
            self.dock._seek_timer.stop()
            if self.dock._target is None:
                return
            self.dock._seek_tick()
        self.fail("History seek did not finish within its bounded step count")

    def test_click_jump_uses_canvas_undo_and_redo_and_restores_input(self):
        self.dock._activate_item(self.dock.list.item(1))
        self.assertFalse(self.canvas.isEnabled())
        self.assertFalse(self.dock.list.isEnabled())
        self.drain_seek()
        self.assertEqual(self.canvas.undo_calls, 2)
        self.assertEqual(self.canvas.tile_history.index, 1)
        self.assertTrue(self.canvas.isEnabled())
        self.assertEqual(self.dock.list.item(1).data(STATE_ROLE), "current")
        self.assertEqual(self.dock.list.item(3).data(STATE_ROLE), "future")
        self.assertTrue(self.dock.seek(3))
        self.drain_seek()
        self.assertEqual(self.canvas.redo_calls, 2)
        self.assertEqual(self.canvas.tile_history.index, 3)

    def test_enter_activates_keyboard_selected_state(self):
        self.dock.show()
        self.app.processEvents()
        self.dock.list.setCurrentRow(2)
        QTest.keyClick(self.dock.list, Qt.Key.Key_Return)
        self.drain_seek()
        self.assertEqual(self.canvas.tile_history.index, 2)

    def test_pending_transaction_and_transform_cannot_be_scrubbed(self):
        for pending, transform in (({}, None), (None, object())):
            self.canvas.tile_history._pending = pending
            self.canvas.free_transform = transform
            self.assertFalse(self.dock.seek(0))
            self.assertEqual(self.canvas.undo_calls, 0)
            self.assertFalse(self.dock.undo_button.isEnabled())

    def test_new_document_or_branch_aborts_queued_jump(self):
        self.dock.seek(0)
        self.dock._seek_timer.stop()
        self.canvas.document = object()
        self.dock._seek_tick()
        self.assertEqual(self.canvas.undo_calls, 0)
        self.assertTrue(self.canvas.isEnabled())
        self.assertIsNone(self.dock._target)
        self.dock.seek(0)
        self.dock._seek_timer.stop()
        self.canvas.tile_history.steps[-1] = SimpleNamespace(label="Nouvelle branche", detail="")
        self.dock._seek_tick()
        self.assertEqual(self.canvas.undo_calls, 0)
        self.assertEqual(self.dock.list.item(3).text(), "Nouvelle branche")

    def test_no_progress_or_restore_error_stops_after_one_attempt(self):
        with patch.object(self.canvas, "undo") as undo:
            self.dock.seek(0)
            self.drain_seek()
            undo.assert_called_once()
        self.assertTrue(self.canvas.isEnabled())
        with patch.object(self.canvas, "undo", side_effect=OSError("Unavailable swap")) as undo:
            self.dock.seek(0)
            self.drain_seek()
            undo.assert_called_once()
        self.assertIn("pas pu", self.dock.hint.text())
        self.assertTrue(self.canvas.isEnabled())

    def test_metadata_refresh_preserves_rows_and_stops_when_hidden(self):
        first = self.dock.list.item(1)
        self.dock.refresh()
        self.assertIs(self.dock.list.item(1), first)
        self.dock.show()
        self.assertTrue(self.dock._retention_timer.isActive())
        self.dock.hide()
        self.assertFalse(self.dock._retention_timer.isActive())

    def test_disabled_canvas_stays_disabled_after_jump(self):
        self.canvas.setEnabled(False)
        self.dock.seek(0)
        self.drain_seek()
        self.assertFalse(self.canvas.isEnabled())

    def test_retention_trim_rebuilds_exact_available_states(self):
        self.canvas.tile_history.steps.pop(0)
        self.canvas.tile_history.index = 2
        self.dock.refresh()
        self.assertEqual(self.dock.list.count(), 3)
        self.assertEqual(self.dock.list.item(1).text(), "Étape 1")
        self.assertEqual(self.dock.list.currentRow(), 2)

    def test_retention_trim_during_jump_aborts_without_crossing_states(self):
        self.dock.seek(0)
        self.dock._seek_timer.stop()
        self.dock._seek_tick()
        self.assertEqual(self.canvas.undo_calls, 1)
        self.canvas.tile_history.steps.pop(0)
        self.canvas.tile_history.index -= 1
        self.drain_seek()
        self.assertEqual(self.canvas.undo_calls, 1)
        self.assertTrue(self.canvas.isEnabled())
        self.assertFalse(self.dock.seek(-1))
        self.assertFalse(self.dock.seek(3))

    def test_real_native_history_jump_round_trips_pixels_and_cursor(self):
        document = Document(8, 8)
        history = TileHistory()
        layer = document.get_active_layer()
        original = layer.image.pixelColor(0, 0)
        for color in ("red", "blue", "green"):
            history.begin(document, dirty_only=True, label="Coup de pinceau")
            history.capture_before(layer, QRect(0, 0, 1, 1))
            layer.image.setPixelColor(0, 0, QColor(color))
            history.mark_dirty(layer, QRect(0, 0, 1, 1))
            self.assertTrue(history.commit(document))
        self.canvas.document = document
        self.canvas.tile_history = history
        self.canvas.undo = lambda: history.undo(document)
        self.canvas.redo = lambda: history.redo(document)
        self.dock.refresh()
        self.dock.seek(0)
        self.drain_seek()
        self.assertEqual(layer.image.pixelColor(0, 0), original)
        history._assert_cursor_consistency()
        self.dock.seek(2)
        self.drain_seek()
        self.assertEqual(layer.image.pixelColor(0, 0), QColor("blue"))
        history._assert_cursor_consistency()


class HistoryDescriptionTests(unittest.TestCase):
    def test_native_metadata_keeps_name_after_structural_payload_migration(self):
        document = Document(12, 12)
        history = TileHistory()
        history.begin(document, structure_only=True)
        document.get_active_layer().name = "Lumières"
        self.assertTrue(history.commit(document))
        step = history.steps[-1]
        self.assertEqual(step.label, "Renommer le calque")
        self.assertEqual(step.detail, "Lumières")
        self.assertFalse(step.before)
        self.assertFalse(step.after)
        self.assertTrue(history.undo(document))
        self.assertNotEqual(document.get_active_layer().name, "Lumières")
        self.assertTrue(history.redo(document))
        self.assertEqual(document.get_active_layer().name, "Lumières")

    def test_explicit_stroke_label_survives_and_does_not_add_noop_steps(self):
        document = Document(12, 12)
        history = TileHistory()
        layer = document.get_active_layer()
        history.begin(document, dirty_only=True, label="Tampon de duplication", detail=layer.name)
        history.capture_before(layer, QRect(0, 0, 1, 1))
        layer.image.setPixelColor(0, 0, QColor("orange"))
        history.mark_dirty(layer, QRect(0, 0, 1, 1))
        self.assertTrue(history.commit(document))
        self.assertEqual(history.steps[-1].label, "Tampon de duplication")
        self.assertEqual(history.steps[-1].detail, layer.name)
        history.begin(document, dirty_only=True, label="Ne pas ajouter")
        self.assertFalse(history.commit(document))
        self.assertEqual(len(history.steps), 1)

    def test_selection_and_mask_descriptions_need_only_tile_keys(self):
        selection = describe_step({}, {}, [("__selection_mask__", 0, 0)])
        mask = describe_step({}, {}, [("__alpha_mask__:1", 0, 0)])
        self.assertEqual(selection[0], "Sélection")
        self.assertEqual(mask[0], "Peindre le masque")


if __name__ == "__main__":
    unittest.main()
