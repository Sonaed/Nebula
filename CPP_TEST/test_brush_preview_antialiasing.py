"""Regression test for the live brush-stroke preview looking jagged/"sharp"
while drawing and only turning smooth once the stylus lifts.

GPUInstancedStrokeRenderer draws each brush dab as a GPU quad while a stroke
is in progress (for performance), then reads the result back into the real
tile store at stroke end - at which point the authoritative, always
anti-aliased native CPU brush kernel takes over for the committed pixels.
The preview shader's edge falloff (FRAGMENT_SHADER's `coverage` calculation)
used to be a pure fraction of the brush's local radius (`1.0 - uHardness`),
with no floor - for hardness 1.0 (a common "hard round"/ink-pen/pencil
setting) that fraction is 0.001, which is sub-pixel for any realistically
sized brush, producing a hard/aliased edge in the live preview only. This
can't be verified by rendering (no GPU/GL context in this environment), so
these tests check the shader source directly: the transition width must be
floored using a screen-space derivative (`fwidth`) so it's never sub-pixel,
regardless of hardness or brush size.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fragment_shader_source() -> str:
    src = (ROOT / "CANVAS" / "gpu_instanced_stroke.py").read_text()
    start = src.index('FRAGMENT_SHADER = """')
    end = src.index('"""', start + len('FRAGMENT_SHADER = """'))
    return src[start:end]


def test_fragment_shader_floors_the_antialiasing_band_with_fwidth():
    shader = _fragment_shader_source()
    assert "fwidth(radius)" in shader
    assert "max(softness, aa)" in shader
    # The smoothstep call must use the floored value, not the raw hardness
    # fraction directly - otherwise the floor is computed but never used.
    assert "smoothstep(1.0 - edgeSoftness, 1.0, radius)" in shader
    assert "smoothstep(1.0 - softness, 1.0, radius)" not in shader


def test_fragment_shader_still_respects_hardness_for_soft_brushes():
    """A genuinely soft brush (low hardness) must keep its full, wide falloff -
    the floor should only ever WIDEN a too-thin band, never narrow a wide one."""
    shader = _fragment_shader_source()
    assert "float softness = max(0.001, 1.0 - uHardness);" in shader
    assert "float aa = fwidth(radius)" in shader
    # `edgeSoftness` must be whichever is LARGER, so a soft brush's wide
    # `softness` still wins over the small `aa` floor.
    idx = shader.index("float edgeSoftness = max(softness, aa);")
    assert idx > shader.index("float softness = max(0.001, 1.0 - uHardness);")
    assert idx > shader.index("float aa = fwidth(radius)")


def test_fragment_shader_braces_balance():
    """Cheap sanity check since no GLSL compiler is available here."""
    shader = _fragment_shader_source()
    assert shader.count("{") == shader.count("}")
    assert shader.count("(") == shader.count(")")
