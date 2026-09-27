"""Resolve Existence-owned module manifests without making Nebula dependent on them."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _existence_root() -> Path:
    return Path(os.environ.get("EXISTENCE_ROOT", "/home/deanos/Documents/Existence"))


def load_manifest(module_id: str) -> dict[str, Any]:
    """Return a manifest dict, with a safe local fallback for standalone Nebula."""
    root = _existence_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from modules.registry import default_registry
        manifest = default_registry().manifest(module_id)
        if manifest is not None:
            return manifest.to_dict()
    except (ImportError, OSError):
        pass
    return {"id": module_id, "module_type": "existence_module", "version": "unknown"}


class ExistenceModuleAdapter:
    """Host-side identity shared by all Existence-provided dock presentations."""

    def __init__(self, module_id: str, host_id: str = "nebula") -> None:
        self.module_id = module_id
        self.host_id = host_id
        self.manifest = load_manifest(module_id)

    @property
    def accepts(self) -> tuple[str, ...]:
        return tuple(self.manifest.get("accepts", ()))

    @property
    def ui_modes(self) -> tuple[str, ...]:
        return tuple(self.manifest.get("ui_modes", ()))

