from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDockWidget, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)
from UI.widgets.color_wheel import ColorWheel


class ColorDock(QDockWidget):
    """Sélecteur RGB compact connecté à la couleur canonique du brush."""

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("COLOR", parent)
        self.canvas = canvas
        self.setObjectName("ColorDock")
        self.setMinimumWidth(250)
        self.sliders = {}
        self.value_labels = {}

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(9, 9, 9, 9)
        self.wheel = ColorWheel()
        self.wheel.colorChanged.connect(self._wheel_changed)
        root.addWidget(self.wheel)
        self.swatch = QPushButton()
        self.swatch.setMinimumHeight(58)
        self.swatch.clicked.connect(self.choose_color)
        root.addWidget(self.swatch)

        for key, label in (("r", "R"), ("g", "G"), ("b", "B")):
            row = QHBoxLayout()
            title = QLabel(label)
            title.setFixedWidth(16)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 255)
            value_label = QLabel("0")
            value_label.setFixedWidth(30)
            slider.valueChanged.connect(self._sliders_changed)
            row.addWidget(title)
            row.addWidget(slider, 1)
            row.addWidget(value_label)
            root.addLayout(row)
            self.sliders[key] = slider
            self.value_labels[key] = value_label

        self.hex_label = QLabel()
        self.hex_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.hex_label)
        self.setWidget(content)
        canvas.brush_settings_changed.connect(self.sync_from_canvas)
        self.sync_from_canvas(canvas.get_cpp_brush_settings())

    def _sliders_changed(self, _value=0) -> None:
        rgba = [
            self.sliders["r"].value(),
            self.sliders["g"].value(),
            self.sliders["b"].value(),
            255,
        ]
        self.canvas.set_brush_setting("color", rgba)

    def _wheel_changed(self, color: QColor) -> None:
        self.canvas.set_brush_setting(
            "color", [color.red(), color.green(), color.blue(), color.alpha()]
        )

    def choose_color(self) -> None:
        current = QColor(*self.canvas.get_cpp_brush_settings()["color"])
        color = QColorDialog.getColor(current, self, "Couleur du brush")
        if color.isValid():
            self.canvas.set_brush_setting(
                "color", [color.red(), color.green(), color.blue(), color.alpha()]
            )

    def sync_from_canvas(self, settings) -> None:
        rgba = settings["color"]
        for key, value in zip(("r", "g", "b"), rgba[:3]):
            slider = self.sliders[key]
            blocked = slider.blockSignals(True)
            slider.setValue(int(value))
            slider.blockSignals(blocked)
            self.value_labels[key].setText(str(int(value)))
        color = QColor(*rgba)
        blocked = self.wheel.blockSignals(True)
        self.wheel.setColor(color)
        self.wheel.blockSignals(blocked)
        self.hex_label.setText(color.name().upper())
        self.swatch.setText(color.name().upper())
        self.swatch.setStyleSheet(
            f"background-color: {color.name()}; color: "
            f"{'#111318' if color.lightness() > 140 else '#f2f3f5'};"
        )


__all__ = ["ColorDock"]
