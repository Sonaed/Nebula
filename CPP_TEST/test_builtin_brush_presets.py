"""Factory brush presets (revision 3): behaviour, not just values."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QInputDevice, QPainter, QPointingDevice, QTabletEvent
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document
from TOOLS.brush_preset_manager import BrushPresetManager

APP = QApplication.instance() or QApplication([])
PEN = QPointingDevice(
    "nebula-preset-pen", 4343, QInputDevice.DeviceType.Stylus, QPointingDevice.PointerType.Pen,
    QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 2,
)


class BuiltinPresetValuesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = BrushPresetManager(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_glow_lightens_instead_of_multiplying(self):
        self.assertEqual(self.manager.load("Glow")["blendMode"], 2)  # Screen

    def test_blending_presets_move_paint(self):
        for name in ("Blender", "Smudge"):
            self.assertTrue(self.manager.load(name)["smudgeTool"], name)
        self.assertFalse(self.manager.load("Round Hard")["smudgeTool"])

    def test_english_factory_files_are_renamed_but_user_files_kept(self):
        import json
        directory = Path(self._tmp.name)
        french = self.manager.load("Glow")
        self.manager.preset_path("Glow").unlink()
        (directory / "Glow.json").write_text(json.dumps({**french, "name": "Glow"}), encoding="utf-8")
        (directory / "Pencil.json").write_text(json.dumps({"size": 3, "_legacy_builtin": True}), encoding="utf-8")
        migrated = BrushPresetManager(self._tmp.name)
        self.assertIn("Lueur", migrated.list_presets())
        self.assertFalse((directory / "Glow.json").exists())
        self.assertFalse((directory / "Pencil.json").exists())
        self.assertEqual(migrated.load("Pencil")["name"], "Crayon HB")

    def test_revision_two_factory_presets_are_upgraded_but_custom_ones_are_not(self):
        glow = self.manager.load("Glow")
        glow.update(blendMode=1, builtinRevision=2)
        self.manager._atomic_json_write(self.manager.preset_path("Glow"), glow)
        self.manager.save("My Glow", {**glow, "builtIn": False})
        upgraded = BrushPresetManager(self._tmp.name)
        self.assertEqual(upgraded.load("Glow")["blendMode"], 2)
        self.assertEqual(upgraded.load("My Glow")["blendMode"], 1)


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class BuiltinPresetCanvasTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(500, 300)
        self.canvas.set_document(Document(400, 200, 72, None))
        self.canvas.zoom, self.canvas.offset, self.canvas.view_rotation = 1.0, QPointF(0, 0), 0.0
        self.canvas.use_gpu = False
        self.canvas.tools.current_tool = "brush"

    def tearDown(self):
        self.canvas.close()

    def _stroke(self, y):
        button = Qt.MouseButton.LeftButton
        points = [(40 + i * 8, y) for i in range(40)]
        for index, (x, py) in enumerate(points):
            kind = (QTabletEvent.Type.TabletPress if index == 0 else
                    QTabletEvent.Type.TabletRelease if index == len(points) - 1 else
                    QTabletEvent.Type.TabletMove)
            p = QPointF(x, py)
            self.canvas.tabletEvent(QTabletEvent(
                kind, PEN, p, p, 1.0, 0, 0, 0, 0, 0, Qt.KeyboardModifier.NoModifier,
                Qt.MouseButton.NoButton if kind == QTabletEvent.Type.TabletMove else button,
                Qt.MouseButton.NoButton if kind == QTabletEvent.Type.TabletRelease else button))
        APP.processEvents()

    def _paint_block(self, colour, rect=(100, 60, 100, 80)):
        painter = QPainter(self.canvas.get_active_layer().image)
        painter.fillRect(*rect, QColor(*colour))
        painter.end()

    def test_smudge_drags_real_paint_and_never_invents_white(self):
        self._paint_block((200, 40, 40))
        self.assertTrue(self.canvas.load_cpp_brush_preset("Estompe"))
        self.canvas.set_brush_setting("size", 30.0)
        self._stroke(100)   # from x=40 across the block to x=352
        layer = self.canvas.get_active_layer().image
        dragged = QColor.fromRgba(layer.pixel(215, 100))   # just right of the block
        self.assertGreater(dragged.alpha(), 40)
        self.assertGreater(dragged.red(), dragged.green() + 60)   # red paint, not white
        before = QColor.fromRgba(layer.pixel(60, 100))           # transparent start stays clean
        self.assertTrue(before.alpha() < 10 or before.red() > before.green() + 60)

    def test_wet_oil_picks_up_the_colour_underneath(self):
        self._paint_block((200, 40, 40), (0, 0, 400, 200))
        self.assertTrue(self.canvas.load_cpp_brush_preset("Huile ronde"))
        self.canvas.set_brush_setting("color", (245, 245, 245, 255))
        self.canvas.set_brush_setting("size", 40.0)
        self._stroke(100)
        mixed = QColor.fromRgba(self.canvas.get_active_layer().image.pixel(300, 100))
        self.assertGreater(mixed.red(), 200)          # lighter than the red...
        self.assertGreater(mixed.green(), 60)
        self.assertLess(mixed.green(), 235)            # ...but not plain white: it mixed
        self.assertGreater(mixed.red() - mixed.green(), 8)

    def test_switching_preset_keeps_the_chosen_colour(self):
        self.canvas.set_brush_setting("color", (200, 30, 30, 255))
        self.assertTrue(self.canvas.load_cpp_brush_preset("Conte"))
        self.assertEqual(list(self.canvas.brush_settings.get("color"))[:3], [200, 30, 30])

    def test_eraser_preset_erases_from_the_brush_tool(self):
        layer = self.canvas.get_active_layer()
        painter = QPainter(layer.image)
        painter.fillRect(0, 0, 400, 200, QColor(30, 90, 200))
        painter.end()
        self.assertTrue(self.canvas.load_cpp_brush_preset("Eraser Hard"))
        self._stroke(100)
        self.assertLess(QColor.fromRgba(layer.image.pixel(200, 100)).alpha(), 30)


class PaintingShortcutTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.canvas.set_document(Document(100, 100, 72, None))

    def tearDown(self):
        self.canvas.close()

    def _key(self, key):
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        self.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    def test_brackets_resize_and_digits_set_opacity(self):
        self.canvas.set_brush_setting("size", 20.0)
        self._key(Qt.Key.Key_BracketRight)
        self.assertGreater(self.canvas.brush_settings.get("size"), 20.0)
        self._key(Qt.Key.Key_BracketLeft)
        self._key(Qt.Key.Key_BracketLeft)
        self.assertLess(self.canvas.brush_settings.get("size"), 20.0)
        self._key(Qt.Key.Key_4)
        self.assertAlmostEqual(self.canvas.brush_settings.get("opacity"), 0.4)
        self._key(Qt.Key.Key_0)
        self.assertAlmostEqual(self.canvas.brush_settings.get("opacity"), 1.0)

    def test_x_and_d_ask_for_colour_swap_and_reset(self):
        received = []
        self.canvas.color_shortcut_requested.connect(received.append)
        self._key(Qt.Key.Key_X)
        self._key(Qt.Key.Key_D)
        self.assertEqual(received, ["swap", "reset"])


if __name__ == "__main__":
    unittest.main()
