import ctypes
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CORE.projection_worker import ProjectionLayer, ProjectionWorker, _MODES
from DOCUMENTS.blend_modes import composite_layers


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "build_cpp_native" / "libCreativeCoreBridge.so"


@unittest.skipUnless(BRIDGE.is_file(), "Build the native projection bridge to run this integration test")
class NativeProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_blend_modes_match_python_reference(self):
        library = ctypes.CDLL(str(BRIDGE))
        worker = ProjectionWorker(native_library=library)
        self.assertTrue(worker.native_enabled)
        try:
            backdrop = QImage(4, 3, QImage.Format.Format_RGBA8888)
            backdrop.fill(QColor(120, 170, 50, 190))
            source = QImage(4, 3, QImage.Format.Format_RGBA8888)
            source.fill(QColor(210, 40, 180, 160))
            parameters = {
                "opacity": .9, "opposite_mix": .2, "intensity": .7,
                "gamma": 1.2, "mix_normal": .1, "pivot": .4,
                "clamp": .85, "softness": .8, "hue_shift": 21.,
                "saturation_boost": 1.3, "offset": .12,
            }
            for mode in _MODES:
                layers = [
                    ProjectionLayer(backdrop, True, 1., "normal", {}),
                    ProjectionLayer(source, True, .8, mode, parameters),
                ]
                loop = QEventLoop()
                rendered = []
                errors = []
                projected = lambda _g, _x, _y, image: (rendered.append(image), loop.quit())
                failed = lambda _g, _x, _y, message: (errors.append(message), loop.quit())
                worker.projected.connect(projected)
                worker.failed.connect(failed)
                worker.request({(0, 0): (4, 3, layers)})
                QTimer.singleShot(3000, loop.quit)
                loop.exec()
                worker.projected.disconnect(projected)
                worker.failed.disconnect(failed)
                self.assertFalse(errors, f"{mode}: {errors}")
                self.assertEqual(len(rendered), 1, f"{mode}: native result timed out")
                reference = composite_layers(4, 3, layers)
                for y in range(3):
                    for x in range(4):
                        actual = rendered[0].pixelColor(x, y).getRgb()
                        expected = reference.pixelColor(x, y).getRgb()
                        self.assertLessEqual(
                            max(abs(a-b) for a, b in zip(actual, expected)), 1,
                            f"{mode} at ({x},{y}): {actual} != {expected}",
                        )
        finally:
            worker.close()

    def test_invalid_thread_preference_keeps_native_worker_enabled(self):
        settings = QSettings("CreativeSystem", "CreativeSystem")
        existed = settings.contains("cpu/threads")
        previous = settings.value("cpu/threads")
        settings.setValue("cpu/threads", "not-a-number")
        worker = ProjectionWorker(native_library=ctypes.CDLL(str(BRIDGE)))
        try:
            self.assertTrue(worker.native_enabled)
            worker.set_thread_count(1)
            worker.set_thread_count(0)
        finally:
            worker.close()
            if existed:
                settings.setValue("cpu/threads", previous)
            else:
                settings.remove("cpu/threads")

    def test_unparameterized_soft_light_uses_standard_mode(self):
        worker = ProjectionWorker(native_library=ctypes.CDLL(str(BRIDGE)))
        try:
            base = QImage(2, 2, QImage.Format.Format_RGBA8888)
            base.fill(QColor(80, 160, 90, 255))
            source = QImage(2, 2, QImage.Format.Format_RGBA8888)
            source.fill(QColor(200, 60, 170, 180))
            layers = [ProjectionLayer(base, True, 1., "normal", {}),
                      ProjectionLayer(source, True, 1., "soft_light", {})]
            loop = QEventLoop()
            rendered = []
            slot = lambda _g, _x, _y, image: (rendered.append(image), loop.quit())
            worker.projected.connect(slot)
            worker.request({(0, 0): (2, 2, layers)})
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            reference = composite_layers(2, 2, layers)
            actual = rendered[0].pixelColor(0, 0).getRgb()
            expected = reference.pixelColor(0, 0).getRgb()
            self.assertLessEqual(max(abs(a-b) for a, b in zip(actual, expected)), 2)
            worker.projected.disconnect(slot)
        finally:
            worker.close()

    def test_batch_projection_returns_every_independent_tile(self):
        worker = ProjectionWorker(native_library=ctypes.CDLL(str(BRIDGE)))
        try:
            worker.set_thread_count(4)
            source = QImage(64, 64, QImage.Format.Format_RGBA8888)
            source.fill(QColor(80, 130, 210, 255))
            layers = [ProjectionLayer(source, True, 1., "multiply", {
                "intensity": .7, "gamma": 1.2, "mix_normal": .1,
            })]
            inputs = {(x, 0): (64, 64, layers) for x in range(16)}
            loop = QEventLoop()
            results = []
            errors = []
            worker.projected.connect(lambda gen, x, y, image: (results.append((x, y, image)),
                                                                  loop.quit() if len(results) == 16 else None))
            worker.failed.connect(lambda *args: (errors.append(args), loop.quit()))
            worker.request(inputs)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            self.assertFalse(errors, errors)
            self.assertEqual({(x, y) for x, y, _image in results}, set(inputs))
            self.assertTrue(all(image.pixelColor(10, 10) == QColor(80, 130, 210, 255)
                                for _x, _y, image in results))
        finally:
            worker.close()

    def test_native_projection_applies_layer_clipping(self):
        worker = ProjectionWorker(native_library=ctypes.CDLL(str(BRIDGE)))
        try:
            base = QImage(2, 1, QImage.Format.Format_RGBA8888)
            base.fill(QColor(20, 30, 40, 0))
            base.setPixelColor(0, 0, QColor(20, 30, 40, 128))
            top = QImage(2, 1, QImage.Format.Format_RGBA8888)
            top.fill(QColor(240, 30, 10, 255))
            layers = [ProjectionLayer(base, True, 1., "normal", {}),
                      ProjectionLayer(top, True, 1., "normal", {}, True)]
            loop = QEventLoop()
            rendered = []
            slot = lambda _g, _x, _y, image: (rendered.append(image), loop.quit())
            worker.projected.connect(slot)
            worker.request({(0, 0): (2, 1, layers)})
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            self.assertEqual(len(rendered), 1)
            self.assertEqual(rendered[0].pixelColor(0, 0), QColor(167, 30, 20, 128))
            self.assertEqual(rendered[0].pixelColor(1, 0).alpha(), 0)
            worker.projected.disconnect(slot)
        finally:
            worker.close()
