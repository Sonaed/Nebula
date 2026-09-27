#include "brush_wet.h"
#include "wet_mask.h"
#include "wet_kernel.h"
#include <map>

#include <algorithm>
#include <cmath>

float BrushWet::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

QColor BrushWet::mixColors(
    const QColor& a,
    const QColor& b,
    float amount
)
{
    amount =
        clamp01(amount);

    return QColor::fromRgbF(
        a.redF() *
            (1.0f - amount) +
        b.redF() *
            amount,

        a.greenF() *
            (1.0f - amount) +
        b.greenF() *
            amount,

        a.blueF() *
            (1.0f - amount) +
        b.blueF() *
            amount,

        1.0f
    );
}

QColor BrushWet::sampleCanvasColor(
    const QImage& image,
    const QPointF& position,
    float radius,
    float* coverage
)
{
    if (coverage)
        *coverage = 0.0f;

    if (image.isNull())
        return QColor(
            255,
            255,
            255
        );

    const int cx =
        static_cast<int>(
            std::round(position.x())
        );

    const int cy =
        static_cast<int>(
            std::round(position.y())
        );

    const int r =
        std::max(
            1,
            static_cast<int>(
                std::ceil(
                    radius * 0.35f
                )
            )
        );
    const int radiusSquared = r * r;

    float sumR = 0.0f;
    float sumG = 0.0f;
    float sumB = 0.0f;
    float total = 0.0f;

    // thread_local, not a plain function-local static: this cache used to be
    // a single process-wide std::map mutated with no locking whatsoever. The
    // synchronous (mouse) brush path only ever calls this from the UI thread,
    // so the race never showed there - but the stylus path runs one
    // BrushAsyncWorker per stroke on its own std::thread (and one per
    // symmetry axis on top of that, all concurrent), and every one of them
    // calls sampleCanvasColor for wet/smudge dabs. Two threads racing on the
    // same std::map's internal tree during masks.emplace() is a data race
    // (UB) that can corrupt the map or hand back a garbage/mismatched mask,
    // which is exactly the kind of thing that shows up on screen as a
    // corrupted block of pixels. thread_local gives each worker thread (and
    // the UI thread) its own private cache - no sharing, no lock needed, same
    // memoization benefit.
    thread_local std::map<int, creative_wet::Mask> masks;
    auto it = masks.find(r); if (it == masks.end()) it = masks.emplace(r, creative_wet::makeMask(r)).first;

    // Coverage is meant to read as "how much of the sampled disk is opaque
    // paint" in [0,1] - update() multiplies pickupWeight by it directly, so
    // it is the whole reason wetness/pickup ever pick up a different color
    // from the canvas. The mask's samples carry a radial falloff weight (1
    // at the centre, 0 at the rim - see wet_mask.cpp's makeMask), and the
    // average of that linear falloff over a disk is exactly 1/3 (a cone's
    // volume is a third of its bounding cylinder's). Dividing the weighted
    // accumulation by the raw sample COUNT - as this used to - ignores
    // that: a disk that is 100% opaque, fully-covered paint still only
    // accumulates about a third of `samples.size()`, so coverage was
    // silently ceilinged at ~0.33 no matter how solid the paint underneath
    // really was, which made pickupWeight (and therefore the whole wet-mix
    // "pick up the color underneath" effect) about three times weaker than
    // wetness/pickup=1 was supposed to deliver - indistinguishable from a
    // flat brush stroke in practice. Dividing by the sum of the mask's own
    // weights instead means a fully opaque, fully covered sample reads as
    // coverage≈1, as the rest of the formula in update() expects.
    static thread_local std::map<int, float> maskWeightSums;
    auto weightIt = maskWeightSums.find(r);
    if (weightIt == maskWeightSums.end())
    {
        float sum = 0.0f;
        for (const auto& sample : it->second.samples)
            sum += sample.weight;
        weightIt = maskWeightSums.emplace(r, std::max(0.0001f, sum)).first;
    }
    const float maskWeightSum = weightIt->second;

    if (image.format() == QImage::Format_RGBA8888) {
        creative_wet::Accum accum{};
        const int cx = std::clamp(static_cast<int>(std::round(position.x())), 0, image.width() - 1);
        const int cy = std::clamp(static_cast<int>(std::round(position.y())), 0, image.height() - 1);
        const uint8_t* base = reinterpret_cast<const uint8_t*>(image.constBits());
#if defined(__GNUC__) || defined(__clang__)
        if (__builtin_cpu_supports("avx2")) creative_wet::sample_avx2(base, image.width(), image.height(), image.bytesPerLine(), cx, cy, it->second, accum);
        else if (__builtin_cpu_supports("sse4.1")) creative_wet::sample_sse4(base, image.width(), image.height(), image.bytesPerLine(), cx, cy, it->second, accum);
        else creative_wet::sample_reference(base, image.width(), image.height(), image.bytesPerLine(), cx, cy, it->second, accum);
#else
        creative_wet::sample_reference(base, image.width(), image.height(), image.bytesPerLine(), cx, cy, it->second, accum);
#endif
        if (accum.total <= 0.0f) return QColor(255,255,255);
        if (coverage)
            *coverage = clamp01(accum.total / maskWeightSum);
        return QColor::fromRgbF(accum.r / accum.total, accum.g / accum.total, accum.b / accum.total, 1.0f);
    }

    for (const auto& sample : it->second.samples) {
        const int x = sample.dx, y = sample.dy;
        {
            const int distanceSquared = x * x + y * y;

            const int px =
                cx + x;

            const int py =
                cy + y;

            if (px < 0 ||
                py < 0 ||
                px >= image.width() ||
                py >= image.height())
            {
                continue;
            }

            const float weight = sample.weight;

            float alpha = 1.0f;
            if (image.format() == QImage::Format_ARGB32)
            {
                const QRgb pixel = reinterpret_cast<const QRgb*>(image.constScanLine(py))[px];
                constexpr float channelScale = 1.0f / 255.0f;
                alpha = qAlpha(pixel) * channelScale;
                sumR += qRed(pixel) * channelScale * weight * alpha;
                sumG += qGreen(pixel) * channelScale * weight * alpha;
                sumB += qBlue(pixel) * channelScale * weight * alpha;
            }
            else
            {
                const QColor color = image.pixelColor(px, py);
                alpha = color.alphaF();
                sumR += color.redF() * weight * alpha;
                sumG += color.greenF() * weight * alpha;
                sumB += color.blueF() * weight * alpha;
            }

            total +=
                weight * alpha;
        }
    }

    if (total <= 0.0f)
        return QColor(
            255,
            255,
            255
        );

    if (coverage)
        *coverage = clamp01(total / maskWeightSum);

    return QColor::fromRgbF(
        sumR / total,
        sumG / total,
        sumB / total,
        1.0f
    );
}

