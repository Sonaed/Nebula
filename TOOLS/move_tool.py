from PySide6.QtGui import (
    QImage,
)
from PySide6.QtCore import (
    QPoint,
    QPointF,
)
from CORE.native_bridge import translate_image_native


class MoveTool:

    def __init__(self) -> None:

        self.active: bool = False

        self.last_position: QPoint = QPoint()

    # =========================================================
    # DÉBUT
    # =========================================================

    def begin(
        self,
        position: QPoint
    ) -> None:

        self.active = True

        self.last_position = position

    # =========================================================
    # DÉPLACEMENT
    # =========================================================

    def move(
        self,
        image: QImage,
        position: QPoint
    ) -> bool:

        if not self.active:
            return False

        delta = (
            position
            - self.last_position
        )

        if (
            delta.x() == 0
            and delta.y() == 0
        ):
            return True

        if not self.apply(
            image,
            QPointF(
                delta.x(),
                delta.y()
            )
        ):
            return False

        self.last_position = position
        return True

    # =========================================================
    # FIN
    # =========================================================

    def end(self) -> None:

        self.active = False

    # =========================================================
    # APPLICATION
    # =========================================================

    def apply(
        self,
        image: QImage,
        delta: QPointF
    ) -> bool:

        dx = int(
            round(
                delta.x()
            )
        )

        dy = int(
            round(
                delta.y()
            )
        )

        if dx == 0 and dy == 0:
            return True

        translated = translate_image_native(image, dx, dy)
        if translated is not None:
            image.swap(translated)
            return True
        return False

    # =========================================================
    # ÉTAT
    # =========================================================

    def is_active(self) -> bool:

        return self.active
