#include "brush_paint.h"

#include <algorithm>

float BrushPaint::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

QColor BrushPaint::mixColors(
    const QColor& a,
    const QColor& b,
    float amount
)
{
    amount =
        clamp01(amount);

    return QColor::fromRgbF(
        a.redF() *
            (1.0f - amount) +
        b.redF() *
            amount,

        a.greenF() *
            (1.0f - amount) +
        b.greenF() *
            amount,

        a.blueF() *
            (1.0f - amount) +
        b.blueF() *
            amount,

        1.0f
    );
}

QColor BrushPaint::blendPixel(
    const QColor& destination,
    const QColor& source,
    BrushBlendMode mode,
    float alpha
)
{
    alpha =
        clamp01(alpha);

    if (alpha <= 0.0f)
        return destination;

    const float dr =
        destination.redF();

    const float dg =
        destination.greenF();

    const float db =
        destination.blueF();

    const float sr =
        source.redF();

    const float sg =
        source.greenF();

    const float sb =
        source.blueF();

    float rr = sr;
    float rg = sg;
    float rb = sb;

    switch (mode)
    {
    case BrushBlendMode::Normal:
        break;

    case BrushBlendMode::Multiply:
        rr = dr * sr;
        rg = dg * sg;
        rb = db * sb;
        break;

    case BrushBlendMode::Screen:
        rr =
            1.0f -
            (1.0f - dr) *
            (1.0f - sr);

        rg =
            1.0f -
            (1.0f - dg) *
            (1.0f - sg);

        rb =
            1.0f -
            (1.0f - db) *
            (1.0f - sb);
        break;

    case BrushBlendMode::Overlay:
        rr =
            dr < 0.5f
                ? 2.0f * dr * sr
                : 1.0f -
                  2.0f *
                  (1.0f - dr) *
                  (1.0f - sr);

        rg =
            dg < 0.5f
                ? 2.0f * dg * sg
                : 1.0f -
                  2.0f *
                  (1.0f - dg) *
                  (1.0f - sg);

        rb =
            db < 0.5f
                ? 2.0f * db * sb
                : 1.0f -
                  2.0f *
                  (1.0f - db) *
                  (1.0f - sb);
        break;

    case BrushBlendMode::Darken:
        rr = std::min(dr, sr);
        rg = std::min(dg, sg);
        rb = std::min(db, sb);
        break;

    case BrushBlendMode::Lighten:
        rr = std::max(dr, sr);
        rg = std::max(dg, sg);
        rb = std::max(db, sb);
        break;
    }

    /*
     * Composition alpha source-over en couleurs non prémultipliées.
     *
     * Un pixel transparent peut contenir un RGB noir. Il ne doit jamais
     * assombrir le bord d'un dab : sa contribution est pondérée par son
     * alpha avant la normalisation de la couleur de sortie.
     */
    const float sourceAlpha = alpha;
    const float destinationAlpha =
        clamp01(destination.alphaF());

    const float outputAlpha =
        sourceAlpha +
        destinationAlpha *
        (1.0f - sourceAlpha);

    if (outputAlpha <= 0.0f)
        return QColor(0, 0, 0, 0);

    const auto composeChannel = [=](
        float destinationChannel,
        float sourceChannel,
        float blendedChannel
    )
    {
        const float premultiplied =
            sourceAlpha *
                (1.0f - destinationAlpha) *
                sourceChannel +
            sourceAlpha *
                destinationAlpha *
                blendedChannel +
            (1.0f - sourceAlpha) *
                destinationAlpha *
                destinationChannel;

        return clamp01(
            premultiplied /
            outputAlpha
        );
    };

    return QColor::fromRgbF(
        composeChannel(dr, sr, rr),
        composeChannel(dg, sg, rg),
        composeChannel(db, sb, rb),
        outputAlpha
    );
}
