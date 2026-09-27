"""Clipping onto folders: hidden base hides clipped layers; folder gesture check."""
import sys, types, importlib.util, re, dataclasses
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeImage:
    Format = SimpleNamespace(Format_RGBA8888=1, Format_ARGB32=2)
    def __init__(self, size=(4, 4), fmt=1):
        self._size = size
        self.alpha = 255
    def size(self): return self._size


def load_blend_modes():
    calls = []
    def stub(name, **attrs):
        mod = types.ModuleType(name); mod.__dict__.update(attrs); sys.modules[name] = mod
    stub("PySide6"); stub("PySide6.QtCore", QRect=object)
    stub("PySide6.QtGui", QColor=lambda *a: a, QImage=FakeImage)
    def fill(img, color): img.alpha = color[3]; return True
    def mask(img, m): img.alpha = img.alpha * m.alpha // 255; return True
    stub("CORE"); stub("CORE.native_filters", load_filters=lambda: None)
    names = ["composite_layers_advanced", "composite_layers_native", "clone_image_native",
             "draw_text_native", "plan_layer_composite_runs"]
    stub("CORE.native_bridge", apply_alpha_mask_native=mask, fill_image_native=fill,
         **{n: (lambda *a, **k: None) for n in names})
    stub("DOCUMENTS"); 
    adj = {n: object for n in ["AdjustmentLayerSpec", "CurvesAdjustment", "LevelsAdjustment",
        "HueSaturationAdjustment", "ExposureAdjustment", "VibranceAdjustment",
        "ColorBalanceAdjustment", "ParametricCurvesAdjustment", "SelectiveColorAdjustment",
        "LuminosityMaskAdjustment", "apply_adjustment", "apply_layer_effects"]}
    stub("DOCUMENTS.adjustments", **adj)
    spec = importlib.util.spec_from_file_location("bm", ROOT / "DOCUMENTS" / "blend_modes.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


bm = load_blend_modes()


def entry(visible=True, clipping=False):
    return SimpleNamespace(image=None, visible=visible, opacity=1.0, blend_mode="normal",
                           blend_parameters={}, clipping=clipping)


def test_hidden_folder_hides_clipped_layers():
    base = [True]
    out = bm.hide_clipped_over_hidden_base([entry(visible=False)], base)   # hidden folder
    out += bm.hide_clipped_over_hidden_base([entry(clipping=True)], base)
    out += bm.hide_clipped_over_hidden_base([entry(clipping=True)], base)
    assert [e.visible for e in out] == [False, False, False]


def test_visible_base_keeps_clipped_layers_and_resets():
    base = [True]
    out = bm.hide_clipped_over_hidden_base([entry(visible=False)], base)
    out += bm.hide_clipped_over_hidden_base([entry(visible=True)], base)   # new visible base
    out += bm.hide_clipped_over_hidden_base([entry(clipping=True)], base)
    assert [e.visible for e in out] == [False, True, True]


def test_hiding_works_for_frozen_dataclasses():
    @dataclasses.dataclass(frozen=True)
    class P:
        image: object
        visible: bool
        clipping: bool = False
    out = bm.hide_clipped_over_hidden_base([P(None, False), P(None, True, True)], [True])
    assert out[1].visible is False


def test_adjustment_coverage_combines_opacity_mask_clip():
    assert bm.adjustment_coverage(1.0, (4, 4)) is None
    cov = bm.adjustment_coverage(0.5, (4, 4))
    assert cov.alpha == 128
    mask = FakeImage(); mask.alpha = 128
    cov = bm.adjustment_coverage(1.0, (4, 4), mask=mask)
    assert cov.alpha == 128
    clip = FakeImage(); clip.alpha = 255
    assert bm.adjustment_coverage(1.0, (4, 4), clip_image=clip).alpha == 255


def _dock_helpers():
    src = (ROOT / "UI/docks/layers_dock.py").read_text()
    start = src.index("    def _can_clip_onto_folder")
    end = src.index("    def refresh_layers(")
    ns = {}
    body = "class H:\n" + src[start:end]
    exec(body, ns)
    return ns["H"]


def make_doc():
    L = [SimpleNamespace(id=f"l{i}") for i in range(4)]     # l0,l1 in folder g; l2 above; l3 top
    g = SimpleNamespace(id="g", layer_ids=["l0", "l1"], parent_id=None)
    return SimpleNamespace(layers=L, layer_groups=[g])


def test_folder_clip_gesture_accepts_layer_right_above_folder():
    H = _dock_helpers(); h = H(); h._document = make_doc()
    assert h._can_clip_onto_folder(2, "g") is True
    assert h._can_clip_onto_folder(3, "g") is False      # not adjacent
    assert h._can_clip_onto_folder(1, "g") is False      # member itself


def test_folder_clip_rejects_other_level():
    H = _dock_helpers(); h = H(); doc = make_doc()
    outer = SimpleNamespace(id="o", layer_ids=["l2", "l3"], parent_id=None)
    doc.layer_groups.append(outer)                        # l2 in a different root folder
    h._document = doc
    assert h._can_clip_onto_folder(2, "g") is False


def test_clip_base_is_folder_label():
    H = _dock_helpers(); h = H(); h._document = make_doc()
    assert h._clip_base_is_folder(2) is True
    assert h._clip_base_is_folder(1) is False            # base l0 is in the same folder
    assert h._clip_base_is_folder(3) is False
