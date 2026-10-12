from __future__ import annotations

from dataclasses import dataclass

from CORE.native_bridge import load_creative_core, native_fill_ex
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage


@dataclass
class FillOptions:
    """Options bar state of the paint bucket.

    The class defaults are a plain flood fill; the UI applies the colouring
    defaults (STUDIO_DEFAULTS) until the user changes them.
    """
    tolerance: int = 0
    sample_all_layers: bool = False   # follow the line art of every visible layer
    gap: int = 0                      # close gaps in the lines up to this many pixels
    grow: int = 0                     # extend under the lines (no white halo)


STUDIO_DEFAULTS = {"tolerance": 24, "sample_all_layers": True, "gap": 2, "grow": 1}


class FillTool:
    """Colouring fill: region found on a reference image, painted on the layer.

    With "sample all layers" the region follows the visible composite, so flat
    colours can go on their own layer under the inks.  Gap closing seals small
    openings in the line art without leaking, and growing pushes the colour a
    pixel or two under the lines.
    """

    def __init__(self, tolerance: int = 0) -> None:
        self.options = FillOptions(tolerance=max(0, min(255, int(tolerance))))
        self.cpp_library = load_creative_core()
        self._reference: QImage | None = None

    # Kept for scripts written against the old API.
    @property
    def tolerance(self) -> int:
        return self.options.tolerance

    @tolerance.setter
    def tolerance(self, value: int) -> None:
        self.options.tolerance = max(0, min(255, int(value)))

    def set_reference(self, reference: QImage | None) -> None:
        """Image the region is detected on for the next fill (None = the layer)."""
        if reference is not None and reference.format() not in (
                QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            reference = reference.convertToFormat(QImage.Format.Format_ARGB32)
        self._reference = reference

    def _run(self, image: QImage, position: QPoint, color: QColor, apply: bool):
        x, y = position.x(), position.y()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return None
        reference = self._reference if (self._reference is not None
                                        and self._reference.size() == image.size()) else None
        options = self.options
        return native_fill_ex(image, reference, x, y, options.tolerance, options.gap,
                              options.grow, color, apply, self.cpp_library)

    def preview_bounds(self, image: QImage, position: QPoint):
        """Bounds the fill will touch, without changing pixels (history planning)."""
        bounds = self._run(image, position, QColor(0, 0, 0, 255), apply=False)
        if bounds is None:
            if not (0 <= position.x() < image.width() and 0 <= position.y() < image.height()):
                return None
            raise RuntimeError("CreativeCore is required for fill previews")
        return QRect(*bounds)

    def fill(self, image: QImage, position: QPoint, color: QColor) -> QRect:
        """Fill and return the modified bounding rectangle."""
        bounds = self._run(image, position, color, apply=True)
        if bounds is None:
            if not (0 <= position.x() < image.width() and 0 <= position.y() < image.height()):
                return QRect()
            raise RuntimeError("CreativeCore is required for raster fills")
        return QRect(*bounds)


__all__ = ["FillOptions", "FillTool", "STUDIO_DEFAULTS"]
