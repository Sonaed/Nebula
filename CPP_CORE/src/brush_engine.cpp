#include "brush_engine.h"
#include "simd_runtime.h"
#include "brush_texture.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace {
inline uint8_t quantizeChannel(float value) {
    return static_cast<uint8_t>(std::clamp(std::lround(std::clamp(value, 0.0f, 1.0f) * 255.0f), 0L, 255L));
}

inline void blendRgba8888(uint8_t* destination, const uint8_t* source, BrushBlendMode mode) {
    const float dr = destination[0] / 255.0f, dg = destination[1] / 255.0f, db = destination[2] / 255.0f;
    const float sr = source[0] / 255.0f, sg = source[1] / 255.0f, sb = source[2] / 255.0f;
    const float sa = source[3] / 255.0f, da = destination[3] / 255.0f;
    float rr = sr, rg = sg, rb = sb;
    switch (mode) {
    case BrushBlendMode::Multiply: rr=dr*sr; rg=dg*sg; rb=db*sb; break;
    case BrushBlendMode::Screen: rr=1-(1-dr)*(1-sr); rg=1-(1-dg)*(1-sg); rb=1-(1-db)*(1-sb); break;
    case BrushBlendMode::Overlay:
        rr=dr<.5f?2*dr*sr:1-2*(1-dr)*(1-sr);
        rg=dg<.5f?2*dg*sg:1-2*(1-dg)*(1-sg);
        rb=db<.5f?2*db*sb:1-2*(1-db)*(1-sb); break;
    case BrushBlendMode::Darken: rr=std::min(dr,sr); rg=std::min(dg,sg); rb=std::min(db,sb); break;
    case BrushBlendMode::Lighten: rr=std::max(dr,sr); rg=std::max(dg,sg); rb=std::max(db,sb); break;
    case BrushBlendMode::Normal: break;
    }
    const float oa=sa+da*(1-sa);
    if (oa<=0) { destination[0]=destination[1]=destination[2]=destination[3]=0; return; }
    const auto channel=[&](float d,float s,float b) {
        return quantizeChannel((sa*(1-da)*s+sa*da*b+(1-sa)*da*d)/oa);
    };
    destination[0]=channel(dr,sr,rr); destination[1]=channel(dg,sg,rg);
    destination[2]=channel(db,sb,rb); destination[3]=quantizeChannel(oa);
}
}

BrushEngine::BrushEngine() = default;

float BrushEngine::clamp01(
    float value
)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

float BrushEngine::applyPressure(
    float pressure,
    bool enabled,
    float minimum,
    float base
)
{
    base =
        clamp01(base);

    minimum =
        clamp01(minimum);

    pressure =
        clamp01(pressure);

    if (!enabled)
        return base;

    return clamp01(
        minimum +
        (base - minimum) *
        pressure
    );
}

void BrushEngine::setSettings(
    const BrushSettings& settings
)
{
    m_settings =
        settings;

    m_settings.size =
        std::max(
            0.01f,
            m_settings.size
        );

    m_settings.opacity =
        clamp01(
            m_settings.opacity
        );

    m_settings.flow =
        clamp01(
            m_settings.flow
        );

    m_settings.hardness =
        clamp01(
            m_settings.hardness
        );

    m_settings.spacing =
        std::max(
            0.001f,
            m_settings.spacing
        );

    m_settings.roundness =
        clamp01(
            m_settings.roundness
        );

    m_settings.scatter =
        clamp01(
            m_settings.scatter
        );

    m_settings.sizeJitter =
        clamp01(
            m_settings.sizeJitter
        );

    m_settings.randomSize = clamp01(m_settings.randomSize);
    m_settings.randomOpacity = clamp01(m_settings.randomOpacity);
    m_settings.velocitySpacing = clamp01(m_settings.velocitySpacing);

    m_settings.rotationJitter =
        std::clamp(
            m_settings.rotationJitter,
            0.0f,
            180.0f
        );

    m_settings.directionFollow = clamp01(m_settings.directionFollow);
    m_settings.tiltElongation = clamp01(m_settings.tiltElongation);
    m_settings.tiltFollow = clamp01(m_settings.tiltFollow);

    m_settings.textureStrength =
        clamp01(
            m_settings.textureStrength
        );

    m_settings.textureScale =
        std::max(
            0.01f,
            m_settings.textureScale
        );

    m_settings.textureRandomScale =
        clamp01(
            m_settings.textureRandomScale
        );

    m_settings.textureRandomOffset =
        clamp01(
            m_settings.textureRandomOffset
        );

    m_settings.textureBrightness =
        std::clamp(
            m_settings.textureBrightness,
            -1.0f,
            1.0f
        );

    m_settings.textureContrast =
        std::max(
            0.0f,
            m_settings.textureContrast
        );

    m_settings.hueJitter =
        std::clamp(
            m_settings.hueJitter,
            0.0f,
            180.0f
        );

    m_settings.saturationJitter =
        clamp01(
            m_settings.saturationJitter
        );

    m_settings.brightnessJitter =
        clamp01(
            m_settings.brightnessJitter
        );

    m_settings.gradientAmount =
        clamp01(
            m_settings.gradientAmount
        );

    m_settings.paintMix =
        clamp01(
            m_settings.paintMix
        );

    m_settings.wetness =
        clamp01(
            m_settings.wetness
        );

    m_settings.pickup =
        clamp01(
            m_settings.pickup
        );

    m_settings.dilution =
        clamp01(
            m_settings.dilution
        );

    m_settings.smudge =
        clamp01(
            m_settings.smudge
        );

    m_settings.paintPersistence =
        clamp01(
            m_settings.paintPersistence
        );

    m_settings.colorCarry =
        clamp01(
            m_settings.colorCarry
        );

    m_settings.minimumSize =
        clamp01(
            m_settings.minimumSize
        );

    m_settings.minimumOpacity =
        clamp01(
            m_settings.minimumOpacity
        );

    m_settings.minimumFlow =
        clamp01(
            m_settings.minimumFlow
        );

    while (m_settings.angle < 0.0f)
        m_settings.angle += 360.0f;

    while (m_settings.angle >= 360.0f)
        m_settings.angle -= 360.0f;

    m_randomState =
        m_settings.randomSeed;
}

const BrushSettings&
BrushEngine::settings() const
{
    return m_settings;
}

void BrushEngine::setColor(
    const QColor& color
)
{
    m_color =
        color;
}

const QColor&
BrushEngine::color() const
{
    return m_color;
}