QColor BrushWet::sampleCanvasColorForTest(const QImage& image, const QPointF& position, float radius) {
    return sampleCanvasColor(image, position, radius, nullptr);
}

void BrushWet::begin(
    const QColor& baseColor,
    const BrushSettings& settings
)
{
    m_color =
        baseColor;

    m_colorAmount = settings.smudgeTool ? 0.0f : clamp01(settings.wetness);
    m_paintLoad = settings.smudgeTool
        ? 0.0f
        : clamp01(0.35f + 0.65f * settings.paintPersistence);
}

void BrushWet::update(
    const QImage& image,
    const QPointF& position,
    float radius,
    const QColor& freshColor,
    float pressure,
    const BrushSettings& settings
)
{
    if (settings.smudgeTool)
    {
        const QColor canvasColor = sampleCanvasColor(
            image,
            position,
            radius
        );
        if (m_colorAmount <= 0.0f)
            m_color = canvasColor;
        else
            m_color = mixColors(
                canvasColor,
                m_color,
                clamp01(settings.colorCarry * settings.smudge)
            );
        m_colorAmount = clamp01(
            std::max(0.05f, settings.smudge) * pressure
        );
        return;
    }

    if (!settings.wetMix ||
        settings.wetness <= 0.0f)
    {
        m_color =
            freshColor;

        m_colorAmount =
            1.0f;

        return;
    }

    float surfaceCoverage = 0.0f;
    const QColor canvasColor = settings.sampleCanvas
        ? sampleCanvasColor(image, position, radius, &surfaceCoverage)
        : m_color;

    // A dab is a three-way mixture: fresh pigment, pigment already carried by
    // the brush, and pigment picked up from the canvas.  The weights model a
    // reservoir instead of repeatedly lerping the final color, which makes
    // long strokes converge smoothly instead of oscillating.
    const float p = clamp01(pressure);
    const float wet = clamp01(settings.wetness);
    // freshWeight used to be independent of wetness/pickup entirely - only
    // pressure and dilution touched it. That meant every single dab, no
    // matter how extreme wetness/pickup were set, injected ~0.91 weight of
    // pure, undiluted freshColor (at p=1, dilution=0.2) into the blend
    // alongside carryWeight/pickupWeight. Working the reservoir's fixed
    // point through algebraically: even with the coverage-ceiling fix
    // (surfaceCoverage able to reach ~1) and wetness=pickup=1 painting over
    // a fully opaque, fully overlapped patch, the blend could never
    // converge past roughly 50/50 toward the underlying canvas color - and
    // a normal single-pass stroke (not fully re-covering every pixel many
    // times) landed far short of even that, reading as "barely tinted" -
    // which is what was reported as "wet mix still very weak" even after
    // the coverage fix landed and was rebuilt.
    //
    // carryWeight already scales UP with wetness via (0.35 + 0.65*wet): a
    // wetter brush leans more on its own carried paint load. freshWeight now
    // mirrors that shape inverted - (1.0 - 0.65*wet) - so a wetter brush
    // sheds exactly as much "lay down pure fresh color" weight as
    // carryWeight gains, instead of keeping fresh deposit at full strength
    // regardless of wetness. At wetness=0 nothing changes here (this whole
    // function is unreached below wetness<=0 - see the early return above);
    // at wetness=1, freshWeight drops to 35% of its former value, letting
    // carryWeight/pickupWeight actually dominate the blend the way
    // wetness/pickup sliders at maximum are supposed to promise.
    const float freshWeight = clamp01(0.18f + 0.82f * p) *
        (1.0f - 0.45f * clamp01(settings.dilution)) *
        (1.0f - 0.65f * wet);
    const float carryWeight = clamp01(m_paintLoad * settings.colorCarry *
                                      (0.35f + 0.65f * wet));
    const float pickupWeight = clamp01(settings.pickup * wet * p *
                                       (1.0f - settings.dilution)) *
        surfaceCoverage;
    const float totalWeight = freshWeight + carryWeight + pickupWeight;

    if (totalWeight > 0.0f)
    {
        const float freshRatio = freshWeight / totalWeight;
        const float carryRatio = carryWeight / totalWeight;
        const float pickupRatio = pickupWeight / totalWeight;
        m_color = QColor::fromRgbF(
            freshColor.redF() * freshRatio + m_color.redF() * carryRatio + canvasColor.redF() * pickupRatio,
            freshColor.greenF() * freshRatio + m_color.greenF() * carryRatio + canvasColor.greenF() * pickupRatio,
            freshColor.blueF() * freshRatio + m_color.blueF() * carryRatio + canvasColor.blueF() * pickupRatio,
            1.0f);
    }

    const float retained = m_paintLoad * clamp01(settings.paintPersistence);
    const float picked = pickupWeight * (0.55f + 0.45f * settings.colorCarry);
    const float fresh = freshWeight * (0.65f + 0.35f * p);
    m_paintLoad = clamp01(retained + picked + fresh);
    m_colorAmount = clamp01(m_paintLoad * (0.5f + 0.5f * wet));
}

QColor BrushWet::color() const
{
    return m_color;
}

float BrushWet::colorAmount() const
{
    return m_colorAmount;
}
