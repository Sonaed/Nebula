"""Canvas Drawing Assistants — Krita-style.

Assistants snap strokes to geometric guides painted over the canvas.

Available assistants
--------------------
ruler               Two-point straight line.
ellipse             Three-point ellipse (centre + two radii).
perspective_1pt     One-point perspective (single vanishing point).
perspective_2pt     Two-point perspective (horizon + 2 VPs).
parallel_ruler      Infinite parallel lines at a fixed angle.
concentric          Concentric circles from a centre point.

Each assistant:
  • is rendered as a semi-transparent overlay in _draw_overlay().
  • snaps the cursor with snap_point(), returning the nearest on-guide position.
  • is defined by a list of *handle* points the user drags to configure.

Integration
-----------
The Canvas calls:
  assistants.draw_overlay(painter, view_state)
  snapped = assistants.snap_point(image_pos)
  assistants.mouse_press(image_pos, handle_mode=True)
  assistants.mouse_move(image_pos)
  assistants.mouse_release()
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import ClassVar
from uuid import uuid4

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QBrush,
)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def _snap_to_line(point: QPointF, a: QPointF, b: QPointF) -> QPointF:
    """Project *point* onto the infinite line through *a* and *b*."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if dx == 0 and dy == 0:
        return QPointF(a)
    t = ((point.x() - a.x()) * dx + (point.y() - a.y()) * dy) / (dx * dx + dy * dy)
    return QPointF(a.x() + t * dx, a.y() + t * dy)


def _line_intersection(p1: QPointF, p2: QPointF,
                       p3: QPointF, p4: QPointF) -> QPointF | None:
    """Return the intersection of line (p1–p2) and (p3–p4), or None if parallel."""
    d1x, d1y = p2.x() - p1.x(), p2.y() - p1.y()
    d2x, d2y = p4.x() - p3.x(), p4.y() - p3.y()
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-10:
        return None
    t = ((p3.x() - p1.x()) * d2y - (p3.y() - p1.y()) * d2x) / denom
    return QPointF(p1.x() + t * d1x, p1.y() + t * d1y)


def _snap_to_ellipse(point: QPointF, center: QPointF,
                     rx: float, ry: float, angle: float) -> QPointF:
    """Snap *point* to the nearest point on the axis-aligned ellipse
    (after rotating *point* by -*angle*)."""
    if rx < 0.1 or ry < 0.1:
        return QPointF(center)
    cos_a, sin_a = math.cos(-angle), math.sin(-angle)
    dx, dy = point.x() - center.x(), point.y() - center.y()
    lx = cos_a * dx - sin_a * dy
    ly = sin_a * dx + cos_a * dy
    # polar angle on unit circle
    theta = math.atan2(ly / ry, lx / rx)
    ex = rx * math.cos(theta)
    ey = ry * math.sin(theta)
    # rotate back
    cos_b, sin_b = math.cos(angle), math.sin(angle)
    return QPointF(center.x() + cos_b * ex - sin_b * ey,
                   center.y() + sin_b * ex + cos_b * ey)


# ─────────────────────────────────────────────────────────────────────────────
# Base assistant
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _Assistant:
    HANDLES_NEEDED: ClassVar[int] = 2
    LABEL: ClassVar[str] = "assistant"
    SNAP_RADIUS: ClassVar[float] = 40.0   # image pixels

    id: str = field(default_factory=lambda: str(uuid4()))
    handles: list[QPointF] = field(default_factory=list)
    active: bool = True
    color: QColor = field(default_factory=lambda: QColor(80, 160, 255, 180))

    def is_complete(self) -> bool:
        return len(self.handles) >= self.HANDLES_NEEDED

    def snap_point(self, point: QPointF) -> QPointF | None:
        """Return snapped position or None if not applicable."""
        return None

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        """Paint the overlay.  *to_screen(QPointF) → QPointF*."""
        pass

    def _screen_handles(self, to_screen) -> list[QPointF]:
        return [to_screen(h) for h in self.handles]

    def _draw_handle(self, p: QPainter, pos: QPointF, fill: QColor | None = None) -> None:
        p.setPen(QPen(Qt.GlobalColor.white, 1.5))
        p.setBrush(fill or self.color)
        p.drawEllipse(pos, 5, 5)

    def _pen(self, alpha: int = 180) -> QPen:
        c = QColor(self.color)
        c.setAlpha(alpha)
        return QPen(c, 1.2)


# ─────────────────────────────────────────────────────────────────────────────
# Ruler assistant
# ─────────────────────────────────────────────────────────────────────────────