void BrushEngine::setTexture(
    const QImage& texture
)
{
    if (texture.isNull())
    {
        m_texture =
            QImage();

        return;
    }

    m_texture =
        texture.convertToFormat(
            QImage::Format_Grayscale8
        );
}

void BrushEngine::clearTexture()
{
    m_texture =
        QImage();
}

bool BrushEngine::setBitmapTip(const QImage& image)
{
    if (image.isNull() || image.width() > 4096 || image.height() > 4096)
        return false;
    m_bitmapTip = image.convertToFormat(QImage::Format_ARGB32);
    return !m_bitmapTip.isNull();
}

void BrushEngine::clearBitmapTip()
{
    m_bitmapTip = QImage();
}

bool BrushEngine::hasTexture() const
{
    return !m_texture.isNull();
}

float BrushEngine::evaluateSize(
    float pressure,
    float velocity,
    float tilt
) const
{
    const float velocityFactor = clamp01(velocity);
    const float velocityScale = (1.0f - m_settings.velocitySize) + velocityFactor * m_settings.velocitySize;
    const float tiltScale = (1.0f - m_settings.tiltSize) + clamp01(tilt) * m_settings.tiltSize;
    // 1 = soft (plus de contrôle en basse pression) => sqrt
    // 2 = hard (réponse tardive)                      => p²
    // "Soft" deliberately compresses low pressure for finer control;
    // "Hard" reaches the configured response sooner.  The two mappings had
    // been reversed, making the UI labels and saved presets disagree with
    // the brush engine.
    pressure = m_settings.pressureCurve == 1 ? pressure * pressure :
        (m_settings.pressureCurve == 2 ? std::sqrt(std::max(0.0f, pressure)) : pressure);
    return m_settings.size * velocityScale * tiltScale *
        applyPressure(
            pressure,
            m_settings.pressureSize,
            m_settings.minimumSize,
            1.0f
        );
}

float BrushEngine::evaluateOpacity(
    float pressure,
    float velocity,
    float tilt
) const
{
    pressure = m_settings.pressureCurve == 1 ? pressure * pressure : (m_settings.pressureCurve == 2 ? std::sqrt(std::max(0.0f, pressure)) : pressure);
    const float velocityFactor = clamp01(velocity);
    const float velocityScale = (1.0f - m_settings.velocityOpacity) + velocityFactor * m_settings.velocityOpacity;
    const float tiltScale = (1.0f - m_settings.tiltOpacity) + clamp01(tilt) * m_settings.tiltOpacity;
    return velocityScale * tiltScale * applyPressure(
        pressure,
        m_settings.pressureOpacity,
        m_settings.minimumOpacity,
        m_settings.opacity
    );
}

float BrushEngine::evaluateFlow(
    float pressure,
    float velocity
) const
{
    pressure = m_settings.pressureCurve == 1 ? pressure * pressure : (m_settings.pressureCurve == 2 ? std::sqrt(std::max(0.0f, pressure)) : pressure);
    const float velocityFactor = clamp01(velocity);
    const float velocityScale = (1.0f - m_settings.velocityFlow) + velocityFactor * m_settings.velocityFlow;
    return velocityScale * applyPressure(
        pressure,
        m_settings.pressureFlow,
        m_settings.minimumFlow,
        m_settings.flow
    );
}

/* ============================================================
 * Tampon de trace (stroke buffer)
 *
 * Sépare réellement `flow` et `opacity`, comme Photoshop :
 *   - chaque dab rapproche la couverture du pixel de l'opacité du dab :
 *       c = c + flow·dab·(opacité - c)      (si opacité > c)
 *     la couverture ne dépasse donc jamais l'opacité, même en repassant ;
 *     avec l'opacité à la pression, appuyer plus fort fonce encore la zone,
 *     mais un passage léger n'éclaircit jamais une zone déjà foncée ;
 *   - le pixel est recomposé depuis sa valeur d'avant le trait.
 *
 * L'accumulation se fait en flottant : un flow très bas monte réellement
 * (aucune perte de quantification 8 bits par dab).
 * ============================================================ */

void BrushEngine::resetStrokeBuffer()
{
    m_strokeTiles.tiles.clear();
    m_strokeTiles.tiles.shrink_to_fit();
    m_strokeTilesX = 0;
    m_strokeTilesY = 0;
    m_strokeImageWidth = 0;
    m_strokeImageHeight = 0;
    m_strokeFormat = QImage::Format_Invalid;
    m_strokeBufferActive = false;
}

void BrushEngine::ensureStrokeBuffer(const QImage& image, const QColor& color, bool erase)
{
    const int tilesX = (image.width() + kStrokeTileSize - 1) / kStrokeTileSize;
    const int tilesY = (image.height() + kStrokeTileSize - 1) / kStrokeTileSize;
    const bool sameGeometry = m_strokeBufferActive &&
        m_strokeImageWidth == image.width() &&
        m_strokeImageHeight == image.height() &&
        m_strokeFormat == image.format() &&
        m_strokeTiles.tiles.size() == static_cast<size_t>(tilesX) * static_cast<size_t>(tilesY);
    // Une couleur différente (jitter, couleur sale) ou un changement de mode
    // fige le trait courant : les pixels actuels deviennent la nouvelle
    // origine et la couverture repart de zéro.
    // Per-dab colour jitter must not restart the buffer: the restart
    // recoloured the whole footprint of the dab and left pale bands along
    // the stroke.  The colour is set once per stroke (Photoshop's colour
    // dynamics "per stroke"); only an intentional gradient along the
    // stroke still changes it.
    const bool colourFollowsStroke = m_settings.useStrokeGradient && m_settings.gradientAmount > 0.0f;
    if (sameGeometry && m_strokeErase == erase &&
        (erase || color == m_strokeColor || !colourFollowsStroke))
        return;
    m_strokeTiles.tiles.clear();
    m_strokeTiles.tiles.resize(static_cast<size_t>(tilesX) * static_cast<size_t>(tilesY));
    m_strokeTilesX = tilesX;
    m_strokeTilesY = tilesY;
    m_strokeImageWidth = image.width();
    m_strokeImageHeight = image.height();
    m_strokeFormat = image.format();
    m_strokeErase = erase;
    m_strokeColor = color;
    m_strokeBufferActive = true;
}

