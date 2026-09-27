"""Color Dock — Krita-grade colour selector.

Tabs:
  • Wheel    — HSV colour wheel (existing ColorWheel widget)
  • HSV      — Hue / Saturation / Value sliders
  • HSL      — Hue / Saturation / Lightness sliders
  • RGB      — Red / Green / Blue sliders (8-bit)

Below the tabs:
  • Foreground / Background swatches (click to swap, X to reset)
  • Hex input
  • Recent colours strip (16 swatches)
  • Named palette strip (custom saved colours)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog, QDockWidget, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from UI.widgets.color_wheel import ColorWheel
from UI.theme.palette import COLORS
from UI.widgets.dock_title_bar import install_dock_title


# ─────────────────────────────────────────────────────────────────────────────
# Reusable labelled channel slider
# ─────────────────────────────────────────────────────────────────────────────

class _ChannelSlider(QWidget):
    """Label + QSlider + value label in one row."""

    valueChanged = Signal(int)   # raw int (0–max)

    def __init__(self, label: str, max_val: int = 255, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFixedWidth(24)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet("font-size: 11px; color: #bbb;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, max_val)

        self._val_lbl = QLabel("0")
        self._val_lbl.setFixedWidth(30)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._val_lbl.setStyleSheet("font-size: 11px; color: #ddd;")

        self._slider.valueChanged.connect(self._on_change)
        row.addWidget(lbl)
        row.addWidget(self._slider, 1)
        row.addWidget(self._val_lbl)

    def _on_change(self, v: int) -> None:
        self._val_lbl.setText(str(v))
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, v: int, block: bool = True) -> None:
        blocked = self._slider.blockSignals(block)
        self._slider.setValue(int(v))
        self._val_lbl.setText(str(int(v)))
        self._slider.blockSignals(blocked)


# ─────────────────────────────────────────────────────────────────────────────
# Recent-colours strip + named palette
# ─────────────────────────────────────────────────────────────────────────────

class _ColorStrip(QWidget):
    """Horizontal strip of coloured squares, clickable."""

    colorPicked = Signal(QColor)

    _SZ = 18

    def __init__(self, max_colors: int = 20, parent=None) -> None:
        super().__init__(parent)
        self._colors: list[QColor] = []
        self._max = max_colors
        self.setFixedHeight(self._SZ + 6)

    def push(self, color: QColor) -> None:
        c = QColor(color); c.setAlpha(255)
        self._colors = [r for r in self._colors
                        if abs(r.red()-c.red())+abs(r.green()-c.green())+abs(r.blue()-c.blue()) > 4]
        self._colors.insert(0, c)
        if len(self._colors) > self._max:
            self._colors = self._colors[:self._max]
        self.update()

    def setColors(self, colors: list[QColor]) -> None:
        self._colors = list(colors)
        self.update()

    def colors(self) -> list[QColor]:
        return list(self._colors)

    def sizeHint(self) -> QSize:
        n = max(1, len(self._colors))
        return QSize(n * (self._SZ + 2) + 4, self._SZ + 6)

    def paintEvent(self, _ev) -> None:
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        x = 3
        for c in self._colors:
            p.fillRect(x, 3, self._SZ, self._SZ, c)
            p.setPen(QPen(QColor(90, 90, 90), 1))
            p.drawRect(x, 3, self._SZ, self._SZ)
            x += self._SZ + 2

    def mousePressEvent(self, ev) -> None:
        x = 3
        pt = ev.position().toPoint()
        for c in self._colors:
            if x <= pt.x() <= x + self._SZ and 3 <= pt.y() <= 3 + self._SZ:
                self.colorPicked.emit(c)
                return
            x += self._SZ + 2

    def mouseDoubleClickEvent(self, ev) -> None:
        # Double-click on empty area adds current FG color (handled by dock)
        pass


# ─────────────────────────────────────────────────────────────────────────────
# FG/BG swatch widget
# ─────────────────────────────────────────────────────────────────────────────

class _FgBgSwatch(QWidget):
    """Foreground / Background swatches with swap and reset buttons."""

    foregroundClicked = Signal()
    backgroundClicked = Signal()
    swapClicked = Signal()
    resetClicked = Signal()

    _SZ = 36

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fg = QColor(0, 0, 0)
        self._bg = QColor(255, 255, 255)
        self.setFixedSize(self._SZ * 2 + 20, self._SZ + 20)

    def setForeground(self, c: QColor) -> None:
        self._fg = QColor(c)
        self.update()

    def setBackground(self, c: QColor) -> None:
        self._bg = QColor(c)
        self.update()

    def paintEvent(self, _ev) -> None:
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # BG swatch (behind)
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.fillRect(self._SZ // 2 + 6, self._SZ // 2 + 6, self._SZ, self._SZ, self._bg)
        p.drawRect(self._SZ // 2 + 6, self._SZ // 2 + 6, self._SZ, self._SZ)
        # FG swatch (front)
        p.fillRect(2, 2, self._SZ, self._SZ, self._fg)
        p.drawRect(2, 2, self._SZ, self._SZ)
        # swap arrow hint (small ↔ in corner)
        p.setPen(QColor(200, 200, 200))
        p.setFont(QFont("Arial", 9))
        p.drawText(self._SZ + 8, self._SZ // 2, "⇄")
        # reset dot (tiny D&W)
        p.setFont(QFont("Arial", 7))
        p.drawText(self._SZ + 8, self._SZ // 2 + 12, "D/W")

    def mousePressEvent(self, ev) -> None:
        pt = ev.position().toPoint()
        # FG zone
        if 2 <= pt.x() <= 2 + self._SZ and 2 <= pt.y() <= 2 + self._SZ:
            self.foregroundClicked.emit()
        # swap zone
        elif self._SZ + 6 <= pt.x() <= self._SZ + 22 and 2 <= pt.y() <= 18:
            self.swapClicked.emit()
        # reset zone
        elif self._SZ + 6 <= pt.x() <= self._SZ + 22 and 20 <= pt.y() <= 36:
            self.resetClicked.emit()
        # BG zone
        elif self._SZ // 2 + 6 <= pt.x() <= self._SZ * 3 // 2 + 6:
            self.backgroundClicked.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Main Color Dock
# ─────────────────────────────────────────────────────────────────────────────

class ColorDock(QDockWidget):
    """Krita-grade colour selector connected to the brush colour."""

    _MAX_RECENT = 16

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Color", parent)
        self.canvas = canvas
        self.setObjectName("ColorDock")
        self.setMinimumWidth(240)
        install_dock_title(self, "Color")

        self._bg_color: QColor = QColor(255, 255, 255)   # background colour
        self._updating = False   # re-entry guard

        content = QWidget()
        content.setObjectName("dockContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(5)

        # ── FG/BG swatch ──────────────────────────────────────────────────
        self._fgbg = _FgBgSwatch()
        self._fgbg.foregroundClicked.connect(self._choose_fg)
        self._fgbg.backgroundClicked.connect(self._choose_bg)
        self._fgbg.swapClicked.connect(self._swap_fg_bg)
        self._fgbg.resetClicked.connect(self._reset_fg_bg)
        root.addWidget(self._fgbg, alignment=Qt.AlignmentFlag.AlignLeft)

        # ── Tab widget: Wheel / HSV / HSL / RGB ───────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs)

        # Tab 1 — Wheel
        wheel_page = QWidget()
        wl = QVBoxLayout(wheel_page)
        wl.setContentsMargins(0, 4, 0, 0)
        self.wheel = ColorWheel()
        self.wheel.colorChanged.connect(self._wheel_changed)
        wl.addWidget(self.wheel, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._tabs.addTab(wheel_page, "Wheel")

        # Tab 2 — HSV
        hsv_page = QWidget()
        hsvl = QVBoxLayout(hsv_page)
        hsvl.setContentsMargins(2, 6, 2, 0)
        self._h_slider = _ChannelSlider("H", 359)
        self._s_slider = _ChannelSlider("S", 255)
        self._v_slider = _ChannelSlider("V", 255)
        for s in (self._h_slider, self._s_slider, self._v_slider):
            s.valueChanged.connect(self._hsv_changed)
            hsvl.addWidget(s)
        hsvl.addStretch()
        self._tabs.addTab(hsv_page, "HSV")

        # Tab 3 — HSL
        hsl_page = QWidget()
        hsll = QVBoxLayout(hsl_page)
        hsll.setContentsMargins(2, 6, 2, 0)
        self._hl_slider = _ChannelSlider("H", 359)
        self._sl_slider = _ChannelSlider("S", 255)
        self._l_slider  = _ChannelSlider("L", 255)
        for s in (self._hl_slider, self._sl_slider, self._l_slider):
            s.valueChanged.connect(self._hsl_changed)
            hsll.addWidget(s)
        hsll.addStretch()
        self._tabs.addTab(hsl_page, "HSL")

        # Tab 4 — RGB
        rgb_page = QWidget()
        rgbl = QVBoxLayout(rgb_page)
        rgbl.setContentsMargins(2, 6, 2, 0)
        self._r_slider = _ChannelSlider("R")
        self._g_slider = _ChannelSlider("G")
        self._b_slider = _ChannelSlider("B")
        for s in (self._r_slider, self._g_slider, self._b_slider):
            s.valueChanged.connect(self._rgb_changed)
            rgbl.addWidget(s)
        rgbl.addStretch()
        self._tabs.addTab(rgb_page, "RGB")

        # ── Hex input ─────────────────────────────────────────────────────
        hex_row = QHBoxLayout()
        hex_lbl = QLabel("#")
        hex_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setFixedWidth(72)
        self._hex_edit.setStyleSheet(
            f"background:{COLORS['input_bg']}; color:{COLORS['text']}; border:1px solid {COLORS['border']}; "
            "font-size:11px; padding:1px 3px;")
        self._hex_edit.editingFinished.connect(self._hex_edited)
        # preview square
        self._swatch_btn = QPushButton()
        self._swatch_btn.setFixedSize(28, 22)
        self._swatch_btn.clicked.connect(self._choose_fg)
        hex_row.addWidget(hex_lbl)
        hex_row.addWidget(self._hex_edit)
        hex_row.addStretch()
        hex_row.addWidget(self._swatch_btn)
        root.addLayout(hex_row)

        # ── Recent colours ────────────────────────────────────────────────
        recent_hdr = QHBoxLayout()
        rl = QLabel("Recent")
        rl.setStyleSheet("color:#777; font-size:10px;")
        clear_btn = QToolButton()
        clear_btn.setText("✕")
        clear_btn.setFixedSize(16, 16)
        clear_btn.setStyleSheet("color:#666; border:none; font-size:9px;")
        clear_btn.clicked.connect(self._clear_recent)
        recent_hdr.addWidget(rl)
        recent_hdr.addStretch()
        recent_hdr.addWidget(clear_btn)
        root.addLayout(recent_hdr)

        scroll_r = QScrollArea()
        scroll_r.setFixedHeight(28)
        scroll_r.setWidgetResizable(True)
        scroll_r.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_r.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_r.setFrameShape(QFrame.Shape.NoFrame)
        self._recent_strip = _ColorStrip(max_colors=self._MAX_RECENT)
        self._recent_strip.colorPicked.connect(self._apply_color)
        scroll_r.setWidget(self._recent_strip)
        root.addWidget(scroll_r)

        # ── Custom palette swatches ───────────────────────────────────────
        palette_hdr = QHBoxLayout()
        pl = QLabel("Palette")
        pl.setStyleSheet("color:#777; font-size:10px;")
        add_btn = QToolButton()
        add_btn.setText("+")
        add_btn.setFixedSize(16, 16)
        add_btn.setStyleSheet("color:#aaa; border:none; font-size:11px; font-weight:bold;")
        add_btn.setToolTip("Add current colour to palette")
        add_btn.clicked.connect(self._add_to_palette)
        palette_hdr.addWidget(pl)
        palette_hdr.addStretch()
        palette_hdr.addWidget(add_btn)
        root.addLayout(palette_hdr)

        scroll_p = QScrollArea()
        scroll_p.setFixedHeight(28)
        scroll_p.setWidgetResizable(True)
        scroll_p.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_p.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_p.setFrameShape(QFrame.Shape.NoFrame)
        self._palette_strip = _ColorStrip(max_colors=64)
        self._palette_strip.colorPicked.connect(self._apply_color)
        scroll_p.setWidget(self._palette_strip)
        root.addWidget(scroll_p)

        self.setWidget(content)

        canvas.brush_settings_changed.connect(self.sync_from_canvas)
        self.sync_from_canvas(canvas.get_cpp_brush_settings())

    # ── sync ──────────────────────────────────────────────────────────────────

    def sync_from_canvas(self, settings) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            rgba = settings["color"]
            c = QColor(*rgba)
            self._apply_all_controls(c)
        finally:
            self._updating = False

    def _apply_all_controls(self, c: QColor) -> None:
        """Push colour into all controls without triggering feedback loops."""
        # Wheel
        blocked = self.wheel.blockSignals(True)
        self.wheel.setColor(c)
        self.wheel.blockSignals(blocked)

        # HSV
        h, s, v, _ = c.getHsv()
        self._h_slider.setValue(max(0, h))
        self._s_slider.setValue(s)
        self._v_slider.setValue(v)

        # HSL
        hl, sl, l, _ = c.getHsl()
        self._hl_slider.setValue(max(0, hl))
        self._sl_slider.setValue(sl)
        self._l_slider.setValue(l)

        # RGB
        self._r_slider.setValue(c.red())
        self._g_slider.setValue(c.green())
        self._b_slider.setValue(c.blue())

        # Hex + swatch
        self._hex_edit.setText(c.name()[1:].upper())
        self._swatch_btn.setStyleSheet(
            f"background:{c.name()}; border:1px solid #555;")
        self._fgbg.setForeground(c)

    # ── internal signal handlers ──────────────────────────────────────────────

    def _wheel_changed(self, color: QColor) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._apply_all_controls(color)
            self.canvas.set_brush_setting(
                "color", [color.red(), color.green(), color.blue(), 255])
        finally:
            self._updating = False

    def _rgb_changed(self, _=0) -> None:
        if self._updating:
            return
        c = QColor(self._r_slider.value(), self._g_slider.value(), self._b_slider.value())
        self._push_color(c)

    def _hsv_changed(self, _=0) -> None:
        if self._updating:
            return
        c = QColor.fromHsv(self._h_slider.value(), self._s_slider.value(),
                           self._v_slider.value())
        self._push_color(c)

    def _hsl_changed(self, _=0) -> None:
        if self._updating:
            return
        c = QColor.fromHsl(self._hl_slider.value(), self._sl_slider.value(),
                           self._l_slider.value())
        self._push_color(c)

    def _hex_edited(self) -> None:
        text = self._hex_edit.text().strip().lstrip("#")
        if len(text) == 6:
            try:
                c = QColor(int(text[:2], 16), int(text[2:4], 16), int(text[4:], 16))
                self._push_color(c)
            except ValueError:
                pass

    def _push_color(self, c: QColor) -> None:
        self._updating = True
        try:
            self._apply_all_controls(c)
            self.canvas.set_brush_setting(
                "color", [c.red(), c.green(), c.blue(), 255])
        finally:
            self._updating = False

    def _apply_color(self, c: QColor) -> None:
        self._push_color(c)

    # ── FG/BG actions ─────────────────────────────────────────────────────────

    def _choose_fg(self) -> None:
        try:
            rgba = self.canvas.get_cpp_brush_settings()["color"]
            current = QColor(*rgba)
        except Exception:
            current = QColor(0, 0, 0)
        c = QColorDialog.getColor(current, self, "Foreground Colour")
        if c.isValid():
            self._push_color(c)
            self.push_recent(c)

    def _choose_bg(self) -> None:
        c = QColorDialog.getColor(self._bg_color, self, "Background Colour")
        if c.isValid():
            self._bg_color = c
            self._fgbg.setBackground(c)

    def _swap_fg_bg(self) -> None:
        try:
            rgba = self.canvas.get_cpp_brush_settings()["color"]
            fg = QColor(*rgba)
        except Exception:
            fg = QColor(0, 0, 0)
        new_fg = QColor(self._bg_color)
        self._bg_color = fg
        self._fgbg.setBackground(fg)
        self._push_color(new_fg)

    def _reset_fg_bg(self) -> None:
        self._bg_color = QColor(255, 255, 255)
        self._fgbg.setBackground(self._bg_color)
        self._push_color(QColor(0, 0, 0))

    # ── palette management ────────────────────────────────────────────────────

    def push_recent(self, color: QColor) -> None:
        """Call after each brush stroke ends to record the used colour."""
        self._recent_strip.push(color)

    def _clear_recent(self) -> None:
        self._recent_strip.setColors([])

    def _add_to_palette(self) -> None:
        try:
            rgba = self.canvas.get_cpp_brush_settings()["color"]
            self._palette_strip.push(QColor(*rgba))
        except Exception:
            pass

    def choose_color(self) -> None:
        """Legacy compatibility method."""
        self._choose_fg()


__all__ = ["ColorDock"]
