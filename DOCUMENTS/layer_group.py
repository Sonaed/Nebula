from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import uuid4

from PySide6.QtGui import QImage
from CORE.native_bridge import clone_image_native


@dataclass
class LayerGroup:
    """Isolated group of contiguous document layers with a small tile cache."""

    name: str = "Groupe"
    id: str = field(default_factory=lambda: str(uuid4()))
    layer_ids: list[str] = field(default_factory=list)
    # ``None`` designates a root group.  A nested group still lists its leaf
    # layers so tile storage remains flat, but its compositing scope is owned
    # by the parent group.
    parent_id: str | None = None
    visible: bool = True
    opacity: float = 1.0
    blend_mode: str = "normal"
    blend_parameters: dict[str, float] = field(default_factory=dict)
    _tile_cache: OrderedDict = field(default_factory=OrderedDict, repr=False)
    cache_limit: int = 256

    def cached_tile(self, key: tuple[int, int], signature: tuple) -> QImage | None:
        entry = self._tile_cache.get(key)
        if entry is None or entry[0] != signature:
            return None
        self._tile_cache.move_to_end(key)
        clone = clone_image_native(entry[1])
        if clone is None:
            raise RuntimeError("CreativeCore is required to read group cache tiles")
        return clone

    def store_tile(self, key: tuple[int, int], signature: tuple, image: QImage) -> None:
        clone = clone_image_native(image)
        if clone is None:
            raise RuntimeError("CreativeCore is required to store group cache tiles")
        self._tile_cache[key] = (signature, clone)
        self._tile_cache.move_to_end(key)
        while len(self._tile_cache) > max(1, self.cache_limit):
            self._tile_cache.popitem(last=False)

    def invalidate(self) -> None:
        self._tile_cache.clear()

    def cache_size_bytes(self) -> int:
        return sum(int(image.sizeInBytes()) for _signature, image in self._tile_cache.values())
