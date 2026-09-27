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
#include <vector>

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

    // Reliquat de distance reporté d'un segment au suivant : sans lui, la
    // densité du trait dépend du taux de rapport de la tablette.
    double m_distanceRemainder = 0.0;

    // Dernière tangente connue : conservée pour les segments de longueur
    // nulle, afin que le dab ne pivote pas brutalement à l'arrêt du stylet.
    float m_lastStrokeAngle = 0.0f;

    /*
     * Tampon de trace (stroke buffer).
     *
     * Modèle Photoshop : les dabs accumulent leur couverture dans un masque
     * propre au trait via a = a + flow·(1-a), qui sature naturellement à 1.
     * Ce masque est ensuite composité UNE SEULE FOIS à l'opacité cible.
     *
     * Sans lui, chaque dab est composité indépendamment et repasser sur une
     * zone fait tendre l'alpha vers 1 au lieu de plafonner à `opacity` :
     * `flow` et `opacity` deviennent alors mathématiquement interchangeables.
     */
    std::vector<float> m_strokeMask;      // couverture cumulée [0..1]
    int m_strokeMaskWidth = 0;
    int m_strokeMaskHeight = 0;
    bool m_strokeMaskActive = false;
    float m_strokeOpacity = 1.0f;
    QColor m_strokeColor;
    int m_strokeDirtyLeft = 0;
    int m_strokeDirtyTop = 0;
    int m_strokeDirtyRight = -1;
    int m_strokeDirtyBottom = -1;

    void beginStrokeMask(int width, int height, float opacity, const QColor& color);
    void accumulateStrokeMask(const QImage& dab, int offsetX, int offsetY, float flow);
    void flushStrokeMask(QImage& image);

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
