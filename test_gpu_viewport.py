from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QMainWindow

from CANVAS.gpu_viewport import GPUViewport


def create_test_image() -> QImage:

    width = 1200
    height = 800

    image = QImage(
        width,
        height,
        QImage.Format.Format_RGBA8888,
    )

    image.fill(
        QColor(
            30,
            30,
            30,
            255,
        )
    )

    painter = QPainter(
        image
    )

    # Quadrillage
    size = 40

    for y in range(
        0,
        height,
        size,
    ):

        for x in range(
            0,
            width,
            size,
        ):

            if (
                (x // size)
                + (y // size)
            ) % 2 == 0:

                painter.fillRect(
                    x,
                    y,
                    size,
                    size,
                    QColor(
                        60,
                        60,
                        60,
                        255,
                    ),
                )

    # Grand rectangle de test
    painter.fillRect(
        100,
        100,
        1000,
        600,
        QColor(
            180,
            100,
            40,
            255,
        ),
    )

    # Centre
    painter.fillRect(
        350,
        250,
        500,
        300,
        QColor(
            70,
            130,
            210,
            255,
        ),
    )

    painter.end()

    return image


def main() -> None:

    app = QApplication(
        sys.argv
    )

    window = QMainWindow()

    viewport = GPUViewport(
        create_test_image()
    )

    window.setCentralWidget(
        viewport
    )

    window.resize(
        1000,
        700
    )

    window.show()

    viewport.fit_image()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