class RulerAssistant(_Assistant):
    HANDLES_NEEDED = 2
    LABEL = "ruler"

    def snap_point(self, point: QPointF) -> QPointF | None:
        if len(self.handles) < 2:
            return None
        snapped = _snap_to_line(point, self.handles[0], self.handles[1])
        if _dist(point, snapped) <= self.SNAP_RADIUS:
            return snapped
        return None

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        if len(self.handles) < 2:
            return
        from PySide6.QtCore import Qt
        sh = self._screen_handles(to_screen)
        # Draw an extended line far beyond the handles
        dx = sh[1].x() - sh[0].x()
        dy = sh[1].y() - sh[0].y()
        length = math.hypot(dx, dy) or 1
        scale = 5000 / length
        far0 = QPointF(sh[0].x() - dx * scale, sh[0].y() - dy * scale)
        far1 = QPointF(sh[1].x() + dx * scale, sh[1].y() + dy * scale)
        p.setPen(self._pen())
        p.drawLine(far0, far1)
        for h in sh:
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# Parallel ruler
# ─────────────────────────────────────────────────────────────────────────────

class ParallelRulerAssistant(_Assistant):
    HANDLES_NEEDED = 2
    LABEL = "parallel_ruler"

    def snap_point(self, point: QPointF) -> QPointF | None:
        if len(self.handles) < 2:
            return None
        # Snap to infinite line through *point* parallel to handle vector
        dx = self.handles[1].x() - self.handles[0].x()
        dy = self.handles[1].y() - self.handles[0].y()
        parallel_end = QPointF(point.x() + dx, point.y() + dy)
        snapped = _snap_to_line(point, point, parallel_end)
        # Always snap (no radius limit for parallel ruler)
        return QPointF(point)  # direction snap: just return as-is and let caller constrain

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        if len(self.handles) < 2:
            return
        sh = self._screen_handles(to_screen)
        p.setPen(self._pen(120))
        dx = sh[1].x() - sh[0].x()
        dy = sh[1].y() - sh[0].y()
        for offset in range(-10, 11):
            ox, oy = offset * 40 * dy / (math.hypot(dx, dy) or 1), offset * 40 * (-dx) / (math.hypot(dx, dy) or 1)
            scale = 5000 / (math.hypot(dx, dy) or 1)
            p0 = QPointF(sh[0].x() + ox - dx * scale, sh[0].y() + oy - dy * scale)
            p1 = QPointF(sh[0].x() + ox + dx * scale, sh[0].y() + oy + dy * scale)
            p.drawLine(p0, p1)
        for h in sh:
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# Ellipse assistant
# ─────────────────────────────────────────────────────────────────────────────

class EllipseAssistant(_Assistant):
    HANDLES_NEEDED = 3
    LABEL = "ellipse"

    def _params(self):
        """Return (center, rx, ry, angle) or None."""
        if len(self.handles) < 3:
            return None
        c = self.handles[0]
        r1 = self.handles[1]
        r2 = self.handles[2]
        rx = _dist(c, r1)
        # Project r2 perpendicular to the r1 axis
        dx1, dy1 = r1.x() - c.x(), r1.y() - c.y()
        angle = math.atan2(dy1, dx1)
        # ry = distance from center to r2, projected onto perpendicular axis
        perp_x, perp_y = -dy1, dx1
        plen = math.hypot(perp_x, perp_y) or 1
        perp_x /= plen; perp_y /= plen
        ry_vec_x, ry_vec_y = r2.x() - c.x(), r2.y() - c.y()
        ry = abs(ry_vec_x * perp_x + ry_vec_y * perp_y)
        return c, rx, ry, angle

    def snap_point(self, point: QPointF) -> QPointF | None:
        params = self._params()
        if params is None:
            return None
        c, rx, ry, angle = params
        snapped = _snap_to_ellipse(point, c, rx, ry, angle)
        if _dist(point, snapped) <= self.SNAP_RADIUS:
            return snapped
        return None

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        params = self._params()
        if params is None:
            if self.handles:
                sh = self._screen_handles(to_screen)
                for h in sh:
                    self._draw_handle(p, h)
            return
        c, rx, ry, angle = params
        sc = to_screen(c)
        # Draw ellipse by sampling
        path = QPainterPath()
        N = 120
        for i in range(N + 1):
            theta = 2 * math.pi * i / N
            ex = rx * math.cos(theta)
            ey = ry * math.sin(theta)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            ix = c.x() + cos_a * ex - sin_a * ey
            iy = c.y() + sin_a * ex + cos_a * ey
            sp = to_screen(QPointF(ix, iy))
            if i == 0:
                path.moveTo(sp)
            else:
                path.lineTo(sp)
        path.closeSubpath()
        p.setPen(self._pen())
        p.setBrush(QBrush())
        p.drawPath(path)
        for h in self._screen_handles(to_screen):
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# 1-point perspective
# ─────────────────────────────────────────────────────────────────────────────

