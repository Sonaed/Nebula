"""Photoshop-style Free Transform session (Ctrl+T feel).

The whole gesture sequence (move, scale, rotate, as many drags as you like)
is accumulated into ONE matrix and the pixels are resampled exactly once on
commit (Enter / tool change). The old tool resampled on every mouse release,
so each extra adjustment blurred the image a little more.

Controls:
  * corner handles  - proportional scale (Shift = free), anchored at the
                      opposite corner; Alt = scale from the centre
  * edge handles    - one axis (Shift = proportional), Alt = from the centre
  * outside the box - rotate around the centre (Shift = 15° steps)
  * inside the box  - move (Shift = constrain to horizontal/vertical)
  * Enter           - commit;  Esc - cancel
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform, QPolygonF

from TOOLS.transform_tool import TransformTool, draw_transformed, split_by_selection


# (hx, hy) sign of each handle in the box's local frame.
HANDLES = {
    "top_left": (-1, -1), "top": (0, -1), "top_right": (1, -1),
    "right": (1, 0), "bottom_right": (1, 1), "bottom": (0, 1),
    "bottom_left": (-1, 1), "left": (-1, 0),
}

CURSORS = {
    "move": Qt.CursorShape.SizeAllCursor,
    "rotate": Qt.CursorShape.CrossCursor,
    "top_left": Qt.CursorShape.SizeFDiagCursor, "bottom_right": Qt.CursorShape.SizeFDiagCursor,
    "top_right": Qt.CursorShape.SizeBDiagCursor, "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
    "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
}


class FreeTransformSession:
    MIN_SCALE = 0.01

    def __init__(self, layer, selection_image: QImage | None, bounds: QRect) -> None:
        self.layer = layer
        self.original = layer.image.copy()
        self.original_selection = None if selection_image is None else selection_image.copy()
        self.bounds = QRect(bounds)
        self.floating, self.remainder = split_by_selection(self.original, self.original_selection)
        self.piece = self.floating.copy(self.bounds)
        # Transform parameters (centre-based).
        self.tx = self.ty = 0.0
        self.sx = self.sy = 1.0
        self.angle = 0.0
        self.drag_handle = ""
        self._drag_start = QPointF()
        self._drag_state = None

    # ------------------------------------------------------------ geometry
    @property
    def base_center(self) -> QPointF:
        return QRectF(self.bounds).center()

    def center(self) -> QPointF:
        c = self.base_center
        return QPointF(c.x() + self.tx, c.y() + self.ty)

    def matrix(self) -> QTransform:
        c = self.base_center
        t = QTransform()
        t.translate(c.x() + self.tx, c.y() + self.ty)
        t.rotate(self.angle)
        t.scale(self.sx, self.sy)
        t.translate(-c.x(), -c.y())
        return t

    def is_identity(self) -> bool:
        return (abs(self.tx) < 1e-4 and abs(self.ty) < 1e-4 and abs(self.sx - 1) < 1e-6
                and abs(self.sy - 1) < 1e-6 and abs(self.angle) < 1e-6)

    def corners(self) -> list[QPointF]:
        r = QRectF(self.bounds)
        m = self.matrix()
        return [m.map(p) for p in (r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())]

    def handle_points(self) -> dict[str, QPointF]:
        r = QRectF(self.bounds)
        c = r.center()
        m = self.matrix()
        return {name: m.map(QPointF(c.x() + hx * r.width() / 2, c.y() + hy * r.height() / 2))
                for name, (hx, hy) in HANDLES.items()}

    def _to_local(self, point: QPointF, center: QPointF, angle: float) -> QPointF:
        """Document point -> unrotated frame centred on ``center``."""
        a = radians(-angle)
        dx, dy = point.x() - center.x(), point.y() - center.y()
        return QPointF(dx * cos(a) - dy * sin(a), dx * sin(a) + dy * cos(a))

    def _from_local(self, local: QPointF, center: QPointF, angle: float) -> QPointF:
        a = radians(angle)
        return QPointF(center.x() + local.x() * cos(a) - local.y() * sin(a),
                       center.y() + local.x() * sin(a) + local.y() * cos(a))

    # ------------------------------------------------------------- hit test
    def hit_test(self, point: QPointF, zoom: float) -> str:
        radius = 9.0 / max(zoom, 0.01)
        for name, handle in self.handle_points().items():
            if hypot(point.x() - handle.x(), point.y() - handle.y()) <= radius:
                return name
        if QPolygonF(self.corners()).containsPoint(point, Qt.FillRule.OddEvenFill):
            return "move"
        return "rotate"   # anywhere outside the box rotates, like Photoshop

    # ----------------------------------------------------------------- drag
    def begin_drag(self, handle: str, point: QPointF) -> None:
        self.drag_handle = handle
        self._drag_start = QPointF(point)
        self._drag_state = (self.tx, self.ty, self.sx, self.sy, self.angle, self.center())

    def update_drag(self, point: QPointF, shift: bool, alt: bool) -> None:
        if not self.drag_handle or self._drag_state is None:
            return
        tx0, ty0, sx0, sy0, angle0, center0 = self._drag_state
        handle = self.drag_handle
        if handle == "move":
            dx, dy = point.x() - self._drag_start.x(), point.y() - self._drag_start.y()
            if shift:
                if abs(dx) >= abs(dy):
                    dy = 0.0
                else:
                    dx = 0.0
            self.tx, self.ty = tx0 + dx, ty0 + dy
            return
        if handle == "rotate":
            a1 = degrees(atan2(point.y() - center0.y(), point.x() - center0.x()))
            a0 = degrees(atan2(self._drag_start.y() - center0.y(), self._drag_start.x() - center0.x()))
            angle = angle0 + (a1 - a0)
            if shift:
                angle = round(angle / 15.0) * 15.0
            self.angle = (angle + 180.0) % 360.0 - 180.0
            return

        hx, hy = HANDLES[handle]
        w, h = float(self.bounds.width()) or 1.0, float(self.bounds.height()) or 1.0
        half_x0, half_y0 = sx0 * w / 2.0, sy0 * h / 2.0
        local = self._to_local(point, center0, angle0)
        # Anchor: opposite side, or the centre with Alt.
        ax = 0.0 if (alt or hx == 0) else -hx * half_x0
        ay = 0.0 if (alt or hy == 0) else -hy * half_y0
        sx, sy = sx0, sy0
        if hx:
            span = (local.x() - ax) * hx * (2.0 if alt else 1.0)
            sx = span / w
        if hy:
            span = (local.y() - ay) * hy * (2.0 if alt else 1.0)
            sy = span / h
        corner = bool(hx and hy)
        proportional = (not shift) if corner else shift
        if proportional:
            if corner:
                fx, fy = sx / sx0 if sx0 else 1.0, sy / sy0 if sy0 else 1.0
                factor = fx if abs(fx) >= abs(fy) else fy
            else:
                factor = (sx / sx0) if hx else (sy / sy0)
            sx, sy = sx0 * factor, sy0 * factor
        sx = sx if abs(sx) >= self.MIN_SCALE else (self.MIN_SCALE if sx >= 0 else -self.MIN_SCALE)
        sy = sy if abs(sy) >= self.MIN_SCALE else (self.MIN_SCALE if sy >= 0 else -self.MIN_SCALE)
        # New centre in the local frame: halfway between anchor and moving side.
        cx = 0.0 if (alt or not hx) else ax + hx * sx * w / 2.0
        cy = 0.0 if (alt or not hy) else ay + hy * sy * h / 2.0
        if proportional and not alt:
            # the unconstrained axis of a proportional edge drag stays centred
            if not hx:
                cx = 0.0
            if not hy:
                cy = 0.0
        new_center = self._from_local(QPointF(cx, cy), center0, angle0)
        base = self.base_center
        self.sx, self.sy = sx, sy
        self.tx, self.ty = new_center.x() - base.x(), new_center.y() - base.y()

    def end_drag(self) -> None:
        self.drag_handle = ""
        self._drag_state = None

    def nudge(self, dx: float, dy: float) -> None:
        self.tx += dx
        self.ty += dy

    # --------------------------------------------------------------- output
    def result(self) -> tuple[QImage, QImage | None]:
        fmt = (self.original.format() if self.original.format() in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)
            else QImage.Format.Format_ARGB32)
        m = self.matrix()
        image = TransformTool.render(self.remainder, self.floating, self.bounds, m, fmt)
        selection = (TransformTool.transform_selection(self.original_selection, self.bounds, m)
                     if self.original_selection is not None else None)
        return image, selection

    def remainder_image(self) -> QImage:
        fmt = (self.original.format() if self.original.format() in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)
            else QImage.Format.Format_ARGB32)
        return self.remainder.convertToFormat(fmt)

    # -------------------------------------------------------------- drawing
    def draw(self, painter: QPainter, offset: QPointF, zoom: float, opacity: float = 1.0) -> None:
        """Draw preview + box. ``painter`` is in (unrotated) view coordinates."""
        painter.save()
        painter.translate(offset)
        painter.scale(zoom, zoom)
        painter.setOpacity(opacity)
        # Preview only needs screen resolution: skip the costly pre-reduction.
        draw_transformed(painter, self.piece, QPointF(self.bounds.topLeft()),
                         self.matrix(), high_quality=False)
        painter.restore()

        to_screen = lambda p: QPointF(offset.x() + p.x() * zoom, offset.y() + p.y() * zoom)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        polygon = QPolygonF([to_screen(p) for p in self.corners()])
        for colour, width in ((QColor(0, 0, 0, 170), 3.0), (QColor(255, 255, 255, 235), 1.0)):
            pen = QPen(colour, width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
        pen = QPen(QColor(30, 30, 30), 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255))
        for point in self.handle_points().values():
            s = to_screen(point)
            painter.drawRect(QRectF(s.x() - 4, s.y() - 4, 8, 8))
        c = to_screen(self.center())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(c, 4, 4)
        painter.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 6))
        painter.restore()


__all__ = ["FreeTransformSession", "CURSORS"]
