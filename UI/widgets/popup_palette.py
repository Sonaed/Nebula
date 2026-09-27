"""Pop-up Palette — Krita-style floating palette on right-click.

Opens centered on the click point.  Provides:
  • Compact HSV color wheel
  • Brush size + opacity sliders
  • Recent-colour strip (up to 16 swatches)
  • Foreground/Background colour swatches
  • Hex input
Closes automatically when the mouse is released outside the widget or Escape
is pressed.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    Qt, QPoint, QPointF, QRect, QRectF, QSize, Signal, QTimer,
)
from PySide6.QtGui import (
    QColor, QConicalGradient, QFont, QFontMetrics, QImage, QKeyEvent,
    QMouseEvent, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
from UI.theme.palette import COLORS

# ─────────────────────────────────────────────────────────────────────────────
# Mini colour wheel (HSV, no external deps)
# ─────────────────────────────────────────────────────────────────────────────

class _MiniWheel(QWidget):
    """Small HSV colour wheel with a triangular/square SV picker inside."""

    colorChanged = Signal(QColor)

    _RING_W = 14        # width of the hue ring in pixels
    _HANDLE_R = 5       # radius of the drag handle

    def __init__(self, size: int = 160, parent=None) -> None:
        super().__init__(parent)
        self._sz = size
        self.setFixedSize(size, size)
        self._hue: float = 0.0          # 0–1
        self._sat: float = 0.8
        self._val: float = 0.9
        self._drag: str | None = None   # "ring" | "sq"
        self._wheel_img: QImage | None = None
        self._sq_img: QImage | None = None
        self._rebuild_wheel()
        self._rebuild_sq()

    # ── colour access ────────────────────────────────────────────────────────

    def color(self) -> QColor:
        return QColor.fromHsvF(self._hue, self._sat, self._val)

    def setColor(self, c: QColor) -> None:
        h, s, v, _ = c.getHsvF()
        if h < 0:
            h = 0.0
        changed = (h != self._hue or s != self._sat or v != self._val)
        self._hue, self._sat, self._val = h, s, v
        if changed:
            self._rebuild_sq()
            self.update()

    # ── painting ─────────────────────────────────────────────────────────────

    def _center(self) -> QPointF:
        return QPointF(self._sz / 2, self._sz / 2)

    def _outer_r(self) -> float:
        return self._sz / 2 - 2

    def _inner_r(self) -> float:
        return self._outer_r() - self._RING_W

    def _rebuild_wheel(self) -> None:
        sz = self._sz
        img = QImage(sz, sz, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        cx, cy = sz / 2, sz / 2
        outer_r = self._outer_r()
        inner_r = self._inner_r()
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for angle_deg in range(360):
            hue = angle_deg / 360.0
            color = QColor.fromHsvF(hue, 1.0, 1.0)
            pen = QPen(color, self._RING_W)
            p.setPen(pen)
            # Draw small arc segment
            path = QPainterPath()
            path.moveTo(cx + outer_r * math.cos(math.radians(-angle_deg)),
                        cy + outer_r * math.sin(math.radians(-angle_deg)))
            path.arcTo(cx - outer_r, cy - outer_r, 2 * outer_r, 2 * outer_r,
                       angle_deg, -1)
            p.drawPath(path)
        p.end()
        self._wheel_img = img

    def _sq_topleft(self) -> QPointF:
        """Top-left corner of the SV square inscribed in the inner circle."""
        r = self._inner_r() * 0.70
        cx, cy = self._sz / 2, self._sz / 2
        return QPointF(cx - r, cy - r)

    def _sq_side(self) -> float:
        return self._inner_r() * 1.40

    def _rebuild_sq(self) -> None:
        side = max(1, int(self._sq_side()))
        img = QImage(side, side, QImage.Format.Format_ARGB32)
        # Fill: rows = value (top bright → bottom dark),
        #        cols = saturation (left white → right full hue)
        hue_color = QColor.fromHsvF(self._hue, 1.0, 1.0)
        for row in range(side):
            v = 1.0 - row / (side - 1) if side > 1 else 1.0
            for col in range(side):
                s = col / (side - 1) if side > 1 else 1.0
                # Blend: white*(1-s) + hue*s, then *v
                r = int((255 * (1 - s) + hue_color.red() * s) * v)
                g = int((255 * (1 - s) + hue_color.green() * s) * v)
                b = int((255 * (1 - s) + hue_color.blue() * s) * v)
                img.setPixelColor(col, row, QColor(r, g, b))
        self._sq_img = img

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self._sz / 2, self._sz / 2

        # Draw hue ring (pre-rendered)
        if self._wheel_img:
            p.drawImage(0, 0, self._wheel_img)

        # Hue ring handle
        angle_rad = -self._hue * 2 * math.pi
        r_mid = (self._outer_r() + self._inner_r()) / 2
        hx = cx + r_mid * math.cos(angle_rad)
        hy = cy + r_mid * math.sin(angle_rad)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.setBrush(QColor.fromHsvF(self._hue, 1.0, 1.0))
        p.drawEllipse(QPointF(hx, hy), self._HANDLE_R, self._HANDLE_R)

        # SV square
        tl = self._sq_topleft()
        side = self._sq_side()
        if self._sq_img:
            p.drawImage(QRect(int(tl.x()), int(tl.y()), int(side), int(side)),
                        self._sq_img)

        # SV handle
        sx = tl.x() + self._sat * side
        sy = tl.y() + (1.0 - self._val) * side
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.setBrush(self.color())
        p.drawEllipse(QPointF(sx, sy), self._HANDLE_R, self._HANDLE_R)

    # ── mouse ─────────────────────────────────────────────────────────────────

    def _point_in_ring(self, pos: QPointF) -> bool:
        cx, cy = self._sz / 2, self._sz / 2
        d = math.hypot(pos.x() - cx, pos.y() - cy)
        return self._inner_r() - 2 <= d <= self._outer_r() + 2

    def _point_in_sq(self, pos: QPointF) -> bool:
        tl = self._sq_topleft()
        side = self._sq_side()
        return (tl.x() <= pos.x() <= tl.x() + side and
                tl.y() <= pos.y() <= tl.y() + side)

    def _update_hue(self, pos: QPointF) -> None:
        cx, cy = self._sz / 2, self._sz / 2
        angle = math.atan2(pos.y() - cy, pos.x() - cx)
        self._hue = (-angle / (2 * math.pi)) % 1.0
        self._rebuild_sq()

    def _update_sv(self, pos: QPointF) -> None:
        tl = self._sq_topleft()
        side = self._sq_side()
        s = max(0.0, min(1.0, (pos.x() - tl.x()) / side))
        v = max(0.0, min(1.0, 1.0 - (pos.y() - tl.y()) / side))
        self._sat, self._val = s, v

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._point_in_ring(pos):
            self._drag = "ring"
            self._update_hue(pos)
            self.update()
            self.colorChanged.emit(self.color())
        elif self._point_in_sq(pos):
            self._drag = "sq"
            self._update_sv(pos)
            self.update()
            self.colorChanged.emit(self.color())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._drag == "ring":
            self._update_hue(pos)
        elif self._drag == "sq":
            self._update_sv(pos)
        else:
            return
        self.update()
        self.colorChanged.emit(self.color())

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag = None


# ─────────────────────────────────────────────────────────────────────────────
# Thin slider (vertical or horizontal, compact)
# ─────────────────────────────────────────────────────────────────────────────

class _TinySlider(QWidget):
    """Tiny labelled slider (0–1 or 0–max_px) used in the pop-up palette."""

    valueChanged = Signal(float)   # always 0–1 normalised

    def __init__(self, label: str, orientation=Qt.Orientation.Horizontal,
                 parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._value: float = 0.5
        self._drag = False
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(22)
            self.setMinimumWidth(80)
        else:
            self.setFixedWidth(22)
            self.setMinimumHeight(80)
        self._orient = orientation

    def value(self) -> float:
        return self._value

    def setValue(self, v: float) -> None:
        self._value = max(0.0, min(1.0, v))
        self.update()

    def _track_rect(self) -> QRect:
        m = 4
        if self._orient == Qt.Orientation.Horizontal:
            return QRect(m, m, self.width() - 2 * m, self.height() - 2 * m)
        return QRect(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def _value_from_pos(self, pos: QPointF) -> float:
        r = self._track_rect()
        if self._orient == Qt.Orientation.Horizontal:
            return max(0.0, min(1.0, (pos.x() - r.left()) / max(1, r.width())))
        return max(0.0, min(1.0, 1.0 - (pos.y() - r.top()) / max(1, r.height())))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._track_rect()
        # track background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(60, 60, 60))
        p.drawRoundedRect(r, 3, 3)
        # fill
        fill = QRect(r)
        if self._orient == Qt.Orientation.Horizontal:
            fill.setWidth(int(r.width() * self._value))
        else:
            h = int(r.height() * self._value)
            fill.setTop(fill.bottom() - h)
        p.setBrush(QColor(200, 200, 200))
        p.drawRoundedRect(fill, 3, 3)
        # label
        p.setPen(QColor(230, 230, 230))
        p.setFont(QFont("Arial", 8))
        label = f"{self._label} {int(self._value * 100)}%"
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._drag = True
        self._value = self._value_from_pos(event.position())
        self.update()
        self.valueChanged.emit(self._value)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag:
            self._value = self._value_from_pos(event.position())
            self.update()
            self.valueChanged.emit(self._value)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = False


# ─────────────────────────────────────────────────────────────────────────────
# Swatches strip
# ─────────────────────────────────────────────────────────────────────────────

class _SwatchStrip(QWidget):
    """Horizontal strip of colour swatches (recent colours)."""

    colorPicked = Signal(QColor)

    _SWATCH = 18

    def __init__(self, colors: list[QColor] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._colors: list[QColor] = list(colors or [])
        self.setFixedHeight(self._SWATCH + 4)

    def setColors(self, colors: list[QColor]) -> None:
        self._colors = list(colors)
        self.update()

    def sizeHint(self) -> QSize:
        n = max(1, len(self._colors))
        return QSize(n * (self._SWATCH + 2), self._SWATCH + 4)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        x = 2
        for color in self._colors:
            rect = QRect(x, 2, self._SWATCH, self._SWATCH)
            p.fillRect(rect, color)
            p.setPen(QColor(100, 100, 100))
            p.drawRect(rect)
            x += self._SWATCH + 2

    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = 2
        for color in self._colors:
            rect = QRect(x, 2, self._SWATCH, self._SWATCH)
            if rect.contains(event.position().toPoint()):
                self.colorPicked.emit(color)
                return
            x += self._SWATCH + 2


# ─────────────────────────────────────────────────────────────────────────────
# Main PopupPalette
# ─────────────────────────────────────────────────────────────────────────────

class PopupPalette(QWidget):
    """Krita-style pop-up palette.

    Usage::

        palette = PopupPalette(canvas)
        palette.show_at(global_pos)        # open centered on cursor
        palette.colorChanged.connect(...)  # forward to canvas
    """

    colorChanged = Signal(QColor)
    brushSizeChanged = Signal(float)     # absolute px value
    brushOpacityChanged = Signal(float)  # 0–1

    _MAX_RECENT = 16
    _MAX_SIZE_PX = 500.0

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent,
                         Qt.WindowType.Popup |
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.canvas = canvas
        self._recent: list[QColor] = []

        self._build_ui()
        self._sync_from_canvas()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # --- colour wheel ---
        self._wheel = _MiniWheel(size=180)
        self._wheel.colorChanged.connect(self._on_wheel_changed)
        root.addWidget(self._wheel, alignment=Qt.AlignmentFlag.AlignHCenter)

        # --- hex input ---
        hex_row = QHBoxLayout()
        lbl = QLabel("#")
        lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setFixedWidth(68)
        self._hex_edit.setStyleSheet(
            f"background: {COLORS['input_bg']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; "
            "font-size: 11px; padding: 1px 3px;")
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_row.addStretch()
        hex_row.addWidget(lbl)
        hex_row.addWidget(self._hex_edit)
        hex_row.addStretch()
        root.addLayout(hex_row)

        # --- size slider ---
        self._size_slider = _TinySlider("Size")
        self._size_slider.valueChanged.connect(self._on_size_changed)
        root.addWidget(self._size_slider)

        # --- opacity slider ---
        self._opacity_slider = _TinySlider("Opacity")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        root.addWidget(self._opacity_slider)

        # --- recent colours ---
        recent_lbl = QLabel("Recent")
        recent_lbl.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(recent_lbl)
        self._swatch_strip = _SwatchStrip()
        self._swatch_strip.colorPicked.connect(self._pick_swatch)
        root.addWidget(self._swatch_strip)

        # style the container
        self.setStyleSheet("""
            PopupPalette {
                background: rgba(30, 30, 30, 240);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 10px;
            }
            QLabel { color: #ccc; }
        """)
        self.adjustSize()

    # ── public API ────────────────────────────────────────────────────────────

    def show_at(self, global_pos: QPoint) -> None:
        """Open the palette centered on *global_pos*."""
        self._sync_from_canvas()
        self.adjustSize()
        sz = self.sizeHint()
        pos = QPoint(global_pos.x() - sz.width() // 2,
                     global_pos.y() - sz.height() // 2)
        # keep on screen
        screen = QApplication.screenAt(global_pos)
        if screen:
            sg = screen.availableGeometry()
            pos.setX(max(sg.left(), min(pos.x(), sg.right() - sz.width())))
            pos.setY(max(sg.top(), min(pos.y(), sg.bottom() - sz.height())))
        self.move(pos)
        self.show()
        self.raise_()
        self.activateWindow()

    def push_recent(self, color: QColor) -> None:
        """Record a colour as recently used."""
        c = QColor(color)
        c.setAlpha(255)
        self._recent = [r for r in self._recent
                        if abs(r.red() - c.red()) + abs(r.green() - c.green()) + abs(r.blue() - c.blue()) > 5]
        self._recent.insert(0, c)
        if len(self._recent) > self._MAX_RECENT:
            self._recent = self._recent[:self._MAX_RECENT]

    # ── sync with canvas ──────────────────────────────────────────────────────

    def _sync_from_canvas(self) -> None:
        try:
            settings = self.canvas.get_cpp_brush_settings()
            rgba = settings.get("color", [0, 0, 0, 255])
            c = QColor(*rgba)
            blocked = self._wheel.blockSignals(True)
            self._wheel.setColor(c)
            self._wheel.blockSignals(blocked)
            self._hex_edit.setText(c.name()[1:].upper())

            size = float(settings.get("size", 20.0))
            norm_size = min(1.0, size / self._MAX_SIZE_PX)
            self._size_slider.setValue(norm_size)

            opacity = float(settings.get("opacity", 1.0))
            self._opacity_slider.setValue(opacity)

            self._swatch_strip.setColors(self._recent)
        except Exception:
            pass

    # ── internal handlers ─────────────────────────────────────────────────────

    def _on_wheel_changed(self, color: QColor) -> None:
        self._hex_edit.setText(color.name()[1:].upper())
        rgba = [color.red(), color.green(), color.blue(), 255]
        try:
            self.canvas.set_brush_setting("color", rgba)
        except Exception:
            pass
        self.colorChanged.emit(color)

    def _on_hex_edited(self) -> None:
        text = self._hex_edit.text().strip().lstrip("#")
        if len(text) == 6:
            try:
                r = int(text[0:2], 16)
                g = int(text[2:4], 16)
                b = int(text[4:6], 16)
                c = QColor(r, g, b)
                blocked = self._wheel.blockSignals(True)
                self._wheel.setColor(c)
                self._wheel.blockSignals(blocked)
                try:
                    self.canvas.set_brush_setting("color", [r, g, b, 255])
                except Exception:
                    pass
                self.colorChanged.emit(c)
            except ValueError:
                pass

    def _on_size_changed(self, norm: float) -> None:
        px = norm * self._MAX_SIZE_PX
        try:
            self.canvas.set_brush_setting("size", px)
        except Exception:
            pass
        self.brushSizeChanged.emit(px)

    def _on_opacity_changed(self, v: float) -> None:
        try:
            self.canvas.set_brush_setting("opacity", v)
        except Exception:
            pass
        self.brushOpacityChanged.emit(v)

    def _pick_swatch(self, color: QColor) -> None:
        blocked = self._wheel.blockSignals(True)
        self._wheel.setColor(color)
        self._wheel.blockSignals(blocked)
        self._hex_edit.setText(color.name()[1:].upper())
        try:
            self.canvas.set_brush_setting(
                "color", [color.red(), color.green(), color.blue(), 255])
        except Exception:
            pass
        self.colorChanged.emit(color)
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


__all__ = ["PopupPalette"]
