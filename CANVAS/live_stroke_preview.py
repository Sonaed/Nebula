"""Trait d'aperçu instantané (anti-latence) — refonte UX 2026-09.

Le vrai trait passe par le stabilisateur puis, pour les presets complexes, par
le worker C++ asynchrone : les pixels définitifs arrivent quelques frames après
le stylet. Cet aperçu dessine la « queue » récente du geste (positions brutes,
avant lissage) par-dessus le canvas, à la couleur et à la taille du pinceau.
Les pixels réels la rattrapent en dessous ; le trait reste collé au stylet.

Aucun pixel du document n'est modifié : c'est un simple overlay Qt.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

TAIL_SECONDS = 0.16      # durée de la queue affichée (fenêtre de latence typique)
LINGER_SECONDS = 0.28    # après le lever du stylet, le temps que le worker finisse
MAX_POINTS = 256


class LiveStrokePreview:
    def __init__(self, canvas):
        self.canvas = canvas
        self.points: list[tuple[QPointF, float, float]] = []
        self.active = False
        self.released_at = None
        self.style = None
        self.enabled = QSettings("CreativeSystem", "CreativeSystem").value("brush/live_preview", True, bool)

    # ── entrées ──
    def press(self, position, pressure: float = 1.0) -> None:
        self.points.clear()
        self.released_at = None
        self.active = bool(self.enabled and getattr(self.canvas.tools, "current_tool", "") == "brush")
        if not self.active:
            return
        try:
            settings = self.canvas.get_cpp_brush_settings()
            red, green, blue, alpha = settings.get("color", (0, 0, 0, 255))
            self.style = {
                "size": float(settings.get("size", 10.0)),
                "opacity": float(settings.get("opacity", 1.0)) * (alpha / 255.0),
                "pressure_size": bool(settings.get("pressureSize", True)),
                "minimum": float(settings.get("minimumSize", 0.05)),
                "color": (int(red), int(green), int(blue)),
            }
        except Exception:  # noqa: BLE001 — l'aperçu ne doit jamais gêner le dessin
            self.active = False
            return
        self.points.append((QPointF(position), float(pressure), time.monotonic()))

    def move(self, position, pressure: float = 1.0) -> None:
        if not self.active:
            return
        self.points.append((QPointF(position), float(pressure), time.monotonic()))
        if len(self.points) > MAX_POINTS:
            del self.points[:-MAX_POINTS]

    def release(self) -> None:
        if not self.active:
            return
        self.active = False
        self.released_at = time.monotonic()
        # repeints pour effacer proprement la queue quand le vrai trait est posé
        for delay in (90, 180, int(LINGER_SECONDS * 1000) + 20):
            QTimer.singleShot(delay, self.canvas.update)

    # ── rendu ──
    def _latency_expected(self) -> bool:
        """N'afficher l'aperçu que lorsqu'un décalage existe réellement."""
        canvas = self.canvas
        pending = getattr(canvas, "_async_stroke_pending", 0) > 0
        smoothing = float(getattr(getattr(canvas.tools, "brush", None), "smoothing", 0.0) or 0.0)
        return pending or smoothing > 0.0

    def paint(self, painter: QPainter) -> None:
        if not self.points or self.style is None:
            return
        now = time.monotonic()
        if self.released_at is not None:
            if now - self.released_at > LINGER_SECONDS:
                self.points.clear()
                return
            horizon = self.released_at - TAIL_SECONDS
        elif self.active and getattr(self.canvas, "drawing", False):
            horizon = now - TAIL_SECONDS
        else:
            return
        if not self._latency_expected() and self.released_at is None:
            return
        recent = [p for p in self.points if p[2] >= horizon]
        # garder un point antérieur pour que la queue se raccorde au trait posé
        older = [p for p in self.points if p[2] < horizon]
        if older:
            recent.insert(0, older[-1])
        if len(recent) < 2:
            return
        style = self.style
        zoom = float(getattr(self.canvas, "zoom", 1.0) or 1.0)
        pressure = recent[-1][1]
        scale = max(style["minimum"], pressure) if style["pressure_size"] else 1.0
        width = max(1.0, style["size"] * zoom * scale)
        color = QColor(*style["color"])
        fade = 1.0
        if self.released_at is not None:
            fade = max(0.0, 1.0 - (now - self.released_at) / LINGER_SECONDS)
        color.setAlphaF(max(0.0, min(1.0, style["opacity"] * 0.85 * fade)))
        path = QPainterPath(recent[0][0])
        for point, _p, _t in recent[1:]:
            path.lineTo(point)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()


__all__ = ["LiveStrokePreview"]
