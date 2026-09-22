from __future__ import annotations

import ctypes
from typing import Any

from TOOLS.brush_preset_manager import (
    BrushPresetManager,
)


class CppBrushPresetApplier:
    """
    Applique un preset JSON directement à un BrushEngine C++.

    Cette classe est utilisée par le Canvas réel.
    """

    def __init__(
        self,
        library,
        handle,
    ):
        self.library = library
        self.handle = handle

    # ========================================================
    # HELPERS
    # ========================================================

    def call_float(
        self,
        function_name: str,
        value: float,
    ):
        getattr(
            self.library,
            function_name,
        )(
            self.handle,
            ctypes.c_float(
                float(value)
            ),
        )

    def call_int(
        self,
        function_name: str,
        value: bool | int,
    ):
        getattr(
            self.library,
            function_name,
        )(
            self.handle,
            ctypes.c_int(
                int(bool(value))
            ),
        )

    # ========================================================
    # APPLY
    # ========================================================

    def apply(
        self,
        settings: dict[str, Any],
    ):
        float_map = {
            "size":
                "cs_brush_set_size",

            "opacity":
                "cs_brush_set_opacity",

            "flow":
                "cs_brush_set_flow",

            "hardness":
                "cs_brush_set_hardness",

            "spacing":
                "cs_brush_set_spacing",

            "roundness":
                "cs_brush_set_roundness",

            "angle":
                "cs_brush_set_angle",

            "scatter":
                "cs_brush_set_scatter",

            "sizeJitter":
                "cs_brush_set_size_jitter",

            "rotationJitter":
                "cs_brush_set_rotation_jitter",

            "velocitySize": "cs_brush_set_velocity_size",
            "velocityOpacity": "cs_brush_set_velocity_opacity",
            "velocityFlow": "cs_brush_set_velocity_flow",

            "textureStrength":
                "cs_brush_set_texture_strength",

            "textureScale":
                "cs_brush_set_texture_scale",

            "textureRandomScale":
                "cs_brush_set_texture_random_scale",

            "textureRandomOffset":
                "cs_brush_set_texture_random_offset",

            "textureBrightness":
                "cs_brush_set_texture_brightness",

            "textureContrast":
                "cs_brush_set_texture_contrast",

            "hueJitter":
                "cs_brush_set_hue_jitter",

            "saturationJitter":
                "cs_brush_set_saturation_jitter",

            "brightnessJitter":
                "cs_brush_set_brightness_jitter",

            "gradientAmount":
                "cs_brush_set_gradient_amount",

            "paintMix":
                "cs_brush_set_paint_mix",

            "wetness":
                "cs_brush_set_wetness",

            "pickup":
                "cs_brush_set_pickup",

            "dilution":
                "cs_brush_set_dilution",

            "smudge":
                "cs_brush_set_smudge",

            "paintPersistence":
                "cs_brush_set_paint_persistence",

            "colorCarry":
                "cs_brush_set_color_carry",

            "minimumSize":
                "cs_brush_set_minimum_size",

            "minimumOpacity":
                "cs_brush_set_minimum_opacity",

            "minimumFlow":
                "cs_brush_set_minimum_flow",
        }

        int_map = {
            "eraser":
                "cs_brush_set_eraser",

            "textureMirror":
                "cs_brush_set_texture_mirror",

            "textureAffectOpacity":
                "cs_brush_set_texture_affect_opacity",

            "dirtyColor":
                "cs_brush_set_dirty_color",

            "strokeGradient":
                "cs_brush_set_stroke_gradient",

            "linearGradient":
                "cs_brush_set_linear_gradient",

            "radialGradient":
                "cs_brush_set_radial_gradient",

            "wetMix":
                "cs_brush_set_wet_mix",

            "sampleCanvas":
                "cs_brush_set_sample_canvas",

            "smudgeTool":
                "cs_brush_set_smudge_tool",

            "pressureSize":
                "cs_brush_set_pressure_size",

            "pressureOpacity":
                "cs_brush_set_pressure_opacity",

            "pressureFlow":
                "cs_brush_set_pressure_flow",
        }

        for key, function_name in float_map.items():
            if key in settings:
                self.call_float(
                    function_name,
                    float(settings[key]),
                )

        for key, function_name in int_map.items():
            if key in settings:
                self.call_int(
                    function_name,
                    bool(settings[key]),
                )

        if "blendMode" in settings:
            self.library.cs_brush_set_blend_mode(
                self.handle,
                ctypes.c_int(
                    int(settings["blendMode"])
                ),
            )

        if "color" in settings:
            color = settings["color"]

            self.library.cs_brush_set_color(
                self.handle,
                ctypes.c_uint8(
                    int(color[0])
                ),
                ctypes.c_uint8(
                    int(color[1])
                ),
                ctypes.c_uint8(
                    int(color[2])
                ),
                ctypes.c_uint8(
                    int(color[3])
                ),
            )

        if "gradientColor" in settings:
            color = settings["gradientColor"]

            self.library.cs_brush_set_gradient_color(
                self.handle,
                ctypes.c_uint8(
                    int(color[0])
                ),
                ctypes.c_uint8(
                    int(color[1])
                ),
                ctypes.c_uint8(
                    int(color[2])
                ),
                ctypes.c_uint8(
                    int(color[3])
                ),
            )


class CanvasBrushPresetController:
    """
    Interface haut niveau utilisée par Canvas.
    """

    def __init__(
        self,
        library,
        handle,
    ):
        self.manager = (
            BrushPresetManager()
        )

        self.applier = (
            CppBrushPresetApplier(
                library,
                handle,
            )
        )

    def list_presets(self):
        return self.manager.list_presets()

    def load(self, name: str):
        settings = self.manager.load(
            name
        )

        if settings is None:
            return False

        self.applier.apply(
            settings
        )

        return True
