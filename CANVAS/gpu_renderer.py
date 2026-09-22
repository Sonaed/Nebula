from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from collections import OrderedDict
from math import ceil, floor, log2

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QImage, QOpenGLContext, QTransform
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLTexture,
    QOpenGLTextureBlitter,
)
from .texture_atlas import TextureAtlas


@dataclass
class GPUTexture:
    texture: QOpenGLTexture
    cache_key: int
    width: int
    height: int
    revision: int = -1


class CanvasGPURenderer:
    """
    Backend GPU 2D de CreativeSystem.

    Les Layers restent des QImage côté CPU.
    Le viewport est affiché par OpenGL via
    QOpenGLTextureBlitter.

    Le zoom et le pan sont donc exécutés par
    la carte graphique, tandis que le moteur
    de pinceau reste indépendant.
    """

    def __init__(self) -> None:

        self.initialized = False

        self.blitter: QOpenGLTextureBlitter | None = None

        self.textures: OrderedDict[tuple[int, int, int], GPUTexture] = OrderedDict()
        self.max_cached_tiles = 1024
        self.on_tile_ready = None
        self.texture_atlas = TextureAtlas()
        self.atlas_upload_backend = self._atlas_upload_backend
        self.atlas_texture = None
        self.atlas_gpu_ready = False
        self.atlas_texture_id = 0
        self.atlas_width = self.texture_atlas.size
        self.atlas_height = self.texture_atlas.size
        self.atlas_format = QOpenGLTexture.TextureFormat.RGBA8_UNorm
        self.atlas_dirty_regions = []

        self.dirty_layers: set[int] = set()
        self.dirty_rects: dict[int, QRect] = {}
        self._opaque_tile_cache: dict[tuple[int, int, int], tuple[int, bool]] = {}
        self._gl_library = None
        self._pbo_buffers: list[QOpenGLBuffer] = []
        self._pbo_index = 0
        self.transfer_stats = {
            "full_uploads": 0,
            "full_upload_bytes": 0,
            "dirty_uploads": 0,
            "dirty_upload_bytes": 0,
            "dirty_staging_bytes": 0,
            "pbo_uploads": 0,
            "pbo_upload_bytes": 0,
            "tile_draw_calls": 0,
            "mipmap_generations": 0,
            "occluded_tile_draws": 0,
        }

    @staticmethod
    def _blit_transform(target: QRectF, viewport: QRect) -> QTransform:
        """Build a Qt affine transform without the crashing matrix converter."""
        vw = max(1.0, float(viewport.width()))
        vh = max(1.0, float(viewport.height()))
        return QTransform(
            2.0 * float(target.width()) / vw, 0.0,
            0.0, 2.0 * float(target.height()) / vh,
            2.0 * float(target.x()) / vw - 1.0,
            1.0 - 2.0 * float(target.y() + target.height()) / vh,
        )

    def _atlas_upload_backend(self, atlas_image, rect) -> None:
        """Upload the changed atlas region through the real GL texture."""
        if not self.initialized or QOpenGLContext.currentContext() is None:
            return
        if not self.atlas_gpu_ready or self.atlas_texture is None or rect is None:
            return
        # The native atlas adapter supplies the changed region as a Qt image;
        # keep the upload rectangle absolute without rebuilding a full atlas.
        source = atlas_image.convertToFormat(QImage.Format.Format_RGBA8888)
        patch = source if source.size() == rect.size() else source.copy(rect)
        if self._upload_with_pbo(self.atlas_texture, patch, rect.x(), rect.y()):
            return
        if not self._ensure_gl_upload_function():
            return
        byte_count = patch.sizeInBytes()
        source = (ctypes.c_ubyte * byte_count).from_buffer(patch.bits())
        self.atlas_texture.bind()
        try:
            self._gl_library.glTexSubImage2D(
                0x0DE1, 0, rect.x(), rect.y(), patch.width(), patch.height(),
                0x1908, 0x1401, ctypes.cast(source, ctypes.c_void_p),
            )
        finally:
            self.atlas_texture.release()
        self.transfer_stats["dirty_uploads"] += 1
        self.transfer_stats["dirty_upload_bytes"] += byte_count

    def upload_atlas_region(self, key, image) -> bool:
        return self.texture_atlas.upload_region(key, image, self.atlas_upload_backend)

    def mark_atlas_dirty(self, rect: QRect, image: QImage | None = None) -> None:
        if rect is None or rect.isEmpty():
            return
        region = (rect.x(), rect.y(), rect.width(), rect.height(),
                  image.bytesPerLine() if image is not None else rect.width() * 4,
                  "RGBA8888", image.copy(rect) if image is not None else None)
        self.atlas_dirty_regions.append(region)
        if image is not None and self.atlas_gpu_ready:
            self.upload_atlas_region((rect.x(), rect.y()), image)

    def transfer_stats_snapshot(self, reset: bool = False) -> dict[str, int]:
        """Return cumulative CPU staging/GPU upload measurements."""
        snapshot = dict(self.transfer_stats)
        if reset:
            for key in self.transfer_stats:
                self.transfer_stats[key] = 0
        return snapshot

    @staticmethod
    def compressed_texture_support() -> dict[str, bool]:
        """Report BC4/BC7 support; compression remains opt-in per driver."""
        ctx = QOpenGLContext.currentContext()
        exts = set(ctx.extensions()) if ctx is not None else set()
        return {
            "bc4": b"GL_EXT_texture_compression_rgtc" in exts or b"GL_ARB_texture_compression_rgtc" in exts,
            "bc7": b"GL_EXT_texture_compression_s3tc" in exts or b"GL_ARB_texture_compression_bptc" in exts,
        }

    @staticmethod
    def bounded_dirty_rect(rect: QRect | None, width: int, height: int) -> QRect:
        bounds = QRect(0, 0, width, height)
        return bounds if rect is None else rect.intersected(bounds)

    @staticmethod
    def _mip_levels(width: int, height: int) -> int:
        return max(1, int(floor(log2(max(1, width, height)))) + 1)

    def _generate_mipmaps(self, texture: QOpenGLTexture) -> None:
        texture.generateMipMaps()
        self.transfer_stats["mipmap_generations"] += 1

    def _upload_client_memory(self, texture: QOpenGLTexture, image: QImage,
                              x: int = 0, y: int = 0) -> bool:
        if not self._ensure_gl_upload_function():
            return False
        patch = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        byte_count = patch.sizeInBytes()
        storage = (ctypes.c_ubyte * byte_count).from_buffer(patch.bits())
        texture.bind()
        try:
            self._gl_library.glTexSubImage2D(
                0x0DE1, 0, x, y, patch.width(), patch.height(),
                0x1908, 0x1401, ctypes.c_void_p(ctypes.addressof(storage)),
            )
            self._generate_mipmaps(texture)
        finally:
            texture.release()
        return True

    @staticmethod
    def _image_is_fully_opaque(image: QImage) -> bool:
        if image.isNull():
            return False
        if not image.hasAlphaChannel():
            return True
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(rgba.constBits())
        return all(raw[offset] == 255 for offset in range(3, rgba.sizeInBytes(), 4))

    def _layer_opaque_tiles(self, layer, document_width: int,
                            document_height: int) -> set[tuple[int, int]]:
        """Return fully opaque resident tiles; unknown/swapped tiles stay conservative."""
        store = getattr(layer, "tile_store", None)
        tile_size = getattr(store, "tile_size", 64)
        columns = ceil(document_width / tile_size)
        rows = ceil(document_height / tile_size)
        opaque = set()
        image = None
        for ty in range(rows):
            for tx in range(columns):
                key = (id(layer), tx, ty)
                if store is not None:
                    if not store.has_tile(tx, ty) or not store.tile_is_resident(tx, ty):
                        continue
                    revision = store.tile_revision(tx, ty)
                else:
                    image = layer.image
                    revision = int(image.cacheKey())
                cached = self._opaque_tile_cache.get(key)
                if cached is not None and cached[0] == revision:
                    is_opaque = cached[1]
                else:
                    x, y = tx * tile_size, ty * tile_size
                    width = min(tile_size, document_width - x)
                    height = min(tile_size, document_height - y)
                    tile = store.tile(tx, ty) if store is not None else image.copy(x, y, width, height)
                    is_opaque = self._image_is_fully_opaque(tile)
                    self._opaque_tile_cache[key] = (revision, is_opaque)
                if is_opaque:
                    opaque.add((tx, ty))
        return opaque

    def compute_occlusion(self, layers, document_width: int,
                          document_height: int) -> dict[int, set[tuple[int, int]]]:
        """Collect tiles covered by eligible opaque layers above each layer."""
        covered: set[tuple[int, int]] = set()
        occluded: dict[int, set[tuple[int, int]]] = {}
        for layer in reversed(layers):
            occluded[id(layer)] = set(covered)
            eligible = (
                layer.visible
                and str(getattr(layer, "blend_mode", "normal")).lower() == "normal"
                and not getattr(layer, "blend_parameters", {})
                and float(getattr(layer, "opacity", 1.0)) >= 1.0
                and not bool(getattr(layer, "clipping", False))
            )
            if eligible:
                covered.update(self._layer_opaque_tiles(layer, document_width, document_height))
        return occluded

    # ==========================================================
    # INITIALISATION
    # ==========================================================

    def initialize(self) -> bool:

        # PySide6 6.11 with CPython 3.14 has a reproducible native crash in
        # QOpenGLTextureBlitter's Shiboken conversion layer during paintGL.
        # Keep the application usable until that binding is fixed; users can
        # explicitly opt in to the GPU path for a newer, known-good binding.
        if (sys.version_info >= (3, 14) and
                os.environ.get("CREATIVESYSTEM_ENABLE_UNSAFE_GPU_BLITTER") != "1"):
            self.atlas_gpu_ready = False
            self.initialized = False
            return False

        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:

            print(
                "GPU ERROR : aucun contexte OpenGL courant."
            )

            return False

        # Qt's texture blitter has an ES 1.00 shader variant which is not
        # compatible with the advanced blend-equation qualifiers emitted by
        # some drivers.  Prefer the desktop GLSL path requested at startup;
        # if the platform cannot provide it, use the existing CPU fallback
        # instead of repeatedly compiling a broken shader every frame.
        try:
            version = context.format().version()
            if context.isOpenGLES() or version < (3, 0):
                print(
                    "GPU indisponible : contexte OpenGL desktop/GLSL 3 requis "
                    f"(obtenu {'OpenGL ES' if context.isOpenGLES() else 'OpenGL'} {version[0]}.{version[1]})"
                )
                return False
        except (AttributeError, TypeError):
            # Keep compatibility with unusual Qt/platform bindings; creation
            # below remains the final capability check.
            pass

        self.blitter = QOpenGLTextureBlitter()

        if not self.blitter.create():

            print(
                "GPU ERROR : QOpenGLTextureBlitter.create() a échoué."
            )

            self.blitter = None

            return False

        try:
            atlas = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            atlas.setFormat(self.atlas_format)
            atlas.setSize(self.atlas_width, self.atlas_height)
            atlas.setMipLevels(1)
            atlas.allocateStorage()
            atlas.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            atlas.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            atlas.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self.atlas_texture = atlas
            self.atlas_texture_id = int(atlas.textureId())
            self.atlas_gpu_ready = bool(atlas.isCreated() and self.atlas_texture_id)
        except Exception:
            self.atlas_texture = None
            self.atlas_texture_id = 0
            self.atlas_gpu_ready = False

        self._initialize_pbo_ring()

        self.initialized = True

        print(
            "✓ GPU renderer OpenGL initialisé"
        )

        return True

    def _initialize_pbo_ring(self) -> None:
        """Create a double-buffered pixel-unpack ring while the canvas context is current."""
        buffers = []
        for _ in range(2):
            buffer = QOpenGLBuffer(QOpenGLBuffer.Type.PixelUnpackBuffer)
            if not buffer.create():
                for created in buffers:
                    created.destroy()
                self._pbo_buffers = []
                return
            buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
            if not buffer.bind():
                buffer.destroy()
                for created in buffers:
                    created.destroy()
                self._pbo_buffers = []
                return
            buffer.allocate(4)
            buffer.release()
            buffers.append(buffer)
        self._pbo_buffers = buffers
        self._pbo_index = 0

    def _ensure_gl_upload_function(self) -> bool:
        if self._gl_library is not None:
            return True
        library_name = ctypes.util.find_library("GL")
        if not library_name:
            return False
        self._gl_library = ctypes.CDLL(library_name)
        self._gl_library.glTexSubImage2D.argtypes = [
            ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self._gl_library.glTexSubImage2D.restype = None
        return True

    def _upload_with_pbo(self, texture: QOpenGLTexture, image: QImage,
                         x: int = 0, y: int = 0) -> bool:
        """Stage an image in a rotating PBO, then enqueue its texture transfer."""
        if not self._pbo_buffers or QOpenGLContext.currentContext() is None:
            return False
        patch = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        byte_count = patch.sizeInBytes()
        if byte_count <= 0:
            return False
        pbo = self._pbo_buffers[self._pbo_index]
        self._pbo_index = (self._pbo_index + 1) % len(self._pbo_buffers)
        if not pbo.bind():
            return False
        try:
            # Reallocating with a null store lets the driver orphan storage
            # still consumed by an earlier DMA transfer from this ring slot.
            pbo.allocate(byte_count)
            mapped = pbo.mapRange(
                0, byte_count,
                QOpenGLBuffer.RangeAccessFlag.RangeWrite |
                QOpenGLBuffer.RangeAccessFlag.RangeInvalidateBuffer,
            )
            # Shiboken's VoidPtr has a false boolean value even when it wraps
            # a valid address, so test its numeric pointer instead.
            mapped_address = int(mapped) if mapped is not None else 0
            if mapped_address == 0:
                return False
            source = (ctypes.c_ubyte * byte_count).from_buffer(patch.bits())
            ctypes.memmove(mapped_address, ctypes.addressof(source), byte_count)
            if not pbo.unmap():
                return False
            texture.bind()
            try:
                if not self._ensure_gl_upload_function():
                    return False
                self._gl_library.glTexSubImage2D(
                    0x0DE1, 0, x, y, patch.width(), patch.height(),
                    0x1908, 0x1401, ctypes.c_void_p(0),
                )
            finally:
                texture.release()
        finally:
            pbo.release()
        self.transfer_stats["pbo_uploads"] += 1
        self.transfer_stats["pbo_upload_bytes"] += byte_count
        self._generate_mipmaps(texture)
        return True

    # ==========================================================
    # DIRTY
    # ==========================================================

    def mark_layer_dirty(
        self,
        layer,
        rect: QRect | None = None,
    ) -> None:
        key = id(layer)
        self.dirty_layers.add(key)
        if rect is not None and not rect.isEmpty():
            previous = self.dirty_rects.get(key)
            self.dirty_rects[key] = QRect(rect) if previous is None else previous.united(rect)
            self.mark_atlas_dirty(QRect(rect), getattr(layer, "image", None))
        else:
            # No bounds means the caller may have changed arbitrary pixels.
            self.dirty_rects.pop(key, None)

    def prune_layers(self, layers) -> None:
        """Release cached textures for layers no longer in the document."""
        if QOpenGLContext.currentContext() is None:
            return
        live_keys = {id(layer) for layer in layers}
        stale_keys = [key for key in self.textures if key[0] not in live_keys]
        for key in stale_keys:
            gpu_texture = self.textures.pop(key)
            try:
                if gpu_texture.texture.isCreated():
                    gpu_texture.texture.destroy()
            except RuntimeError:
                pass
            self.dirty_layers.discard(key[0])
            self.dirty_rects.pop(key[0], None)
        stale_opacity_keys = [key for key in self._opaque_tile_cache if key[0] not in live_keys]
        for key in stale_opacity_keys:
            self._opaque_tile_cache.pop(key, None)
        self.dirty_layers.intersection_update(live_keys)
        for key in self.dirty_rects.keys() - live_keys:
            self.dirty_rects.pop(key, None)

    # ==========================================================
    # TEXTURE
    # ==========================================================

    def _create_texture(
        self,
        image: QImage,
    ) -> QOpenGLTexture:

        # Premultiplied alpha prevents linear texture filtering from mixing a
        # colored edge with the black RGB values of transparent neighbors.
        image = image.convertToFormat(
            QImage.Format.Format_RGBA8888_Premultiplied
        )

        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        texture.setSize(image.width(), image.height())
        texture.setMipLevels(self._mip_levels(image.width(), image.height()))
        texture.allocateStorage(
            QOpenGLTexture.PixelFormat.RGBA,
            QOpenGLTexture.PixelType.UInt8,
        )

        # Initial layer uploads and scratch-loaded tile uploads share this
        # path.  The PBO ring stages bytes without making the UI wait for the
        # GPU to consume a client-memory pointer. Keep Qt's upload as fallback
        # for drivers without pixel-unpack buffer support.
        if not self._upload_with_pbo(texture, image):
            if not self._upload_client_memory(texture, image):
                texture.destroy()
                raise RuntimeError("Impossible de téléverser l'image OpenGL")

        texture.setMinificationFilter(
            QOpenGLTexture.Filter.LinearMipMapLinear
        )

        texture.setMagnificationFilter(
            QOpenGLTexture.Filter.Linear
        )

        texture.setWrapMode(
            QOpenGLTexture.CoordinateDirection.DirectionS,
            QOpenGLTexture.WrapMode.ClampToEdge,
        )

        texture.setWrapMode(
            QOpenGLTexture.CoordinateDirection.DirectionT,
            QOpenGLTexture.WrapMode.ClampToEdge,
        )

        return texture

    def sync_layer(
        self,
        layer,
    ) -> GPUTexture | None:

        if not self.initialized:
            return None

        if self.blitter is None:
            return None

        key = (id(layer), -1, -1)

        width = layer.image.width()
        height = layer.image.height()

        cache_key = layer.image.cacheKey()

        existing = self.textures.get(
            key
        )

        dirty = key[0] in self.dirty_layers

        # ------------------------------------------------------
        # Texture existante, même taille
        # ------------------------------------------------------

        if (
            existing is not None
            and existing.width == width
            and existing.height == height
        ):

            if (
                dirty
                or existing.cache_key != cache_key
            ):
                dirty_rect = self.dirty_rects.get(key[0]) if dirty else None
                dirty_rect = self.bounded_dirty_rect(dirty_rect, width, height)
                if not dirty_rect.isEmpty():
                    patch = layer.image.copy(dirty_rect).convertToFormat(
                        QImage.Format.Format_RGBA8888_Premultiplied
                    )
                    byte_count = patch.sizeInBytes()
                    if self._upload_with_pbo(
                        existing.texture, patch, dirty_rect.x(), dirty_rect.y()
                    ):
                        self.transfer_stats["dirty_uploads"] += 1
                        self.transfer_stats["dirty_upload_bytes"] += byte_count
                        self.transfer_stats["dirty_staging_bytes"] += byte_count
                    else:
                        # Fallback for unsupported PBOs. This is the legacy
                        # client-memory path and may synchronize with the GPU.
                        if not self._upload_client_memory(
                            existing.texture, patch, dirty_rect.x(), dirty_rect.y()
                        ):
                            raise RuntimeError("OpenGL upload indisponible pour glTexSubImage2D")
                        self.transfer_stats["dirty_uploads"] += 1
                        self.transfer_stats["dirty_upload_bytes"] += byte_count
                        self.transfer_stats["dirty_staging_bytes"] += byte_count

                existing.cache_key = cache_key

                self.dirty_layers.discard(
                    key[0]
                )
                self.dirty_rects.pop(key[0], None)

            return existing

        # ------------------------------------------------------
        # Texture existante mais taille différente
        # ------------------------------------------------------

        if existing is not None:

            try:

                if existing.texture.isCreated():
                    existing.texture.destroy()

            except RuntimeError:
                pass

            del self.textures[key]

        # ------------------------------------------------------
        # Création initiale
        # ------------------------------------------------------

        texture = self._create_texture(
            layer.image
        )

        result = GPUTexture(
            texture=texture,
            cache_key=cache_key,
            width=width,
            height=height,
        )

        self.textures[key] = result
        self.transfer_stats["full_uploads"] += 1
        self.transfer_stats["full_upload_bytes"] += width * height * 4

        self.dirty_layers.discard(
            key[0]
        )
        self.dirty_rects.pop(key[0], None)

        return result

    def sync_tile(self, layer, tx: int, ty: int) -> GPUTexture | None:
        store = getattr(layer, "tile_store", None)
        if not self.initialized or self.blitter is None or store is None or not store.has_tile(tx, ty):
            return None
        key = (id(layer), int(tx), int(ty))
        revision = store.tile_revision(tx, ty)
        existing = self.textures.get(key)
        if existing is not None and existing.revision == revision:
            self.textures.move_to_end(key)
            return existing
        if existing is not None:
            if existing.texture.isCreated():
                existing.texture.destroy()
            del self.textures[key]

        if not store.tile_is_resident(tx, ty):
            store.request_tile_async(tx, ty, self.on_tile_ready)
            return None
        image = store.tile(tx, ty)
        texture = self._create_texture(image)
        result = GPUTexture(
            texture=texture,
            cache_key=revision,
            width=image.width(),
            height=image.height(),
            revision=revision,
        )
        self.textures[key] = result
        self.transfer_stats["full_uploads"] += 1
        self.transfer_stats["full_upload_bytes"] += image.sizeInBytes()
        while len(self.textures) > self.max_cached_tiles:
            old_key, old_texture = self.textures.popitem(last=False)
            if old_texture.texture.isCreated():
                old_texture.texture.destroy()
        return result

    def _draw_tiled_layer(
        self, layer, document, viewport_width, viewport_height, zoom, offset,
        transform_scale_x, transform_scale_y, is_transforming, device_pixel_ratio,
        occluded_tiles: set[tuple[int, int]] | None = None,
    ) -> None:
        store = layer.tile_store
        if not self.initialized or self.blitter is None:
            return
        size = store.tile_size
        if zoom <= 0:
            return
        if is_transforming:
            cx, cy = document.width * 0.5, document.height * 0.5
            sx = transform_scale_x or 1.0
            sy = transform_scale_y or 1.0
            corners = []
            for sx_screen, sy_screen in (
                (0.0, 0.0), (viewport_width, 0.0),
                (0.0, viewport_height), (viewport_width, viewport_height),
            ):
                px = (sx_screen - offset.x()) / zoom
                py = (sy_screen - offset.y()) / zoom
                corners.append((cx + (px - cx) / sx, cy + (py - cy) / sy))
            left = max(0, floor(min(point[0] for point in corners)))
            top = max(0, floor(min(point[1] for point in corners)))
            right = min(document.width, floor(max(point[0] for point in corners)) + 1)
            bottom = min(document.height, floor(max(point[1] for point in corners)) + 1)
        else:
            left = max(0, floor(-offset.x() / zoom))
            top = max(0, floor(-offset.y() / zoom))
            right = min(document.width, floor((viewport_width - offset.x()) / zoom) + 1)
            bottom = min(document.height, floor((viewport_height - offset.y()) / zoom) + 1)
        if right <= left or bottom <= top:
            return

        tx0, ty0 = left // size, top // size
        tx1, ty1 = min(store.columns - 1, (right - 1) // size), min(store.rows - 1, (bottom - 1) // size)
        viewport = QRectF(
            0, 0, viewport_width * device_pixel_ratio,
            viewport_height * device_pixel_ratio,
        ).toRect()
        self.blitter.bind()
        self.blitter.setOpacity(float(layer.opacity))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                if not is_transforming and occluded_tiles and (tx, ty) in occluded_tiles:
                    self.transfer_stats["occluded_tile_draws"] += 1
                    continue
                gpu_tile = self.sync_tile(layer, tx, ty)
                if gpu_tile is None:
                    continue
                doc_rect = store.tile_rect(tx, ty)
                if is_transforming:
                    x = document.width * 0.5 + (doc_rect.x() - document.width * 0.5) * transform_scale_x
                    y = document.height * 0.5 + (doc_rect.y() - document.height * 0.5) * transform_scale_y
                    width = doc_rect.width() * transform_scale_x
                    height = doc_rect.height() * transform_scale_y
                else:
                    x, y = doc_rect.x(), doc_rect.y()
                    width, height = doc_rect.width(), doc_rect.height()
                target = QRectF(
                    (offset.x() + x * zoom) * device_pixel_ratio,
                    (offset.y() + y * zoom) * device_pixel_ratio,
                    width * zoom * device_pixel_ratio,
                    height * zoom * device_pixel_ratio,
                )
                self.blitter.blit(
                    gpu_tile.texture.textureId(),
                    self._blit_transform(target, viewport),
                    QOpenGLTextureBlitter.Origin.OriginTopLeft,
                )
                self.transfer_stats["tile_draw_calls"] += 1
        self.blitter.release()

    # ==========================================================
    # CALQUE
    # ==========================================================

    def draw_layer(
        self,
        layer,
        document,
        viewport_width: float,
        viewport_height: float,
        zoom: float,
        offset,
        transform_scale_x: float = 1.0,
        transform_scale_y: float = 1.0,
        is_transforming: bool = False,
        device_pixel_ratio: float = 1.0,
        occluded_tiles: set[tuple[int, int]] | None = None,
        skip_full_layer: bool = False,
        texture_override_id: int | None = None,
    ) -> None:

        if skip_full_layer and not is_transforming:
            self.transfer_stats["occluded_tile_draws"] += 1
            return

        if getattr(layer, "tile_store", None) is not None and texture_override_id is None:
            self._draw_tiled_layer(
                layer, document, viewport_width, viewport_height, zoom, offset,
                transform_scale_x, transform_scale_y, is_transforming, device_pixel_ratio,
                occluded_tiles,
            )
            return

        if not self.initialized:
            return

        if self.blitter is None:
            return

        if texture_override_id is None:
            gpu_texture = self.sync_layer(layer)
            if gpu_texture is None:
                return
            texture_id = gpu_texture.texture.textureId()
        else:
            texture_id = int(texture_override_id)

        # ------------------------------------------------------
        # Position normale
        # ------------------------------------------------------

        if not is_transforming:

            target_x = offset.x()

            target_y = offset.y()

            target_width = (
                document.width
                * zoom
            )

            target_height = (
                document.height
                * zoom
            )

        # ------------------------------------------------------
        # Transformation
        # ------------------------------------------------------

        else:

            center_x = (
                document.width
                * 0.5
            )

            center_y = (
                document.height
                * 0.5
            )

            scaled_width = (
                document.width
                * transform_scale_x
            )

            scaled_height = (
                document.height
                * transform_scale_y
            )

            target_x = (
                offset.x()
                + (
                    center_x
                    - scaled_width * 0.5
                )
                * zoom
            )

            target_y = (
                offset.y()
                + (
                    center_y
                    - scaled_height * 0.5
                )
                * zoom
            )

            target_width = (
                scaled_width
                * zoom
            )

            target_height = (
                scaled_height
                * zoom
            )

        target = QRectF(
            target_x * device_pixel_ratio,
            target_y * device_pixel_ratio,
            target_width * device_pixel_ratio,
            target_height * device_pixel_ratio,
        )

        viewport = QRectF(
            0.0,
            0.0,
            viewport_width * device_pixel_ratio,
            viewport_height * device_pixel_ratio,
        ).toRect()

        transform = self._blit_transform(target, viewport)

        # ------------------------------------------------------
        # Blit GPU
        # ------------------------------------------------------

        self.blitter.bind()

        self.blitter.setOpacity(
            float(layer.opacity)
        )

        self.blitter.blit(
            texture_id,
            transform,
            # QImage uploads are top-left; an active stroke FBO is rendered
            # in OpenGL's bottom-left coordinate space. Select the origin at
            # the single blit boundary so no upload/readback double-flip is
            # introduced.
            (QOpenGLTextureBlitter.Origin.OriginBottomLeft
             if texture_override_id is not None
             else QOpenGLTextureBlitter.Origin.OriginTopLeft),
        )

        self.blitter.release()

    # ==========================================================
    # NETTOYAGE
    # ==========================================================

    def cleanup(self) -> None:

        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:

            # On ne détruit pas les wrappers ici si le contexte
            # n'est plus courant.
            return

        # ------------------------------------------------------
        # Textures
        # ------------------------------------------------------

        for gpu_texture in list(
            self.textures.values()
        ):

            try:

                if gpu_texture.texture.isCreated():

                    gpu_texture.texture.destroy()

            except RuntimeError:

                pass

        self.textures.clear()

        for buffer in self._pbo_buffers:
            try:
                if buffer.isCreated():
                    buffer.destroy()
            except RuntimeError:
                pass
        self._pbo_buffers.clear()

        self.dirty_layers.clear()
        self.dirty_rects.clear()
        self._opaque_tile_cache.clear()

        # ------------------------------------------------------
        # Blitter
        # ------------------------------------------------------

        if self.blitter is not None:

            try:

                if self.blitter.isCreated():
                    self.blitter.destroy()

            except RuntimeError:

                pass

            self.blitter = None

        self.initialized = False
    def upload_compressed_atlas_region(self, data, rect, fmt) -> bool:
        if not self.atlas_gpu_ready or fmt not in ("BC4", "BC7"):
            return False
        support = self.compressed_texture_support()
        if not support[fmt.lower()]: return False
        if not self._ensure_gl_upload_function(): return False
        lib = self._gl_library
        if not hasattr(lib, "glCompressedTexSubImage2D"):
            try:
                lib.glCompressedTexSubImage2D = getattr(__import__('ctypes').CDLL(__import__('ctypes').util.find_library('GL')), 'glCompressedTexSubImage2D')
            except Exception: return False
        block = 8 if fmt == "BC4" else 16
        w,h=rect.w,rect.h; expected=((w+3)//4)*((h+3)//4)*block
        if len(data)!=expected: return False
        internal = 0x8DBB if fmt == "BC4" else 0x8E8C
        self.atlas_texture.bind()
        try: lib.glCompressedTexSubImage2D(0x0DE1,0,rect.x,rect.y,w,h,internal,len(data),data)
        finally: self.atlas_texture.release()
        return True
