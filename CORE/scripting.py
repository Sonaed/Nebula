"""Public, capability-limited Nebula scripting API (``nebula.script.v1``).

Scripts receive document operations, never a Qt window, filesystem path or
native pointer. A host chooses grants before it invokes a trusted callable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import QPoint

API_VERSION = "nebula.script.v1"


class ScriptPermissionError(PermissionError):
    """Raised before an operation outside the host's grants is performed."""


@dataclass(frozen=True)
class ScriptPermissions:
    """Explicit host grants; the default facade is read-only."""
    read_document: bool = True
    modify_document: bool = False
    save_document: bool = False
    export_document: bool = False


@dataclass
class ScriptDocument:
    document: Any
    save_callback: Callable[[], bool] | None = None
    export_callback: Callable[[str], bool] | None = None
    permissions: ScriptPermissions = field(default_factory=ScriptPermissions)

    def _require(self, capability: str) -> None:
        if not getattr(self.permissions, capability):
            raise ScriptPermissionError(f"Le script n’a pas la permission {capability}.")

    @property
    def size(self) -> tuple[int, int]:
        self._require("read_document")
        return int(self.document.width), int(self.document.height)

    def layers(self) -> tuple[dict[str, Any], ...]:
        self._require("read_document")
        return tuple({"id": str(layer.id), "name": str(layer.name),
                      "visible": bool(layer.visible), "opacity": float(layer.opacity),
                      "blend_mode": str(layer.blend_mode),
                      "kind": str(getattr(layer, "layer_kind", "raster"))}
                     for layer in self.document.layers)

    def _layer(self, layer_id: str):
        for layer in self.document.layers:
            if str(layer.id) == str(layer_id):
                return layer
        raise KeyError(f"Calque introuvable : {layer_id}")

    def add_layer(self, name: str = "Nouveau calque") -> str:
        self._require("modify_document")
        return str(self.document.add_layer(name).id)

    def add_retouch_layer(self, name: str = "Retouche") -> str:
        self._require("modify_document")
        return str(self.document.add_retouch_layer(name).id)

    def add_adjustment(self, kind: str, name: str | None = None, spec: dict | None = None) -> str:
        self._require("modify_document")
        layer = self.document.add_adjustment_layer(kind, name, spec)
        return str(layer.id)

    def set_layer(self, layer_id: str, *, visible: bool | None = None,
                  opacity: float | None = None, blend_mode: str | None = None) -> None:
        self._require("modify_document")
        layer = self._layer(layer_id)
        if visible is not None:
            layer.visible = bool(visible)
        if opacity is not None:
            layer.opacity = max(0.0, min(1.0, float(opacity)))
        if blend_mode is not None:
            layer.blend_mode = str(blend_mode)

    def add_mask_from_selection(self, layer_id: str) -> None:
        """Attach the current selection as an editable alpha mask."""
        self._require("modify_document")
        layer = self._layer(layer_id)
        mask = QImage(self.document.selection.image.size(), QImage.Format.Format_ARGB32)
        for y in range(mask.height()):
            for x in range(mask.width()):
                alpha = self.document.selection.image.pixelColor(x, y).alpha()
                mask.setPixelColor(x, y, QColor(255, 255, 255, alpha))
        layer.set_alpha_mask(mask)

    def retouch_clone(self, source_layer_id: str, target: tuple[int, int],
                      source: tuple[int, int], radius: int = 16,
                      retouch_layer_id: str | None = None) -> str:
        """Apply a clone operation to a separate retouch layer."""
        self._require("modify_document")
        from TOOLS.retouch_tool import RetouchTool
        source_layer = self._layer(source_layer_id)
        destination = self._layer(retouch_layer_id) if retouch_layer_id else None
        result = RetouchTool().clone(self.document, source_layer, QPoint(*source), QPoint(*target),
                                     radius, layer=destination)
        return str(result.id)

    def save_selection(self, name: str) -> bool:
        self._require("modify_document")
        return bool(self.document.save_selection(name))

    def load_selection(self, name: str) -> bool:
        self._require("modify_document")
        return bool(self.document.load_selection(name))

    def selection_names(self) -> tuple[str, ...]:
        self._require("read_document")
        return tuple(sorted(self.document.saved_selections))

    def clear_selection(self) -> None:
        self._require("modify_document")
        self.document.selection.clear()

    def select_all(self) -> None:
        self._require("modify_document")
        self.document.selection.select_all()

    def save(self) -> bool:
        self._require("save_document")
        return bool(self.save_callback and self.save_callback())

    def export(self, target: str) -> bool:
        self._require("export_document")
        return bool(self.export_callback and self.export_callback(str(target)))


def run_script(script: Callable[[ScriptDocument], Any], document: Any,
               save_callback: Callable[[], bool] | None = None, *,
               export_callback: Callable[[str], bool] | None = None,
               permissions: ScriptPermissions | None = None) -> Any:
    """Run a trusted callable against a versioned, permissioned facade."""
    if not callable(script):
        raise TypeError("script must be callable")
    return script(ScriptDocument(document, save_callback, export_callback,
                                 permissions or ScriptPermissions()))


__all__ = ["API_VERSION", "ScriptDocument", "ScriptPermissionError",
           "ScriptPermissions", "run_script"]
