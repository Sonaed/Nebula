"""Regression tests for round 2 of the performance overhaul.

Three memoization fixes, all following the same shape: something that only
actually needs to be recomputed when the document's structure changes was
instead being fully rebuilt every single frame.

1. Document.repair_layer_groups() ran its O(groups^2) consistency check every
   frame (from Canvas._ensure_projection) even when nothing about the
   layer/group structure had changed since the last call.
2. Canvas._projection_signature_for() rebuilt a full per-layer/per-group
   metadata tuple for EVERY visible+prefetch tile, every frame, even though
   only two revision numbers per layer actually vary by tile.
3. GPUTileCompositor._revision() had the identical per-tile pattern for the
   shader-compositor path.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class CountingList(list):
    """A list that counts how many times it's iterated (for-looped over)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


# ---------------------------------------------------------------------------
# 1. Document.repair_layer_groups
# ---------------------------------------------------------------------------

def _load_document_repair():
    src = (ROOT / "DOCUMENTS" / "document.py").read_text()
    start = src.index("    def _group_structure_signature(self) -> tuple:")
    end = src.index("    def move_layer_to_group(")
    body = "class H:\n" + src[start:end]
    ns = {}
    exec(body, ns)
    return ns["H"]


def make_group(gid, layer_ids, parent_id=None):
    g = SimpleNamespace(id=gid, layer_ids=layer_ids, parent_id=parent_id)

    def invalidate():
        pass
    g.invalidate = invalidate
    return g


class FakeNativeState:
    def remove_group(self, index):
        pass


def test_repair_layer_groups_still_fixes_a_real_gap():
    """Correctness must survive the memoization: an inconsistent structure
    (a foreign layer sitting inside what should be one contiguous group) is
    still repaired to its longest contiguous run, same as before."""
    H = _load_document_repair()
    h = H()
    h.layers = [SimpleNamespace(id=f"l{i}") for i in range(4)]
    # Group "g" nominally owns l0 and l2, with l1 (not a member) in between -
    # a gap with no foreign group claiming l1, so it should be folded in.
    h.layer_groups = [make_group("g", ["l0", "l2"])]
    h._native_state = FakeNativeState()
    h._group_repair_cache = None

    changed = h.repair_layer_groups()
    assert changed is True
    assert h.layer_groups[0].layer_ids == ["l0", "l1", "l2"]


def test_repair_layer_groups_skips_recompute_when_structure_is_unchanged():
    H = _load_document_repair()
    h = H()
    h.layers = CountingList(SimpleNamespace(id=f"l{i}") for i in range(4))
    h.layer_groups = CountingList([make_group("g", ["l0", "l1"]),
                                    make_group("g2", ["l2", "l3"])])
    h._native_state = FakeNativeState()
    h._group_repair_cache = None

    first = h.repair_layer_groups()
    iterations_after_first = h.layer_groups.iterations
    assert iterations_after_first > 1  # the full algorithm loops over groups several times

    h.layer_groups.iterations = 0
    h.layers.iterations = 0
    second = h.repair_layer_groups()

    assert second == first
    # Only the cheap signature check (one pass over layers, one over groups)
    # should have run - not the full by_id/chain/related/sort machinery again.
    assert h.layer_groups.iterations == 1
    assert h.layers.iterations == 1


def test_repair_layer_groups_recomputes_when_something_actually_changes():
    H = _load_document_repair()
    h = H()
    h.layers = [SimpleNamespace(id=f"l{i}") for i in range(4)]
    h.layer_groups = [make_group("g", ["l0", "l1"])]
    h._native_state = FakeNativeState()
    h._group_repair_cache = None
    h.repair_layer_groups()

    # A real structural change (a layer added to the group) must be picked up.
    h.layer_groups[0].layer_ids = ["l0", "l1", "l2"]
    changed = h.repair_layer_groups()
    assert changed is False  # already contiguous and valid - just re-verified
    assert h._group_repair_cache[0] == h._group_structure_signature()


# ---------------------------------------------------------------------------
# 2. Canvas._projection_signature_for / _layer_static_signature / _groups_static_signature
# ---------------------------------------------------------------------------

def _load_canvas_signature_methods():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _layer_static_signature(self, layer) -> tuple:")
    end = src.index("    def visible_document_tile_keys(")
    body = "class H:\n" + src[start:end]
    ns = {}
    exec(body, ns)
    return ns["H"]


class FakeMaskStore:
    def __init__(self, revisions):
        self._revisions = revisions

    def tile_revision(self, tx, ty):
        return self._revisions.get((tx, ty), 0)


class FakeTileStore:
    def __init__(self, revisions):
        self._revisions = revisions

    def tile_revision(self, tx, ty):
        return self._revisions.get((tx, ty), 0)