BrushEngine::StrokeTile* BrushEngine::strokeTile(const QImage& image, int tileX, int tileY)
{
    auto& slot = m_strokeTiles.tiles[static_cast<size_t>(tileY) * m_strokeTilesX + tileX];
    if (slot)
        return slot.get();
    slot = std::make_unique<StrokeTile>();
    std::fill(std::begin(slot->coverage), std::end(slot->coverage), 0.0f);
    std::fill(std::begin(slot->dual), std::end(slot->dual), 0.0f);
    std::fill(std::begin(slot->original), std::end(slot->original), 0u);
    // Capture de l'origine au premier contact : aucun pixel de cette tuile
    // n'a encore été modifié par le trait.
    const int x0 = tileX * kStrokeTileSize;
    const int y0 = tileY * kStrokeTileSize;
    const int w = std::min(kStrokeTileSize, image.width() - x0);
    const int h = std::min(kStrokeTileSize, image.height() - y0);
    const bool raw32 = image.depth() == 32;
    for (int y = 0; y < h; ++y) {
        uint32_t* destination = slot->original + y * kStrokeTileSize;
        if (raw32) {
            std::memcpy(destination, image.constScanLine(y0 + y) + x0 * 4, size_t(w) * 4);
        } else {
            for (int x = 0; x < w; ++x)
                destination[x] = image.pixelColor(x0 + x, y0 + y).rgba();
        }
    }
    return slot.get();
}

namespace {
// Lit/écrit un pixel 32 bits non prémultiplié dans l'ordre (r, g, b, a).
inline void unpackPixel(uint32_t value, QImage::Format format, float& r, float& g, float& b, float& a)
{
    if (format == QImage::Format_RGBA8888) {
        const auto* bytes = reinterpret_cast<const uint8_t*>(&value);
        r = bytes[0]; g = bytes[1]; b = bytes[2]; a = bytes[3];
    } else {   // ARGB32 et chemin générique (QRgb)
        r = qRed(value); g = qGreen(value); b = qBlue(value); a = qAlpha(value);
    }
    r *= 1.0f / 255.0f; g *= 1.0f / 255.0f; b *= 1.0f / 255.0f; a *= 1.0f / 255.0f;
}

inline void writePixel(QImage& image, int x, int y, float r, float g, float b, float a)
{
    const uint8_t R = quantizeChannel(r), G = quantizeChannel(g), B = quantizeChannel(b), A = quantizeChannel(a);
    switch (image.format()) {
    case QImage::Format_RGBA8888: {
        uint8_t* p = image.scanLine(y) + size_t(x) * 4;
        p[0] = R; p[1] = G; p[2] = B; p[3] = A;
        break;
    }
    case QImage::Format_ARGB32:
        reinterpret_cast<QRgb*>(image.scanLine(y))[x] = qRgba(R, G, B, A);
        break;
    default:
        image.setPixelColor(x, y, QColor(R, G, B, A));
        break;
    }
}
}

void BrushEngine::depositDab(QImage& image, const QImage& dab, int offsetX, int offsetY,
                             float flow, float opacityCap)
{
    if (!m_strokeBufferActive || dab.isNull())
        return;
    const float flowAmount = clamp01(flow);
    const float cap = clamp01(opacityCap);
    if (flowAmount <= 0.0f || cap <= 0.0f)
        return;

    const QImage::Format format = image.format();
    const bool packedFormat = format == QImage::Format_ARGB32 || format == QImage::Format_RGBA8888;
    const QImage::Format storedFormat = packedFormat ? format : QImage::Format_ARGB32;

    const int left = std::max(0, offsetX);
    const int top = std::max(0, offsetY);
    const int right = std::min(image.width(), offsetX + dab.width());
    const int bottom = std::min(image.height(), offsetY + dab.height());

    // Paper grain (canvas-space texture) is applied to the whole stroke, as
    // "texture each tip: off" in Photoshop: the buffer accumulates coverage
    // freely and the grain shapes what is shown.  Height model: a pit of
    // depth d needs coverage above strength·d before it takes pigment, so a
    // light touch only marks the raised fibres and pressing hard fills the
    // tooth, like graphite on real paper.

    for (int py = top; py < bottom; ++py) {
        const auto* dabLine = reinterpret_cast<const QRgb*>(dab.constScanLine(py - offsetY));
        const int tileY = py / kStrokeTileSize;
        const int localY = py - tileY * kStrokeTileSize;
        StrokeTile* tile = nullptr;
        int currentTileX = -1;
        for (int px = left; px < right; ++px) {
            const int dabAlpha = qAlpha(dabLine[px - offsetX]);
            if (dabAlpha == 0)
                continue;
            const int tileX = px / kStrokeTileSize;
            if (tileX != currentTileX) {
                tile = strokeTile(image, tileX, tileY);
                currentTileX = tileX;
            }
            const int index = localY * kStrokeTileSize + (px - tileX * kStrokeTileSize);
            float& coverage = tile->coverage[index];
            if (coverage >= cap)
                continue;   // déjà à l'opacité de ce dab : rien ne change
            const float deposit = flowAmount * static_cast<float>(dabAlpha) * (1.0f / 255.0f);
            coverage = std::min(cap, coverage + deposit * (cap - coverage));

            compositeBufferPixel(image, tile, index, px, py, storedFormat);
        }
    }
}

bool BrushEngine::dualActive() const
{
    return m_settings.dualBrush && m_strokeBufferActive;
}

void BrushEngine::compositeBufferPixel(QImage& image, StrokeTile* tile, int index, int px, int py,
                                       QImage::Format storedFormat)
{
    float shown = tile->coverage[index];
    if (m_settings.dualBrush) {
        const float m = shown, d = tile->dual[index];
        switch (m_settings.dualMode) {
        case 1: shown = std::min(m, d); break;                                       // darken
        case 2: shown = d <= 0.0f ? 0.0f : clamp01(1.0f - (1.0f - m) / d); break;    // colour burn
        case 3: shown = clamp01(m + d - 1.0f); break;                                // linear burn
        case 4: shown = m < 0.5f ? 2.0f * m * d : 1.0f - 2.0f * (1.0f - m) * (1.0f - d); break;
        case 5: shown = d <= 0.0f ? 0.0f : clamp01(m / std::max(1.0e-3f, 1.0f - d) * d); break;
        case 6: shown = (m + d >= 1.0f) ? m : 0.0f; break;                          // hard mix (keeps main softness)
        case 7: shown = clamp01((m - (1.0f - d)) * 2.0f); break;                    // linear height
        default: shown = m * d; break;                                               // multiply
        }
    }
    if (m_settings.textureCanvasSpace && !m_texture.isNull() && m_settings.textureStrength > 0.0f) {
        const float grainTile = std::max(8.0f, m_settings.textureScale * 256.0f);
        const float grain = BrushTexture::sample(
            m_texture, m_settings, (px + 0.5f) / grainTile, (py + 0.5f) / grainTile, false);
        const float depth = clamp01(m_settings.textureStrength) * (1.0f - grain);
        shown = clamp01((shown - depth) / std::max(1.0e-3f, 1.0f - depth));
    }
    float dr, dg, db, da;
    unpackPixel(tile->original[index], storedFormat, dr, dg, db, da);
    if (m_strokeErase) {
        writePixel(image, px, py, dr, dg, db, da * (1.0f - shown));
        return;
    }
    const float sa = shown;
    const float oa = sa + da * (1.0f - sa);
    if (oa <= 0.0f) {
        writePixel(image, px, py, 0.0f, 0.0f, 0.0f, 0.0f);
        return;
    }
    const float keep = da * (1.0f - sa);
    const float red = m_strokeColor.redF(), green = m_strokeColor.greenF(), blue = m_strokeColor.blueF();
    writePixel(image, px, py, (red * sa + dr * keep) / oa, (green * sa + dg * keep) / oa,
               (blue * sa + db * keep) / oa, oa);
}

