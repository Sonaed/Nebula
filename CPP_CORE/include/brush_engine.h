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
#include <cstdint>
#include <memory>
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
     * Tampon de trace (stroke buffer) — modèle Photoshop/Krita.
     *
     * Chaque pixel touché par le trait conserve :
     *   - sa couverture cumulée (flottante) ;
     *   - sa valeur AVANT le trait.
     * Le pixel final est TOUJOURS recomposé depuis la valeur d'origine :
     *   out = origine OVER (couleur, couverture)
     * Repasser sur une zone ne peut donc jamais dépasser l'opacité du trait.
     *
     * L'ancienne version recomposait la couverture cumulée sur le pixel DÉJÀ
     * peint après chaque dab : à 40 % d'opacité, un trait qui se chevauche
     * montait à ~100 %.
     *
     * Stockage creux par tuiles de 64 px : seule la zone réellement peinte
     * est allouée (un document 8K ne réserve plus 256 Mo de masque).
     */
    static constexpr int kStrokeTileSize = 64;
    struct StrokeTile {
        float coverage[kStrokeTileSize * kStrokeTileSize];
        float dual[kStrokeTileSize * kStrokeTileSize];
        uint32_t original[kStrokeTileSize * kStrokeTileSize];
    };
    // Une copie du moteur (worker asynchrone, clones de symétrie) repart
    // toujours d'un tampon vide : les tuiles ne sont jamais partagées.
    struct StrokeTileStore {
        std::vector<std::unique_ptr<StrokeTile>> tiles;
        StrokeTileStore() = default;
        StrokeTileStore(const StrokeTileStore&) {}
        StrokeTileStore& operator=(const StrokeTileStore&) { tiles.clear(); return *this; }
        StrokeTileStore(StrokeTileStore&&) noexcept = default;
        StrokeTileStore& operator=(StrokeTileStore&&) noexcept = default;
    };
    StrokeTileStore m_strokeTiles;
    int m_strokeTilesX = 0;
    int m_strokeTilesY = 0;
    int m_strokeImageWidth = 0;
    int m_strokeImageHeight = 0;
    QImage::Format m_strokeFormat = QImage::Format_Invalid;
    bool m_strokeBufferActive = false;
    bool m_strokeErase = false;
    QColor m_strokeColor;

    void resetStrokeBuffer();
    void ensureStrokeBuffer(const QImage& image, const QColor& color, bool erase);
    StrokeTile* strokeTile(const QImage& image, int tileX, int tileY);
    void depositDab(QImage& image, const QImage& dab, int offsetX, int offsetY,
                    float flow, float opacityCap);
    // Gomme directe (sans tampon) : utilise la vraie forme du dab.
    void eraseDabDirect(QImage& image, const QImage& dab, int offsetX, int offsetY, float strength);
    // Dual brush: stamps the second tip along [from, to] into the stroke
    // buffer's dual mask and re-composites the touched pixels.
    void stampDualAlong(QImage& image, const QPointF& from, const QPointF& to, float mainSize);
    void compositeBufferPixel(QImage& image, StrokeTile* tile, int index, int px, int py,
                              QImage::Format storedFormat);
    bool dualActive() const;
    QImage m_dualTip;
    double m_dualRemainder = 0.0;
public:
    bool setDualTip(const QImage& image);
    void clearDualTip();
private:
    // Per-pixel wet paint: drags the real canvas from the previous dab,
    // mixes in reservoir pigment, dilutes, and respects transparency.
    void wetDab(QImage& image, const QImage& dab, int offsetX, int offsetY,
                const QColor& pigment, float strength, int dragX, int dragY,
                float smear, float pigmentRate, float pigmentAlpha);
    QPointF m_previousDab;
    bool m_hasPreviousDab = false;

    // Advanced at every stroke start so two strokes never replay the same
    // jitter/scatter sequence (identical strokes looked stamped).
    unsigned int m_strokeCounter = 0;
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
