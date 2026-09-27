"""Câblage de DOCUMENTS/adjustments.py sur les noyaux natifs.

Vérifie de bout en bout (sans Qt : un faux QImage suffit) que chaque réglage
appelle bien le bon noyau avec les bons paramètres et donne les mêmes pixels que
l'ancienne implémentation NumPy, que l'original n'est jamais modifié, qu'un
bridge trop ancien échoue explicitement (aucun repli Python) et que le chemin
« sans effet » de apply_layer_effects ne recopie rien.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("NumPy absent")

for _name in ("PySide6", "PySide6.QtGui", "PySide6.QtCore", "PySide6.QtWidgets"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = mock.MagicMock(name=_name)

from CORE import native_filters  # noqa: E402
from CPP_TEST import test_native_filters as nf  # noqa: E402
from DOCUMENTS import adjustments as adj  # noqa: E402


class FakeImage:
    """Sous-ensemble de QImage utilisé par adjustments.py (copie-sur-écriture)."""

    class Format:
        Format_RGBA8888 = "rgba8888"

    def __init__(self, width, height, data=None):
        self._w, self._h = width, height
        self._buf = data if data is not None else bytearray(width * height * 4)
        self._shared = data is not None

    @classmethod
    def from_array(cls, array):
        return cls(array.shape[1], array.shape[0], bytearray(array.tobytes()))

    def to_array(self):
        return np.frombuffer(bytes(self._buf), dtype=np.uint8).reshape(self._h, self._w, 4)

    def isNull(self): return self._w == 0 or self._h == 0
    def width(self): return self._w
    def height(self): return self._h
    def size(self): return (self._w, self._h)
    def bytesPerLine(self): return self._w * 4

    def convertToFormat(self, _fmt):
        image = FakeImage(self._w, self._h, self._buf)   # partage les données
        image._shared = True
        return image

    def detach(self):
        if self._shared:
            self._buf = bytearray(self._buf)
            self._shared = False

    def bits(self):
        self.detach()
        return memoryview(self._buf)

    def constBits(self):
        return memoryview(self._buf)


def _fake_lut(filters):
    def apply(image, red, green, blue):
        result = image.convertToFormat(FakeImage.Format.Format_RGBA8888)
        filters.apply_lut(result.bits(), result.width(), result.height(),
                          bytes(red), bytes(green), bytes(blue), stride=result.bytesPerLine())
        return result
    return apply


class AdjustmentWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        library = nf._build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        cls.data = nf._adjustment_test_image(np)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for patcher in (mock.patch.object(adj, "QImage", FakeImage),
                        mock.patch.object(adj, "load_filters", lambda: self.filters),
                        mock.patch.object(adj, "apply_rgb_lut_native", _fake_lut(self.filters))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = FakeImage.from_array(self.data)
        self.before = bytes(self.source._buf)

    def run_kind(self, kind, **fields):
        spec = adj.AdjustmentLayerSpec(kind=kind, **fields)
        out = adj.apply_adjustment(self.source, spec)
        self.assertEqual(bytes(self.source._buf), self.before, "l'image source a été modifiée")
        return out.to_array()

    def test_hue_saturation_matches_legacy(self):
        out = self.run_kind("hue_saturation",
                            hue_saturation=adj.HueSaturationAdjustment(70, -35, 12))
        self.assertTrue(np.array_equal(out, nf._legacy_hue_saturation(np, self.data, 70, -35, 12)))

    def test_vibrance_matches_legacy(self):
        out = self.run_kind("vibrance", vibrance=adj.VibranceAdjustment(60, -15))
        self.assertTrue(np.array_equal(out, nf._legacy_vibrance(np, self.data, 60, -15)))

    def test_color_balance_matches_legacy(self):
        spec = adj.ColorBalanceAdjustment((10, -5, 30), (0, 20, -20), (-40, 0, 25))
        out = self.run_kind("color_balance", color_balance=spec)
        self.assertTrue(np.array_equal(out, nf._legacy_color_balance(
            np, self.data, spec.shadows, spec.midtones, spec.highlights)))

    def test_threshold_matches_legacy(self):
        for level in (0, 1, 100, 128, 255, 300, -5):
            out = self.run_kind("threshold", threshold=level)
            data = self.data.copy()
            luminance = 0.2126 * data[..., 0] + 0.7152 * data[..., 1] + 0.0722 * data[..., 2]
            value = np.where(luminance >= max(0, min(255, int(level))), 255, 0).astype(np.uint8)
            data[..., :3] = value[..., None]
            self.assertTrue(np.array_equal(out, data), f"seuil {level}")

    def test_exposure_matches_legacy(self):
        for exposure, offset, gamma in ((0, 0, 1), (1.5, 0.0, 1.0), (-2, 0.1, 2.2), (0.3, -0.2, 0.5)):
            out = self.run_kind("exposure", exposure=adj.ExposureAdjustment(exposure, offset, gamma))
            data = self.data.copy()
            rgb = data[..., :3].astype(np.float32) / 255.0
            rgb = np.clip(rgb * (2.0 ** float(exposure)) + float(offset), 0.0, 1.0)
            rgb = np.power(rgb, 1.0 / max(0.01, float(gamma)))
            data[..., :3] = np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
            self.assertTrue(np.array_equal(out, data), f"exposition {exposure},{offset},{gamma}")

    def test_luminosity_mask_flow_matches_legacy(self):
        for mode in ("lights", "shadows", "midtones"):
            mask = adj.LuminosityMaskAdjustment(mode, 0.8, 0.4, invert=(mode == "shadows"))
            out = self.run_kind("hue_saturation", hue_saturation=adj.HueSaturationAdjustment(90, 40, 0),
                                luminosity_mask=mask)
            adjusted = nf._legacy_hue_saturation(np, self.data, 90, 40, 0)
            expected = nf._legacy_luminosity_blend(np, self.data, adjusted, mode, 0.8, 0.4,
                                                   mode == "shadows")
            diff = np.abs(out.astype(int) - expected.astype(int))
            self.assertLessEqual(int(diff.max()), 1, mode)
            self.assertTrue(np.array_equal(out[..., 3], self.data[..., 3]))

    def test_layer_effects_without_effects_returns_the_same_object(self):
        for effects in (None, [], [{"type": "bevel"}], [{"kind": "color_overlay"}]):
            self.assertIs(adj.apply_layer_effects(self.source, effects), self.source)

    def test_layer_effects_stroke_and_shadow_do_not_touch_the_source(self):
        effects = [{"type": "drop_shadow", "offset_x": 3, "offset_y": 2, "size": 4},
                   {"kind": "stroke", "size": 2, "color": [255, 0, 0, 255]}]
        out = adj.apply_layer_effects(self.source, effects)
        self.assertEqual(bytes(self.source._buf), self.before)
        self.assertIsNot(out, self.source)
        self.assertFalse(np.array_equal(out.to_array(), self.data))

    def test_outdated_bridge_fails_loudly_instead_of_falling_back(self):
        old = mock.MagicMock()
        old.supports_adjustments = False
        with mock.patch.object(adj, "load_filters", lambda: old):
            for kind, extra in (("hue_saturation", {}), ("vibrance", {}), ("color_balance", {}),
                                ("threshold", {})):
                with self.assertRaises(RuntimeError, msg=kind):
                    adj.apply_adjustment(self.source, adj.AdjustmentLayerSpec(kind=kind, **extra))
            with self.assertRaises(RuntimeError):
                adj.apply_layer_effects(self.source, [{"type": "stroke"}])
        with mock.patch.object(adj, "load_filters", lambda: None):
            with self.assertRaises(RuntimeError):
                adj.apply_adjustment(self.source, adj.AdjustmentLayerSpec(kind="vibrance"))

    def test_lut_adjustments_still_work_and_fail_without_core(self):
        out = adj.apply_adjustment(self.source, adj.AdjustmentLayerSpec(kind="invert")).to_array()
        self.assertTrue(np.array_equal(out[..., :3], 255 - self.data[..., :3]))
        self.assertTrue(np.array_equal(out[..., 3], self.data[..., 3]))
        with mock.patch.object(adj, "apply_rgb_lut_native", lambda *a: None):
            with self.assertRaises(RuntimeError):
                adj.apply_adjustment(self.source, adj.AdjustmentLayerSpec(kind="invert"))

    def test_unknown_kind_is_still_rejected(self):
        with self.assertRaises(ValueError):
            adj.apply_adjustment(self.source, adj.AdjustmentLayerSpec(kind="nope"))


if __name__ == "__main__":
    unittest.main()
