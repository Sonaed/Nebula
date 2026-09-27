"""Regression test for the root cause behind "mask layers still not working"
(user report, after fixes #7-#10 had already made the mask WRITE path, the
mask thumbnail cache, and its invalidation wiring all provably correct).

Five separate rounds of empirical runtime tracing ([maskdbg2] through
[maskdbg5]) were needed to find this, because every plausible suspect turned
out clean: the mask paint itself (bail_out=True on the instanced-stroke fast
path, sync_gpu_layer's mask branch firing with correct dirty_rect/
updated_tiles on every dab), the thumbnail cache invalidation and
materialize() call (a full 36x36-thumbnail pixel scan showed dozens of
freshly-painted pixels appearing exactly when expected), and the delegate
that paints the thumbnail (fresh QPixmap identities on every repaint). None
of that explained why the canvas itself, or the thumbnail on screen, never
visibly changed.

The actual answer: this app has FOUR different rendering paths for the
canvas, not two.
  1. GPUTileCompositor.compose_tile()/_draw_stack() - GPU shader compositing,
     samples alpha_mask_store and binds it as uMask.
  2. Canvas._ensure_projection()/_projection_tile_for_layer() - the CPU tile
     path, calls apply_alpha_mask_native per tile.
  3. _paint_cpu_fallback()'s "advanced" branch (has_non_normal(document) or
     document.layer_groups) - routes through _ensure_projection() too.
  4. _paint_cpu_fallback()'s FAST simple per-layer loop, taken whenever
     none of the above "advanced" conditions apply - which is exactly the
     common case this bug report hit: one raster layer, "normal" blend mode,
     no clipping, no groups, with an alpha mask attached.

An unconditional diagnostic print placed at the very entry of
GPUTileCompositor.compose_tile() never fired once in the user's traces, and
neither did one placed inside _ensure_projection() gated only on "a mask is
currently being edited" (true for the whole duration of every stroke this
test paints). That proved paths 1-3 were never reached at all for this
setup, leaving only path 4 - which drew `layer.image` directly with
painter.drawImage() and never so much as looked at layer.alpha_mask_store.
Every other symptom (correct mask data, correct thumbnail, no canvas
change) is explained by this one gap.

The fix mirrors _projection_tile_for_layer's own masking logic (clone the
image, apply the mask via CreativeCore's apply_alpha_mask_native, raise
rather than silently draw unmasked on any failure) for the whole flattened
layer image instead of per-tile, and draws the resulting `image` variable
in both of the loop's drawImage() call sites (the transform-preview branch
and the plain branch both used to draw the raw, unmasked layer.image).
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CANVAS_PATH = ROOT / "CANVAS" / "canvas.py"


def _extract_paint_cpu_fallback() -> str:
    src = CANVAS_PATH.read_text()
    start = src.index("    def _paint_cpu_fallback(")
    end = src.index("    def _preview_brush_shape(", start)
    return src[start:end]


def _extract_mask_application_snippet() -> str:
    body = _extract_paint_cpu_fallback()
    start = body.index("            image = layer.image\n")
    end = body.index("            is_transform_preview = (")
    return body[start:end]


def test_source_fast_path_draws_the_computed_image_not_layer_image_directly():
    body = _extract_paint_cpu_fallback()
    # Both drawImage() call sites (transform-preview branch and the plain
    # branch) must draw the locally-computed `image` variable now, not the
    # raw layer.image property - that swap is the actual fix.
    assert body.count("painter.drawImage(\n                    0,\n                    0,\n                    image\n                )") == 2
    assert "painter.drawImage(\n                    0,\n                    0,\n                    layer.image\n                )" not in body


def test_source_checks_alpha_mask_store_and_mask_disabled():
    snippet = _extract_mask_application_snippet()
    assert 'mask_store = getattr(layer, "alpha_mask_store", None)' in snippet
    assert 'getattr(layer, "mask_disabled", False)' in snippet
    assert "clone_image_native(image)" in snippet
    assert "apply_alpha_mask_native(masked_image, mask)" in snippet
    assert "raise RuntimeError" in snippet


def test_source_masking_is_computed_before_the_transform_preview_branch():
    body = _extract_paint_cpu_fallback()
    # Both branches need the masked image, so it must be computed once,
    # before the is_transform_preview fork, not duplicated into each branch.
    mask_index = body.index('mask_store = getattr(layer, "alpha_mask_store", None)')
    transform_index = body.index("is_transform_preview = (")
    assert mask_index < transform_index


def _make_masking_function():
    """Wraps the extracted mask-application snippet as a standalone callable
    over a controlled layer/image/native-bridge-fake namespace - this
    codebase's established pattern for exercising real method bodies without
    Qt/CreativeCore available in this sandbox (see e.g.
    test_layer_thumbnail_refresh_after_stroke.py's _as_callable)."""
    snippet = _extract_mask_application_snippet()
    # The extracted snippet keeps its original 12-space indentation (method
    # body + for-loop body), so the trailing return must match it rather
    # than the usual 4-space function-body convention.
    src = ("def _compute(layer, image, clone_image_native, apply_alpha_mask_native):\n"
           + snippet + "            return image\n")
    namespace: dict = {"getattr": getattr, "RuntimeError": RuntimeError}
    exec(compile(src, "<mask_application_snippet>", "exec"), namespace)  # noqa: S102 - real source under test
    return namespace["_compute"]


class _FakeImage:
    def __init__(self, tag, size=(10, 10)):
        self.tag = tag
        self._size = size

    def size(self):
        return self._size

    def __repr__(self):
        return f"_FakeImage({self.tag!r})"


def test_behavior_no_mask_store_draws_layer_image_unchanged():
    compute = _make_masking_function()
    layer = SimpleNamespace(image=_FakeImage("original"), alpha_mask_store=None)
    calls = []
    result = compute(
        layer, layer.image,
        clone_image_native=lambda img: calls.append(("clone", img)) or img,
        apply_alpha_mask_native=lambda img, mask: calls.append(("apply", img, mask)) or True,
    )
    assert result is layer.image
    assert calls == []


def test_behavior_mask_disabled_skips_masking_even_with_a_mask_store():
    compute = _make_masking_function()
    layer = SimpleNamespace(image=_FakeImage("original"), alpha_mask_store=object(), mask_disabled=True)
    calls = []
    result = compute(
        layer, layer.image,
        clone_image_native=lambda img: calls.append(("clone", img)) or img,
        apply_alpha_mask_native=lambda img, mask: calls.append(("apply", img, mask)) or True,
    )
    assert result is layer.image
    assert calls == []


def test_behavior_mask_store_applies_mask_to_a_clone_not_the_original():
    compute = _make_masking_function()
    mask_image = _FakeImage("mask", size=(10, 10))
    mask_store = SimpleNamespace(materialize=lambda: mask_image)
    layer = SimpleNamespace(image=_FakeImage("original", size=(10, 10)), alpha_mask_store=mask_store)
    cloned = _FakeImage("clone", size=(10, 10))
    calls = []

    def fake_clone(img):
        calls.append(("clone", img))
        return cloned

    def fake_apply(img, mask):
        calls.append(("apply", img, mask))
        return True

    result = compute(layer, layer.image, clone_image_native=fake_clone, apply_alpha_mask_native=fake_apply)
    assert result is cloned
    assert result is not layer.image
    assert calls == [("clone", layer.image), ("apply", cloned, mask_image)]


def test_behavior_size_mismatch_raises_instead_of_silently_drawing_unmasked():
    compute = _make_masking_function()
    mask_image = _FakeImage("mask", size=(5, 5))  # deliberately mismatched
    mask_store = SimpleNamespace(materialize=lambda: mask_image)
    layer = SimpleNamespace(image=_FakeImage("original", size=(10, 10)), alpha_mask_store=mask_store)
    try:
        compute(
            layer, layer.image,
            clone_image_native=lambda img: _FakeImage("clone", size=(10, 10)),
            apply_alpha_mask_native=lambda img, mask: True,
        )
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "a mask/image size mismatch must raise, not silently draw unmasked"


def test_behavior_native_apply_failure_raises():
    compute = _make_masking_function()
    mask_image = _FakeImage("mask", size=(10, 10))
    mask_store = SimpleNamespace(materialize=lambda: mask_image)
    layer = SimpleNamespace(image=_FakeImage("original", size=(10, 10)), alpha_mask_store=mask_store)
    try:
        compute(
            layer, layer.image,
            clone_image_native=lambda img: _FakeImage("clone", size=(10, 10)),
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
