from __future__ import annotations

from CORE.native_bridge import (load_creative_core, native_flood_fill,
                                native_flood_fill_bounds)
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage


class FillTool:
    """Contiguous flood fill operating directly on an editable layer."""

    def __init__(self, tolerance: int = 0) -> None:
        self.tolerance = max(0, min(255, int(tolerance)))
        self.cpp_library = load_creative_core()

    def preview_bounds(self, image: QImage, position: QPoint):
        """Inspect a native fill region without changing pixels."""
        x, y = position.x(), position.y()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return None
        bounds = native_flood_fill_bounds(
            image, x, y, self.tolerance, self.cpp_library
        )
        if bounds is None:
            raise RuntimeError("CreativeCore is required for fill previews")
        return QRect(*bounds)

    def fill(self, image: QImage, position: QPoint, color: QColor) -> QRect:
        """Fill a connected region and return the modified bounding rectangle."""
        width = image.width()
        height = image.height()
        start_x = position.x()
        start_y = position.y()
        if not (0 <= start_x < width and 0 <= start_y < height):
            return QRect()

        native_bounds = native_flood_fill(
            image, start_x, start_y, self.tolerance, color, self.cpp_library
        )
        if native_bounds is None:
            raise RuntimeError("CreativeCore is required for raster fills")
        return QRect(*native_bounds)


__all__ = ["FillTool"]
