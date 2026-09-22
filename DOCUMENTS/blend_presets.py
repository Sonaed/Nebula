from __future__ import annotations

import json
import zipfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
from PySide6.QtGui import QColor, QImage

from DOCUMENTS.blend_modes import BLEND_MODES, composite_layers
from DOCUMENTS.layer import Layer
from CORE.native_bridge import fill_image_native, fill_image_rect_native


_COMMON_BLEND_PARAMS = [
    {"key": "opacity", "name": "Opacity", "min": 0.0, "max": 1.0,
     "default": 1.0, "uniform": "opacity", "step": 0.01},
    {"key": "opposite_mix", "name": "Mix Opposé", "min": 0.0, "max": 1.0,
     "default": 0.0, "uniform": "opposite_mix", "step": 0.01},
]

_MODE_BLEND_PARAMS = {
    "multiply": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "gamma", "name": "Gamma", "min": 0.5, "max": 2.5, "default": 1.0, "uniform": "gamma_value", "step": 0.1},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "screen": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "gamma", "name": "Gamma", "min": 0.5, "max": 2.5, "default": 1.0, "uniform": "gamma_value", "step": 0.1},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "overlay": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "pivot", "name": "Pivot", "min": 0.0, "max": 1.0, "default": 0.5, "uniform": "pivot", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "hard_light": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "pivot", "name": "Pivot", "min": 0.0, "max": 1.0, "default": 0.5, "uniform": "pivot", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "color_dodge": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "clamp", "name": "Clamp", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "clamp_value", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "color_burn": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "clamp", "name": "Clamp", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "clamp_value", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "soft_light": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "softness", "name": "Softness", "min": 0.0, "max": 1.0, "default": 0.5, "uniform": "softness", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "hue": [], "saturation": [], "color": [], "luminosity": [],
    "difference": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "offset", "name": "Offset", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "offset_value", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
    "exclusion": [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "offset", "name": "Offset", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "offset_value", "step": 0.01},
        {"key": "mix_normal", "name": "Mix Normal", "min": 0.0, "max": 1.0, "default": 0.0, "uniform": "mix_normal", "step": 0.01},
    ],
}
for _mode in ("hue", "saturation", "color", "luminosity"):
    _MODE_BLEND_PARAMS[_mode] = [
        {"key": "intensity", "name": "Intensity", "min": 0.0, "max": 1.0, "default": 1.0, "uniform": "intensity", "step": 0.01},
        {"key": "hue_shift", "name": "Hue Shift", "min": -180.0, "max": 180.0, "default": 0.0, "uniform": "hue_shift", "step": 1.0},
        {"key": "saturation_boost", "name": "Sat Boost", "min": 0.0, "max": 2.0, "default": 1.0, "uniform": "saturation_boost", "step": 0.01},
    ]

BLEND_PARAMS = {
    mode: [dict(parameter) for parameter in (_MODE_BLEND_PARAMS.get(mode, []) + _COMMON_BLEND_PARAMS)]
    for mode in BLEND_MODES
}


