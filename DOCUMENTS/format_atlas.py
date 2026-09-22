"""Read-only adapter for legacy Atlas v2/v3 projects.

The file structure, compression and per-layer mask application live in the
CreativeCore C++ bridge. This module only maps decoded native records into the
existing Nebula UI document model; saving is deliberately handled by NebulaFormat.
"""
from __future__ import annotations

import ctypes
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from CORE.native_bridge import read_atlas_project
from DOCUMENTS.document import Document


_BLEND_MAP = {
    "normal": "normal", "multiply": "multiply", "screen": "screen",
    "overlay": "overlay", "add": "addition", "addition": "addition",
    "sub": "subtract", "subtract": "subtract", "difference": "difference",
    "hue": "hue", "sat": "saturation", "saturation": "saturation",
    "lum": "luminosity", "luminosity": "luminosity",
}
class AtlasFormat:
    """Import supported `.atlas` v2/v3 files without ever writing back to them."""

    @staticmethod
    def load(file_path: str | Path) -> Document | None:
        try:
            decoded = read_atlas_project(file_path)
        except (OSError, RuntimeError, MemoryError, ValueError):
            return None
        if decoded is None:
            return None
        try:
            background_name = decoded["background"].lower()
            background_color = {
                "white": QColor(255, 255, 255, 255),
                "black": QColor(0, 0, 0, 255),
            }.get(background_name)
            document = Document(decoded["width"], decoded["height"],
                                decoded["dpi"], background_color)
            document.name = decoded["name"]
            document.author = decoded["author"]
            document.layers.clear()  # discard the blank constructor layer
            for record in decoded["layers"]:
                raw_pixels = record["pixels"]
                buffer_type = ctypes.c_uint8 * len(raw_pixels)
                pixels = buffer_type.from_buffer_copy(raw_pixels)
                image = QImage(pixels, decoded["width"], decoded["height"],
                               decoded["width"] * 4,
                               QImage.Format.Format_RGBA8888)
                layer = document.add_layer(record["name"])
                layer.image = image
                layer.opacity = record["opacity"]
                layer.visible = record["visible"]
                atlas_blend = record["blend"].lower()
                layer.blend_mode = _BLEND_MAP.get(atlas_blend, "normal")
            return document if document.layers else None
        except (MemoryError, OSError, ValueError, RuntimeError, TypeError):
            return None


__all__ = ["AtlasFormat"]
