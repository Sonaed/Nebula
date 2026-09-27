#include "brush_tip.h"
#include "brush_texture.h"

#include <algorithm>
#include <cmath>

float BrushTip::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

void BrushTip::draw(
    QImage& image,
    const BrushSettings& settings,
    const QPointF& position,
    float diameter,
    float opacity,
    float rotation,
    float textureScale,
    float textureOffsetX,
    float textureOffsetY,
    bool mirrorTexture,
    const QColor& color,
    const QImage& texture,
    const QImage& bitmapTip,
    float subpixelX,
    float subpixelY,
    float roundnessScale
)
{
    if (diameter <= 0.0f ||
        opacity <= 0.0f)
    {
        return;
    }

    const int padding = 2;

    const int size =
        std::max(
            4,
            static_cast<int>(
                std::ceil(diameter)
            ) +
            padding * 2
        );

    const float radius =
        diameter * 0.5f;

    const float center =
        static_cast<float>(size) *
        0.5f;

    // Le profil est évalué autour du centre RÉEL du dab, pas du centre du
    // bitmap : c'est ce qui donne le positionnement sous-pixel.
    const float centerX = center + subpixelX;
    const float centerY = center + subpixelY;

    const float hardness =
        clamp01(
            settings.hardness
        );

    const float roundness =
        std::max(
            0.01f,
            settings.roundness *
            std::clamp(roundnessScale, 0.05f, 1.0f)
        );

    const float radians =
        -rotation *
        3.14159265358979323846f /
        180.0f;

    const float cosA =
        std::cos(radians);

    const float sinA =
        std::sin(radians);

    for (int y = 0; y < size; ++y)
    {
        const int pixelY = y + static_cast<int>(position.y() - center);
        if (pixelY < 0 || pixelY >= image.height())
            continue;
        auto* argbRow = image.format() == QImage::Format_ARGB32
            ? reinterpret_cast<QRgb*>(image.scanLine(pixelY)) : nullptr;

        for (int x = 0; x < size; ++x)
        {
            // Échantillonner au CENTRE du pixel (x + 0,5) : échantillonner son
            // coin décalait chaque dab d'un demi-pixel vers le bas-droite.
            const float localX =
                static_cast<float>(x) + 0.5f -
                centerX;

            const float localY =
                static_cast<float>(y) + 0.5f -
                centerY;

            const float rotatedX =
                localX * cosA -
                localY * sinA;

            const float rotatedY =
                localX * sinA +
                localY * cosA;

            const float normalizedX =
                rotatedX /
                radius;

            const float normalizedY =
                rotatedY /
                (radius * roundness);

            const float distance =
                std::sqrt(
                    normalizedX *
                        normalizedX +
                    normalizedY *
                        normalizedY
                );

            // Couverture analytique du contour : un pixel à cheval sur le
            // bord reçoit un alpha partiel.  Sans cela, un dab dur est un
            // disque en escalier, quelle que soit la valeur de hardness.
            //
            // La largeur du bord est mesurée en vrais pixels via le gradient
            // du champ de distance normalisé : sur une pointe aplatie
            // (roundness < 1), utiliser le grand rayon rendait le bord du
            // petit axe plus fin qu'un pixel, donc crénelé. Pour une pointe
            // ronde, le résultat est identique à l'ancienne formule.
            const float gradX = normalizedX / radius;
            const float gradY = normalizedY / (radius * roundness);
            const float gradient = std::sqrt(gradX * gradX + gradY * gradY) /
                                   std::max(distance, 1.0e-4f);
            const float edgeCoverage = distance < 1.0e-4f
                ? 1.0f
                : clamp01((1.0f - distance) / std::max(gradient, 1.0e-6f) + 0.5f);

            if (edgeCoverage <= 0.0f)
                continue;

            float brushAlpha;

            if (distance <= hardness)
            {
                brushAlpha = 1.0f;
            }
            else
            {
                const float range =
                    std::max(
                        0.0001f,
                        1.0f -
                        hardness
                    );

                float falloff =
                    1.0f -
                    (distance -
                     hardness) /
                    range;

                falloff = clamp01(falloff);

                // Smoothstep : la rampe linéaire avait une dérivée
                // discontinue en distance == hardness, d'où un anneau visible
                // (bande de Mach) sur les dégradés doux.
                brushAlpha =
                    falloff * falloff *
                    (3.0f - 2.0f * falloff);
            }

            brushAlpha *= edgeCoverage;

            // Pixel-art brushes need a true binary edge.  Keep the brush
            // opacity intact, but remove the fractional coverage that would
            // otherwise create anti-aliased contour pixels.
            if (!settings.antialiasing)
            {
                brushAlpha = brushAlpha >= 0.5f ? 1.0f : 0.0f;
                if (brushAlpha == 0.0f)
                    continue;
            }

            const float u =
                (normalizedX * 0.5f +
                 0.5f) *
                textureScale +
                textureOffsetX;

            const float v =
                (normalizedY * 0.5f +
                 0.5f) *
                textureScale +
                textureOffsetY;

            const float textureValue =
                BrushTexture::sample(
                    texture,
                    settings,
                    u,
                    v,
                    mirrorTexture
                );

            const float textureMix =
                1.0f -
                settings.textureStrength;

            const float finalTexture =
                textureMix +
                textureValue *
                settings.textureStrength;

            float finalAlpha =
                brushAlpha *
                opacity;

            // The bitmap tip (pencil/charcoal/chalk/bristle/watercolor/
            // speckle - see BrushPresetManager._render_builtin_bitmap_tip)
            // is a SHAPE MASK: every built-in one is rendered pure grayscale
            // (R=G=B=A=value) precisely because its RGB channels were never
            // meant to be looked at, only its alpha channel, to modulate
            // coverage exactly like the analytic brushAlpha/edgeCoverage
            // terms above. dabColor must stay the user's selected `color`
            // for every pixel, tip or no tip - previously this branch
            // clobbered it with QColor::fromRgba(tipPixel), i.e. the tip
            // texture's own grayscale value, so every bitmap-tip preset
            // (Pencil HB/2B, Col Erase, Charcoal, Chalk, Conte, Dry Brush,
            // Oil Flat, Watercolor, Spray, Stipple) painted in gray/silver
            // regardless of the color actually picked. Oil Round has no
            // bitmap tip and was never affected, which is why it looked
            // fine by comparison.
            QColor dabColor = color;
            if (!bitmapTip.isNull())
            {
                const float bitmapU = normalizedX * 0.5f + 0.5f;
                const float bitmapV = normalizedY * 0.5f + 0.5f;
                float tipAlpha;
                const QImage::Format tipFormat = bitmapTip.format();
                if (tipFormat == QImage::Format_ARGB32 ||
                    tipFormat == QImage::Format_ARGB32_Premultiplied)
                {
                    // Interpolation bilinéaire de la pointe : l'échantillonnage
                    // au plus proche voisin crénelait tous les bords dès que la
                    // taille du pinceau ne tombait pas pile sur celle du bitmap.
                    const int w = bitmapTip.width();
                    const int h = bitmapTip.height();
                    const float fx = std::clamp(bitmapU * w - 0.5f, 0.0f, static_cast<float>(w - 1));
                    const float fy = std::clamp(bitmapV * h - 0.5f, 0.0f, static_cast<float>(h - 1));
                    const int x0 = static_cast<int>(fx);
                    const int y0 = static_cast<int>(fy);
                    const int x1 = std::min(x0 + 1, w - 1);
                    const int y1 = std::min(y0 + 1, h - 1);
                    const float tx = fx - static_cast<float>(x0);
                    const float ty = fy - static_cast<float>(y0);
                    const auto* row0 = reinterpret_cast<const QRgb*>(bitmapTip.constScanLine(y0));
                    const auto* row1 = reinterpret_cast<const QRgb*>(bitmapTip.constScanLine(y1));
                    const float a00 = static_cast<float>(qAlpha(row0[x0]));
                    const float a10 = static_cast<float>(qAlpha(row0[x1]));
                    const float a01 = static_cast<float>(qAlpha(row1[x0]));
                    const float a11 = static_cast<float>(qAlpha(row1[x1]));
                    const float top = a00 + (a10 - a00) * tx;
                    const float bottom = a01 + (a11 - a01) * tx;
                    tipAlpha = (top + (bottom - top) * ty) / 255.0f;
                }
                else
                {
                    const int tipX = std::clamp(
                        static_cast<int>(bitmapU * bitmapTip.width()), 0, bitmapTip.width() - 1);
                    const int tipY = std::clamp(
                        static_cast<int>(bitmapV * bitmapTip.height()), 0, bitmapTip.height() - 1);
                    tipAlpha = qAlpha(bitmapTip.pixel(tipX, tipY)) / 255.0f;
                }
                finalAlpha *= settings.antialiasing
                    ? tipAlpha
                    : (tipAlpha >= 0.5f ? 1.0f : 0.0f);
                // dabColor intentionally left as `color`: only the tip's
                // alpha (shape) is used, never its RGB (which is just the
                // grayscale render of that same shape, not paint color).
            }

            if (settings.textureAffectOpacity)
            {
                finalAlpha *=
                    finalTexture;
            }

            finalAlpha =
                clamp01(
                    finalAlpha
                );

            const int pixelX =
                x +
                static_cast<int>(
                    position.x() -
                    center
                );

            if (pixelX < 0 || pixelX >= image.width())
            {
                continue;
            }
            const int alpha = qRound(clamp01(finalAlpha) * 255.0f);
            if (argbRow)
                argbRow[pixelX] = qRgba(dabColor.red(), dabColor.green(), dabColor.blue(), alpha);
            else {
                QColor pixel = dabColor;
                pixel.setAlpha(alpha);
                image.setPixelColor(pixelX, pixelY, pixel);
            }
        }
    }
}
