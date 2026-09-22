#pragma once

#include "brush_settings.h"

#include <QImage>

class BrushTexture
{
public:
    static float sample(
        const QImage& texture,
        const BrushSettings& settings,
        float u,
        float v,
        bool mirrorTexture
    );

private:
    static float clamp01(float value);

    static float applyAdjustments(
        const BrushSettings& settings,
        float value
    );
};
