from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import apply_linear_gradient_native


class GradientTool:
    """Linear foreground-to-transparent gradient for raster layers."""

    def apply(
        self,
        image: QImage,
        start: QPoint | QPointF,
        end: QPoint | QPointF,
        color: QColor,
    ) -> QRect:
        if image.isNull():
            return QRect()

        start_point = QPointF(start)
        end_point = QPointF(end)
        if start_point == end_point:
            end_point.setX(end_point.x() + 1.0)

        opaque = QColor(color)
        native_result = apply_linear_gradient_native(
            image, start_point.x(), start_point.y(), end_point.x(), end_point.y(), opaque
        )
        if native_result is not True:
            raise RuntimeError("CreativeCore is required to render gradients")
        return image.rect()


__all__ = ["GradientTool"]
