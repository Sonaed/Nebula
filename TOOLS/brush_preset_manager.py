from __future__ import annotations

import copy
import json
import shutil
import zipfile
import base64
import hashlib
import os
import tempfile
import math
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

    FORMAT_VERSION = 3
    CSBR_FORMAT = "CreativeSystemBrushPackage"
    MAX_CSBR_BYTES = 64 * 1024 * 1024
    MAX_CSBR_ENTRY_BYTES = 32 * 1024 * 1024
    MAX_CSBR_ENTRIES = 5
    CATEGORY_FILE = ".categories.json"
    BUILTIN_CATEGORIES = {
        "Pencil": "01_Sketching", "Ink": "02_Inking", "Ink Pen": "02_Inking",
        "Paint": "03_Painting", "Round Hard": "03_Painting", "Round Soft": "03_Painting",
        "Round Soft Flow": "03_Painting", "Flat Hard": "03_Painting", "Flat Soft": "03_Painting",
        "Airbrush": "04_Airbrush", "Charcoal": "05_Texture", "Paint": "03_Painting",
        "Eraser Soft": "06_Erasers", "Eraser Hard": "06_Erasers",
    }
    DEFAULT_FAVORITES = {"Pencil HB", "Ink Pen", "Round Soft", "Oil Round", "Airbrush Soft", "Eraser Soft"}
    LEGACY_PRESETS = {"Pencil", "Ink", "Paint", "Round Soft Flow", "Flat Hard", "Flat Soft", "Airbrush"}

    # Factory presets ship with French names.  The English names (and the
    # pre-26 legacy names) stay valid aliases for scripts and old files.
    FRENCH_NAMES = {
        "Pencil HB": "Crayon HB", "Pencil 2B": "Crayon 2B", "Pencil 4H": "Crayon 4H",
        "Mechanical Pencil": "Porte-mine", "Blue Sketch": "Esquisse légère",
        "Col Erase": "Crayon effaçable", "Ink Brush": "Pinceau encre", "Fineliner": "Feutre fin",
        "Marker": "Marqueur", "G-Pen": "Plume G", "Ink Pen": "Stylo encre",
        "Oil Round": "Huile ronde", "Oil Flat": "Huile plate", "Watercolor": "Aquarelle",
        "Gouache": "Gouache", "Blender": "Mélangeur", "Round Hard": "Rond dur",
        "Round Soft": "Rond doux", "Airbrush Soft": "Aérographe doux",
        "Airbrush Hard": "Aérographe dur", "Spray": "Bombe", "Glow": "Lueur", "Chalk": "Craie",
        "Conte": "Conté", "Dry Brush": "Brosse sèche", "Stipple": "Pointillé",
        "Charcoal": "Fusain", "Eraser Soft": "Gomme douce", "Eraser Hard": "Gomme dure",
        "Eraser Pencil": "Gomme crayon", "Eraser Airbrush": "Gomme aérographe",
        "Smudge": "Estompe", "Pixel": "Pixel", "Concept Block": "Aplat",
    }
    ENGLISH_NAMES = {french: english for english, french in FRENCH_NAMES.items()}
    ALIASES = {**FRENCH_NAMES, "Pencil": "Crayon HB", "Ink": "Stylo encre", "Paint": "Huile ronde",
               "Airbrush": "Aérographe doux", "Round Soft Flow": "Rond doux",
               "Flat Hard": "Rond dur", "Flat Soft": "Rond doux"}

    @classmethod
    def canonical(cls, name: str) -> str:
        """Current name of a preset, resolving English and legacy aliases."""
        name = str(name).strip()
        return cls.ALIASES.get(name, name)

    def __init__(self, directory: str | Path | None = None, create_builtins: bool = True):
        self.last_error = ""
        configured_root = os.environ.get("CREATIVE_SYSTEM_DATA_HOME", "").strip()
        default_root = (Path(configured_root) if configured_root else
                        Path.home() / ".local" / "share" / "CreativeSystem")
        self.directory = (Path(directory) if directory is not None else
                          default_root / "brush_presets")

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A portable/read-only install must still be able to launch and
            # paint.  Keep an ephemeral, process-safe preset library instead
            # of failing Canvas construction because the preferred user data
            # location is unavailable.
            self.directory = Path(tempfile.gettempdir()) / "CreativeSystem" / "brush_presets"
            self.directory.mkdir(parents=True, exist_ok=True)

        if create_builtins and self._builtins_current():
            create_builtins = False
        if create_builtins:
            try:
                self.create_builtin_presets()
            except OSError:
                # A directory may already exist yet still be mounted
                # read-only. Retry builtin installation in the session cache.
                self.directory = Path(tempfile.gettempdir()) / "CreativeSystem" / "brush_presets"
                self.directory.mkdir(parents=True, exist_ok=True)
                self.create_builtin_presets()
            self._remember_builtins()

    # ========================================================
    # PATHS
    # ========================================================

    def preset_path(self, name: str) -> Path:
        safe_name = (
            self.canonical(name)
            .replace("/", "_")
            .replace("\\", "_")
        )

        if not safe_name:
            safe_name = "Unnamed"

        return self.directory / f"{safe_name}.json"

    @staticmethod
    def _valid_preset_name(value: object) -> str | None:
        name = str(value or "").strip()
        if (not name or len(name) > 128 or name in {".", ".."}
                or Path(name).name != name or any(part == ".." for part in Path(name).parts)):
            return None
        return name

    @classmethod
    def _validate_settings(cls, data: object, fallback_name: str | None = None) -> dict | None:
        """Validate the portable metadata before it reaches the preset library."""
        if not isinstance(data, dict) or data.get("format") != "CreativeSystemBrushPreset":
            return None
        name = cls._valid_preset_name(data.get("name") or fallback_name)
        if name is None:
            return None
        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError):
            return None
        # Future formats must be rejected instead of silently losing settings.
        if version < 1 or version > cls.FORMAT_VERSION:
            return None
        validated = deepcopy(data)
        validated["name"] = name
        validated["format"] = "CreativeSystemBrushPreset"
        validated["version"] = cls.FORMAT_VERSION
        return validated

    @staticmethod
    def _atomic_json_write(path: Path, data: dict) -> None:
        encoded = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

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

        self._atomic_json_write(path, data)

        return path

    # ========================================================
    # LOAD
    # ========================================================

    # Several managers are created at start-up (canvas, docks, resources):
    # install/migrate the factory presets once per library state, and parse
    # each JSON file once per modification instead of on every lookup.
    _BUILTIN_STAMPS: dict[str, int] = {}
    _LOAD_CACHE: dict[str, tuple[tuple[int, int, int], dict]] = {}

    def _directory_stamp(self) -> int:
        try:
            return self.directory.stat().st_mtime_ns
        except OSError:
            return -1

    def _builtins_current(self) -> bool:
        return self._BUILTIN_STAMPS.get(str(self.directory)) == self._directory_stamp()

    def _remember_builtins(self) -> None:
        self._BUILTIN_STAMPS[str(self.directory)] = self._directory_stamp()

    def load(self, name: str) -> dict | None:
        path = self.preset_path(name)

        try:
            stat = path.stat()
        except OSError:
            return None
        key = str(path)
        # Inode included: every save is an atomic replace (new inode), so a
        # coarse-mtime filesystem cannot serve a stale preset.
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = self._LOAD_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return copy.deepcopy(cached[1])

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
        if isinstance(data, dict):
            self._LOAD_CACHE[key] = (signature, copy.deepcopy(data))

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
            if path.name != self.CATEGORY_FILE and not ((self.load(path.stem) or {}).get("_legacy_builtin")):
                result.append(path.stem)

        return result

    def categories(self) -> list[str]:
        path = self.directory / self.CATEGORY_FILE
        try:
            stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            stored = stored.get("categories", []) if isinstance(stored, dict) else stored
        except (OSError, json.JSONDecodeError):
            stored = []
        from_presets = [self.metadata(name)["category"] for name in self.list_presets()]
        return sorted({str(value).strip()[:64] for value in [*stored, *from_presets] if str(value).strip()})

    def add_category(self, name: str) -> bool:
        category = str(name).strip()[:64]
        if not category:
            return False
        path = self.directory / self.CATEGORY_FILE
        values = self.categories()
        if category not in values:
            values.append(category)
            self._atomic_json_write(path, {"categories": sorted(values)})
        return True

    def metadata(self, name: str) -> dict:
        data = self.load(name) or {}
        return {
            "name": self.canonical(name),
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
        self._atomic_json_write(self.preset_path(name), data)
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

    STARDUST_DOCUMENT = "creativesysteme.stellardust.document"

    @classmethod
    def _unwrap_foreign(cls, data):
        """Accepte un document StarDust (.csbr) : il embarque un preset Nebula
        prêt à l'emploi dans ``exports.nebula_brush_preset``."""
        if isinstance(data, dict) and data.get("format") == cls.STARDUST_DOCUMENT:
            preset = (data.get("exports") or {}).get("nebula_brush_preset")
            return preset if isinstance(preset, dict) else None
        return data

    def import_preset(self, source: str | Path) -> str | None:
        source = Path(source)
        self.last_error = ""
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self.last_error = f"Fichier illisible : {error}"
            return None
        if isinstance(data, dict) and data.get("format") == self.STARDUST_DOCUMENT and not self._unwrap_foreign(data):
            self.last_error = ("Ce document StarDust n'est pas un moteur de pinceau exportable "
                               "(ré-enregistre-le depuis StarDust v0.4.1+)")
            return None
        data = self._validate_settings(self._unwrap_foreign(data), source.stem)
        if data is None:
            self.last_error = self.last_error or "Ce n'est pas un preset de pinceau CreativeSystem valide"
            return None
        self._atomic_json_write(self.preset_path(data["name"]), data)
        return data["name"]

    @staticmethod
    def _png_bytes(image: QImage) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise OSError("Could not encode brush PNG")
        buffer.close()
        return bytes(data)

    # Chaque pointe est une fonction pure de `kind` (256 Ko de pixels calculés en
    # Python) : la calculer une fois par processus au lieu de une fois par
    # instance du gestionnaire (il en est créé plusieurs au démarrage).
    _BITMAP_TIP_CACHE: dict[str, str] = {}

    @classmethod
    def _builtin_bitmap_tip(cls, kind: str) -> str:
        """Deterministic grayscale tips embedded into built-in CSBR presets."""
        cached = cls._BITMAP_TIP_CACHE.get(kind)
        if cached is None:
            cached = cls._BITMAP_TIP_CACHE[kind] = cls._render_builtin_bitmap_tip(kind)
        return cached

    _PAPER_CACHE: str | None = None

    @classmethod
    def _builtin_paper_texture(cls) -> str:
        """Seamless 256 px drawing-paper tooth (grayscale PNG, base64).

        Bright = raised fibres that catch graphite or chalk, dark = pits the
        tool skips.  Built from wrapped value noise so the tile repeats
        without seams, with a slight horizontal fibre direction.
        """
        if cls._PAPER_CACHE is not None:
            return cls._PAPER_CACHE
        import numpy as np
        size = 256
        rng = np.random.default_rng(20261003)
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)

        def wrapped_noise(cells_x: int, cells_y: int) -> np.ndarray:
            grid = rng.random((cells_y, cells_x), dtype=np.float32)
            gx, gy = xx * cells_x / size, yy * cells_y / size
            x0, y0 = gx.astype(int), gy.astype(int)
            fx, fy = gx - x0, gy - y0
            fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
            x1, y1 = (x0 + 1) % cells_x, (y0 + 1) % cells_y
            x0, y0 = x0 % cells_x, y0 % cells_y
            top = grid[y0, x0] * (1 - fx) + grid[y0, x1] * fx
            bottom = grid[y1, x0] * (1 - fx) + grid[y1, x1] * fx
            return top * (1 - fy) + bottom * fy

        tooth = (wrapped_noise(64, 85) * 0.45 + wrapped_noise(128, 128) * 0.30
                 + wrapped_noise(32, 48) * 0.15 + wrapped_noise(8, 8) * 0.10)
        tooth = (tooth - tooth.min()) / max(1e-6, float(tooth.max() - tooth.min()))
        value = np.clip(0.18 + 1.05 * tooth, 0.0, 1.0) ** 0.8
        gray = np.ascontiguousarray((value * 255.0 + 0.5).astype(np.uint8)).tobytes()
        image = QImage(gray, size, size, size, QImage.Format.Format_Grayscale8)
        cls._PAPER_CACHE = base64.b64encode(cls._png_bytes(image)).decode("ascii")
        return cls._PAPER_CACHE

    @classmethod
    def _render_builtin_bitmap_tip(cls, kind: str) -> str:
        """Render a natural-media tip from seeded value noise.

        The previous generator hashed pixel coordinates linearly, which gave
        visible diagonal moiré (Spray), barcode stripes (Dry Brush) and
        grain that averaged away to nothing once the tip was scaled down.
        """
        import numpy as np

        size = 128
        rng = np.random.default_rng(int(hashlib.sha256(kind.encode("utf-8")).hexdigest()[:8], 16))
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        dx, dy = (xx - 63.5) / 63.5, (yy - 63.5) / 63.5
        radius = np.sqrt(dx * dx + dy * dy)

        def noise(cell: int) -> np.ndarray:
            # Smooth value noise: bicubic-like upsampling of a coarse grid.
            n = size // cell + 2
            grid = rng.random((n, n), dtype=np.float32)
            gx, gy = xx / cell, yy / cell
            x0, y0 = gx.astype(int), gy.astype(int)
            fx, fy = gx - x0, gy - y0
            fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
            top = grid[y0, x0] * (1 - fx) + grid[y0, x0 + 1] * fx
            bottom = grid[y0 + 1, x0] * (1 - fx) + grid[y0 + 1, x0 + 1] * fx
            return top * (1 - fy) + bottom * fy

        def disc(edge: float) -> np.ndarray:
            # 1 inside, smooth falloff over the outer ``edge`` fraction.
            return np.clip((1.0 - radius) / max(edge, 1e-3), 0.0, 1.0)

        if kind == "bristle":
            # Individual hairs of varied width/strength inside a flat ferrule.
            alpha = np.zeros((size, size), np.float32)
            for _ in range(26):
                cx = rng.uniform(8, 120)
                width = rng.uniform(1.2, 3.6)
                strength = rng.uniform(0.45, 1.0)
                length = rng.uniform(0.70, 1.0)
                hair = np.exp(-((xx - cx) / width) ** 2)
                taper = np.clip((length - np.abs(dy)) / 0.25, 0.0, 1.0)
                alpha = np.maximum(alpha, hair * taper * strength)
            alpha *= np.clip((1.0 - np.abs(dx)) / 0.12, 0, 1)
            alpha *= 0.75 + 0.25 * noise(8)
        elif kind == "speckle":
            # Discrete round droplets of varied size: reads as spray or
            # stippling instead of a noise square.
            alpha = np.zeros((size, size), np.float32)
            for _ in range(70):
                r = 0.92 * math.sqrt(rng.random())
                a = rng.uniform(0, 2 * math.pi)
                cx, cy = 63.5 + r * 63.5 * math.cos(a), 63.5 + r * 63.5 * math.sin(a)
                dot = rng.uniform(1.4, 4.2)
                d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
                alpha = np.maximum(alpha, np.clip(dot - d + 0.5, 0, 1) * rng.uniform(0.6, 1.0))
        elif kind == "watercolor":
            # Pigment pools at the edge of a wash (edge darkening).
            rim = np.exp(-((radius - 0.86) / 0.10) ** 2)
            body = 0.55 + 0.20 * noise(24) + 0.10 * noise(9)
            alpha = disc(0.10) * np.clip(body + 0.45 * rim, 0, 1)
        elif kind == "charcoal":
            grain = noise(3) * 0.6 + noise(10) * 0.4
            alpha = disc(0.55) * np.clip((grain - 0.30) * 2.2, 0, 1)
        elif kind == "chalk":
            grain = noise(4) * 0.7 + noise(14) * 0.3
            alpha = disc(0.18) * np.clip((grain - 0.22) * 2.4, 0, 1)
        else:  # pencil: graphite grain on a nearly solid lead.
            grain = noise(3) * 0.55 + noise(7) * 0.45
            alpha = disc(0.35) * (0.45 + 0.55 * grain)

        value = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
        buffer = np.ascontiguousarray(np.stack([value, value, value, value], axis=-1)).tobytes()
        # ``buffer`` outlives the QImage view: the PNG is encoded right here.
        image = QImage(buffer, size, size, size * 4, QImage.Format.Format_RGBA8888)
        return base64.b64encode(cls._png_bytes(image)).decode("ascii")

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
            assets = {"texture.png": texture, "preview.png": preview}
            if bitmap_tip is not None:
                assets["bitmap_tip.png"] = bitmap_tip
            manifest = {
                "format": self.CSBR_FORMAT,
                "version": self.FORMAT_VERSION,
                "assets": {asset_name: hashlib.sha256(payload).hexdigest()
                           for asset_name, payload in assets.items()},
            }
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".csbr-", suffix=".tmp", dir=destination.parent)
            os.close(descriptor)
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("brush.json", json.dumps(settings, indent=2, ensure_ascii=False))
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for asset_name, payload in assets.items():
                    archive.writestr(asset_name, payload)
            os.replace(temporary, destination)
            return True
        except (OSError, ValueError, TypeError, zipfile.BadZipFile):
            try:
                if 'temporary' in locals():
                    os.unlink(temporary)
            except OSError:
                pass
            return False

    def import_csbr(self, source: str | Path) -> str | None:
        self.last_error = ""
        if not zipfile.is_zipfile(source):
            # .csbr de StarDust (JSON) ou ancien preset JSON renommé.
            return self.import_preset(source)
        try:
            with zipfile.ZipFile(source, "r") as archive:
                infos = archive.infolist()
                names = {entry.filename for entry in infos}
                missing = {"brush.json", "texture.png", "preview.png"} - names
                if missing:
                    self.last_error = "Paquet .csbr incomplet : " + ", ".join(sorted(missing)) + " manquant(s)"
                    return None
                # Flat, small archives only: no duplicate entries, folders or paths.
                allowed = {"brush.json", "texture.png", "preview.png", "bitmap_tip.png", "manifest.json"}
                if (len(infos) > self.MAX_CSBR_ENTRIES or len(names) != len(infos)
                        or any(entry.filename not in allowed or entry.is_dir() for entry in infos)
                        or any(entry.file_size > self.MAX_CSBR_ENTRY_BYTES for entry in infos)
                        or sum(max(0, entry.file_size) for entry in infos) > self.MAX_CSBR_BYTES):
                    return None
                raw_settings = archive.read("brush.json")
                if len(raw_settings) > 1024 * 1024:
                    return None
                settings = self._validate_settings(json.loads(raw_settings.decode("utf-8")), Path(source).stem)
                if settings is None:
                    self.last_error = "brush.json invalide ou d'une version future"
                    return None
                images = {}
                for image_name in ("texture.png", "preview.png"):
                    image = QImage()
                    image_data = archive.read(image_name)
                    if (not image_data.startswith(b"\x89PNG\r\n\x1a\n")
                            or not image.loadFromData(image_data)
                            or image.width() > 4096 or image.height() > 4096):
                        self.last_error = f"Image {image_name} invalide dans le paquet"
                        return None
                    images[image_name] = image_data
                # Version 3 includes content hashes. Version 1/2 packages remain readable.
                if "manifest.json" in names:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    hashes = manifest.get("assets", {}) if isinstance(manifest, dict) else {}
                    # Versions 1 à FORMAT_VERSION lisibles (le commentaire le promettait,
                    # le code exigeait la version exacte et refusait les anciens paquets).
                    if (manifest.get("format") != self.CSBR_FORMAT
                            or not 1 <= int(manifest.get("version", 0)) <= self.FORMAT_VERSION
                            or any(asset in hashes and hashes.get(asset) != hashlib.sha256(data).hexdigest()
                                   for asset, data in images.items())):
                        self.last_error = "Paquet .csbr corrompu ou de format inconnu"
                        return None
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
                    images["bitmap_tip.png"] = bitmap_tip
                if "manifest.json" in names:
                    # Check every exported asset, including an optional bitmap tip.
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    hashes = manifest.get("assets", {}) if isinstance(manifest, dict) else {}
                    if any(asset in hashes and hashes.get(asset) != hashlib.sha256(data).hexdigest()
                           for asset, data in images.items()):
                        self.last_error = "Paquet .csbr corrompu (empreinte invalide)"
                        return None
                self._atomic_json_write(self.preset_path(settings["name"]), settings)
                return settings["name"]
        except (OSError, ValueError, TypeError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self.last_error = f"Import impossible : {error}"
            return None

    # ========================================================
    # BUILTIN PRESETS
    # ========================================================

    def _migrate_english_builtins(self) -> None:
        """Rename factory presets installed under English names (≤ 26.4.0)."""
        for english in (*self.FRENCH_NAMES, *self.LEGACY_PRESETS):
            french = self.ALIASES.get(english, english)
            if french == english:
                continue
            old_path = self.directory / f"{english}.json"
            if not old_path.is_file():
                continue
            try:
                data = json.loads(old_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not (data.get("builtIn") or data.get("_legacy_builtin")):
                continue  # a user preset that happens to use the name: keep it
            try:
                if data.get("builtIn") and english in self.FRENCH_NAMES and not self.preset_path(french).exists():
                    data["name"] = french
                    self._atomic_json_write(self.preset_path(french), data)
                old_path.unlink()
            except OSError:
                continue

    def create_builtin_presets(self):
        self._migrate_english_builtins()
        # Clean, ready-to-paint defaults requested for the first-run brush pack.
        pack = {
            "Charcoal": {},
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
        # Curated working set from the Nebula base-library specification.
        # Values not repeated here inherit the complete, stable ``common`` set.
        pack.update({
            "Pencil HB": dict(size=6., opacity=.70, flow=.60, hardness=.50, spacing=.10, roundness=.92, textureStrength=.30, textureScale=1.3, textureContrast=1.15, pressureSize=True, pressureOpacity=True, minimumSize=.15, minimumOpacity=.10),
            "Pencil 2B": dict(size=10., opacity=.85, flow=.75, hardness=.35, spacing=.09, textureStrength=.45, textureScale=1.6, textureContrast=1.25, pressureSize=True, pressureOpacity=True, minimumSize=.20),
            "Pencil 4H": dict(size=3., opacity=.35, flow=.50, hardness=.75, spacing=.07, textureStrength=.15, pressureSize=True, pressureOpacity=True, minimumSize=.25, color=[60,70,90,255]),
            "Mechanical Pencil": dict(size=2.5, opacity=.90, flow=1., hardness=.85, spacing=.06, pressureSize=False, pressureOpacity=True, minimumOpacity=.30),
            "Blue Sketch": dict(size=14., opacity=.28, flow=.55, hardness=.25, spacing=.11, scatter=.04, sizeJitter=.15, pressureSize=True, pressureOpacity=True, color=[70,105,170,255]),
            "Col Erase": dict(size=8., opacity=.65, flow=.70, hardness=.20, spacing=.08, roundness=.80, textureStrength=.55, textureScale=2., textureContrast=1.35, pressureSize=True, pressureOpacity=True),
            "Ink Brush": dict(size=22., opacity=1., flow=1., hardness=.92, spacing=.035, pressureSize=True, minimumSize=.04, minimumOpacity=1.),
            "Fineliner": dict(size=3., opacity=1., flow=1., hardness=1., spacing=.04, pressureSize=False, minimumSize=1., minimumOpacity=1.),
            "Marker": dict(size=30., opacity=.92, flow=.95, hardness=.88, spacing=.05, roundness=.35, angle=45., pressureOpacity=True, minimumOpacity=.55),
            "G-Pen": dict(size=16., opacity=1., flow=1., hardness=.98, spacing=.03, pressureSize=True, minimumSize=.02, minimumOpacity=1., stabilization=.50, pressureCurve=2),
            "Oil Round": dict(size=55., opacity=.95, flow=.80, hardness=.40, spacing=.045, wetMix=True, wetness=.55, pickup=.45, dilution=.20, paintPersistence=.75, colorCarry=.80, smudge=.15, dirtyColor=True, pressureSize=True, pressureFlow=True),
            "Oil Flat": dict(size=70., opacity=1., flow=.85, hardness=.55, spacing=.04, roundness=.25, wetMix=True, wetness=.45, pickup=.35, dilution=.15, paintPersistence=.80, colorCarry=.75, dirtyColor=True, pressureSize=True, pressureFlow=True),
            "Watercolor": dict(size=60., opacity=.45, flow=.30, hardness=0., spacing=.05, wetMix=True, wetness=.80, pickup=.30, dilution=.65, paintPersistence=.50, colorCarry=.60, textureStrength=.35, pressureSize=True, pressureFlow=True),
            "Gouache": dict(size=50., opacity=1., flow=.95, hardness=.70, spacing=.05, wetMix=True, wetness=.25, pickup=.20, paintPersistence=.90, colorCarry=.85, pressureSize=True),
            "Blender": dict(size=40., opacity=1., flow=0., hardness=0., spacing=.04, wetMix=True, wetness=1., pickup=1., paintPersistence=0., colorCarry=1., smudge=.85, pressureSize=True, pressureFlow=True),
            "Airbrush Soft": dict(size=120., opacity=1., flow=.12, hardness=0., spacing=.025, pressureSize=False, pressureFlow=True),
            "Airbrush Hard": dict(size=70., opacity=1., flow=.25, hardness=.45, spacing=.03, pressureSize=False, pressureFlow=True),
            "Spray": dict(size=80., opacity=.85, flow=.30, hardness=.90, spacing=.06, scatter=.85, sizeJitter=.60, pressureSize=False, pressureFlow=True),
            "Glow": dict(size=100., opacity=1., flow=.15, hardness=0., spacing=.025, blendMode=1, pressureSize=False, pressureFlow=True, color=[255,200,120,255]),
            "Chalk": dict(size=35., opacity=.90, flow=.85, hardness=.30, spacing=.08, textureStrength=.60, textureScale=1.8, textureContrast=1.3, pressureSize=True, pressureOpacity=True),
            "Conte": dict(size=18., opacity=.75, flow=.70, hardness=.40, spacing=.07, roundness=.60, textureStrength=.50, pressureSize=True, pressureOpacity=True, color=[110,60,45,255]),
            "Dry Brush": dict(size=50., opacity=.85, flow=.55, hardness=.65, spacing=.06, roundness=.30, textureStrength=.75, wetMix=True, wetness=.15, pickup=.25, paintPersistence=.60, pressureSize=True, pressureFlow=True),
            "Stipple": dict(size=12., opacity=1., flow=1., hardness=.85, spacing=.85, scatter=.45, sizeJitter=.40, rotationJitter=180., pressureSize=True, minimumSize=.30, minimumOpacity=1.),
            "Eraser Pencil": dict(size=14., opacity=.55, flow=.60, hardness=.35, spacing=.09, eraser=True, textureStrength=.35, pressureSize=True, pressureOpacity=True),
            "Eraser Airbrush": dict(size=110., opacity=1., flow=.12, hardness=0., spacing=.025, eraser=True, pressureSize=False, pressureFlow=True),
            "Smudge": dict(size=35., opacity=1., flow=1., hardness=.20, spacing=.03, wetMix=True, wetness=1., pickup=1., paintPersistence=0., colorCarry=1., smudge=1., pressureSize=True),
            "Pixel": dict(size=1., opacity=1., flow=1., hardness=1., spacing=.25, pressureSize=False, minimumSize=1., minimumOpacity=1., antialiasing=False),
            "Concept Block": dict(size=150., opacity=1., flow=1., hardness=.80, spacing=.04, roundness=.85, pressureSize=False, minimumSize=1.),
        })
        # Fine tuning from the published Nebula base-library sheet.  Keep
        # this explicit: a preset is a tool, not merely a round tip size.
        for name, tuning in {
            "Pencil HB": dict(angle=0., scatter=.015, sizeJitter=.08, rotationJitter=3., textureRandomOffset=.12, textureMirror=True, textureAffectOpacity=True, brightnessJitter=.04, pressureFlow=False),
            "Pencil 2B": dict(roundness=.85, scatter=.03, sizeJitter=.12, rotationJitter=5., textureRandomOffset=.18, textureMirror=True, brightnessJitter=.06, minimumOpacity=.08),
            "Pencil 4H": dict(roundness=.95, scatter=.005, sizeJitter=.04, rotationJitter=1., textureScale=1., textureContrast=1.05, minimumOpacity=.15),
            "Mechanical Pencil": dict(roundness=1., scatter=0., sizeJitter=0., rotationJitter=0., textureStrength=.08),
            "Blue Sketch": dict(roundness=.88, rotationJitter=6., textureStrength=.20, minimumSize=.18, minimumOpacity=.05),
            "Col Erase": dict(angle=12., scatter=.05, sizeJitter=.14, rotationJitter=8., textureRandomScale=.15, textureRandomOffset=.20, textureMirror=True, saturationJitter=.04, brightnessJitter=.07, minimumSize=.22, minimumOpacity=.06),
            "Ink Pen": dict(size=6., opacity=1., flow=1., hardness=.95, spacing=.045, roundness=1., angle=0., scatter=0., sizeJitter=0., rotationJitter=0., textureStrength=0., pressureSize=True, pressureOpacity=False, pressureFlow=False, minimumSize=.12, minimumOpacity=1., stabilization=.35, color=[15,15,18,255]),
            "Ink Brush": dict(roundness=1., scatter=0., sizeJitter=0., rotationJitter=0., textureStrength=0., pressureOpacity=False, pressureFlow=False, color=[12,12,15,255]),
            "Fineliner": dict(roundness=1., pressureOpacity=False, pressureFlow=False, color=[20,20,22,255]),
            "Marker": dict(scatter=0., sizeJitter=.02, rotationJitter=0., textureStrength=.06, blendMode=0, paintMix=1., pressureSize=False),
            "G-Pen": dict(roundness=1., scatter=0., sizeJitter=0., rotationJitter=0., textureStrength=0., pressureOpacity=False, pressureFlow=False, color=[8,8,10,255]),
            "Round Hard": dict(size=30., opacity=1., flow=1., hardness=.95, spacing=.05, roundness=1., pressureSize=True, pressureFlow=False, minimumSize=.08),
            "Round Soft": dict(size=45., opacity=1., flow=.85, hardness=0., spacing=.06, roundness=1., scatter=0., sizeJitter=0., pressureSize=True, pressureOpacity=False, pressureFlow=True, minimumSize=.10, minimumFlow=0.),
            "Oil Round": dict(roundness=.95, angle=0., scatter=.01, sizeJitter=.06, rotationJitter=4., textureStrength=.18, textureScale=1.5, textureContrast=1.1, sampleCanvas=True, hueJitter=.01, saturationJitter=.03, minimumSize=.15),
            "Oil Flat": dict(angle=0., sizeJitter=.05, rotationJitter=2., textureStrength=.22, textureScale=1.8, sampleCanvas=True, minimumSize=.20),
            "Watercolor": dict(roundness=.92, scatter=.02, sizeJitter=.10, rotationJitter=5., textureContrast=1.3, textureRandomOffset=.20, textureMirror=True, sampleCanvas=True, hueJitter=.015, saturationJitter=.05, brightnessJitter=.04, minimumSize=.25, minimumFlow=.05),
            "Gouache": dict(roundness=.88, sizeJitter=.08, rotationJitter=3., textureStrength=.25, textureScale=1.4, textureContrast=1.2, sampleCanvas=True, dilution=0., pressureFlow=False, minimumSize=.18),
            "Blender": dict(roundness=1., sampleCanvas=True, dilution=0., pressureFlow=True, minimumSize=.15),
            "Airbrush Soft": dict(roundness=1., scatter=0., sizeJitter=0., pressureOpacity=False, minimumFlow=0.),
            "Airbrush Hard": dict(roundness=1., pressureFlow=True, minimumFlow=.02),
            "Spray": dict(roundness=1., rotationJitter=0., brightnessJitter=.10, saturationJitter=.06, minimumFlow=0.),
            "Glow": dict(roundness=1., pressureFlow=True, minimumFlow=0.),
            "Charcoal": dict(size=45., opacity=.80, flow=.75, hardness=.10, spacing=.07, roundness=.70, angle=25., scatter=.08, sizeJitter=.20, rotationJitter=12., textureStrength=.70, textureScale=2.4, textureContrast=1.45, textureRandomScale=.20, textureRandomOffset=.30, textureMirror=True, textureAffectOpacity=True, brightnessJitter=.10, pressureSize=True, pressureOpacity=True, minimumSize=.20, minimumOpacity=.05),
            "Chalk": dict(roundness=.75, angle=0., scatter=.06, sizeJitter=.18, rotationJitter=15., textureRandomOffset=.25, textureMirror=True, saturationJitter=.05, brightnessJitter=.08, minimumSize=.25, minimumOpacity=.10),
            "Conte": dict(angle=35., scatter=.03, sizeJitter=.12, rotationJitter=6., textureScale=1.6, textureContrast=1.25, textureRandomOffset=.15, textureMirror=True, minimumSize=.20, minimumOpacity=.08),
            "Dry Brush": dict(angle=0., scatter=.12, sizeJitter=.25, rotationJitter=8., textureScale=2.8, textureContrast=1.55, textureRandomScale=.25, textureRandomOffset=.35, textureMirror=True, textureAffectOpacity=True, sampleCanvas=True, dilution=0., colorCarry=.50, minimumSize=.25),
            "Stipple": dict(roundness=.90, brightnessJitter=.12, saturationJitter=.06, pressureOpacity=False),
            "Eraser Soft": dict(size=50., opacity=1., flow=.85, hardness=0., spacing=.06, roundness=1., eraser=True, pressureSize=True, pressureFlow=True, minimumSize=.10),
            "Eraser Hard": dict(size=30., opacity=1., flow=1., hardness=.95, spacing=.05, roundness=1., eraser=True, pressureSize=True, pressureFlow=False, minimumSize=.08),
            "Eraser Pencil": dict(roundness=.88, scatter=.03, sizeJitter=.12, rotationJitter=5., textureScale=1.5, textureContrast=1.2, textureRandomOffset=.15, textureMirror=True, minimumSize=.18, minimumOpacity=.05),
            "Eraser Airbrush": dict(roundness=1., pressureFlow=True, minimumFlow=0.),
            "Smudge": dict(roundness=1., sampleCanvas=True, dilution=0., pressureFlow=True, minimumSize=.12),
            "Pixel": dict(roundness=1., angle=0., scatter=0., sizeJitter=0., rotationJitter=0., textureStrength=0., pressureSize=False, pressureOpacity=False, pressureFlow=False, minimumSize=1., minimumOpacity=1., antialiasing=False),
            "Concept Block": dict(angle=0., sizeJitter=.05, textureStrength=.10, textureScale=2., pressureFlow=False),
        }.items():
            pack[name].update(tuning)
        # Revision 3 — tuned against rendered stroke sheets.  Each entry fixes
        # something that looked or behaved wrong in revision 2.
        for name, tuning in {
            # Blending tools move existing paint instead of laying down colour.
            "Blender": dict(opacity=1., flow=.70, hardness=0., spacing=.04, smudgeTool=True,
                            wetMix=True, wetness=1., pickup=.80, smudge=.55, paintPersistence=0.,
                            pressureSize=True, pressureFlow=True, minimumFlow=.10),
            # Flat marker: constant tone, no dark build-up at stroke ends.
            "Marker": dict(opacity=.85, flow=1., hardness=.90, pressureOpacity=False,
                           pressureSize=False, minimumOpacity=1.),
            # A blocking brush, not a 150 px wall.
            "Concept Block": dict(size=60., hardness=.90, spacing=.05, pressureSize=False,
                                  pressureOpacity=True, minimumOpacity=.35),
            # Bristle tips follow the stroke so hairs drag lengthwise.
            "Dry Brush": dict(size=45., roundness=1., spacing=.035, scatter=.02, sizeJitter=.06,
                              rotationJitter=3., directionFollow=1., textureStrength=.35,
                              wetMix=False, wetness=0., pickup=0., pressureSize=True,
                              pressureOpacity=True, pressureFlow=False, minimumOpacity=.20),
            "Oil Flat": dict(roundness=1., directionFollow=1., spacing=.035, textureStrength=.12),
            "Spray": dict(size=90., opacity=1., flow=.45, spacing=.18, scatter=.45, sizeJitter=.30,
                          rotationJitter=180., brightnessJitter=0., saturationJitter=0.,
                          pressureFlow=True, pressureSize=False),
            # Clean round dots: the speckle tip shrank each dot to dust.
            "Stipple": dict(size=10., hardness=.90, spacing=1.6, scatter=1.2, sizeJitter=.35,
                            rotationJitter=0., brightnessJitter=0., saturationJitter=0.,
                            pressureSize=True, pressureFlow=False, minimumSize=.60,
                            _csbr_bitmap_tip_png=""),
            "Watercolor": dict(opacity=.55, flow=.35, spacing=.04, textureStrength=.20),
            # blendMode 1 is Multiply in CreativeCore: the "glow" darkened.
            "Glow": dict(blendMode=2, flow=.25),
            "Smudge": dict(opacity=1., flow=1., hardness=.60, smudgeTool=True, smudge=.65, pickup=.75,
                           wetness=1., paintPersistence=0., pressureFlow=True, minimumFlow=.15),
            "Pencil HB": dict(spacing=.08, textureStrength=.18),
            "Pencil 2B": dict(spacing=.08, textureStrength=.25),
            "Charcoal": dict(spacing=.06, textureStrength=.35),
            "Chalk": dict(spacing=.07, textureStrength=.30),
        }.items():
            pack[name].update(tuning)
        # Revision 4 — paper grain fixed to the canvas for dry media, so the
        # tooth no longer repeats inside every dab.
        paper = self._builtin_paper_texture()
        for name, strength, scale in (
            ("Pencil HB", .55, .5), ("Pencil 2B", .65, .5), ("Pencil 4H", .45, .5),
            ("Col Erase", .55, .5), ("Charcoal", .80, .75), ("Chalk", .75, .75),
            ("Conte", .65, .6), ("Eraser Pencil", .40, .5),
        ):
            pack[name].update(textureCanvasSpace=True, textureStrength=strength,
                              textureScale=scale, textureRandomScale=0., textureRandomOffset=0.,
                              textureContrast=1.0, textureBrightness=0., textureMirror=False,
                              textureAffectOpacity=True, _csbr_texture_png=paper)
        # Keep the historical names as compatibility aliases.  Existing
        # documents and scripts can still request ``Ink``/``Pencil`` while
        # the newer curated presets remain available beside them.
        for category, names in {
            "01_Sketching": ("Pencil HB", "Pencil 2B", "Pencil 4H", "Mechanical Pencil", "Blue Sketch", "Col Erase"),
            "02_Inking": ("Ink Brush", "Fineliner", "Marker", "G-Pen"),
            "03_Painting": ("Oil Round", "Oil Flat", "Watercolor", "Gouache", "Blender"),
            "04_Airbrush": ("Airbrush Soft", "Airbrush Hard", "Spray", "Glow"),
            "05_Texture": ("Chalk", "Conte", "Dry Brush", "Stipple"),
            "06_Erasers": ("Eraser Pencil", "Eraser Airbrush"),
            "07_Utility": ("Smudge", "Pixel", "Concept Block"),
        }.items():
            self.BUILTIN_CATEGORIES.update({name: category for name in names})
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
            "minimumFlow": 0.0, "eraser": False, "smudgeTool": False, "directionFollow": 0.0,
            "textureCanvasSpace": False, "_csbr_texture_png": "",
            "color": [30, 30, 30, 255], "gradientColor": [255, 255, 255, 255],
        }
        tips = {"Pencil HB": "pencil", "Pencil 2B": "pencil", "Col Erase": "pencil",
                "Eraser Pencil": "pencil",
                "Charcoal": "charcoal", "Chalk": "chalk", "Conte": "chalk",
                "Dry Brush": "bristle", "Oil Flat": "bristle", "Watercolor": "watercolor",
                "Spray": "speckle"}
        for name, tip_kind in tips.items():
            if name in pack:
                pack[name]["_csbr_bitmap_tip_png"] = self._builtin_bitmap_tip(tip_kind)
        self._installing_builtins = True
        try:
            for name, values in pack.items():
                path = self.preset_path(name)
                if path.exists():
                    continue
                settings = {**common, **values}
                data = {
                    **settings, "name": self.canonical(name), "format": "CreativeSystemBrushPreset",
                    "version": self.FORMAT_VERSION, "category": self.BUILTIN_CATEGORIES.get(name, "07_Utility"),
                    "favorite": name in self.DEFAULT_FAVORITES, "builtIn": True,
                    "builtinRevision": 4,
                }
                self._atomic_json_write(path, data)
        finally:
            self._installing_builtins = False

        # Safe migration for the bundled read-only presets already installed
        # by earlier versions: only catalog metadata changes, never user data.
        for path in self.directory.glob("*.json"):
            if path.name == self.CATEGORY_FILE:
                continue
            data = self.load(path.stem)
            name = self.ENGLISH_NAMES.get(path.stem, path.stem)
            # Built-ins are installed by the application, unlike a copied or
            # imported user preset.  Upgrade only those known factory presets
            # to the complete revision; custom brushes remain untouched.
            try:
                builtin_revision = int(data.get("builtinRevision", 0)) if data else 0
            except (TypeError, ValueError):
                builtin_revision = 0
            if (data and data.get("builtIn") is True and name in pack
                    and builtin_revision < 4):
                settings = {**common, **pack[name]}
                data = {
                    **settings, "name": self.canonical(name),
                    "format": "CreativeSystemBrushPreset",
                    "version": self.FORMAT_VERSION,
                    "category": self.BUILTIN_CATEGORIES.get(name, "07_Utility"),
                    "favorite": name in self.DEFAULT_FAVORITES,
                    "builtIn": True,
                    "builtinRevision": 4,
                }
                self._atomic_json_write(self.preset_path(name), data)
            if not data or name not in self.BUILTIN_CATEGORIES:
                continue
            category = self.BUILTIN_CATEGORIES.get(name, "07_Utility")
            if data.get("category") != category or bool(data.get("favorite")) != (name in self.DEFAULT_FAVORITES):
                data["category"] = category
                data["favorite"] = name in self.DEFAULT_FAVORITES
                self._atomic_json_write(self.preset_path(name), data)
        # Add missing generated tips during an upgrade without overwriting a
        # user-provided bitmap tip.
        for name, tip_kind in tips.items():
            data = self.load(name)
            if data is not None and not data.get("_csbr_bitmap_tip_png"):
                data["_csbr_bitmap_tip_png"] = self._builtin_bitmap_tip(tip_kind)
                self._atomic_json_write(self.preset_path(name), data)
        for category in ("01_Sketching", "02_Inking", "03_Painting", "04_Airbrush", "05_Texture", "06_Erasers", "07_Utility"):
            self.add_category(category)