void BrushEngine::stampDualAlong(QImage& image, const QPointF& from, const QPointF& to, float mainSize)
{
    const float size = std::max(1.0f, mainSize * std::max(0.05f, m_settings.dualSizeRatio));
    const double step = std::max(0.5, static_cast<double>(size) * std::max(0.01f, m_settings.dualSpacing));
    const QPointF delta = to - from;
    const double distance = std::hypot(delta.x(), delta.y());
    double travelled = step - std::min(m_dualRemainder, step);
    if (distance <= 0.0)
        travelled = 0.0;
    const QImage::Format format = image.format();
    const bool packed = format == QImage::Format_ARGB32 || format == QImage::Format_RGBA8888;
    const QImage::Format storedFormat = packed ? format : QImage::Format_ARGB32;
    BrushSettings tipSettings = m_settings;
    tipSettings.hardness = m_settings.dualHardness;
    tipSettings.roundness = 1.0f;
    tipSettings.textureStrength = 0.0f;
    tipSettings.antialiasing = true;
    const int count = std::clamp(m_settings.dualCount, 1, 16);
    for (; travelled <= distance; travelled += step) {
        const double t = distance > 0.0 ? travelled / distance : 0.0;
        const QPointF base = from + delta * t;
        for (int n = 0; n < count; ++n) {
            const float scatter = m_settings.dualScatter * size;
            const double x = base.x() + (scatter > 0.0f ? BrushRandom::range(m_randomState, -scatter, scatter) : 0.0f);
            const double y = base.y() + (scatter > 0.0f ? BrushRandom::range(m_randomState, -scatter, scatter) : 0.0f);
            const float rotation = m_dualTip.isNull() ? 0.0f : BrushRandom::range(m_randomState, 0.0f, 360.0f);
            const int side = std::max(4, static_cast<int>(std::ceil(size)) + 6);
            QImage dab(side, side, QImage::Format_ARGB32);
            dab.fill(Qt::transparent);
            const double cornerX = std::floor(x - side * 0.5);
            const double cornerY = std::floor(y - side * 0.5);
            BrushTip::draw(dab, tipSettings, QPointF(side * 0.5, side * 0.5), size, 1.0f, rotation,
                           1.0f, 0.0f, 0.0f, false, Qt::white, QImage(), m_dualTip,
                           static_cast<float>(x - side * 0.5 - cornerX),
                           static_cast<float>(y - side * 0.5 - cornerY), 1.0f);
            for (int wy = -1; wy <= 1; ++wy)
            for (int wx = -1; wx <= 1; ++wx) {
            if ((wx || wy) && !m_settings.wrapAround)
                continue;
            const int offsetX = static_cast<int>(cornerX) + wx * image.width();
            const int offsetY = static_cast<int>(cornerY) + wy * image.height();
            const int left = std::max(0, offsetX), top = std::max(0, offsetY);
            const int right = std::min(image.width(), offsetX + side);
            const int bottom = std::min(image.height(), offsetY + side);
            if (left >= right || top >= bottom)
                continue;
            for (int py = top; py < bottom; ++py) {
                const auto* line = reinterpret_cast<const QRgb*>(dab.constScanLine(py - offsetY));
                const int tileY = py / kStrokeTileSize;
                const int localY = py - tileY * kStrokeTileSize;
                for (int px = left; px < right; ++px) {
                    const int alpha = qAlpha(line[px - offsetX]);
                    if (alpha == 0)
                        continue;
                    const int tileX = px / kStrokeTileSize;
                    StrokeTile* tile = strokeTile(image, tileX, tileY);
                    const int index = localY * kStrokeTileSize + (px - tileX * kStrokeTileSize);
                    const float value = alpha * (1.0f / 255.0f);
                    if (value <= tile->dual[index])
                        continue;
                    tile->dual[index] = value;
                    if (tile->coverage[index] > 0.0f)
                        compositeBufferPixel(image, tile, index, px, py, storedFormat);
                }
            }
            }   // wrap shifts
        }
        if (distance <= 0.0)
            break;
    }
    m_dualRemainder = distance > 0.0 ? distance - (travelled - step) : step;
    if (m_dualRemainder < 0.0)
        m_dualRemainder = 0.0;
}

bool BrushEngine::setDualTip(const QImage& image)
{
    if (image.isNull() || image.width() > 4096 || image.height() > 4096)
        return false;
    m_dualTip = image.convertToFormat(QImage::Format_ARGB32);
    return true;
}

void BrushEngine::clearDualTip()
{
    m_dualTip = QImage();
}


