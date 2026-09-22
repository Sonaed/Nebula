#include "brush_color.h"
#include "brush_random.h"

#include <algorithm>
#include <cmath>

float BrushColor::clamp01(float value)
{
    return std::clamp(
        value,
        0.0f,
        1.0f
    );
}

float BrushColor::randomRange(
    unsigned int& state,
    float minimum,
    float maximum
)
{
    return BrushRandom::range(
        state,
        minimum,
        maximum
    );
}

QColor BrushColor::applyJitter(
    const BrushSettings& settings,
    const QColor& baseColor,
    QColor& previousColor,
    bool& hasPreviousColor,
    unsigned int& randomState
)
{
    if (!settings.dirtyColor &&
        settings.hueJitter <= 0.0f &&
        settings.saturationJitter <= 0.0f &&
        settings.brightnessJitter <= 0.0f)
    {
        return baseColor;
    }

    int hue =
        baseColor.hsvHue();

    int saturation =
        baseColor.hsvSaturation();

    int value =
        baseColor.value();

    if (hue < 0)
        hue = 0;

    if (settings.hueJitter > 0.0f)
    {
        hue += static_cast<int>(
            randomRange(
                randomState,
                -settings.hueJitter,
                settings.hueJitter
            )
        );

        while (hue < 0)
            hue += 360;

        while (hue >= 360)
            hue -= 360;
    }

    if (settings.saturationJitter > 0.0f)
    {
        saturation += static_cast<int>(
            randomRange(
                randomState,
                -settings.saturationJitter,
                settings.saturationJitter
            ) * 255.0f
        );

        saturation =
            std::clamp(
                saturation,
                0,
                255
            );
    }

    if (settings.brightnessJitter > 0.0f)
    {
        value += static_cast<int>(
            randomRange(
                randomState,
                -settings.brightnessJitter,
                settings.brightnessJitter
            ) * 255.0f
        );

        value =
            std::clamp(
                value,
                0,
                255
            );
    }

    QColor result =
        QColor::fromHsv(
            hue,
            saturation,
            value,
            baseColor.alpha()
        );

    if (settings.dirtyColor &&
        hasPreviousColor)
    {
        constexpr float dirtyAmount =
            0.18f;

        result.setRed(
            static_cast<int>(
                result.red() *
                    (1.0f - dirtyAmount) +
                previousColor.red() *
                    dirtyAmount
            )
        );

        result.setGreen(
            static_cast<int>(
                result.green() *
                    (1.0f - dirtyAmount) +
                previousColor.green() *
                    dirtyAmount
            )
        );

        result.setBlue(
            static_cast<int>(
                result.blue() *
                    (1.0f - dirtyAmount) +
                previousColor.blue() *
                    dirtyAmount
            )
        );
    }

    previousColor = result;
    hasPreviousColor = true;

    return result;
}

QColor BrushColor::applyGradient(
    const BrushSettings& settings,
    const QColor& baseColor,
    float strokeT
)
{
    strokeT =
        clamp01(
            strokeT
        );

    if (!settings.useStrokeGradient ||
        settings.gradientAmount <= 0.0f)
    {
        return baseColor;
    }

    const QColor target =
        settings.gradientColor;

    float t =
        strokeT;

    if (settings.useRadialGradient)
    {
        const float centered =
            std::abs(
                strokeT * 2.0f -
                1.0f
            );

        t =
            1.0f -
            centered;
    }

    QColor gradientColor(
        static_cast<int>(
            baseColor.red() *
                (1.0f - t) +
            target.red() *
                t
        ),

        static_cast<int>(
            baseColor.green() *
                (1.0f - t) +
            target.green() *
                t
        ),

        static_cast<int>(
            baseColor.blue() *
                (1.0f - t) +
            target.blue() *
                t
        ),

        baseColor.alpha()
    );

    const float amount =
        settings.gradientAmount;

    return QColor(
        static_cast<int>(
            baseColor.red() *
                (1.0f - amount) +
            gradientColor.red() *
                amount
        ),

        static_cast<int>(
            baseColor.green() *
                (1.0f - amount) +
            gradientColor.green() *
                amount
        ),

        static_cast<int>(
            baseColor.blue() *
                (1.0f - amount) +
            gradientColor.blue() *
                amount
        ),

        baseColor.alpha()
    );
}

QColor BrushColor::evaluate(
    const BrushSettings& settings,
    const QColor& baseColor,
    QColor& previousColor,
    bool& hasPreviousColor,
    float strokeT,
    float pressure,
    unsigned int& randomState
)
{
    Q_UNUSED(pressure);

    QColor result =
        applyJitter(
            settings,
            baseColor,
            previousColor,
            hasPreviousColor,
            randomState
        );

    if (settings.useLinearGradient ||
        settings.useRadialGradient)
    {
        result =
            applyGradient(
                settings,
                result,
                strokeT
            );
    }

    return result;
}
