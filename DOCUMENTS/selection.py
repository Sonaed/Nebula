from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from CORE.native_bridge import (load_creative_core, native_selection_bounds,
                                native_selection_combine, native_selection_contains,
                                native_selection_invert, fill_image_native)


def _native_selection_library():
    return load_creative_core()


class SelectionOperation(str, Enum):
    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


class SelectionMask:
    """Document-sized 8-bit semantic selection stored as an ARGB mask."""

    def __init__(self, width: int, height: int) -> None:
        self.image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._bounds_cache: QRect | None = None
        self.clear()

    def invalidate(self) -> None:
        self._bounds_cache = None

    @property
    def width(self) -> int:
        return self.image.width()

    @property
    def height(self) -> int:
        return self.image.height()

    def clear(self) -> None:
        if not fill_image_native(self.image, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear selections")
        self._bounds_cache = QRect()

    def select_all(self) -> None:
        if not fill_image_native(self.image, QColor(255, 255, 255, 255, 255)):
            raise RuntimeError("CreativeCore is required to select the whole document")
        self._bounds_cache = self.image.rect()

    def is_empty(self) -> bool:
        return self.bounds().isEmpty()

    def contains(self, x: int, y: int) -> bool:
        selected = native_selection_contains(self.image, x, y)
        if selected is None:
            raise RuntimeError("CreativeCore is required for selection queries")
        return selected

    def combine(self, candidate: QImage, operation: SelectionOperation) -> None:
        if candidate.size() != self.image.size():
            raise ValueError("Le masque de sélection doit avoir la taille du document")
        native_result = native_selection_combine(self.image, candidate, operation.value)
        if native_result is not True:
            raise RuntimeError("CreativeCore is required for selection operations")
        self.invalidate()

    def invert(self) -> None:
        if native_selection_invert(self.image) is not True:
            raise RuntimeError("CreativeCore is required to invert selections")
        self.invalidate()

    def bounds(self) -> QRect:
        if self._bounds_cache is not None:
            return QRect(self._bounds_cache)
        values = native_selection_bounds(self.image)
        if values is None:
            raise RuntimeError("CreativeCore is required to measure selections")
        self._bounds_cache = QRect(*values)
        return QRect(self._bounds_cache)


__all__ = ["SelectionMask", "SelectionOperation"]