class Perspective1PtAssistant(_Assistant):
    HANDLES_NEEDED = 3   # VP, left-horizon, right-horizon
    LABEL = "perspective_1pt"

    def snap_point(self, point: QPointF) -> QPointF | None:
        if len(self.handles) < 1:
            return None
        vp = self.handles[0]
        # Snap to the line from VP through point
        snapped = _snap_to_line(point, vp, point)
        return snapped   # always on the VP ray

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        if not self.handles:
            return
        sh = self._screen_handles(to_screen)
        vp = sh[0]
        p.setPen(self._pen(100))
        # Draw rays from VP in various directions
        for angle_deg in range(0, 360, 15):
            rad = math.radians(angle_deg)
            far = QPointF(vp.x() + math.cos(rad) * 4000,
                          vp.y() + math.sin(rad) * 4000)
            p.drawLine(vp, far)
        # Horizon line (handles 1–2)
        if len(sh) >= 3:
            p.setPen(self._pen(200))
            scale = 5000
            dx = sh[2].x() - sh[1].x()
            dy = sh[2].y() - sh[1].y()
            ln = math.hypot(dx, dy) or 1
            far0 = QPointF(sh[1].x() - dx / ln * scale, sh[1].y() - dy / ln * scale)
            far1 = QPointF(sh[2].x() + dx / ln * scale, sh[2].y() + dy / ln * scale)
            p.drawLine(far0, far1)
        for h in sh:
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# 2-point perspective
# ─────────────────────────────────────────────────────────────────────────────

class Perspective2PtAssistant(_Assistant):
    HANDLES_NEEDED = 3   # VP-left, VP-right, vertical-guide
    LABEL = "perspective_2pt"

    def snap_point(self, point: QPointF) -> QPointF | None:
        if len(self.handles) < 2:
            return None
        vp_l, vp_r = self.handles[0], self.handles[1]
        # Pick the VP whose ray is closer to the point
        sl = _snap_to_line(point, vp_l, point)
        sr = _snap_to_line(point, vp_r, point)
        dl = _dist(point, sl)
        dr = _dist(point, sr)
        snapped = sl if dl < dr else sr
        if min(dl, dr) <= self.SNAP_RADIUS:
            return snapped
        return None

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        if len(self.handles) < 2:
            return
        sh = self._screen_handles(to_screen)
        vp_l, vp_r = sh[0], sh[1]
        p.setPen(self._pen(90))
        for vp in (vp_l, vp_r):
            for angle_deg in range(0, 180, 10):
                rad = math.radians(angle_deg)
                far = QPointF(vp.x() + math.cos(rad) * 4000,
                              vp.y() + math.sin(rad) * 4000)
                far2 = QPointF(vp.x() - math.cos(rad) * 4000,
                               vp.y() - math.sin(rad) * 4000)
                p.drawLine(far2, far)
        # Horizon
        p.setPen(self._pen(200))
        dx = vp_r.x() - vp_l.x()
        dy = vp_r.y() - vp_l.y()
        ln = math.hypot(dx, dy) or 1
        far0 = QPointF(vp_l.x() - dx / ln * 5000, vp_l.y() - dy / ln * 5000)
        far1 = QPointF(vp_r.x() + dx / ln * 5000, vp_r.y() + dy / ln * 5000)
        p.drawLine(far0, far1)
        for h in sh:
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# Concentric circles
# ─────────────────────────────────────────────────────────────────────────────

class ConcentricAssistant(_Assistant):
    HANDLES_NEEDED = 2
    LABEL = "concentric"

    def snap_point(self, point: QPointF) -> QPointF | None:
        if len(self.handles) < 2:
            return None
        c = self.handles[0]
        r_ref = _dist(c, self.handles[1])
        d = _dist(c, point)
        if d < 0.1:
            return None
        # Snap to nearest integer multiple of r_ref
        if r_ref < 0.1:
            return None
        n = max(1, round(d / r_ref))
        r_snap = n * r_ref
        dx, dy = point.x() - c.x(), point.y() - c.y()
        scale = r_snap / d
        snapped = QPointF(c.x() + dx * scale, c.y() + dy * scale)
        if abs(d - r_snap) <= self.SNAP_RADIUS:
            return snapped
        return None

    def draw_overlay(self, p: QPainter, to_screen) -> None:
        if len(self.handles) < 2:
            return
        sh = self._screen_handles(to_screen)
        sc, sr = sh[0], sh[1]
        r_screen = _dist(sc, sr)
        if r_screen < 0.1:
            return
        p.setPen(self._pen(130))
        for n in range(1, 20):
            r = r_screen * n
            p.drawEllipse(sc, r, r)
        for h in sh:
            self._draw_handle(p, h)


# ─────────────────────────────────────────────────────────────────────────────
# Assistant manager
# ─────────────────────────────────────────────────────────────────────────────

