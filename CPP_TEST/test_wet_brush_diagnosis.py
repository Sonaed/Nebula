"""Diagnosis for: "the wet brush-preset category, I don't know if it works,
I don't see a difference."

This is NOT a bug-fix test - after tracing the full chain (preset dict ->
BrushSettingsState -> CppBrushPresetApplier.apply() -> native
cs_brush_set_wetness/pickup/dilution/paint_persistence/color_carry/wet_mix
-> BrushEngine::drawSegment() -> BrushWet::update()/color() -> BrushTip::draw())
every link is wired correctly and BrushWet::update() (CPP_CORE/src/brush_wet.cpp)
performs real, non-trivial pigment-reservoir color mixing. It is not a stub.

So this file transcribes BrushWet::update()'s actual math (same formula, same
constants, line-for-line) in Python and uses it to confirm *why* the user
doesn't perceive a difference: on the single most natural test - one fresh
brush color, painted on blank canvas - the "wet" blend is mathematically
identical to a dry dab, because the three ingredients it blends (fresh color,
carried color, canvas-picked-up color) all resolve to the same value or zero
weight in that specific scenario. The effect only diverges from a dry brush
once there is a *different* color already on the canvas to pick up, or the
brush color changes mid-stroke (colorCarry/paintPersistence lag).

If this file's `test_wet_mix_is_invisible_on_blank_canvas_same_color` and
`test_wet_mix_visibly_differs_once_painting_over_a_different_color` both pass,
that confirms the "no visible difference" report is explained by test
conditions, not a code defect - i.e. no fix is needed in this chain, only an
explanation of how to actually observe the effect.
"""


def clamp01(v):
    return max(0.0, min(1.0, v))


def mix_colors(a, b, amount):
    """BrushWet::mixColors - linear per-channel lerp, used only by the smudge
    tool path (not exercised here, kept for completeness/reference)."""
    amount = clamp01(amount)
    return tuple(a[i] * (1.0 - amount) + b[i] * amount for i in range(3))


class WetState:
    """Transcription of BrushWet's per-stroke state (m_color, m_paintLoad,
    m_colorAmount) and its begin()/update() methods, matching
    CPP_CORE/src/brush_wet.cpp exactly (non-smudge path only)."""

    def __init__(self):
        self.color = None
        self.paint_load = 0.0
        self.color_amount = 0.0

    def begin(self, base_color, wet_mix, wetness, paint_persistence):
        self.color = base_color
        self.color_amount = clamp01(wetness)
        self.paint_load = clamp01(0.35 + 0.65 * paint_persistence)

    def update(self, canvas_color, surface_coverage, fresh_color, pressure,
               wet_mix, wetness, sample_canvas, dilution, pickup,
               color_carry, paint_persistence):
        if not wet_mix or wetness <= 0.0:
            self.color = fresh_color
            self.color_amount = 1.0
            return

        p = clamp01(pressure)
        wet = clamp01(wetness)
        fresh_weight = clamp01(0.18 + 0.82 * p) * (1.0 - 0.45 * clamp01(dilution))
        carry_weight = clamp01(self.paint_load * color_carry * (0.35 + 0.65 * wet))
        pickup_weight = clamp01(pickup * wet * p * (1.0 - dilution)) * surface_coverage
        total = fresh_weight + carry_weight + pickup_weight

        if total > 0.0:
            fresh_ratio = fresh_weight / total
            carry_ratio = carry_weight / total
            pickup_ratio = pickup_weight / total
            self.color = tuple(
                fresh_color[i] * fresh_ratio +
                self.color[i] * carry_ratio +
                canvas_color[i] * pickup_ratio
                for i in range(3)
            )

        retained = self.paint_load * clamp01(paint_persistence)
        picked = pickup_weight * (0.55 + 0.45 * color_carry)
        fresh = fresh_weight * (0.65 + 0.35 * p)
        self.paint_load = clamp01(retained + picked + fresh)
        self.color_amount = clamp01(self.paint_load * (0.5 + 0.5 * wet))


# "Oil Round" preset values, from TOOLS/brush_preset_manager.py:
# wetMix=True, wetness=.55, pickup=.45, dilution=.20, paintPersistence=.75,
# colorCarry=.80
OIL_ROUND = dict(wet_mix=True, wetness=0.55, pickup=0.45, dilution=0.20,
                  paint_persistence=0.75, color_carry=0.80, sample_canvas=True)


