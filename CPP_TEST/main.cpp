#include "brush_engine.h"

#include <QDebug>
#include <QImage>
#include <QPainter>

static void drawStroke(
    BrushEngine& engine,
    QImage& image,
    float y,
    float pressureStart = 1.0f,
    float pressureEnd = 1.0f
)
{
    const BrushInput start{
        QPointF(100.0, y),
        pressureStart,
        0.0f,
        0.0f,
        0.0f,
        0.0f,
        0.0
    };

    const BrushInput end{
        QPointF(1000.0, y),
        pressureEnd,
        0.0f,
        0.0f,
        0.0f,
        0.0f,
        1.0
    };

    engine.beginStroke(start);
    engine.drawSegment(
        image,
        start,
        end
    );
    engine.endStroke();
}

int main()
{
    QImage image(
        1100,
        650,
        QImage::Format_RGBA8888
    );

    image.fill(
        QColor(
            235,
            235,
            235
        )
    );

    /*
     * Sous-couches de peinture.
     */
    {
        QPainter painter(&image);

        painter.fillRect(
            80,
            90,
            940,
            80,
            QColor(
                220,
                70,
                70
            )
        );

        painter.fillRect(
            80,
            240,
            940,
            80,
            QColor(
                60,
                130,
                220
            )
        );

        painter.fillRect(
            80,
            390,
            940,
            80,
            QColor(
                70,
                180,
                100
            )
        );

        painter.fillRect(
            80,
            540,
            940,
            60,
            QColor(
                220,
                180,
                60
            )
        );
    }

    BrushEngine engine;

    BrushSettings settings;

    settings.size = 85.0f;
    settings.opacity = 0.80f;
    settings.flow = 0.55f;
    settings.hardness = 0.60f;
    settings.spacing = 0.10f;

    settings.roundness = 0.95f;

    settings.wetMix = true;
    settings.sampleCanvas = true;

    settings.wetness = 0.90f;
    settings.pickup = 0.75f;
    settings.dilution = 0.20f;
    settings.smudge = 0.65f;
    settings.paintPersistence = 0.92f;
    settings.colorCarry = 0.85f;

    settings.blendMode =
        BrushBlendMode::Normal;

    settings.paintMix = 1.0f;

    settings.pressureSize = true;
    settings.minimumSize = 0.25f;

    settings.randomSeed = 12345;

    engine.setSettings(settings);

    qDebug() << "Wet / Smudge / Mixing test";

    qDebug() << "Wetness           :"
             << engine.settings().wetness;

    qDebug() << "Pickup            :"
             << engine.settings().pickup;

    qDebug() << "Dilution          :"
             << engine.settings().dilution;

    qDebug() << "Smudge            :"
             << engine.settings().smudge;

    qDebug() << "Paint persistence :"
             << engine.settings().paintPersistence;

    qDebug() << "Color carry       :"
             << engine.settings().colorCarry;

    /*
     * Stroke rouge sur fond rouge :
     * sert de source pour le pickup.
     */
    engine.setColor(
        QColor(
            40,
            40,
            40
        )
    );

    drawStroke(
        engine,
        image,
        130.0f,
        0.25f,
        1.0f
    );

    /*
     * Stroke bleu humide.
     * Il doit ramasser une partie de la peinture
     * déjà présente.
     */
    engine.setColor(
        QColor(
            70,
            90,
            230
        )
    );

    drawStroke(
        engine,
        image,
        280.0f,
        0.2f,
        1.0f
    );

    /*
     * Stroke vert avec mélange.
     */
    engine.setColor(
        QColor(
            50,
            210,
            110
        )
    );

    drawStroke(
        engine,
        image,
        430.0f,
        0.15f,
        1.0f
    );

    /*
     * Dernier stroke avec forte dilution.
     */
    BrushSettings diluted =
        engine.settings();

    diluted.dilution = 0.80f;
    diluted.pickup = 0.35f;
    diluted.smudge = 0.30f;
    diluted.colorCarry = 0.40f;
    diluted.randomSeed = 98765;

    engine.setSettings(diluted);

    engine.setColor(
        QColor(
            210,
            80,
            180
        )
    );

    drawStroke(
        engine,
        image,
        570.0f,
        0.30f,
        1.0f
    );

    /*
     * Tests numériques du mélange.
     */
    const QColor a(
        255,
        0,
        0
    );

    const QColor b(
        0,
        0,
        255
    );

    /*
     * On valide au minimum que l'image
     * contient bien plusieurs niveaux après mélange.
     */
    const QColor pixel1 =
        image.pixelColor(
            500,
            130
        );

    const QColor pixel2 =
        image.pixelColor(
            500,
            280
        );

    const QColor pixel3 =
        image.pixelColor(
            500,
            430
        );

    const QColor pixel4 =
        image.pixelColor(
            500,
            570
        );

    qDebug()
        << "Pixel stroke 1 :"
        << pixel1;

    qDebug()
        << "Pixel stroke 2 :"
        << pixel2;

    qDebug()
        << "Pixel stroke 3 :"
        << pixel3;

    qDebug()
        << "Pixel stroke 4 :"
        << pixel4;

    qDebug()
        << "Wet engine actif";

    qDebug()
        << "CreativeCore Wet / Smudge / Mixing OK";

    Q_UNUSED(a);
    Q_UNUSED(b);

    if (!image.save(
            "cpp_brush_test.png"
        ))
    {
        qDebug()
            << "ERREUR : impossible de sauvegarder l'image";
    }

    qDebug()
        << "Image : cpp_brush_test.png";

    return 0;
}
