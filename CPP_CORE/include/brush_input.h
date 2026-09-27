#pragma once

#include <QPointF>

struct BrushInput
{
    QPointF position;

    float pressure = 1.0f;

    float tiltX = 0.0f;
    float tiltY = 0.0f;

    float rotation = 0.0f;

    float velocity = 0.0f;

    double time = 0.0;
};
