#pragma once

#include "brush_settings.h"

#include <QColor>
#include <QImage>
#include <QPointF>

class BrushWet
{
public:
    void begin(
        const QColor& baseColor,
        const BrushSettings& settings
    );

    void update(
        const QImage& image,
        const QPointF& position,
        float radius,
        const QColor& freshColor,
        float pressure,
        const BrushSettings& settings
    );

    QColor color() const;

    float colorAmount() const;
    static QColor sampleCanvasColorForTest(const QImage& image, const QPointF& position, float radius);

private:
    static float clamp01(float value);

    static QColor mixColors(
        const QColor& a,
        const QColor& b,
        float amount
    );

    static QColor sampleCanvasColor(
        const QImage& image,
        const QPointF& position,
        float radius,
        float* coverage = nullptr
    );

    QColor m_color =
        QColor(0, 0, 0, 255);

    float m_colorAmount = 0.0f;

    // Pigment load carried by the brush between dabs.  Keeping this separate
    // from wetness gives the stroke a real reservoir: pickup can accumulate,
    // dilution can drain it, and paint persistence can retain it.
    float m_paintLoad = 0.0f;
};
