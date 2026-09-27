"""Regression test for: "avec oil flat / dry brush / pencil / etc., meme
avec de la couleur choisie, il n'y en a pas - c'est ce truc gris/bizarre."

Root cause: in BrushTip::draw() (CPP_CORE/src/brush_tip.cpp), every dab
starts with `QColor dabColor = color;` (the user's actual selected paint
color) - correct. But for any preset that uses a bitmap tip (Pencil HB/2B,
Col Erase, Charcoal, Chalk, Conte, Dry Brush, Oil Flat, Watercolor, Spray,
Stipple - see the `tips = {...}` table in TOOLS/brush_preset_manager.py),
the code samples the tip bitmap and correctly pulls its ALPHA channel out
to modulate coverage/shape (`tipAlpha`, used to scale `finalAlpha`) - and
then, immediately after, overwrote dabColor with the *whole* sampled pixel:

    dabColor = QColor::fromRgba(tipPixel);

Every built-in bitmap tip is rendered pure grayscale by
_render_builtin_bitmap_tip() in brush_preset_manager.py
(`image.setPixelColor(x, y, QColor(value, value, value, value))`, i.e.
R=G=B=A=value for every pixel). So that line silently threw away the user's
selected color on every single pixel of every bitmap-tip preset and
replaced it with a gray/black/white value taken from the tip texture's own
render - producing exactly the "grayscale/textured, no color at all" result
reported, regardless of what color was selected. Oil Round has no bitmap
tip (absent from the `tips` dict) and was never affected, matching the
user's own observation that it "marche mieux".

The bitmap tip is a SHAPE MASK: only its alpha channel carries information
that should affect the final pixel (coverage), exactly like the analytic
hardness/roundness falloff computed earlier in the same function. Its RGB
channels are not meaningful paint color and must never reach the canvas.

The fix removes the `dabColor = QColor::fromRgba(tipPixel);` line entirely:
dabColor stays `color` regardless of whether a bitmap tip is present; only
`tipAlpha` (already correctly extracted) continues to scale `finalAlpha`.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CPP_CORE" / "src" / "brush_tip.cpp"


def _dab_loop_body():
    src = SRC_PATH.read_text()
    start = src.index("            QColor dabColor = color;")
    end = src.index("            if (settings.textureAffectOpacity)")
    return src[start:end]


def select_dab_color_and_alpha(color_rgba, tip_pixel_rgba, base_alpha, antialiasing):
    """Transcription of the (fixed) per-pixel branch in BrushTip::draw():
    dabColor always starts and stays as `color`; a bitmap tip only ever
    contributes its alpha channel, scaling finalAlpha - exactly mirroring
    the C++ control flow, just with tuples instead of QColor/QRgb."""
    dab_color = color_rgba
    final_alpha = base_alpha
    if tip_pixel_rgba is not None:
        tip_alpha = tip_pixel_rgba[3] / 255.0
        final_alpha *= tip_alpha if antialiasing else (1.0 if tip_alpha >= 0.5 else 0.0)
        # dab_color intentionally NOT reassigned from tip_pixel_rgba.
    return dab_color, final_alpha


def select_dab_color_and_alpha_PRE_FIX(color_rgba, tip_pixel_rgba, base_alpha, antialiasing):
    """The buggy behavior being regression-tested against, transcribed
    verbatim from the removed line so the test can prove it used to fail
    (and would fail again if ever reintroduced)."""
    dab_color = color_rgba
    final_alpha = base_alpha
    if tip_pixel_rgba is not None:
        tip_alpha = tip_pixel_rgba[3] / 255.0
        final_alpha *= tip_alpha if antialiasing else (1.0 if tip_alpha >= 0.5 else 0.0)
        dab_color = tip_pixel_rgba  # <-- the bug: QColor::fromRgba(tipPixel)
    return dab_color, final_alpha


RED = (255, 0, 0, 255)
# A representative sample from a real built-in bitmap tip: pure grayscale,
# R=G=B=A=value, per _render_builtin_bitmap_tip in brush_preset_manager.py.
GRAY_TIP_PIXEL = (168, 168, 168, 168)


def test_bitmap_tip_preset_keeps_the_users_selected_color():
    dab_color, alpha = select_dab_color_and_alpha(RED, GRAY_TIP_PIXEL, base_alpha=1.0, antialiasing=True)
    assert dab_color == RED, (
        "a bitmap-tip preset (Oil Flat, Dry Brush, Pencil, Charcoal, ...) "
        "must paint in the color the user selected, not the tip texture's "
        "own grayscale render"
    )
    # The tip's alpha channel must still be doing its job (shape/coverage).
    assert abs(alpha - (168 / 255.0)) < 1e-6


def test_no_bitmap_tip_is_unaffected():
    """Oil Round and any other tip-less preset: dab_color/alpha both pass
    through unchanged, confirming the fix doesn't touch that path at all."""
    dab_color, alpha = select_dab_color_and_alpha(RED, None, base_alpha=0.8, antialiasing=True)
    assert dab_color == RED
    assert alpha == 0.8


def test_non_antialiased_bitmap_tip_still_keeps_color():
    """The pixel-art (antialiasing=False) branch takes a different path for
    alpha (hard 0/1 threshold) but must still never touch dab_color."""
    dab_color, alpha = select_dab_color_and_alpha(RED, GRAY_TIP_PIXEL, base_alpha=1.0, antialiasing=False)
    assert dab_color == RED
    assert alpha == 1.0  # 168/255 >= 0.5 -> thresholds to full coverage


def test_pre_fix_transcription_reproduces_the_reported_bug():
    """Proves this test suite actually discriminates: the old logic really
    did discard the selected color in favor of the tip's own gray pixel."""
    dab_color, _ = select_dab_color_and_alpha_PRE_FIX(RED, GRAY_TIP_PIXEL, base_alpha=1.0, antialiasing=True)
    assert dab_color == GRAY_TIP_PIXEL
    assert dab_color != RED


def test_source_no_longer_overwrites_dab_color_from_the_bitmap_tip():
    """Pins the actual fix in brush_tip.cpp: the per-pixel branch must set
    dabColor from `color` and never reassign it from the sampled tip pixel."""
    body = _dab_loop_body()
    assert "QColor dabColor = color;" in body
    assert "dabColor = QColor::fromRgba(tipPixel)" not in body, (
        "the bitmap-tip color-overwrite bug has been reintroduced: dabColor "
        "must only ever come from `color`, never from the tip texture's own "
        "(grayscale) pixel value"
    )
    # The alpha channel must still be the one thing pulled from the tip.
    assert "tipAlpha" in body and "finalAlpha *=" in body


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
