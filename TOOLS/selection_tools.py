from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from CORE.native_bridge import (load_creative_core, native_magic_wand,
                                fill_image_native)


@dataclass
class SelectionOptions:
    """Photoshop-style options bar state shared by every selection tool."""
    anti_alias: bool = True
    feather: int = 0
    tolerance: int = 32          # Photoshop's default
    contiguous: bool = True
    sample_all_layers: bool = False


def _alpha_view(image: QImage) -> np.ndarray:
    """Writable (h, w) view on the alpha byte of an ARGB32 image."""
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    buffer = np.frombuffer(image.bits(), dtype=np.uint8, count=stride * height)
    return buffer.reshape(height, stride)[:, 3:width * 4:4]


def _white_rgb(image: QImage) -> None:
    """Selection masks keep white RGB; only alpha carries coverage."""
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    buffer = np.frombuffer(image.bits(), dtype=np.uint8, count=stride * height)
    rows = buffer.reshape(height, stride)
    for channel in range(3):
        rows[:, channel:width * 4:4] = 255


def _new_mask(size) -> QImage:
    mask = QImage(size, QImage.Format.Format_ARGB32)
    mask.fill(QColor(255, 255, 255, 0))
    return mask


def feather_mask(mask: QImage, radius: int) -> None:
    """Soften a selection candidate in place (CreativeCore box blur)."""
    radius = max(0, int(radius))
    if radius == 0:
        return
    from DOCUMENTS.selection import _native_filters
    _native_filters().selection_feather(mask.bits(), mask.width(), mask.height(), radius,
                                        stride=mask.bytesPerLine())


def antialias_mask(mask: QImage) -> None:
    """Give a hard 0/255 mask a one-pixel soft edge, like Photoshop's Anti-alias.

    Interior and exterior pixels are untouched; boundary pixels get partial
    coverage from their 3x3 neighbourhood. The edge is softened symmetrically,
    so the selection neither grows nor shrinks.
    """
    alpha = _alpha_view(mask)
    hard = (alpha >= 128).astype(np.float32)
    padded = np.pad(hard, 1, mode="edge")
    h, w = hard.shape
    box = sum(padded[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)) / 9.0
    soft = 0.5 * hard + 0.5 * box
    alpha[:, :] = np.clip(np.rint(soft * 255.0), 0, 255).astype(np.uint8)


class SelectionTools:
    SHAPE_TOOLS = frozenset({"select_rectangle", "select_ellipse", "lasso"})

    def __init__(self, cpp_library=None) -> None:
        self.cpp_library = cpp_library or load_creative_core()
        self.options = SelectionOptions()

    @staticmethod
    def shape_mask(tool: str, size, points: list[QPoint | QPointF],
                   anti_alias: bool = True, feather: int = 0) -> QImage:
        """Rasterise a marquee/lasso. Anti-aliased edges like Photoshop."""
        if tool not in SelectionTools.SHAPE_TOOLS:
            raise ValueError(f"Outil de sélection inconnu : {tool}")
        mask = _new_mask(size)
        if not points:
            return mask
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,
                              bool(anti_alias) and tool != "select_rectangle")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 255))
        if tool in ("select_rectangle", "select_ellipse"):
            first, last = QPointF(points[0]), QPointF(points[-1])
            bounds = QRectF(first, last).normalized()
            if tool == "select_rectangle":
                # Snap to whole pixels: a marquee never has soft edges.
                bounds = QRectF(round(bounds.left()), round(bounds.top()),
                                round(bounds.right()) - round(bounds.left()),
                                round(bounds.bottom()) - round(bounds.top()))
                painter.drawRect(bounds)
            else:
                painter.drawEllipse(bounds)
        elif len(points) >= 3:
            path = QPainterPath(QPointF(points[0]))
            for point in points[1:]:
                path.lineTo(QPointF(point))
            path.closeSubpath()
            path.setFillRule(Qt.FillRule.WindingFill)
            painter.drawPath(path)
        painter.end()
        feather_mask(mask, feather)
        return mask

    @staticmethod
    def magic_wand(
        image: QImage,
        start: QPoint,
        tolerance: int = 32,
        cpp_library=None,
        contiguous: bool = True,
        anti_alias: bool = True,
        feather: int = 0,
    ) -> QImage:
        mask = _new_mask(image.size())
        if not image.rect().contains(start):
            return mask
        tolerance = max(0, min(255, int(tolerance)))
        if image.format() not in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            image = image.convertToFormat(QImage.Format.Format_ARGB32)

        if contiguous:
            if not native_magic_wand(image, start.x(), start.y(), tolerance, mask,
                                     cpp_library or load_creative_core()):
                raise RuntimeError("CreativeCore is required for magic-wand selection")
        else:
            # Non-contiguous: every pixel of the image within tolerance.
            argb = image.convertToFormat(QImage.Format.Format_ARGB32)
            w, h, stride = argb.width(), argb.height(), argb.bytesPerLine()
            pixels = np.frombuffer(argb.constBits(), dtype=np.uint8,
                                   count=stride * h).reshape(h, stride)[:, :w * 4].reshape(h, w, 4)
            target = pixels[start.y(), start.x()].astype(np.int16)
            distance = np.abs(pixels.astype(np.int16) - target).max(axis=2)
            alpha = _alpha_view(mask)
            alpha[:, :] = np.where(distance <= tolerance, 255, 0).astype(np.uint8)

        _white_rgb(mask)
        if anti_alias:
            antialias_mask(mask)
        feather_mask(mask, feather)
        return mask


__all__ = ["SelectionTools", "SelectionOptions", "antialias_mask", "feather_mask"]
