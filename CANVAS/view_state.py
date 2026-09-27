"""Pure canvas view geometry shared by the widget and unit tests."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF


def transform_point(position: QPointF, viewport_width: float, viewport_height: float,
                    rotation: float, flip_x: bool, flip_y: bool,
                    inverse: bool = False) -> QPointF:
    center = QPointF(float(viewport_width) * 0.5, float(viewport_height) * 0.5)
    point = position - center
    angle = -float(rotation) if inverse else float(rotation)
    if not inverse:
        if flip_x:
            point.setX(-point.x())
        if flip_y:
            point.setY(-point.y())
    radians = math.radians(angle)
    point = QPointF(
        point.x() * math.cos(radians) - point.y() * math.sin(radians),
        point.x() * math.sin(radians) + point.y() * math.cos(radians),
    )
    if inverse:
        if flip_x:
            point.setX(-point.x())
        if flip_y:
            point.setY(-point.y())
    return center + point


def fit_zoom(document_width: int, document_height: int, viewport_width: int,
             viewport_height: int, rotation: float, min_zoom: float,
             max_zoom: float, margin: int = 40) -> float:
    if document_width <= 0 or document_height <= 0:
        return float(min_zoom)
    angle = math.radians(float(rotation))
    rotated_width = abs(document_width * math.cos(angle)) + abs(document_height * math.sin(angle))
    rotated_height = abs(document_width * math.sin(angle)) + abs(document_height * math.cos(angle))
    available_width = max(int(viewport_width) - margin, 1)
    available_height = max(int(viewport_height) - margin, 1)
    return max(float(min_zoom), min(float(max_zoom),
        min(available_width / max(rotated_width, 1e-9),
            available_height / max(rotated_height, 1e-9))))
