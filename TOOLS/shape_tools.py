from __future__ import annotations

from PySide6.QtCore import QPointF
from CORE.native_bridge import native_shape_path


class ShapeTools:
    """Geometry generation only; brush rendering remains owned by the Canvas."""

    SUPPORTED = frozenset({"line", "rectangle", "ellipse"})

    def path(self, shape: str, start, end) -> list[QPointF]:
        if shape not in self.SUPPORTED:
            raise ValueError(f"Forme inconnue : {shape}")
        start_point = QPointF(start)
        end_point = QPointF(end)
        coordinates = native_shape_path(shape, start_point.x(), start_point.y(),
                                         end_point.x(), end_point.y())
        if coordinates is None:
            raise RuntimeError("CreativeCore is required to generate shape paths")
        return [QPointF(x, y) for x, y in coordinates]


__all__ = ["ShapeTools"]