class BlendPresetManager:
    """Read-only defaults and editable user copies for layer blend settings."""

    FORMAT = "CreativeSystemBlendPreset"
    VERSION = 1

    @classmethod
    def parameter_specs(cls, mode: str) -> list[tuple[str, str, float, float, float, float]]:
        return [
            (item["key"], item["name"], item["min"], item["max"], item["step"], item["default"])
            for item in BLEND_PARAMS.get(mode, BLEND_PARAMS["normal"])
        ]

    @classmethod
    def default_parameters(cls, mode: str) -> dict[str, float]:
        return {
            item["key"]: item["default"]
            for item in BLEND_PARAMS.get(mode, BLEND_PARAMS["normal"])
            if item["key"] != "opacity"
        }

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else (
            Path.home() / ".local" / "share" / "CreativeSystem" / "blend_presets"
        )
        self.directory.mkdir(parents=True, exist_ok=True)

    def _preset_path(self, name: str) -> Path:
        safe_name = name.strip().replace("/", "_").replace("\\", "_") or "Unnamed"
        return self.directory / f"{safe_name}.json"

    @classmethod
    def defaults(cls) -> dict[str, dict]:
        result = {}
        for mode in BLEND_MODES:
            params = {item["key"]: item["default"] for item in BLEND_PARAMS[mode]}
            name = mode.replace("_", " ").title()
            result[name] = {"format": cls.FORMAT, "version": cls.VERSION,
                            "name": name, "mode": mode, "parameters": params}
        return result

    def list_presets(self) -> list[str]:
        return sorted(set(self.defaults()) | {path.stem for path in self.directory.glob("*.json")})

    def is_builtin(self, name: str) -> bool:
        return name in self.defaults()

    def load(self, name: str) -> dict | None:
        if name in self.defaults():
            return self.defaults()[name]
        try:
            data = json.loads(self._preset_path(name).read_text(encoding="utf-8"))
            return data if self._valid(data) else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _valid(data: dict) -> bool:
        if not isinstance(data, dict) or data.get("format") != BlendPresetManager.FORMAT:
            return False
        mode = data.get("mode")
        params = data.get("parameters")
        if mode not in BLEND_MODES or not isinstance(params, dict):
            return False
        ranges = {
            item["key"]: (item["min"], item["max"])
            for item in BLEND_PARAMS.get(mode, BLEND_PARAMS["normal"])
        }
        try:
            return all(key in ranges and ranges[key][0] <= float(value) <= ranges[key][1]
                       for key, value in params.items())
        except (TypeError, ValueError):
            return False

    def save(self, name: str, preset: dict) -> bool:
        name = name.strip()
        normalized = {
            "format": self.FORMAT,
            "version": self.VERSION,
            "mode": preset.get("mode") if isinstance(preset, dict) else None,
            "parameters": preset.get("parameters") if isinstance(preset, dict) else None,
        }
        if not name or self.is_builtin(name) or not self._valid(normalized):
            return False
        data = {**normalized, "name": name}
        try:
            self._preset_path(name).write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except OSError:
            return False

    def duplicate(self, name: str, new_name: str) -> bool:
        preset = self.load(name)
        return bool(preset and self.save(new_name, preset))

    @staticmethod
    def _png(image: QImage) -> bytes:
        data = QByteArray(); buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise OSError("Could not encode blend preview")
        buffer.close(); return bytes(data)

    @classmethod
    @lru_cache(maxsize=16)
    def _preview(cls, mode: str, parameter_values: tuple = ()) -> bytes:
        base = Layer("Preview Base", 128, 48)
        if not fill_image_native(base.image, QColor("#9B1F35")):
            raise RuntimeError("CreativeCore is required to build blend previews")
        top = Layer("Preview Blend", 128, 48)
        top.blend_mode = mode
        top.blend_parameters = cls.default_parameters(mode)
        top.blend_parameters.update(dict(parameter_values))
        if not fill_image_rect_native(top.image, QRect(40, 8, 48, 32),
                                      QColor("#b0b0b0")):
            raise RuntimeError("CreativeCore is required to build blend previews")
        return cls._png(composite_layers(128, 48, [base, top]))

    def export_csbl(self, name: str, destination: str | Path) -> bool:
        preset = self.load(name)
        if preset is None:
            return False
        try:
            payload = {"format": self.FORMAT, "version": self.VERSION, "name": name,
                       "mode": preset["mode"], "parameters": preset["parameters"]}
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("blend.json", json.dumps(payload, indent=2))
                archive.writestr("preview.png", self._preview(preset["mode"], tuple(sorted(preset["parameters"].items()))))
            return True
        except (OSError, ValueError, zipfile.BadZipFile):
            return False

    def preview_png(self, name: str) -> bytes | None:
        preset = self.load(name)
        return self._preview(preset["mode"], tuple(sorted(preset["parameters"].items()))) if preset else None

    def import_csbl(self, source: str | Path) -> str | None:
        try:
            with zipfile.ZipFile(source) as archive:
                if set(("blend.json", "preview.png")) - set(archive.namelist()):
                    return None
                if sum(item.file_size for item in archive.infolist()) > 8 * 1024 * 1024:
                    return None
                data = json.loads(archive.read("blend.json").decode("utf-8"))
                image = QImage()
                if not image.loadFromData(archive.read("preview.png")) or not self._valid(data):
                    return None
                name = str(data.get("name", Path(source).stem)).strip()
                if not name or self.is_builtin(name):
                    return None
                return name if self.save(name, data) else None
        except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
            return None
