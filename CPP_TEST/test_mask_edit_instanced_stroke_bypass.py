"""Regression test for: "j'ai essaye d'editer le masque et rien" - the click
hit-test fix (test_layer_mask_click_hit_test.py) made entering mask-edit
mode reliable (confirmed via the "Masque actif" status message and live
[maskdbg] traces), but painting on the mask still visibly did nothing.

Root cause, found via temporary runtime instrumentation: TabletPress/
mousePressEvent in Canvas try THREE different fast paths, in this order,
before falling back to the synchronous CreativeCore draw that
get_active_image()/sync_gpu_layer() are mask-aware for:

    1. _try_begin_instanced_stroke  - a GPU-only path for simple/plain
       brush presets (GPUInstancedStrokeRenderer)
    2. _can_use_async_brush + _begin_async_brush - the normal async stylus
       path
    3. the synchronous _cpp_begin_stroke/_cpp_draw_segment path, which IS
       mask-aware (get_active_image() returns _editing_alpha_mask_image,
       and sync_gpu_layer() redirects the commit to
       layer.ensure_alpha_mask().write_image(...))

_can_use_async_brush already excluded mask editing
(`self._editing_alpha_mask_layer_id != layer.id`). _try_begin_instanced_
stroke did NOT - it has no concept of mask editing at all.
GPUInstancedStrokeRenderer.begin() is handed `layer.image` (the REAL layer
pixels) directly, and its eventual commit (_commit_readback in
gpu_instanced_stroke.py) paints straight back into `layer.image`/
`layer.tile_store`.

Any plain/simple brush preset - roundness~1, no wet-mix, normal blend mode,
no adaptive spacing/texture/stroke-gradient/dirty-color, i.e. most default
presets - qualifies for GPUInstancedStrokeRenderer.supports(). So painting
with one of those while editing a mask used to silently divert the ENTIRE
stroke onto the layer's real pixels instead of the mask buffer: the mask
itself never changed at all (which is exactly "je peins sur le masque et il
ne se passe rien"), while the layer's actual content was quietly being
painted on instead, invisibly to anyone watching the mask thumbnail.

The fix: _try_begin_instanced_stroke now excludes mask editing the same way
_can_use_async_brush already does, so a mask-editing stroke always falls
through to the mask-aware synchronous path.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CANVAS" / "canvas.py"


def _extract_guard_condition() -> str:
    """Pulls the exact if-condition (real source) that
    _try_begin_instanced_stroke uses to bail out early."""
    src = SRC_PATH.read_text()
    start = src.index("    def _try_begin_instanced_stroke(")
    cond_start = src.index("if (", start) + len("if ")
    end_marker = "):\n            return False"
    cond_end = src.index(end_marker, cond_start) + 1  # +1 to include the final ")"
    return src[cond_start:cond_end]


def _evaluate_guard(*, editing_mask_layer_id, layer_id, layer_lock_alpha=False,
                    gpu_shader_strokes_enabled=True, smoothing=0.0, gpu_ready=True,
                    use_gpu=True, transforming=False, layer_groups=(),
                    has_non_normal=False, selection_empty=True):
    """Evaluates the real guard expression (extracted from source, not
    retyped) against a fully-controlled fake `self`/`layer`, isolating just
    the mask-editing exclusion this test cares about."""
    condition_src = _extract_guard_condition()

    fake_layer = SimpleNamespace(id=layer_id, lock_alpha=layer_lock_alpha)
    fake_document = SimpleNamespace(
        layer_groups=layer_groups,
        selection=SimpleNamespace(is_empty=lambda: selection_empty),
    )
    fake_self = SimpleNamespace(
        tools=SimpleNamespace(brush=SimpleNamespace(smoothing=smoothing)),
        gpu_ready=gpu_ready,
        use_gpu=use_gpu,
        transforming=transforming,
        document=fake_document,
        _editing_alpha_mask_layer_id=editing_mask_layer_id,
    )
    namespace = {
        "self": fake_self,
        "layer": fake_layer,
        "GPU_SHADER_STROKES_ENABLED": gpu_shader_strokes_enabled,
        "has_non_normal": lambda document: has_non_normal,
        "getattr": getattr,
        "float": float,
    }
    return eval(condition_src, namespace)  # noqa: S307 - real source expression under test


def test_bail_out_condition_true_while_editing_this_layers_mask():
    """The actual fix: when the active layer's mask is being edited, the
    early-out condition must be True (i.e. _try_begin_instanced_stroke bails
    out, letting the mask-aware synchronous path handle the stroke)."""
    bail_out = _evaluate_guard(editing_mask_layer_id="layer-1", layer_id="layer-1")
    assert bail_out is True


def test_bail_out_condition_false_for_a_plain_stroke_not_editing_any_mask():
    """Must not regress the ordinary case: no mask being edited at all, a
    plain qualifying brush preset should still take the fast instanced-
    stroke path exactly as before."""
    bail_out = _evaluate_guard(editing_mask_layer_id=None, layer_id="layer-1")
    assert bail_out is False


def test_bail_out_condition_false_when_editing_a_different_layers_mask():
    """Editing layer B's mask while painting on layer A (not the same
    layer) must not block layer A's ordinary fast-path painting."""
    bail_out = _evaluate_guard(editing_mask_layer_id="layer-2", layer_id="layer-1")
    assert bail_out is False


def test_source_excludes_instanced_stroke_during_mask_editing():
    """Pins the fix in canvas.py: the guard must compare
    _editing_alpha_mask_layer_id against the layer being painted on, the
    same way _can_use_async_brush already does."""
    src = SRC_PATH.read_text()
    assert 'self._editing_alpha_mask_layer_id == getattr(layer, "id", None)' in src, (
        "expected _try_begin_instanced_stroke's bail-out condition to "
        "exclude the layer currently being edited as a mask"
    )
    method_start = src.index("def _try_begin_instanced_stroke(")
    method_body = src[method_start:method_start + 2500]
    assert "_editing_alpha_mask_layer_id" in method_body, (
        "the mask-editing check must live inside _try_begin_instanced_stroke "
        "itself, not somewhere unrelated"
    )


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
