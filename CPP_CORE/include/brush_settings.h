#pragma once

#include <QColor>

enum class BrushBlendMode
{
    Normal,
    Multiply,
    Screen,
    Overlay,
    Darken,
    Lighten
};

struct BrushSettings
{
    // Basic
    float size = 10.0f;
    float opacity = 1.0f;
    float flow = 1.0f;
    float hardness = 0.8f;
    float spacing = 0.15f;

    // Tip
    float roundness = 1.0f;
    float angle = 0.0f;

    // Jitter / Scatter
    float scatter = 0.0f;
    float sizeJitter = 0.0f;
    float rotationJitter = 0.0f;

    // Texture
    float textureStrength = 0.0f;
    float textureScale = 1.0f;
    float textureRandomScale = 0.0f;
    float textureRandomOffset = 0.0f;
    float textureBrightness = 0.0f;
    float textureContrast = 1.0f;

    bool textureMirror = false;
    bool textureAffectOpacity = true;

    // Color
    bool dirtyColor = false;

    float hueJitter = 0.0f;
    float saturationJitter = 0.0f;
    float brightnessJitter = 0.0f;

    bool useStrokeGradient = false;
    bool useLinearGradient = true;
    bool useRadialGradient = false;

    float gradientAmount = 0.0f;
    QColor gradientColor =
        QColor(255, 255, 255, 255);

    // Paint
    BrushBlendMode blendMode =
        BrushBlendMode::Normal;

    bool flowAccumulation = true;
    float paintMix = 1.0f;

    // Wet / Smudge / Mixing
    float wetness = 0.0f;
    float pickup = 0.0f;
    float dilution = 0.0f;
    float smudge = 0.0f;
    float paintPersistence = 1.0f;
    float colorCarry = 1.0f;

    bool wetMix = false;
    bool sampleCanvas = true;
    bool smudgeTool = false;

    // General
    bool eraser = false;
    bool antialiasing = true;

    // Pressure
    bool pressureSize = true;
    bool pressureOpacity = false;
    bool pressureFlow = false;

    float minimumSize = 0.01f;
    float minimumOpacity = 0.0f;
    float minimumFlow = 0.0f;

    // Advanced dynamics driven by the current input velocity.
    float velocitySize = 0.0f;
    float velocityOpacity = 0.0f;
    float velocityFlow = 0.0f;
    float tiltSize = 0.0f;
    float tiltOpacity = 0.0f;

    // Deterministic random
    unsigned int randomSeed = 12345;
};
