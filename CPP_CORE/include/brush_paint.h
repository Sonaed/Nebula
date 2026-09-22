#pragma once

#include "brush_settings.h"

#include <QColor>

class BrushPaint
{
public:
    static QColor blendPixel(
        const QColor& destination,
        const QColor& source,
        BrushBlendMode mode,
        float alpha
    );

    static QColor mixColors(
        const QColor& a,
        const QColor& b,
        float amount
    );

private:
    static float clamp01(float value);
};
