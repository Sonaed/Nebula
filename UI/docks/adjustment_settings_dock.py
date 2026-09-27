from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QDockWidget, QFormLayout,
    QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from UI.dialogs.adjustment_layer_dialog import CurveEditor


class AdjustmentSettingsDock(QDockWidget):
    """Non-modal, context-aware editor for the active adjustment layer."""

    spec_changed = Signal(dict)
    editing_started = Signal()
    editing_finished = Signal()

    def __init__(self, parent=None):
        super().__init__("Adjustment Settings", parent)
        self.setObjectName("adjustmentSettingsDock")
        self._layer = None
        self._spec = {}
        self._updating = False
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(350)
        self._edit_timer.timeout.connect(self.editing_finished.emit)
        self._body = QWidget(self)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._body)
        self.setWidget(self._scroll)
        self.setMinimumWidth(280)
        self._show_empty()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_empty(self):
        self._clear()
        self._layout.addWidget(QLabel("Sélectionnez un calque de réglage."))
        self._layout.addStretch(1)
        self.hide()

    def set_layer(self, layer):
        if layer is None or getattr(layer, "layer_kind", "raster") != "adjustment":
            self._layer = None
            self._show_empty()
            return
        self._layer = layer
        self._spec = dict(layer.adjustment or {})
        self._build()
        self.show()

    def _field(self, form, label, key, value, low=-100.0, high=100.0, step=1.0):
        control = QDoubleSpinBox(self._body)
        control.setRange(low, high)
        control.setSingleStep(step)
        control.setDecimals(2 if step < 1 else 0)
        control.setValue(float(value))
        control.valueChanged.connect(lambda _value, k=key: self._changed(k, control.value()))
        form.addRow(label, control)
        return control

    def _integer(self, form, label, key, value, low, high):
        control = QSpinBox(self._body)
        control.setRange(low, high)
        control.setValue(int(value))
        control.valueChanged.connect(lambda _value, k=key: self._changed(k, control.value()))
        form.addRow(label, control)
        return control

    def _build(self):
        self._clear()
        kind = str(self._spec.get("kind", "")).lower()
        self._layout.addWidget(QLabel(f"<b>{self._layer.name}</b>"))
        self._layout.addWidget(QLabel(f"Contexte : {kind.replace('_', ' ').title()}"))
        form = QFormLayout()
        self._layout.addLayout(form)
        self._controls = {}
        if kind == "levels":
            values = dict(self._spec.get("levels", {}))
            for key, label, low, high in (("black", "Noir", 0, 254), ("white", "Blanc", 1, 255), ("gamma", "Gamma", .01, 10), ("output_black", "Sortie noire", 0, 255), ("output_white", "Sortie blanche", 0, 255)):
                self._controls[key] = self._integer(form, label, key, values.get(key, 1 if key == "white" else 0), low, high) if key != "gamma" else self._field(form, label, key, values.get(key, 1), low, high, .01)
        elif kind == "curves":
            raw = dict(self._spec.get("curves", {}))
            curves = {"rgb": raw.get("points", [[0, 0], [255, 255]])}
            curves.update({key: values for key, values in dict(raw.get("channels", {})).items()})
            self._curve_editor = CurveEditor(curves, self._body)
            self._layout.addWidget(self._curve_editor)
            self._curve_editor.changed.connect(lambda: self._changed("_curves", None))
        elif kind == "exposure":
            values = dict(self._spec.get("exposure", {}))
            for key, label, low, high, step in (("exposure", "Exposition", -5, 5, .01), ("offset", "Décalage", -1, 1, .01), ("gamma", "Gamma", .01, 5, .01)):
                self._controls[key] = self._field(form, label, key, values.get(key, 0 if key != "gamma" else 1), low, high, step)
        elif kind == "vibrance":
            values = dict(self._spec.get("vibrance", {}))
            for key, label in (("vibrance", "Vibrance"), ("saturation", "Saturation")):
                self._controls[key] = self._field(form, label, key, values.get(key, 0))
        elif kind == "parametric_curves":
            values = dict(self._spec.get("parametric_curves", {}))
            for key, label in (("black", "Noirs"), ("shadows", "Ombres"), ("midtones", "Tons moyens"), ("highlights", "Hautes lumières"), ("white", "Blancs")):
                self._controls[key] = self._field(form, label, key, values.get(key, 0))
        elif kind == "color_balance":
            values = dict(self._spec.get("color_balance", {}))
            for zone, label in (("shadows", "Ombres"), ("midtones", "Tons moyens"), ("highlights", "Hautes lumières")):
                for index, channel in enumerate(("R", "V", "B")):
                    key = f"{zone}_{index}"
                    self._controls[key] = self._field(form, f"{label} {channel}", key, list(values.get(zone, (0, 0, 0)))[index])
        elif kind == "threshold":
            self._controls["threshold"] = self._integer(form, "Seuil", "threshold", self._spec.get("threshold", 128), 0, 255)
        elif kind == "posterize":
            self._controls["posterize"] = self._integer(form, "Niveaux", "posterize", self._spec.get("posterize", 4), 2, 32)
        elif kind == "luminosity_mask":
            self._mask_controls(form, self._spec.get("luminosity_mask", {}))
        elif kind == "selective_color":
            values = dict(self._spec.get("selective_color", {}).get("channels", {}))
            for channel in ("reds", "yellows", "greens", "cyans", "blues", "magentas", "whites", "neutrals", "blacks"):
                raw = list(values.get(channel, (0, 0, 0, 0)))
                for index, label in enumerate(("C", "M", "J", "N")):
                    self._controls[f"selective_{channel}_{index}"] = self._field(form, f"{channel} {label}", f"selective_{channel}_{index}", raw[index] if index < len(raw) else 0)
        mask = self._spec.get("luminosity_mask")
        if kind != "luminosity_mask":
            self._mask_controls(form, mask or {})
        self._layout.addStretch(1)

    def _mask_controls(self, form, values):
        values = dict(values or {})
        combo = QComboBox(self._body)
        combo.addItems(["none", "lights", "midtones", "shadows"])
        combo.setCurrentText(values.get("mode", "none"))
        combo.currentTextChanged.connect(lambda value: self._changed("_mask_mode", value))
        form.addRow("Masque luminosité", combo)
        self._mask_combo = combo
        self._mask_amount = self._field(form, "Intensité", "_mask_amount", values.get("amount", 1), 0, 1, .01)
        self._mask_feather = self._field(form, "Adoucissement", "_mask_feather", values.get("feather", .15), .01, 1, .01)

    def _changed(self, key, value):
        if self._updating or self._layer is None:
            return
        if not self._edit_timer.isActive():
            self.editing_started.emit()
        spec = dict(self._spec)
        kind = str(spec.get("kind", ""))
        if key.startswith("_mask_"):
            mask = dict(spec.get("luminosity_mask", {}))
            if key == "_mask_mode": mask["mode"] = value
            elif key == "_mask_amount": mask["amount"] = value
            elif key == "_mask_feather": mask["feather"] = value
            spec["luminosity_mask"] = mask
        elif kind in {"levels", "exposure", "vibrance", "parametric_curves", "color_balance"}:
            group = dict(spec.get(kind, {}))
            if "_" in key and kind == "color_balance":
                zone, index = key.rsplit("_", 1); values = list(group.get(zone, (0, 0, 0))); values[int(index)] = value; group[zone] = values
            else: group[key] = value
            spec[kind] = group
        elif kind == "curves" and key == "_curves":
            spec["curves"] = {"points": self._curve_editor.curves["rgb"], "channels": {channel: self._curve_editor.curves[channel] for channel in ("red", "green", "blue")}}
        elif kind == "selective_color" and key.startswith("selective_"):
            _, channel, index = key.split("_"); group = dict(spec.get("selective_color", {}).get("channels", {})); values = list(group.get(channel, (0, 0, 0, 0))); values[int(index)] = value; group[channel] = values; spec["selective_color"] = {"channels": group}
        else:
            spec[key] = value
        self._spec = spec
        self.spec_changed.emit(dict(spec))
        self._edit_timer.start()
