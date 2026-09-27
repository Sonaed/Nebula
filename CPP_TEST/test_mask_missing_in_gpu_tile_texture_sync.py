"""Regression test for the ACTUAL rendering path behind "mask layers still
not working" (user report, after fix #11 - CANVAS/canvas.py's
_paint_cpu_fallback() - was delivered, unit-tested and verified delivered,
but the user retested and still saw "rien ne s'affiche du tout" with no
error in the terminal at all).

Fix #11's own regression test (test_mask_missing_in_cpu_fallback_fast_path)
proved _paint_cpu_fallback()'s fast loop is correctly mask-aware now - and
that conclusion is still true. The mistake was believing that loop was the
code path actually exercised. It is only reached when
Canvas._paint_gl_frame() bails out to it: no GL context, self.use_gpu is
False, transforming/selection_drawing, or gpu_ready is False. None of those
applied to this user's session (GPU active, "normal" blend, no groups, not
transforming) - so _paint_gl_frame() took its OWN per-layer draw branch
instead, calling self.gpu_renderer.draw_layer() directly for every visible
layer. That is a completely different code path from both
GPUTileCompositor.compose_tile() (used only by _paint_gpu_projection() for
non-normal/grouped documents) and _paint_cpu_fallback() - and it turned out
to have the exact same gap fix #11 closed elsewhere: CanvasGPURenderer.
sync_tile(), which uploads the GPU texture for a tiled layer
(draw_layer -> _draw_tiled_layer -> sync_tile, the common case for any
ordinary raster layer), built the texture straight from the color tile and
never looked at layer.alpha_mask_store at all.

Two separate defects had to be fixed together, because fixing only the
first would still show nothing changing after a stroke:

1. sync_tile() didn't apply the mask when building the texture.
2. Even once it does, its only staleness signal was the *color* tile's own
   revision - and painting on a mask never touches layer.tile_store, only
   layer.alpha_mask_store (a separate TileStore). So the mask tile's own
   revision has to be folded into sync_tile()'s cache key, or a painted-then
   -released mask stroke would still show the pre-edit (or no-mask) texture
   forever.
3. A third, independent staleness path: _draw_tiled_layer_cached() (the
   "simple" per-frame draw list, used whenever no rotation/flip/transform is
   active - i.e. ordinary painting) keeps its own per-layer cache of which
   tiles to draw, keyed only by a signature built from the *color* tile
   store's revisions. A mask edit never changes that signature, so this
   cache's own diffing logic would skip re-calling sync_tile() at all for
   an edited layer, even after (1) and (2) were both fixed - it would just
   keep re-drawing last frame's texture ids. CanvasGPURenderer.
   invalidate_layer_draw_cache(), called from the mask-paint code path in
   Canvas.sync_gpu_layer() right alongside the existing mark_layer_dirty()
   call, drops that one layer's cached draw list so it rebuilds (and thus
   re-calls the now-fixed sync_tile()) on the very next frame.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
GPU_RENDERER_PATH = ROOT / "CANVAS" / "gpu_renderer.py"
CANVAS_PATH = ROOT / "CANVAS" / "canvas.py"


def _extract_sync_tile() -> str:
    src = GPU_RENDERER_PATH.read_text()
    start = src.index("    def sync_tile(")
    end = src.index("    def _draw_tiled_layer_cached(", start)
    return src[start:end]


def _extract_mask_revision_snippet() -> str:
    body = _extract_sync_tile()
    start = body.index('        mask_store = getattr(layer, "alpha_mask_store", None)\n')
    end = body.index("        key = (str(getattr(layer,")
    return body[start:end]


def _extract_mask_application_snippet() -> str:
    body = _extract_sync_tile()
    start = body.index("        if mask_revision is not None:\n")
    end = body.index("        texture = self._create_texture(image, tiled=True)")
    return body[start:end]


def test_source_sync_tile_imports_native_masking_helpers():
    src = GPU_RENDERER_PATH.read_text()
    assert "from CORE.native_bridge import apply_alpha_mask_native, clone_image_native" in src


def test_source_mask_revision_checked_and_folded_into_cache_key():
    snippet = _extract_mask_revision_snippet()
    assert 'mask_store = getattr(layer, "alpha_mask_store", None)' in snippet
    assert 'getattr(layer, "mask_disabled", False)' in snippet
    assert "mask_store.has_tile(tx, ty)" in snippet
    assert "mask_store.tile_is_resident(tx, ty)" in snippet
    assert "mask_store.request_tile_async(tx, ty, self.on_tile_ready)" in snippet
    assert "mask_revision = mask_store.tile_revision(tx, ty)" in snippet
    assert "revision = (revision, mask_revision)" in snippet


def test_source_mask_applied_to_a_clone_before_texture_creation():
    snippet = _extract_mask_application_snippet()
    assert "clone_image_native(image)" in snippet
    assert "apply_alpha_mask_native(masked_image, mask)" in snippet
    assert "raise RuntimeError" in snippet
    body = _extract_sync_tile()
    # The masked image (not the raw color tile) must be what gets uploaded,
    # and the color tile must be read before the masking block runs.
    assert "texture = self._create_texture(image, tiled=True)" in body
    tile_read_index = body.index("image = store.tile(tx, ty)")
    mask_block_index = body.index("if mask_revision is not None:")
    texture_index = body.index("texture = self._create_texture(image, tiled=True)")
    assert tile_read_index < mask_block_index < texture_index


def test_source_invalidate_layer_draw_cache_exists_and_pops_the_layer():
    src = GPU_RENDERER_PATH.read_text()
    start = src.index("    def invalidate_layer_draw_cache(")
    end = src.index("    def prune_layers(", start)
    body = src[start:end]
    assert 'self._draw_cache.pop(str(getattr(layer, "id", "__anonymous__")), None)' in body


def test_source_canvas_mask_write_invalidates_the_draw_cache():
    src = CANVAS_PATH.read_text()
    start = src.index("def sync_gpu_layer(")
    write_index = src.index(
        "layer.ensure_alpha_mask().write_image(self._editing_alpha_mask_image, dirty_rect)", start
    )
    tail = src[write_index:write_index + 900]
    assert "self.gpu_renderer.mark_layer_dirty(layer, dirty_rect)" in tail
    assert "self.gpu_renderer.invalidate_layer_draw_cache(layer)" in tail
    mark_index = tail.index("self.gpu_renderer.mark_layer_dirty(layer, dirty_rect)")
    invalidate_index = tail.index("self.gpu_renderer.invalidate_layer_draw_cache(layer)")
    assert mark_index < invalidate_index


def _make_mask_revision_function():
    """Wraps the mask-revision-lookup snippet as a standalone callable, this
    codebase's established pattern (see test_mask_missing_in_cpu_fallback_
    fast_path.py's _make_masking_function) for exercising real method bodies
    without Qt/CreativeCore available in this sandbox.

    The snippet itself reassigns `revision` to the final (color, mask) tuple
    (`revision = (revision, mask_revision)`), and it references
    `self.on_tile_ready` directly (as the real method body does) rather than
    a bare name - so the wrapper's first parameter must literally be named
    `self` for that reference to resolve, and an `initial_revision` seed is
    assigned to `revision` before the snippet runs.
    """
    snippet = _extract_mask_revision_snippet()
    src = ("def _compute(self, layer, tx, ty, initial_revision):\n"
           "        revision = initial_revision\n"
           + snippet
           + "        return revision, mask_revision\n")
    namespace: dict = {"getattr": getattr}
    exec(compile(src, "<mask_revision_snippet>", "exec"), namespace)  # noqa: S102 - real source under test
    return namespace["_compute"]


class _FakeMaskStore:
    def __init__(self, tiles: dict, resident: set | None = None):
        self.tiles = tiles
        self.resident = resident if resident is not None else set(tiles)
        self.requested: list = []

    def has_tile(self, tx, ty):
        return (tx, ty) in self.tiles

    def tile_is_resident(self, tx, ty):
        return (tx, ty) in self.resident

    def tile_revision(self, tx, ty):
        return self.tiles[(tx, ty)]

    def request_tile_async(self, tx, ty, callback):
        self.requested.append((tx, ty, callback))


def test_behavior_no_mask_store_leaves_revision_untouched():
    compute = _make_mask_revision_function()
    layer = SimpleNamespace(alpha_mask_store=None)
    fake_self = SimpleNamespace(on_tile_ready=None)
    result = compute(fake_self, layer, 0, 0, initial_revision=42)
    assert result == ((42, None), None)


def test_behavior_mask_disabled_ignores_an_attached_mask_store():
    compute = _make_mask_revision_function()
    mask_store = _FakeMaskStore({(0, 0): 7})
    layer = SimpleNamespace(alpha_mask_store=mask_store, mask_disabled=True)
    fake_self = SimpleNamespace(on_tile_ready=None)
    result = compute(fake_self, layer, 0, 0, initial_revision=42)
    assert result == ((42, None), None)
    assert mask_store.requested == []


def test_behavior_mask_store_with_no_tile_at_these_coordinates_is_ignored():
    compute = _make_mask_revision_function()
    mask_store = _FakeMaskStore({(1, 1): 7})  # not (0, 0)
    layer = SimpleNamespace(alpha_mask_store=mask_store, mask_disabled=False)
    fake_self = SimpleNamespace(on_tile_ready=None)
    result = compute(fake_self, layer, 0, 0, initial_revision=42)
    assert result == ((42, None), None)


def test_behavior_non_resident_mask_tile_requests_async_and_bails_immediately():
    compute = _make_mask_revision_function()
    mask_store = _FakeMaskStore({(0, 0): 7}, resident=set())
    layer = SimpleNamespace(alpha_mask_store=mask_store, mask_disabled=False)
    callback = object()
    fake_self = SimpleNamespace(on_tile_ready=callback)
    result = compute(fake_self, layer, 0, 0, initial_revision=42)
    # The snippet's own `return None` fires here - sync_tile() bails out of
    # the whole method for this frame, exactly like it already does when the
    # *color* tile isn't resident; the mask tile just gets the same async
    # treatment once it's the one missing.
    assert result is None
    assert mask_store.requested == [(0, 0, callback)]


def test_behavior_resident_mask_tile_is_folded_into_the_revision_tuple():
    compute = _make_mask_revision_function()
    mask_store = _FakeMaskStore({(0, 0): 7})
    layer = SimpleNamespace(alpha_mask_store=mask_store, mask_disabled=False)
    fake_self = SimpleNamespace(on_tile_ready=None)
    result = compute(fake_self, layer, 0, 0, initial_revision=42)
    assert result == ((42, 7), 7)


def _make_masking_function():
    snippet = _extract_mask_application_snippet()
    src = ("def _compute(mask_revision, mask_store, tx, ty, image, "
           "clone_image_native, apply_alpha_mask_native):\n"
           + snippet + "        return image\n")
    namespace: dict = {"getattr": getattr, "RuntimeError": RuntimeError}
    exec(compile(src, "<mask_application_snippet>", "exec"), namespace)  # noqa: S102 - real source under test
    return namespace["_compute"]


class _FakeImage:
    def __init__(self, tag, size=(64, 64)):
        self.tag = tag
        self._size = size

    def size(self):
        return self._size

    def __repr__(self):
        return f"_FakeImage({self.tag!r})"


def test_behavior_no_mask_revision_draws_the_color_tile_unchanged():
    compute = _make_masking_function()
    image = _FakeImage("color_tile")
    calls = []
    result = compute(
        mask_revision=None, mask_store=None, tx=0, ty=0, image=image,
        clone_image_native=lambda img: calls.append(("clone", img)) or img,
        apply_alpha_mask_native=lambda img, mask: calls.append(("apply", img, mask)) or True,
    )
    assert result is image
    assert calls == []


def test_behavior_mask_revision_present_applies_mask_to_a_clone_not_the_original():
    compute = _make_masking_function()
    color_tile = _FakeImage("color_tile", size=(64, 64))
    mask_tile = _FakeImage("mask_tile", size=(64, 64))
    mask_store = SimpleNamespace(tile=lambda tx, ty: mask_tile)
    cloned = _FakeImage("clone", size=(64, 64))
    calls = []

    def fake_clone(img):
        calls.append(("clone", img))
        return cloned

    def fake_apply(img, mask):
        calls.append(("apply", img, mask))
        return True

    result = compute(
        mask_revision=7, mask_store=mask_store, tx=0, ty=0, image=color_tile,
        clone_image_native=fake_clone, apply_alpha_mask_native=fake_apply,
    )
    assert result is cloned
    assert result is not color_tile
    assert calls == [("clone", color_tile), ("apply", cloned, mask_tile)]


def test_behavior_mask_tile_size_mismatch_raises_instead_of_silently_drawing_unmasked():
    compute = _make_masking_function()
    color_tile = _FakeImage("color_tile", size=(64, 64))
    mask_tile = _FakeImage("mask_tile", size=(32, 32))  # deliberately mismatched
    mask_store = SimpleNamespace(tile=lambda tx, ty: mask_tile)
    try:
        compute(
            mask_revision=7, mask_store=mask_store, tx=0, ty=0, image=color_tile,
            clone_image_native=lambda img: _FakeImage("clone", size=(64, 64)),
            apply_alpha_mask_native=lambda img, mask: True,
        )
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_behavior_native_apply_failure_raises():
    compute = _make_masking_function()
    color_tile = _FakeImage("color_tile", size=(64, 64))
    mask_tile = _FakeImage("mask_tile", size=(64, 64))
    mask_store = SimpleNamespace(tile=lambda tx, ty: mask_tile)
    try:
        compute(
            mask_revision=7, mask_store=mask_store, tx=0, ty=0, image=color_tile,
            clone_image_native=lambda img: _FakeImage("clone", size=(64, 64)),
            apply_alpha_mask_native=lambda img, mask: False,  # CreativeCore refuses
        )
        raised = False
    except RuntimeError:
        raised = True
    assert raised


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
