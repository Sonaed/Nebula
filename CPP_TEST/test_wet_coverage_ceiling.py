"""Regression test for: "meme wetness/pickup a 1.0, aucun melange visible,
juste l'impression de flat brush color" - even on a normal "brush" tool
preset (Oil Round, Oil Flat...), confirmed via live debug instrumentation
that wetMix/wetness/pickup all correctly reach the C++ engine, and that
BrushWet::update() runs the wet-mix math end to end - yet `coverage` never
exceeded ~0.33 even while painting squarely over a fully opaque, differently
colored patch.

Root cause: BrushWet::sampleCanvasColor() (CPP_CORE/src/brush_wet.cpp)
samples a disk of pixels through a kernel built by creative_wet::makeMask()
(CPP_CORE/src/wet_mask.cpp), whose per-sample weight falls off linearly from
1.0 at the centre to 0.0 at the rim:

    float w = 1.0f - std::sqrt((float)d) / std::max(1.0f, (float)r);

`coverage` is meant to read as "how much of this disk is opaque paint", in
[0,1], and BrushWet::update() multiplies pickupWeight by it directly - it is
the ONLY thing that lets wetness/pickup ever pick up a different color from
the canvas. But the code computed it as:

    *coverage = clamp01(accum.total / samples.size());

dividing the weighted accumulation by the raw sample COUNT instead of the
SUM of the samples' own weights. The average value of a linear (cone-shaped)
falloff over a disk is exactly 1/3 of its peak (a cone's volume is a third
of its bounding cylinder's) - so even a disk that is 100% opaque, fully
covered by paint, could only ever accumulate about `samples.size() / 3`
worth of weighted signal, capping `coverage` at ~0.33 no matter how much
paint was actually underneath the brush. Since pickupWeight is multiplied
by coverage, this made the entire "pick up the color underneath" effect
roughly three times weaker than wetness=1/pickup=1 was supposed to deliver,
which in practice reads as "flat brush color, wetness does nothing" - live
debug logs from the user's own machine showed coverage topping out at 0.336
while painting directly over a solid, fully opaque patch.

The fix: divide by the sum of the mask's own sample weights instead of the
raw sample count, so a fully opaque, fully covered sample reads as
coverage≈1, matching what the rest of the formula in update() expects.
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CPP_CORE" / "src" / "brush_wet.cpp"
MASK_PATH = ROOT / "CPP_CORE" / "src" / "wet_mask.cpp"


def make_mask(radius: int):
    """Transcription of creative_wet::makeMask (wet_mask.cpp): a disk of
    (dx, dy, weight) samples with weight falling off linearly from the
    centre (1.0) to the rim (0.0)."""
    samples = []
    rs = radius * radius
    for y in range(-radius, radius + 1):
        for x in range(-radius, radius + 1):
            d = x * x + y * y
            if d > rs:
                continue
            w = 1.0 - math.sqrt(d) / max(1.0, float(radius))
            samples.append((x, y, w))
    return samples


def coverage_old(samples, alpha_at):
    """The removed behaviour: divide by the raw sample count."""
    total = sum(w * alpha_at(dx, dy) for dx, dy, w in samples)
    return min(1.0, max(0.0, total / max(1.0, len(samples))))


def coverage_fixed(samples, alpha_at):
    """The fixed behaviour: divide by the sum of the mask's own weights."""
    total = sum(w * alpha_at(dx, dy) for dx, dy, w in samples)
    weight_sum = max(0.0001, sum(w for _, _, w in samples))
    return min(1.0, max(0.0, total / weight_sum))


def test_linear_falloff_kernel_averages_to_one_third():
    """Confirms the math the whole bug hinges on: the mean of a linear
    (cone) falloff over a disk is 1/3 of its peak value - not an
    approximation, a real geometric identity (cone volume = 1/3 cylinder
    volume), so this must hold to good precision even discretised."""
    samples = make_mask(60)  # large radius for a good discrete approximation
    mean_weight = sum(w for _, _, w in samples) / len(samples)
    assert abs(mean_weight - (1.0 / 3.0)) < 0.02, (
        f"expected the discretised mean weight to land near 1/3, got {mean_weight}"
    )


def test_old_coverage_formula_ceilings_at_one_third_even_when_fully_opaque():
    """The bug, proven directly: paint a FULLY opaque, uniform patch under
    the whole sampled disk (alpha=1 everywhere) - the old formula still
    can't get anywhere close to coverage=1."""
    samples = make_mask(25)
    fully_opaque = lambda dx, dy: 1.0
    old = coverage_old(samples, fully_opaque)
    assert old < 0.36, (
        f"old formula should ceiling near 1/3 even for 100% opaque coverage, got {old}"
    )
    assert old > 0.30


def test_fixed_coverage_formula_reaches_near_one_when_fully_opaque():
    """Same fully-opaque disk, fixed formula: must read close to 1.0, which
    is what BrushWet::update()'s pickupWeight math actually expects for
    "the whole sampled area is solid paint"."""
    samples = make_mask(25)
    fully_opaque = lambda dx, dy: 1.0
    fixed = coverage_fixed(samples, fully_opaque)
    assert fixed > 0.999


def test_fixed_formula_is_roughly_three_times_the_old_one_at_full_opacity():
    """Ties the two together: the fix doesn't change what coverage MEANS
    for a partially-covered disk (both still scale with actual coverage),
    it just removes the ~3x under-reporting - directly explaining why
    pickupWeight (coverage is its only source of "differs from the brush's
    own color") was about three times weaker than intended at any given
    wetness/pickup setting."""
    samples = make_mask(25)
    fully_opaque = lambda dx, dy: 1.0
    old = coverage_old(samples, fully_opaque)
    fixed = coverage_fixed(samples, fully_opaque)
    ratio = fixed / old
    assert 2.6 < ratio < 3.4, f"expected roughly a 3x correction, got {ratio}"


def test_source_divides_coverage_by_the_mask_weight_sum_not_sample_count():
    """Pins the actual fix in brush_wet.cpp: both the fast (RGBA8888) path
    and the generic path must normalise by the cached mask weight sum, and
    the old sample-count divisor must be gone from both coverage lines."""
    src = SRC_PATH.read_text()
    assert "maskWeightSum" in src, "expected the cached per-radius weight-sum to be used"
    assert src.count("*coverage = clamp01(") == 2, (
        "expected exactly two coverage assignments (fast RGBA8888 path + "
        "generic path)"
    )
    for line in src.splitlines():
        if "*coverage = clamp01(" in line:
            assert "maskWeightSum" in line, f"coverage line still uses the old divisor: {line!r}"
            assert "samples.size()" not in line, f"coverage line still divides by sample count: {line!r}"


def test_mask_weight_sum_is_cached_per_radius_not_recomputed_unbounded():
    """The weight sum must be cached alongside the existing per-radius mask
    cache (same pattern, same thread_local discipline as the mask cache
    itself - see the thread-safety fix already in this function), not
    recomputed from scratch on every single dab."""
    src = SRC_PATH.read_text()
    assert "std::map<int, float> maskWeightSums" in src
    assert "thread_local" in src.split("std::map<int, float> maskWeightSums")[0].splitlines()[-1] \
        or "static thread_local" in src


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
