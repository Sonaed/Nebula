#include "brush_engine.h"

#include <QColor>
#include <QImage>
#include <QPointF>
#include <QDebug>

#include <cmath>

static int failures = 0;

static void check(
    bool condition,
    const char* name
)
{
    if (condition)
    {
        qDebug() << "[PASS]" << name;
    }
    else
    {
        qCritical() << "[FAIL]" << name;
        ++failures;
    }
}

static bool approximately(
    float a,
    float b,
    float epsilon = 0.0001f
)
{
    return std::abs(a - b) <= epsilon;
}

static QImage makeTexture()
{
    QImage texture(
        8,
        8,
        QImage::Format_Grayscale8
    );

    for (int y = 0; y < texture.height(); ++y)
    {
        for (int x = 0; x < texture.width(); ++x)
        {
            const int value =
                ((x + y) % 2 == 0)
                    ? 255
                    : 0;

            texture.setPixelColor(
                x,
                y,
                QColor(
                    value,
                    value,
                    value
                )
            );
        }
    }

    return texture;
}

static void testSettings()
{
    BrushEngine engine;

    BrushSettings settings;

    settings.size = -50.0f;
    settings.opacity = 2.0f;
    settings.flow = -1.0f;
    settings.hardness = 4.0f;
    settings.spacing = 0.0f;

    settings.roundness = 5.0f;
    settings.scatter = -1.0f;

    settings.textureScale = 0.0f;
    settings.textureContrast = -5.0f;

    settings.wetness = 4.0f;
    settings.pickup = -1.0f;
    settings.paintPersistence = 3.0f;

    engine.setSettings(settings);

    const BrushSettings& result =
        engine.settings();

    check(
        result.size > 0.0f,
        "Size clamp"
    );

    check(
        result.opacity == 1.0f,
        "Opacity clamp"
    );

    check(
        result.flow == 0.0f,
        "Flow clamp"
    );

    check(
        result.hardness == 1.0f,
        "Hardness clamp"
    );

    check(
        result.spacing > 0.0f,
        "Spacing clamp"
    );

    check(
        result.roundness == 1.0f,
        "Roundness clamp"
    );

    check(
        result.scatter == 0.0f,
        "Scatter clamp"
    );

    check(
        result.textureScale > 0.0f,
        "Texture scale clamp"
    );

    check(
        result.textureContrast == 0.0f,
        "Texture contrast clamp"
    );

    check(
        result.wetness == 1.0f,
        "Wetness clamp"
    );

    check(
        result.pickup == 0.0f,
        "Pickup clamp"
    );

    check(
        result.paintPersistence == 1.0f,
        "Paint persistence clamp"
    );
}

static void testPressure()
{
    BrushEngine engine;

    BrushSettings settings;

    settings.size = 100.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;

    settings.pressureSize = true;
    settings.pressureOpacity = true;
    settings.pressureFlow = true;

    settings.minimumSize = 0.20f;
    settings.minimumOpacity = 0.10f;
    settings.minimumFlow = 0.15f;

    engine.setSettings(settings);

    check(
        approximately(
            engine.evaluateSize(0.0f),
            20.0f
        ),
        "Pressure -> minimum size"
    );

    check(
        approximately(
            engine.evaluateSize(1.0f),
            100.0f
        ),
        "Pressure -> maximum size"
    );

    check(
        approximately(
            engine.evaluateSize(0.5f),
            60.0f
        ),
        "Pressure -> interpolated size"
    );

    check(
        approximately(
            engine.evaluateOpacity(0.0f),
            0.10f
        ),
        "Pressure -> minimum opacity"
    );

    check(
        approximately(
            engine.evaluateOpacity(1.0f),
            1.0f
        ),
        "Pressure -> maximum opacity"
    );

    check(
        approximately(
            engine.evaluateFlow(0.0f),
            0.15f
        ),
        "Pressure -> minimum flow"
    );

    check(
        approximately(
            engine.evaluateFlow(1.0f),
            1.0f
        ),
        "Pressure -> maximum flow"
    );
}

static void testTexture()
{
    BrushEngine engine;

    const QImage texture =
        makeTexture();

    engine.setTexture(texture);

    check(
        engine.hasTexture(),
        "Texture registration"
    );

    engine.clearTexture();

    check(
        !engine.hasTexture(),
        "Texture clear"
    );

    engine.setTexture(texture);

    BrushSettings settings =
        engine.settings();

    settings.textureStrength = 1.0f;
    settings.textureScale = 1.0f;
    settings.textureContrast = 1.0f;
    settings.textureBrightness = 0.0f;

    engine.setSettings(settings);

    QImage image(
        128,
        128,
        QImage::Format_RGBA8888
    );

    image.fill(Qt::white);

    engine.setColor(
        QColor(0, 0, 0)
    );

    const BrushInput input{
        QPointF(64.0, 64.0),
        1.0f
    };

    engine.beginStroke(input);
    engine.drawSegment(
        image,
        input,
        input
    );
    engine.endStroke();

    check(
        image.pixelColor(
            64,
            64
        ).alpha() > 0,
        "Texture affects dab"
    );
}

