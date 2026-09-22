from __future__ import annotations

import json
import shutil
import zipfile
import base64
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from CORE.native_bridge import render_brush_preset_art_native


class BrushPresetManager:
    """
    Gestionnaire JSON pour les presets CreativeSystem.

    Les presets utilisateur sont stockés dans :
    ~/.local/share/CreativeSystem/brush_presets/
    """

    FORMAT_VERSION = 2

    def __init__(self, directory: str | Path | None = None, create_builtins: bool = True):
        self.directory = Path(directory) if directory is not None else (
            Path.home()
            / ".local"
            / "share"
            / "CreativeSystem"
            / "brush_presets"
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True
        )

        if create_builtins:
            self.create_builtin_presets()

    # ========================================================
    # PATHS
    # ========================================================

    def preset_path(self, name: str) -> Path:
        safe_name = (
            name.strip()
            .replace("/", "_")
            .replace("\\", "_")
        )

        if not safe_name:
            safe_name = "Unnamed"

        return self.directory / f"{safe_name}.json"

    # ========================================================
    # SAVE
    # ========================================================

    def save(
        self,
        name: str,
        settings: dict,
    ) -> Path:
        path = self.preset_path(name)

        previous = self.load(name) or {}
        if previous.get("builtIn") and not getattr(self, "_installing_builtins", False):
            raise PermissionError(f"Built-in brush preset is read-only: {name}")
        data = deepcopy(settings)

        data["name"] = name
        data["format"] = "CreativeSystemBrushPreset"
        data["version"] = self.FORMAT_VERSION
        data["category"] = str(previous.get("category", "General"))
        data["favorite"] = bool(previous.get("favorite", False))

        path.write_text(
            json.dumps(
                data,
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    # ========================================================
    # LOAD
    # ========================================================

    def load(self, name: str) -> dict | None:
        path = self.preset_path(name)

        if not path.exists():
            return None

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None

        return data

    # ========================================================
    # DELETE
    # ========================================================

    def delete(self, name: str) -> bool:
        path = self.preset_path(name)

        if not path.exists():
            return False
        if (self.load(name) or {}).get("builtIn"):
            return False

        try:
            path.unlink()
        except OSError:
            return False

        return True

    # ========================================================
    # LIST
    # ========================================================

    def list_presets(self) -> list[str]:
        result = []

        for path in sorted(
            self.directory.glob("*.json")
        ):
            result.append(
                path.stem
            )

        return result

    def metadata(self, name: str) -> dict:
        data = self.load(name) or {}
        return {
            "name": name,
            "category": str(data.get("category", "General")),
            "favorite": bool(data.get("favorite", False)),
            "version": int(data.get("version", 1)),
            "builtIn": bool(data.get("builtIn", False)),
        }

    def set_metadata(self, name: str, **values) -> bool:
        data = self.load(name)
        if data is None:
            return False
        if data.get("builtIn"):
            return False
        if "category" in values:
            data["category"] = str(values["category"] or "General")
        if "favorite" in values:
            data["favorite"] = bool(values["favorite"])
        data["version"] = self.FORMAT_VERSION
        self.preset_path(name).write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        return True

    def duplicate(self, name: str, new_name: str) -> Path | None:
        data = self.load(name)
        if data is None:
            return None
        data.pop("name", None)
        data.pop("builtIn", None)
        category = data.get("category", "General")
        favorite = data.get("favorite", False)
        path = self.save(new_name, data)
        self.set_metadata(new_name, category=category, favorite=favorite)
        return path

    def export_preset(self, name: str, destination: str | Path) -> bool:
        source = self.preset_path(name)
        if not source.exists():
            return False
        shutil.copy2(source, Path(destination))
        return True

    def import_preset(self, source: str | Path) -> str | None:
        source = Path(source)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("format") != "CreativeSystemBrushPreset":
            return None
        name = str(data.get("name") or source.stem).strip()
        if not name:
            return None
        data["version"] = self.FORMAT_VERSION
        self.preset_path(name).write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        return name

    @staticmethod
    def _png_bytes(image: QImage) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise OSError("Could not encode brush PNG")
        buffer.close()
        return bytes(data)

    @staticmethod
    def _brush_art(settings: dict) -> tuple[bytes, bytes]:
        """Create a neutral tip texture and visible preset preview."""
        hardness = max(0.0, min(1.0, float(settings.get("hardness", 1.0))))
        texture = QImage(64, 64, QImage.Format.Format_ARGB32)
        preview = QImage(128, 64, QImage.Format.Format_ARGB32)
        color_values = settings.get("color", [220, 220, 220, 255])
        color = QColor(*[max(0, min(255, int(v))) for v in color_values[:4]])
        preview_size = max(5.0, min(52.0, float(settings.get("size", 25)) * 0.5))
        if not render_brush_preset_art_native(texture, preview, hardness, preview_size, color):
            raise RuntimeError("CreativeCore is required to build brush preset art")
        return BrushPresetManager._png_bytes(texture), BrushPresetManager._png_bytes(preview)

    def export_csbr(self, name: str, destination: str | Path) -> bool:
        settings = self.load(name)
        if settings is None:
            return False
        try:
            texture = base64.b64decode(settings["_csbr_texture_png"], validate=True) if settings.get("_csbr_texture_png") else None
            preview = base64.b64decode(settings["_csbr_preview_png"], validate=True) if settings.get("_csbr_preview_png") else None
            bitmap_tip = base64.b64decode(settings["_csbr_bitmap_tip_png"], validate=True) if settings.get("_csbr_bitmap_tip_png") else None
            if bitmap_tip is not None:
                image = QImage()
                if (len(bitmap_tip) > 32 * 1024 * 1024
                        or not bitmap_tip.startswith(b"\x89PNG\r\n\x1a\n")
                        or not image.loadFromData(bitmap_tip)
                        or image.width() > 4096 or image.height() > 4096):
                    return False
            if texture is None or preview is None:
                generated_texture, generated_preview = self._brush_art(settings)
                texture = texture or generated_texture
                preview = preview or generated_preview
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("brush.json", json.dumps(settings, indent=2, ensure_ascii=False))
                archive.writestr("texture.png", texture)
                archive.writestr("preview.png", preview)
                if bitmap_tip is not None:
                    archive.writestr("bitmap_tip.png", bitmap_tip)
            return True
        except (OSError, ValueError, TypeError, zipfile.BadZipFile):
            return False

    def import_csbr(self, source: str | Path) -> str | None:
        try:
            with zipfile.ZipFile(source, "r") as archive:
                names = set(archive.namelist())
                if set(("brush.json", "texture.png", "preview.png")) - names:
                    return None
                if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
                    return None
                settings = json.loads(archive.read("brush.json").decode("utf-8"))
                images = {}
                for image_name in ("texture.png", "preview.png"):
                    image = QImage()
                    image_data = archive.read(image_name)
                    if not image.loadFromData(image_data):
                        return None
                    images[image_name] = image_data
                if not isinstance(settings, dict):
                    return None
                name = str(settings.get("name") or Path(source).stem).strip()
                if not name or settings.get("format") != "CreativeSystemBrushPreset":
                    return None
                settings["name"] = name
                settings["version"] = self.FORMAT_VERSION
                settings["_csbr_texture_png"] = base64.b64encode(images["texture.png"]).decode("ascii")
                settings["_csbr_preview_png"] = base64.b64encode(images["preview.png"]).decode("ascii")
                if "bitmap_tip.png" in names:
                    bitmap_tip = archive.read("bitmap_tip.png")
                    image = QImage()
                    if (len(bitmap_tip) > 32 * 1024 * 1024
                            or not bitmap_tip.startswith(b"\x89PNG\r\n\x1a\n")
                            or not image.loadFromData(bitmap_tip)
                            or image.width() > 4096 or image.height() > 4096):
                        return None
                    settings["_csbr_bitmap_tip_png"] = base64.b64encode(bitmap_tip).decode("ascii")
                self.preset_path(name).write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
                return name
        except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    # ========================================================
    # BUILTIN PRESETS
    # ========================================================

    def create_builtin_presets(self):
        presets = {
            "Pencil": {
                "size": 8.0,
                "opacity": 0.75,
                "flow": 0.65,
                "hardness": 0.55,
                "spacing": 0.12,
                "roundness": 0.9,
                "angle": 0.0,
                "scatter": 0.01,
                "sizeJitter": 0.10,
                "rotationJitter": 2.0,

                "textureStrength": 0.25,
                "textureScale": 1.4,
                "textureRandomScale": 0.10,
                "textureRandomOffset": 0.10,
                "textureBrightness": 0.0,
                "textureContrast": 1.1,
                "textureMirror": True,
                "textureAffectOpacity": True,

                "dirtyColor": False,
                "hueJitter": 0.0,
                "saturationJitter": 0.02,
                "brightnessJitter": 0.05,

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

                "color": [30, 30, 30, 255],
                "gradientColor": [255, 255, 255, 255],
            },

            "Ink": {
                "size": 12.0,
                "opacity": 1.0,
                "flow": 1.0,
                "hardness": 0.95,
                "spacing": 0.08,
                "roundness": 1.0,
                "angle": 0.0,
                "scatter": 0.0,
                "sizeJitter": 0.03,
                "rotationJitter": 0.0,

                "textureStrength": 0.08,
                "textureScale": 1.0,
                "textureRandomScale": 0.03,
                "textureRandomOffset": 0.03,
                "textureBrightness": 0.0,
                "textureContrast": 1.15,
                "textureMirror": False,
                "textureAffectOpacity": True,

                "dirtyColor": False,
                "hueJitter": 0.0,
                "saturationJitter": 0.0,
                "brightnessJitter": 0.02,

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
                "pressureOpacity": True,
                "pressureFlow": False,

                "minimumSize": 0.02,
                "minimumOpacity": 0.0,
                "minimumFlow": 0.0,

                "eraser": False,

                "color": [10, 10, 10, 255],
                "gradientColor": [255, 255, 255, 255],
            },

            "Paint": {
                "size": 70.0,
                "opacity": 0.85,
                "flow": 0.70,
                "hardness": 0.35,
                "spacing": 0.18,
                "roundness": 0.95,
                "angle": 0.0,
                "scatter": 0.03,
                "sizeJitter": 0.08,
                "rotationJitter": 8.0,

                "textureStrength": 0.30,
                "textureScale": 1.2,
                "textureRandomScale": 0.15,
                "textureRandomOffset": 0.12,
                "textureBrightness": 0.0,
                "textureContrast": 0.9,
                "textureMirror": True,
                "textureAffectOpacity": True,

                "dirtyColor": True,
                "hueJitter": 5.0,
                "saturationJitter": 0.08,
                "brightnessJitter": 0.06,

                "strokeGradient": False,
                "linearGradient": True,
                "radialGradient": False,
                "gradientAmount": 0.0,

                "blendMode": 0,
                "paintMix": 1.0,

                "wetMix": True,
                "sampleCanvas": True,
                "wetness": 0.45,
                "pickup": 0.30,
                "dilution": 0.20,
                "smudge": 0.15,
                "paintPersistence": 0.75,
                "colorCarry": 0.85,

                "pressureSize": True,
                "pressureOpacity": True,
                "pressureFlow": True,

                "minimumSize": 0.05,
                "minimumOpacity": 0.15,
                "minimumFlow": 0.10,

                "eraser": False,

                "color": [210, 80, 70, 255],
                "gradientColor": [255, 210, 80, 255],
            },

            "Charcoal": {
                "size": 90.0,
                "opacity": 0.62,
                "flow": 0.55,
                "hardness": 0.22,
                "spacing": 0.25,
                "roundness": 0.75,
                "angle": 15.0,
                "scatter": 0.12,
                "sizeJitter": 0.18,
                "rotationJitter": 25.0,

                "textureStrength": 0.65,
                "textureScale": 1.7,
                "textureRandomScale": 0.25,
                "textureRandomOffset": 0.25,
                "textureBrightness": 0.05,
                "textureContrast": 1.4,
                "textureMirror": True,
                "textureAffectOpacity": True,

                "dirtyColor": True,
                "hueJitter": 1.0,
                "saturationJitter": 0.04,
                "brightnessJitter": 0.10,

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
                "smudge": 0.05,
                "paintPersistence": 1.0,
                "colorCarry": 1.0,

                "pressureSize": True,
                "pressureOpacity": True,
                "pressureFlow": False,

                "minimumSize": 0.03,
                "minimumOpacity": 0.0,
                "minimumFlow": 0.0,

                "eraser": False,

                "color": [45, 42, 40, 255],
                "gradientColor": [180, 175, 165, 255],
            },
        }

        for name, settings in presets.items():
            path = self.preset_path(name)

            if not path.exists():
                self.save(
                    name,
                    settings
                )

        # Clean, ready-to-paint defaults requested for the first-run brush pack.
        pack = {
            "Round Hard": dict(size=25.0, opacity=1.0, flow=1.0, hardness=1.0, spacing=0.10, roundness=1.0, angle=0.0),
            "Round Soft": dict(size=40.0, opacity=1.0, flow=1.0, hardness=0.0, spacing=0.10, roundness=1.0, angle=0.0),
            "Round Soft Flow": dict(size=40.0, opacity=1.0, flow=0.3, hardness=0.0, spacing=0.10, roundness=1.0, angle=0.0),
            "Flat Hard": dict(size=35.0, opacity=1.0, flow=1.0, hardness=1.0, spacing=0.10, roundness=0.3, angle=0.0),
            "Flat Soft": dict(size=35.0, opacity=1.0, flow=1.0, hardness=0.3, spacing=0.10, roundness=0.3, angle=0.0),
            "Ink Pen": dict(size=12.0, opacity=1.0, flow=1.0, hardness=1.0, spacing=0.05, roundness=1.0, angle=0.0, pressureSize=True, pressureOpacity=True),
            "Airbrush": dict(size=100.0, opacity=1.0, flow=0.2, hardness=0.0, spacing=0.05, roundness=1.0, angle=0.0),
            "Eraser Soft": dict(size=40.0, opacity=1.0, flow=1.0, hardness=0.0, spacing=0.10, roundness=1.0, angle=0.0, eraser=True),
            "Eraser Hard": dict(size=25.0, opacity=1.0, flow=1.0, hardness=1.0, spacing=0.10, roundness=1.0, angle=0.0, eraser=True),
        }
        common = {
            "scatter": 0.0, "sizeJitter": 0.0, "rotationJitter": 0.0,
            "textureStrength": 0.0, "textureScale": 1.0,
            "textureRandomScale": 0.0, "textureRandomOffset": 0.0,
            "textureBrightness": 0.0, "textureContrast": 1.0,
            "textureMirror": False, "textureAffectOpacity": True,
            "dirtyColor": False, "hueJitter": 0.0, "saturationJitter": 0.0,
            "brightnessJitter": 0.0, "strokeGradient": False,
            "linearGradient": True, "radialGradient": False, "gradientAmount": 0.0,
            "blendMode": 0, "paintMix": 1.0, "wetMix": False,
            "sampleCanvas": True, "wetness": 0.0, "pickup": 0.0,
            "dilution": 0.0, "smudge": 0.0, "paintPersistence": 1.0,
            "colorCarry": 1.0, "pressureSize": False,
            "pressureOpacity": False, "pressureFlow": False,
            "minimumSize": 0.01, "minimumOpacity": 0.0,
            "minimumFlow": 0.0, "eraser": False,
            "color": [30, 30, 30, 255], "gradientColor": [255, 255, 255, 255],
        }
        self._installing_builtins = True
        try:
            for name, values in pack.items():
                path = self.preset_path(name)
                if path.exists():
                    continue
                settings = {**common, **values}
                data = {
                    **settings, "name": name, "format": "CreativeSystemBrushPreset",
                    "version": self.FORMAT_VERSION, "category": "Basic Brushes",
                    "favorite": False, "builtIn": True,
                }
                path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        finally:
            self._installing_builtins = False
