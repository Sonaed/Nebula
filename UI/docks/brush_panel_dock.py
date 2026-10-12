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
        "Base": "Pointe et forme",
        "Pression": "Dynamique",
        "Texture": "Texture",
        "Couleur": "Variations de couleur",
        "Peinture / Wet": "Peinture humide",
        "Double pointe": "Double pointe",
    }

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Pinceau", parent)
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
        install_dock_title(self, "Pinceau")
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

        self.preset_label = QLabel(self.canvas.get_cpp_brush_preset_name() or "Pinceau personnalisé")
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

            if group_name == "Double pointe":
                from UI.docks.brush_settings_dialog import DUAL_MODES
                mode_row = QHBoxLayout()
                mode_label = QLabel("Mode de fusion")
                mode_label.setObjectName("parameterLabel")
                dual_mode = QComboBox()
                dual_mode.addItems(DUAL_MODES)
                dual_mode.setCurrentIndex(int(values.get("dualMode", 0)))
                dual_mode.currentIndexChanged.connect(
                    lambda index: self.canvas.set_brush_setting("dualMode", float(index)))
                self.controls["dualMode"] = dual_mode
                mode_row.addWidget(mode_label)
                mode_row.addWidget(dual_mode, 1)
                mode_widget = QWidget()
                mode_widget.setLayout(mode_row)
                section.addWidget(mode_widget)

            if group_name == "Peinture / Wet":
                blend = QComboBox()
                blend.addItems([
                    "Normal", "Produit", "Écran", "Incrustation",
                    "Obscurcir", "Éclaircir",
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
                smooth_combo.addItems(["Désactivé", "Inertie", "Corde", "Moyenne glissante"])
                smooth_combo.setToolTip(
                    "Inertie : le trait suit le stylet avec un léger retard\n"
                    "Corde : le stylet tire le pinceau au bout d'une corde\n"
                    "Moyenne glissante : lisse sur les derniers points"
                )
                # Map index → mode string
                _SMOOTH_MODES = ["none", "basic", "weighted", "stabilize"]

                def _on_smooth(idx: int, _modes=_SMOOTH_MODES) -> None:
                    # The Canvas owns the application of this persistent
                    # choice, so loading a preset has precisely the same
                    # behaviour as changing it here.
                    self.canvas.set_brush_setting("smoothMode", idx)

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
        percent = not unit and ((minimum >= -1.0 and maximum <= 1.0 and step <= 0.01)
                                or key in ("spacing", "scatter", "dualSizeRatio",
                                           "dualSpacing", "dualScatter"))
        if not unit and key in ("angle", "rotationJitter"):
            unit = " °"
        control = NumericSlider(
            label, minimum, maximum, float(values[key]), step, " %" if percent else unit,
            default=float(values[key]), display_scale=100.0 if percent else 1.0,
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

        fg_lbl = QLabel("Couleur")
        fg_lbl.setObjectName("parameterLabel")
        fg_lbl.setFixedWidth(20)
        row.addWidget(fg_lbl)

        fg_swatch = ColorSwatchButton("Couleur principale")
        fg_swatch.set_color(QColor(*values["color"]))
        self.controls["color"] = fg_swatch

        def _choose_fg() -> None:
            rgba = self.canvas.get_cpp_brush_settings()["color"]
            color = QColorDialog.getColor(QColor(*rgba), self, "Couleur principale")
            if color.isValid():
                self.canvas.set_brush_setting(
                    "color", [color.red(), color.green(), color.blue(), color.alpha()]
                )
                fg_swatch.set_color(color)

        fg_swatch.clicked.connect(_choose_fg)
        row.addWidget(fg_swatch)

        row.addSpacing(12)

        gr_lbl = QLabel("Dégradé")
        gr_lbl.setObjectName("parameterLabel")
        row.addWidget(gr_lbl)

        gr_swatch = ColorSwatchButton("Couleur de dégradé")
        gr_swatch.set_color(QColor(*values["gradientColor"]))
        self.controls["gradientColor"] = gr_swatch

        def _choose_gr() -> None:
            rgba = self.canvas.get_cpp_brush_settings()["gradientColor"]
            color = QColorDialog.getColor(QColor(*rgba), self, "Couleur de dégradé")
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
        self.preset_label.setText(self.canvas.get_cpp_brush_preset_name() or "Pinceau personnalisé")
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
