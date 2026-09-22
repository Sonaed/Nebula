#include "brush_tip.h"
#include "brush_texture.h"

#include <algorithm>
#include <cmath>

float BrushTip::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

void BrushTip::draw(
    QImage& image,
    const BrushSettings& settings,
    const QPointF& position,
    float diameter,
    float opacity,
    float rotation,
    float textureScale,
    float textureOffsetX,
    float textureOffsetY,
    bool mirrorTexture,
    const QColor& color,
    const QImage& texture,
    const QImage& bitmapTip
)
{
    if (diameter <= 0.0f ||
        opacity <= 0.0f)
    {
        return;
    }

    const int padding = 2;

    const int size =
        std::max(
            4,
            static_cast<int>(
                std::ceil(diameter)
            ) +
            padding * 2
        );

    const float radius =
        diameter * 0.5f;

    const float center =
        static_cast<float>(size) *
        0.5f;

    const float hardness =
        clamp01(
            settings.hardness
        );

    const float roundness =
        std::max(
            0.01f,
            settings.roundness
        );

    const float radians =
        -rotation *
        3.14159265358979323846f /
        180.0f;

    const float cosA =
        std::cos(radians);

    const float sinA =
        std::sin(radians);

    for (int y = 0; y < size; ++y)
    {
        const int pixelY = y + static_cast<int>(position.y() - center);
        if (pixelY < 0 || pixelY >= image.height())
            continue;
        auto* argbRow = image.format() == QImage::Format_ARGB32
            ? reinterpret_cast<QRgb*>(image.scanLine(pixelY)) : nullptr;

        for (int x = 0; x < size; ++x)
        {
            const float localX =
                static_cast<float>(x) -
                center;

            const float localY =
                static_cast<float>(y) -
                center;

            const float rotatedX =
                localX * cosA -
                localY * sinA;

            const float rotatedY =
                localX * sinA +
                localY * cosA;

            const float normalizedX =
                rotatedX /
                radius;

            const float normalizedY =
                rotatedY /
                (radius * roundness);

            const float distance =
                std::sqrt(
                    normalizedX *
                        normalizedX +
                    normalizedY *
                        normalizedY
                );

            if (distance > 1.0f)
                continue;

            float brushAlpha;

            if (distance <= hardness)
            {
                brushAlpha = 1.0f;
            }
            else
            {
                const float range =
                    std::max(
                        0.0001f,
                        1.0f -
                        hardness
                    );

                brushAlpha =
                    1.0f -
                    (distance -
                     hardness) /
                    range;

                brushAlpha =
                    clamp01(
                        brushAlpha
                    );
            }

            const float u =
                (normalizedX * 0.5f +
                 0.5f) *
                textureScale +
                textureOffsetX;

            const float v =
                (normalizedY * 0.5f +
                 0.5f) *
                textureScale +
                textureOffsetY;

            const float textureValue =
                BrushTexture::sample(
                    texture,
                    settings,
                    u,
                    v,
                    mirrorTexture
                );

            const float textureMix =
                1.0f -
                settings.textureStrength;

            const float finalTexture =
                textureMix +
                textureValue *
                settings.textureStrength;

            float finalAlpha =
                brushAlpha *
                opacity;

            QColor dabColor = color;
            if (!bitmapTip.isNull())
            {
                const float bitmapU = normalizedX * 0.5f + 0.5f;
                const float bitmapV = normalizedY * 0.5f + 0.5f;
                const int tipX = std::clamp(
                    static_cast<int>(bitmapU * bitmapTip.width()), 0, bitmapTip.width() - 1);
                const int tipY = std::clamp(
                    static_cast<int>(bitmapV * bitmapTip.height()), 0, bitmapTip.height() - 1);
                const QRgb tipPixel = bitmapTip.pixel(tipX, tipY);
                finalAlpha *= qAlpha(tipPixel) / 255.0f;
                dabColor = QColor::fromRgba(tipPixel);
            }

            if (settings.textureAffectOpacity)
            {
                finalAlpha *=
                    finalTexture;
            }

            finalAlpha =
                clamp01(
                    finalAlpha
                );

            const int pixelX =
                x +
                static_cast<int>(
                    position.x() -
                    center
                );

            if (pixelX < 0 || pixelX >= image.width())
            {
                continue;
            }
            const int alpha = qRound(clamp01(finalAlpha) * 255.0f);
            if (argbRow)
                argbRow[pixelX] = qRgba(dabColor.red(), dabColor.green(), dabColor.blue(), alpha);
            else {
                QColor pixel = dabColor;
                pixel.setAlpha(alpha);
                image.setPixelColor(pixelX, pixelY, pixel);
            }
        }
    }
}
