from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor, QImage
from CORE.native_bridge import (load_creative_core, native_magic_wand,
                                native_selection_shape_mask, fill_image_native)


class SelectionTools:
    SHAPE_TOOLS = frozenset({"select_rectangle", "select_ellipse", "lasso"})

    def __init__(self, cpp_library=None) -> None:
        self.cpp_library = cpp_library or load_creative_core()

    @staticmethod
    def shape_mask(tool: str, size, points: list[QPoint | QPointF]) -> QImage:
        mask = QImage(size, QImage.Format.Format_ARGB32)
        if not points:
            if not fill_image_native(mask, QColor(0, 0, 0, 0)):
                raise RuntimeError("CreativeCore is required to clear selection masks")
            return mask
        native_result = native_selection_shape_mask(mask, tool, points)
        if native_result:
            return mask
        if tool not in SelectionTools.SHAPE_TOOLS:
            raise ValueError(f"Outil de sélection inconnu : {tool}")
        raise RuntimeError("CreativeCore is required to rasterize selection shapes")

    @staticmethod
    def magic_wand(
        image: QImage,
        start: QPoint,
        tolerance: int = 16,
        cpp_library=None,
    ) -> QImage:
        mask = QImage(image.size(), QImage.Format.Format_ARGB32)
        if not fill_image_native(mask, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear selection masks")
        if not image.rect().contains(start):
            return mask
        tolerance = max(0, min(255, int(tolerance)))

        native_result = native_magic_wand(
            image, start.x(), start.y(), tolerance, mask,
            cpp_library or load_creative_core(),
        )
        if native_result:
            return mask

        raise RuntimeError("CreativeCore is required for magic-wand selection")


__all__ = ["SelectionTools"]
