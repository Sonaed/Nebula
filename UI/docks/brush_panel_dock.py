from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QColorDialog, QComboBox, QDockWidget, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from UI.docks.brush_settings_dialog import BOOL_GROUPS, FLOAT_GROUPS
from UI.docks.tools_dock import BrushPreview
from UI.widgets.collapsible_section import CollapsibleSection
from UI.widgets.dock_title_bar import install_dock_title
from UI.widgets.numeric_slider import NumericSlider


class BrushPanelDock(QDockWidget):
    """Dense editor for the canonical CreativeCore brush state."""

    SECTION_NAMES = {"Base": "Brush Tip & Shape", "Pression": "Dynamics", "Texture": "Texture", "Couleur": "Color Dynamics", "Peinture / Wet": "Paint · Wet / Smudge"}

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Brush", parent)
        self.canvas = canvas
        self.controls: dict[str, QWidget] = {}
        self.setObjectName("BrushPanelDock")
        self.setMinimumWidth(260)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
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
            section = CollapsibleSection(self.SECTION_NAMES[group_name], expanded=(group_name == "Base"))
            for field in fields:
                if field[0] not in {"size", "opacity", "flow"}:
                    self._add_numeric(section.content_layout, field, values)
            for key, label in BOOL_GROUPS.get(group_name, []):
                check = QCheckBox(label)
                check.setChecked(bool(values[key]))
                check.toggled.connect(lambda checked, setting=key: self.canvas.set_brush_setting(setting, checked))
                self.controls[key] = check
                section.addWidget(check)
            if group_name == "Couleur":
                section.addWidget(self._color_button("color", "Foreground"))
                section.addWidget(self._color_button("gradientColor", "Gradient color"))
            if group_name == "Peinture / Wet":
                blend = QComboBox()
                blend.addItems(["Normal", "Multiply", "Screen", "Overlay", "Darken", "Lighten"])
                blend.setCurrentIndex(int(values["blendMode"]))
                blend.currentIndexChanged.connect(lambda index: self.canvas.set_brush_setting("blendMode", index))
                self.controls["blendMode"] = blend
                section.addWidget(blend)
            self.root.addWidget(section)
        self.root.addStretch()

    def _add_numeric(self, layout, field, values, unit: str = "") -> None:
        key, label, minimum, maximum, step = field
        control = NumericSlider(label, minimum, maximum, float(values[key]), step, unit, default=float(values[key]))
        control.valueChanged.connect(lambda value, setting=key: self.canvas.set_brush_setting(setting, value))
        self.controls[key] = control
        layout.addWidget(control)

    def _color_button(self, key: str, label: str) -> QPushButton:
        button = QPushButton()
        button.setProperty("colorLabel", label)
        self.controls[key] = button
        self._set_color_button(button, self.canvas.get_cpp_brush_settings()[key])
        def choose() -> None:
            color = QColorDialog.getColor(QColor(*self.canvas.get_cpp_brush_settings()[key]), self, label)
            if color.isValid():
                self.canvas.set_brush_setting(key, [color.red(), color.green(), color.blue(), color.alpha()])
        button.clicked.connect(choose)
        return button

    @staticmethod
    def _set_color_button(button, rgba) -> None:
        color = QColor(*rgba)
        button.setText(f"{button.property('colorLabel') or 'Color'}   {color.name().upper()}")

    def sync_from_canvas(self, *_args) -> None:
        values = self.canvas.get_cpp_brush_settings()
        self.preview.set_settings(values)
        self.preset_label.setText(self.canvas.get_cpp_brush_preset_name() or "Custom Brush")
        for key, control in self.controls.items():
            if isinstance(control, NumericSlider):
                control.setValue(float(values[key]))
            elif isinstance(control, QCheckBox):
                blocked = control.blockSignals(True); control.setChecked(bool(values[key])); control.blockSignals(blocked)
            elif isinstance(control, QComboBox):
                blocked = control.blockSignals(True); control.setCurrentIndex(int(values[key])); control.blockSignals(blocked)
            elif isinstance(control, QPushButton):
                self._set_color_button(control, values[key])


__all__ = ["BrushPanelDock"]
