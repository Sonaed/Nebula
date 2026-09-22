#pragma once

#include "brush_color.h"
#include "brush_input.h"
#include "brush_paint.h"
#include "brush_random.h"
#include "brush_settings.h"
#include "brush_texture.h"
#include "brush_tip.h"
#include "brush_wet.h"

#include <QColor>
#include <QImage>
#include <QPointF>

class BrushEngine
{
public:
    BrushEngine();

    void setSettings(
        const BrushSettings& settings
    );

    const BrushSettings&
    settings() const;

    void setColor(
        const QColor& color
    );

    const QColor&
    color() const;

    void setTexture(
        const QImage& texture
    );

    void clearTexture();

    bool hasTexture() const;

    bool setBitmapTip(const QImage& image);
    void clearBitmapTip();

    float evaluateSize(
        float pressure,
        float velocity = 0.0f,
        float tilt = 0.0f
    ) const;

    float evaluateOpacity(
        float pressure,
        float velocity = 0.0f,
        float tilt = 0.0f
    ) const;

    float evaluateFlow(
        float pressure,
        float velocity = 0.0f
    ) const;

    void beginStroke(
        const BrushInput& input
    );

    void drawSegment(
        QImage& image,
        const BrushInput& start,
        const BrushInput& end,
        const QImage* cloneSource = nullptr,
        int cloneOffsetX = 0,
        int cloneOffsetY = 0
    );

    void endStroke();
    // Adaptive, zero-queue input stabilization; reset with each stroke.
    void setSmoothing(float strength);
    QPointF smoothPoint(const QPointF& point);

private:
    static float clamp01(
        float value
    );

    static float applyPressure(
        float pressure,
        bool enabled,
        float minimum,
        float base
    );

    BrushSettings m_settings;

    QColor m_color =
        QColor(0, 0, 0, 255);

    QImage m_texture;
    QImage m_bitmapTip;

    BrushInput m_lastInput;

    bool m_hasStroke =
        false;

    unsigned int m_randomState =
        12345;

    QColor m_previousColor;

    bool m_hasPreviousColor =
        false;

    BrushWet m_wet;
    float m_smoothing = 0.0f;
    QPointF m_smoothLastInput;
    QPointF m_smoothLastOutput;
    QPointF m_smoothVelocity;
    bool m_hasSmoothPoint = false;
};
