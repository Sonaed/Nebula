"""Regression test for: "j'ai l'impression de faire un masque et ensuite
j'ai le final de ce a quoi ca ressemble" - painting with a wet-mix brush
(Oil Round, Oil Flat, Watercolor, ...) or the Smudge tool looked like a flat,
featureless stamp for the entire stroke, only "revealing" the real,
wet-blended result once the stylus lifted.

Root cause: on TabletPress, whenever the async brush path is used (the
normal path for stylus painting - see _begin_async_brush), Canvas ALSO
started a GPUInstancedStrokeRenderer preview
(gpu_instanced_stroke.py:begin_preview) purely for input latency reasons.
That preview is explicitly a flat approximation - it zeroes wetness,
pickup, dilution and smudge and forces roundness=1/blendMode=Normal before
drawing round dabs (see begin_preview's own docstring: "Complex dynamics
are intentionally ignored... so input feedback stays immediate").

The trouble is *how* that preview gets shown: Canvas.paintGL passes the
preview's FBO texture as `texture_override_id` to gpu_renderer.draw_layer,
which renders the layer's ENTIRE visible area from that texture instead of
the real tile_store - for as long as the preview stays active, i.e. the
whole stroke. Meanwhile _apply_async_brush_patch is already writing the
real, correctly wet-blended pixels into layer.tile_store live, dab by dab,
the entire time - they are simply never shown, because the flat preview
FBO is drawn on top of (in place of) the whole layer until
GPUInstancedStrokeRenderer.request_finish()/process() releases it at
TabletRelease.

The fix: don't start the flat preview override at all when this stroke is
wet-mix (wetMix and wetness > 0) or uses the Smudge tool - for those, skip
straight to relying on the real async patches, which are already streamed
live and are the actual final pixels, not an approximation of them. Plain
(non-wet) brush/eraser strokes keep the existing flat preview, since for
those "fresh color" already equals the final color, so the preview was
never inaccurate for them in the first place.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CANVAS" / "canvas.py"


def _extract_press_preview_block() -> str:
    """Pulls the exact block (real source, not a transcription) that
    decides whether to start the GPU preview override, from the
    TabletPress handler in Canvas.tabletEvent."""
    src = SRC_PATH.read_text()
    start_anchor = "                preview_settings = self.brush_settings.snapshot()"
    end_anchor = "\n                event.accept()\n                return\n"
    start = src.index(start_anchor)
    end = src.index(end_anchor, start) + len(end_anchor)
    return src[start:end]


def _run(settings: dict, current_tool: str, gpu_ready: bool = True):
    import textwrap

    block = "def _probe():\n" + textwrap.indent(_extract_press_preview_block(), "    ")

    calls = {"begin_preview": None, "update": 0}

    class FakeStroke:
        def begin_preview(self, layer, image, settings, position, pressure, eraser=False):
            calls["begin_preview"] = {
                "layer": layer, "image": image, "settings": settings,
                "position": position, "pressure": pressure, "eraser": eraser,
            }
            return True

    fake_self = SimpleNamespace(
        brush_settings=SimpleNamespace(snapshot=lambda: dict(settings)),
        tools=SimpleNamespace(current_tool=current_tool),
        gpu_ready=gpu_ready,
        gpu_instanced_stroke=FakeStroke(),
        update=lambda: calls.__setitem__("update", calls["update"] + 1),
    )

    class FakeEvent:
        def accept(self):
            pass

    namespace = {
        "self": fake_self,
        "layer": SimpleNamespace(image="fake-image"),
        "position": SimpleNamespace(),
        "pressure": 1.0,
        "event": FakeEvent(),
    }
    exec(compile(block, "<preview-block>", "exec"), namespace)
    namespace["_probe"]()
    return calls


def test_wet_mix_preset_skips_the_flat_preview_override():
    """Oil Round/Oil Flat/Watercolor-style settings: wetMix true, wetness
    > 0 - the flat GPU preview must NOT engage, so the real async patches
    are the only thing drawn."""
    calls = _run({"wetMix": True, "wetness": 0.55, "pickup": 0.45}, current_tool="brush")
    assert calls["begin_preview"] is None


def test_smudge_tool_skips_the_flat_preview_override():
    calls = _run({"wetMix": False, "wetness": 0.0}, current_tool="smudge")
    assert calls["begin_preview"] is None


def test_wet_mix_flag_without_positive_wetness_still_previews():
    """wetMix=True but wetness=0 is the same "no wet effect at all" case
    BrushWet::update() itself treats as a no-op (early return in the C++
    code) - the preview gate mirrors that, not just the raw flag."""
    calls = _run({"wetMix": True, "wetness": 0.0}, current_tool="brush")
    assert calls["begin_preview"] is not None


def test_plain_dry_brush_keeps_the_existing_flat_preview():
    """Must NOT regress the ordinary case: a normal (non-wet) brush/eraser
    stroke keeps using the instant flat preview exactly as before, since
    fresh color already equals final color for it."""
    calls = _run({"wetMix": False, "wetness": 0.0}, current_tool="brush")
    assert calls["begin_preview"] is not None
    assert calls["begin_preview"]["eraser"] is False


def test_source_gates_begin_preview_on_wet_mix_and_smudge_tool():
    """Pins the fix in canvas.py: begin_preview's call site must check both
    conditions before the GPU-ready check that used to be the only gate."""
    src = SRC_PATH.read_text()
    assert "wet_mix_active" in src
    assert "smudge_active" in src
    assert 'self.tools.current_tool == "smudge"' in src
    guard_index = src.index("if self.gpu_ready and not wet_mix_active and not smudge_active:")
    assert guard_index > 0, "expected begin_preview's call site to check wet_mix_active/smudge_active"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
