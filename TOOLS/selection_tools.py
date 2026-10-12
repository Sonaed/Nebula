from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from CORE.native_bridge import (load_creative_core, native_magic_wand,
                                fill_image_native, native_selection_shape_mask,
                                native_selection_bounds, copy_image_rect_native)


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
    _edit_region(mask, radius, lambda image: _native_filters().selection_feather(
        image.bits(), image.width(), image.height(), radius, stride=image.bytesPerLine()))


def _edit_region(mask, margin, operation):
    if not isinstance(mask, QImage):
        operation(mask)  # Native-wiring test doubles.
        return
    values = native_selection_bounds(mask)
    if values is None:
        raise RuntimeError('CreativeCore is required to measure mask bounds')
    bounds = QRect(*values)
    if bounds.isEmpty():
        return
    region = bounds.adjusted(-margin,-margin,margin,margin).intersected(mask.rect())
    local = mask.copy(region)
    operation(local)
    if not copy_image_rect_native(local,mask,local.rect(),region.x(),region.y()):
        raise RuntimeError('Could not apply selection edge processing')


# Keep the exact former float32 rounding without full-canvas float workspaces.
_AA_LUT = np.array([np.rint((np.float32(.5)*h + np.float32(.5)*
    (np.arange(10,dtype=np.float32)/np.float32(9)))*np.float32(255)).astype(np.uint8)
    for h in (0,1)])


def antialias_mask(mask: QImage) -> None:
    """Give a hard 0/255 mask a one-pixel soft edge, like Photoshop's Anti-alias.

    Interior and exterior pixels are untouched; boundary pixels get partial
    coverage from their 3x3 neighbourhood. The edge is softened symmetrically,
    so the selection neither grows nor shrinks.
    """
    def apply(image):
        alpha = _alpha_view(image)
        hard = (alpha >= 128).astype(np.uint8)
        padded = np.pad(hard, 1, mode='edge')
        h,w = hard.shape
        counts = sum(padded[dy:dy+h,dx:dx+w] for dy in range(3) for dx in range(3))
        alpha[:,:] = _AA_LUT[hard,counts]
    _edit_region(mask,1,apply)


class SelectionTools:
    SHAPE_TOOLS = frozenset({"select_rectangle", "select_ellipse", "lasso"})

    def __init__(self, cpp_library=None) -> None:
        self.cpp_library = cpp_library or load_creative_core()
        self.options = SelectionOptions()

    @staticmethod
    def shape_region(tool: str, size, points, anti_alias=True, feather=0):
        """Return (mask, document origin) including all antialias/feather support."""
        if tool not in SelectionTools.SHAPE_TOOLS:
            raise ValueError(f'Outil de sélection inconnu : {tool}')
        if not points:
            return _new_mask(QRect(0,0,1,1).size()), QPoint()
        import math
        margin=max(0,int(feather)) + (2 if anti_alias and tool!='select_rectangle' else 1)
        left=math.floor(min(p.x() for p in points))-margin
        top=math.floor(min(p.y() for p in points))-margin
        right=math.ceil(max(p.x() for p in points))+margin
        bottom=math.ceil(max(p.y() for p in points))+margin
        region=QRect(QPoint(left,top),QPoint(right,bottom)).intersected(QRect(QPoint(),size))
        if region.isEmpty():
            return _new_mask(QRect(0,0,1,1).size()),QPoint(-2,-2)
        local=[QPointF(p)-QPointF(region.topLeft()) for p in points]
        return SelectionTools.shape_mask(tool,region.size(),local,anti_alias,feather),region.topLeft()

    @staticmethod
    def shape_mask(tool: str, size, points: list[QPoint | QPointF],
                   anti_alias: bool = True, feather: int = 0) -> QImage:
        """Rasterise a marquee/lasso. Anti-aliased edges like Photoshop."""
        if tool not in SelectionTools.SHAPE_TOOLS:
            raise ValueError(f"Outil de sélection inconnu : {tool}")
        mask = _new_mask(size)
        if not points:
            return mask
        if native_selection_shape_mask(mask, tool, points) is None:
            raise RuntimeError("CreativeCore is required for shape selection")
        if anti_alias and tool != "select_rectangle":
            antialias_mask(mask)
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
