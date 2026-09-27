"""Regression test: painting a layer mask must not nuke the whole projection cache.

Before this fix, Canvas.sync_gpu_layer()'s mask branch called
`self._projection_tile_signatures.clear()` on every single brush dab. On a
document with folders/clipping (anything routed through `_ensure_projection`),
that forced a full recompute of every tile in the document on every mouse-move
event while painting a mask, instead of just the tiles the dab touched -
making mask painting on any non-trivial canvas unusable.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load_sync_gpu_layer():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def sync_gpu_layer(")
    end = src.index("    def _ensure_projection(")
    body = "class H:\n" + src[start:end]
    calls = {"normalize": []}

    def normalize_alpha_mask_native(image, rect):
        calls["normalize"].append(rect)
        return True

    ns = {"QRect": object, "normalize_alpha_mask_native": normalize_alpha_mask_native}
    exec(body, ns)
    return ns["H"], calls


class FakeMaskStore:
    def __init__(self):
        self.writes = []

    def write_image(self, image, rect):
        self.writes.append(rect)


class FakeLayer:
    def __init__(self):
        self.id = "layer-1"
        self._mask_store = FakeMaskStore()

    def ensure_alpha_mask(self):
        return self._mask_store


class FakeGpuRenderer:
    def __init__(self):
        self.dirtied = []

    def mark_layer_dirty(self, layer, rect):
        self.dirtied.append((layer, rect))


def make_canvas(H, layer, populated_signatures):
    canvas = H()
    canvas.document = SimpleNamespace(get_active_layer=lambda: layer)
    canvas._editing_alpha_mask_layer_id = layer.id
    canvas._editing_alpha_mask_image = object()
    canvas._projection_tile_signatures = dict(populated_signatures)
    canvas.gpu_ready = True
    canvas.gpu_renderer = FakeGpuRenderer()
    canvas._repaint_calls = []
    canvas._update_calls = []
    canvas._repaint_brush_dirty_rect = lambda rect: canvas._repaint_calls.append(rect)
    canvas.update = lambda: canvas._update_calls.append(True)
    return canvas


def test_mask_dab_does_not_clear_projection_cache():
    H, calls = _load_sync_gpu_layer()
    layer = FakeLayer()
    populated = {(tx, ty): ("sig", tx, ty) for tx in range(40) for ty in range(50)}
    canvas = make_canvas(H, layer, populated)

    dirty_rect = "the-dirty-rect"
    canvas.sync_gpu_layer(dirty_rect)

    # The whole point of the fix: 2000 unrelated tile signatures must survive
    # a single dab's sync_gpu_layer call untouched.
    assert canvas._projection_tile_signatures == populated
    assert len(canvas._projection_tile_signatures) == 2000


def test_mask_dab_still_writes_the_mask_and_marks_gpu_dirty():
    H, calls = _load_sync_gpu_layer()
    layer = FakeLayer()
    canvas = make_canvas(H, layer, {})

    dirty_rect = "rect-42"
    canvas.sync_gpu_layer(dirty_rect)

    assert layer._mask_store.writes == [dirty_rect]
    assert calls["normalize"] == [dirty_rect]
    assert canvas.gpu_renderer.dirtied == [(layer, dirty_rect)]
    assert canvas._repaint_calls == [dirty_rect]
    assert canvas._update_calls == []


def test_mask_full_replace_with_no_rect_still_repaints_everything():
    H, calls = _load_sync_gpu_layer()
    layer = FakeLayer()
    canvas = make_canvas(H, layer, {(0, 0): "stale"})

    canvas.sync_gpu_layer(None)

    assert layer._mask_store.writes == [None]
    assert canvas.gpu_renderer.dirtied == [(layer, None)]
    assert canvas._update_calls == [True]
    assert canvas._repaint_calls == []
    # A full-document write bumps every touched tile's native revision, which
    # the projection signature already keys off of (see
    # _projection_signature_for) - no explicit clear needed here either.
    assert canvas._projection_tile_signatures == {(0, 0): "stale"}


def test_source_no_longer_clears_signatures_in_mask_branch():
    """Belt-and-suspenders guard against the exact bug regressing."""
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def sync_gpu_layer(")
    end = src.index("    def _ensure_projection(")
    branch_start = src.index("_editing_alpha_mask_image is not None):", start, end)
    branch_end = src.index("# CreativeCore writes through a raw pointer", branch_start, end)
    mask_branch = src[branch_start:branch_end]
    assert "_projection_tile_signatures.clear()" not in mask_branch
