"""Navigator: a live overview of the whole image with the visible area framed.

Click or drag in it to move the view, use the slider (or the wheel over the
overview) to zoom.  It refreshes after every edit and view change, throttled
so it never competes with painting.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from UI.theme.palette import COLORS


class _Overview(QWidget):
    def __init__(self, dock: "NavigatorDock") -> None:
        super().__init__(dock)
        self.dock = dock
        self.setMinimumSize(180, 120)
        self.setMouseTracking(True)
        self._thumbnail = QImage()
        self._dragging = False

    def set_thumbnail(self, image: QImage) -> None:
        self._thumbnail = image
        self.update()

    def _image_rect(self) -> QRectF:
        canvas = self.dock.canvas
        document = getattr(canvas, "document", None)
        if document is None or document.width <= 0 or document.height <= 0:
            return QRectF()
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        scale = min(area.width() / document.width, area.height() / document.height)
        width, height = document.width * scale, document.height * scale
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(COLORS["window"]))
        target = self._image_rect()
        if target.isEmpty():
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucun document")
            return
        painter.fillRect(target, QColor(COLORS["checker_light"]))
        if not self._thumbnail.isNull():
            painter.drawImage(target, self._thumbnail)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.drawRect(target)
        # Visible area (a polygon: the view can be rotated or mirrored).
        canvas = self.dock.canvas
        document = canvas.document
        scale = target.width() / document.width
        corners = [canvas.screen_to_image_f(QPointF(x, y)) for x, y in
                   ((0, 0), (canvas.width(), 0), (canvas.width(), canvas.height()), (0, canvas.height()))]
        polygon = QPolygonF([QPointF(target.left() + c.x() * scale, target.top() + c.y() * scale)
                             for c in corners])
        painter.setClipRect(QRectF(self.rect()))
        painter.setPen(QPen(QColor(COLORS["accent"]), 2))
        fill = QColor(COLORS["accent"])
        fill.setAlpha(28)
        painter.setBrush(fill)
        painter.drawPolygon(polygon)

    def _centre_view_at(self, position: QPointF) -> None:
        target = self._image_rect()
        if target.isEmpty():
            return
        canvas = self.dock.canvas
        scale = target.width() / canvas.document.width
        point = QPointF((position.x() - target.left()) / scale, (position.y() - target.top()) / scale)
        centre = QPointF(canvas.width() / 2, canvas.height() / 2)
        canvas.offset = centre - point * canvas.zoom
        canvas.update()
        self.dock.schedule(view_only=True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._centre_view_at(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._centre_view_at(event.position())

    def mouseReleaseEvent(self, _event) -> None:
        self._dragging = False

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.dock.zoom_by(1.15 ** steps)


class NavigatorDock(QDockWidget):
    MIN_ZOOM, MAX_ZOOM = 0.02, 32.0

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Navigateur", parent)
        self.setObjectName("NavigatorDock")
        self.canvas = canvas
        content = QWidget()
        content.setObjectName("dockContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.overview = _Overview(self)
        layout.addWidget(self.overview, 1)
        row = QHBoxLayout()
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setToolTip("Zoom")
        self.zoom_slider.valueChanged.connect(self._slider_changed)
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setObjectName("fieldCaption")
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.zoom_slider, 1)
        row.addWidget(self.zoom_label)
        layout.addLayout(row)
        self.setWidget(content)

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(350)
        self._thumb_timer.timeout.connect(self._refresh_thumbnail)
        self._view_timer = QTimer(self)
        self._view_timer.setInterval(120)     # follows pan / zoom / rotation
        self._view_timer.timeout.connect(self._poll_view)
        self._last_view = None
        if hasattr(canvas, "history_changed"):
            canvas.history_changed.connect(lambda: self.schedule())
        self.visibilityChanged.connect(self._visibility_changed)

    # ── zoom ────────────────────────────────────────────────────────────────

    def _zoom_to_slider(self, zoom: float) -> int:
        span = math.log(self.MAX_ZOOM / self.MIN_ZOOM)
        return round(1000 * math.log(max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom)) / self.MIN_ZOOM) / span)

    def _slider_changed(self, value: int) -> None:
        if getattr(self, "_syncing", False):
            return
        zoom = self.MIN_ZOOM * math.exp(value / 1000 * math.log(self.MAX_ZOOM / self.MIN_ZOOM))
        self.set_zoom(zoom)

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.canvas.zoom * factor)

    def set_zoom(self, zoom: float) -> None:
        """Zoom around the centre of the view (like the canvas shortcuts)."""
        canvas = self.canvas
        if getattr(canvas, "document", None) is None:
            return
        zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        centre = QPointF(canvas.width() / 2, canvas.height() / 2)
        anchor = canvas.screen_to_image_f(centre)
        canvas.zoom = zoom
        canvas.offset = centre - anchor * zoom
        canvas.update()
        self._poll_view()

    # ── refresh ─────────────────────────────────────────────────────────────

    def _visibility_changed(self, visible: bool) -> None:
        if visible:
            self._view_timer.start()
            self.schedule()
        else:
            self._view_timer.stop()

    def schedule(self, view_only: bool = False) -> None:
        if not self.isVisible():
            return
        if view_only:
            self.overview.update()
        else:
            self._thumb_timer.start()

    def _poll_view(self) -> None:
        canvas = self.canvas
        state = (round(canvas.zoom, 4), round(canvas.offset.x(), 1), round(canvas.offset.y(), 1),
                 getattr(canvas, "view_rotation", 0.0), canvas.width(), canvas.height(),
                 id(getattr(canvas, "document", None)))
        if state != self._last_view:
            if self._last_view is None or state[-1] != self._last_view[-1]:
                self._thumb_timer.start()
            self._last_view = state
            self._syncing = True
            self.zoom_slider.setValue(self._zoom_to_slider(canvas.zoom))
            self._syncing = False
            self.zoom_label.setText(f"{canvas.zoom * 100:.0f} %")
            self.overview.update()

    def _refresh_thumbnail(self) -> None:
        document = getattr(self.canvas, "document", None)
        if document is None or not self.isVisible():
            self.overview.set_thumbnail(QImage())
            return
        from DOCUMENTS.blend_modes import composite_preview
        # Reduced composite: a full-size render froze painting for seconds on
        # big canvases every time the thumbnail refreshed.
        side = max(64, min(1024, max(self.overview.width(), self.overview.height()) * 2))
        self.overview.set_thumbnail(composite_preview(document, side))


__all__ = ["NavigatorDock"]
