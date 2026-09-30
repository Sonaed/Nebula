from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from PySide6.QtCore import QRect, QRectF, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QTransform
from DOCUMENTS.selection import SelectionMask
from CORE.native_bridge import transform_raster_native


@dataclass(frozen=True)
class TransformSpec:
    translate_x: float = 0.0
    translate_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0


@dataclass(frozen=True)
class TransformState:
    """Serializable, non-destructive affine state attached to a raster layer."""
    translate_x: float = 0.0
    translate_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {"translate_x": float(self.translate_x), "translate_y": float(self.translate_y),
                "scale_x": float(self.scale_x), "scale_y": float(self.scale_y),
                "rotation": float(self.rotation)}

    @classmethod
    def from_value(cls, value) -> "TransformState":
        value = value or {}
        if not isinstance(value, dict):
            raise ValueError("TransformState invalide")
        return cls(**{name: float(value.get(name, default)) for name, default in
                      (("translate_x", 0), ("translate_y", 0), ("scale_x", 1),
                       ("scale_y", 1), ("rotation", 0))})


@dataclass(frozen=True)
class PerspectiveSpec:
    """Destination quadrilateral in image coordinates, clockwise."""
    corners: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LiquifyStroke:
    x: float
    y: float
    dx: float
    dy: float
    radius: float = 32.0
    strength: float = 0.5


@dataclass(frozen=True)
class WarpControl:
    x: float
    y: float
    dx: float
    dy: float
    radius: float = 64.0


@dataclass
class TransformResult:
    image: QImage
    selection_image: QImage | None = None


def _premul(image: QImage) -> QImage:
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def split_by_selection(image: QImage, selection_image: QImage | None):
    """Return (floating, remainder) premultiplied images.

    Soft selections are honoured like Photoshop: a 30%-selected pixel moves
    30% of itself and leaves 70% behind (the old code moved any pixel with
    alpha > 0 completely, leaving hard fringes).
    """
    source = _premul(image)
    if selection_image is None:
        remainder = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
        remainder.fill(Qt.GlobalColor.transparent)
        return source, remainder
    floating = source.copy()
    painter = QPainter(floating)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, selection_image)
    painter.end()
    remainder = source.copy()
    painter = QPainter(remainder)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, selection_image)
    painter.end()
    return floating, remainder


def _scale_factors(transform: QTransform) -> tuple[float, float]:
    return (float(np.hypot(transform.m11(), transform.m12())),
            float(np.hypot(transform.m21(), transform.m22())))


def draw_transformed(painter: QPainter, piece: QImage, origin: QPointF,
                     transform: QTransform, high_quality: bool = True) -> None:
    """Draw ``piece`` (placed at ``origin`` in document space) through ``transform``.

    Strong downscales are pre-reduced with Qt's area-averaging smooth scale;
    bilinear sampling alone skips pixels and gives shimmering, aliased
    results below ~50%.
    """
    if piece.isNull() or piece.width() == 0 or piece.height() == 0:
        return
    base = QTransform.fromTranslate(origin.x(), origin.y()) * transform
    image = piece
    if high_quality:
        fx, fy = _scale_factors(transform)
        if fx < 0.75 or fy < 0.75:
            tw = max(1, int(round(piece.width() * min(1.0, fx))))
            th = max(1, int(round(piece.height() * min(1.0, fy))))
            image = piece.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            base = QTransform.fromScale(piece.width() / tw, piece.height() / th) * base
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setTransform(base, True)
    painter.drawImage(0, 0, image)
    painter.restore()