def test_wet_mix_is_invisible_on_blank_canvas_same_color():
    """The scenario a user tries first: pick a wet preset, pick one color,
    draw one stroke on an empty canvas. Fresh color == carried color (both
    are the single selected brush color), and blank canvas gives zero
    surface coverage (see BrushWet::sampleCanvasColor's early
    `if (accum.total <= 0.0f) return ...` leaving *coverage at its
    initialized 0.0f) - so pickup contributes nothing. The blend is then a
    weighted average of one color with itself: mathematically identical to
    the plain fresh color a dry brush would place."""
    color = (0.8, 0.2, 0.2)  # some selected brush color
    wet = WetState()
    wet.begin(color, **{k: OIL_ROUND[k] for k in ("wet_mix", "wetness", "paint_persistence")})

    for pressure in (0.3, 0.6, 1.0, 0.5, 0.8):
        wet.update(
            canvas_color=(1.0, 1.0, 1.0),  # sampleCanvasColor's fallback value
            surface_coverage=0.0,          # blank canvas -> zero coverage
            fresh_color=color,             # same color every dab, no jitter
            pressure=pressure,
            wet_mix=OIL_ROUND["wet_mix"], wetness=OIL_ROUND["wetness"],
            sample_canvas=OIL_ROUND["sample_canvas"], dilution=OIL_ROUND["dilution"],
            pickup=OIL_ROUND["pickup"], color_carry=OIL_ROUND["color_carry"],
            paint_persistence=OIL_ROUND["paint_persistence"],
        )
        for c in range(3):
            assert abs(wet.color[c] - color[c]) < 1e-9, (
                "wet-mixed color drifted from the dry color with nothing "
                "different to blend in - should be impossible"
            )


def test_wet_mix_visibly_differs_once_painting_over_a_different_color():
    """The scenario that actually exercises the feature: painting a wet
    stroke over an area that already has a *different* color underneath.
    Surface coverage is now > 0, so canvas pickup pulls that other color in
    - this is where "wet" should visibly diverge from a dry brush, and it
    does."""
    brush_color = (0.1, 0.1, 0.9)   # blue
    canvas_color = (0.9, 0.8, 0.1)  # yellow already on the canvas

    wet = WetState()
    wet.begin(brush_color, **{k: OIL_ROUND[k] for k in ("wet_mix", "wetness", "paint_persistence")})
    wet.update(
        canvas_color=canvas_color,
        surface_coverage=0.9,  # dab lands solidly on existing paint
        fresh_color=brush_color,
        pressure=0.8,
        wet_mix=OIL_ROUND["wet_mix"], wetness=OIL_ROUND["wetness"],
        sample_canvas=OIL_ROUND["sample_canvas"], dilution=OIL_ROUND["dilution"],
        pickup=OIL_ROUND["pickup"], color_carry=OIL_ROUND["color_carry"],
        paint_persistence=OIL_ROUND["paint_persistence"],
    )

    # Result must sit strictly between pure blue and pure yellow - proof the
    # canvas color was actually picked up and blended in.
    for c in range(3):
        lo, hi = sorted((brush_color[c], canvas_color[c]))
        assert lo - 1e-9 <= wet.color[c] <= hi + 1e-9
    assert wet.color != brush_color


def test_dry_preset_ignores_all_of_this_regardless_of_inputs():
    """Sanity check on the early-out: with wetMix disabled (or wetness<=0,
    the state of a non-wet preset), the fresh color always wins outright -
    matching a normal dry brush exactly, even over a different canvas
    color. Confirms the feature is properly gated and can't leak."""
    wet = WetState()
    wet.begin((0.1, 0.1, 0.9), wet_mix=False, wetness=0.0, paint_persistence=1.0)
    wet.update(
        canvas_color=(0.9, 0.8, 0.1), surface_coverage=0.9,
        fresh_color=(0.1, 0.1, 0.9), pressure=0.8,
        wet_mix=False, wetness=0.0, sample_canvas=True, dilution=0.0,
        pickup=0.0, color_carry=0.0, paint_persistence=1.0,
    )
    assert wet.color == (0.1, 0.1, 0.9)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
