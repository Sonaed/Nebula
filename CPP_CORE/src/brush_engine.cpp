#include "brush_engine.h"
#include "simd_runtime.h"

#include <algorithm>
#include <cmath>

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
    const float velocityFactor = clamp01(velocity);
    const float velocityScale = (1.0f - m_settings.velocityFlow) + velocityFactor * m_settings.velocityFlow;
    return velocityScale * applyPressure(
        pressure,
        m_settings.pressureFlow,
        m_settings.minimumFlow,
        m_settings.flow
    );
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

    const int steps =
        std::max(
            1,
            static_cast<int>(
                std::ceil(
                    distance /
                    spacingDistance
                )
            )
        );

    for (int i = 0;
         i <= steps;
         ++i)
    {
        const float t =
            static_cast<float>(i) /
            static_cast<float>(steps);

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

        const float finalRotation =
            m_settings.angle +
            rotationVariation;

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
            const float wetMixAmount =
                clamp01(
                    m_settings.wetness *
                    m_settings.colorCarry
                );

            finalColor =
                BrushPaint::mixColors(
                    freshColor,
                    m_wet.color(),
                    wetMixAmount
                );
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
             */
            QImage dab(
                std::max(
                    4,
                    static_cast<int>(
                        std::ceil(
                            finalSize
                        )
                    ) + 4
                ),
                std::max(
                    4,
                    static_cast<int>(
                        std::ceil(
                            finalSize
                        )
                    ) + 4
                ),
                QImage::Format_ARGB32
            );

            dab.fill(
                Qt::transparent
            );

            BrushTip::draw(
                dab,
                m_settings,
                QPointF(
                    dab.width() * 0.5,
                    dab.height() * 0.5
                ),
                finalSize,
                paintAlpha,
                finalRotation,
                textureScale,
                textureOffsetX,
                textureOffsetY,
                m_settings.textureMirror,
                finalColor,
                m_texture,
                m_bitmapTip
            );

            const int offsetX =
                static_cast<int>(
                    std::round(
                        basePosition.x() +
                        scatterX -
                        dab.width() *
                            0.5
                    )
                );

            const int offsetY =
                static_cast<int>(
                    std::round(
                        basePosition.y() +
                        scatterY -
                        dab.height() *
                            0.5
                    )
                );

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
