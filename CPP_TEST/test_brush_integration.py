from __future__ import annotations

import os
import tempfile
import unittest
import ctypes
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtGui import QInputDevice, QPointingDevice, QTabletEvent

from CANVAS.canvas import Canvas
from CORE.native_bridge import filter_brush_segment
from CPP_TEST.legacy_brush_reference import clone_segment, filter_segments


class BrushIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.canvas = Canvas()

    def tearDown(self) -> None:
        self.canvas.close()

    def test_canvas_requires_native_brush_engine(self) -> None:
        with patch("CANVAS.canvas.load_creative_core", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "BrushEngine"):
                Canvas()

    def test_tablet_pressure_keeps_previous_sample_for_native_segment(self) -> None:
        self.canvas.tools.brush.pressure = 0.12
        start, end = self.canvas._tablet_pressure_pair(0.78)
        self.assertAlmostEqual(start, 0.12)
        self.assertAlmostEqual(end, 0.78)
        self.assertAlmostEqual(self.canvas.tools.brush.pressure, 0.78)

    def test_synthetic_tablet_sequence_reaches_cpp_with_pressure_and_tilt(self) -> None:
        device = QPointingDevice(
            "XP-Pen synthetic", 28, QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Pen,
            QInputDevice.Capability.Position | QInputDevice.Capability.Pressure
            | QInputDevice.Capability.XTilt | QInputDevice.Capability.YTilt,
            1, 1,
        )
        calls = []
        original = self.canvas._cpp_draw_segment

        def capture(*args, **kwargs):
            if len(args) >= 7:
                calls.append((args[3], args[4], args[5], args[6]))
            return original(*args, **kwargs)

        with patch.object(self.canvas, "_cpp_draw_segment", side_effect=capture):
            events = (
                (QTabletEvent.Type.TabletPress, 0.20, 100, 100),
                (QTabletEvent.Type.TabletMove, 0.80, 120, 110),
                (QTabletEvent.Type.TabletRelease, 0.0, 120, 110),
            )
            for event_type, pressure, x, y in events:
                event = QTabletEvent(
                    event_type, device, QPointF(x, y), QPointF(x, y), pressure,
                    15.0, 16.0, 0.0, 0.0, 0.0,
                    Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton if pressure else Qt.MouseButton.NoButton,
                )
                self.canvas.tabletEvent(event)
                self.assertTrue(event.isAccepted())

        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][0], 0.20)
        self.assertAlmostEqual(calls[0][1], 0.80)
        self.assertEqual(calls[0][2:], ((15.0, 16.0), (15.0, 16.0)))

    def test_canonical_state_updates_cpp_and_python_fallback(self) -> None:
        self.canvas.set_brush_settings(
            {
                "size": 37.0,
                "opacity": 0.42,
                "wetness": 0.6,
                "pressureFlow": True,
            }
        )
        settings = self.canvas.get_cpp_brush_settings()
        self.assertEqual(settings["size"], 37.0)
        self.assertEqual(settings["wetness"], 0.6)
        self.assertTrue(settings["pressureFlow"])
        self.assertEqual(self.canvas.tools.brush.size, 37.0)
        self.assertEqual(self.canvas.tools.brush.opacity, 0.42)

    def test_json_preset_replaces_the_same_state(self) -> None:
        self.assertTrue(self.canvas.load_cpp_brush_preset("Ink"))
        settings = self.canvas.get_cpp_brush_settings()
        self.assertEqual(
            self.canvas.tools.brush.size,
            settings["size"],
        )
        self.assertEqual(
            self.canvas.get_cpp_brush_preset_name(),
            "Ink",
        )

    def test_picker_samples_visible_composite(self) -> None:
        layer = self.canvas.document.get_active_layer()
        self.assertIsNotNone(layer)
        layer.image.fill(QColor(18, 92, 177, 255))
        color = self.canvas.sample_composite_color(QPoint(10, 10))
        self.assertIsNotNone(color)
        self.assertEqual(
            self.canvas.get_cpp_brush_settings()["color"],
            [18, 92, 177, 255],
        )

    def test_picker_reads_one_tile_without_materializing_the_layer(self) -> None:
        layer = self.canvas.document.get_active_layer()
        tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        tile.fill(QColor(24, 132, 208, 255))
        layer.tile_store.set_tile(0, 0, tile)
        layer.discard_image_cache()

        color = self.canvas.sample_composite_color(QPoint(13, 21))

        self.assertEqual(color, QColor(24, 132, 208, 255))
        self.assertIsNone(layer._image_cache)

    def test_picker_resumes_after_async_scratch_read(self) -> None:
        layer = self.canvas.document.get_active_layer()
        with tempfile.TemporaryDirectory() as directory:
            layer.tile_store.set_scratch_directory(directory)
            tile = QImage(64, 64, QImage.Format.Format_ARGB32)
            tile.fill(QColor(170, 65, 31, 255))
            layer.tile_store.set_tile(0, 0, tile)
            layer.discard_image_cache()
            layer.tile_store.evict_tile_to_scratch(0, 0)
            sampled = []
            loop = QEventLoop()
            self.canvas.color_sampled.connect(lambda color: (sampled.append(color), loop.quit()))

            self.assertIsNone(self.canvas.sample_composite_color(QPoint(5, 7)))
            QTimer.singleShot(3000, loop.quit)
            loop.exec()

            self.assertEqual(sampled, [QColor(170, 65, 31, 255)])

    def test_alpha_locked_stroke_uses_sparse_history_tiles_as_its_baseline(self) -> None:
        layer = self.canvas.document.get_active_layer()
        layer.image.fill(QColor(18, 54, 96, 80))
        layer.lock_alpha = True
        self.canvas.set_brush_settings({
            "size": 18.0, "hardness": 1.0, "opacity": 1.0, "flow": 1.0,
            "color": [240, 30, 20, 255],
        })
        self.canvas.begin_stroke_history()
        self.canvas.canvas_brush_begin_stroke()
        self.assertIs(self.canvas._alpha_lock_snapshot, True)
        image = self.canvas._cpp_begin_stroke(layer.image, QPoint(64, 64), 1.0)
        self.assertIsNotNone(image)
        dirty = self.canvas._brush_dirty_rect(QPoint(64, 64), QPoint(64, 64))
        image = self.canvas._restore_locked_alpha(image, dirty)
        layer.image = image
        self.canvas.tile_history.mark_dirty(layer, dirty)
        self.assertGreaterEqual(len(self.canvas.tile_history._pending["before_tiles"]), 4)
        self.assertEqual(layer.image.pixelColor(64, 64).alpha(), 80)

        self.assertGreater(layer.image.pixelColor(64, 64).red(), 18)
        self.canvas._cpp_end_stroke()
        self.canvas.commit_stroke_history()
        self.canvas.canvas_brush_end_stroke()
        self.assertTrue(self.canvas.tile_history.undo(self.canvas.document))
        self.assertEqual(layer.image.pixelColor(64, 64), QColor(18, 54, 96, 80))
        self.assertTrue(self.canvas.tile_history.redo(self.canvas.document))
        self.assertEqual(layer.image.pixelColor(64, 64).alpha(), 80)

    def test_stroke_history_does_not_materialize_the_full_layer(self) -> None:
        layer = self.canvas.document.get_active_layer()
        with patch.object(layer.tile_store, "materialize",
                          side_effect=AssertionError("stroke history materialized layer")):
            self.canvas.begin_stroke_history()
            self.canvas.cancel_history_action()
        self.assertEqual(self.canvas._stroke_image_format, layer.tile_store.image_format)

    def test_smudge_uses_dedicated_cpp_mode(self) -> None:
        self.assertTrue(self.canvas.cpp_brush_enabled)
        self.assertTrue(
            hasattr(self.canvas.cpp_brush_library, "cs_brush_set_smudge_tool")
        )
        self.canvas.tools.set_smudge()
        self.canvas.set_brush_settings({
            "size": 18.0,
            "opacity": 1.0,
            "flow": 1.0,
            "smudge": 1.0,
            "colorCarry": 1.0,
        })
        self.assertEqual(self.canvas.tools.current_tool, "smudge")

        image = QImage(128, 32, QImage.Format.Format_RGBA8888)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(
                    x,
                    y,
                    QColor(220, 30, 30) if x < 64 else QColor(30, 50, 220),
                )

        image = self.canvas._cpp_begin_stroke(image, QPoint(35, 16), 1.0)
        image = self.canvas._cpp_draw_segment(
            image, QPoint(35, 16), QPoint(95, 16), 1.0, 1.0
        )
        self.canvas._cpp_end_stroke()

        self.assertGreater(image.pixelColor(75, 16).red(), 150)
        self.assertLess(image.pixelColor(75, 16).blue(), 100)

    def test_clone_stamp_samples_source_and_uses_cpp_brush(self) -> None:
        self.assertTrue(self.canvas.cpp_brush_enabled)
        self.canvas.tools.set_clone_stamp()
        self.canvas.set_brush_settings({
            "size": 12.0,
            "hardness": 1.0,
            "opacity": 1.0,
            "flow": 1.0,
            "spacing": 0.1,
            "color": [20, 20, 230, 255],
        })
        target = QImage(96, 48, QImage.Format.Format_RGBA8888)
        target.fill(QColor(0, 0, 0, 0))
        source = QImage(96, 48, QImage.Format.Format_RGBA8888)
        source.fill(QColor(220, 25, 35, 255))
        self.canvas._sync_cpp_brush()
        self.canvas.cpp_brush_library.cs_brush_begin_stroke(
            self.canvas.cpp_brush, 30.0, 24.0, 1.0
        )
        result = self.canvas._cpp_draw_segment(
            target, QPoint(30, 24), QPoint(30, 24), 1.0, 1.0,
            clone_source=source, clone_offset=QPoint(30, 0),
        )
        self.canvas._cpp_end_stroke()
        self.assertIsNotNone(result)
        color = result.pixelColor(30, 24)
        self.assertGreater(color.alpha(), 240)
        self.assertGreater(color.red(), 180)
        self.assertLess(color.blue(), 80)

    def test_clone_stamp_cpu_fallback_copies_source_pixels(self) -> None:
        self.canvas.set_brush_settings({
            "size": 12.0, "hardness": 1.0, "opacity": 1.0,
            "flow": 1.0, "spacing": 0.1,
        })
        target = QImage(96, 48, QImage.Format.Format_RGBA8888)
        target.fill(QColor(0, 0, 0, 0))
        source = QImage(96, 48, QImage.Format.Format_RGBA8888)
        source.fill(QColor(220, 25, 35, 255))
        result = clone_segment(target, source, QPoint(30, 0),
                               self.canvas.brush_settings.snapshot(),
                               QPoint(30, 24), QPoint(30, 24))
        color = result.pixelColor(30, 24)
        self.assertGreater(color.alpha(), 240)
        self.assertGreater(color.red(), 180)
        self.assertLess(color.blue(), 80)

    def test_blur_and_sharpen_filter_only_the_local_brush_area(self) -> None:
        layer = self.canvas.document.get_active_layer()
        self.assertIsNotNone(layer)
        self.canvas.document.width, self.canvas.document.height = 48, 24
        image = QImage(48, 24, QImage.Format.Format_RGBA8888)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(0, 0, 0) if x < 24 else QColor(255, 255, 255))
        layer.image = image
        self.canvas.set_brush_settings({"size": 10, "spacing": 0.2, "opacity": 1, "flow": 1})
        self.canvas.begin_stroke_history()
        self.canvas.canvas_brush_begin_stroke()
        layer.image = self.canvas._apply_filter_segment(
            layer.image, QPoint(24, 12), QPoint(24, 12), 1, 1, False
        )
        self.canvas.commit_stroke_history()
        self.canvas.canvas_brush_end_stroke()
        blurred_left = layer.image.pixelColor(23, 12).red()
        blurred_right = layer.image.pixelColor(24, 12).red()
        self.assertGreater(blurred_left, 0)
        self.assertLess(blurred_right, 255)
        self.assertEqual(layer.image.pixelColor(5, 12).red(), 0)

        image = QImage(48, 24, QImage.Format.Format_RGBA8888)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(100, 100, 100) if x < 24 else QColor(150, 150, 150))
        layer.image = image
        self.canvas.begin_stroke_history()
        self.canvas.canvas_brush_begin_stroke()
        layer.image = self.canvas._apply_filter_segment(
            layer.image, QPoint(24, 12), QPoint(24, 12), 1, 1, True
        )
        self.canvas.commit_stroke_history()
        self.canvas.canvas_brush_end_stroke()
        self.assertLess(layer.image.pixelColor(23, 12).red(), 100)
        self.assertGreater(layer.image.pixelColor(24, 12).red(), 150)

    def test_filter_never_falls_back_to_python_when_native_is_unavailable(self) -> None:
        layer = self.canvas.document.get_active_layer()
        self.assertIsNotNone(layer)
        image = QImage(48, 24, QImage.Format.Format_RGBA8888)
        image.fill(QColor(96, 128, 160, 255))
        layer.image = image
        before = image.copy()
        with patch("CANVAS.canvas.filter_brush_segment", return_value=None):
            result = self.canvas._apply_filter_segment(
                layer.image, QPoint(24, 12), QPoint(24, 12), 1.0, 1.0, False
            )
        self.assertEqual(result.size(), before.size())
        self.assertEqual(layer.image.size(), before.size())
        for y in range(before.height()):
            for x in range(before.width()):
                self.assertEqual(layer.image.pixelColor(x, y), before.pixelColor(x, y))

    def test_cpp_brush_filter_matches_python_reference_at_edges(self) -> None:
        self.assertTrue(self.canvas.cpp_brush_enabled)
        source = QImage(36, 28, QImage.Format.Format_RGBA8888)
        for y in range(source.height()):
            for x in range(source.width()):
                source.setPixelColor(x, y, QColor((x * 37) % 256,
                                                   (y * 53) % 256,
                                                   (x * 17 + y * 29) % 256,
                                                   (x * 23 + y * 31) % 256))
        settings = {"size": 13.0, "spacing": 0.19,
                    "opacity": 0.73, "flow": 0.81}
        start, end = QPoint(1, 1), QPoint(33, 25)
        for sharpen in (False, True):
            with self.subTest(sharpen=sharpen):
                native = source.copy()
                self.assertTrue(filter_brush_segment(
                    native, float(start.x()), float(start.y()), 0.18,
                    float(end.x()), float(end.y()), 0.94, settings["size"],
                    settings["spacing"], settings["opacity"] * settings["flow"],
                    sharpen,
                ))
                reference = source.copy()
                filter_segments(
                    reference, [(start, end)], settings, 0.18, 0.94, sharpen
                )
                maximum_delta = max(
                    abs(a - b)
                    for y in range(native.height()) for x in range(native.width())
                    for a, b in zip(native.pixelColor(x, y).getRgb(),
                                    reference.pixelColor(x, y).getRgb())
                )
                self.assertLessEqual(maximum_delta, 1)

    def test_bezier_curve_commits_with_the_active_cpp_brush(self) -> None:
        layer = self.canvas.document.get_active_layer()
        self.assertIsNotNone(layer)
        self.canvas.document.width, self.canvas.document.height = 80, 60
        layer.image = QImage(80, 60, QImage.Format.Format_RGBA8888)
        layer.image.fill(QColor(0, 0, 0, 0))
        self.canvas.set_brush_settings({
            "size": 7, "hardness": 1, "spacing": 0.12,
            "color": [210, 35, 50, 255],
        })
        from PySide6.QtCore import QPointF
        self.canvas.bezier_start = QPointF(5, 30)
        self.canvas.bezier_control1 = QPointF(20, 0)
        self.canvas.bezier_control2 = QPointF(60, 60)
        self.canvas.bezier_end = QPointF(75, 30)
        self.canvas._commit_bezier_curve()
        painted = sum(
            layer.image.pixelColor(x, y).alpha() > 0
            for y in range(60) for x in range(80)
        )
        self.assertGreater(painted, 100)

    def test_line_preview_uses_cpp_brush_backend(self) -> None:
        layer = self.canvas.document.get_active_layer()
        self.assertIsNotNone(layer)
        layer.image = QImage(64, 64, QImage.Format.Format_RGBA8888)
        layer.image.fill(0)
        self.canvas.tools.set_line()
        self.canvas.set_brush_settings({
            "size": 5.0,
            "hardness": 1.0,
            "color": [210, 30, 40, 255],
        })
        self.canvas.shape_original = layer.image.copy()
        self.canvas.shape_start = QPoint(5, 32)

        self.canvas._preview_brush_shape(QPoint(58, 32))

        self.assertGreater(layer.image.pixelColor(32, 32).alpha(), 0)
        self.assertGreater(layer.image.pixelColor(32, 32).red(), 150)

    def test_cpp_brush_symmetry_mirrors_the_stroke(self) -> None:
        image = QImage(800, 600, QImage.Format.Format_RGBA8888)
        image.fill(0)
        self.canvas.set_brush_settings({
            "size": 9.0,
            "hardness": 1.0,
            "opacity": 1.0,
            "flow": 1.0,
            "color": [220, 40, 30, 255],
        })
        self.canvas.symmetry_horizontal = True

        image = self.canvas._cpp_begin_stroke(image, QPoint(20, 32), 1.0)
        image = self.canvas._cpp_draw_segment(
            image, QPoint(20, 32), QPoint(30, 32), 1.0, 1.0
        )
        self.canvas._cpp_end_stroke()

        self.assertGreater(image.pixelColor(25, 32).alpha(), 0)
        self.assertGreater(image.pixelColor(774, 32).alpha(), 0)

    def test_stylus_stroke_keeps_one_contiguous_buffer_across_repaints(self) -> None:
        if not self.canvas.cpp_brush_enabled:
            self.skipTest("CreativeCore bridge is unavailable")
        layer = self.canvas.document.get_active_layer()
        self.canvas.document.width = self.canvas.document.height = 128
        layer.image = QImage(128, 128, QImage.Format.Format_ARGB32)
        layer.image.fill(QColor(0, 0, 0, 0))
        self.canvas.set_brush_settings({
            "size": 8.0, "hardness": 1.0, "flow": 1.0,
            "color": [220, 35, 50, 255],
        })
        self.canvas.begin_stroke_history()
        self.canvas.drawing = True

        # TabletPress installs this converted buffer once. Repaint/segment
        # cycles must not materialize the full layer again.
        converted = self.canvas._cpp_begin_stroke(layer.image, QPoint(10, 20), 1.0)
        layer.adopt_image_cache(converted)
        self.canvas.sync_gpu_layer(self.canvas._brush_dirty_rect(QPoint(10, 20), QPoint(10, 20)))
        image_buffer = layer._image_cache
        calls = {"materialize": 0}
        dirty_writes = []
        original_materialize = layer.tile_store.materialize
        original_write_image = layer.tile_store.write_image

        def count_materialize():
            calls["materialize"] += 1
            return original_materialize()

        def record_write(image, rect=None):
            dirty_writes.append(None if rect is None else (rect.width(), rect.height()))
            return original_write_image(image, rect)

        layer.tile_store.materialize = count_materialize
        layer.tile_store.write_image = record_write
        for x in range(11, 41):
            self.canvas._commit_layer_cache_for_render(
                layer, self.canvas.document.active_layer_index
            )
            image = self.canvas.get_active_image()
            self.assertIs(image, image_buffer)
            self.canvas._cpp_draw_segment(
                image, QPoint(x - 1, 20), QPoint(x, 20), 1.0, 1.0
            )
            dirty = self.canvas._brush_dirty_rect(QPoint(x - 1, 20), QPoint(x, 20))
            self.canvas.sync_gpu_layer(dirty)

        self.assertEqual(calls["materialize"], 0)
        self.assertTrue(dirty_writes)
        self.assertTrue(all(rect is not None and rect[0] * rect[1] < 128 * 128
                            for rect in dirty_writes))
        self.assertIs(layer._image_cache, image_buffer)
        self.canvas._cpp_end_stroke()
        self.canvas.drawing = False
        self.canvas.commit_stroke_history()
        tile = layer.tile_store.tile(0, 0)
        self.assertGreater(tile.pixelColor(20, 20).alpha(), 0)
        self.canvas.undo()
        self.assertEqual(layer.tile_store.tile(0, 0).pixelColor(20, 20).alpha(), 0)
        self.canvas.redo()
        self.assertGreater(layer.tile_store.tile(0, 0).pixelColor(20, 20).alpha(), 0)


    def test_native_smoothing_filters_input_and_resets_at_stroke_end(self) -> None:
        if not self.canvas.cpp_brush_enabled:
            self.skipTest("CreativeCore natif indisponible")
        library = self.canvas.cpp_brush_library
        handle = self.canvas.cpp_brush
        library.cs_brush_set_smoothing(handle, 1.0)
        x, y = ctypes.c_float(), ctypes.c_float()
        smooth = library.cs_brush_smooth_point
        smooth(handle, 0.0, 0.0, ctypes.byref(x), ctypes.byref(y))
        smooth(handle, 10.0, 0.0, ctypes.byref(x), ctypes.byref(y))
        self.assertGreater(x.value, 0.0)
        self.assertLess(x.value, 10.0)
        library.cs_brush_end_stroke(handle)
        smooth(handle, 7.0, 4.0, ctypes.byref(x), ctypes.byref(y))
        self.assertAlmostEqual(x.value, 7.0)
        self.assertAlmostEqual(y.value, 4.0)

    def test_canvas_routes_stabilized_brush_points_to_cpp_rendering(self) -> None:
        if not self.canvas.cpp_brush_enabled:
            self.skipTest("CreativeCore natif indisponible")
        layer = self.canvas.document.get_active_layer()
        layer.image.fill(QColor(0, 0, 0, 0))
        self.canvas.set_brush_settings({
            "size": 6.0, "hardness": 1.0, "opacity": 1.0, "flow": 1.0,
            "color": [240, 30, 20, 255],
        })
        self.canvas.tools.brush.set_smoothing(1.0)
        image = self.canvas._cpp_begin_stroke(layer.image, QPoint(100, 100), 1.0)
        image = self.canvas._cpp_draw_segment(
            image, QPoint(100, 100), QPoint(300, 100), 1.0, 1.0,
            stabilize=True,
        )
        self.assertGreater(image.pixelColor(210, 100).alpha(), 0)
        self.assertEqual(image.pixelColor(300, 100).alpha(), 0)
        self.canvas._cpp_end_stroke()


if __name__ == "__main__":
    unittest.main()
