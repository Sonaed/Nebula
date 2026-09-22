from __future__ import annotations

import os
import unittest
import time
import tempfile
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QResizeEvent
from PySide6.QtCore import QSize, QPoint, QPointF, QRect, QSettings, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
from PySide6.QtTest import QTest

from CANVAS.canvas import Canvas
from UI.theme import ThemeManager
from UI.dialogs.preferences_dialog import PreferencesDialog
from UI.docks.tool_rail_dock import ToolRailDock
from UI.docks.layers_dock import LayersDock
from DOCUMENTS.document import Document
from UI.widgets.collapsible_section import CollapsibleSection
from UI.widgets.numeric_slider import NumericSlider
from UI.widgets.blend_preview import BlendPreviewWidget, PREVIEW_SIZE
from UI.widgets.color_wheel import ColorWheel
from PySide6.QtGui import QColor
from UI.ui import CreativeSystemUI
from CORE.memory_manager import MemoryManager, _create_swap_directory
from unittest.mock import patch


class UIDesignSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_and_reusable_widgets_construct(self) -> None:
        ThemeManager.apply(self.app)
        self.assertIn("#080D1A", self.app.styleSheet())
        self.assertIn("#8975EC", self.app.styleSheet())
        slider = NumericSlider("Size", 1.0, 100.0, 42.0, 1.0, " px")
        section = CollapsibleSection("Dynamics")
        section.addWidget(slider)
        self.assertEqual(slider.value(), 42.0)
        section.header.setChecked(True)
        self.assertTrue(section.content.isVisibleTo(section))

    def test_tile_scratch_defaults_to_the_user_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CACHE_HOME": directory}):
                scratch = _create_swap_directory()
            self.assertTrue(scratch.is_dir())
            self.assertEqual(scratch.parent, Path(directory) / "creativesystem" / "scratch")
            import shutil
            shutil.rmtree(scratch)

    def test_home_action_cards_keep_their_content_visible(self) -> None:
        from UI.home.home_page import HomePage
        page = HomePage()
        page.resize(1000, 700)
        page.show()
        self.app.processEvents()
        self.assertGreaterEqual(page.new_button.height(), 150)
        self.assertGreaterEqual(page.open_button.height(), 150)
        self.assertIn("Nouveau document", [label.text() for label in page.new_button.findChildren(QLabel)])
        page.close()

    def test_requested_preferences_pages_and_tool_icons_exist(self) -> None:
        dialog = PreferencesDialog(None, {})
        for name in ("General", "Interface", "Canvas", "Input", "Tablet", "Brush",
                     "Performance", "CPU", "Files", "Autosave", "Color Management"):
            self.assertIn(name, PreferencesDialog.CATEGORIES)
            self.assertGreater(dialog.pages.count(), 0)
        assets = Path(__file__).resolve().parents[1] / "UI" / "icons"
        self.assertTrue(all((assets / f"{name}.svg").is_file() for name, _, _ in ToolRailDock.TOOL_SPECS))
        dialog.close()
        self.assertIn(
            "performance/memory_limit_mb",
            {option[1] for option in PreferencesDialog.OPTIONS["Performance"]},
        )

    def test_memory_manager_reports_document_and_gpu_estimates(self) -> None:
        window = QMainWindow()
        canvas = Canvas()
        manager = MemoryManager(canvas, window.statusBar(), window)
        snapshot = manager.last_snapshot
        self.assertGreater(snapshot.document_bytes, 0)
        self.assertGreater(snapshot.process_bytes, 0)
        self.assertIn("RAM ", manager.label.text())
        self.assertIn("GPU ", manager.label.text())
        manager.shutdown()
        window.close()

    def test_projection_viewport_bounds_are_tile_limited(self) -> None:
        canvas = Canvas()
        keys = canvas.visible_document_tile_keys()
        self.assertTrue(keys)
        self.assertLess(len(keys), canvas.document.get_active_layer().tile_store.columns
                        * canvas.document.get_active_layer().tile_store.rows)
        self.assertTrue(all(0 <= tx < 13 and 0 <= ty < 10 for tx, ty in keys))
        canvas.close()

    def test_tool_rail_zoom_and_hand_control_canvas_view_only(self) -> None:
        canvas = Canvas()
        rail = ToolRailDock(canvas)
        try:
            canvas.resize(800, 600)
            canvas.show()
            rail.show()
            self.app.processEvents()
            layer = canvas.document.get_active_layer()
            layer.image.setPixelColor(120, 90, QColor("magenta"))
            before_pixels = layer.image.copy()
            before_history = canvas.tile_history.index

            pointer = QPoint(310, 240)
            initial_zoom = canvas.zoom
            image_anchor = canvas.screen_to_image_f(QPointF(pointer))
            rail.buttons["zoom_view"].click()
            self.assertEqual(canvas.tools.current_tool, "zoom_view")
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pointer)
            self.assertAlmostEqual(canvas.zoom, min(canvas.max_zoom, initial_zoom * 1.25), places=6)
            zoomed_anchor = canvas.screen_to_image_f(QPointF(pointer))
            self.assertAlmostEqual(zoomed_anchor.x(), image_anchor.x(), places=5)
            self.assertAlmostEqual(zoomed_anchor.y(), image_anchor.y(), places=5)

            rail.buttons["hand"].click()
            self.assertEqual(canvas.tools.current_tool, "hand")
            before_offset = QPointF(canvas.offset)
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(250, 200))
            QTest.mouseMove(canvas, QPoint(295, 228), 10)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(295, 228))
            self.assertAlmostEqual(canvas.offset.x() - before_offset.x(), 45.0, places=5)
            self.assertAlmostEqual(canvas.offset.y() - before_offset.y(), 28.0, places=5)
            self.assertEqual(layer.image, before_pixels)
            self.assertEqual(canvas.tile_history.index, before_history)
        finally:
            rail.close()
            canvas.close()

    def test_alpha_locked_fill_reuses_captured_tiles_without_full_snapshot(self) -> None:
        canvas = Canvas()
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            layer = canvas.document.get_active_layer()
            layer.image.fill(QColor(24, 52, 92, 72))
            layer.lock_alpha = True
            canvas.tools.set_fill()
            canvas.set_brush_setting("color", [238, 32, 16, 255])
            with patch.object(canvas, "_restore_alpha_from",
                              wraps=canvas._restore_alpha_from) as full_snapshot_restore:
                QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                                 pos=QPoint(canvas.width() // 2, canvas.height() // 2))
            self.assertEqual(full_snapshot_restore.call_count, 0)
            self.assertEqual(layer.image.pixelColor(400, 300).alpha(), 72)
            self.assertGreater(layer.image.pixelColor(400, 300).red(), 24)
            self.assertEqual(canvas.tile_history.index, 1)
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertEqual(layer.image.pixelColor(400, 300), QColor(24, 52, 92, 72))
            self.assertTrue(canvas.tile_history.redo(canvas.document))
            self.assertEqual(layer.image.pixelColor(400, 300).alpha(), 72)
        finally:
            canvas.close()

    def test_locked_alpha_never_falls_back_to_python_raster_copy(self) -> None:
        canvas = Canvas()
        try:
            image = QImage(32, 32, QImage.Format.Format_RGBA8888)
            image.fill(QColor(20, 40, 60, 80))
            snapshot = image.copy()
            with patch("CANVAS.canvas.restore_image_alpha_rect", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                    canvas._restore_alpha_from(image, snapshot, QRect(0, 0, 8, 8))
        finally:
            canvas.close()

    def test_locked_layer_rejects_raster_edits_from_mouse_and_tablet(self) -> None:
        from PySide6.QtGui import QTabletEvent

        canvas = Canvas()
        tools = ("brush", "eraser", "smudge", "clone_stamp", "blur", "sharpen",
                 "fill", "gradient", "line", "rectangle", "ellipse", "crop",
                 "move", "transform", "bezier")
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            layer = canvas.document.get_active_layer()
            layer.image.fill(QColor(35, 70, 105, 180))
            layer.locked = True
            baseline = layer.image.copy()
            pointer = QPoint(canvas.width() // 2, canvas.height() // 2)

            for tool in tools:
                with self.subTest(input="mouse", tool=tool):
                    layer.image = baseline.copy()
                    canvas._reset_history()
                    canvas.tools._select_tool(tool)
                    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pointer)
                    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pointer)
                    self.assertEqual(layer.image, baseline)
                    self.assertEqual(canvas.tile_history.index, 0)
                    self.assertIsNone(canvas.tile_history._pending)

                with self.subTest(input="tablet", tool=tool):
                    layer.image = baseline.copy()
                    canvas._reset_history()
                    canvas.tools._select_tool(tool)
                    tablet_event = SimpleNamespace(
                        type=lambda: QTabletEvent.Type.TabletPress,
                        position=lambda: QPointF(pointer),
                        modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                        pressure=lambda: 0.8, xTilt=lambda: 0, yTilt=lambda: 0,
                        accept=lambda: None,
                    )
                    canvas.tabletEvent(tablet_event)
                    self.assertEqual(layer.image, baseline)
                    self.assertEqual(canvas.tile_history.index, 0)
                    self.assertIsNone(canvas.tile_history._pending)
        finally:
            canvas.close()

    def test_canvas_blend_projection_updates_visible_tile_asynchronously(self) -> None:
        canvas = Canvas()
        upper = canvas.document.add_layer("Multiply")
        upper.image.fill(QColor(128, 128, 128, 255))
        upper.blend_mode = "multiply"
        canvas._ensure_projection()
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: loop.quit() if (0, 0) in canvas._projection_ready_tiles else None)
        timer.start()
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.assertIn((0, 0), canvas._projection_ready_tiles)
        self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(2, 2), QColor(128, 128, 128, 255))
        canvas.close()

    def test_undo_waits_for_the_open_stroke_transaction(self) -> None:
        canvas = Canvas()
        layer = canvas.document.get_active_layer()
        canvas.begin_history_action()
        layer.image.setPixelColor(8, 8, QColor("red"))
        canvas.commit_history_action()
        self.assertEqual(canvas.tile_history.index, 1)

        canvas.begin_stroke_history()
        canvas.undo()
        self.assertEqual(canvas.tile_history.index, 1)
        canvas.commit_stroke_history()
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()

        self.assertEqual(canvas.tile_history.index, 0)
        canvas.close()

    def test_selection_shortcut_edit_is_undoable_without_layer_snapshots(self) -> None:
        canvas = Canvas()
        try:
            layer = canvas.document.get_active_layer()
            layer.image.setPixelColor(8, 8, QColor("red"))
            before = layer.image.copy()
            canvas.setFocus()
            QTest.keyClick(canvas, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(canvas.tile_history.index, 1)
            step = canvas.tile_history.steps[-1]
            from CANVAS.tile_history import SELECTION_TILE_ID
            self.assertTrue(step.tiles)
            self.assertTrue(all(key[0] == SELECTION_TILE_ID for key in step.tiles))
            self.assertEqual(layer.image, before)
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertTrue(canvas.document.selection.is_empty())
            self.assertTrue(canvas.tile_history.redo(canvas.document))
            self.assertTrue(canvas.document.selection.contains(3, 4))
            self.assertEqual(canvas.document.get_active_layer().image, before)
        finally:
            canvas.close()

    def test_shape_selection_mouse_gesture_is_one_undoable_transaction(self) -> None:
        canvas = Canvas()
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            canvas.tools.set_rectangle_selection()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            QTest.mouseMove(canvas, QPoint(180, 170), 10)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(180, 170))

            self.assertEqual(canvas.tile_history.index, 1)
            self.assertFalse(canvas.document.selection.is_empty())
            from CANVAS.tile_history import SELECTION_TILE_ID
            self.assertTrue(all(key[0] == SELECTION_TILE_ID
                                for key in canvas.tile_history.steps[-1].tiles))
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertTrue(canvas.document.selection.is_empty())
            self.assertTrue(canvas.tile_history.redo(canvas.document))
            self.assertFalse(canvas.document.selection.is_empty())
        finally:
            canvas.close()

    def test_escape_cancels_pending_shape_selection_history(self) -> None:
        canvas = Canvas()
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            canvas.tools.set_rectangle_selection()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            self.assertIsNotNone(canvas.tile_history._pending)
            QTest.keyClick(canvas, Qt.Key.Key_Escape)
            self.assertIsNone(canvas.tile_history._pending)
            self.assertFalse(canvas.selection_drawing)
            self.assertEqual(canvas.tile_history.index, 0)
        finally:
            canvas.close()

    def test_tablet_lasso_uses_same_undoable_selection_transaction(self) -> None:
        from PySide6.QtGui import QTabletEvent

        canvas = Canvas()
        def tablet_event(event_type, x, y):
            return SimpleNamespace(
                type=lambda: event_type,
                position=lambda: QPointF(x, y),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 0.7, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            canvas.tools.set_lasso()
            canvas.tabletEvent(tablet_event(QTabletEvent.Type.TabletPress, 100, 100))
            canvas.tabletEvent(tablet_event(QTabletEvent.Type.TabletMove, 180, 110))
            canvas.tabletEvent(tablet_event(QTabletEvent.Type.TabletMove, 150, 190))
            canvas.tabletEvent(tablet_event(QTabletEvent.Type.TabletRelease, 100, 100))
            self.assertEqual(canvas.tile_history.index, 1)
            self.assertFalse(canvas.document.selection.is_empty())
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertTrue(canvas.document.selection.is_empty())
            self.assertTrue(canvas.tile_history.redo(canvas.document))
            self.assertFalse(canvas.document.selection.is_empty())
        finally:
            canvas.close()

    def test_tablet_magic_wand_is_one_undoable_action(self) -> None:
        from PySide6.QtGui import QTabletEvent

        canvas = Canvas()
        try:
            canvas.tools.set_magic_wand()
            event = SimpleNamespace(
                type=lambda: QTabletEvent.Type.TabletPress,
                position=lambda: QPointF(canvas.width() / 2, canvas.height() / 2),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 0.6, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
            canvas.tabletEvent(event)
            self.assertEqual(canvas.tile_history.index, 1)
            self.assertFalse(canvas.document.selection.is_empty())
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertTrue(canvas.document.selection.is_empty())
        finally:
            canvas.close()

    def test_tablet_fill_uses_cpp_path_and_respects_layer_lock(self) -> None:
        from PySide6.QtGui import QTabletEvent

        canvas = Canvas()
        try:
            layer = canvas.document.get_active_layer()
            layer.image.fill(QColor("navy"))
            event = SimpleNamespace(
                type=lambda: QTabletEvent.Type.TabletPress,
                position=lambda: QPointF(canvas.width() / 2, canvas.height() / 2),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 0.7, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
            point = canvas.screen_to_image(event.position())
            layer.image.setPixelColor(point, QColor("white"))
            before = layer.image.copy()
            canvas.set_brush_setting("color", [240, 30, 80, 255])
            canvas.tools.set_fill()
            canvas.tabletEvent(event)
            self.assertEqual(canvas.tile_history.index, 1)
            self.assertEqual(len(canvas.tile_history.steps[-1].tiles), 1)
            self.assertNotIn("__selection_mask__", {
                key[0] for key in canvas.tile_history.steps[-1].tiles
            })
            self.assertNotEqual(canvas.document.get_active_layer().image, before)
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertEqual(canvas.document.get_active_layer().image, before)

            layer = canvas.document.get_active_layer()
            layer.locked = True
            canvas.tabletEvent(event)
            self.assertEqual(canvas.tile_history.index, 0)
        finally:
            canvas.close()

    def test_tablet_shape_tool_draws_and_commits_one_action(self) -> None:
        from PySide6.QtGui import QTabletEvent

        canvas = Canvas()
        def event(event_type, x, y):
            return SimpleNamespace(
                type=lambda: event_type, position=lambda: QPointF(x, y),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 0.8, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
        try:
            canvas.resize(800, 600)
            canvas.show()
            self.app.processEvents()
            canvas.tools.set_rectangle()
            before = canvas.document.get_active_layer().image.copy()
            canvas.tabletEvent(event(QTabletEvent.Type.TabletPress, 180, 160))
            canvas.tabletEvent(event(QTabletEvent.Type.TabletMove, 300, 260))
            canvas.tabletEvent(event(QTabletEvent.Type.TabletRelease, 300, 260))
            self.assertEqual(canvas.tile_history.index, 1)
            self.assertNotEqual(canvas.document.get_active_layer().image, before)
            self.assertTrue(canvas.tile_history.undo(canvas.document))
            self.assertEqual(canvas.document.get_active_layer().image, before)
        finally:
            canvas.close()

    def test_tablet_gradient_and_crop_complete_their_transactions(self) -> None:
        from PySide6.QtGui import QTabletEvent

        def event(event_type, x, y):
            return SimpleNamespace(
                type=lambda: event_type, position=lambda: QPointF(x, y),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 1.0, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
        gradient = Canvas()
        try:
            gradient.resize(800, 600)
            gradient.show()
            self.app.processEvents()
            layer = gradient.document.get_active_layer()
            layer.image.fill(QColor("white"))
            gradient.tools.set_gradient()
            before = layer.image.copy()
            gradient.tabletEvent(event(QTabletEvent.Type.TabletPress, 180, 200))
            gradient.tabletEvent(event(QTabletEvent.Type.TabletMove, 360, 200))
            gradient.tabletEvent(event(QTabletEvent.Type.TabletRelease, 360, 200))
            self.assertEqual(gradient.tile_history.index, 1)
            self.assertNotEqual(layer.image, before)
            self.assertTrue(gradient.tile_history.undo(gradient.document))
            self.assertEqual(gradient.document.get_active_layer().image, before)
        finally:
            gradient.close()

        crop = Canvas()
        try:
            crop.resize(800, 600)
            crop.show()
            self.app.processEvents()
            old_size = (crop.document.width, crop.document.height)
            crop.tools.set_crop()
            crop.tabletEvent(event(QTabletEvent.Type.TabletPress, 180, 160))
            crop.tabletEvent(event(QTabletEvent.Type.TabletMove, 400, 320))
            crop.tabletEvent(event(QTabletEvent.Type.TabletRelease, 400, 320))
            self.assertEqual(crop.tile_history.index, 1)
            self.assertLess(crop.document.width, old_size[0])
            self.assertLess(crop.document.height, old_size[1])
            self.assertTrue(crop.tile_history.undo(crop.document))
            self.assertEqual((crop.document.width, crop.document.height), old_size)
        finally:
            crop.close()

    def test_escape_restores_preview_for_pending_tablet_gradient_and_shape(self) -> None:
        from PySide6.QtGui import QTabletEvent

        def event(event_type, x, y):
            return SimpleNamespace(
                type=lambda: event_type, position=lambda: QPointF(x, y),
                modifiers=lambda: Qt.KeyboardModifier.NoModifier,
                pressure=lambda: 1.0, xTilt=lambda: 0, yTilt=lambda: 0,
                accept=lambda: None,
            )
        for tool_name, select_tool in (("gradient", "set_gradient"),
                                       ("rectangle", "set_rectangle")):
            canvas = Canvas()
            try:
                canvas.resize(800, 600)
                canvas.show()
                self.app.processEvents()
                layer = canvas.document.get_active_layer()
                layer.image.fill(QColor("white"))
                before = layer.image.copy()
                getattr(canvas.tools, select_tool)()
                canvas.tabletEvent(event(QTabletEvent.Type.TabletPress, 180, 180))
                canvas.tabletEvent(event(QTabletEvent.Type.TabletMove, 340, 280))
                self.assertIsNotNone(canvas.tile_history._pending)
                self.assertNotEqual(layer.image, before)
                QTest.keyClick(canvas, Qt.Key.Key_Escape)
                self.assertIsNone(canvas.tile_history._pending)
                self.assertEqual(canvas.tile_history.index, 0)
                self.assertEqual(canvas.document.get_active_layer().image, before)
            finally:
                canvas.close()

    def test_layers_dock_builds_mode_specific_blend_sliders(self) -> None:
        dock = LayersDock(None)
        document = Document(8, 8)
        layer = document.get_active_layer()
        layer.blend_mode = "multiply"
        dock.refresh_layers(document)
        self.assertEqual(set(dock.blend_parameter_controls), {
            "opacity", "opposite_mix", "intensity", "gamma", "mix_normal",
        })
        self.assertEqual(len(dock.blend_parameter_controls), 5)
        changes = []
        edit_events = []
        dock.blend_parameter_changed.connect(lambda key, value: changes.append((key, value)))
        dock.blend_parameter_edit_started.connect(lambda: edit_events.append("start"))
        dock.blend_parameter_edit_ended.connect(lambda: edit_events.append("end"))
        dock.blend_parameter_controls["gamma"].setValue(1.7, emit=True)
        dock.blend_parameter_controls["gamma"].setValue(1.8, emit=True)
        dock._finish_blend_parameter_edit()
        self.assertEqual(changes[-1], ("gamma", 1.8))
        self.assertEqual(edit_events, ["start", "end"])
        layer.blend_mode = "hue"
        dock.update_layer_properties(document)
        self.assertEqual(set(dock.blend_parameter_controls), {
            "opacity", "opposite_mix", "intensity", "hue_shift", "saturation_boost",
        })
        self.assertEqual(len(dock.blend_parameter_controls), 5)
        for mode, specific in {
            "screen": {"intensity", "gamma", "mix_normal"},
            "overlay": {"intensity", "pivot", "mix_normal"},
            "color_burn": {"intensity", "clamp", "mix_normal"},
            "soft_light": {"intensity", "softness", "mix_normal"},
            "difference": {"intensity", "offset", "mix_normal"},
        }.items():
            layer.blend_mode = mode
            dock.update_layer_properties(document)
            self.assertEqual(set(dock.blend_parameter_controls), specific | {"opacity", "opposite_mix"})
        dock.resize(360, 930)
        dock.show()
        self.app.processEvents()
        self.assertGreaterEqual(
            dock.blend_parameter_scroll.viewport().height(),
            dock.blend_parameters_widget.sizeHint().height(),
        )
        self.assertTrue(all(control.isVisible() for control in dock.blend_parameter_controls.values()))
        dock.close()

    def test_blend_preview_is_bounded_and_debounced_without_shader_recompile_on_values(self) -> None:
        preview = BlendPreviewWidget()
        self.assertEqual(preview.size().width(), PREVIEW_SIZE)
        self.assertLessEqual(preview._draw_timer.interval(), 16)
        preview.set_mode("multiply")
        compile_count = preview.shader_compile_count
        timer_id = preview._draw_timer.timerId()
        preview.set_parameter("gamma", 1.6)
        preview.set_parameter("intensity", 0.7)
        self.assertEqual(preview._draw_timer.timerId(), timer_id)
        self.assertEqual(preview.shader_compile_count, compile_count)
        self.assertEqual(preview.parameters["gamma"], 1.6)
        QTest.qWait(40)
        self.assertEqual(preview.frame_request_count, 1)
        preview.set_parameter("gamma", 1.7)
        preview.set_parameter("gamma", 1.8)
        QTest.qWait(40)
        self.assertEqual(preview.frame_request_count, 2)
        preview.close()

    def test_blend_slider_signal_path_updates_canvas_only_when_edit_ends(self) -> None:
        dock = LayersDock(None)
        document = Document(8, 8)
        document.get_active_layer().blend_mode = "multiply"
        dock.refresh_layers(document)
        history = SimpleNamespace(_pending=None)
        updates = []
        canvas = SimpleNamespace(
            document=document,
            tile_history=history,
            begin_history_action=lambda dirty_only=False: setattr(history, "_pending", {}),
            commit_history_action=lambda: setattr(history, "_pending", None),
            update=lambda: updates.append("update"),
        )
        ui = SimpleNamespace(canvas=canvas, layers_dock=dock)
        dock.blend_parameter_edit_started.connect(
            lambda: CreativeSystemUI._begin_blend_parameter_edit(ui)
        )
        dock.blend_parameter_changed.connect(
            lambda key, value: CreativeSystemUI._set_active_blend_parameter(ui, key, value)
        )
        dock.blend_parameter_edit_ended.connect(
            lambda: CreativeSystemUI._end_blend_parameter_edit(ui)
        )
        control = dock.blend_parameter_controls["gamma"]
        control.setValue(1.4, emit=True)
        control.setValue(1.8, emit=True)
        self.assertEqual(updates, [])
        self.assertEqual(document.get_active_layer().blend_parameters["gamma"], 1.8)
        dock._finish_blend_parameter_edit()
        self.assertEqual(updates, ["update"])
        dock.blend_parameter_controls["opacity"].setValue(0.42, emit=True)
        self.assertAlmostEqual(document.get_active_layer().opacity, 0.42)
        self.assertNotIn("opacity", document.get_active_layer().blend_parameters)
        self.assertEqual(updates, ["update"])
        dock._finish_blend_parameter_edit()
        self.assertEqual(updates, ["update", "update"])
        dock.close()

    def test_tablet_pressure_preference_gates_brush_dynamics(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        keys = ("tablet/pressure", "tablet/pressure_size", "tablet/pressure_opacity")
        saved = {key: (settings.contains(key), settings.value(key)) for key in keys}
        canvas = Canvas()
        try:
            settings.setValue("tablet/pressure", False)
            settings.setValue("tablet/pressure_size", True)
            settings.setValue("tablet/pressure_opacity", True)
            canvas._apply_brush_settings(canvas.brush_settings.snapshot())
            self.assertFalse(canvas.tools.brush.pressure_size)
            self.assertFalse(canvas.tools.brush.pressure_opacity)
        finally:
            for key, (present, value) in saved.items():
                if present:
                    settings.setValue(key, value)
                else:
                    settings.remove(key)
            canvas._apply_brush_settings(canvas.brush_settings.snapshot())
            canvas.close()

    def test_canvas_only_fits_the_first_resize(self) -> None:
        canvas = Canvas()
        calls = []
        canvas.fit_document = lambda: calls.append(True)
        canvas._initial_view_fitted = False
        canvas.resizeEvent(QResizeEvent(QSize(900, 700), QSize(800, 600)))
        canvas.resizeEvent(QResizeEvent(QSize(1000, 800), QSize(900, 700)))
        self.assertEqual(len(calls), 1)
        canvas.close()

    def test_synthetic_mouse_suppression_is_configurable(self) -> None:
        from types import SimpleNamespace
        from PySide6.QtCore import Qt

        canvas = Canvas()
        try:
            canvas._last_tablet_event_time = time.monotonic()
            event = SimpleNamespace(
                source=lambda: Qt.MouseEventSource.MouseEventSynthesizedBySystem
            )
            self.assertTrue(canvas._ignore_tablet_synthetic_mouse(event))
            canvas.ignore_synthetic_mouse_after_tablet = False
            self.assertFalse(canvas._ignore_tablet_synthetic_mouse(event))
            native_event = SimpleNamespace(
                source=lambda: Qt.MouseEventSource.MouseEventNotSynthesized
            )
            canvas.ignore_synthetic_mouse_after_tablet = True
            self.assertFalse(canvas._ignore_tablet_synthetic_mouse(native_event))
        finally:
            canvas.close()

    def test_brush_settings_are_remembered_per_tool(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        keys = (
            "brush/remember_per_tool",
            "brush/tool_settings/brush",
            "brush/tool_settings/picker",
        )
        saved = {key: (settings.contains(key), settings.value(key)) for key in keys}
        canvas = Canvas()
        try:
            settings.setValue("brush/remember_per_tool", True)
            settings.remove("brush/tool_settings/brush")
            settings.remove("brush/tool_settings/picker")
            canvas.set_brush_setting("size", 37.0)
            canvas.tools.set_picker()
            self.assertEqual(canvas.brush_settings.get("size"), 10.0)
            canvas.set_brush_setting("size", 5.0)
            canvas.tools.set_brush()
            self.assertEqual(canvas.brush_settings.get("size"), 37.0)
        finally:
            for key, (present, value) in saved.items():
                if present:
                    settings.setValue(key, value)
                else:
                    settings.remove(key)
            canvas.close()

    def test_color_wheel_round_trips_hsv_color(self) -> None:
        wheel = ColorWheel()
        wheel.setColor(QColor(30, 160, 220))
        actual = wheel.color()
        self.assertLess(abs(actual.red() - 30), 3)
        self.assertLess(abs(actual.green() - 160), 3)
        self.assertLess(abs(actual.blue() - 220), 3)

    def test_view_transform_keeps_document_coordinates_stable(self) -> None:
        canvas = Canvas()
        canvas.resize(900, 650)
        canvas.offset.setX(42.0)
        canvas.offset.setY(27.0)
        canvas.zoom = 0.75
        canvas.view_rotation = 37.0
        canvas.view_flip_x = True
        image_point = QPointF(213.0, 147.0)
        screen_point = canvas._view_transform_point(
            canvas.offset + image_point * canvas.zoom
        )

        result = canvas.screen_to_image(screen_point)

        self.assertLessEqual(abs(result.x() - 213), 1)
        self.assertLessEqual(abs(result.y() - 147), 1)
        canvas.close()

    def test_drawing_assistants_constrain_brush_points(self) -> None:
        canvas = Canvas()
        canvas.set_assistant_mode("ruler")
        snapped = canvas.constrain_assistant_point(QPoint(390, 100))
        self.assertEqual(snapped.x(), 400)
        self.assertEqual(snapped.y(), 100)
        canvas.set_assistant_mode("perspective")
        start = canvas.constrain_assistant_point(QPoint(600, 300), begin=True)
        end = canvas.constrain_assistant_point(QPoint(640, 320))
        self.assertEqual(start.y(), 300)
        self.assertEqual(end.y(), 300)
        canvas.set_vanishing_point(QPoint(200, 150))
        self.assertAlmostEqual(canvas.assistant_vanishing_point.x(), 200 / 799)
        self.assertAlmostEqual(canvas.assistant_vanishing_point.y(), 150 / 599)
        canvas.close()

    def test_zoom_tool_keeps_the_point_under_the_pointer_fixed(self) -> None:
        canvas = Canvas()
        canvas.resize(900, 650)
        canvas.view_rotation = 28.0
        canvas.view_flip_y = True
        canvas.offset = QPointF(31.0, 52.0)
        canvas.zoom = 0.8
        image_point = QPointF(240.0, 155.0)
        pointer = canvas._view_transform_point(canvas.offset + image_point * canvas.zoom)

        canvas.zoom_at(pointer, 1.25)

        mapped = canvas._view_transform_point(canvas.offset + image_point * canvas.zoom)
        self.assertLess(abs(mapped.x() - pointer.x()), 0.01)
        self.assertLess(abs(mapped.y() - pointer.y()), 0.01)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
