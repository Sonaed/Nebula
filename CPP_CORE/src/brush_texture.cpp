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

    // Bilinear, wrapping: a pattern stretched over a large tile (Photoshop
    // brush textures are often scaled up) used to show square blocks.
    const int width = texture.width();
    const int height = texture.height();
    if (width < 16 || height < 16) {
        // Tiny patterns are intentional pixel patterns: keep them crisp.
        const int nx = std::clamp(static_cast<int>(u * width), 0, width - 1);
        const int ny = std::clamp(static_cast<int>(v * height), 0, height - 1);
        return applyAdjustments(settings, texture.constScanLine(ny)[nx] / 255.0f);
    }
    const float fx = u * width - 0.5f;
    const float fy = v * height - 0.5f;
    const int x0 = static_cast<int>(std::floor(fx));
    const int y0 = static_cast<int>(std::floor(fy));
    const float tx = fx - x0;
    const float ty = fy - y0;
    auto wrap = [](int value, int size) { value %= size; return value < 0 ? value + size : value; };
    const int xa = wrap(x0, width), xb = wrap(x0 + 1, width);
    const int ya = wrap(y0, height), yb = wrap(y0 + 1, height);
    const uchar* rowA = texture.constScanLine(ya);
    const uchar* rowB = texture.constScanLine(yb);
    const float top = rowA[xa] + (rowA[xb] - rowA[xa]) * tx;
    const float bottom = rowB[xa] + (rowB[xb] - rowB[xa]) * tx;
    const float value = top + (bottom - top) * ty;

    return applyAdjustments(
        settings,
        value /
        255.0f
    );
}
