from PySide6.QtGui import QImage
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

        # =========================
        # Image du calque
        # =========================

        self.tile_store = TileStore(width, height, TILE_SIZE, QImage.Format.Format_ARGB32)
        # Optional editable alpha mask.  An absent mask means full coverage;
        # when present, its alpha channel is multiplied by the layer pixels in
        # CreativeCore during composition.
        self.alpha_mask_store: TileStore | None = None
        self._image_cache: QImage | None = None
        self._image_cache_key: int | None = None

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

    @property
    def alpha_mask(self) -> QImage | None:
        """Compatibility view of the mask; storage remains sparse/native."""
        return None if self.alpha_mask_store is None else self.alpha_mask_store.materialize()

    @property
    def image(self) -> QImage:
        """Compatibility image view; tile storage remains authoritative."""
        self.commit_image_cache()
        if self._image_cache is None:
            self._image_cache = self.tile_store.materialize()
            self._image_cache_key = int(self._image_cache.cacheKey())
        return self._image_cache

    @image.setter
    def image(self, image: QImage) -> None:
        self.tile_store.write_image(image)
        self._image_cache = None
        self._image_cache_key = None

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

    def commit_image_cache(self, rect=None, release: bool = False, force: bool = False) -> set[tuple[int, int]]:
        image = self._image_cache
        changed: set[tuple[int, int]] = set()
        if image is not None and (force or int(image.cacheKey()) != self._image_cache_key):
            changed = self.tile_store.write_image(image, rect)
            self._image_cache_key = int(image.cacheKey())
        if release:
            self._image_cache = None
            self._image_cache_key = None
        return changed

    def release_image_cache(self) -> None:
        self.commit_image_cache(release=True)

    def discard_image_cache(self) -> None:
        """Drop the compatibility image after authoritative tile edits."""
        self._image_cache = None
        self._image_cache_key = None