static void testRendering()
{
    BrushEngine engine;

    BrushSettings settings;

    settings.size = 40.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    settings.hardness = 1.0f;
    settings.spacing = 0.1f;

    settings.pressureSize = false;
    settings.pressureOpacity = false;
    settings.pressureFlow = false;

    engine.setSettings(settings);

    engine.setColor(
        QColor(0, 0, 0)
    );

    QImage image(
        256,
        256,
        QImage::Format_RGBA8888
    );

    image.fill(Qt::white);

    const BrushInput start{
        QPointF(32.0, 128.0),
        1.0f
    };

    const BrushInput end{
        QPointF(224.0, 128.0),
        1.0f
    };

    engine.beginStroke(start);
    engine.drawSegment(
        image,
        start,
        end
    );
    engine.endStroke();

    const QColor center =
        image.pixelColor(
            128,
            128
        );

    check(
        center.red() < 255 ||
        center.green() < 255 ||
        center.blue() < 255,
        "Stroke modifies canvas"
    );

    check(
        image.pixelColor(
            5,
            5
        ) == QColor(
            255,
            255,
            255,
            255
        ),
        "Outside stroke remains unchanged"
    );
}

static void testTransparentEdgeHasNoDarkHalo()
{
    BrushEngine engine;
    BrushSettings settings;
    settings.size = 40.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    settings.hardness = 0.0f;
    settings.spacing = 0.1f;
    settings.pressureSize = false;
    engine.setSettings(settings);
    engine.setColor(QColor(230, 45, 30, 255));

    QImage image(96, 96, QImage::Format_RGBA8888);
    image.fill(Qt::transparent);

    const BrushInput point{QPointF(48.0, 48.0), 1.0f};
    engine.beginStroke(point);
    engine.drawSegment(image, point, point);
    engine.endStroke();

    bool foundSoftEdge = false;
    for (int y = 0; y < image.height(); ++y)
    {
        for (int x = 0; x < image.width(); ++x)
        {
            const QColor pixel = image.pixelColor(x, y);
            if (pixel.alpha() > 10 && pixel.alpha() < 245)
            {
                foundSoftEdge = true;
                check(
                    pixel.red() > 210 &&
                    pixel.green() < 65 &&
                    pixel.blue() < 50,
                    "Transparent soft edge keeps brush RGB without dark halo"
                );
                return;
            }
        }
    }

    check(foundSoftEdge, "Transparent brush produces a soft edge");
}

static void testEraserNeverPaintsTrailingDabs()
{
    BrushEngine engine;
    BrushSettings settings;
    settings.size = 32.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    settings.spacing = 0.1f;
    settings.eraser = true;
    settings.pressureSize = false;
    engine.setSettings(settings);

    const BrushInput start{QPointF(20.0, 32.0), 1.0f};
    const BrushInput end{QPointF(108.0, 32.0), 1.0f};

    QImage transparent(128, 64, QImage::Format_RGBA8888);
    transparent.fill(Qt::transparent);
    engine.beginStroke(start);
    engine.drawSegment(transparent, start, end);
    engine.endStroke();

    bool addedPixel = false;
    for (int y = 0; y < transparent.height() && !addedPixel; ++y)
        for (int x = 0; x < transparent.width(); ++x)
            if (transparent.pixelColor(x, y).alpha() != 0)
            {
                addedPixel = true;
                break;
            }

    check(!addedPixel, "Eraser never paints dabs on transparency");

    QImage opaque(128, 64, QImage::Format_RGBA8888);
    opaque.fill(QColor(40, 120, 220, 255));
    engine.beginStroke(start);
    engine.drawSegment(opaque, start, end);
    engine.endStroke();

    check(
        opaque.pixelColor(64, 32).alpha() < 255,
        "Eraser reduces existing alpha"
    );
}

static void testBlendModes()
{
    BrushEngine engine;

    BrushSettings settings;

    settings.size = 40.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    settings.hardness = 1.0f;
    settings.spacing = 0.1f;

    settings.pressureSize = false;
    settings.pressureOpacity = false;
    settings.pressureFlow = false;

    settings.paintMix = 1.0f;

    /*
     * Gris moyen + couleur clairement différente.
     * Cela évite qu'un mode particulier tombe
     * accidentellement sur une valeur identique.
     */
    const QColor destination(
        120,
        140,
        160
    );

    const QColor source(
        220,
        70,
        40
    );

    engine.setColor(source);

    const BrushBlendMode modes[] = {
        BrushBlendMode::Normal,
        BrushBlendMode::Multiply,
        BrushBlendMode::Screen,
        BrushBlendMode::Overlay,
        BrushBlendMode::Darken,
        BrushBlendMode::Lighten
    };

    for (BrushBlendMode mode : modes)
    {
        settings.blendMode = mode;

        engine.setSettings(settings);

        QImage image(
            128,
            128,
            QImage::Format_RGBA8888
        );

        image.fill(destination);

        const BrushInput input{
            QPointF(
                64.0,
                64.0
            ),
            1.0f
        };

        const QColor before =
            image.pixelColor(
                64,
                64
            );

        engine.beginStroke(input);

        engine.drawSegment(
            image,
            input,
            input
        );

        engine.endStroke();

        const QColor after =
            image.pixelColor(
                64,
                64
            );

        check(
            after != before,
            "Blend mode modifies destination"
        );
    }
}

