"""Regression test for: "le wet mix est encore tres tres faible" (still very
very weak), reported again AFTER the coverage-ceiling fix (see
test_wet_coverage_ceiling.py) had already landed and been rebuilt.

The coverage fix was real and correct - it let `surfaceCoverage` reach ~1
instead of ceilinging at ~0.33 - but it wasn't the whole story.
BrushWet::update()'s reservoir blend (CPP_CORE/src/brush_wet.cpp) mixes
three weights every dab:

    freshWeight  - fresh, currently-selected paint color
    carryWeight  - color the brush is already carrying (m_color, previous
                   dabs' blend)
    pickupWeight - color sampled from the canvas underneath (gated by
                   surfaceCoverage)

`carryWeight` and `pickupWeight` both scale UP with `settings.wetness`, as
you'd expect ("wetter" -> more blending). But `freshWeight` was computed
from pressure and dilution ONLY - completely independent of wetness or
pickup:

    freshWeight = clamp01(0.18 + 0.82*p) * (1 - 0.45*dilution)

Working the reservoir's fixed point through algebraically (see
docstring math below / the comment now in brush_wet.cpp): even with
surfaceCoverage fixed at its new post-fix ceiling of ~1.0, wetness=pickup=1,
full pressure, painting an unbounded number of fully-overlapping dabs over a
single fully opaque patch of a different color, the blend could never
converge past roughly 50/50 toward the canvas color - because every dab
kept re-injecting ~0.91 weight of pure fresh color regardless of how "wet"
the brush was set. A normal single-pass stroke (dabs only partially
overlapping, not revisiting the same pixel indefinitely) lands far short of
even that ceiling, which reads as "barely tinted" - matching what was
reported.

The fix: freshWeight now tapers down with wetness using the exact inverse
of the shape carryWeight already scales up with - (1.0 - 0.65*wet) instead
of carryWeight's (0.35 + 0.65*wet) - so a fully wet brush sheds as much
"lay down pure fresh paint" weight as it gains in carried/picked-up weight,
instead of keeping fresh deposit pinned at full strength no matter what
wetness/pickup are set to.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CPP_CORE" / "src" / "brush_wet.cpp"


def clamp01(v):
    return max(0.0, min(1.0, v))


def simulate_steady_state_blend(
    *,
    fresh_weight_tapers_with_wetness: bool,
    dabs: int = 400,
    wetness: float = 1.0,
    pickup: float = 1.0,
    dilution: float = 0.2,
    color_carry: float = 0.8,
    paint_persistence: float = 0.75,
    pressure: float = 1.0,
    coverage: float = 1.0,
):
    """Transcription of BrushWet::update()'s reservoir math (the wetMix
    branch only), scalar-channel (0=canvas color, 1=fresh/selected color),
    run for `dabs` iterations directly over a fixed, fully-opaque patch of
    the opposite color - the single most favourable case for the pickup
    effect to show up in. Returns the final m_color (1.0 = pure fresh/
    selected color, 0.0 = fully picked up the canvas color underneath)."""
    p = clamp01(pressure)
    wet = clamp01(wetness)

    m_color = 1.0  # begin(): m_color = baseColor (the selected/fresh color)
    m_paint_load = clamp01(0.35 + 0.65 * paint_persistence)  # begin()
    canvas_color = 0.0  # a fully opaque patch of the *other* color
    fresh_color = 1.0

    base_fresh = clamp01(0.18 + 0.82 * p) * (1.0 - 0.45 * clamp01(dilution))
    fresh_weight = (
        base_fresh * (1.0 - 0.65 * wet)
        if fresh_weight_tapers_with_wetness
        else base_fresh
    )

    for _ in range(dabs):
        carry_weight = clamp01(m_paint_load * color_carry * (0.35 + 0.65 * wet))
        pickup_weight = clamp01(pickup * wet * p * (1.0 - dilution)) * coverage
        total = fresh_weight + carry_weight + pickup_weight
        if total > 0.0:
            fresh_ratio = fresh_weight / total
            carry_ratio = carry_weight / total
            pickup_ratio = pickup_weight / total
            m_color = (
                fresh_color * fresh_ratio
                + m_color * carry_ratio
                + canvas_color * pickup_ratio
            )
        retained = m_paint_load * clamp01(paint_persistence)
        picked = pickup_weight * (0.55 + 0.45 * color_carry)
        fresh = fresh_weight * (0.65 + 0.35 * p)
        m_paint_load = clamp01(retained + picked + fresh)

    return m_color


def test_old_formula_ceilings_near_fifty_fifty_even_at_max_settings_infinite_overlap():
    """Confirms the analysis: even in the best possible case for the OLD
    (wetness-independent) freshWeight - maxed wetness/pickup, full pressure,
    fully opaque coverage, hundreds of fully-overlapping dabs - the blend
    can't converge past roughly halfway to the canvas color."""
    final = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=False)
    assert 0.50 < final < 0.56, (
        f"expected the old formula's asymptote to sit near 0.53 (roughly "
        f"50/50), got {final}"
    )


def test_new_formula_converges_much_further_toward_the_canvas_color():
    """Same best-case scenario, new formula: the fix should let the blend
    converge much further toward the canvas color (a lower value = more of
    the underlying color picked up), not just marginally."""
    final = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=True)
    assert final < 0.35, (
        f"expected the fixed formula to converge well past the old ~0.53 "
        f"ceiling, got {final}"
    )


def test_new_formula_is_meaningfully_stronger_than_old_at_max_wetness_pickup():
    old = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=False)
    new = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=True)
    # "how far toward the canvas color did we get" - old ~= 1-0.53=0.47,
    # new should be comfortably at least 1.4x that.
    old_pickup_fraction = 1.0 - old
    new_pickup_fraction = 1.0 - new
    assert new_pickup_fraction > old_pickup_fraction * 1.4, (
        f"expected a meaningfully stronger pickup effect: old reached "
        f"{old_pickup_fraction:.3f} of the way to the canvas color, new "
        f"reached {new_pickup_fraction:.3f}"
    )


def test_zero_wetness_is_unaffected_by_the_change():
    """At wetness=0 this function is unreached at all in the real code (the
    early `if (!settings.wetMix || settings.wetness <= 0.0f)` return fires
    first) - but for continuity/safety, the tapering factor itself must be a
    no-op at wet=0 (1.0 - 0.65*0 == 1.0), so nothing here silently changes
    behaviour right at the boundary."""
    old = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=False, wetness=0.0)
    new = simulate_steady_state_blend(fresh_weight_tapers_with_wetness=True, wetness=0.0)
    assert abs(old - new) < 1e-9


def test_source_tapers_fresh_weight_with_the_inverse_of_carry_weights_shape():
    """Pins the fix: freshWeight's computation must include the
    (1.0 - 0.65*wet) taper, immediately alongside its existing
    pressure/dilution terms, mirroring carryWeight's (0.35 + 0.65*wet)."""
    src = SRC_PATH.read_text()
    assert "(0.35f + 0.65f * wet)" in src, "expected carryWeight's existing wetness scaling to still be present"
    assert "(1.0f - 0.65f * wet)" in src, "expected freshWeight's new inverse wetness taper"
    fresh_weight_start = src.index("const float freshWeight = clamp01(")
    fresh_weight_end = src.index(";", fresh_weight_start)
    fresh_weight_expr = src[fresh_weight_start:fresh_weight_end]
    assert "0.65f * wet" in fresh_weight_expr, (
        "expected the wetness taper to be part of freshWeight's own "
        "expression, not just present somewhere else in the file"
    )


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