void BrushEngine::wetDab(QImage& image, const QImage& dab, int offsetX, int offsetY,
                         const QColor& pigment, float strength, int dragX, int dragY,
                         float smear, float pigmentRate, float pigmentAlpha)
{
    if (dab.isNull() || strength <= 0.0f)
        return;
    const QImage::Format format = image.format();
    // Snapshot of the paint under the previous dab position: dragging reads
    // the canvas as it was before this dab, never pixels it just wrote.
    const QImage dragged = image.copy(offsetX - dragX, offsetY - dragY, dab.width(), dab.height());
    const float pr = pigment.redF(), pg = pigment.greenF(), pb = pigment.blueF();
    const float pa = clamp01(pigmentAlpha);
    const int left = std::max(0, offsetX), top = std::max(0, offsetY);
    const int right = std::min(image.width(), offsetX + dab.width());
    const int bottom = std::min(image.height(), offsetY + dab.height());
    for (int py = top; py < bottom; ++py) {
        const auto* dabLine = reinterpret_cast<const QRgb*>(dab.constScanLine(py - offsetY));
        const uchar* dragLine = dragged.constScanLine(py - offsetY);
        const uchar* destLine = image.constScanLine(py);
        for (int px = left; px < right; ++px) {
            const int mask = qAlpha(dabLine[px - offsetX]);
            if (mask == 0)
                continue;
            const float k = strength * mask * (1.0f / 255.0f);
            float br, bg, bb, ba, dr, dg, db, da;
            uint32_t baseRaw, dragRaw;
            std::memcpy(&baseRaw, destLine + size_t(px) * 4, 4);
            std::memcpy(&dragRaw, dragLine + size_t(px - offsetX) * 4, 4);
            unpackPixel(baseRaw, format, br, bg, bb, ba);
            unpackPixel(dragRaw, format, dr, dg, db, da);
            // Work premultiplied so transparent paint never drags in black
            // or invents white.
            float sr = br * ba + (dr * da - br * ba) * smear;
            float sg = bg * ba + (dg * da - bg * ba) * smear;
            float sb = bb * ba + (db * da - bb * ba) * smear;
            float sa = ba + (da - ba) * smear;
            sr += (pr * pa - sr) * pigmentRate;
            sg += (pg * pa - sg) * pigmentRate;
            sb += (pb * pa - sb) * pigmentRate;
            sa += (pa - sa) * pigmentRate;
            const float rr = br * ba + (sr - br * ba) * k;
            const float rg = bg * ba + (sg - bg * ba) * k;
            const float rb = bb * ba + (sb - bb * ba) * k;
            const float ra = ba + (sa - ba) * k;
            if (ra <= 1.0e-4f)
                writePixel(image, px, py, 0.0f, 0.0f, 0.0f, 0.0f);
            else
                writePixel(image, px, py, rr / ra, rg / ra, rb / ra, ra);
        }
    }
}

void BrushEngine::eraseDabDirect(QImage& image, const QImage& dab, int offsetX, int offsetY, float strength)
{
    const float amount = clamp01(strength);
    if (amount <= 0.0f || dab.isNull())
        return;
    const int left = std::max(0, offsetX);
    const int top = std::max(0, offsetY);
    const int right = std::min(image.width(), offsetX + dab.width());
    const int bottom = std::min(image.height(), offsetY + dab.height());
    for (int py = top; py < bottom; ++py) {
        const auto* dabLine = reinterpret_cast<const QRgb*>(dab.constScanLine(py - offsetY));
        for (int px = left; px < right; ++px) {
            const int dabAlpha = qAlpha(dabLine[px - offsetX]);
            if (dabAlpha == 0)
                continue;
            const float erase = amount * static_cast<float>(dabAlpha) * (1.0f / 255.0f);
            if (image.format() == QImage::Format_RGBA8888) {
                uint8_t* p = image.scanLine(py) + size_t(px) * 4;
                p[3] = quantizeChannel(p[3] * (1.0f / 255.0f) * (1.0f - erase));
            } else if (image.format() == QImage::Format_ARGB32) {
                auto* row = reinterpret_cast<QRgb*>(image.scanLine(py));
                const QRgb pixel = row[px];
                row[px] = qRgba(qRed(pixel), qGreen(pixel), qBlue(pixel),
                                quantizeChannel(qAlpha(pixel) * (1.0f / 255.0f) * (1.0f - erase)));
            } else {
                QColor pixel = image.pixelColor(px, py);
                pixel.setAlphaF(pixel.alphaF() * (1.0f - erase));
                image.setPixelColor(px, py, pixel);
            }
        }
    }
}

void BrushEngine::beginStroke(
    const BrushInput& input
)
{
    m_lastInput =
        input;

    m_lastInput.pressure =
        clamp01(
            m_lastInput.pressure
        );

    ++m_strokeCounter;
    m_randomState =
        m_settings.randomSeed ^ (m_strokeCounter * 0x9E3779B9u);
    if (m_randomState == 0)
        m_randomState = m_settings.randomSeed | 1u;

    m_previousColor =
        m_color;

    m_hasPreviousColor =
        false;

    m_hasPreviousDab = false;
    m_dualRemainder = 0.0;
    m_wet.begin(
        m_color,
        m_settings
    );

    // Reliquat « plein » : le premier segment pose donc un dab dès son
    // origine, c'est-à-dire exactement sur le point d'appui du stylet.
    m_distanceRemainder = std::numeric_limits<double>::max();

    // Le tampon de trace est (ré)armé au premier dab, quand on connaît la
    // taille de l'image cible et l'opacité effective.
    resetStrokeBuffer();

    // Le stabilisateur repart du point d'appui : sans cela, un trait dont la
    // fin n'avait pas appelé endStroke (worker asynchrone) démarrait lissé
    // depuis la fin du trait précédent.
    m_hasSmoothPoint = false;
    m_smoothVelocity = QPointF();

    m_hasStroke =
        true;
}