static void testWet()
{
    BrushEngine engine;

    BrushSettings settings;

    /*
     * Un seul dab au centre.
     *
     * La toile est bleue et la peinture fraîche
     * est rouge. Avec pickup + smudge élevés,
     * le résultat doit être une couleur intermédiaire.
     */
    settings.size = 50.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    settings.hardness = 1.0f;
    settings.spacing = 0.1f;

    settings.wetMix = true;
    settings.sampleCanvas = true;

    settings.wetness = 1.0f;
    settings.pickup = 1.0f;
    settings.dilution = 0.0f;
    settings.smudge = 0.0f;
    settings.paintPersistence = 1.0f;
    settings.colorCarry = 1.0f;

    settings.pressureSize = false;
    settings.pressureOpacity = false;
    settings.pressureFlow = false;

    settings.blendMode =
        BrushBlendMode::Normal;

    settings.paintMix = 1.0f;

    engine.setSettings(settings);

    const QColor freshColor(
        255,
        0,
        0
    );

    const QColor canvasColor(
        0,
        0,
        255
    );

    engine.setColor(
        freshColor
    );

    QImage image(
        256,
        256,
        QImage::Format_RGBA8888
    );

    image.fill(canvasColor);

    const BrushInput input{
        QPointF(
            128.0,
            128.0
        ),
        0.5f
    };

    engine.beginStroke(input);

    engine.drawSegment(
        image,
        input,
        input
    );

    engine.endStroke();

    const QColor result =
        image.pixelColor(
            128,
            128
        );

    qDebug()
        << "Wet result :"
        << result
        << "RGB ="
        << result.red()
        << result.green()
        << result.blue();

    /*
     * Le résultat ne doit être ni le rouge pur,
     * ni le bleu pur.
     *
     * On veut vérifier qu'au moins deux canaux
     * provenant des deux peintures sont présents.
     */
    const bool hasRed =
        result.red() > 10;

    const bool hasBlue =
        result.blue() > 10;

    const bool notPureFresh =
        result != freshColor;

    const bool notPureCanvas =
        result != canvasColor;

    check(
        hasRed &&
        hasBlue &&
        notPureFresh &&
        notPureCanvas,
        "Wet mixing creates intermediate color"
    );
}

static void testDeterminism()
{
    BrushSettings settings;

    settings.size = 50.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;

    settings.scatter = 0.5f;
    settings.sizeJitter = 0.5f;
    settings.rotationJitter = 45.0f;

    settings.randomSeed = 12345;

    BrushInput start{
        QPointF(
            20.0,
            64.0
        ),
        1.0f
    };

    BrushInput end{
        QPointF(
            236.0,
            64.0
        ),
        1.0f
    };

    QImage imageA(
        256,
        128,
        QImage::Format_RGBA8888
    );

    QImage imageB(
        256,
        128,
        QImage::Format_RGBA8888
    );

    imageA.fill(Qt::white);
    imageB.fill(Qt::white);

    BrushEngine engineA;
    BrushEngine engineB;

    engineA.setSettings(settings);
    engineB.setSettings(settings);

    engineA.setColor(
        QColor(
            20,
            20,
            20
        )
    );

    engineB.setColor(
        QColor(
            20,
            20,
            20
        )
    );

    engineA.beginStroke(start);
    engineA.drawSegment(
        imageA,
        start,
        end
    );
    engineA.endStroke();

    engineB.beginStroke(start);
    engineB.drawSegment(
        imageB,
        start,
        end
    );
    engineB.endStroke();

    check(
        imageA == imageB,
        "Random seed produces deterministic result"
    );
}

int main()
{
    qDebug()
        << "================================";

    qDebug()
        << "CreativeCore Unit Tests";

    qDebug()
        << "================================";

    testSettings();
    testPressure();
    testTexture();
    testRendering();
    testTransparentEdgeHasNoDarkHalo();
    testEraserNeverPaintsTrailingDabs();
    testBlendModes();
    testWet();
    testDeterminism();

    qDebug()
        << "================================";

    if (failures == 0)
    {
        qDebug()
            << "ALL TESTS PASSED";

        return 0;
    }

    qCritical()
        << failures
        << "TEST(S) FAILED";

    return 1;
}
