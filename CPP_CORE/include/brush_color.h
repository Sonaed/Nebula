#pragma once

#include "brush_settings.h"

#include <QColor>

class BrushColor
{
public:
    static QColor evaluate(
        const BrushSettings& settings,
        const QColor& baseColor,
        QColor& previousColor,
        bool& hasPreviousColor,
        float strokeT,
        float pressure,
        unsigned int& randomState
    );

private:
    static float clamp01(float value);

    static float randomRange(
        unsigned int& state,
        float minimum,
        float maximum
    );

    static QColor applyJitter(
        const BrushSettings& settings,
        const QColor& baseColor,
        QColor& previousColor,
        bool& hasPreviousColor,
        unsigned int& randomState
    );

    static QColor applyGradient(
        const BrushSettings& settings,
        const QColor& baseColor,
        float strokeT
    );
};
