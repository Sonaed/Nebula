from __future__ import annotations

from math import atan2, degrees, hypot

from PySide6.QtCore import QPointF, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class ColorWheel(QWidget):
    """Cached HSV hue wheel with an interactive saturation/value field."""

    colorChanged = Signal(QColor)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(150, 150)
        self.setMaximumHeight(230)
        self._hue, self._saturation, self._value = 0.0, 0.0, 0.0
        self._cache: QPixmap | None = None
        self._drag_zone = ""

    def color(self) -> QColor:
        return QColor.fromHsvF(self._hue, self._saturation, self._value)

    def setColor(self, color: QColor) -> None:
        hue = color.hsvHueF()
        self._hue = 0.0 if hue < 0.0 else hue
        self._saturation = color.hsvSaturationF()
        self._value = color.valueF()
        self._cache = None
        self.update()

    def _geometry(self):
        side = min(self.width(), self.height()) - 10
        wheel = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        field_side = side * 0.52
        field = QRectF(wheel.center().x() - field_side / 2, wheel.center().y() - field_side / 2, field_side, field_side)
        return wheel, field

    def _render_cache(self) -> None:
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        wheel, field = self._geometry()
        hue = QConicalGradient(wheel.center(), 0)
        for step in range(13):
            hue.setColorAt(step / 12, QColor.fromHsvF(step / 12, 1.0, 1.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hue)
        painter.drawEllipse(wheel)
        inner = wheel.adjusted(wheel.width() * .12, wheel.height() * .12, -wheel.width() * .12, -wheel.height() * .12)
        painter.setBrush(QColor("#222326"))
        painter.drawEllipse(inner)
        saturation = QLinearGradient(field.topLeft(), field.topRight())
        saturation.setColorAt(0, QColor(255, 255, 255))
        saturation.setColorAt(1, QColor.fromHsvF(self._hue, 1.0, 1.0))
        painter.fillRect(field, saturation)
        value = QLinearGradient(field.topLeft(), field.bottomLeft())
        value.setColorAt(0, QColor(0, 0, 0, 0))
        value.setColorAt(1, QColor(0, 0, 0, 255))
        painter.fillRect(field, value)
        painter.end()
        self._cache = pixmap

    def paintEvent(self, _event) -> None:
        if self._cache is None or self._cache.size() != self.size():
            self._render_cache()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)
        wheel, field = self._geometry()
        angle = self._hue * 6.283185307
        radius = wheel.width() * .44
        center = wheel.center()
        from math import cos, sin
        hue_point = QPointF(center.x() + cos(angle) * radius, center.y() - sin(angle) * radius)
        sv_point = QPointF(field.left() + self._saturation * field.width(), field.top() + (1.0 - self._value) * field.height())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(hue_point, 4, 4)
        painter.setPen(QPen(QColor("black") if self._value > .6 else QColor("white"), 2))
        painter.drawEllipse(sv_point, 4, 4)

    def _pick(self, position: QPointF) -> None:
        wheel, field = self._geometry()
        center = wheel.center()
        distance = hypot(position.x() - center.x(), position.y() - center.y())
        if self._drag_zone == "wheel" or (not self._drag_zone and distance > wheel.width() * .36):
            self._drag_zone = "wheel"
            angle = degrees(atan2(center.y() - position.y(), position.x() - center.x())) % 360
            self._hue = angle / 360.0
            self._cache = None
        else:
            self._drag_zone = "field"
            self._saturation = max(0.0, min(1.0, (position.x() - field.left()) / field.width()))
            self._value = 1.0 - max(0.0, min(1.0, (position.y() - field.top()) / field.height()))
        self.update()
        self.colorChanged.emit(self.color())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_zone = ""
            self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_zone = ""

    def resizeEvent(self, event) -> None:
        self._cache = None
        super().resizeEvent(event)


__all__ = ["ColorWheel"]
