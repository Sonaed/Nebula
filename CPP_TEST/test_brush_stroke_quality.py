"""Stroke-quality regressions for the CreativeCore brush (Nebula 26.4.0).

These drive real tablet events through the Canvas so the whole pipeline is
covered: input mapping, stabilizer, Python segment plumbing and the native
stroke buffer.
"""
import math
import os
import sys
import time
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QInputDevice, QPointingDevice, QMouseEvent, QTabletEvent
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CORE.native_bridge import load_creative_core
from DOCUMENTS.document import Document
from TOOLS.brush_smoothing import BrushSmoothing
from TOOLS.cpp_brush_presets import CppBrushPresetApplier
from TOOLS.brush_settings_state import BrushSettingsState

APP = QApplication.instance() or QApplication([])
PEN = QPointingDevice(
    "nebula-test-pen", 4242, QInputDevice.DeviceType.Stylus, QPointingDevice.PointerType.Pen,
    QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 2,
)


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class BrushStrokeQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canvas = Canvas()
        self.canvas.resize(500, 400)
        self.canvas.set_document(Document(400, 300, 72, None))
        self.canvas.zoom = 1.0
        self.canvas.offset = QPointF(0.0, 0.0)
        self.canvas.view_rotation = 0.0
        self.canvas.use_gpu = False
        self.canvas.tools.current_tool = "brush"
        for key, value in {
            "size": 24.0, "opacity": 1.0, "flow": 1.0, "hardness": 1.0,
            "spacing": 0.08, "color": (20, 40, 200, 255),
            "pressureSize": False, "pressureOpacity": False, "pressureFlow": False,
            "sizeJitter": 0.0, "scatter": 0.0,
        }.items():
            self.canvas.set_brush_setting(key, value)
        self.canvas.tools.brush.set_smoothing(0.0)

    def tearDown(self) -> None:
        self.canvas.close()

    # -- helpers ---------------------------------------------------------
    def _event(self, kind, x, y, pressure=1.0):
        types = {"press": QTabletEvent.Type.TabletPress, "move": QTabletEvent.Type.TabletMove,
                 "release": QTabletEvent.Type.TabletRelease}
        point = QPointF(x, y)
        button = Qt.MouseButton.LeftButton
        self.canvas.tabletEvent(QTabletEvent(
            types[kind], PEN, point, point, pressure, 0.0, 0.0, 0.0, 0.0, 0.0,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseButton.NoButton if kind == "move" else button,
            Qt.MouseButton.NoButton if kind == "release" else button,
        ))

    def _stroke(self, points, pressures=None):
        pressures = pressures or [1.0] * len(points)
        self._event("press", *points[0], pressures[0])
        for (x, y), pressure in zip(points[1:], pressures[1:]):
            self._event("move", x, y, pressure)
        self._event("release", *points[-1], pressures[-1])
        APP.processEvents()

    def _alpha(self, x, y) -> int:
        return QColor.fromRgba(self.canvas.get_active_layer().image.pixel(x, y)).alpha()

    def _max_alpha(self) -> int:
        image = self.canvas.get_active_layer().image.convertToFormat(QImage.Format.Format_ARGB32)
        return max(QColor.fromRgba(image.pixel(x, y)).alpha()
                   for y in range(0, image.height(), 2) for x in range(0, image.width(), 2))

    def _wait_async(self):
        deadline = time.monotonic() + 5.0
        while (self.canvas._async_brush_handle is not None
               or self.canvas._async_tablet_events) and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.001)
        self.assertIsNone(self.canvas._async_brush_handle, "native brush did not finish")
        self.assertFalse(self.canvas._async_tablet_events, "queued strokes did not finish")

    def _rapid_line(self, y):
        self._event("press", 30, y)
        for x in range(33, 361, 3):
            self._event("move", x, y)
        self._event("release", 360, y)

    def test_dynamic_brush_controls_reach_native_preset_applier(self) -> None:
        """Controls in the Dynamics tab must not be saved-only settings."""
        calls = []

        expected_names = {
            "cs_brush_set_tilt_follow", "cs_brush_set_tilt_elongation",
            "cs_brush_set_tilt_size", "cs_brush_set_tilt_opacity",
            "cs_brush_set_random_size", "cs_brush_set_random_opacity",
            "cs_brush_set_velocity_spacing", "cs_brush_set_antialiasing",
            "cs_brush_set_wrap_around",
        }

        class RecordingBridge:
            def __getattr__(self, name):
                def record(*args):
                    if name in expected_names:
                        calls.append((name, args[0], args[1].value))
                return record

        state = BrushSettingsState()
        state.update({
            "tiltFollow": 0.8,
            "tiltElongation": 0.5,
            "tiltSize": 0.7,
            "tiltOpacity": 0.4,
            "randomSize": 0.3,
            "randomOpacity": 0.2,
            "velocitySpacing": 0.6,
            "antialiasing": False,
            "wrapAround": True,
        })
        self.assertAlmostEqual(state.get("tiltFollow"), 0.8)
        self.assertAlmostEqual(state.get("tiltElongation"), 0.5)
        self.assertFalse(state.get("antialiasing"))
        self.assertTrue(state.get("wrapAround"))
        applier = CppBrushPresetApplier(RecordingBridge(), 123)
        applier.apply(state.snapshot())
        applied = {name: value for name, _handle, value in calls}
        expected = {
            "cs_brush_set_tilt_follow": 0.8,
            "cs_brush_set_tilt_elongation": 0.5,
            "cs_brush_set_tilt_size": 0.7,
            "cs_brush_set_tilt_opacity": 0.4,
            "cs_brush_set_random_size": 0.3,
            "cs_brush_set_random_opacity": 0.2,
            "cs_brush_set_velocity_spacing": 0.6,
            "cs_brush_set_antialiasing": 0,
            "cs_brush_set_wrap_around": 1,
        }
        self.assertEqual(set(applied), set(expected))
        for name, value in expected.items():
            self.assertAlmostEqual(applied[name], value)

    # -- tests -----------------------------------------------------------
    def test_overlapping_stroke_never_exceeds_brush_opacity(self) -> None:
        self.canvas.set_brush_setting("opacity", 0.4)
        there = [(40 + i * 2.0, 150.0) for i in range(120)]
        back = [(280 - i * 2.0, 152.0) for i in range(120)]
        self._stroke(there + back)
        self.assertLessEqual(abs(self._max_alpha() - round(0.4 * 255)), 1)

    def test_pressure_opacity_light_pass_never_lightens_heavy_paint(self) -> None:
        self.canvas.set_brush_setting("pressureOpacity", True)
        self._stroke([(60 + i * 2.0, 150.0) for i in range(100)], [1.0] * 100)
        heavy = self._alpha(150, 150)
        self._stroke([(60 + i * 2.0, 150.0) for i in range(100)], [0.2] * 100)
        self.assertGreaterEqual(self._alpha(150, 150), heavy)

    def test_hard_eraser_uses_brush_hardness_and_caps_at_its_opacity(self) -> None:
        self.canvas.set_brush_setting("size", 60.0)
        self._stroke([(40 + i * 3.0, 150.0) for i in range(100)])  # opaque band
        self.canvas.tools.current_tool = "eraser"
        self.canvas.set_brush_setting("size", 24.0)
        self.canvas.set_brush_setting("hardness", 1.0)
        self.canvas.set_brush_setting("opacity", 1.0)
        self._stroke([(200.0, 100 + i * 2.0) for i in range(50)])
        # Hard eraser: the whole core of the dab is fully removed, not just
        # the exact centre pixel (the old cone falloff left a soft ramp).
        self.assertEqual(self._alpha(200, 150), 0)
        self.assertEqual(self._alpha(208, 150), 0)
        self.canvas.set_brush_setting("opacity", 0.5)
        self._stroke([(100.0, 100 + i * 1.0) for i in range(100)] +
                     [(100.0, 200 - i * 1.0) for i in range(100)])
        self.assertLessEqual(abs(self._alpha(100, 150) - 128), 2)

    def test_brush_positions_keep_sub_pixel_precision(self) -> None:
        self.canvas.set_brush_setting("size", 6.0)
        self._stroke([(110.0, 100.0), (110.0, 100.0)])
        self._stroke([(110.0, 200.4), (110.0, 200.4)])
        # A dab 0.4 px lower must move its anti-aliased edge accordingly
        # instead of snapping back onto the pixel grid.
        self.assertEqual(self._alpha(110, 103), 0)
        self.assertGreater(self._alpha(110, 203), 60)

    def test_hard_tip_edge_is_antialiased_on_both_sides_of_the_radius(self) -> None:
        self.canvas.set_brush_setting("size", 6.0)
        self._stroke([(110.0, 100.5), (110.0, 100.5)])
        top, bottom = self._alpha(110, 97), self._alpha(110, 103)
        # Centre on a half pixel: rows 97 and 103 sit exactly on the radius
        # and must both receive partial (not zero) coverage, symmetrically.
        self.assertGreater(top, 60)
        self.assertLess(top, 250)
        self.assertLessEqual(abs(top - bottom), 2)

    def test_stabilizer_slider_survives_stroke_start(self) -> None:
        self.canvas.tools.brush.set_smoothing(0.6)
        self._stroke([(40.0, 40.0), (60.0, 40.0)])
        self.assertAlmostEqual(self.canvas.tools.brush.smoothing, 0.6)

    def test_stabilizer_mode_is_restored_from_the_brush_state(self) -> None:
        brush = self.canvas.tools.brush
        brush.set_smoothing(0.65)
        self.canvas.set_brush_setting("smoothMode", 2)
        self.assertEqual(brush.smoothing_mode, "weighted")
        self.assertEqual(brush.smoother.mode, "weighted")
        self.assertAlmostEqual(brush.smoother.strength, 0.65)
        self.canvas.set_brush_setting("smoothMode", 0)
        self.assertEqual(brush.smoothing_mode, "none")
        self.assertEqual(brush.smoother.mode, "basic")
        self.assertEqual(brush.smoother.strength, 0.0)
        # The amount is preserved: returning to Inertie restores the feel the
        # artist set, instead of silently resetting it.
        self.canvas.set_brush_setting("smoothMode", 1)
        self.assertAlmostEqual(brush.smoother.strength, 0.65)

    def test_weighted_stabilizer_changes_the_actual_canvas_input_path(self) -> None:
        brush = self.canvas.tools.brush
        brush.set_smoothing(0.8)
        self.canvas.set_brush_setting("smoothMode", 2)
        brush.begin_stroke()
        self.canvas._cpp_smooth_native_point(QPointF(30, 100).toPoint())
        weighted = self.canvas._cpp_smooth_native_point(QPointF(230, 100).toPoint())
        self.assertGreater(weighted.x(), 30)
        self.assertLess(weighted.x(), 230)
        self.canvas.set_brush_setting("smoothMode", 0)
        brush.begin_stroke()
        self.canvas._cpp_smooth_native_point(QPointF(30, 100).toPoint())
        direct = self.canvas._cpp_smooth_native_point(QPointF(230, 100).toPoint())
        self.assertEqual(direct, QPointF(230, 100))

    def test_delayed_stabilizer_tail_moves_only_toward_pen_lift(self) -> None:
        smoother = BrushSmoothing(strength=0.85, buffer_size=4, mode="stabilize")
        smoother.begin_stroke()
        emitted = [smoother.add_point(QPointF(x, 100)) for x in (10, 35, 65, 105, 150)]
        tail = smoother.flush_tail()
        path = emitted[-1:] + tail
        self.assertTrue(tail)
        self.assertTrue(all(b.x() >= a.x() - 1e-4 for a, b in zip(path, path[1:])))
        self.assertLessEqual(path[-1].x(), 150)

    def test_shift_line_helper_is_one_undoable_precise_stroke(self) -> None:
        layer = self.canvas.get_active_layer()
        self.assertTrue(self.canvas._paint_straight_paint_segment(
            layer, QPointF(30, 150), QPointF(360, 150)))
        self.assertGreater(self._alpha(200, 150), 240)
        self.assertEqual(self.canvas.tile_history.index, 1)
        self.canvas.undo()
        self.assertEqual(self._alpha(200, 150), 0)
        self.canvas.redo()
        self.assertGreater(self._alpha(200, 150), 240)

    def test_shift_click_routes_to_straight_line_gesture(self) -> None:
        self.canvas.zoom = 1.0
        self.canvas.offset = QPointF(0, 0)

        def mouse(kind, x, y, modifiers=Qt.KeyboardModifier.NoModifier):
            button = (Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove
                      else Qt.MouseButton.NoButton)
            buttons = (Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease
                       else Qt.MouseButton.LeftButton)
            event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, modifiers)
            {QEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
             QEvent.Type.MouseButtonRelease: self.canvas.mouseReleaseEvent}[kind](event)

        mouse(QEvent.Type.MouseButtonPress, 30, 150)
        mouse(QEvent.Type.MouseButtonRelease, 30, 150)
        mouse(QEvent.Type.MouseButtonPress, 360, 150, Qt.KeyboardModifier.ShiftModifier)
        self.assertFalse(self.canvas.drawing)
        self.assertGreater(self._alpha(200, 150), 240)
        self.assertEqual(self.canvas.tile_history.index, 2)

    def test_stabilized_stroke_reaches_the_pen_lift_point(self) -> None:
        self.canvas.tools.brush.set_smoothing(0.9)
        self.canvas.set_brush_setting("size", 8.0)
        self._stroke([(40 + i * 6.0, 150.0) for i in range(50)])
        self.assertGreater(self._alpha(334, 150), 200)


    def test_sparse_pen_samples_draw_a_curve_not_a_polyline(self) -> None:
        # Four samples of a fast zig-zag.  Between (150,50) and (250,150) the
        # Catmull-Rom curve passes near (175,66); the straight chord passes
        # through (175,75).  A 4 px brush can only reach (175,66) on the curve.
        self.canvas.set_brush_setting("size", 4.0)
        self._stroke([(50, 150), (150, 50), (250, 150), (350, 50)])
        self.assertGreater(self._alpha(175, 66), 100)
        self.assertLess(self._alpha(175, 75), 60)


    def test_fast_hatching_keeps_every_async_stroke_whole(self) -> None:
        # Pen lifted and put down again immediately: the previous stroke's
        # worker is still rendering its tail.  It used to be cancelled, so
        # every stroke but the last lost its end.
        self.canvas.use_gpu = True
        self.canvas.set_brush_setting("size", 40.0)
        self.canvas.set_brush_setting("spacing", 0.02)
        rows = (60, 120, 180, 240)
        for y in rows:
            points = [(30 + i * 3, y) for i in range(110)]
            self._event("press", *points[0])
            for x, py in points[1:]:
                self._event("move", x, py)
            self._event("release", *points[-1])   # no event processing in between
        self._wait_async()
        for y in rows:
            self.assertGreater(self._alpha(340, y), 200, f"stroke at y={y} lost its end")

    def test_fast_async_strokes_have_separate_complete_undo_entries(self) -> None:
        self.canvas.use_gpu = True
        rows = (60, 120, 180, 240)
        for y in rows:
            self._rapid_line(y)
        self._wait_async()
        self.assertEqual(self.canvas.tile_history.index, len(rows))
        for i in reversed(range(len(rows))):
            self.canvas.undo()
            for j, y in enumerate(rows):
                self.assertEqual(self._alpha(340, y), 255 if j < i else 0)
        for i in range(len(rows)):
            self.canvas.redo()
            for j, y in enumerate(rows):
                self.assertEqual(self._alpha(340, y), 255 if j <= i else 0)

    def test_queued_strokes_keep_color_and_compose_over_prior_strokes(self) -> None:
        self.canvas.use_gpu = True
        self.canvas.set_brush_setting("opacity", 0.5)
        self.canvas.set_brush_setting("color", (255, 0, 0, 255))
        self._rapid_line(150)
        self.canvas.set_brush_setting("color", (0, 0, 255, 255))
        self._rapid_line(150)
        self.canvas.set_brush_setting("color", (0, 255, 0, 255))
        # Simulate a changed view while the two queued strokes finish.
        self.canvas.zoom = 0.5
        self.canvas.offset = QPointF(50, 30)
        self._wait_async()
        color = self.canvas.get_active_layer().image.pixelColor(340, 150)
        self.assertAlmostEqual(color.alpha(), 192, delta=2)
        self.assertAlmostEqual(color.red(), 85, delta=2)
        self.assertEqual(color.green(), 0)
        self.assertAlmostEqual(color.blue(), 170, delta=2)
        self.assertEqual(self.canvas.brush_settings.peek("color"), (0, 255, 0, 255))
        self.assertEqual(self.canvas.offset, QPointF(50, 30))
        self.assertEqual(self.canvas.zoom, 0.5)

    def test_queued_strokes_keep_their_target_layer(self) -> None:
        from DOCUMENTS.layer_manager import LayerManager
        self.canvas.use_gpu = True
        first = self.canvas.get_active_layer()
        second = LayerManager(self.canvas.document).add_layer("Second")
        self.canvas.document.set_active_layer(0)
        self.canvas._reset_history()
        self._rapid_line(60)
        self.canvas.document.set_active_layer(1)
        self._rapid_line(180)
        self.canvas.document.set_active_layer(0)
        self._wait_async()
        self.assertEqual(first.image.pixelColor(340, 60).alpha(), 255)
        self.assertEqual(first.image.pixelColor(340, 180).alpha(), 0)
        self.assertEqual(second.image.pixelColor(340, 180).alpha(), 255)
        self.assertEqual(second.image.pixelColor(340, 60).alpha(), 0)
        self.assertEqual(self.canvas.document.active_layer_index, 0)

    def test_new_press_does_not_cancel_or_wait_for_previous_tail(self) -> None:
        self.canvas.use_gpu = True
        self._rapid_line(60)
        handle = self.canvas._async_brush_handle
        with patch.object(self.canvas.cpp_brush_library, "cs_brush_async_destroy") as destroy:
            self._rapid_line(180)
            destroy.assert_not_called()
            self.assertEqual(self.canvas._async_brush_handle, handle)
            self.assertTrue(self.canvas._async_tablet_events)
        self._wait_async()
        self.assertEqual(self._alpha(340, 60), 255)
        self.assertEqual(self._alpha(340, 180), 255)

    def test_async_tablet_input_does_not_materialize_python_layer_images(self) -> None:
        from DOCUMENTS.tile_store import TileStore
        self.canvas.use_gpu = True
        with patch.object(TileStore, "materialize", side_effect=AssertionError("full canvas copied on UI thread")):
            self._rapid_line(60)
            self._rapid_line(180)
            self._wait_async()
        self.assertEqual(self._alpha(340, 60), 255)
        self.assertEqual(self._alpha(340, 180), 255)

    def test_document_switch_discards_queued_input_and_late_callbacks(self) -> None:
        self.canvas.use_gpu = True
        self._rapid_line(60)
        old_generation = self.canvas._async_stroke_generation
        self._rapid_line(180)
        self.canvas.set_document(Document(400, 300, 72, None))
        self.assertFalse(self.canvas._async_tablet_events)
        self.assertIsNone(self.canvas._async_brush_handle)
        image = QImage(20, 20, QImage.Format.Format_RGBA8888)
        image.fill(QColor("red"))
        self.canvas._dispatch_async_brush_patch(old_generation, 20, 20, 20, 20, image, True, "")
        APP.processEvents()
        self.assertEqual(self._alpha(25, 25), 0)
        self.assertEqual(self.canvas.tile_history.index, 0)

    def test_symmetry_crossing_keeps_both_mirrored_strokes(self) -> None:
        self.canvas.use_gpu = True
        self.canvas.symmetry_horizontal = True
        self._stroke([(40, 90), (180, 150), (230, 210)])
        self.assertEqual(self._alpha(40, 90), 255)
        self.assertEqual(self._alpha(359, 90), 255)
        self.assertEqual(self._alpha(230, 210), 255)
        self.assertEqual(self._alpha(169, 210), 255)
        self.canvas.undo()
        self.assertEqual(self._max_alpha(), 0)

    def test_radial_symmetry_repeats_a_real_stroke_around_canvas_center(self) -> None:
        """Radial copies are painted pixels, not merely guide lines."""
        self.canvas.set_radial_symmetry(4)
        self._stroke([(250, 150), (300, 150)])
        # Centre is (199.5, 149.5) for this 400 × 300 document. The four
        # endpoints are deliberately tested away from the symmetry axes.
        for point in ((300, 150), (199, 250), (99, 149), (200, 49)):
            self.assertEqual(self._alpha(*point), 255)
        self.canvas.undo()
        self.assertEqual(self._max_alpha(), 0)

    def test_radial_straight_segment_commits_each_copy_as_a_small_region(self) -> None:
        """Opposite copies must not turn their union into a canvas-sized write."""
        self.canvas.set_radial_symmetry(4)
        layer = self.canvas.get_active_layer()
        with patch.object(self.canvas, "sync_gpu_layer", wraps=self.canvas.sync_gpu_layer) as sync:
            self.assertTrue(self.canvas._paint_straight_paint_segment(
                layer, QPointF(250, 150), QPointF(300, 150)))
        self.assertEqual(sync.call_count, 4)
        regions = [call.args[0] for call in sync.call_args_list]
        self.assertTrue(all(region.width() < 100 and region.height() < 100 for region in regions))

    def test_radial_symmetry_uses_the_artist_selected_center(self) -> None:
        self.canvas.set_radial_symmetry(2)
        self.canvas.set_radial_symmetry_center(QPointF(100, 120))
        self._stroke([(140, 120), (165, 120)])
        self.assertEqual(self._alpha(165, 120), 255)
        self.assertEqual(self._alpha(35, 120), 255)


    def test_dual_brush_breaks_the_stroke_where_the_second_tip_is_absent(self) -> None:
        # Second tip: small, hard, spaced three diameters apart along the
        # path.  In multiply mode the main stroke only shows inside its dabs.
        for key, value in {"size": 30.0, "dualBrush": True, "dualSizeRatio": 0.3,
                           "dualSpacing": 3.0, "dualHardness": 1.0, "dualMode": 0.0,
                           "dualScatter": 0.0, "dualCount": 1.0}.items():
            self.canvas.set_brush_setting(key, value)
        self._stroke([(40 + i * 4, 150) for i in range(81)])
        row = [self._alpha(x, 150) for x in range(60, 340)]
        self.assertGreater(max(row), 200)                 # inked inside the second-tip dabs
        self.assertLess(min(row), 20)                     # and gaps between them
        self.canvas.set_brush_setting("dualBrush", False)
        self.canvas.document.get_active_layer().image.fill(0)
        self._stroke([(40 + i * 4, 150) for i in range(81)])
        self.assertGreater(min(self._alpha(x, 150) for x in range(60, 340)), 200)


    def test_wrap_around_continues_dabs_on_the_opposite_edge(self) -> None:
        self.canvas.set_wrap_around(True)
        try:
            # Document is 400 px wide: a stroke crossing x = 400 must reappear at x ≈ 0.
            self._stroke([(370 + i * 2, 150) for i in range(40)])   # 370 → 448
            self.assertGreater(self._alpha(395, 150), 200)
            self.assertGreater(self._alpha(20, 150), 200)            # wrapped part (420 → 20)
            self.assertLess(self._alpha(200, 150), 10)
        finally:
            self.canvas.set_wrap_around(False)
        self.canvas.document.get_active_layer().image.fill(0)
        self._stroke([(370 + i * 2, 100) for i in range(40)])
        self.assertLess(self._alpha(20, 100), 10)                   # no wrap when off


if __name__ == "__main__":
    unittest.main()
