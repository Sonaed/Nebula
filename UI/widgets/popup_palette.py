"""Right-click palette: colour, size, opacity, recent colours, favourite brushes.

Opens centred on the cursor and closes on Escape or a click outside (it is a
Qt popup).  Everything it shows is shared with the docks: the wheel is the
Couleur panel's wheel, recent colours come from the same settings key, and
the brush buttons are the presets marked as favourites.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget,
)

from UI.theme.palette import COLORS
from UI.widgets.color_wheel import ColorWheel
from UI.widgets.numeric_slider import NumericSlider


class PopupPalette(QWidget):
    colorChanged = Signal(QColor)
    brushSizeChanged = Signal(float)
    brushOpacityChanged = Signal(float)

    _MAX_RECENT = 12
    _MAX_FAVORITES = 6

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("popupPalette")
        self.canvas = canvas
        self._syncing = False
        self._build_ui()

    # ── build ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(8)

        self._wheel = ColorWheel()
        self._wheel.setFixedSize(196, 196)
        self._wheel.colorChanged.connect(self._on_wheel_changed)
        root.addWidget(self._wheel, alignment=Qt.AlignmentFlag.AlignHCenter)

        hex_row = QHBoxLayout()
        hex_row.addStretch()
        hash_label = QLabel("#")
        hash_label.setObjectName("fieldCaption")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setFixedWidth(78)
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_row.addWidget(hash_label)
        hex_row.addWidget(self._hex_edit)
        hex_row.addStretch()
        root.addLayout(hex_row)

        self._size_slider = NumericSlider("Taille", 1.0, 500.0, 10.0, 1.0, " px")
        self._size_slider.valueChanged.connect(self._on_size_changed)
        root.addWidget(self._size_slider)
        self._opacity_slider = NumericSlider("Opacité", 0.0, 1.0, 1.0, 0.01, " %", display_scale=100.0)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        root.addWidget(self._opacity_slider)

        self._recent_label = QLabel("Récentes")
        self._recent_label.setObjectName("fieldCaption")
        root.addWidget(self._recent_label)
        self._recent_row = QHBoxLayout()
        self._recent_row.setSpacing(4)
        root.addLayout(self._recent_row)

        self._favorites_label = QLabel("Pinceaux favoris")
        self._favorites_label.setObjectName("fieldCaption")
        root.addWidget(self._favorites_label)
        self._favorites_grid = QGridLayout()
        self._favorites_grid.setSpacing(4)
        root.addLayout(self._favorites_grid)
        self.setFixedWidth(240)

    # ── public API ──────────────────────────────────────────────────────────

    def hideEvent(self, event) -> None:
        self._hidden_at = time.monotonic()
        super().hideEvent(event)

    def closed_recently(self, window: float = 0.3) -> bool:
        """True right after closing: the click that closed it must not reopen it."""
        return time.monotonic() - getattr(self, "_hidden_at", -1e9) < window

    def show_at(self, global_pos: QPoint) -> None:
        """Open centred on *global_pos*, kept inside the screen."""
        self._sync_from_canvas()
        self.adjustSize()
        size = self.sizeHint()
        position = QPoint(global_pos.x() - size.width() // 2, global_pos.y() - size.height() // 2)
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            position.setX(max(area.left(), min(position.x(), area.right() - size.width())))
            position.setY(max(area.top(), min(position.y(), area.bottom() - size.height())))
        self.move(position)
        self.show()
        self.raise_()
        self.activateWindow()

    # ── sync ────────────────────────────────────────────────────────────────

    def _sync_from_canvas(self) -> None:
        settings = self.canvas.get_cpp_brush_settings()
        color = QColor(*settings.get("color", [0, 0, 0, 255])[:3])
        self._syncing = True
        try:
            self._wheel.setColor(color)
            self._hex_edit.setText(color.name()[1:].upper())
            self._size_slider.setValue(float(settings.get("size", 10.0)))
            self._opacity_slider.setValue(float(settings.get("opacity", 1.0)))
        finally:
            self._syncing = False
        self._fill_recent()
        self._fill_favorites()

    def _fill_recent(self) -> None:
        while self._recent_row.count():
            item = self._recent_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        stored = QSettings("CreativeSystem", "CreativeSystem").value("color/recent", []) or []
        if isinstance(stored, str):
            stored = [stored]
        colors = [QColor(name) for name in stored if QColor(name).isValid()][:self._MAX_RECENT // 2 * 2]
        for color in colors[:8]:
            button = QToolButton()
            button.setFixedSize(22, 22)
            button.setToolTip(color.name().upper())
            button.setStyleSheet(f"QToolButton {{ background: {color.name()}; border: 1px solid "
                                 f"{COLORS['border']}; border-radius: 5px; }}"
                                 f"QToolButton:hover {{ border-color: {COLORS['accent']}; }}")
            button.clicked.connect(lambda _=False, c=QColor(color): self._apply_color(c, close=True))
            self._recent_row.addWidget(button)
        self._recent_row.addStretch()
        self._recent_label.setVisible(bool(colors))

    def _fill_favorites(self) -> None:
        while self._favorites_grid.count():
            item = self._favorites_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        manager = getattr(self.canvas, "brush_preset_manager", None)
        names = []
        if manager is not None:
            names = [name for name in manager.list_presets()
                     if manager.metadata(name)["favorite"]][:self._MAX_FAVORITES]
        from UI.docks.brush_presets_dock import BrushPresetsDock
        current = self.canvas.get_cpp_brush_preset_name()
        for index, name in enumerate(names):
            button = QToolButton()
            button.setCheckable(True)
            button.setChecked(name == current)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setText(name)
            button.setToolTip(name)
            button.setIcon(QIcon(QPixmap.fromImage(
                BrushPresetsDock._render_thumbnail(manager.load(name) or {}, name))))
            button.setIconSize(QSize(92, 18))
            button.setFixedSize(104, 46)
            button.setObjectName("popupBrush")
            button.clicked.connect(lambda _=False, n=name: self._pick_brush(n))
            self._favorites_grid.addWidget(button, index // 2, index % 2)
        self._favorites_label.setVisible(bool(names))

    # ── handlers ────────────────────────────────────────────────────────────

    def _apply_color(self, color: QColor, close: bool = False) -> None:
        self.canvas.set_brush_setting("color", [color.red(), color.green(), color.blue(), 255])
        self.colorChanged.emit(color)
        if close:
            self.hide()
        else:
            self._syncing = True
            self._wheel.setColor(color)
            self._hex_edit.setText(color.name()[1:].upper())
            self._syncing = False

    def _on_wheel_changed(self, color: QColor) -> None:
        if not self._syncing:
            self._hex_edit.setText(color.name()[1:].upper())
            self.canvas.set_brush_setting("color", [color.red(), color.green(), color.blue(), 255])
            self.colorChanged.emit(color)

    def _on_hex_edited(self) -> None:
        color = QColor("#" + self._hex_edit.text().strip().lstrip("#"))
        if color.isValid():
            self._apply_color(color)

    def _on_size_changed(self, value: float) -> None:
        if not self._syncing:
            self.canvas.set_brush_setting("size", float(value))
            self.brushSizeChanged.emit(float(value))

    def _on_opacity_changed(self, value: float) -> None:
        if not self._syncing:
            self.canvas.set_brush_setting("opacity", float(value))
            self.brushOpacityChanged.emit(float(value))

    def _pick_brush(self, name: str) -> None:
        self.canvas.load_cpp_brush_preset(name)
        self.hide()

    # ── painting / keys ─────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(COLORS["panel"])
        background.setAlpha(248)
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


__all__ = ["PopupPalette"]
