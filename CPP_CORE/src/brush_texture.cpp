#include "brush_texture.h"

#include <algorithm>
#include <cmath>

float BrushTexture::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

float BrushTexture::applyAdjustments(
    const BrushSettings& settings,
    float value
)
{
    value = clamp01(value);

    value =
        0.5f +
        (value - 0.5f) *
        settings.textureContrast;

    value +=
        settings.textureBrightness;

    return clamp01(value);
}

float BrushTexture::sample(
    const QImage& texture,
    const BrushSettings& settings,
    float u,
    float v,
    bool mirrorTexture
)
{
    if (texture.isNull())
        return 1.0f;

    const int tileU =
        static_cast<int>(
            std::floor(u)
        );

    const int tileV =
        static_cast<int>(
            std::floor(v)
        );

    u -= std::floor(u);
    v -= std::floor(v);

    if (mirrorTexture &&
        ((tileU + tileV) & 1))
    {
        u = 1.0f - u;
    }

    const int x =
        std::clamp(
            static_cast<int>(
                u * texture.width()
            ),
            0,
            texture.width() - 1
        );

    const int y =
        std::clamp(
            static_cast<int>(
                v * texture.height()
            ),
            0,
            texture.height() - 1
        );

    const uchar value =
        texture.constScanLine(y)[x];

    return applyAdjustments(
        settings,
        static_cast<float>(value) /
        255.0f
    );
}
