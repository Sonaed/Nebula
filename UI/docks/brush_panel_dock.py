from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDockWidget,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from UI.docks.brush_settings_dialog import BOOL_GROUPS, FLOAT_GROUPS
from UI.docks.tools_dock import BrushPreview
from UI.widgets.collapsible_section import CollapsibleSection
from UI.widgets.dock_title_bar import install_dock_title
from UI.widgets.numeric_slider import NumericSlider
from TOOLS.brush_settings_state import DEFAULT_BRUSH_SETTINGS
from UI.theme.palette import COLORS


def _make_swatch_icon(color: QColor, size: int = 18) -> QIcon:
    """Génère une icône carré plein de la couleur donnée."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # fond avec la couleur
    painter.setBrush(color)
    painter.setPen(QColor(COLORS["border"]))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    painter.end()
    return QIcon(px)


class ColorSwatchButton(QPushButton):
    """Bouton swatch couleur : montre uniquement la couleur + tooltip."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._color = QColor(COLORS["input_bg"])
        self.setFixedSize(QSize(32, 22))
        self.setToolTip(label)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._refresh()

    def set_color(self, color: QColor) -> None:
        if color != self._color:
            self._color = color
            self._refresh()

    def get_color(self) -> QColor:
        return self._color

    def _refresh(self) -> None:
        # Fond coloré rendu dans paintEvent via stylesheet background-color
        hex_color = self._color.name()
        self.setStyleSheet(
            f"QPushButton {{ background: {hex_color}; border: 2px solid {COLORS['border']};"
            f" border-radius: 3px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent']}; }}"
        )
        self.setToolTip(f"{self._label}   {hex_color.upper()}")


