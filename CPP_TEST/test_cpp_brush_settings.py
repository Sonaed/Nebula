from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# Racine du projet pour permettre les imports TOOLS / CANVAS / etc.
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

LIBRARY = (
    ROOT /
    "build_cpp" /
    "libCreativeCoreBridge.so"
)

if not LIBRARY.exists():
    raise FileNotFoundError(
        f"Bibliothèque introuvable : {LIBRARY}"
    )

lib = ctypes.CDLL(
    str(LIBRARY)
)

Handle = ctypes.c_void_p


# ============================================================
# C API
# ============================================================

lib.cs_brush_create.restype = Handle
lib.cs_brush_destroy.argtypes = [Handle]

FLOAT_FUNCTIONS = [
    "cs_brush_set_size",
    "cs_brush_set_opacity",
    "cs_brush_set_flow",
    "cs_brush_set_hardness",
    "cs_brush_set_spacing",
    "cs_brush_set_roundness",
    "cs_brush_set_angle",
    "cs_brush_set_scatter",
    "cs_brush_set_size_jitter",
    "cs_brush_set_rotation_jitter",
    "cs_brush_set_texture_strength",
    "cs_brush_set_texture_scale",
    "cs_brush_set_texture_random_scale",
    "cs_brush_set_texture_random_offset",
    "cs_brush_set_texture_brightness",
    "cs_brush_set_texture_contrast",
    "cs_brush_set_hue_jitter",
    "cs_brush_set_saturation_jitter",
    "cs_brush_set_brightness_jitter",
    "cs_brush_set_gradient_amount",
    "cs_brush_set_paint_mix",
    "cs_brush_set_wetness",
    "cs_brush_set_pickup",
    "cs_brush_set_dilution",
    "cs_brush_set_smudge",
    "cs_brush_set_paint_persistence",
    "cs_brush_set_color_carry",
]

INT_FUNCTIONS = [
    "cs_brush_set_eraser",
    "cs_brush_set_texture_mirror",
    "cs_brush_set_texture_affect_opacity",
    "cs_brush_set_dirty_color",
    "cs_brush_set_stroke_gradient",
    "cs_brush_set_linear_gradient",
    "cs_brush_set_radial_gradient",
    "cs_brush_set_wet_mix",
    "cs_brush_set_sample_canvas",
]

for name in FLOAT_FUNCTIONS:
    getattr(lib, name).argtypes = [
        Handle,
        ctypes.c_float,
    ]

for name in INT_FUNCTIONS:
    getattr(lib, name).argtypes = [
        Handle,
        ctypes.c_int,
    ]

lib.cs_brush_set_blend_mode.argtypes = [
    Handle,
    ctypes.c_int,
]

lib.cs_brush_set_color.argtypes = [
    Handle,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8,
]

lib.cs_brush_set_gradient_color.argtypes = [
    Handle,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8,
]


# ============================================================
# SLIDER
# ============================================================

class SliderField(QWidget):
    def __init__(
        self,
        title,
        minimum,
        maximum,
        value,
        scale,
        callback,
        suffix="",
    ):
        super().__init__()

        self.scale = scale
        self.callback = callback
        self.suffix = suffix

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        self.label = QLabel(title)

        self.slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.slider.setRange(
            minimum,
            maximum
        )

        self.slider.setValue(
            int(value / scale)
        )

        self.value_label = QLabel()
        self.value_label.setMinimumWidth(75)

        self.slider.valueChanged.connect(
            self._changed
        )

        layout.addWidget(
            self.label
        )

        layout.addWidget(
            self.slider,
            1
        )

        layout.addWidget(
            self.value_label
        )

        self._changed(
            self.slider.value()
        )

    def _changed(self, value):
        real_value = value * self.scale

        self.value_label.setText(
            f"{real_value:g}{self.suffix}"
        )

        self.callback(
            real_value
        )

    def set_real_value(self, value):
        self.slider.setValue(
            round(value / self.scale)
        )


# ============================================================
# MAIN WINDOW
# ============================================================

class BrushSettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "CreativeSystem — C++ Brush Settings"
        )

        self.resize(
            650,
            950
        )

        self.brush = lib.cs_brush_create()

        if not self.brush:
            raise RuntimeError(
                "Impossible de créer le BrushEngine C++."
            )

        self.preset_manager = (
            BrushPresetManager()
        )

        self.settings = {}

        self.base_color = QColor(
            20,
            60,
            220
        )

        self.gradient_color = QColor(
            220,
            70,
            180
        )

        self.slider_fields = {}

        self.check_fields = {}

        self.build_ui()

        self.load_default_values()

        self.refresh_presets()

        print(
            "CreativeCore Brush Settings Panel OK"
        )

        print(
            "Presets JSON + Color + Wet / Smudge connectés."
        )

    def __del__(self):
        brush = getattr(
            self,
            "brush",
            None
        )

        if brush:
            lib.cs_brush_destroy(
                brush
            )

            self.brush = None

    # ========================================================
    # C++ CALL
    # ========================================================

    def call(self, name, *args):
        getattr(lib, name)(
            self.brush,
            *args
        )

    # ========================================================
    # UI HELPERS
    # ========================================================

    def add_slider(
        self,
        layout,
        key,
        title,
        minimum,
        maximum,
        value,
        scale,
        suffix="",
    ):
        callback = (
            lambda value, key=key:
            self.set_float(
                key,
                value
            )
        )

        widget = SliderField(
            title,
            minimum,
            maximum,
            value,
            scale,
            callback,
            suffix
        )

        self.slider_fields[key] = widget

        layout.addWidget(
            widget
        )

    def add_check(
        self,
        layout,
        key,
        title,
        value=False,
    ):
        widget = QCheckBox(title)

        widget.setChecked(
            value
        )

        widget.stateChanged.connect(
            lambda state, key=key:
            self.set_bool(
                key,
                bool(state)
            )
        )

        self.check_fields[key] = widget

        layout.addWidget(
            widget
        )

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):
        scroll = QScrollArea()

        scroll.setWidgetResizable(
            True
        )

        container = QWidget()

        main = QVBoxLayout(
            container
        )

        title = QLabel(
            "CreativeSystem Brush Engine"
        )

        title.setStyleSheet(
            "font-size:24px;font-weight:700;"
        )

        subtitle = QLabel(
            "C++ BrushSettings + JSON Brush Presets"
        )

        subtitle.setStyleSheet(
            "color:#888;"
        )

        main.addWidget(title)
        main.addWidget(subtitle)

        # ====================================================
        # PRESETS
        # ====================================================

        preset_box = QGroupBox(
            "BRUSH PRESETS"
        )

        preset_layout = QVBoxLayout(
            preset_box
        )

        row = QHBoxLayout()

        self.preset_combo = QComboBox()

        row.addWidget(
            self.preset_combo,
            1
        )

        load_button = QPushButton(
            "Load"
        )

        load_button.clicked.connect(
            self.load_selected_preset
        )

        row.addWidget(
            load_button
        )

        preset_layout.addLayout(
            row
        )

        self.preset_name = QLineEdit()

        self.preset_name.setPlaceholderText(
            "Nom du nouveau preset..."
        )

        preset_layout.addWidget(
            self.preset_name
        )

        row = QHBoxLayout()

        save_button = QPushButton(
            "Save As"
        )

        save_button.clicked.connect(
            self.save_new_preset
        )

        row.addWidget(
            save_button
        )

        delete_button = QPushButton(
            "Delete"
        )

        delete_button.clicked.connect(
            self.delete_selected_preset
        )

        row.addWidget(
            delete_button
        )

        preset_layout.addLayout(
            row
        )

        path_label = QLabel(
            str(
                self.preset_manager.directory
            )
        )

        path_label.setWordWrap(True)
        path_label.setStyleSheet(
            "color:#777;font-size:11px;"
        )

        preset_layout.addWidget(
            path_label
        )

        main.addWidget(
            preset_box
        )

        # ====================================================
        # BASIC
        # ====================================================

        group = QGroupBox("BRUSH")
        layout = QVBoxLayout(group)

        self.add_slider(
            layout,
            "size",
            "Size",
            1,
            2000,
            50,
            1.0,
            " px"
        )

        self.add_slider(
            layout,
            "opacity",
            "Opacity",
            0,
            100,
            100,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "flow",
            "Flow",
            0,
            100,
            100,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "hardness",
            "Hardness",
            0,
            100,
            80,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "spacing",
            "Spacing",
            1,
            200,
            15,
            0.01
        )

        self.add_slider(
            layout,
            "roundness",
            "Roundness",
            1,
            100,
            100,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "angle",
            "Angle",
            0,
            360,
            0,
            1.0,
            "°"
        )

        main.addWidget(group)

        # ====================================================
        # JITTER
        # ====================================================

        group = QGroupBox(
            "SPACING / JITTER"
        )

        layout = QVBoxLayout(group)

        self.add_slider(
            layout,
            "scatter",
            "Scatter",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "sizeJitter",
            "Size Jitter",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "rotationJitter",
            "Rotation Jitter",
            0,
            180,
            0,
            1.0,
            "°"
        )

        main.addWidget(group)

        # ====================================================
        # TEXTURE
        # ====================================================

        group = QGroupBox(
            "TEXTURE"
        )

        layout = QVBoxLayout(group)

        self.add_slider(
            layout,
            "textureStrength",
            "Strength",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "textureScale",
            "Scale",
            1,
            1000,
            100,
            0.01
        )

        self.add_slider(
            layout,
            "textureRandomScale",
            "Random Scale",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "textureRandomOffset",
            "Random Offset",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "textureBrightness",
            "Brightness",
            -100,
            100,
            0,
            0.01
        )

        self.add_slider(
            layout,
            "textureContrast",
            "Contrast",
            0,
            300,
            100,
            0.01
        )

        self.add_check(
            layout,
            "textureMirror",
            "Mirror Texture"
        )

        self.add_check(
            layout,
            "textureAffectOpacity",
            "Affect Opacity",
            True
        )

        main.addWidget(group)

        # ====================================================
        # COLOR
        # ====================================================

        group = QGroupBox("COLOR")
        layout = QVBoxLayout(group)

        base_color = QPushButton(
            "Base Color"
        )

        base_color.clicked.connect(
            self.choose_base_color
        )

        layout.addWidget(
            base_color
        )

        gradient_color = QPushButton(
            "Gradient Color"
        )

        gradient_color.clicked.connect(
            self.choose_gradient_color
        )

        layout.addWidget(
            gradient_color
        )

        self.add_check(
            layout,
            "dirtyColor",
            "Dirty Color"
        )

        self.add_slider(
            layout,
            "hueJitter",
            "Hue Jitter",
            0,
            180,
            0,
            1.0,
            "°"
        )

        self.add_slider(
            layout,
            "saturationJitter",
            "Saturation Jitter",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "brightnessJitter",
            "Brightness Jitter",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_check(
            layout,
            "strokeGradient",
            "Stroke Gradient"
        )

        self.add_slider(
            layout,
            "gradientAmount",
            "Gradient Amount",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_check(
            layout,
            "linearGradient",
            "Linear Gradient",
            True
        )

        self.add_check(
            layout,
            "radialGradient",
            "Radial Gradient"
        )

        main.addWidget(group)

        # ====================================================
        # PAINT
        # ====================================================

        group = QGroupBox("PAINT")
        layout = QVBoxLayout(group)

        blend_row = QHBoxLayout()

        blend_row.addWidget(
            QLabel("Blend Mode")
        )

        self.blend_combo = QComboBox()

        self.blend_combo.addItems(
            [
                "Normal",
                "Multiply",
                "Screen",
                "Overlay",
                "Darken",
                "Lighten",
            ]
        )

        self.blend_combo.currentIndexChanged.connect(
            lambda index:
            self.set_int(
                "blendMode",
                index
            )
        )

        blend_row.addWidget(
            self.blend_combo,
            1
        )

        layout.addLayout(
            blend_row
        )

        self.add_slider(
            layout,
            "paintMix",
            "Paint Mix",
            0,
            100,
            100,
            0.01,
            "%"
        )

        main.addWidget(group)

        # ====================================================
        # WET
        # ====================================================

        group = QGroupBox(
            "WET / SMUDGE"
        )

        layout = QVBoxLayout(group)

        self.add_check(
            layout,
            "wetMix",
            "Enable Wet Mixing"
        )

        self.add_check(
            layout,
            "sampleCanvas",
            "Sample Canvas",
            True
        )

        self.add_slider(
            layout,
            "wetness",
            "Wetness",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "pickup",
            "Pickup",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "dilution",
            "Dilution",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "smudge",
            "Smudge",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "paintPersistence",
            "Paint Persistence",
            0,
            100,
            100,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "colorCarry",
            "Color Carry",
            0,
            100,
            100,
            0.01,
            "%"
        )

        main.addWidget(group)

        # ====================================================
        # PRESSURE
        # ====================================================

        group = QGroupBox(
            "PRESSURE"
        )

        layout = QVBoxLayout(group)

        self.add_check(
            layout,
            "pressureSize",
            "Pressure → Size",
            True
        )

        self.add_check(
            layout,
            "pressureOpacity",
            "Pressure → Opacity"
        )

        self.add_check(
            layout,
            "pressureFlow",
            "Pressure → Flow"
        )

        self.add_slider(
            layout,
            "minimumSize",
            "Minimum Size",
            0,
            100,
            1,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "minimumOpacity",
            "Minimum Opacity",
            0,
            100,
            0,
            0.01,
            "%"
        )

        self.add_slider(
            layout,
            "minimumFlow",
            "Minimum Flow",
            0,
            100,
            0,
            0.01,
            "%"
        )

        main.addWidget(group)

        # ====================================================
        # GENERAL
        # ====================================================

        group = QGroupBox("GENERAL")
        layout = QVBoxLayout(group)

        self.add_check(
            layout,
            "eraser",
            "Eraser"
        )

        main.addWidget(group)

        reset = QPushButton(
            "Reset"
        )

        reset.clicked.connect(
            self.reset_brush
        )

        main.addWidget(
            reset
        )

        main.addStretch()

        scroll.setWidget(
            container
        )

        self.setCentralWidget(
            scroll
        )

    # ========================================================
    # DEFAULTS
    # ========================================================

    def load_default_values(self):
        defaults = {
            "size": 50.0,
            "opacity": 1.0,
            "flow": 1.0,
            "hardness": 0.8,
            "spacing": 0.15,
            "roundness": 1.0,
            "angle": 0.0,
            "scatter": 0.0,
            "sizeJitter": 0.0,
            "rotationJitter": 0.0,

            "textureStrength": 0.0,
            "textureScale": 1.0,
            "textureRandomScale": 0.0,
            "textureRandomOffset": 0.0,
            "textureBrightness": 0.0,
            "textureContrast": 1.0,
            "textureMirror": False,
            "textureAffectOpacity": True,

            "dirtyColor": False,
            "hueJitter": 0.0,
            "saturationJitter": 0.0,
            "brightnessJitter": 0.0,

            "strokeGradient": False,
            "linearGradient": True,
            "radialGradient": False,
            "gradientAmount": 0.0,

            "blendMode": 0,
            "paintMix": 1.0,

            "wetMix": False,
            "sampleCanvas": True,
            "wetness": 0.0,
            "pickup": 0.0,
            "dilution": 0.0,
            "smudge": 0.0,
            "paintPersistence": 1.0,
            "colorCarry": 1.0,

            "pressureSize": True,
            "pressureOpacity": False,
            "pressureFlow": False,

            "minimumSize": 0.01,
            "minimumOpacity": 0.0,
            "minimumFlow": 0.0,

            "eraser": False,

            "color": [20, 60, 220, 255],
            "gradientColor": [220, 70, 180, 255],
        }

        self.apply_settings(
            defaults
        )

    # ========================================================
    # SETTINGS
    # ========================================================

    def set_float(
        self,
        key,
        value,
    ):
        self.settings[key] = float(value)

        api_names = {
            "size": "cs_brush_set_size",
            "opacity": "cs_brush_set_opacity",
            "flow": "cs_brush_set_flow",
            "hardness": "cs_brush_set_hardness",
            "spacing": "cs_brush_set_spacing",
            "roundness": "cs_brush_set_roundness",
            "angle": "cs_brush_set_angle",
            "scatter": "cs_brush_set_scatter",
            "sizeJitter": "cs_brush_set_size_jitter",
            "rotationJitter": "cs_brush_set_rotation_jitter",

            "textureStrength": "cs_brush_set_texture_strength",
            "textureScale": "cs_brush_set_texture_scale",
            "textureRandomScale": "cs_brush_set_texture_random_scale",
            "textureRandomOffset": "cs_brush_set_texture_random_offset",
            "textureBrightness": "cs_brush_set_texture_brightness",
            "textureContrast": "cs_brush_set_texture_contrast",

            "hueJitter": "cs_brush_set_hue_jitter",
            "saturationJitter": "cs_brush_set_saturation_jitter",
            "brightnessJitter": "cs_brush_set_brightness_jitter",
            "gradientAmount": "cs_brush_set_gradient_amount",

            "paintMix": "cs_brush_set_paint_mix",

            "wetness": "cs_brush_set_wetness",
            "pickup": "cs_brush_set_pickup",
            "dilution": "cs_brush_set_dilution",
            "smudge": "cs_brush_set_smudge",
            "paintPersistence": "cs_brush_set_paint_persistence",
            "colorCarry": "cs_brush_set_color_carry",

            "minimumSize": None,
            "minimumOpacity": None,
            "minimumFlow": None,
        }

        api_name = api_names.get(
            key
        )

        if api_name:
            self.call(
                api_name,
                ctypes.c_float(value)
            )

    def set_bool(
        self,
        key,
        value,
    ):
        self.settings[key] = bool(value)

        api_names = {
            "eraser": "cs_brush_set_eraser",
            "textureMirror": "cs_brush_set_texture_mirror",
            "textureAffectOpacity": "cs_brush_set_texture_affect_opacity",

            "dirtyColor": "cs_brush_set_dirty_color",
            "strokeGradient": "cs_brush_set_stroke_gradient",
            "linearGradient": "cs_brush_set_linear_gradient",
            "radialGradient": "cs_brush_set_radial_gradient",

            "wetMix": "cs_brush_set_wet_mix",
            "sampleCanvas": "cs_brush_set_sample_canvas",

            "pressureSize": None,
            "pressureOpacity": None,
            "pressureFlow": None,
        }

        api_name = api_names.get(
            key
        )

        if api_name:
            self.call(
                api_name,
                ctypes.c_int(
                    1 if value else 0
                )
            )

    def set_int(
        self,
        key,
        value,
    ):
        self.settings[key] = int(value)

        if key == "blendMode":
            self.call(
                "cs_brush_set_blend_mode",
                ctypes.c_int(value)
            )

    # ========================================================
    # COLORS
    # ========================================================

    def choose_base_color(self):
        current = QColor(
            *self.settings.get(
                "color",
                [20, 60, 220, 255]
            )
        )

        color = QColorDialog.getColor(
            current,
            self,
            "Brush Color"
        )

        if not color.isValid():
            return

        rgba = [
            color.red(),
            color.green(),
            color.blue(),
            color.alpha(),
        ]

        self.settings["color"] = rgba

        self.call(
            "cs_brush_set_color",
            ctypes.c_uint8(rgba[0]),
            ctypes.c_uint8(rgba[1]),
            ctypes.c_uint8(rgba[2]),
            ctypes.c_uint8(rgba[3]),
        )

    def choose_gradient_color(self):
        current = QColor(
            *self.settings.get(
                "gradientColor",
                [220, 70, 180, 255]
            )
        )

        color = QColorDialog.getColor(
            current,
            self,
            "Gradient Color"
        )

        if not color.isValid():
            return

        rgba = [
            color.red(),
            color.green(),
            color.blue(),
            color.alpha(),
        ]

        self.settings["gradientColor"] = rgba

        self.call(
            "cs_brush_set_gradient_color",
            ctypes.c_uint8(rgba[0]),
            ctypes.c_uint8(rgba[1]),
            ctypes.c_uint8(rgba[2]),
            ctypes.c_uint8(rgba[3]),
        )

    # ========================================================
    # APPLY
    # ========================================================

    def apply_settings(
        self,
        data,
    ):
        self.settings = {}

        for key, value in data.items():
            if key in (
                "name",
                "format",
                "version",
            ):
                continue

            if key in self.slider_fields:
                self.settings[key] = value

                self.slider_fields[key].set_real_value(
                    float(value)
                )

            elif key in self.check_fields:
                self.settings[key] = bool(value)

                self.check_fields[key].setChecked(
                    bool(value)
                )

            elif key == "blendMode":
                self.settings[key] = int(value)

                self.blend_combo.setCurrentIndex(
                    int(value)
                )

            elif key in (
                "color",
                "gradientColor",
            ):
                self.settings[key] = list(value)

        color = self.settings.get(
            "color"
        )

        if color:
            self.call(
                "cs_brush_set_color",
                ctypes.c_uint8(color[0]),
                ctypes.c_uint8(color[1]),
                ctypes.c_uint8(color[2]),
                ctypes.c_uint8(color[3]),
            )

        gradient = self.settings.get(
            "gradientColor"
        )

        if gradient:
            self.call(
                "cs_brush_set_gradient_color",
                ctypes.c_uint8(gradient[0]),
                ctypes.c_uint8(gradient[1]),
                ctypes.c_uint8(gradient[2]),
                ctypes.c_uint8(gradient[3]),
            )

        # Les callbacks des widgets ont appliqué
        # les paramètres C++ pendant la restauration.
        self.settings = self.normalized_settings(
            self.settings
        )

    def normalized_settings(
        self,
        data,
    ):
        result = {}

        for key, value in data.items():
            if isinstance(value, bool):
                result[key] = value
            elif isinstance(value, (int, float)):
                result[key] = value
            elif isinstance(value, list):
                result[key] = list(value)

        return result

    # ========================================================
    # PRESETS
    # ========================================================

    def refresh_presets(self):
        current = self.preset_combo.currentText()

        self.preset_combo.blockSignals(
            True
        )

        self.preset_combo.clear()

        self.preset_combo.addItems(
            self.preset_manager.list_presets()
        )

        index = self.preset_combo.findText(
            current
        )

        if index >= 0:
            self.preset_combo.setCurrentIndex(
                index
            )

        self.preset_combo.blockSignals(
            False
        )

    def load_selected_preset(self):
        name = self.preset_combo.currentText()

        if not name:
            return

        data = self.preset_manager.load(
            name
        )

        if data is None:
            QMessageBox.warning(
                self,
                "Preset",
                "Impossible de charger ce preset."
            )
            return

        self.apply_settings(
            data
        )

        self.preset_name.setText(
            name
        )

        print(
            f"Preset chargé : {name}"
        )

    def save_new_preset(self):
        name = (
            self.preset_name.text()
            .strip()
        )

        if not name:
            QMessageBox.warning(
                self,
                "Preset",
                "Entre un nom de preset."
            )
            return

        settings = dict(
            self.settings
        )

        path = self.preset_manager.save(
            name,
            settings
        )

        self.refresh_presets()

        index = self.preset_combo.findText(
            name
        )

        if index >= 0:
            self.preset_combo.setCurrentIndex(
                index
            )

        print(
            f"Preset sauvegardé : {path}"
        )

        QMessageBox.information(
            self,
            "Preset",
            f"Preset sauvegardé :\n{path}"
        )

    def delete_selected_preset(self):
        name = self.preset_combo.currentText()

        if not name:
            return

        answer = QMessageBox.question(
            self,
            "Supprimer le preset",
            f"Supprimer « {name} » ?"
        )

        if answer != QMessageBox.Yes:
            return

        if self.preset_manager.delete(
            name
        ):
            self.refresh_presets()

            print(
                f"Preset supprimé : {name}"
            )

    # ========================================================
    # RESET
    # ========================================================

    def reset_brush(self):
        self.load_default_values()

        self.preset_name.clear()

        print(
            "Brush reset."
        )


# ============================================================
# IMPORT LOCAL
# ============================================================

from TOOLS.brush_preset_manager import (
    BrushPresetManager,
)


# ============================================================
# MAIN
# ============================================================

def main():
    app = QApplication(
        sys.argv
    )

    window = BrushSettingsWindow()

    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(
        main()
    )
