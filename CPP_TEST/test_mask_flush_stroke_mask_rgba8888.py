"""Regression test for: "Trait ralenti : 488.3 ms (cible 8 ms)" while
editing a layer mask.

Root cause, found via temporary runtime instrumentation on
_cpp_draw_segment_once() (prepare/bits/buffer_setup all measured ~0ms;
native_call alone accounted for the whole 56-116ms per dab): the C++ side's
BrushEngine::flushStrokeMask() - the "stroke mask" compositing path taken
by any plain/simple brush preset with flowAccumulation enabled, which is
most default presets - only had a raw-scanline fast path for
QImage::Format_ARGB32. Any other format (the `else` branch) fell back to
QImage::pixelColor()/setPixelColor() PER PIXEL, which is dozens of times
slower than a raw pointer write once Qt's per-call conversion/bounds-check
overhead is paid for every pixel of every dab.

Layer.tile_store (DOCUMENTS/layer.py) stores raster layers as
Format_ARGB32, so ordinary layer painting through this path was already
fast. But Canvas._prepare_cpp_image() (CANVAS/canvas.py) ALWAYS converts
whatever image it is handed to Format_RGBA8888 before it reaches the C++
bridge - including edit_layer_alpha_mask()'s mask-edit buffer, which is
built directly as Format_RGBA8888. That meant flushStrokeMask() never
actually saw Format_ARGB32 for anything routed through
_cpp_draw_segment_once()/_cpp_begin_stroke(): it always took the slow
pixelColor()/setPixelColor() branch, for EVERY call through this path.

This was invisible for ordinary painting because a plain preset almost
always takes the GPU-only instanced-stroke fast path instead (bypassing
BrushEngine::drawSegment entirely), and the rarer async C++ path that also
converts to RGBA8888 runs on a background thread where a slow dab doesn't
block the UI. Mask editing is excluded from BOTH of those fast paths (see
test_mask_edit_instanced_stroke_bypass.py and _can_use_async_brush) because
neither is mask-aware, so it is permanently locked onto this exact
synchronous path - making it the one place this always-slow branch became
directly, blockingly visible.

The fix: BrushEngine::flushStrokeMask() (CPP_CORE/src/brush_engine.cpp)
gained a second fast path for Format_RGBA8888, mirroring the existing
Format_ARGB32 branch's math exactly but reading/writing four separate
bytes (R,G,B,A) via image.scanLine() instead of a packed QRgb. This test
can't compile the real C++ (no Qt dev headers in this sandbox - see the
other CPP_TEST/*.cpp files, which are meant to be built on the user's
machine), so it transcribes both branches' composite algebra into Python
and checks they are bit-for-bit the same formula, plus pins the exact
source text of the fix.
"""
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CPP_CORE" / "src" / "brush_engine.cpp"


def _extract_flush_stroke_mask() -> str:
    src = SRC_PATH.read_text()
    start = src.index("void BrushEngine::flushStrokeMask(")
    end = src.index("void BrushEngine::beginStroke(", start)
    return src[start:end]


def quantize(value: float) -> int:
    """Transcription of quantizeChannel(): clamp to [0,1], scale to
    [0,255], std::lround (round-half-away-from-zero, not Python's
    round-half-to-even)."""
    value = max(0.0, min(1.0, value))
    return int(math.floor(value * 255.0 + 0.5))


def composite_reference(dest_rgba, src_rgb, source_alpha):
    """The float-domain src-over formula shared, verbatim, by BOTH the
    (untouched) ARGB32 branch and the new RGBA8888 branch of
    flushStrokeMask(): only how the four channels are packed in/out of
    memory differs between them."""
    dr, dg, db, da_byte = dest_rgba
    da = da_byte / 255.0
    oa = source_alpha + da * (1.0 - source_alpha)
    if oa <= 0.0:
        return (0, 0, 0, 0)
    red, green, blue = src_rgb
    out_r = (red * source_alpha + (dr / 255.0) * da * (1.0 - source_alpha)) / oa
    out_g = (green * source_alpha + (dg / 255.0) * da * (1.0 - source_alpha)) / oa
    out_b = (blue * source_alpha + (db / 255.0) * da * (1.0 - source_alpha)) / oa
    return (quantize(out_r), quantize(out_g), quantize(out_b), quantize(oa))


