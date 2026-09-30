from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from CORE.native_bridge import (load_creative_core, native_selection_bounds,
                                native_selection_combine, native_selection_contains,
                                native_selection_invert, fill_image_native)
from CORE.native_filters import load_filters
from DOCUMENTS.tile_store import TileStore, TILE_SIZE


def _native_filters():
    """Filtres natifs (ABI >= 4) ou erreur explicite : aucun repli NumPy."""
    filters = load_filters()
    if filters is None or not filters.supports_adjustments:
        raise RuntimeError("CreativeCore récent requis pour les opérations de sélection "
                           "(filtres ABI >= 4).")
    return filters


def _native_selection_library():
    return load_creative_core()


class SelectionOperation(str, Enum):
    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"
    DIFFERENCE = "difference"


class SelectionMask:
    """Document-sized semantic selection with sparse tiled backing.

    Native selection kernels require a contiguous QImage.  ``tile_store`` is
    therefore authoritative between edits while ``_image`` is a short-lived
    working surface materialized only for a native operation or compatibility
    consumer.  This keeps an empty/local selection out of the document's
    resident-tile budget and gives every downstream consumer a stable tile
    index.
    """

    def __init__(self, width: int, height: int) -> None:
        self.tile_size = TILE_SIZE
        self.tile_store = TileStore(width, height, self.tile_size,
                                    QImage.Format.Format_ARGB32)
        self._image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._bounds_cache: QRect | None = None
        self.revision = 0
        self._outline_cache: tuple[int, int, list] | None = None
        self.feather_radius = 0
        self.outline_visible = True
        self.clear()

    @property
    def image(self) -> QImage:
        """Compatibility working image; materialized from sparse tiles lazily."""
        image = getattr(self, "_image", None)
        if image is None:
            image = self.tile_store.materialize()
            self._image = image
        return image

    @image.setter
    def image(self, image: QImage) -> None:
        if image.isNull():
            raise ValueError("Le masque de sélection ne peut pas être nul")
        store = getattr(self, "tile_store", None)
        if store is not None and (store.width != image.width() or store.height != image.height()):
            store.close()
            self.tile_store = TileStore(image.width(), image.height(), self.tile_size,
                                        QImage.Format.Format_ARGB32)
        self._image = image.convertToFormat(QImage.Format.Format_ARGB32)
        self._sync_tiles()

    def _sync_tiles(self) -> None:
        """Publish the dense native working surface as sparse 64px tiles."""
        store = getattr(self, "tile_store", None)
        image = getattr(self, "_image", None)
        if store is None or image is None:
            return
        values = native_selection_bounds(image)
        bounds = QRect(*values) if values is not None else QRect()
        wanted = store.keys_for_rect(bounds)
        for key in store.occupied_keys - wanted:
            store.remove_resident_tile(*key)
        for tx, ty in wanted:
            rect = store.tile_rect(tx, ty)
            tile = image.copy(rect)
            # Bounding rectangles may cross transparent holes. Do not retain
            # those tile slots: a sparse selection must stay sparse.
            tile_bounds = native_selection_bounds(tile)
            if tile_bounds is None or QRect(*tile_bounds).isEmpty():
                store.remove_resident_tile(tx, ty)
            else:
                store.set_tile(tx, ty, tile)

    def invalidate(self) -> None:
        self._bounds_cache = None
        # Lightweight native-wiring fixtures construct this object without
        # __init__; production instances always start at zero.
        self.revision = getattr(self, "revision", 0) + 1
        self._sync_tiles()
        # Native operations are complete at this point.  Releasing the dense
        # staging surface is what makes the TileStore the real backing store
        # for long-lived selections (not merely a serialized mirror).
        self._image = None

    def outline_segments(self):
        """Exact pixel outline of the selection (alpha >= 50%) as line segments.

        Returns a list of (x1, y1, x2, y2) in document pixels, cached until the
        selection changes. Used to draw real marching ants instead of a
        bounding rectangle.
        """
        key = (self.revision, self.image.cacheKey())
        if self._outline_cache is not None and self._outline_cache[:2] == key:
            return self._outline_cache[2]
        import numpy as np
        w, h, stride = self.width, self.height, self.image.bytesPerLine()
        raw = np.frombuffer(self.image.constBits(), dtype=np.uint8, count=stride * h)
        mask = raw.reshape(h, stride)[:, 3:w * 4:4] >= 128
        padded = np.pad(mask, 1)
        segments = []
        # Horizontal edges: between row y-1 and y, spanning x..x+1.
        horizontal = padded[1:, 1:-1] != padded[:-1, 1:-1]          # (h+1, w)
        runs = np.diff(np.pad(horizontal.astype(np.int8), ((0, 0), (1, 1))), axis=1)
        starts, ends = np.argwhere(runs == 1), np.argwhere(runs == -1)
        for (y, x0), (_, x1) in zip(starts, ends):
            segments.append((int(x0), int(y), int(x1), int(y)))
        vertical = padded[1:-1, 1:] != padded[1:-1, :-1]            # (h, w+1)
        runs = np.diff(np.pad(vertical.T.astype(np.int8), ((0, 0), (1, 1))), axis=1)
        starts, ends = np.argwhere(runs == 1), np.argwhere(runs == -1)
        for (x, y0), (_, y1) in zip(starts, ends):
            segments.append((int(x), int(y0), int(x), int(y1)))
        self._outline_cache = (key[0], key[1], segments)
        return segments

    @property
    def width(self) -> int:
        return self.image.width()

    @property
    def height(self) -> int:
        return self.image.height()

    def clear(self) -> None:
        if not fill_image_native(self.image, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear selections")
        self.invalidate()
        self._bounds_cache = QRect()

    def select_all(self) -> None:
        if not fill_image_native(self.image, QColor(255, 255, 255, 255)):
            raise RuntimeError("CreativeCore is required to select the whole document")
        self.invalidate()
        self._bounds_cache = QRect(0, 0, self.tile_store.width, self.tile_store.height)

    def is_empty(self) -> bool:
        return self.bounds().isEmpty()

    def contains(self, x: int, y: int) -> bool:
        selected = native_selection_contains(self.image, x, y)
        if selected is None:
            raise RuntimeError("CreativeCore is required for selection queries")
        return selected

    def combine(self, candidate: QImage, operation: SelectionOperation) -> None:
        if candidate.size() != self.image.size():
            raise ValueError("Le masque de sélection doit avoir la taille du document")
        if operation == SelectionOperation.DIFFERENCE:
            # Symmetric difference: (A − B) ∪ (B − A). Keep the native
            # operations authoritative while exposing the complete public API.
            original = self.image.copy()
            if native_selection_combine(self.image, candidate, SelectionOperation.SUBTRACT.value) is not True:
                raise RuntimeError("CreativeCore is required for selection operations")
            other = candidate.copy()
            if native_selection_combine(other, original, SelectionOperation.SUBTRACT.value) is not True:
                raise RuntimeError("CreativeCore is required for selection operations")
            native_result = native_selection_combine(self.image, other, SelectionOperation.ADD.value)
        else:
            native_result = native_selection_combine(self.image, candidate, operation.value)
        if native_result is not True:
            raise RuntimeError("CreativeCore is required for selection operations")
        self.invalidate()

    def occupied_tiles(self) -> set[tuple[int, int]]:
        """Tile index for consumers that can avoid traversing empty selection areas."""
        return set(self.tile_store.occupied_keys)

    def invert(self) -> None:
        if native_selection_invert(self.image) is not True:
            raise RuntimeError("CreativeCore is required to invert selections")
        self.invalidate()

    def bounds(self) -> QRect:
        if self._bounds_cache is not None:
            return QRect(self._bounds_cache)
        values = native_selection_bounds(self.image)
        if values is None:
            raise RuntimeError("CreativeCore is required to measure selections")
        self._bounds_cache = QRect(*values)
        return QRect(self._bounds_cache)

    def feather(self, radius: int) -> None:
        """Feather the selection with a separable box blur (CreativeCore)."""
        radius = max(0, int(radius))
        if radius == 0:
            return
        _native_filters().selection_feather(self.image.bits(), self.width, self.height, radius,
                                            stride=self.image.bytesPerLine())
        self.invalidate()
        self.feather_radius = radius

    def expand(self, radius: int) -> None:
        """Grow the selection by a square morphological radius."""
        radius = max(0, int(radius))
        if radius == 0:
            return
        _native_filters().selection_morph(self.image.bits(), self.width, self.height, radius,
                                          True, stride=self.image.bytesPerLine())
        self.invalidate()

    def contract(self, radius: int) -> None:
        """Shrink the selection by a square morphological radius."""
        radius = max(0, int(radius))
        if radius == 0:
            return
        _native_filters().selection_morph(self.image.bits(), self.width, self.height, radius,
                                          False, stride=self.image.bytesPerLine())
        self.invalidate()

    def select_color_range(self, image: QImage, color: QColor, tolerance: int = 16) -> None:
        """Create a soft selection from a sampled RGB color."""
        if image.size() != self.image.size():
            raise ValueError("Color range image must match the document")
        filters = _native_filters()
        source = image.convertToFormat(QImage.Format.Format_RGBA8888)
        filters.select_color_range(self.image.bits(), self.width, self.height,
                                   source.constBits(), (color.red(), color.green(), color.blue()),
                                   int(tolerance), stride=self.image.bytesPerLine(),
                                   source_stride=source.bytesPerLine())
        self.invalidate()

    def select_alpha(self, image: QImage) -> None:
        """Replace this selection with a layer's alpha channel natively."""
        if image.size() != self.image.size():
            raise ValueError("Layer image must match the document")
        self.combine(image, SelectionOperation.REPLACE)


__all__ = ["SelectionMask", "SelectionOperation"]