void BrushEngine::drawSegment(
    QImage& image,
    const BrushInput& start,
    const BrushInput& end,
    const QImage* cloneSource,
    int cloneOffsetX,
    int cloneOffsetY
)
{
    if (image.isNull())
        return;

    const float startPressure =
        clamp01(
            start.pressure
        );

    const float endPressure =
        clamp01(
            end.pressure
        );

    const QPointF delta =
        end.position -
        start.position;

    const double distance =
        std::hypot(
            delta.x(),
            delta.y()
        );

    const float normalizedVelocity = clamp01(static_cast<float>(distance) / std::max(20.0f, m_settings.size * 2.0f));
    const float normalizedTiltStart = clamp01(std::hypot(start.tiltX, start.tiltY) / 90.0f);
    const float normalizedTiltEnd = clamp01(std::hypot(end.tiltX, end.tiltY) / 90.0f);

    /*
     * Direction du trait (tangente) et azimut du stylet.
     *
     * `delta` contenait déjà la direction mais n'était jamais exploité : la
     * rotation du dab ne dépendait que de settings.angle + jitter, donc un
     * pinceau plat gardait le même biseau dans tous les sens.
     */
    const bool hasDirection = distance > 1e-6;
    const float strokeAngle = hasDirection
        ? static_cast<float>(std::atan2(delta.y(), delta.x()) * 180.0 / 3.14159265358979323846)
        : m_lastStrokeAngle;
    if (hasDirection)
        m_lastStrokeAngle = strokeAngle;

    const float tiltMagnitude = (normalizedTiltStart + normalizedTiltEnd) * 0.5f;
    const bool hasTilt = std::hypot(end.tiltX, end.tiltY) > 1e-6f;
    const float tiltAzimuth = hasTilt
        ? static_cast<float>(std::atan2(static_cast<double>(end.tiltY),
                                        static_cast<double>(end.tiltX))
                             * 180.0 / 3.14159265358979323846)
        : 0.0f;

    const float startSize =
        evaluateSize(
            startPressure,
            normalizedVelocity,
            normalizedTiltStart
        );

    const float endSize =
        evaluateSize(
            endPressure,
            normalizedVelocity,
            normalizedTiltEnd
        );

    const float startOpacity =
        evaluateOpacity(
            startPressure,
            normalizedVelocity,
            normalizedTiltStart
        );

    const float endOpacity =
        evaluateOpacity(
            endPressure,
            normalizedVelocity,
            normalizedTiltEnd
        );

    const float startFlow =
        evaluateFlow(
            startPressure,
            normalizedVelocity
        );

    const float endFlow =
        evaluateFlow(
            endPressure,
            normalizedVelocity
        );

    const double averageSize =
        std::max(
            0.01,
            static_cast<double>(
                (startSize +
                 endSize) *
                0.5f
            )
        );

    const double spacingDistance =
        std::max(
            0.5,
            averageSize *
            static_cast<double>(
                m_settings.spacing *
                (1.0f + m_settings.velocitySpacing * normalizedVelocity)
            )
        );

    // Espacement continu : on avance le long du segment par pas de
    // spacingDistance en reportant le reliquat, au lieu de redécouper chaque
    // segment indépendamment.  Le dab de fin (t == 1) n'est jamais posé ici,
    // il appartient au segment suivant : sinon chaque jointure reçoit deux
    // dabs superposés et le trait « perle » à chaque événement stylet.
    // Distance jusqu'au prochain dab, en tenant compte de ce qui restait à
    // parcourir à la fin du segment précédent.
    const bool stationary = distance <= 0.0;

    // Dual brush runs on its own spacing along the whole segment, before
    // the main dabs, so the main tip finds the second tip's mask in place.
    const bool bufferEligible = m_settings.flowAccumulation &&
        (m_settings.eraser || (m_settings.blendMode == BrushBlendMode::Normal &&
                               !m_settings.smudgeTool && !m_settings.wetMix && cloneSource == nullptr));
    if (m_settings.dualBrush && bufferEligible) {
        ensureStrokeBuffer(image, m_color, m_settings.eraser);
        stampDualAlong(image, start.position, end.position, static_cast<float>(averageSize));
    }

    // A press/release at one point is a real dab.  Treating it like a
    // zero-length segment and waiting for spacingDistance made bitmap tips,
    // textures and ordinary clicks render nothing at all.
    if (stationary)
        m_distanceRemainder = spacingDistance;
    else if (m_distanceRemainder > spacingDistance)
        m_distanceRemainder = spacingDistance;   // premier dab du trait

    double travelled = spacingDistance - m_distanceRemainder;
    if (travelled < 0.0)
        travelled = 0.0;

    if (travelled > distance)
    {
        // Segment trop court pour atteindre le prochain dab : on accumule.
        m_distanceRemainder += distance;
        m_lastInput = end;
        return;
    }

    for (; travelled <= distance; travelled += spacingDistance)
    {
        const float t = stationary ? 0.0f : static_cast<float>(travelled / distance);

        const QPointF basePosition =
            start.position +
            delta * t;

        const float baseSize =
            startSize +
            (endSize -
             startSize) *
            t;

        const float opacity =
            startOpacity +
            (endOpacity -
             startOpacity) *
            t;

        const float flow =
            startFlow +
            (endFlow -
             startFlow) *
            t;

        const float pressure =
            startPressure +
            (endPressure -
             startPressure) *
            t;

        const float scatterAmount =
            m_settings.scatter *
            baseSize *
            0.5f;

        const float scatterX =
            BrushRandom::range(
                m_randomState,
                -scatterAmount,
                scatterAmount
            );

        const float scatterY =
            BrushRandom::range(
                m_randomState,
                -scatterAmount,
                scatterAmount
            );

        const float sizeVariation =
            BrushRandom::range(
                m_randomState,
                -m_settings.sizeJitter,
                m_settings.sizeJitter
            ) + BrushRandom::range(
                m_randomState,
                -m_settings.randomSize,
                m_settings.randomSize
            );

        const float sizeMultiplier =
            std::max(
                0.05f,
                1.0f +
                sizeVariation
            );

        const float finalSize =
            baseSize *
            sizeMultiplier;

        const float rotationVariation =
            BrushRandom::range(
                m_randomState,
                -m_settings.rotationJitter,
                m_settings.rotationJitter
            );

        float finalRotation =
            m_settings.angle +
            rotationVariation;

        // Le dab suit la tangente du trait, puis l'azimut du stylet.
        if (m_settings.directionFollow > 0.0f)
            finalRotation += m_settings.directionFollow * strokeAngle;
        if (m_settings.tiltFollow > 0.0f && hasTilt)
            finalRotation += m_settings.tiltFollow * tiltAzimuth;

        float textureScale =
            m_settings.textureScale;

        if (m_settings.textureRandomScale > 0.0f)
        {
            const float variation =
                BrushRandom::range(
                    m_randomState,
                    -m_settings.textureRandomScale,
                    m_settings.textureRandomScale
                );

            textureScale *=
                std::max(
                    0.05f,
                    1.0f +
                    variation
                );
        }

        float textureOffsetX =
            0.0f;

        float textureOffsetY =
            0.0f;

        if (m_settings.textureRandomOffset > 0.0f)
        {
            textureOffsetX =
                BrushRandom::range(
                    m_randomState,
                    -m_settings.textureRandomOffset,
                    m_settings.textureRandomOffset
                );

            textureOffsetY =
                BrushRandom::range(
                    m_randomState,
                    -m_settings.textureRandomOffset,
                    m_settings.textureRandomOffset
                );
        }

        const QColor freshColor =
            BrushColor::evaluate(
                m_settings,
                m_color,
                m_previousColor,
                m_hasPreviousColor,
                t,
                pressure,
                m_randomState
            );

        m_wet.update(
            image,
            basePosition,
            finalSize,
            freshColor,
            pressure,
            m_settings
        );

        QColor finalColor =
            freshColor;

        if (m_settings.smudgeTool)
        {
            finalColor = m_wet.color();
        }

        else if (m_settings.wetMix &&
            m_settings.wetness > 0.0f)
        {
            // BrushWet already resolved fresh pigment, carried pigment and
            // canvas pickup.  A second lerp here weakened pickup and made
            // wet strokes look like a translucent overlay.
            finalColor = m_wet.color();
        }

        const float opacityVariation = BrushRandom::range(
            m_randomState,
            -m_settings.randomOpacity,
            m_settings.randomOpacity
        );
        const float paintAlpha =
            clamp01(opacity * (1.0f + opacityVariation)) * flow *
            (m_settings.smudgeTool
                ? std::max(0.05f, m_settings.smudge)
                : m_settings.paintMix);

        /*
         * BrushTip produit le masque du dab (forme, dureté, texture, pointe
         * bitmap, position sous-pixel).  La gomme utilise exactement le même
         * masque : elle respecte donc la dureté et la forme du pinceau au
         * lieu d'un cône flou aimanté sur la grille de pixels.
         *
         * Chemin « tampon de trace » : dépôt de couleur simple et gomme.
         * Les modes de fusion, le clone et le smudge lisent la destination
         * pixel par pixel et restent sur le blit direct.
         */
        const bool eraseMode = m_settings.eraser;
        const bool useStrokeMask =
            m_settings.flowAccumulation &&
            (eraseMode ||
             (m_settings.blendMode == BrushBlendMode::Normal &&
              !m_settings.smudgeTool &&
              !m_settings.wetMix &&
              cloneSource == nullptr));
        // Le tampon applique lui-même flow et opacité : le masque du dab
        // reste à pleine couverture, sinon l'atténuation serait comptée deux
        // fois.
        const bool wetPathPlanned = (m_settings.wetMix || m_settings.smudgeTool)
            && m_settings.blendMode == BrushBlendMode::Normal && cloneSource == nullptr;
        const bool fullCoverageDab = useStrokeMask || eraseMode || wetPathPlanned;
        {
            QImage dab(
                std::max(4, static_cast<int>(std::ceil(finalSize)) + 6),
                std::max(4, static_cast<int>(std::ceil(finalSize)) + 6),
                QImage::Format_ARGB32
            );

            dab.fill(
                Qt::transparent
            );

            // Position exacte (flottante) du centre du dab sur le canvas.
            const double exactX = basePosition.x() + scatterX;
            const double exactY = basePosition.y() + scatterY;

            // Coin entier du bitmap, puis résidu fractionnaire transmis au
            // profil : le dab n'est plus aimanté sur la grille de pixels.
            const double cornerX = std::floor(exactX - dab.width() * 0.5);
            const double cornerY = std::floor(exactY - dab.height() * 0.5);
            const float subpixelX =
                static_cast<float>(exactX - dab.width() * 0.5 - cornerX);
            const float subpixelY =
                static_cast<float>(exactY - dab.height() * 0.5 - cornerY);

            float tipTextureScale = textureScale;
            float tipTextureOffsetX = textureOffsetX;
            float tipTextureOffsetY = textureOffsetY;
            if (m_settings.textureCanvasSpace) {
                tipTextureScale = std::max(8.0f, m_settings.textureScale * 256.0f);
                tipTextureOffsetX = static_cast<float>(exactX);
                tipTextureOffsetY = static_cast<float>(exactY);
            }
            BrushTip::draw(
                dab,
                m_settings,
                QPointF(
                    dab.width() * 0.5,
                    dab.height() * 0.5
                ),
                finalSize,
                fullCoverageDab ? 1.0f : paintAlpha,
                finalRotation,
                tipTextureScale,
                tipTextureOffsetX,
                tipTextureOffsetY,
                m_settings.textureMirror,
                finalColor,
                m_texture,
                m_bitmapTip,
                subpixelX,
                subpixelY,
                // Plus le stylet est incliné, plus le dab s'aplatit.
                1.0f - m_settings.tiltElongation * tiltMagnitude
            );

            const int baseOffsetX = static_cast<int>(cornerX);
            const int baseOffsetY = static_cast<int>(cornerY);
            QPoint wrapShifts[9] = {QPoint(0, 0)};
            int wrapCount = 1;
            if (m_settings.wrapAround) {
                const QRect bounds(0, 0, image.width(), image.height());
                for (int sy = -1; sy <= 1; ++sy)
                    for (int sx = -1; sx <= 1; ++sx) {
                        if (!sx && !sy)
                            continue;
                        const QPoint shift(sx * image.width(), sy * image.height());
                        if (QRect(baseOffsetX + shift.x(), baseOffsetY + shift.y(),
                                  dab.width(), dab.height()).intersects(bounds))
                            wrapShifts[wrapCount++] = shift;
                    }
            }
            for (int wrapIndex = 0; wrapIndex < wrapCount; ++wrapIndex) {
            const int offsetX = baseOffsetX + wrapShifts[wrapIndex].x();
            const int offsetY = baseOffsetY + wrapShifts[wrapIndex].y();

            if (useStrokeMask) {
                ensureStrokeBuffer(image, finalColor, eraseMode);
                depositDab(image, dab, offsetX, offsetY,
                           flow * (eraseMode ? 1.0f : m_settings.paintMix),
                           opacity);
                continue;
            }

            if (eraseMode) {
                eraseDabDirect(image, dab, offsetX, offsetY, paintAlpha);
                continue;
            }

            const bool wetPath = (m_settings.wetMix || m_settings.smudgeTool)
                && m_settings.blendMode == BrushBlendMode::Normal && cloneSource == nullptr
                && (image.format() == QImage::Format_RGBA8888 || image.format() == QImage::Format_ARGB32);
            if (wetPath) {
                int dragX = 0, dragY = 0;
                if (m_hasPreviousDab) {
                    const double limit = std::max(1.0, static_cast<double>(finalSize));
                    dragX = static_cast<int>(std::lround(std::clamp(exactX - m_previousDab.x(), -limit, limit)));
                    dragY = static_cast<int>(std::lround(std::clamp(exactY - m_previousDab.y(), -limit, limit)));
                }
                const float wetness = clamp01(m_settings.wetness);
                const float smear = m_settings.smudgeTool
                    ? clamp01(0.35f + 0.65f * m_settings.smudge)
                    : clamp01(m_settings.smudge + 0.6f * wetness * m_settings.pickup);
                const float pigmentRate = m_settings.smudgeTool
                    ? 0.0f
                    : std::clamp(m_settings.paintMix * (1.0f - 0.7f * wetness), 0.05f, 1.0f);
                const float pigmentAlpha = 1.0f - 0.75f * clamp01(m_settings.dilution);
                // Rates are defined per quarter-diameter of travel, then
                // converted to per-dab rates: with dense spacing twenty dabs
                // overlap, and a raw per-dab rate compounded to an opaque,
                // unmixed stroke.
                const float spacingFactor = std::clamp(m_settings.spacing / 0.25f, 0.02f, 1.0f);
                auto perDab = [spacingFactor](float rate) {
                    return 1.0f - std::pow(1.0f - std::clamp(rate, 0.0f, 0.999f), spacingFactor);
                };
                wetDab(image, dab, offsetX, offsetY, finalColor, clamp01(opacity * flow),
                       dragX, dragY, smear, perDab(pigmentRate), pigmentAlpha);
                m_previousDab = QPointF(exactX, exactY);
                m_hasPreviousDab = true;
                continue;
            }

            const bool fastRgba = image.format() == QImage::Format_RGBA8888;
            for (int y = 0; y < dab.height(); ++y) {
                const int py = offsetY + y;
                if (py < 0 || py >= image.height()) continue;
                const auto* sourceLine = reinterpret_cast<const QRgb*>(dab.constScanLine(y));
                auto* rgbaDestination = fastRgba ? image.scanLine(py) : nullptr;
                for (int x = 0; x < dab.width(); ++x) {
                    const int px = offsetX + x;
                    if (px < 0 || px >= image.width()) continue;
                    const QRgb sourcePixel = sourceLine[x];
                    if (qAlpha(sourcePixel) == 0) continue;

                    if (fastRgba) {
                        uint8_t sourceBytes[4] = {
                            static_cast<uint8_t>(qRed(sourcePixel)),
                            static_cast<uint8_t>(qGreen(sourcePixel)),
                            static_cast<uint8_t>(qBlue(sourcePixel)),
                            static_cast<uint8_t>(qAlpha(sourcePixel)),
                        };
                        if (cloneSource != nullptr) {
                            const int sx = px + cloneOffsetX, sy = py + cloneOffsetY;
                            if (sx < 0 || sy < 0 || sx >= cloneSource->width() || sy >= cloneSource->height())
                                continue;
                            const uchar* sampled = cloneSource->constScanLine(sy) + sx * 4;
                            const int alpha = qRound(sampled[3] * (sourceBytes[3] / 255.0));
                            if (alpha <= 0) continue;
                            sourceBytes[0] = sampled[0]; sourceBytes[1] = sampled[1];
                            sourceBytes[2] = sampled[2]; sourceBytes[3] = static_cast<uint8_t>(alpha);
                        }
                        if (m_settings.blendMode == BrushBlendMode::Normal && sourceBytes[3] == 255) {
                            // Exact Normal opaque fast path: source replaces destination.
                            creative_simd::copyRgba(rgbaDestination + px * 4, sourceBytes, 1);
                        } else {
                            blendRgba8888(rgbaDestination + px * 4, sourceBytes, m_settings.blendMode);
                        }
                        continue;
                    }

                    QColor source = QColor::fromRgba(sourcePixel);
                    if (cloneSource != nullptr) {
                        const int sx = px + cloneOffsetX, sy = py + cloneOffsetY;
                        if (sx < 0 || sy < 0 || sx >= cloneSource->width() || sy >= cloneSource->height())
                            continue;
                        const uchar* sampled = cloneSource->constScanLine(sy) + sx * 4;
                        QColor replacement(sampled[0], sampled[1], sampled[2], sampled[3]);
                        if (replacement.alpha() == 0) continue;
                        replacement.setAlpha(qRound(replacement.alpha() * source.alphaF()));
                        source = replacement;
                    }
                    const QColor destination = image.format() == QImage::Format_ARGB32
                        ? QColor::fromRgba(reinterpret_cast<const QRgb*>(image.constScanLine(py))[px])
                        : image.pixelColor(px, py);
                    const QColor result = BrushPaint::blendPixel(
                        destination, source, m_settings.blendMode, source.alphaF());
                    if (image.format() == QImage::Format_ARGB32)
                        reinterpret_cast<QRgb*>(image.scanLine(py))[px] = result.rgba();
                    else
                        image.setPixelColor(px, py, result);
                }
            }
            }   // wrap shifts
        }
    }

    // Distance restante après le dernier dab posé : elle sera consommée par
    // le segment suivant pour que l'espacement reste continu sur tout le trait.
    m_distanceRemainder = stationary ? 0.0 : distance - (travelled - spacingDistance);
    if (m_distanceRemainder < 0.0)
        m_distanceRemainder = 0.0;

    m_lastInput =
        end;

    m_lastInput.pressure =
        endPressure;

    m_hasStroke =
        true;
}