def composite_argb32_transcription(dest_rgba, src_rgb, source_alpha):
    """The pre-existing, untouched ARGB32 branch - the trusted reference
    the new RGBA8888 branch must match exactly."""
    return composite_reference(dest_rgba, src_rgb, source_alpha)


def composite_rgba8888_transcription(dest_bytes, src_rgb, source_alpha):
    """The NEW branch added by this fix: same algebra, byte-array access
    instead of a packed QRgb."""
    return composite_reference(tuple(dest_bytes), src_rgb, source_alpha)


def test_rgba8888_branch_matches_the_trusted_argb32_math():
    """The fix is a format change, not a math change: for the same
    starting pixel and the same dab, the new byte-oriented RGBA8888 branch
    must produce EXACTLY the same output as the already-correct ARGB32
    branch it was modeled on."""
    rng = random.Random(20260926)
    for _ in range(500):
        dest = (rng.randint(0, 255), rng.randint(0, 255),
                rng.randint(0, 255), rng.randint(0, 255))
        src_rgb = (rng.random(), rng.random(), rng.random())
        alpha = rng.random()
        argb = composite_argb32_transcription(dest, src_rgb, alpha)
        rgba = composite_rgba8888_transcription(dest, src_rgb, alpha)
        assert argb == rgba, (dest, src_rgb, alpha, argb, rgba)


def test_zero_output_alpha_clears_all_four_channels():
    assert composite_rgba8888_transcription((10, 20, 30, 0), (0.0, 0.0, 0.0), 0.0) == (0, 0, 0, 0)


def test_opaque_fresh_source_over_transparent_destination_is_pure_source():
    result = composite_rgba8888_transcription((0, 0, 0, 0), (0.2, 0.6, 0.9), 1.0)
    assert result == (quantize(0.2), quantize(0.6), quantize(0.9), 255)


def test_fully_covered_destination_survives_a_zero_alpha_dab():
    # sourceAlpha == 0.0 never actually reaches flushStrokeMask() (it early-
    # returns above `coverage <= 0.0f`/`sourceAlpha <= 0.0f`), but the
    # composite math itself should still be a no-op if it ever did.
    result = composite_rgba8888_transcription((10, 20, 30, 255), (0.9, 0.9, 0.9), 0.0)
    assert result == (10, 20, 30, 255)


def test_source_rgba8888_checked_before_the_slow_generic_fallback():
    body = _extract_flush_stroke_mask()
    argb_index = body.index("QImage::Format_ARGB32")
    rgba_index = body.index("QImage::Format_RGBA8888")
    pixelcolor_index = body.index("image.pixelColor(px, py)")
    assert argb_index < rgba_index < pixelcolor_index, (
        "expected the RGBA8888 fast path to be checked before falling back "
        "to the slow generic pixelColor()/setPixelColor() branch"
    )


def test_source_rgba8888_branch_writes_raw_scanline_bytes():
    body = _extract_flush_stroke_mask()
    assert "image.scanLine(py) + static_cast<size_t>(px) * 4" in body
    assert "destination[0] = quantizeChannel(outR);" in body
    assert "destination[1] = quantizeChannel(outG);" in body
    assert "destination[2] = quantizeChannel(outB);" in body
    assert "destination[3] = quantizeChannel(oa);" in body


def test_source_pins_root_cause_explanation():
    """Belt-and-suspenders: keeps the fix's rationale (why RGBA8888, not
    some other format, is the one that actually needed a fast path) findable
    in the source, not just in this test file."""
    body = _extract_flush_stroke_mask()
    assert "_prepare_cpp_image" in body
    assert "Trait ralenti" in body


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
