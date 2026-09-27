from __future__ import annotations

from PySide6.QtCore import QRect, QPoint
from PySide6.QtGui import QImage
from CORE.native_bridge import crop_image_native, native_crop_rect


class CropTool:
    @staticmethod
    def normalized_rect(start: QPoint, end: QPoint, bounds: QRect) -> QRect:
        result = native_crop_rect(start.x(), start.y(), end.x(), end.y(),
                                  bounds.x(), bounds.y(), bounds.width(), bounds.height())
        if result is None:
            raise RuntimeError("CreativeCore is required for crop geometry")
        x, y, width, height = result
        return QRect(x, y, width, height) if width > 0 and height > 0 else QRect()

    @staticmethod
    def apply(image: QImage, rect: QRect) -> QImage:
        if rect.isEmpty():
            return QImage()
        cropped = crop_image_native(image, rect)
        if cropped is None:
            raise RuntimeError("CreativeCore is required to crop raster pixels")
        return cropped


__all__ = ["CropTool"]
