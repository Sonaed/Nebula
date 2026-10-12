"""Édition ▸ Courbe de pression… — edit the global stylus response."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTabletEvent
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from TOOLS.pressure_curve import PRESETS, PressureCurve
from UI.theme.palette import COLORS


class PressureCurveEditor(QWidget):
    """Square graph: drag points, double-click to add, right-click to remove."""

    curveChanged = Signal()

    MARGIN = 14
    HIT = 9

    def __init__(self, curve: PressureCurve, parent=None) -> None:
        super().__init__(parent)
        self.curve = curve
        self.setMinimumSize(280, 280)
        self.setMouseTracking(True)
        self._drag: int | None = None
        self._probe: float | None = None   # live pen pressure shown on the curve

    # ── geometry ────────────────────────────────────────────────────────────

    def _area(self) -> QRectF:
        side = min(self.width(), self.height()) - 2 * self.MARGIN
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def _to_screen(self, x: float, y: float) -> QPointF:
        area = self._area()
        return QPointF(area.left() + x * area.width(), area.bottom() - y * area.height())

    def _to_curve(self, point: QPointF) -> tuple[float, float]:
        area = self._area()
        x = (point.x() - area.left()) / max(1.0, area.width())
        y = (area.bottom() - point.y()) / max(1.0, area.height())
        return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

    def _hit(self, point: QPointF) -> int | None:
        for index, (x, y) in enumerate(self.curve.points):
            screen = self._to_screen(x, y)
            if abs(screen.x() - point.x()) <= self.HIT and abs(screen.y() - point.y()) <= self.HIT:
                return index
        return None

    def set_probe(self, pressure: float | None) -> None:
        self._probe = pressure
        self.update()

    # ── painting ────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        painter.fillRect(area, QColor(COLORS["input_bg"]))
        grid = QPen(QColor(COLORS["border_soft"]), 1)
        painter.setPen(grid)
        for step in range(1, 4):
            x = area.left() + area.width() * step / 4
            y = area.top() + area.height() * step / 4
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.PenStyle.DashLine))
        painter.drawLine(area.bottomLeft(), area.topRight())
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawRect(area)

        path = QPainterPath()
        for i in range(101):
            point = self._to_screen(i / 100, self.curve.map(i / 100))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        painter.setPen(QPen(QColor(COLORS["accent"]), 2.2))
        painter.drawPath(path)

        for x, y in self.curve.points:
            painter.setPen(QPen(QColor(COLORS["accent"]), 2))
            painter.setBrush(QColor(COLORS["panel"]))
            painter.drawEllipse(self._to_screen(x, y), 5.5, 5.5)

        if self._probe is not None:
            out = self.curve.map(self._probe)
            point = self._to_screen(self._probe, out)
            painter.setPen(QPen(QColor(COLORS["text_muted"]), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(point.x(), area.bottom()), point)
            painter.drawLine(QPointF(area.left(), point.y()), point)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["text"]))
            painter.drawEllipse(point, 4, 4)

        painter.setPen(QColor(COLORS["text_muted"]))
        painter.drawText(QRectF(area.left(), area.bottom() + 1, area.width(), self.MARGIN),
                         Qt.AlignmentFlag.AlignCenter, "pression du stylet")

    # ── interaction ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        index = self._hit(event.position())
        if event.button() == Qt.MouseButton.RightButton:
            if index is not None and 0 < index < len(self.curve.points) - 1:
                points = list(self.curve.points)
                del points[index]
                self.curve.set_points(points)
                self.curveChanged.emit()
                self.update()
            return
        self._drag = index

    def mouseDoubleClickEvent(self, event) -> None:
        if self._hit(event.position()) is None:
            self.curve.set_points([*self.curve.points, self._to_curve(event.position())])
            self.curveChanged.emit()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self._hit(event.position()) is not None
                           else Qt.CursorShape.ArrowCursor)
            return
        points = list(self.curve.points)
        x, y = self._to_curve(event.position())
        if self._drag == 0:
            x = 0.0
        elif self._drag == len(points) - 1:
            x = 1.0
        else:  # keep points ordered, never on top of a neighbour
            x = min(points[self._drag + 1][0] - 0.02, max(points[self._drag - 1][0] + 0.02, x))
        points[self._drag] = (x, y)
        self.curve.set_points(points)
        self.curveChanged.emit()
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None


class _TestPad(QWidget):
    """Draw here with the pen: shows raw → curved pressure live."""

    pressureProbed = Signal(object)

    def __init__(self, curve: PressureCurve, parent=None) -> None:
        super().__init__(parent)
        self.curve = curve
        self.setMinimumHeight(110)
        self._strokes: list[list[tuple[QPointF, float]]] = []

    def tabletEvent(self, event: QTabletEvent) -> None:
        kind = event.type()
        sample = (event.position(), float(event.pressure()))
        if kind == QTabletEvent.Type.TabletPress:
            self._strokes.append([sample])
        elif kind == QTabletEvent.Type.TabletMove and self._strokes and event.buttons():
            self._strokes[-1].append(sample)
        self.pressureProbed.emit(None if kind == QTabletEvent.Type.TabletRelease else sample[1])
        self.update()
        event.accept()

    def clear(self) -> None:
        self._strokes.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["checker_light"]))
        if not self._strokes:
            painter.setPen(QColor(COLORS["checker_dark"]).darker(160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Essayez votre stylet ici")
            return
        for stroke in self._strokes:
            for (a, pa), (b, pb) in zip(stroke, stroke[1:]):
                width = 1.0 + 16.0 * self.curve.map((pa + pb) / 2)
                painter.setPen(QPen(QColor(30, 30, 34), width, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)


class PressureCurveDialog(QDialog):
    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Courbe de pression")
        self.canvas = canvas
        self._original = PressureCurve(canvas.pressure_curve.points)
        self.curve = PressureCurve(canvas.pressure_curve.points)

        root = QVBoxLayout(self)
        intro = QLabel("Ajustez la réponse du stylet : glissez les points, double-cliquez pour en "
                       "ajouter, clic droit pour en retirer.")
        intro.setWordWrap(True)
        intro.setObjectName("fieldCaption")
        root.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Modèle"))
        self.preset = QComboBox()
        self.preset.addItem("Personnalisée")
        self.preset.addItems(list(PRESETS))
        self.preset.activated.connect(self._apply_preset)
        row.addWidget(self.preset, 1)
        root.addLayout(row)

        self.editor = PressureCurveEditor(self.curve)
        self.editor.curveChanged.connect(self._curve_edited)
        root.addWidget(self.editor, 1)

        self.pad = _TestPad(self.curve)
        self.pad.pressureProbed.connect(self.editor.set_probe)
        root.addWidget(self.pad)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Appliquer")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        clear = QPushButton("Effacer l'essai")
        clear.clicked.connect(self.pad.clear)
        buttons.addButton(clear, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._sync_preset_label()
        self.resize(420, 600)

    def _sync_preset_label(self) -> None:
        for index, points in enumerate(PRESETS.values(), start=1):
            if PressureCurve(points).points == self.curve.points:
                self.preset.setCurrentIndex(index)
                return
        self.preset.setCurrentIndex(0)

    def _apply_preset(self, index: int) -> None:
        if index > 0:
            self.curve.set_points(PRESETS[self.preset.itemText(index)])
            self._curve_edited(sync=False)

    def _curve_edited(self, sync: bool = True) -> None:
        # Live: the canvas uses the curve while the dialog is open.
        self.canvas.pressure_curve.set_points(self.curve.points)
        self.editor.update()
        self.pad.update()
        if sync:
            self._sync_preset_label()

    def accept(self) -> None:
        self.canvas.pressure_curve.set_points(self.curve.points)
        self.canvas.pressure_curve.save(QSettings("CreativeSystem", "CreativeSystem"))
        super().accept()

    def reject(self) -> None:
        self.canvas.pressure_curve.set_points(self._original.points)
        super().reject()


__all__ = ["PressureCurveDialog", "PressureCurveEditor"]
