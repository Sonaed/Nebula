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
        const QImage& bitmapTip,
        // Décalage fractionnaire du centre réel du dab à l'intérieur du
        // bitmap.  Sans lui, chaque dab est aimanté sur la grille de pixels
        // et le trait avance par marches au lieu de glisser.
        float subpixelX = 0.0f,
        float subpixelY = 0.0f,
        // Écrasement supplémentaire du dab (1 = rond, <1 = aplati).
        // Piloté par l'inclinaison du stylet : un fusain incliné s'aplatit.
        float roundnessScale = 1.0f
    );

private:
    static float clamp01(float value);
};
