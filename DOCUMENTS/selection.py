from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect, QPoint
from PySide6.QtGui import QColor, QImage
from CORE.native_bridge import (load_creative_core, native_selection_bounds,
                                native_selection_combine, native_selection_contains,
                                native_selection_invert, fill_image_native)
from CORE.native_bridge import copy_image_rect_native
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
    """Dense native working surface with a lazily published sparse save cache.

    Empty masks allocate no full canvas. Editing an active selection keeps one
    dense surface rather than splitting and reassembling it after each kernel.
    """

    def __init__(self, width: int, height: int) -> None:
        self.tile_size = TILE_SIZE
        self._tile_store = TileStore(width, height, self.tile_size, QImage.Format.Format_ARGB32)
        self._tiles_dirty = False
        self._image = None
        self._bounds_cache = QRect()
        self.revision = 0
        self._outline_cache = None
        self.feather_radius = 0
        self.outline_visible = True

    @property
    def tile_store(self) -> TileStore:
        if self._tiles_dirty:
            self._sync_tiles()
        return self._tile_store

    @tile_store.setter
    def tile_store(self, store):
        self._tile_store = store
        self._tiles_dirty = False

    @property
    def image(self) -> QImage:
        if self._image is None:
            self._image = self._tile_store.materialize()
        return self._image

    @image.setter
    def image(self, image: QImage) -> None:
        if image.isNull():
            raise ValueError("Le masque de sélection ne peut pas être nul")
        store = getattr(self, '_tile_store', None)
        if store is not None and (store.width != image.width() or store.height != image.height()):
            store.close()
            self._tile_store = TileStore(image.width(), image.height(), self.tile_size, QImage.Format.Format_ARGB32)
        self._image = image.convertToFormat(QImage.Format.Format_ARGB32)
        self._tiles_dirty = True
        self._bounds_cache = None

    def _sync_tiles(self) -> None:
        store = getattr(self, '_tile_store', None)
        image = getattr(self, '_image', None)
        if store is None or image is None:
            return
        bounds = self.bounds()
        wanted = store.keys_for_rect(bounds)
        for key in store.occupied_keys - wanted:
            store.remove_resident_tile(*key)
        writes = []
        for tx, ty in wanted:
            tile = image.copy(store.tile_rect(tx, ty))
            values = native_selection_bounds(tile)
            if values is not None and not QRect(*values).isEmpty():
                writes.append((tx, ty, tile))
            else:
                store.remove_resident_tile(tx, ty)
        if writes and not store.set_tiles_batch(writes):
            raise OSError('Could not publish selection tiles')
        self._tiles_dirty = False

    def invalidate(self) -> None:
        self._bounds_cache = None
        self._outline_cache = None
        self.revision = getattr(self, 'revision', 0) + 1
        self._tiles_dirty = True

    def outline_segments(self):
        """Exact pixel outline of the selection (alpha >= 50%) as line segments.

        Returns a list of (x1, y1, x2, y2) in document pixels, cached until the
        selection changes. Used to draw real marching ants instead of a
        bounding rectangle.
        """
        if self.bounds().isEmpty():
            return []
        key = (self.revision, self.image.cacheKey())
        if self._outline_cache is not None and self._outline_cache[:2] == key:
            return self._outline_cache[2]
        import numpy as np
        bounds = self.bounds()
        if bounds.isEmpty():
            self._outline_cache = (key[0], key[1], [])
            return []
        w, h, stride = self.width, self.height, self.image.bytesPerLine()
        raw = np.frombuffer(self.image.constBits(), dtype=np.uint8, count=stride * h)
        alpha = raw.reshape(h, stride)[:, 3:w * 4:4]
        mask = alpha[bounds.top():bounds.bottom()+1, bounds.left():bounds.right()+1] >= 128
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
        segments = [(x0+bounds.x(), y0+bounds.y(), x1+bounds.x(), y1+bounds.y())
                    for x0,y0,x1,y1 in segments]
        self._outline_cache = (key[0], key[1], segments)
        return segments

    @property
    def width(self) -> int:
        return self._tile_store.width if hasattr(self, '_tile_store') else self.image.width()

    @property
    def height(self) -> int:
        return self._tile_store.height if hasattr(self, '_tile_store') else self.image.height()

    def clear(self) -> None:
        store = getattr(self, '_tile_store', None)
        if store is None:  # Minimal native-wiring fixtures.
            if not fill_image_native(self.image, QColor(0, 0, 0, 0)):
                raise RuntimeError('CreativeCore is required to clear selections')
        else:
            self._image = None
            for key in store.occupied_keys:
                store.remove_resident_tile(*key)
        self.invalidate()
        self._tiles_dirty = False
        self._bounds_cache = QRect()

    def select_all(self) -> None:
        if not fill_image_native(self.image, QColor(255, 255, 255, 255)):
            raise RuntimeError("CreativeCore is required to select the whole document")
        self.invalidate()
        self._bounds_cache = QRect(0, 0, self.width, self.height)

    def is_empty(self) -> bool:
        # The overwhelmingly common painting case has no selection.  Asking
        # ``bounds()`` in that state used to materialize a full-canvas image
        # merely to prove that its alpha was zero.  A 48 MP canvas then paid
        # that allocation from every brush segment (and once per symmetry
        # copy).  With no dense edit surface and no sparse tiles, emptiness is
        # already exact.
        if self._image is None and not self._tile_store.occupied_keys:
            return True
        if self._bounds_cache is not None:
            return self._bounds_cache.isEmpty()
        return self.bounds().isEmpty()

    def contains(self, x: int, y: int) -> bool:
        selected = native_selection_contains(self.image, x, y)
        if selected is None:
            raise RuntimeError("CreativeCore is required for selection queries")
        return selected

    def combine(self, candidate: QImage, operation: SelectionOperation) -> None:
        if candidate.size() != self.image.size():
            raise ValueError("Le masque de sélection doit avoir la taille du document")
        # Layer pixels are usually premultiplied: the native kernel reads
        # straight ARGB32, and used to reject them ("Depuis la transparence
        # du calque" raised instead of selecting).
        if candidate.format() != QImage.Format.Format_ARGB32:
            candidate = candidate.convertToFormat(QImage.Format.Format_ARGB32)
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

    def combine_region(self, candidate: QImage, origin: QPoint,
                       operation: SelectionOperation) -> None:
        """Apply a document-coordinate candidate without allocating its empty border."""
        extent = QRect(0, 0, self.width, self.height)
        area = QRect(origin, candidate.size()).intersected(extent)
        previous = self.bounds()
        if operation == SelectionOperation.REPLACE:
            self.clear()
        elif operation == SelectionOperation.INTERSECT:
            # Intersect must also clear previously selected pixels outside B.
            common = previous.intersected(area)
            if common.isEmpty():
                self.clear()
                return
            before = self.image.copy(common)
            other = candidate.copy(common.translated(-origin))
            if not native_selection_combine(before, other, operation.value):
                raise RuntimeError('CreativeCore is required for selection operations')
            self.clear()
            copy_image_rect_native(before, self.image, before.rect(), common.x(), common.y())
            self.invalidate()
            return
        if area.isEmpty():
            return
        local = self.image.copy(area)
        other = candidate.copy(area.translated(-origin))
        if other.format() != QImage.Format.Format_ARGB32:
            other = other.convertToFormat(QImage.Format.Format_ARGB32)
        if operation == SelectionOperation.DIFFERENCE:
            original = QImage(local)
            native_selection_combine(local, other, 'subtract')
            right = QImage(other)
            native_selection_combine(right, original, 'subtract')
            ok = native_selection_combine(local, right, 'add')
        else:
            ok = native_selection_combine(local, other, operation.value)
        if not ok or not copy_image_rect_native(local, self.image, local.rect(), area.x(), area.y()):
            raise RuntimeError('CreativeCore is required for selection operations')
        self.invalidate()

    def invert(self) -> None:
        if native_selection_invert(self.image) is not True:
            raise RuntimeError("CreativeCore is required to invert selections")
        self.invalidate()

    def bounds(self) -> QRect:
        if self._bounds_cache is not None:
            return QRect(self._bounds_cache)
        if self._image is None and not self._tile_store.occupied_keys:
            self._bounds_cache = QRect()
            return QRect()
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
        self._filter_region(radius, lambda image: _native_filters().selection_feather(
            image.bits(), image.width(), image.height(), radius, stride=image.bytesPerLine()))
        self.feather_radius = radius

    def expand(self, radius: int) -> None:
        """Grow the selection by a square morphological radius."""
        radius = max(0, int(radius))
        if radius == 0:
            return
        self._filter_region(radius, lambda image: _native_filters().selection_morph(
            image.bits(), image.width(), image.height(), radius, True, stride=image.bytesPerLine()))

    def contract(self, radius: int) -> None:
        """Shrink the selection by a square morphological radius."""
        radius = max(0, int(radius))
        if radius == 0:
            return
        self._filter_region(radius, lambda image: _native_filters().selection_morph(
            image.bits(), image.width(), image.height(), radius, False, stride=image.bytesPerLine()))

    def _filter_region(self, margin, operation):
        if not hasattr(self, '_tile_store'):
            operation(self.image)
            self.invalidate()
            return
        bounds = self.bounds()
        if bounds.isEmpty():
            return
        rect = bounds.adjusted(-margin, -margin, margin, margin).intersected(QRect(0, 0, self.width, self.height))
        region = self.image.copy(rect)
        operation(region)
        if not copy_image_rect_native(region, self.image, region.rect(), rect.x(), rect.y()):
            raise RuntimeError('Could not apply the selection filter')
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
