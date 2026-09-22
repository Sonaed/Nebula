from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


DEFAULT_BRUSH_SETTINGS: dict[str, Any] = {
    "size": 10.0,
    "opacity": 1.0,
    "flow": 1.0,
    "hardness": 0.8,
    "spacing": 0.15,
    "roundness": 1.0,
    "angle": 0.0,
    "scatter": 0.0,
    "sizeJitter": 0.0,
    "rotationJitter": 0.0,
    # Advanced dynamics (shared by the Python engine and future C++ inputs).
    "velocitySize": 0.0,
    "velocityOpacity": 0.0,
    "velocityFlow": 0.0,
    "tiltSize": 0.0,
    "tiltOpacity": 0.0,
    "tiltAngle": 0.0,
    "randomSize": 0.0,
    "randomOpacity": 0.0,
    "adaptiveSpacing": False,
    "pressureSpacing": 0.0,
    "velocitySpacing": 0.0,
    "pressureSize": True,
    "pressureOpacity": False,
    "pressureFlow": False,
    "minimumSize": 0.01,
    "minimumOpacity": 0.0,
    "minimumFlow": 0.0,
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
    "gradientColor": [255, 255, 255, 255],
    "blendMode": 0,
    "paintMix": 1.0,
    "wetness": 0.0,
    "pickup": 0.0,
    "dilution": 0.0,
    "smudge": 0.0,
    "paintPersistence": 1.0,
    "colorCarry": 1.0,
    "wetMix": False,
    "sampleCanvas": True,
    "smudgeTool": False,
    "eraser": False,
    "color": [0, 0, 0, 255],
}


class BrushSettingsState:
    """Unique application-side state mirrored to every brush backend."""

    def __init__(
        self,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._values = deepcopy(DEFAULT_BRUSH_SETTINGS)
        self._on_change = on_change

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._values.get(key, default))

    def update(
        self,
        values: dict[str, Any],
        *,
        notify: bool = True,
    ) -> dict[str, Any]:
        known = {
            key: deepcopy(value)
            for key, value in values.items()
            if key in DEFAULT_BRUSH_SETTINGS
        }
        self._values.update(known)
        if notify and known and self._on_change is not None:
            self._on_change(self.snapshot())
        return self.snapshot()

    def set(self, key: str, value: Any) -> dict[str, Any]:
        if key not in DEFAULT_BRUSH_SETTINGS:
            raise KeyError(f"Paramètre de brush inconnu : {key}")
        return self.update({key: value})
