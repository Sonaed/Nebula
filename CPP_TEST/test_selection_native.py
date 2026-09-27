"""Câblage de selection.py et de apply_clipped_adjustment sur les noyaux natifs (sans Qt)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from CPP_TEST.test_adjustments_native import FakeImage  # noqa: E402
from DOCUMENTS import blend_modes, selection  # noqa: E402


class SelectionWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        library = nf._build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        rng = np.random.default_rng(4)
        cls.data = rng.integers(0, 256, size=(29, 41, 4), dtype=np.uint8)
        cls.data[..., 3][rng.random((29, 41)) < 0.5] = 0

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for module in (selection, blend_modes):
            patcher = mock.patch.object(module, "load_filters", lambda: self.filters)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(selection, "QImage", FakeImage)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(blend_modes, "QImage", FakeImage)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mask = selection.SelectionMask.__new__(selection.SelectionMask)
        self.mask.image = FakeImage.from_array(self.data)
        self.mask._bounds_cache = "stale"

    def test_feather_expand_contract_match_legacy(self):
        cases = (("feather", lambda r: nf._legacy_feather(np, self.data, r)),
                 ("expand", lambda r: nf._legacy_morph(np, self.data, r, True)),
                 ("contract", lambda r: nf._legacy_morph(np, self.data, r, False)))
        for name, legacy in cases:
            self.mask.image = FakeImage.from_array(self.data)
            self.mask._bounds_cache = "stale"
            getattr(self.mask, name)(4)
            self.assertTrue(np.array_equal(self.mask.image.to_array(), legacy(4)), name)
            self.assertIsNone(self.mask._bounds_cache, f"{name} n'invalide pas le cache")

    def test_zero_radius_is_a_noop(self):
        for name in ("feather", "expand", "contract"):
            getattr(self.mask, name)(0)
            self.assertTrue(np.array_equal(self.mask.image.to_array(), self.data))
            self.assertEqual(self.mask._bounds_cache, "stale")

    def test_select_color_range(self):
        source = FakeImage.from_array(self.data)
        color = SimpleNamespace(red=lambda: 90, green=lambda: 120, blue=lambda: 30)
        self.mask.select_color_range(source, color, 40)
        target = np.array([90, 120, 30], dtype=np.int32)
        distance = np.sqrt(((self.data[..., :3].astype(np.int32) - target) ** 2).sum(axis=2))
        expected = np.clip(255 - distance * 255 / (40 * 1.732), 0, 255).astype(np.uint8)
        self.assertTrue(np.array_equal(self.mask.image.to_array()[..., 3], expected))
        with self.assertRaises(ValueError):
            self.mask.select_color_range(FakeImage(3, 3), color, 40)

    def test_outdated_bridge_fails_loudly(self):
        old = mock.MagicMock()
        old.supports_adjustments = False
        with mock.patch.object(selection, "load_filters", lambda: old):
            for call in (lambda: self.mask.feather(2), lambda: self.mask.expand(2),
                         lambda: self.mask.contract(2)):
                with self.assertRaises(RuntimeError):
                    call()

    def test_clipped_adjustment_matches_legacy_and_keeps_inputs(self):
        rng = np.random.default_rng(6)
        base = rng.integers(0, 256, size=(29, 41, 4), dtype=np.uint8)
        changed = rng.integers(0, 256, size=(29, 41, 4), dtype=np.uint8)
        images = [FakeImage.from_array(a) for a in (base, changed, self.data)]
        before = [bytes(i._buf) for i in images]
        out = blend_modes.apply_clipped_adjustment(*images)
        self.assertEqual([bytes(i._buf) for i in images], before)
        self.assertTrue(np.array_equal(out.to_array(), nf._legacy_clipped(np, base, changed, self.data)))
        with self.assertRaises(ValueError):
            blend_modes.apply_clipped_adjustment(images[0], FakeImage(2, 2), images[2])
        with mock.patch.object(blend_modes, "load_filters", lambda: None):
            with self.assertRaises(RuntimeError):
                blend_modes.apply_clipped_adjustment(*images)


if __name__ == "__main__":
    unittest.main()
