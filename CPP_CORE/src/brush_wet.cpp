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
    float radius
)
{
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

    static std::map<int, creative_wet::Mask> masks;
    auto it = masks.find(r); if (it == masks.end()) it = masks.emplace(r, creative_wet::makeMask(r)).first;
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

            if (image.format() == QImage::Format_ARGB32)
            {
                const QRgb pixel = reinterpret_cast<const QRgb*>(image.constScanLine(py))[px];
                constexpr float channelScale = 1.0f / 255.0f;
                sumR += qRed(pixel) * channelScale * weight;
                sumG += qGreen(pixel) * channelScale * weight;
                sumB += qBlue(pixel) * channelScale * weight;
            }
            else
            {
                const QColor color = image.pixelColor(px, py);
                sumR += color.redF() * weight;
                sumG += color.greenF() * weight;
                sumB += color.blueF() * weight;
            }

            total +=
                weight;
        }
    }

    if (total <= 0.0f)
        return QColor(
            255,
            255,
            255
        );

    return QColor::fromRgbF(
        sumR / total,
        sumG / total,
        sumB / total,
        1.0f
    );
}

QColor BrushWet::sampleCanvasColorForTest(const QImage& image, const QPointF& position, float radius) {
    return sampleCanvasColor(image, position, radius);
}

void BrushWet::begin(
    const QColor& baseColor,
    const BrushSettings& settings
)
{
    m_color =
        baseColor;

    m_colorAmount = settings.smudgeTool
        ? 0.0f
        : settings.wetness;
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

    const QColor canvasColor =
        settings.sampleCanvas
            ? sampleCanvasColor(
                  image,
                  position,
                  radius
              )
            : m_color;

    const float pickupAmount =
        clamp01(
            settings.pickup *
            settings.wetness
        );

    const float dilutedPickup =
        pickupAmount *
        (1.0f -
         settings.dilution);

    QColor picked =
        mixColors(
            freshColor,
            canvasColor,
            dilutedPickup
        );

    const float carryAmount =
        clamp01(
            settings.smudge *
            settings.colorCarry
        );

    if (m_colorAmount > 0.0f)
    {
        picked =
            mixColors(
                picked,
                m_color,
                carryAmount
            );
    }

    const float pressureMix =
        clamp01(
            pressure *
            settings.wetness
        );

    m_color =
        mixColors(
            freshColor,
            picked,
            pressureMix
        );

    m_colorAmount =
        clamp01(
            m_colorAmount *
                settings.paintPersistence +
            0.05f
        );
}

QColor BrushWet::color() const
{
    return m_color;
}

float BrushWet::colorAmount() const
{
    return m_colorAmount;
}
