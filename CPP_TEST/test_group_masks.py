"""Folder masks: add, paint, undo/redo, nesting kept by undo, PSD round trip."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.blend_modes import composite_document
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager

APP = QApplication.instance() or QApplication([])

SQUARE = [QPointF(0, 0), QPointF(160, 0), QPointF(160, 120), QPointF(0, 120)]
LEFT_HALF = [QPointF(0, 0), QPointF(80, 0), QPointF(80, 120), QPointF(0, 120)]


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class GroupMaskTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(160, 120, 72, None))
        self.manager = LayerManager(self.canvas.document)
        self.manager.add_layer("Encre")
        # Paint both layers red, then put them in one folder.
        for index in (0, 1):
            self.canvas.document.set_active_layer(index)
            self.canvas.set_brush_setting("color", [220, 30, 30, 255])
            self.canvas.apply_lasso_fill(SQUARE)
        self.group = self.canvas.document.group_layers([0, 1], "Dossier")
        self.canvas.reset_history() if hasattr(self.canvas, "reset_history") else None

    def tearDown(self):
        self.canvas.close()

    def visible_alpha(self, x, y):
        return QColor.fromRgba(composite_document(self.canvas.document).pixel(x, y)).alpha()

    def add_mask(self):
        self.canvas.begin_history_action(structure_only=True)
        self.assertTrue(self.manager.add_group_mask(self.group.id))
        self.canvas.commit_history_action()
        self.assertTrue(self.canvas.edit_group_alpha_mask(self.group.id))

    def paint_mask_black(self, points):
        self.canvas.set_brush_setting("color", [0, 0, 0, 255])
        self.canvas.apply_lasso_fill(points)

    def test_painting_the_folder_mask_hides_its_whole_content(self):
        self.add_mask()
        self.assertEqual(self.visible_alpha(40, 60), 255)      # white mask: all visible
        self.paint_mask_black(LEFT_HALF)
        self.assertEqual(self.visible_alpha(40, 60), 0)        # both layers hidden
        self.assertEqual(self.visible_alpha(120, 60), 255)
        # The layers' own pixels are untouched: only the folder mask changed.
        for layer in self.canvas.document.layers:
            self.assertEqual(QColor.fromRgba(layer.image.pixel(40, 60)).alpha(), 255)
            self.assertIsNone(layer.alpha_mask_store)

    def _mouse(self, event_type, point):
        move = event_type == QEvent.Type.MouseMove
        release = event_type == QEvent.Type.MouseButtonRelease
        event = QMouseEvent(event_type, QPointF(*point), QPointF(*point),
                            Qt.MouseButton.NoButton if move else Qt.MouseButton.LeftButton,
                            Qt.MouseButton.NoButton if release else Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QEvent.Type.MouseButtonRelease: self.canvas.mouseReleaseEvent}[event_type](event)

    def test_brush_stroke_on_the_folder_mask(self):
        self.add_mask()
        self.canvas.zoom = 1.0
        self.canvas.offset = QPointF(0, 0)
        self.canvas.tools.set_brush()
        self.canvas.set_brush_setting("size", 30.0)
        self.canvas.set_brush_setting("opacity", 1.0)
        self.canvas.set_brush_setting("color", [0, 0, 0, 255])
        self._mouse(QEvent.Type.MouseButtonPress, (20, 60))
        for x in range(25, 141, 5):
            self._mouse(QEvent.Type.MouseMove, (x, 60))
        self._mouse(QEvent.Type.MouseButtonRelease, (140, 60))
        APP.processEvents()
        self.assertLess(self.visible_alpha(80, 60), 40)       # stroke hides the folder
        self.assertEqual(self.visible_alpha(80, 5), 255)      # elsewhere untouched
        for layer in self.canvas.document.layers:              # pixels untouched
            self.assertEqual(QColor.fromRgba(layer.image.pixel(80, 60)).alpha(), 255)
        self.canvas.undo()
        self.assertEqual(self.visible_alpha(80, 60), 255)

    def test_mask_painting_undo_and_redo(self):
        self.add_mask()
        self.paint_mask_black(LEFT_HALF)
        self.canvas.undo()
        self.assertEqual(self.visible_alpha(40, 60), 255)
        self.canvas.redo()
        self.assertEqual(self.visible_alpha(40, 60), 0)

    def test_adding_the_mask_is_undoable_and_keeps_the_folder(self):
        self.add_mask()
        self.paint_mask_black(LEFT_HALF)
        self.canvas.undo()          # paint
        self.canvas.undo()          # add mask
        group = self.canvas.document.layer_groups[0]
        self.assertIs(group, self.group)          # same folder object, not rebuilt
        self.assertIsNone(group.alpha_mask_store)
        self.canvas.redo()
        self.canvas.redo()
        self.assertIsNotNone(group.alpha_mask_store)
        self.assertEqual(self.visible_alpha(40, 60), 0)

    def test_disable_and_invert(self):
        self.add_mask()
        self.paint_mask_black(LEFT_HALF)
        self.assertTrue(self.manager.toggle_group_mask_disabled(self.group.id))
        self.assertEqual(self.visible_alpha(40, 60), 255)
        self.manager.toggle_group_mask_disabled(self.group.id)
        self.assertTrue(self.manager.invert_group_mask(self.group.id))
        self.assertEqual(self.visible_alpha(40, 60), 255)
        self.assertEqual(self.visible_alpha(120, 60), 0)

    def test_structural_undo_keeps_nested_folders(self):
        document = self.canvas.document
        self.manager.add_layer("Fond")
        inner = document.layer_groups[0]
        inner.parent_id = None
        self.canvas.begin_history_action(structure_only=True)
        document.set_group_visibility(inner.id, False)
        self.canvas.commit_history_action()
        parent_before = {g.id: g.parent_id for g in document.layer_groups}
        self.canvas.undo()
        self.assertEqual({g.id: g.parent_id for g in document.layer_groups}, parent_before)

    def test_psd_round_trip_keeps_the_folder_mask(self):
        from DOCUMENTS.format_psd import PSDFormat
        self.add_mask()
        self.paint_mask_black(LEFT_HALF)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dossier.psd"
            self.assertTrue(PSDFormat.save(self.canvas.document, path))
            loaded = PSDFormat.load(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.layer_groups), 1)
        group = loaded.layer_groups[0]
        self.assertIsNotNone(group.alpha_mask_store)
        image = composite_document(loaded)
        self.assertEqual(QColor.fromRgba(image.pixel(40, 60)).alpha(), 0)
        self.assertEqual(QColor.fromRgba(image.pixel(120, 60)).alpha(), 255)


if __name__ == "__main__":
    unittest.main()