def make_layer(lid, tile_revs, mask_revs=None):
    return SimpleNamespace(
        id=lid, visible=True, opacity=1.0, blend_mode="normal", clipping=False,
        blend_parameters={}, layer_kind="raster", adjustment=None,
        tile_store=FakeTileStore(tile_revs),
        alpha_mask_store=FakeMaskStore(mask_revs) if mask_revs is not None else None,
    )


def test_projection_signature_matches_with_or_without_precomputed_static():
    H = _load_canvas_signature_methods()
    h = H()
    layer = make_layer("a", {(1, 2): 5}, {(1, 2): 9})
    h.document = SimpleNamespace(layers=[layer], layer_groups=[])

    fresh = h._projection_signature_for(1, 2)
    layer_static = [h._layer_static_signature(l) for l in h.document.layers]
    groups_static = h._groups_static_signature()
    precomputed = h._projection_signature_for(1, 2, layer_static, groups_static)

    assert fresh == precomputed


def test_projection_signature_still_distinguishes_tiles_and_state_changes():
    H = _load_canvas_signature_methods()
    h = H()
    layer = make_layer("a", {(0, 0): 1, (1, 0): 2}, {(0, 0): 0, (1, 0): 0})
    h.document = SimpleNamespace(layers=[layer], layer_groups=[])

    sig_tile_a = h._projection_signature_for(0, 0)
    sig_tile_b = h._projection_signature_for(1, 0)
    assert sig_tile_a != sig_tile_b  # different tile revision -> different signature

    layer.opacity = 0.5
    sig_after_opacity_change = h._projection_signature_for(0, 0)
    assert sig_after_opacity_change != sig_tile_a  # frame-level change still detected


def test_ensure_projection_precomputes_static_signature_once_per_frame():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _ensure_projection(self) -> None:")
    end = src.index("    def _tile_projection_layers(")
    body = src[start:end]
    assert "layer_static = [self._layer_static_signature(layer) for layer in self.document.layers]" in body
    assert "groups_static = self._groups_static_signature()" in body
    assert "self._projection_signature_for(tx, ty, layer_static, groups_static," in body
    # Make sure this precompute happens ONCE, outside the per-tile `for` loop.
    precompute_index = body.index("layer_static = [self._layer_static_signature")
    loop_index = body.index("for tx, ty in ordered:")
    assert precompute_index < loop_index


# ---------------------------------------------------------------------------
# 3. GPUTileCompositor._static_signature / _revision / compose_tile
# ---------------------------------------------------------------------------

def _load_compositor_revision_methods():
    src = (ROOT / "CANVAS" / "gpu_tile_compositor.py").read_text()
    start = src.index("    def _static_signature(self, document) -> tuple:")
    end = src.index("    def _clear_tile(")
    body = "class H:\n" + src[start:end]
    ns = {}
    exec(body, ns)
    return ns["H"]


def make_gpu_layer(lid, visible, tile_revs):
    return SimpleNamespace(
        id=lid, visible=visible, blend_mode="normal", opacity=1.0, clipping=False,
        tile_store=SimpleNamespace(
            tile_revision=lambda tx, ty, r=tile_revs: r.get((tx, ty), 0),
            has_tile=lambda tx, ty: True,
        ),
        alpha_mask_store=None,
    )


def test_compositor_revision_matches_with_or_without_precomputed_static():
    H = _load_compositor_revision_methods()
    h = H()
    document = SimpleNamespace(
        layers=[make_gpu_layer("a", True, {(0, 0): 3}), make_gpu_layer("b", False, {(0, 0): 9})],
        layer_groups=(),
    )

    fresh = h._revision(document, 0, 0)
    static = h._static_signature(document)
    precomputed = h._revision(document, 0, 0, static)

    assert fresh == precomputed
    # Invisible layer "b" must be excluded, same as the original implementation.
    layer_ids_in_signature = {entry[0][0] for entry in fresh[0]}
    assert layer_ids_in_signature == {"a"}


def test_compose_tile_source_reuses_precomputed_static_across_the_frame_loop():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    marker = "supports_cached(self.document)):"
    start = src.index(marker)
    end = src.index("if composed_tiles:", start)
    body = src[start:end]
    assert "static = self.gpu_tile_compositor._static_signature(self.document)" in body
    assert "self.gpu_tile_compositor.compose_tile(self.document, tx, ty, static, True)" in body
    # The precompute must sit outside/above the per-tile loop, not inside it.
    precompute_index = body.index("_static_signature(self.document)")
    loop_index = body.index("for tx, ty in visible_keys:")
    assert precompute_index < loop_index
