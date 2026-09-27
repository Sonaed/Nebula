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

    /*
     * Oriente le dab sur la tangente du trait (« Angle Jitter: Direction »
     * de Photoshop).  0 = angle fixe, 1 = suit entièrement la direction.
     * Indispensable aux pinceaux calligraphiques, plats et biseautés : sans
     * lui, un marqueur garde le même biseau quel que soit le sens du geste.
     */
    float directionFollow = 0.0f;

    /*
     * Élongation du dab avec l'inclinaison du stylet, et orientation sur
     * l'azimut du tilt.  C'est le comportement fusain/marqueur : un outil
     * incliné s'aplatit dans le sens de l'inclinaison.
     */
    float tiltElongation = 0.0f;
    float tiltFollow = 0.0f;

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
    // 0 linear, 1 soft (more low-pressure control), 2 hard.
    int pressureCurve = 0;

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
