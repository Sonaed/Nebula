from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget


class NumericSlider(QWidget):
    valueChanged = Signal(float)

    def __init__(self, label: str, minimum: float, maximum: float, value: float,
                 step: float = 0.01, unit: str = "", default: float | None = None,
                 parent=None, display_scale: float = 1.0) -> None:
        super().__init__(parent)
        self._minimum, self._maximum = minimum, maximum
        # Normalised 0–1 settings read as percentages (display_scale=100).
        self._scale = float(display_scale) or 1.0
        self._steps = max(1, round((maximum - minimum) / step))
        self._default = value if default is None else default
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 3)
        root.setSpacing(2)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setObjectName("parameterLabel")
        self.spin = QDoubleSpinBox()
        self.spin.setObjectName("parameterValue")
        self.spin.setRange(minimum * self._scale, maximum * self._scale)
        shown_step = step * self._scale
        self.spin.setSingleStep(shown_step)
        self.spin.setDecimals(0 if float(shown_step).is_integer() else
                              max(0, min(3, len(str(shown_step).split(".")[-1]))))
        self.spin.setSuffix(unit)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin.setFrame(False)
        self.spin.setMaximumWidth(82)
        header.addWidget(self.label)
        header.addStretch()
        header.addWidget(self.spin)
        root.addLayout(header)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._steps)
        root.addWidget(self.slider)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self.setValue(value, emit=False)

    def _to_slider(self, value: float) -> int:
        return round((value - self._minimum) / (self._maximum - self._minimum) * self._steps)

    def _from_slider(self, value: int) -> float:
        return self._minimum + value / self._steps * (self._maximum - self._minimum)

    def _slider_changed(self, value: int) -> None:
        actual = self._from_slider(value)
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(actual * self._scale)
        self.spin.blockSignals(blocked)
        self.valueChanged.emit(actual)

    def _spin_changed(self, value: float) -> None:
        value = value / self._scale
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(value))
        self.slider.blockSignals(blocked)
        self.valueChanged.emit(value)

    def setValue(self, value: float, *, emit: bool = False) -> None:
        for control in (self.spin, self.slider):
            control.blockSignals(True)
        self.spin.setValue(value * self._scale)
        self.slider.setValue(self._to_slider(value))
        for control in (self.spin, self.slider):
            control.blockSignals(False)
        if emit:
            self.valueChanged.emit(float(value))

    def value(self) -> float:
        return self.spin.value() / self._scale

    def mouseDoubleClickEvent(self, event) -> None:
        self.setValue(self._default, emit=True)
        event.accept()
