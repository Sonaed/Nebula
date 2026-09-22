#pragma once

#include "brush_settings.h"

#include <QColor>
#include <QImage>
#include <QPainter>
#include <QPointF>

class BrushTip
{
public:
    static void draw(
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
    );

private:
    static float clamp01(float value);
};
