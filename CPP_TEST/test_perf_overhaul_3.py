"""Regression tests for round 3 of the performance overhaul.

1. change_active_group_opacity() cleared the ENTIRE projection tile-signature
   cache on every tick of the group-opacity slider (same anti-pattern as the
   mask-painting bug), when the per-tile signature already tracks group
   opacity and would recomposite the right tiles on its own.
2. Canvas._paint_gpu_projection() gated the shader-compositor path with the
   uncached GPUTileCompositor.supports() (rebuilding a full per-layer/
   per-group signature every frame) instead of the existing supports_cached(),
   and GPUTileCompositor.compose_tile() independently re-derived that same
   signature once per VISIBLE TILE rather than once per frame.
3. Canvas._tile_projection_layers() rebuilt the group/layer hierarchy
   (group_by_id/children/roots/positions) from scratch for every dirty tile
   in a frame instead of once per frame.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. change_active_group_opacity
# ---------------------------------------------------------------------------

def test_group_opacity_slider_no_longer_clears_whole_projection_cache():
    src = (ROOT / "CORE" / "application.py").read_text()
    start = src.index("    def change_active_group_opacity(self, value: int) -> None:")
    end = src.index("    def move_layer_up(")
    body = src[start:end]
    assert "_projection_tile_signatures.clear()" not in body
    assert "self.canvas.document.set_group_opacity(" in body
    assert "self.canvas.update()" in body


# ---------------------------------------------------------------------------
# 2. supports_cached wiring
# ---------------------------------------------------------------------------

def test_paint_gpu_projection_uses_cached_supports_check():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("def _paint_gpu_projection(self)")
    end = src.index("def _projection_tile_layers", start) if "def _projection_tile_layers" in src[start:] else src.index("def _tile_projection_layers", start)
    body = src[start:end]
    assert "GPUTileCompositor.supports(self.document)" not in body
    assert "self.gpu_tile_compositor.supports_cached(self.document)" in body
    # The boolean is already known True from the `if` above - must not be
    # re-derived (and its signature re-rebuilt) once per tile inside the loop.
    assert "self.gpu_tile_compositor.compose_tile(self.document, tx, ty, static, True)" in body


def test_compose_tile_accepts_precomputed_supports_and_skips_recheck():
    src = (ROOT / "CANVAS" / "gpu_tile_compositor.py").read_text()
    start = src.index("    def compose_tile(")
    end = src.index("    def cleanup(")
    body = "class H:\n" + src[start:end]

    calls = {"supports_cached": 0}

    class H_bases:
        pass

    ns = {}
    exec(body, ns)
    H = ns["H"]

    h = H()
    h.supports_cached = lambda document: (calls.__setitem__("supports_cached", calls["supports_cached"] + 1) or False)
    h.frame_stats = {"composite_fallbacks": 0, "composite_tiles": 0}

    # supports=True precomputed: must skip supports_cached() entirely.
    h._revision = lambda *a, **k: ("sig",)
    h.tiles = {}
    # Force an early, harmless failure path right after the supports check so
    # we don't need a real GL context - we only care whether supports_cached
    # got called before that point.
    try:
        h.compose_tile(SimpleNamespace(layers=[]), 0, 0, static=None, supports=True)
    except Exception:
        pass
    assert calls["supports_cached"] == 0

    try:
        h.compose_tile(SimpleNamespace(layers=[]), 0, 0, static=None, supports=None)
    except Exception:
        pass
    assert calls["supports_cached"] == 1  # None means "derive it yourself", unchanged


# ---------------------------------------------------------------------------
# 3. _group_hierarchy / _tile_projection_layers hoist
# ---------------------------------------------------------------------------

def _load_group_hierarchy():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _group_hierarchy(self) -> tuple:")
    end = src.index("    def _projection_tile_for_layer(")
    body = "class H:\n" + src[start:end]
    class FakeProjectionLayer:
        def __init__(self, image, visible, opacity, blend_mode, blend_parameters, clipping=False):
            self.image = image
            self.visible = visible
            self.opacity = opacity
            self.blend_mode = blend_mode
            self.blend_parameters = blend_parameters
            self.clipping = clipping

    ns = {"QImage": SimpleNamespace(Format=SimpleNamespace(Format_RGBA8888=1)),
          "QColor": lambda *a: a, "QRect": object,
          "ProjectionLayer": FakeProjectionLayer,
          "composite_layers": lambda w, h, tiles: SimpleNamespace(size=lambda: (w, h)),
          "fill_image_native": lambda *a: True,
          "apply_adjustment": lambda base, spec: base,
          "apply_clipped_adjustment": lambda base, adjusted, cov: adjusted,
          "adjustment_coverage": lambda *a, **k: None,
          "hide_clipped_over_hidden_base": lambda items, base_visible: items,
          "AdjustmentLayerSpec": object, "CurvesAdjustment": lambda *a: a,
          "LevelsAdjustment": lambda **k: k, "HueSaturationAdjustment": lambda **k: k,
          "ExposureAdjustment": lambda **k: k, "VibranceAdjustment": lambda **k: k,
          "ColorBalanceAdjustment": lambda **k: k, "ParametricCurvesAdjustment": lambda **k: k,
          "SelectiveColorAdjustment": lambda **k: k, "LuminosityMaskAdjustment": lambda **k: k}
    exec(body, ns)
    return ns["H"], ns


class CountingDict(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.builds = 0


def make_group(gid, layer_ids, parent_id=None):
    return SimpleNamespace(id=gid, layer_ids=layer_ids, parent_id=parent_id, visible=True,
                           opacity=1.0, blend_mode="normal", blend_parameters={},
                           cached_tile=lambda *a: None, store_tile=lambda *a: None)


def make_leaf_layer(lid):
    return SimpleNamespace(id=lid, visible=True, opacity=1.0, blend_mode="normal",
                           blend_parameters={}, layer_kind="raster", adjustment=None,
                           clipping=False, tile_store=SimpleNamespace(tile_revision=lambda *a: 0),
                           alpha_mask_store=None)


def test_group_hierarchy_matches_with_or_without_precompute():
    H, ns = _load_group_hierarchy()
    h = H()
    layers = [make_leaf_layer("l0"), make_leaf_layer("l1"), make_leaf_layer("l2")]
    groups = [make_group("g", ["l0", "l1"])]
    h.document = SimpleNamespace(layers=layers, layer_groups=groups)
    h._projection_tile_for_layer = lambda layer, tx, ty, rect: ([], False)

    hierarchy = h._group_hierarchy()
    group_by_id, children, roots, positions = hierarchy
    assert set(group_by_id) == {"g"}
    assert roots == [groups[0]]
    assert positions == {"l0": 0, "l1": 1, "l2": 2}

    # Passing it in vs. letting the method derive it itself must agree.
    rect = SimpleNamespace(width=lambda: 64, height=lambda: 64, size=lambda: (64, 64))
    fresh = h._tile_projection_layers(0, 0, rect)
    precomputed = h._tile_projection_layers(0, 0, rect, hierarchy)
    assert fresh[1] == precomputed[1]  # same "missing" outcome
    assert len(fresh[0]) == len(precomputed[0])


def test_ensure_projection_builds_hierarchy_lazily_and_once_per_frame():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _ensure_projection(self) -> None:")
    end = src.index("    def _group_hierarchy(self) -> tuple:")
    body = src[start:end]

    assert "hierarchy = None" in body
    assert "self._tile_projection_layers(tx, ty, rect, hierarchy)" in body
    # Must only be built inside the per-tile loop, guarded by "is None" (lazy,
    # so an all-cache-hit frame never pays for it) - not unconditionally
    # before the loop like layer_static/groups_static (which every tile needs
    # regardless of hit/miss).
    guard = "if hierarchy is None:\n                hierarchy = self._group_hierarchy()"
    assert guard in body
    precompute_index = body.index("layer_static = [self._layer_static_signature")
    lazy_build_index = body.index(guard)
    loop_index = body.index("for tx, ty in keys:")
    assert precompute_index < loop_index < lazy_build_index
