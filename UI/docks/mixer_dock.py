"""Mélangeur: a painter's palette to mix colours before using them.

Paint with the current colour; the brush picks up what is already on the
palette, so colours mix as they are dragged.  Right-click or Alt+click takes a
colour back as the brush colour.  The palette is kept between sessions.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from UI.theme.palette import COLORS

PAPER = QColor(246, 243, 236)


def _storage_path() -> Path:
    root = os.environ.get("CREATIVE_SYSTEM_DATA_HOME", "").strip()
    base = Path(root) if root else Path.home() / ".local" / "share" / "CreativeSystem"
    return base / "mixer.png"


class MixingSurface(QWidget):
    colorPicked = Signal(QColor)

    SIZE = (640, 420)                 # surface resolution, scaled to the widget

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 130)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.image = QImage(*self.SIZE, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(PAPER)
        self.brush_size = 26.0
        self.wetness = 0.55           # how much the brush picks up from the palette
        self.color_provider = lambda: QColor(0, 0, 0)
        self._load: QColor | None = None
        self._last: QPointF | None = None
        self.restore()

    # ── persistence ─────────────────────────────────────────────────────────
    def restore(self) -> None:
        path = _storage_path()
        if path.is_file():
            stored = QImage(str(path))
            if not stored.isNull():
                painter = QPainter(self.image)
                painter.drawImage(QRectF(self.image.rect()), stored)
                painter.end()

    def save(self) -> None:
        try:
            path = _storage_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.image.save(str(path), "PNG")
        except OSError:
            pass

    def clear(self) -> None:
        self.image.fill(PAPER)
        self.update()
        self.save()

    # ── geometry ────────────────────────────────────────────────────────────
    def _scale(self) -> float:
        return min(self.width() / self.image.width(), self.height() / self.image.height())

    def _to_image(self, point: QPointF) -> QPointF:
        scale = self._scale()
        offset_x = (self.width() - self.image.width() * scale) / 2
        offset_y = (self.height() - self.image.height() * scale) / 2
        return QPointF((point.x() - offset_x) / scale, (point.y() - offset_y) / scale)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS["window"]))
        scale = self._scale()
        width, height = self.image.width() * scale, self.image.height() * scale
        target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self.image)

    # ── painting ────────────────────────────────────────────────────────────
    def _sample(self, point: QPointF, radius: int) -> QColor:
        x0, y0 = int(point.x()), int(point.y())
        total = [0.0, 0.0, 0.0]
        count = 0
        step = max(1, radius // 4)
        for dy in range(-radius, radius + 1, step):
            for dx in range(-radius, radius + 1, step):
                x, y = x0 + dx, y0 + dy
                if dx * dx + dy * dy > radius * radius or not self.image.rect().contains(x, y):
                    continue
                c = self.image.pixelColor(x, y)
                total[0] += c.redF(); total[1] += c.greenF(); total[2] += c.blueF()
                count += 1
        if not count:
            return QColor(PAPER)
        return QColor.fromRgbF(total[0] / count, total[1] / count, total[2] / count)

    @staticmethod
    def _mix(a: QColor, b: QColor, amount: float) -> QColor:
        return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                               a.greenF() + (b.greenF() - a.greenF()) * amount,
                               a.blueF() + (b.blueF() - a.blueF()) * amount)

    def _dab(self, point: QPointF) -> None:
        radius = self.brush_size / 2
        under = self._sample(point, max(1, int(radius * 0.6)))
        # The brush load picks up the palette and slowly returns to fresh paint.
        self._load = self._mix(self._load, under, self.wetness * 0.35)
        self._load = self._mix(self._load, self.color_provider(), 0.04)
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QRadialGradient(point, radius)
        solid = QColor(self._load); solid.setAlphaF(0.85)
        edge = QColor(self._load); edge.setAlphaF(0.0)
        gradient.setColorAt(0.0, solid)
        gradient.setColorAt(0.6, solid)
        gradient.setColorAt(1.0, edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(point, radius, radius)
        painter.end()

    def _stroke_to(self, point: QPointF) -> None:
        if self._last is None:
            self._dab(point)
        else:
            distance = math.hypot(point.x() - self._last.x(), point.y() - self._last.y())
            steps = max(1, int(distance / max(1.0, self.brush_size * 0.12)))
            for i in range(1, steps + 1):
                t = i / steps
                self._dab(QPointF(self._last.x() + (point.x() - self._last.x()) * t,
                                  self._last.y() + (point.y() - self._last.y()) * t))
        self._last = point
        self.update()

    def _pick(self, point: QPointF) -> None:
        if self.image.rect().contains(int(point.x()), int(point.y())):
            self.colorPicked.emit(self._sample(point, 3))

    def mousePressEvent(self, event) -> None:
        point = self._to_image(event.position())
        if event.button() == Qt.MouseButton.RightButton or event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._pick(point)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._load = QColor(self.color_provider())
            self._last = None
            self._stroke_to(point)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._load is not None:
            self._stroke_to(self._to_image(event.position()))

    def mouseReleaseEvent(self, _event) -> None:
        if self._load is not None:
            self._load = None
            self._last = None
            self.save()

    def tabletEvent(self, event) -> None:
        # Pen input arrives as synthetic mouse events too; let Qt deliver those.
        event.ignore()


class MixerDock(QDockWidget):
    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Mélangeur", parent)
        self.setObjectName("MixerDock")
        self.canvas = canvas
        content = QWidget()
        content.setObjectName("dockContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.surface = MixingSurface()
        self.surface.color_provider = self._brush_color
        self.surface.colorPicked.connect(self._use_color)
        layout.addWidget(self.surface, 1)
        row = QHBoxLayout()
        caption = QLabel("Taille")
        caption.setObjectName("fieldCaption")
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(4, 120)
        self.size_slider.setValue(int(self.surface.brush_size))
        self.size_slider.valueChanged.connect(lambda v: setattr(self.surface, "brush_size", float(v)))
        clear = QToolButton()
        clear.setText("Effacer")
        clear.setAutoRaise(True)
        clear.setToolTip("Vider la palette de mélange")
        clear.clicked.connect(self.surface.clear)
        row.addWidget(caption)
        row.addWidget(self.size_slider, 1)
        row.addWidget(clear)
        layout.addLayout(row)
        hint = QLabel("Peindre pour mélanger · clic droit ou Alt + clic : prendre la couleur")
        hint.setObjectName("fieldCaption")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.setWidget(content)

    def _brush_color(self) -> QColor:
        rgba = self.canvas.get_cpp_brush_settings().get("color", [0, 0, 0, 255])
        return QColor(*rgba[:3])

    def _use_color(self, color: QColor) -> None:
        self.canvas.set_brush_setting("color", [color.red(), color.green(), color.blue(), 255])


__all__ = ["MixerDock", "MixingSurface"]
