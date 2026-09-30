"""Selection-aware non-destructive retouch primitives.

The source layer is read-only. Pixels are written only to a dedicated retouch
layer, whose operation log stays serializable for history, scripts and PSD
export diagnostics. The implementation deliberately keeps contextual fill
bounded to the selected rectangle: it is predictable on dense documents and
never materializes unrelated tiles.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage


@dataclass(frozen=True)
class RetouchOperation:
    kind: str
    source: tuple[int, int] | None
    target: tuple[int, int] | None
    radius: int = 1

    def as_dict(self) -> dict:
        return {"kind": self.kind,
                "source": None if self.source is None else list(self.source),
                "target": None if self.target is None else list(self.target),
                "radius": int(self.radius)}


class RetouchTool:
    """Clone, heal and limited contextual fill for a separate retouch layer."""

    @staticmethod
    def _allowed(selection, x: int, y: int) -> bool:
        return selection is None or selection.is_empty() or selection.contains(x, y)

    @staticmethod
    def _circle(center: QPoint, radius: int, bounds: QRect):
        radius = max(1, int(radius))
        rr = radius * radius
        for y in range(max(bounds.top(), center.y() - radius), min(bounds.bottom(), center.y() + radius) + 1):
            dy = y - center.y()
            for x in range(max(bounds.left(), center.x() - radius), min(bounds.right(), center.x() + radius) + 1):
                if (x - center.x()) ** 2 + dy * dy <= rr:
                    yield x, y

    @staticmethod
    def _ensure_layer(document, layer=None):
        layer = layer or document.add_retouch_layer()
        if getattr(layer, "layer_kind", "raster") != "retouch":
            raise ValueError("La retouche doit être appliquée sur un calque Retouche")
        return layer

    def clone(self, document, source_layer, source: QPoint, target: QPoint,
              radius: int = 16, *, layer=None, selection=None):
        layer = self._ensure_layer(document, layer)
        source_image = source_layer.image
        output = layer.image.copy()
        selection = selection if selection is not None else document.selection
        offset = source - target
        bounds = output.rect()
        for x, y in self._circle(target, radius, bounds):
            sx, sy = x + offset.x(), y + offset.y()
            if (0 <= sx < source_image.width() and 0 <= sy < source_image.height()
                    and self._allowed(selection, x, y)):
                output.setPixelColor(x, y, source_image.pixelColor(sx, sy))
        layer.image = output
        operation = RetouchOperation("clone", (source.x(), source.y()),
                                     (target.x(), target.y()), radius)
        layer.retouch_operations.append(operation.as_dict())
        return layer

    def heal(self, document, source_layer, source: QPoint, target: QPoint,
             radius: int = 16, *, layer=None, selection=None):
        """Blend a sampled patch with local destination colour on a retouch layer."""
        layer = self._ensure_layer(document, layer)
        source_image, base = source_layer.image, layer.image.copy()
        selection = selection if selection is not None else document.selection
        offset, bounds = source - target, base.rect()
        for x, y in self._circle(target, radius, bounds):
            sx, sy = x + offset.x(), y + offset.y()
            if not (0 <= sx < source_image.width() and 0 <= sy < source_image.height()
                    and self._allowed(selection, x, y)):
                continue
            sampled = source_image.pixelColor(sx, sy)
            under = source_layer.image.pixelColor(x, y)
            base.setPixelColor(x, y, QColor((sampled.red() + under.red()) // 2,
                                            (sampled.green() + under.green()) // 2,
                                            (sampled.blue() + under.blue()) // 2,
                                            sampled.alpha()))
        layer.image = base
        layer.retouch_operations.append(RetouchOperation(
            "heal", (source.x(), source.y()), (target.x(), target.y()), radius).as_dict())
        return layer

    def contextual_fill(self, document, source_layer, *, layer=None, selection=None):
        """Limited deterministic content fill using the selected border mean."""
        selection = selection if selection is not None else document.selection
        if selection is None or selection.is_empty():
            raise ValueError("Le remplissage contextuel limité requiert une sélection")
        layer = self._ensure_layer(document, layer)
        bounds = selection.bounds().intersected(source_layer.image.rect())
        if bounds.isEmpty():
            return layer
        samples = []
        image = source_layer.image
        expanded = bounds.adjusted(-1, -1, 1, 1).intersected(image.rect())
        for x in range(expanded.left(), expanded.right() + 1):
            for y in (expanded.top(), expanded.bottom()):
                samples.append(image.pixelColor(x, y))
        for y in range(bounds.top(), bounds.bottom() + 1):
            for x in (expanded.left(), expanded.right()):
                samples.append(image.pixelColor(x, y))
        if not samples:
            return layer
        fill = QColor(sum(p.red() for p in samples) // len(samples),
                      sum(p.green() for p in samples) // len(samples),
                      sum(p.blue() for p in samples) // len(samples),
                      sum(p.alpha() for p in samples) // len(samples))
        output = layer.image.copy()
        for y in range(bounds.top(), bounds.bottom() + 1):
            for x in range(bounds.left(), bounds.right() + 1):
                if self._allowed(selection, x, y):
                    output.setPixelColor(x, y, fill)
        layer.image = output
        layer.retouch_operations.append(RetouchOperation("contextual_fill", None, None, 0).as_dict())
        return layer


__all__ = ["RetouchOperation", "RetouchTool"]