class TransformTool:
    """Affine raster transform shared by full-layer and selection workflows."""

    @staticmethod
    def matrix(bounds: QRectF, spec: TransformSpec) -> QTransform:
        center = bounds.center()
        transform = QTransform()
        transform.translate(center.x() + spec.translate_x, center.y() + spec.translate_y)
        transform.rotate(spec.rotation)
        transform.scale(spec.scale_x, spec.scale_y)
        transform.translate(-center.x(), -center.y())
        return transform

    @staticmethod
    def render(remainder: QImage, floating: QImage, bounds: QRect,
               transform: QTransform, output_format) -> QImage:
        """Composite a transformed floating piece back onto the remainder."""
        result = remainder.copy()
        piece = floating.copy(bounds)
        painter = QPainter(result)
        draw_transformed(painter, piece, QPointF(bounds.topLeft()), transform)
        painter.end()
        return result.convertToFormat(output_format)

    @staticmethod
    def transform_selection(selection_image: QImage, bounds: QRect,
                            transform: QTransform) -> QImage:
        output = QImage(selection_image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        draw_transformed(painter, _premul(selection_image).copy(bounds),
                         QPointF(bounds.topLeft()), transform)
        painter.end()
        return output.convertToFormat(QImage.Format.Format_ARGB32)

    def apply(self, image: QImage, spec: TransformSpec,
              selection: SelectionMask | None = None) -> TransformResult:
        selection_image = None
        bounds = QRect(0, 0, image.width(), image.height())
        if selection is not None and not selection.is_empty():
            selection_image = selection.image
            bounds = selection.bounds()
        transform = self.matrix(QRectF(bounds), spec)
        native = transform_raster_native(
            image, selection_image, spec.translate_x, spec.translate_y,
            spec.scale_x, spec.scale_y, spec.rotation)
        if native is None:
            raise RuntimeError("CreativeCore is required for raster transforms")
        native_image, native_selection = native
        return TransformResult(native_image, native_selection)
        floating, remainder = split_by_selection(image, selection_image)
        output_format = (image.format() if image.format() in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)
            else QImage.Format.Format_ARGB32)
        result = self.render(remainder, floating, bounds, transform, output_format)
        new_selection = (self.transform_selection(selection_image, bounds, transform)
                         if selection_image is not None else None)
        return TransformResult(result, new_selection)

    @staticmethod
    def set_non_destructive_state(layer, state: TransformState | TransformSpec) -> None:
        """Attach a render-time transform without touching source tiles."""
        if not isinstance(state, (TransformState, TransformSpec)):
            raise TypeError("state doit être TransformState ou TransformSpec")
        layer.transform_state = TransformState(
            state.translate_x, state.translate_y, state.scale_x, state.scale_y, state.rotation).as_dict()
        layer._transform_cache = None

    @staticmethod
    def clear_non_destructive_state(layer) -> None:
        layer.transform_state = None
        layer._transform_cache = None

    @staticmethod
    def perspective(image: QImage, spec: PerspectiveSpec) -> QImage:
        """Apply a true four-corner projective transform using Qt's rasterizer."""
        if len(spec.corners) != 4:
            raise ValueError("Perspective transform requires four corners")
        source = [QPointF(0, 0), QPointF(image.width(), 0),
                  QPointF(image.width(), image.height()), QPointF(0, image.height())]
        target = [QPointF(float(x), float(y)) for x, y in spec.corners]
        transform = QTransform()
        if not QTransform.quadToQuad(source, target, transform):
            raise ValueError("Invalid perspective quadrilateral")
        return image.transformed(transform, Qt.TransformationMode.SmoothTransformation)

    @staticmethod
    def liquify(image: QImage, strokes: list[LiquifyStroke]) -> QImage:
        """Apply push-style liquify strokes with a bounded inverse warp."""
        source = image.convertToFormat(QImage.Format.Format_RGBA8888)
        h, w = source.height(), source.width()
        data = np.frombuffer(source.constBits(), dtype=np.uint8, count=w * h * 4).reshape(h, w, 4)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        sample_x, sample_y = np.array(xx, copy=True), np.array(yy, copy=True)
        for stroke in strokes:
            radius = max(1.0, float(stroke.radius))
            distance = np.hypot(xx - stroke.x, yy - stroke.y)
            weight = np.clip(1.0 - distance / radius, 0.0, 1.0) ** 2
            sample_x -= float(stroke.dx) * float(stroke.strength) * weight
            sample_y -= float(stroke.dy) * float(stroke.strength) * weight
        sample_x = np.clip(np.rint(sample_x), 0, w - 1).astype(np.int32)
        sample_y = np.clip(np.rint(sample_y), 0, h - 1).astype(np.int32)
        result = QImage(w, h, QImage.Format.Format_RGBA8888)
        result.bits()[:] = data[sample_y, sample_x].tobytes()
        return result

    @staticmethod
    def warp(image: QImage, controls: list[WarpControl]) -> QImage:
        """Apply a smooth inverse mesh warp from sparse control points."""
        return TransformTool.liquify(
            image,
            [LiquifyStroke(c.x, c.y, c.dx, c.dy, c.radius, 1.0) for c in controls],
        )


__all__ = ["TransformTool", "split_by_selection", "draw_transformed", "TransformSpec", "TransformResult",
           "PerspectiveSpec", "LiquifyStroke", "WarpControl", "TransformState"]
