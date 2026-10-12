"""Real widget workflows: initial layout, returning home, formats, and options."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication, QMainWindow, QDockWidget, QLabel
from PySide6.QtTest import QTest
from CANVAS.canvas import Canvas
from DOCUMENTS.document_dialog import DocumentDialog
from UI.ui import CreativeSystemUI, BUILTIN_WORKSPACE_OPEN
from UI.models.workspace_manager import WorkspaceManager
from UI.home.home_page import HomePage


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dock_visibility_survives_hidden_parent_and_inactive_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            window = QMainWindow()
            docks = []
            for name in ('Color', 'Presets', 'Closed'):
                dock = QDockWidget(name, window)
                dock.setObjectName(name)
                dock.setWidget(QLabel(name))
                window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                docks.append(dock)
            window.tabifyDockWidget(docks[0], docks[1])
            docks[2].hide()
            settings = QSettings(str(Path(directory)/'layout.ini'), QSettings.Format.IniFormat)
            manager = WorkspaceManager(window, settings)
            manager.set_docks(docks)
            expected = {'Color': True, 'Presets': True, 'Closed': False}
            self.assertEqual(manager._factory_visibility, expected)
            manager.save('Before showing')
            window.show()
            self.app.processEvents()
            self.assertEqual(manager._visibility(), expected)
            window.hide()
            self.assertEqual(manager._visibility(), expected)
            window.close()

    def test_workspace_opens_all_expected_docks_and_focus_restores_them(self):
        settings = QSettings('CreativeSystem', 'CreativeSystem')
        saved = {key: settings.value(key) for key in settings.allKeys()}
        settings.clear()
        window = QMainWindow()
        canvas = Canvas()
        try:
            ui = CreativeSystemUI(window, canvas)
            window.resize(1280, 800)
            window.show()
            ui.show_workspace()
            self.app.processEvents()
            expected = BUILTIN_WORKSPACE_OPEN['Peinture']
            actual = {d.objectName() for d in ui._workspace_docks() if not d.isHidden()}
            self.assertEqual(actual, expected)
            self.assertLessEqual(window.minimumSizeHint().height(), 800)
            self.assertTrue(ui.search_button.isVisible())
            self.assertGreaterEqual(canvas.width(), 700)
            self.assertLess(ui.toolbar_smoothing.mapTo(window, ui.toolbar_smoothing.rect().topRight()).x(), window.width())
            ui.toggle_focus_mode()
            self.assertTrue(all(d.isHidden() for d in ui._workspace_docks()))
            ui.toggle_focus_mode()
            self.assertEqual({d.objectName() for d in ui._workspace_docks() if not d.isHidden()}, expected)
            ui.load_workspace("Minimal")
            self.assertEqual({d.objectName() for d in ui._workspace_docks() if not d.isHidden()}, {"ToolRailDock"})
            ui.load_workspace("Peinture")
            self.assertFalse(ui.history_dock.isHidden())
            ui.show_home()
            ui.show_workspace()
            self.assertEqual({d.objectName() for d in ui._workspace_docks() if not d.isHidden()}, expected)
            canvas.tools.set_gradient()
            ui.gradient_geometry.setCurrentIndex(1)
            ui.gradient_colors.setCurrentIndex(1)
            ui.gradient_opacity.setValue(42)
            ui.gradient_reverse.setChecked(True)
            self.assertEqual(canvas.tools.gradient_tool.geometry, 'radial')
            self.assertEqual(canvas.tools.gradient_tool.color_mode, 'color')
            self.assertEqual(canvas.tools.gradient_tool.opacity, .42)
            self.assertTrue(canvas.tools.gradient_tool.reverse)
            ui.gradient_geometry.setCurrentIndex(2)
            self.assertFalse(ui.gradient_spread.isEnabled())
            canvas.tools.set_brush()
            self.assertTrue(all(not action.isVisible() for action in ui._gradient_actions))
            canvas.set_brush_setting('size', 73.0)
            self.assertEqual(ui.toolbar_size.value(), 73)
            self.assertEqual(ui.toolbar_size_slider.value(), 73)
        finally:
            canvas.close()
            window.close()
            settings.clear()
            for key, value in saved.items():
                settings.setValue(key, value)

    def test_format_presets_remain_editable_and_ratio_swap_work(self):
        dialog = DocumentDialog(preset='a4')
        try:
            self.assertEqual(dialog.get_dimensions(), (2480, 3508))
            self.assertEqual(dialog.get_dpi(), 300)
            self.assertTrue(dialog.width_spin.isEnabled())
            self.assertIn('210.0 × 297.0 mm', dialog.estimate_label.text())
            dialog.swap_orientation()
            self.assertEqual(dialog.get_dimensions(), (3508, 2480))
            dialog.aspect_lock.setChecked(True)
            dialog.width_spin.setValue(1754)
            self.assertEqual(dialog.get_dimensions(), (1754, 1240))
            dialog.background_combo.setCurrentIndex(1)
            self.assertEqual(dialog.get_background(), 'transparent')
            self.assertEqual(dialog.preview.background, 'transparent')
            dialog.width_spin.setValue(20000)
            self.assertLessEqual(dialog.height_spin.value(), 20000)
            dialog.height_spin.setValue(20000)
            w, h = dialog.get_dimensions()
            self.assertAlmostEqual(w / h, 3508 / 2480, places=3)
        finally:
            dialog.close()

    def test_pixel_art_presets_are_preserved(self):
        dialog = DocumentDialog(pixel_art=True)
        try:
            dialog.tabs.setCurrentIndex(1)
            self.assertTrue(dialog.is_pixel())
            self.assertEqual(dialog.get_dimensions(), (32, 32))
            self.assertEqual(dialog.get_dpi(), 72)
            self.assertEqual(dialog.get_pixel_preset()['palette'], 'PICO-8')
        finally:
            dialog.close()

    def test_home_format_and_recent_signals_have_real_values(self):
        page = HomePage()
        formats, recent = [], []
        page.preset_requested.connect(formats.append)
        page.recent_document_requested.connect(recent.append)
        page.preset_buttons['a4'].click()
        self.assertEqual(formats, ['a4'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'painting.nebula'
            path.touch()
            page.set_recent_documents([str(path), str(path), str(path)+'missing'])
            self.assertEqual(page.recent_layout.count(), 1)
            page.recent_layout.itemAt(0).widget().click()
            self.assertEqual(recent, [str(path)])
        page.close()


if __name__ == '__main__':
    unittest.main()
