from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import apply_gradient_native, apply_linear_gradient_native


class GradientTool:
    """Native raster gradients with two stops and feathered selection support."""

    GEOMETRIES = ("linear", "radial", "conical")
    COLOR_MODES = ("transparent", "color")
    SPREADS = ("pad", "repeat", "reflect")

    def __init__(self) -> None:
        self.geometry = "linear"
        self.color_mode = "transparent"
        self.end_color = QColor("white")
        self.reverse = False
        self.spread = "pad"
        self.opacity = 1.0

    def apply(
        self,
        image: QImage,
        start: QPoint | QPointF,
        end: QPoint | QPointF,
        color: QColor,
        *,
        selection_mask: QImage | None = None,
    ) -> QRect:
        if image.isNull():
            return QRect()

        start_point = QPointF(start)
        end_point = QPointF(end)
        if start_point == end_point:
            end_point.setX(end_point.x() + 1.0)

        if self.geometry not in self.GEOMETRIES or self.color_mode not in self.COLOR_MODES:
            raise ValueError("Mode de dégradé inconnu")
        if self.spread not in self.SPREADS or not 0.0 <= self.opacity <= 1.0:
            raise ValueError("Les paramètres du dégradé sont invalides")
        if selection_mask is not None and (
                selection_mask.isNull() or selection_mask.size() != image.size()):
            raise ValueError("La sélection doit avoir la taille du calque")

        foreground = QColor(color)
        # Preserve exact results and compatibility of the original unmasked
        # linear preset. Every extended mode uses the versioned native API.
        legacy = (self.geometry == "linear" and self.color_mode == "transparent"
                  and not self.reverse and self.spread == "pad" and self.opacity == 1.0
                  and selection_mask is None)
        if legacy:
            native_result = apply_linear_gradient_native(
                image, start_point.x(), start_point.y(), end_point.x(), end_point.y(),
                foreground,
            )
        else:
            background = QColor(self.end_color if self.color_mode == "color" else foreground)
            if self.color_mode == "transparent":
                background.setAlpha(0)
            native_result = apply_gradient_native(
                image, start_point.x(), start_point.y(), end_point.x(), end_point.y(),
                foreground, background, geometry=self.geometry, spread=self.spread,
                reverse=self.reverse, opacity=self.opacity, selection_mask=selection_mask,
            )
        if native_result is not True:
            raise RuntimeError("CreativeCore is required to render gradients")
        return image.rect()


__all__ = ["GradientTool"]