_ASSISTANT_TYPES: dict[str, type] = {
    "ruler": RulerAssistant,
    "parallel_ruler": ParallelRulerAssistant,
    "ellipse": EllipseAssistant,
    "perspective_1pt": Perspective1PtAssistant,
    "perspective_2pt": Perspective2PtAssistant,
    "concentric": ConcentricAssistant,
}


class AssistantManager:
    """Owns all active assistants and handles editing + snapping."""

    SNAP_RADIUS_PX: float = 30.0   # screen pixels for handle hit-test

    def __init__(self) -> None:
        self._assistants: list[_Assistant] = []
        self._editing: _Assistant | None = None
        self._drag_handle_idx: int = -1
        self._building: _Assistant | None = None
        self.snap_enabled: bool = True
        self.assistant_mode: bool = False   # True = handle editing, False = drawing

    # ── assistant lifecycle ───────────────────────────────────────────────────

    def add(self, kind: str) -> _Assistant | None:
        cls = _ASSISTANT_TYPES.get(kind)
        if cls is None:
            return None
        a = cls()
        self._assistants.append(a)
        self._building = a
        return a

    def remove(self, assistant_id: str) -> None:
        self._assistants = [a for a in self._assistants if a.id != assistant_id]
        if self._editing and self._editing.id == assistant_id:
            self._editing = None

    def clear(self) -> None:
        self._assistants.clear()
        self._editing = None
        self._building = None

    def assistants(self) -> list[_Assistant]:
        return list(self._assistants)

    # ── point snapping ────────────────────────────────────────────────────────

    def snap_point(self, image_pos: QPointF) -> QPointF:
        """Return the snapped position (image coords).  Falls back to original."""
        if not self.snap_enabled:
            return image_pos
        best = image_pos
        best_dist = self.SNAP_RADIUS_PX * 2
        for a in self._assistants:
            if not a.active or not a.is_complete():
                continue
            snapped = a.snap_point(image_pos)
            if snapped is not None:
                d = _dist(image_pos, snapped)
                if d < best_dist:
                    best_dist = d
                    best = snapped
        return best

    # ── building a new assistant (click to place handles) ────────────────────

    def build_click(self, image_pos: QPointF) -> bool:
        """Add a handle to the assistant being built.  Returns True when done."""
        if self._building is None:
            return True
        self._building.handles.append(QPointF(image_pos))
        if self._building.is_complete():
            self._building = None
            return True
        return False

    def is_building(self) -> bool:
        return self._building is not None

    # ── handle drag (edit mode) ───────────────────────────────────────────────

    def mouse_press_edit(self, image_pos: QPointF, to_image) -> bool:
        """Try to start dragging a handle.  Returns True if handled."""
        for a in self._assistants:
            for i, h in enumerate(a.handles):
                if _dist(image_pos, h) <= self.SNAP_RADIUS_PX:
                    self._editing = a
                    self._drag_handle_idx = i
                    return True
        return False

    def mouse_move_edit(self, image_pos: QPointF) -> None:
        if self._editing is not None and self._drag_handle_idx >= 0:
            self._editing.handles[self._drag_handle_idx] = QPointF(image_pos)

    def mouse_release_edit(self) -> None:
        self._editing = None
        self._drag_handle_idx = -1

    # ── overlay drawing ───────────────────────────────────────────────────────

    def draw_overlay(self, painter: QPainter, to_screen) -> None:
        """Paint all active assistants.  *to_screen(QPointF) → QPointF*."""
        for a in self._assistants:
            if a.active:
                a.draw_overlay(painter, to_screen)
        # If building, draw pending handles
        if self._building and self._building.handles:
            for h in self._building.handles:
                sh = to_screen(h)
                painter.setPen(QPen(QColor(255, 200, 60, 200), 1.5))
                painter.setBrush(QColor(255, 200, 60, 160))
                painter.drawEllipse(sh, 6, 6)

    # ── serialise / deserialise ───────────────────────────────────────────────

    def to_dict(self) -> list[dict]:
        result = []
        for a in self._assistants:
            result.append({
                "kind": a.LABEL,
                "id": a.id,
                "active": a.active,
                "handles": [[h.x(), h.y()] for h in a.handles],
            })
        return result

    def from_dict(self, data: list[dict]) -> None:
        self.clear()
        for d in data:
            cls = _ASSISTANT_TYPES.get(d.get("kind", ""))
            if cls is None:
                continue
            a = cls()
            a.id = d.get("id", a.id)
            a.active = d.get("active", True)
            a.handles = [QPointF(x, y) for x, y in d.get("handles", [])]
            self._assistants.append(a)


__all__ = [
    "AssistantManager",
    "RulerAssistant", "EllipseAssistant", "ParallelRulerAssistant",
    "Perspective1PtAssistant", "Perspective2PtAssistant",
    "ConcentricAssistant",
]
