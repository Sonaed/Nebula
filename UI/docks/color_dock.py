"""Color Dock.

Layout, top to bottom:
  • Foreground / background swatches + hex field
  • HSV wheel, scaled to the dock width
  • Channel sliders (TSV / TSL / RVB, chosen with a compact selector)
  • Recent colours and palette as wrapping swatch grids; both persist
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QSize, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog, QDockWidget, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QComboBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
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
    """Wrapping grid of clickable colour swatches (right-click removes)."""

    colorPicked = Signal(QColor)
    colorRemoved = Signal(QColor)

    _SZ = 20
    _GAP = 4

    def __init__(self, max_colors: int = 20, parent=None) -> None:
        super().__init__(parent)
        self._colors: list[QColor] = []
        self._max = max_colors
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def push(self, color: QColor) -> None:
        c = QColor(color); c.setAlpha(255)
        self._colors = [r for r in self._colors
                        if abs(r.red()-c.red())+abs(r.green()-c.green())+abs(r.blue()-c.blue()) > 4]
        self._colors.insert(0, c)
        if len(self._colors) > self._max:
            self._colors = self._colors[:self._max]
        self._relayout()

    def setColors(self, colors: list[QColor]) -> None:
        self._colors = list(colors)[:self._max]
        self._relayout()

    def colors(self) -> list[QColor]:
        return list(self._colors)

    def _columns(self, width: int) -> int:
        return max(1, (width + self._GAP) // (self._SZ + self._GAP))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        rows = max(1, -(-len(self._colors) // self._columns(width)))
        return rows * (self._SZ + self._GAP)

    def sizeHint(self) -> QSize:
        return QSize(8 * (self._SZ + self._GAP), self.heightForWidth(max(1, self.width())))

    def _relayout(self) -> None:
        self.setFixedHeight(self.heightForWidth(max(1, self.width())))
        self.updateGeometry()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        height = self.heightForWidth(self.width())
        if height != self.height():
            self.setFixedHeight(height)

    def _rect(self, index: int):
        from PySide6.QtCore import QRect
        columns = self._columns(self.width())
        row, column = divmod(index, columns)
        return QRect(column * (self._SZ + self._GAP), row * (self._SZ + self._GAP), self._SZ, self._SZ)

    def _index_at(self, point) -> int:
        for index in range(len(self._colors)):
            if self._rect(index).contains(point):
                return index
        return -1

    def paintEvent(self, _ev) -> None:
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        for index, c in enumerate(self._colors):
            p.setBrush(c)
            p.drawRoundedRect(self._rect(index).adjusted(0, 0, -1, -1), 4, 4)

    def mousePressEvent(self, ev) -> None:
        index = self._index_at(ev.position().toPoint())
        if index < 0:
            return
        color = self._colors[index]
        if ev.button() == Qt.MouseButton.RightButton:
            del self._colors[index]
            self._relayout()
            self.colorRemoved.emit(color)
        else:
            self.colorPicked.emit(color)


# ─────────────────────────────────────────────────────────────────────────────
# FG/BG swatch widget
# ─────────────────────────────────────────────────────────────────────────────

class _FgBgSwatch(QWidget):
    """Foreground / Background swatches with swap and reset buttons."""

    foregroundClicked = Signal()
    backgroundClicked = Signal()
    swapClicked = Signal()
    resetClicked = Signal()

    # Photoshop-style layout: foreground top-left, background bottom-right,
    # swap arrows top-right, mini default (black/white) swatches bottom-left.
    # The old version printed "⇄" and "D/W" as text right where the
    # background swatch is drawn, so the two overlapped.
    _SZ = 30
    _OFFSET = 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fg = QColor(0, 0, 0)
        self._bg = QColor(255, 255, 255)
        self.setFixedSize(self._SZ + self._OFFSET + 4, self._SZ + self._OFFSET + 4)
        self.setToolTip("Clic : choisir · flèches : permuter (X) · mini-carrés : noir / blanc (D)")

    def setForeground(self, c: QColor) -> None:
        self._fg = QColor(c)
        self.update()

    def setBackground(self, c: QColor) -> None:
        self._bg = QColor(c)
        self.update()

    def _fg_rect(self):
        from PySide6.QtCore import QRect
        return QRect(1, 1, self._SZ, self._SZ)

    def _bg_rect(self):
        from PySide6.QtCore import QRect
        return QRect(1 + self._OFFSET, 1 + self._OFFSET, self._SZ, self._SZ)

    def _swap_rect(self):
        from PySide6.QtCore import QRect
        return QRect(self._SZ + 3, 1, self._OFFSET - 2, self._OFFSET - 2)

    def _reset_rect(self):
        from PySide6.QtCore import QRect
        return QRect(1, self._SZ + 3, self._OFFSET - 2, self._OFFSET - 2)

    def paintEvent(self, _ev) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QPen(QColor(COLORS["border"]), 1)
        for rect, color in ((self._bg_rect(), self._bg), (self._fg_rect(), self._fg)):
            p.setPen(frame)
            p.setBrush(color)
            p.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 4, 4)
        # Swap: two small curved arrows.
        p.setPen(QPen(QColor(COLORS["text_muted"]), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = self._swap_rect().adjusted(2, 2, -2, -2)
        path = QPainterPath(QPointF(r.left(), r.bottom() - 3))
        path.quadTo(QPointF(r.left(), r.top()), QPointF(r.right() - 3, r.top()))
        p.drawPath(path)
        p.drawLine(QPointF(r.right() - 5, r.top() - 2), QPointF(r.right() - 3, r.top()))
        p.drawLine(QPointF(r.right() - 5, r.top() + 2), QPointF(r.right() - 3, r.top()))
        p.drawLine(QPointF(r.left() - 2, r.bottom() - 5), QPointF(r.left(), r.bottom() - 3))
        p.drawLine(QPointF(r.left() + 2, r.bottom() - 5), QPointF(r.left(), r.bottom() - 3))
        # Reset: mini black/white swatches.
        q = self._reset_rect()
        size = q.width() * 0.62
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(int(q.right() - size), int(q.bottom() - size), int(size), int(size))
        p.setBrush(QColor(0, 0, 0))
        p.drawRect(q.left(), q.top(), int(size), int(size))

    def mousePressEvent(self, ev) -> None:
        pt = ev.position().toPoint()
        if self._swap_rect().contains(pt):
            self.swapClicked.emit()
        elif self._reset_rect().contains(pt):
            self.resetClicked.emit()
        elif self._fg_rect().contains(pt):
            self.foregroundClicked.emit()
        elif self._bg_rect().contains(pt):
            self.backgroundClicked.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Main Color Dock
# ─────────────────────────────────────────────────────────────────────────────

class ColorDock(QDockWidget):
    """Krita-grade colour selector connected to the brush colour."""

    _MAX_RECENT = 16

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Couleur", parent)
        self.canvas = canvas
        self.setObjectName("ColorDock")
        self.setMinimumWidth(240)
        install_dock_title(self, "Couleur")

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


        # ── Swatches + hex on one row ─────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._fgbg)
        top_row.addStretch()
        hex_lbl = QLabel("#")
        hex_lbl.setObjectName("fieldCaption")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setFixedWidth(78)
        self._hex_edit.setToolTip("Couleur hexadécimale")
        self._hex_edit.editingFinished.connect(self._hex_edited)
        top_row.addWidget(hex_lbl)
        top_row.addWidget(self._hex_edit)
        root.addLayout(top_row)

        # ── Wheel: always visible, grows with the dock ────────────────────
        self.wheel = ColorWheel()
        self.wheel.setMaximumHeight(320)
        self.wheel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.wheel.colorChanged.connect(self._wheel_changed)
        root.addWidget(self.wheel, 3)

        # ── Channel sliders under the wheel ───────────────────────────────
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 2, 0, 0)
        channels = QLabel("Curseurs")
        channels.setObjectName("fieldCaption")
        mode_row.addWidget(channels)
        mode_row.addStretch()
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(("TSV", "TSL", "RVB"))
        self.mode_selector.setToolTip("Modèle des curseurs : teinte/saturation/valeur, "
                                      "teinte/saturation/luminosité ou rouge/vert/bleu")
        mode_row.addWidget(self.mode_selector)
        root.addLayout(mode_row)
        self._tabs = QStackedWidget()
        self.mode_selector.currentIndexChanged.connect(self._tabs.setCurrentIndex)
        root.addWidget(self._tabs)

        def channel_page(sliders, slot):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 2, 0, 0)
            layout.setSpacing(2)
            for slider in sliders:
                slider.valueChanged.connect(slot)
                layout.addWidget(slider)
            self._tabs.addWidget(page)

        self._h_slider = _ChannelSlider("T", 359)
        self._s_slider = _ChannelSlider("S", 255)
        self._v_slider = _ChannelSlider("V", 255)
        channel_page((self._h_slider, self._s_slider, self._v_slider), self._hsv_changed)
        self._hl_slider = _ChannelSlider("T", 359)
        self._sl_slider = _ChannelSlider("S", 255)
        self._l_slider = _ChannelSlider("L", 255)
        channel_page((self._hl_slider, self._sl_slider, self._l_slider), self._hsl_changed)
        self._r_slider = _ChannelSlider("R")
        self._g_slider = _ChannelSlider("V")
        self._b_slider = _ChannelSlider("B")
        channel_page((self._r_slider, self._g_slider, self._b_slider), self._rgb_changed)

        # ── Harmony and gamut mask ────────────────────────────────────────
        settings = QSettings("CreativeSystem", "CreativeSystem")
        harmony_row = QHBoxLayout()
        harmony_row.setContentsMargins(0, 6, 0, 0)
        harmony_label = QLabel("Harmonie")
        harmony_label.setObjectName("fieldCaption")
        self.harmony_selector = QComboBox()
        self.harmony_selector.addItems(list(self.HARMONIES))
        self.harmony_selector.setToolTip("Couleurs accordées à la couleur actuelle (clic pour l'utiliser)")
        self.harmony_selector.setCurrentText(str(settings.value("color/harmony", "Aucune")))
        harmony_row.addWidget(harmony_label)
        harmony_row.addStretch()
        harmony_row.addWidget(self.harmony_selector)
        root.addLayout(harmony_row)
        self._harmony_strip = _ColorStrip(max_colors=16)
        self._harmony_strip.colorPicked.connect(self._apply_color)
        root.addWidget(self._harmony_strip)

        gamut_row = QHBoxLayout()
        gamut_row.setContentsMargins(0, 2, 0, 0)
        gamut_label = QLabel("Masque de gamme")
        gamut_label.setObjectName("fieldCaption")
        self.gamut_selector = QComboBox()
        self.gamut_selector.addItems(list(self.GAMUTS))
        self.gamut_selector.setToolTip("Limite la roue à une famille de teintes, centrée sur la teinte actuelle")
        self.gamut_recentre = QToolButton()
        self.gamut_recentre.setText("↻")
        self.gamut_recentre.setAutoRaise(True)
        self.gamut_recentre.setToolTip("Recentrer le masque sur la teinte actuelle")
        gamut_row.addWidget(gamut_label)
        gamut_row.addStretch()
        gamut_row.addWidget(self.gamut_selector)
        gamut_row.addWidget(self.gamut_recentre)
        root.addLayout(gamut_row)
        for combo in (self.harmony_selector, self.gamut_selector):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(9)
        self._gamut_centre = float(settings.value("color/gamut_centre", 0.0))
        self.gamut_selector.setCurrentText(str(settings.value("color/gamut", "Aucun")))
        self.harmony_selector.currentTextChanged.connect(self._harmony_changed)
        self.gamut_selector.currentTextChanged.connect(lambda _t: self._gamut_changed(recentre=True))
        self.gamut_recentre.clicked.connect(lambda: self._gamut_changed(recentre=True))

        # ── Recent colours ────────────────────────────────────────────────
        def caption_row(text: str, button_text: str, tooltip: str, slot) -> QWidget:
            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 0)
            label = QLabel(text)
            label.setObjectName("fieldCaption")
            button = QToolButton()
            button.setText(button_text)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.setFixedSize(20, 20)
            button.clicked.connect(slot)
            row.addWidget(label)
            row.addStretch()
            row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            return holder

        self._recent_header = caption_row("Récentes", "✕", "Effacer les couleurs récentes", self._clear_recent)
        root.addWidget(self._recent_header)
        self._recent_strip = _ColorStrip(max_colors=self._MAX_RECENT)
        self._recent_strip.colorPicked.connect(self._apply_color)
        self._recent_strip.colorRemoved.connect(lambda _c: self._save_swatches())
        root.addWidget(self._recent_strip)
        self._recent_scroll = self._recent_strip

        # ── Palette (starts with a useful set, persists) ──────────────────
        root.addWidget(caption_row("Palette", "+", "Ajouter la couleur actuelle (clic droit sur une "
                                   "pastille pour la retirer)", self._add_to_palette))
        self._palette_strip = _ColorStrip(max_colors=64)
        self._palette_strip.colorPicked.connect(self._apply_color)
        self._palette_strip.colorRemoved.connect(lambda _c: self._save_swatches())
        root.addWidget(self._palette_strip)
        self._palette_scroll = self._palette_strip
        self._load_swatches()
        self._refresh_swatch_sections()
        self._gamut_changed(recentre=False)

        root.addStretch(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(240)
        scroll.setWidget(content)
        self.setWidget(scroll)

        canvas.brush_settings_changed.connect(self.sync_from_canvas)
        if hasattr(canvas, "color_shortcut_requested"):
            canvas.color_shortcut_requested.connect(
                lambda action: self._swap_fg_bg() if action == "swap" else self._reset_fg_bg())
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
        if hasattr(self, "_harmony_strip"):
            self._refresh_harmony(c)
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

    # Starter palette (artwork content, not UI chrome): neutrals then hues.
    # Hue offsets in degrees.
    HARMONIES = {
        "Aucune": (),
        "Complémentaire": (0, 180),
        "Analogue": (-30, 0, 30),
        "Triade": (0, 120, 240),
        "Complémentaires divisées": (0, 150, 210),
        "Tétrade": (0, 90, 180, 270),
    }
    # Allowed hue sectors as (offset°, width°) around the mask centre.
    GAMUTS = {
        "Aucun": (),
        "Complémentaire": ((0, 60), (180, 60)),
        "Analogue": ((0, 100),),
        "Triade": ((0, 50), (120, 50), (240, 50)),
        "Complémentaires divisées": ((0, 50), (150, 40), (210, 40)),
        "Carré": ((0, 40), (90, 40), (180, 40), (270, 40)),
    }

    def _current_color(self) -> QColor:
        rgba = self.canvas.get_cpp_brush_settings().get("color", [0, 0, 0, 255])
        return QColor(*rgba[:3])

    def _refresh_harmony(self, color: QColor | None = None) -> None:
        offsets = self.HARMONIES.get(self.harmony_selector.currentText(), ())
        visible = bool(offsets)
        self._harmony_strip.setVisible(visible)
        if not visible:
            return
        color = color or self._current_color()
        hue = color.hsvHue() if color.hsvHue() >= 0 else 0
        sat, val = color.hsvSaturationF(), color.valueF()
        sat = max(sat, 0.35)          # a grey has no hue: give the harmony something to show
        val = max(val, 0.35)
        swatches = []
        for offset in offsets:
            h = (hue + offset) % 360
            swatches.append(QColor.fromHsvF(h / 360.0, sat, val))
        for offset in offsets:          # lighter / darker companions
            h = (hue + offset) % 360
            swatches.append(QColor.fromHsvF(h / 360.0, max(0.0, sat - 0.25), min(1.0, val + 0.25)))
            swatches.append(QColor.fromHsvF(h / 360.0, min(1.0, sat + 0.1), max(0.0, val - 0.3)))
        self._harmony_strip.setColors(swatches)

    def _harmony_changed(self, name: str) -> None:
        QSettings("CreativeSystem", "CreativeSystem").setValue("color/harmony", name)
        self._refresh_harmony()

    def _gamut_changed(self, recentre: bool) -> None:
        name = self.gamut_selector.currentText()
        if recentre:
            color = self._current_color()
            self._gamut_centre = float(max(0, color.hsvHue()))
        settings = QSettings("CreativeSystem", "CreativeSystem")
        settings.setValue("color/gamut", name)
        settings.setValue("color/gamut_centre", self._gamut_centre)
        sectors = [(self._gamut_centre + offset, width) for offset, width in self.GAMUTS.get(name, ())]
        self.wheel.set_gamut(sectors)
        self.gamut_recentre.setEnabled(bool(sectors))

    DEFAULT_PALETTE = (
        (0, 0, 0), (58, 58, 63), (122, 122, 128), (189, 189, 194), (255, 255, 255), (242, 230, 216), (200, 53, 46), (232, 116, 59), (242, 193, 78), (109, 170, 69), (47, 143, 131), (60, 111, 200), (91, 75, 183), (176, 74, 154), (138, 90, 60), (231, 185, 161),
    )

    def _load_swatches(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        palette = settings.value("color/palette", None)
        recent = settings.value("color/recent", []) or []
        if isinstance(palette, str):
            palette = [palette]
        if isinstance(recent, str):
            recent = [recent]
        colors = ([QColor(*rgb) for rgb in self.DEFAULT_PALETTE] if palette is None
                  else [QColor(n) for n in palette if QColor(n).isValid()])
        self._palette_strip.setColors(colors)
        self._recent_strip.setColors([QColor(n) for n in recent if QColor(n).isValid()])

    def _save_swatches(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        settings.setValue("color/palette", [c.name() for c in self._palette_strip.colors()])
        settings.setValue("color/recent", [c.name() for c in self._recent_strip.colors()])

    def _refresh_swatch_sections(self) -> None:
        """An empty recent list takes no room."""
        has_recent = bool(self._recent_strip.colors())
        self._recent_header.setVisible(has_recent)
        self._recent_strip.setVisible(has_recent)

    def push_recent(self, color: QColor) -> None:
        """Call after each brush stroke ends to record the used colour."""
        self._recent_strip.push(color)
        self._refresh_swatch_sections()
        self._save_swatches()

    def _clear_recent(self) -> None:
        self._recent_strip.setColors([])
        self._refresh_swatch_sections()
        self._save_swatches()

    def _add_to_palette(self) -> None:
        rgba = self.canvas.get_cpp_brush_settings().get("color")
        if rgba is None or len(rgba) < 3:
            return
        self._palette_strip.push(QColor(*rgba[:3]))
        self._save_swatches()

    def choose_color(self) -> None:
        """Legacy compatibility method."""
        self._choose_fg()


__all__ = ["ColorDock"]