class BrushPanelDock(QDockWidget):
    """Dense editor for the canonical CreativeCore brush state."""

    SECTION_NAMES = {
        "Base": "Brush Tip & Shape",
        "Pression": "Dynamics",
        "Texture": "Texture",
        "Couleur": "Color Dynamics",
        "Peinture / Wet": "Paint · Wet / Smudge",
    }

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Brush", parent)
        self.canvas = canvas
        self.controls: dict[str, QWidget] = {}
        self.setObjectName("BrushPanelDock")
        self.setMinimumWidth(260)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        install_dock_title(self, "Brush")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("dockContent")
        self.root = QVBoxLayout(container)
        self.root.setContentsMargins(8, 7, 8, 8)
        self.root.setSpacing(4)
        scroll.setWidget(container)
        self.setWidget(scroll)
        self._build()

    def _build(self) -> None:
        values = self.canvas.get_cpp_brush_settings()
        self.preview = BrushPreview()
        self.preview.setMinimumHeight(78)
        self.preview.setMaximumHeight(92)
        self.preview.set_settings(values)
        self.root.addWidget(self.preview)

        self.preset_label = QLabel(self.canvas.get_cpp_brush_preset_name() or "Custom Brush")
        self.preset_label.setObjectName("dockTitle")
        self.root.addWidget(self.preset_label)

        base_fields = {field[0]: field for field in FLOAT_GROUPS["Base"]}
        for key, unit in (("size", " px"), ("opacity", ""), ("flow", "")):
            self._add_numeric(self.root, base_fields[key], values, unit)

        for group_name, fields in FLOAT_GROUPS.items():
            section = CollapsibleSection(
                self.SECTION_NAMES[group_name], expanded=(group_name == "Base")
            )
            for field in fields:
                if field[0] not in {"size", "opacity", "flow"}:
                    self._add_numeric(section.content_layout, field, values)
            for key, label in BOOL_GROUPS.get(group_name, []):
                check = QCheckBox(label)
                check.setChecked(bool(values[key]))
                check.toggled.connect(
                    lambda checked, setting=key: self.canvas.set_brush_setting(setting, checked)
                )
                self.controls[key] = check
                section.addWidget(check)

            if group_name == "Couleur":
                section.addWidget(self._color_swatch_row(values))

            if group_name == "Peinture / Wet":
                blend = QComboBox()
                blend.addItems([
                    "Normal", "Multiply", "Screen", "Overlay",
                    "Darken", "Lighten",
                ])
                blend.setCurrentIndex(int(values["blendMode"]))
                blend.currentIndexChanged.connect(
                    lambda index: self.canvas.set_brush_setting("blendMode", index)
                )
                self.controls["blendMode"] = blend
                section.addWidget(blend)

                # ── Stabilisateur ─────────────────────────────────────────
                smooth_row = QHBoxLayout()
                smooth_lbl = QLabel("Stabilisateur")
                smooth_lbl.setObjectName("parameterLabel")
                smooth_row.addWidget(smooth_lbl)
                smooth_combo = QComboBox()
                smooth_combo.addItems(["Désactivé", "Basic (inertie)", "Pondéré (corde)", "Stabilise (FIFO)"])
                smooth_combo.setToolTip(
                    "Basic: inertie simple\n"
                    "Pondéré: le curseur tire le pinceau comme une corde\n"
                    "Stabilise: moyenne glissante des N derniers points"
                )
                # Map index → mode string
                _SMOOTH_MODES = ["none", "basic", "weighted", "stabilize"]

                def _on_smooth(idx: int, _modes=_SMOOTH_MODES) -> None:
                    mode = _modes[idx]
                    # Persist the selection with the preset state.  The
                    # native smoothing amount remains governed by the normal
                    # Stabilisation control; this value selects its method.
                    self.canvas.set_brush_setting("smoothMode", idx)
                    if hasattr(self.canvas, "brush_smoother"):
                        if mode == "none":
                            self.canvas.brush_smoother.set_mode("basic")
                            self.canvas.brush_smoother.strength = 0.0
                        else:
                            self.canvas.brush_smoother.set_mode(mode)

                smooth_combo.currentIndexChanged.connect(_on_smooth)
                self.controls["smoothMode"] = smooth_combo
                smooth_row.addWidget(smooth_combo, 1)
                smooth_widget = QWidget()
                smooth_widget.setLayout(smooth_row)
                section.addWidget(smooth_widget)

            self.root.addWidget(section)

        self.root.addStretch()

    # ──────────────────────────────────────────────────────────────────────────
    # Widgets helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _add_numeric(self, layout, field, values, unit: str = "") -> None:
        key, label, minimum, maximum, step = field
        control = NumericSlider(
            label, minimum, maximum, float(values[key]), step, unit, default=float(values[key])
        )
        control.valueChanged.connect(
            lambda value, setting=key: self.canvas.set_brush_setting(setting, value)
        )
        self.controls[key] = control
        layout.addWidget(control)

    def _color_swatch_row(self, values) -> QWidget:
        """
        Ligne compacte avec deux boutons swatch (Foreground + Gradient).
        Aucun texte dans les boutons — uniquement la couleur et le tooltip.
        """
        row = QHBoxLayout()
        row.setSpacing(6)

        fg_lbl = QLabel("FG")
        fg_lbl.setObjectName("parameterLabel")
        fg_lbl.setFixedWidth(20)
        row.addWidget(fg_lbl)

        fg_swatch = ColorSwatchButton("Foreground")
        fg_swatch.set_color(QColor(*values["color"]))
        self.controls["color"] = fg_swatch

        def _choose_fg() -> None:
            rgba = self.canvas.get_cpp_brush_settings()["color"]
            color = QColorDialog.getColor(QColor(*rgba), self, "Couleur foreground")
            if color.isValid():
                self.canvas.set_brush_setting(
                    "color", [color.red(), color.green(), color.blue(), color.alpha()]
                )
                fg_swatch.set_color(color)

        fg_swatch.clicked.connect(_choose_fg)
        row.addWidget(fg_swatch)

        row.addSpacing(12)

        gr_lbl = QLabel("Grad")
        gr_lbl.setObjectName("parameterLabel")
        row.addWidget(gr_lbl)

        gr_swatch = ColorSwatchButton("Gradient color")
        gr_swatch.set_color(QColor(*values["gradientColor"]))
        self.controls["gradientColor"] = gr_swatch

        def _choose_gr() -> None:
            rgba = self.canvas.get_cpp_brush_settings()["gradientColor"]
            color = QColorDialog.getColor(QColor(*rgba), self, "Couleur gradient")
            if color.isValid():
                self.canvas.set_brush_setting(
                    "gradientColor", [color.red(), color.green(), color.blue(), color.alpha()]
                )
                gr_swatch.set_color(color)

        gr_swatch.clicked.connect(_choose_gr)
        row.addWidget(gr_swatch)
        row.addStretch()

        container = QWidget()
        container.setLayout(row)
        return container

    # ──────────────────────────────────────────────────────────────────────────
    # Sync
    # ──────────────────────────────────────────────────────────────────────────

    def sync_from_canvas(self, *_args) -> None:
        values = self.canvas.get_cpp_brush_settings()
        self.preview.set_settings(values)
        self.preset_label.setText(self.canvas.get_cpp_brush_preset_name() or "Custom Brush")
        for key, control in self.controls.items():
            # Presets are intentionally forwards/backwards compatible.  A
            # control added by a newer Nebula build must not make opening an
            # older .csbr preset fail repeatedly in the UI event loop.
            value = values.get(key, DEFAULT_BRUSH_SETTINGS.get(key, 0))
            if isinstance(control, NumericSlider):
                control.setValue(float(value))
            elif isinstance(control, QCheckBox):
                blocked = control.blockSignals(True)
                control.setChecked(bool(value))
                control.blockSignals(blocked)
            elif isinstance(control, QComboBox):
                blocked = control.blockSignals(True)
                control.setCurrentIndex(int(value))
                control.blockSignals(blocked)
            elif isinstance(control, ColorSwatchButton):
                if key in values:
                    control.set_color(QColor(*values[key]))


__all__ = ["BrushPanelDock"]
