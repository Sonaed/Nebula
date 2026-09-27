from PySide6.QtGui import QColor, QImage, QPainter
from uuid import uuid4
from DOCUMENTS.tile_store import TileStore, TILE_SIZE


class Layer:

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
    ):
        self.id = str(uuid4())
        # =========================
        # Informations du calque
        # =========================

        self.name = name

        self.visible = True

        self.opacity = 1.0
        self.blend_mode = "normal"
        self.blend_parameters: dict[str, float] = {}
        self.locked = False
        self.lock_alpha = False
        self.clipping = False
        self.label_color: str | None = None
        # Optional non-destructive Photoshop-compatible metadata.  Raster
        # layers keep the existing fast tile path; adjustment layers and
        # effects are evaluated by the composition/export pipeline.
        self.layer_kind = "raster"
        self.adjustment = None
        self.layer_effects: list[dict] = []
        self.psd_effects: list[dict] = []

        # =========================
        # Image du calque
        # =========================

        self.tile_store = TileStore(width, height, TILE_SIZE, QImage.Format.Format_ARGB32)
        # Optional editable alpha mask.  An absent mask means full coverage;
        # when present, its alpha channel is multiplied by the layer pixels in
        # CreativeCore during composition.
        self.alpha_mask_store: TileStore | None = None
        # When True the mask is kept but not applied during projection,
        # equivalent to Photoshop's Shift-click mask disable.
        self.mask_disabled: bool = False
        self._image_cache: QImage | None = None
        self._image_cache_key: int | None = None
        self._cache_dirty = False

    def ensure_alpha_mask(self) -> TileStore:
        """Create the sparse mask store on first use."""
        if self.alpha_mask_store is None:
            self.alpha_mask_store = TileStore(
                self.tile_store.width, self.tile_store.height,
                self.tile_store.tile_size, QImage.Format.Format_ARGB32,
            )
        return self.alpha_mask_store

    def set_alpha_mask(self, image: QImage | None) -> None:
        """Replace or remove the editable alpha mask."""
        if image is None or image.isNull():
            if self.alpha_mask_store is not None:
                self.alpha_mask_store.close()
            self.alpha_mask_store = None
            return
        if image.width() != self.tile_store.width or image.height() != self.tile_store.height:
            raise ValueError("Le masque alpha doit avoir la taille du document")
        self.ensure_alpha_mask().write_image(image)

    def alpha_mask_coverage(self) -> QImage | None:
        """Full-document mask coverage (white RGB, coverage in alpha).

        ``TileStore.materialize()`` fills absent tiles with transparent pixels,
        which for a mask means "hidden".  A sparse mask treats absent tiles as
        full coverage (Photoshop's white), so every full-document consumer must
        go through this instead of materialize().
        """
        store = self.alpha_mask_store
        if store is None:
            return None
        image = QImage(store.width, store.height, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255, 255))
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        for tx, ty in store.occupied_keys:
            painter.drawImage(store.tile_rect(tx, ty).topLeft(), store.tile(tx, ty))
        painter.end()
        return image

    def alpha_mask_grayscale(self, fmt=QImage.Format.Format_RGBA8888) -> QImage | None:
        """Photoshop-style view of the mask: opaque grey, black hides, white reveals."""
        store = self.alpha_mask_store
        if store is None:
            return None
        image = QImage(store.width, store.height, fmt)
        image.fill(QColor(255, 255, 255, 255))
        painter = QPainter(image)
        for tx, ty in store.occupied_keys:
            rect = store.tile_rect(tx, ty)
            # coverage alpha a over black -> grey level a
            painter.fillRect(rect, QColor(0, 0, 0, 255))
            painter.drawImage(rect.topLeft(), store.tile(tx, ty))
        painter.end()
        return image

    @property
    def alpha_mask(self) -> QImage | None:
        """Compatibility view of the mask; storage remains sparse/native."""
        return self.alpha_mask_coverage()

    @property
    def image(self) -> QImage:
        """Compatibility image view; tile storage remains authoritative."""
        self.commit_image_cache()
        if self._image_cache is None:
            self._image_cache = self.tile_store.materialize()
            self._image_cache_key = int(self._image_cache.cacheKey())
            self._cache_dirty = False
        return self._image_cache

    @image.setter
    def image(self, image: QImage) -> None:
        self.tile_store.write_image(image)
        self._image_cache = None
        self._image_cache_key = None
        self._cache_dirty = False

    def adopt_image_cache(self, image: QImage) -> None:
        """Use a compatible mutable image as a stroke buffer without a full write.

        The caller must synchronize every modified dirty rectangle through
        ``commit_image_cache``. This is intended for CreativeCore, which
        returns a converted contiguous buffer after applying a local dab.
        """
        if image.isNull() or image.width() != self.tile_store.width or image.height() != self.tile_store.height:
            raise ValueError("Stroke buffer dimensions do not match the layer")
        self._image_cache = image
        self._image_cache_key = int(image.cacheKey())
        # Adoption is used for buffers returned by CreativeCore after an
        # in-place operation; cacheKey() is unchanged by that operation.
        self._cache_dirty = True

    def mark_image_cache_dirty(self) -> None:
        """Record an in-place native write; cacheKey() is not reliable for it."""
        if self._image_cache is not None:
            self._cache_dirty = True

    def commit_image_cache(self, rect=None, release: bool = False, force: bool = False) -> set[tuple[int, int]]:
        image = self._image_cache
        changed: set[tuple[int, int]] = set()
        if image is not None and (force or self._cache_dirty or int(image.cacheKey()) != self._image_cache_key):
            changed = self.tile_store.write_image(image, rect)
            self._image_cache_key = int(image.cacheKey())
            self._cache_dirty = False
        if release:
            self._image_cache = None
            self._image_cache_key = None
            self._cache_dirty = False
        return changed

    def release_image_cache(self) -> None:
        self.commit_image_cache(release=True)

    def discard_image_cache(self) -> None:
        """Drop the compatibility image after authoritative tile edits."""
        self._image_cache = None
        self._image_cache_key = None
        self._cache_dirty = False
