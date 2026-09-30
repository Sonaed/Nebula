"""Unified user resource catalog and safe bundle import/export."""
from __future__ import annotations

import json
import hashlib
import os
import sys
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ResourceRecord:
    kind: str
    name: str
    path: Path
    apps: tuple = field(default=(), compare=False)   # apps autorisées (bibliothèque centrale d'Existence)
    version: str = "1"
    content_hash: str = ""
    dependencies: tuple = field(default=(), compare=False)


APP_ID = "nebula"


def _shared_library(root: Path):
    """Bibliothèque centrale possédée par Existence (module Ressources).

    Même dossier que la bibliothèque historique de Nebula : on y ajoute
    seulement l'index des étiquettes d'applications. Sans Existence, Nebula
    fonctionne comme avant (aucune étiquette)."""
    existence_root = Path(os.environ.get("EXISTENCE_ROOT", "/home/deanos/Documents/Existence"))
    if existence_root.exists() and str(existence_root) not in sys.path:
        sys.path.append(str(existence_root))
    try:
        from modules.resource_center.library import SharedLibrary
        return SharedLibrary(root)
    except Exception:  # noqa: BLE001
        return None


class ResourceManager:
    """Owns the common resource library without changing existing formats."""

    KINDS = {
        # Shared Existence catalogue categories.  The original Nebula kinds
        # remain unchanged below for backwards compatibility.
        "documents": (".csd", ".psd", ".svg", ".pdf", ".json", ".txt", ".md"),
        "images": (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"),
        "projects": (".csproject", ".zip", ".json"),
        "brushes": (".csbr", ".json", ".abr", ".abr2"),
        "brush_engines": (".csbe", ".csbr", ".json"),
        "blends": (".csbl", ".json"),
        "filters": (".csfilter", ".json"),
        "effects": (".cseffect", ".json"),
        "masks": (".csmask", ".png", ".jpg", ".jpeg", ".webp", ".json"),
        "generators": (".csgenerator", ".json"),
        "libraries": (".zip", ".json"),
        "modules": (".zip", ".json", ".toml"),
        "textures": (".png", ".jpg", ".jpeg", ".webp"),
        "patterns": (".png", ".jpg", ".jpeg", ".webp"),
        "gradients": (".json", ".csg", ".csgr", ".grd"),
        "palettes": (".json", ".cspl", ".aco", ".ase", ".gpl", ".txt"),
        "styles": (".json", ".asl", ".cseffect"),
        "fonts": (".ttf", ".otf", ".woff", ".woff2"),
        "icc_profiles": (".icc", ".icm"),
        "reference_sets": (".zip", ".json"),
    }
    MAX_BUNDLE_BYTES = 256 * 1024 * 1024

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _resource_metadata(path: Path) -> dict:
        """Read portable resource metadata from JSON payloads when present."""
        if path.suffix.lower() != ".json":
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    def __init__(self, root: str | Path | None = None) -> None:
        configured_root = os.environ.get("CREATIVE_SYSTEM_DATA_HOME", "").strip()
        default_root = (Path(configured_root) if configured_root else
                        Path.home() / ".local" / "share" / "CreativeSystem")
        self.root = Path(root) if root is not None else default_root / "resources"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only or sandboxed hosts still get a working session library;
            # the caller can provide a persistent root when available.
            self.root = Path(tempfile.mkdtemp(prefix="creative-resources-"))
        for kind in self.KINDS:
            (self.root / kind).mkdir(exist_ok=True)
        self.library = _shared_library(self.root)
        self._ensure_builtin_presets()

    def _ensure_builtin_presets(self) -> None:
        """Seed a small, editable starter library without overwriting users."""
        builtins = {
            "gradients": {
                "Nebula Sunset.json": {"format": "CreativeSystemGradient", "version": 1,
                    "name": "Nebula Sunset", "stops": [{"position": 0.0, "color": "#17104A"}, {"position": 0.5, "color": "#7C3AED"}, {"position": 1.0, "color": "#F97316"}]},
                "Aurora Cyan.json": {"format": "CreativeSystemGradient", "version": 1,
                    "name": "Aurora Cyan", "stops": [{"position": 0.0, "color": "#071A3D"}, {"position": 0.55, "color": "#06B6D4"}, {"position": 1.0, "color": "#D946EF"}]},
                "Monochrome.json": {"format": "CreativeSystemGradient", "version": 1,
                    "name": "Monochrome", "stops": [{"position": 0.0, "color": "#111128"}, {"position": 1.0, "color": "#E8E8FF"}]},
                "Ocean Current.json": {"format": "CreativeSystemGradient", "version": 2,
                    "name": "Ocean Current", "stops": [{"position": 0.0, "color": "#041B2D"}, {"position": 0.45, "color": "#0369A1"}, {"position": 1.0, "color": "#67E8F9"}]},
                "Ember Core.json": {"format": "CreativeSystemGradient", "version": 2,
                    "name": "Ember Core", "stops": [{"position": 0.0, "color": "#2A0714"}, {"position": 0.5, "color": "#DC2626"}, {"position": 1.0, "color": "#FDE047"}]},
                "Polar Light.json": {"format": "CreativeSystemGradient", "version": 2,
                    "name": "Polar Light", "stops": [{"position": 0.0, "color": "#102A43"}, {"position": 0.5, "color": "#A7F3D0"}, {"position": 1.0, "color": "#F0FDFA"}]},
            },
            "palettes": {
                "Nebula Core.json": {"format": "CreativeSystemPalette", "version": 1,
                    "name": "Nebula Core", "builtin_version": 2, "colors": ["#080818", "#111128", "#1E1E45", "#7C3AED", "#A855F7", "#D946EF", "#06B6D4", "#E8E8FF"]},
                "Solar Flare.json": {"format": "CreativeSystemPalette", "version": 1,
                    "name": "Solar Flare", "builtin_version": 2, "colors": ["#17104A", "#4C0519", "#BE123C", "#EF4444", "#F97316", "#F59E0B", "#FDE047", "#FFF7ED"]},
                "Forest Signal.json": {"format": "CreativeSystemPalette", "version": 1,
                    "name": "Forest Signal", "builtin_version": 2, "colors": ["#06251D", "#064E3B", "#047857", "#10B981", "#06B6D4", "#67E8F9", "#A7F3D0", "#ECFDF5"]},
            },
        }
        for kind, records in builtins.items():
            for filename, payload in records.items():
                payload = {**payload, "builtin_version": int(payload.get("builtin_version", 1))}
                path = self.root / kind / filename
                should_seed = not path.exists()
                if path.exists():
                    try:
                        current = json.loads(path.read_text(encoding="utf-8"))
                        should_seed = int(current.get("builtin_version", 0)) < int(payload.get("builtin_version", 1))
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        should_seed = False
                if should_seed:
                    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def catalog(self, kind: str | None = None, app: str | None = APP_ID) -> list[ResourceRecord]:
        """Ressources utilisables par ``app`` (Nebula par défaut ; None = toutes)."""
        kinds = (kind,) if kind is not None else tuple(self.KINDS)
        tags = {}
        if self.library is not None:
            try:
                tags = {Path(e["path"]).resolve(): tuple(e["apps"]) for e in self.library.entries()}
            except (OSError, ValueError, KeyError):
                tags = {}
        records: list[ResourceRecord] = []
        content_seen: set[tuple[str, str]] = set()
        for selected in kinds:
            if selected not in self.KINDS:
                raise ValueError(f"Unknown resource kind: {selected}")
            directory = self.root / selected
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.suffix.lower() in self.KINDS[selected]:
                    apps = tags.get(path.resolve(), ())
                    if app is not None and apps and app not in apps:
                        continue
                    metadata = self._resource_metadata(path)
                    dependencies = metadata.get("dependencies", ())
                    if not isinstance(dependencies, (list, tuple)):
                        dependencies = ()
                    record = ResourceRecord(
                        selected, path.stem, path, apps,
                        str(metadata.get("resource_version", metadata.get("version", "1"))),
                        self._hash(path), tuple(str(item) for item in dependencies),
                    )
                    # SharedLibrary may retain a migration alias beside the
                    # canonical file. Expose one content-addressed resource.
                    fingerprint = (selected, record.content_hash)
                    if fingerprint not in content_seen:
                        content_seen.add(fingerprint)
                        records.append(record)
        return records

    def set_apps(self, record: ResourceRecord, apps) -> None:
        if self.library is not None:
            self.library.set_apps(record.path, apps)

    def sync_brush_presets(self, preset_manager) -> list[str]:
        """Installe dans la bibliothèque de presets de Nebula les pinceaux de la
        bibliothèque centrale qui lui sont destinés (ex. exportés par StarDust)."""
        installed = []
        if preset_manager is None:
            return installed
        known = set(preset_manager.list_presets())
        for record in self.catalog("brushes"):
            try:
                suffix = record.path.suffix.lower()
                if suffix == ".json":
                    data = json.loads(record.path.read_text(encoding="utf-8"))
                    name = str(data.get("name") or record.name) if isinstance(data, dict) else record.name
                    current = preset_manager.load(name) or {}
                    if name in known and current.get("_library_version") == data.get("_library_version"):
                        continue
                    imported = preset_manager.import_preset(record.path)
                elif suffix == ".csbr" and record.name not in known:
                    imported = preset_manager.import_csbr(record.path)
                else:
                    continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if imported:
                installed.append(imported)
        return installed

    @staticmethod
    def _is_builtin(record: ResourceRecord) -> bool:
        """Starter resources are recreated by a new library and need not be bundled."""
        if record.path.suffix.lower() != ".json":
            return False
        try:
            payload = json.loads(record.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and "builtin_version" in payload

    def import_file(self, source: str | Path, kind: str) -> Path:
        if kind not in self.KINDS:
            raise ValueError(f"Unknown resource kind: {kind}")
        source_path = Path(source)
        if not source_path.is_file() or source_path.suffix.lower() not in self.KINDS[kind]:
            raise ValueError("Unsupported resource file")
        name = source_path.name.replace("/", "_").replace("\\", "_")
        if name in {".", ".."} or ".." in Path(name).parts:
            raise ValueError("Invalid resource filename")
        destination = self.root / kind / name
        if destination.exists():
            destination = destination.with_name(f"{destination.stem}-{uuid4().hex[:8]}{destination.suffix}")
        shutil.copy2(source_path, destination)
        if self.library is not None:
            try:
                self.library.add_file(destination, kind, owner=APP_ID)
            except (OSError, ValueError):
                pass
        return destination

    def rename(self, record: ResourceRecord, name: str) -> Path:
        name = name.strip().replace("/", "_").replace("\\", "_")
        if not name or name in {".", ".."} or ".." in Path(name).parts:
            raise ValueError("Invalid resource name")
        suffix = record.path.suffix
        if not name.lower().endswith(suffix.lower()):
            name += suffix
        destination = self.root / record.kind / name
        if destination.exists() and destination != record.path:
            raise ValueError("A resource with this name already exists")
        record.path.rename(destination)
        if self.library is not None:
            try:
                self.library.rename_key(record.path, destination)
            except (OSError, ValueError):
                pass
        return destination

    def delete(self, record: ResourceRecord) -> None:
        record.path.unlink()
        if self.library is not None:
            try:
                self.library.forget(record.path)
            except (OSError, ValueError):
                pass

    def export_bundle(self, destination: str | Path, kinds=None) -> Path:
        selected = tuple(kinds or self.KINDS)
        records = [record for record in self.catalog()
                   if not self._is_builtin(record)]
        if any(record.kind not in selected for record in records):
            records = [record for record in records if record.kind in selected]
        # A shared library may expose both its canonical entry and the local
        # import alias.  Bundles are content-addressed, so ship that payload
        # once while retaining deterministic ordering.
        unique_records = []
        seen_content = set()
        for record in records:
            key = (record.kind, record.content_hash)
            if key not in seen_content:
                seen_content.add(key)
                unique_records.append(record)
        records = unique_records
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = [{"kind": r.kind, "name": r.path.name, "resource_version": r.version,
                     "sha256": r.content_hash, "dependencies": list(r.dependencies)}
                    for r in records]
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"version": 2, "resources": manifest}))
            for record in records:
                archive.write(record.path, f"resources/{record.kind}/{record.path.name}")
        return destination

    def import_bundle(self, source: str | Path) -> list[Path]:
        imported: list[Path] = []
        with zipfile.ZipFile(source, "r") as archive:
            infos = archive.infolist()
            if sum(max(0, item.file_size) for item in infos) > self.MAX_BUNDLE_BYTES:
                raise ValueError("Resource bundle exceeds the import budget")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("version") not in (1, 2) or not isinstance(manifest.get("resources"), list):
                raise ValueError("Invalid resource bundle manifest")
            declared = {(str(item.get("kind")), str(item.get("name"))): item
                        for item in manifest["resources"] if isinstance(item, dict)}
            allowed = {f"resources/{kind}/" for kind in self.KINDS}
            for info in infos:
                if info.is_dir() or info.filename == "manifest.json":
                    continue
                if not any(info.filename.startswith(prefix) for prefix in allowed):
                    raise ValueError("Resource bundle contains an invalid path")
                relative = Path(info.filename)
                if ".." in relative.parts:
                    raise ValueError("Resource bundle path traversal")
                kind = relative.parts[1]
                suffix = relative.suffix.lower()
                if suffix not in self.KINDS[kind]:
                    raise ValueError("Resource bundle contains an unsupported file")
                target = self.root / kind / relative.name
                if target.exists():
                    target = target.with_name(f"{target.stem}-{uuid4().hex[:8]}{target.suffix}")
                written = 0
                with archive.open(info) as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(min(1024 * 1024, self.MAX_BUNDLE_BYTES - written))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self.MAX_BUNDLE_BYTES:
                            raise ValueError("Resource bundle exceeds the import budget")
                        dst.write(chunk)
                descriptor = declared.get((kind, relative.name), {})
                expected_hash = descriptor.get("sha256")
                if expected_hash is not None and (not isinstance(expected_hash, str)
                                                  or self._hash(target) != expected_hash):
                    target.unlink(missing_ok=True)
                    raise ValueError("Resource bundle hash mismatch")
                imported.append(target)
        return imported

    def dependency_status(self, record: ResourceRecord) -> tuple[str, ...]:
        """Return missing resource identifiers without importing side effects."""
        available = {f"{item.kind}:{item.name}" for item in self.catalog(app=None)}
        return tuple(dependency for dependency in record.dependencies if dependency not in available)

    def update_resource(self, record: ResourceRecord, source: str | Path) -> ResourceRecord:
        """Atomically replace a resource while retaining a content-addressed rollback copy."""
        source = Path(source)
        if (record.kind not in self.KINDS or not source.is_file()
                or source.suffix.lower() not in self.KINDS[record.kind]):
            raise ValueError("Mise à jour de ressource invalide")
        previous_hash = self._hash(record.path)
        history = self.root / ".history" / record.kind / record.path.stem
        history.mkdir(parents=True, exist_ok=True)
        backup = history / f"{previous_hash}{record.path.suffix}"
        if not backup.exists():
            shutil.copy2(record.path, backup)
        temporary = record.path.with_name(f".{record.path.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, record.path)
        finally:
            temporary.unlink(missing_ok=True)
        return next(item for item in self.catalog(record.kind, app=None)
                    if item.path == record.path)

    def rollback_resource(self, record: ResourceRecord, content_hash: str) -> ResourceRecord:
        """Restore a previously retained version by its SHA-256 content hash."""
        token = str(content_hash).lower()
        if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
            raise ValueError("Empreinte de ressource invalide")
        backup = self.root / ".history" / record.kind / record.path.stem / f"{token}{record.path.suffix}"
        if not backup.is_file() or self._hash(backup) != token:
            raise ValueError("Version de ressource introuvable")
        temporary = record.path.with_name(f".{record.path.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(backup, temporary)
            os.replace(temporary, record.path)
        finally:
            temporary.unlink(missing_ok=True)
        return next(item for item in self.catalog(record.kind, app=None)
                    if item.path == record.path)