void BrushEngine::endStroke()
{
    m_hasStroke =
        false;
    m_hasPreviousDab = false;
    m_distanceRemainder = 0.0;
    resetStrokeBuffer();
    m_hasSmoothPoint = false;
    m_smoothVelocity = QPointF();
}

void BrushEngine::setSmoothing(float strength)
{
    m_smoothing = clamp01(strength);
}

QPointF BrushEngine::smoothPoint(const QPointF& point)
{
    // Preserve the legacy brush response: filtered velocity predicts motion,
    // adaptive responsiveness restores fast strokes, and micro-motion is damped.
    const double strength = m_smoothing;
    if (strength <= 0.0) {
        m_smoothLastInput = point;
        m_smoothLastOutput = point;
        m_hasSmoothPoint = true;
        return point;
    }
    if (!m_hasSmoothPoint) {
        m_smoothLastInput = point;
        m_smoothLastOutput = point;
        m_smoothVelocity = QPointF();
        m_hasSmoothPoint = true;
        return point;
    }
    const QPointF delta = point - m_smoothLastInput;
    const double distance = std::hypot(delta.x(), delta.y());
    const double velocityMix = 0.55 + strength * 0.25;
    m_smoothVelocity = m_smoothVelocity * (1.0 - velocityMix) + delta * velocityMix;
    double responsiveness = std::clamp(0.72 - strength * 0.48, 0.18, 0.72);
    if (distance > 20.0)
        responsiveness = std::clamp(responsiveness + std::min(0.20, distance / 250.0), 0.18, 0.88);
    const QPointF target = point + m_smoothVelocity * (0.18 + strength * 0.12);
    QPointF output = m_smoothLastOutput + (target - m_smoothLastOutput) * responsiveness;
    if (distance < 3.0) {
        const double microMotion = 0.45 * strength;
        output = output * (1.0 - microMotion) + m_smoothLastOutput * microMotion;
    }
    m_smoothLastInput = point;
    m_smoothLastOutput = output;
    return output;
}
