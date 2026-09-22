from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QTransform

from CORE.native_bridge import transform_raster_native
from DOCUMENTS.selection import SelectionMask


@dataclass(frozen=True)
class TransformSpec:
    translate_x: float = 0.0
    translate_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0


@dataclass
class TransformResult:
    image: QImage
    selection_image: QImage | None = None


class TransformTool:
    """Affine raster transform shared by full-layer and selection workflows."""

    @staticmethod
    def matrix(bounds: QRectF, spec: TransformSpec) -> QTransform:
        center = bounds.center()
        transform = QTransform()
        transform.translate(center.x() + spec.translate_x, center.y() + spec.translate_y)
        transform.rotate(spec.rotation)
        transform.scale(spec.scale_x, spec.scale_y)
        transform.translate(-center.x(), -center.y())
        return transform

    def apply(self, image: QImage, spec: TransformSpec,
              selection: SelectionMask | None = None) -> TransformResult:
        native_result = transform_raster_native(
            image, selection.image if selection is not None else None,
            spec.translate_x, spec.translate_y, spec.scale_x, spec.scale_y,
            spec.rotation,
        )
        if native_result is None:
            raise RuntimeError("CreativeCore is required for raster transforms")
        return TransformResult(*native_result)


__all__ = ["TransformTool", "TransformSpec", "TransformResult"]
