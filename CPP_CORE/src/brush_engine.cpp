#include "brush_engine.h"
#include "simd_runtime.h"

#include <algorithm>
#include <cmath>
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
 * Tampon de trace
 *
 * Sépare réellement `flow` et `opacity`, comme Photoshop :
 *   - chaque dab accumule sa couverture : a = a + flow·coverage·(1-a)
 *   - la saturation à 1 est naturelle, sans clamp artificiel
 *   - le masque est composité une seule fois à l'opacité cible
 *
 * Effet de bord bénéfique : l'accumulation se fait en flottant, ce qui
 * supprime la perte de précision 8 bits sur les flows très bas (un dab
 * d'alpha 1/255 sur un pixel opaque ne disparaissait plus après
 * quantification, donc l'aérographe ne montait jamais).
 * ============================================================ */

void BrushEngine::beginStrokeMask(int width, int height, float opacity, const QColor& color)
{
    if (width <= 0 || height <= 0) {
        m_strokeMaskActive = false;
        return;
    }
    m_strokeMaskWidth = width;
    m_strokeMaskHeight = height;
    m_strokeMask.assign(static_cast<size_t>(width) * static_cast<size_t>(height), 0.0f);
    m_strokeOpacity = clamp01(opacity);
    m_strokeColor = color;
    m_strokeMaskActive = true;
    m_strokeDirtyLeft = width;
    m_strokeDirtyTop = height;
    m_strokeDirtyRight = -1;
    m_strokeDirtyBottom = -1;
}

void BrushEngine::accumulateStrokeMask(const QImage& dab, int offsetX, int offsetY, float flow)
{
    if (!m_strokeMaskActive || dab.isNull())
        return;

    const float flowAmount = clamp01(flow);
    if (flowAmount <= 0.0f)
        return;

    for (int y = 0; y < dab.height(); ++y) {
        const int py = offsetY + y;
        if (py < 0 || py >= m_strokeMaskHeight)
            continue;
        const auto* sourceLine = reinterpret_cast<const QRgb*>(dab.constScanLine(y));
        float* maskRow = m_strokeMask.data() + static_cast<size_t>(py) * m_strokeMaskWidth;

        for (int x = 0; x < dab.width(); ++x) {
            const int px = offsetX + x;
            if (px < 0 || px >= m_strokeMaskWidth)
                continue;
            const int dabAlpha = qAlpha(sourceLine[x]);
            if (dabAlpha == 0)
                continue;

            const float coverage = static_cast<float>(dabAlpha) * (1.0f / 255.0f);
            const float deposit = flowAmount * coverage;
            float& accumulated = maskRow[px];
            // Saturation naturelle : on ne dépasse jamais 1.
            accumulated = accumulated + deposit * (1.0f - accumulated);

            if (px < m_strokeDirtyLeft)   m_strokeDirtyLeft = px;
            if (px > m_strokeDirtyRight)  m_strokeDirtyRight = px;
            if (py < m_strokeDirtyTop)    m_strokeDirtyTop = py;
            if (py > m_strokeDirtyBottom) m_strokeDirtyBottom = py;
        }
    }
}

void BrushEngine::flushStrokeMask(QImage& image)
{
    if (!m_strokeMaskActive || m_strokeDirtyRight < m_strokeDirtyLeft)
        return;

    const int left   = std::max(0, m_strokeDirtyLeft);
    const int top    = std::max(0, m_strokeDirtyTop);
    const int right  = std::min(image.width() - 1, m_strokeDirtyRight);
    const int bottom = std::min(image.height() - 1, m_strokeDirtyBottom);

    const float red   = static_cast<float>(m_strokeColor.red())   * (1.0f / 255.0f);
    const float green = static_cast<float>(m_strokeColor.green()) * (1.0f / 255.0f);
    const float blue  = static_cast<float>(m_strokeColor.blue())  * (1.0f / 255.0f);

    for (int py = top; py <= bottom; ++py) {
        const float* maskRow = m_strokeMask.data() + static_cast<size_t>(py) * m_strokeMaskWidth;
        for (int px = left; px <= right; ++px) {
            const float coverage = maskRow[px];
            if (coverage <= 0.0f)
                continue;
            // L'opacité cible plafonne la couverture accumulée : c'est ce qui
            // rend `opacity` et `flow` réellement distincts.
            const float sourceAlpha = coverage * m_strokeOpacity;
            if (sourceAlpha <= 0.0f)
                continue;

            if (image.format() == QImage::Format_ARGB32) {
                auto* row = reinterpret_cast<QRgb*>(image.scanLine(py));
                const QRgb destination = row[px];
                const float da = static_cast<float>(qAlpha(destination)) * (1.0f / 255.0f);
                const float oa = sourceAlpha + da * (1.0f - sourceAlpha);
                if (oa <= 0.0f) { row[px] = qRgba(0, 0, 0, 0); continue; }
                const float dr = static_cast<float>(qRed(destination))   * (1.0f / 255.0f);
                const float dg = static_cast<float>(qGreen(destination)) * (1.0f / 255.0f);
                const float db = static_cast<float>(qBlue(destination))  * (1.0f / 255.0f);
                const float outR = (red   * sourceAlpha + dr * da * (1.0f - sourceAlpha)) / oa;
                const float outG = (green * sourceAlpha + dg * da * (1.0f - sourceAlpha)) / oa;
                const float outB = (blue  * sourceAlpha + db * da * (1.0f - sourceAlpha)) / oa;
                row[px] = qRgba(quantizeChannel(outR), quantizeChannel(outG),
                                quantizeChannel(outB), quantizeChannel(oa));
            } else if (image.format() == QImage::Format_RGBA8888) {
                // Mirrors the ARGB32 branch above, byte-per-channel instead of
                // a packed QRgb. _prepare_cpp_image() (Python side) always
                // hands the C++ bridge an RGBA8888 buffer - including the
                // mask-edit buffer built by edit_layer_alpha_mask() - so this
                // was the actual format on every single dab that reached
                // here, and it used to fall through to the generic
                // pixelColor()/setPixelColor() branch below. That branch pays
                // Qt's per-pixel accessor overhead (conversion + bounds
                // checks + function-call cost) for every pixel of every dab,
                // dozens of times slower than the raw scanline writes the
                // ARGB32 branch already got. Since a plain brush preset with
                // flowAccumulation (useStrokeMask above) is the common case,
                // and mask editing is permanently locked onto this
                // synchronous path (it cannot use the GPU-instanced or async
                // fast paths - neither is mask-aware), this was the direct
                // cause of "Trait ralenti : ~488 ms (cible 8 ms)" while
                // painting on a layer mask.
                uint8_t* destination = image.scanLine(py) + static_cast<size_t>(px) * 4;
                const float da = static_cast<float>(destination[3]) * (1.0f / 255.0f);
                const float oa = sourceAlpha + da * (1.0f - sourceAlpha);
                if (oa <= 0.0f) {
                    destination[0] = 0;
                    destination[1] = 0;
                    destination[2] = 0;
                    destination[3] = 0;
                    continue;
                }
                const float dr = static_cast<float>(destination[0]) * (1.0f / 255.0f);
                const float dg = static_cast<float>(destination[1]) * (1.0f / 255.0f);
                const float db = static_cast<float>(destination[2]) * (1.0f / 255.0f);
                const float outR = (red   * sourceAlpha + dr * da * (1.0f - sourceAlpha)) / oa;
                const float outG = (green * sourceAlpha + dg * da * (1.0f - sourceAlpha)) / oa;
                const float outB = (blue  * sourceAlpha + db * da * (1.0f - sourceAlpha)) / oa;
                destination[0] = quantizeChannel(outR);
                destination[1] = quantizeChannel(outG);
                destination[2] = quantizeChannel(outB);
                destination[3] = quantizeChannel(oa);
            } else {
                QColor destination = image.pixelColor(px, py);
                const float da = static_cast<float>(destination.alphaF());
                const float oa = sourceAlpha + da * (1.0f - sourceAlpha);
                if (oa <= 0.0f) continue;
                QColor result;
                result.setRgbF(
                    (red   * sourceAlpha + destination.redF()   * da * (1.0f - sourceAlpha)) / oa,
                    (green * sourceAlpha + destination.greenF() * da * (1.0f - sourceAlpha)) / oa,
                    (blue  * sourceAlpha + destination.blueF()  * da * (1.0f - sourceAlpha)) / oa,
                    oa);
                image.setPixelColor(px, py, result);
            }
        }
    }

    m_strokeDirtyLeft = m_strokeMaskWidth;
    m_strokeDirtyTop = m_strokeMaskHeight;
    m_strokeDirtyRight = -1;
    m_strokeDirtyBottom = -1;
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

    m_randomState =
        m_settings.randomSeed;

    m_previousColor =
        m_color;

    m_hasPreviousColor =
        false;

    m_wet.begin(
        m_color,
        m_settings
    );

    // Reliquat « plein » : le premier segment pose donc un dab dès son
    // origine, c'est-à-dire exactement sur le point d'appui du stylet.
    m_distanceRemainder = std::numeric_limits<double>::max();

    // Le tampon de trace est (ré)armé au premier dab, quand on connaît la
    // taille de l'image cible et l'opacité effective.
    m_strokeMaskActive = false;
    m_strokeMask.clear();

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
                m_settings.spacing
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

        const float paintAlpha =
            opacity * flow *
            (m_settings.smudgeTool
                ? std::max(0.05f, m_settings.smudge)
                : m_settings.paintMix);

        if (m_settings.eraser)
        {
            /*
             * La gomme ne doit jamais passer par BrushTip::draw : cette
             * fonction ajoute de la couleur. Elle agit uniquement sur
             * l'alpha déjà présent dans le calque.
             */
            const int radius =
                std::max(
                    1,
                    static_cast<int>(
                        finalSize *
                        0.5f
                    )
                );

            const QPointF center =
                basePosition +
                QPointF(
                    scatterX,
                    scatterY
                );

            for (int y = -radius;
                 y <= radius;
                 ++y)
            {
                for (int x = -radius;
                     x <= radius;
                     ++x)
                {
                    const float d =
                        std::sqrt(
                            static_cast<float>(
                                x * x +
                                y * y
                            )
                        );

                    if (d > radius)
                        continue;

                    const int px =
                        static_cast<int>(
                            std::round(
                                center.x()
                            )
                        ) + x;

                    const int py =
                        static_cast<int>(
                            std::round(
                                center.y()
                            )
                        ) + y;

                    if (px < 0 ||
                        py < 0 ||
                        px >= image.width() ||
                        py >= image.height())
                    {
                        continue;
                    }

                    const float erase =
                        paintAlpha *
                        (1.0f -
                         d /
                         std::max(
                             1.0f,
                             static_cast<float>(
                                 radius
                             )
                         ));

                    if (image.format() == QImage::Format_ARGB32)
                    {
                        auto* row = reinterpret_cast<QRgb*>(image.scanLine(py));
                        const QRgb pixel = row[px];
                        const int alpha = qRound(qAlpha(pixel) * (1.0f - clamp01(erase)));
                        row[px] = qRgba(qRed(pixel), qGreen(pixel), qBlue(pixel), alpha);
                    }
                    else
                    {
                        QColor pixel = image.pixelColor(px, py);
                        pixel.setAlphaF(pixel.alphaF() * (1.0f - clamp01(erase)));
                        image.setPixelColor(px, py, pixel);
                    }
                }
            }
        }
        else
        {
            /*
             * BrushTip produit un masque de dab.
             * On le dessine ensuite avec le mode de fusion.
             *
             * Chemin « tampon de trace » : réservé au dépôt de couleur simple.
             * Les modes de fusion, le clone et le smudge lisent la destination
             * pixel par pixel et doivent rester sur le blit direct.
             */
            const bool useStrokeMask =
                m_settings.blendMode == BrushBlendMode::Normal &&
                !m_settings.smudgeTool &&
                !m_settings.wetMix &&
                m_bitmapTip.isNull() &&
                cloneSource == nullptr &&
                m_settings.flowAccumulation;

            QImage dab(
                std::max(
                    4,
                    static_cast<int>(
                        std::ceil(
                            finalSize
                        )
                    ) + 6
                ),
                std::max(
                    4,
                    static_cast<int>(
                        std::ceil(
                            finalSize
                        )
                    ) + 6
                ),
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

            BrushTip::draw(
                dab,
                m_settings,
                QPointF(
                    dab.width() * 0.5,
                    dab.height() * 0.5
                ),
                finalSize,
                // Le tampon applique lui-même flow puis opacity : le masque
                // du dab doit rester à pleine couverture, sinon l'atténuation
                // serait comptée deux fois.
                useStrokeMask ? 1.0f : paintAlpha,
                finalRotation,
                textureScale,
                textureOffsetX,
                textureOffsetY,
                m_settings.textureMirror,
                finalColor,
                m_texture,
                m_bitmapTip,
                subpixelX,
                subpixelY,
                // Plus le stylet est incliné, plus le dab s'aplatit.
                1.0f - m_settings.tiltElongation * tiltMagnitude
            );

            const int offsetX = static_cast<int>(cornerX);
            const int offsetY = static_cast<int>(cornerY);

            if (useStrokeMask) {
                if (!m_strokeMaskActive ||
                    m_strokeMaskWidth != image.width() ||
                    m_strokeMaskHeight != image.height()) {
                    beginStrokeMask(image.width(), image.height(), opacity, finalColor);
                } else {
                    // La couleur peut varier en cours de trait (jitter, dirty
                    // color) : on vide le tampon avant d'en changer.
                    if (finalColor != m_strokeColor) {
                        flushStrokeMask(image);
                        beginStrokeMask(image.width(), image.height(), opacity, finalColor);
                    } else {
                        m_strokeOpacity = clamp01(opacity);
                    }
                }
                accumulateStrokeMask(dab, offsetX, offsetY, flow * m_settings.paintMix);
                flushStrokeMask(image);
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
    m_distanceRemainder = 0.0;
    m_strokeMaskActive = false;
    m_strokeMask.clear();
    m_strokeMask.shrink_to_fit();
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
