from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from collections import OrderedDict
from math import ceil, cos, floor, log2, radians, sin

from PySide6.QtCore import QRect, QRectF

# Mode pixel art : agrandissement au plus proche (pixels nets) pour toutes les
# textures. Liste mutable pour pouvoir le basculer sans réimporter le module.
PIXEL_NEAREST = [False]
from PySide6.QtGui import QImage, QOpenGLContext, QTransform
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLTexture,
)
from CORE.native_bridge import apply_alpha_mask_native, clone_image_native
from .gpu_safe_blitter import SafeTextureBlitter
from .texture_atlas import TextureAtlas


@dataclass
class GPUTexture:
    texture: QOpenGLTexture
    cache_key: int
    width: int
    height: int
    revision: int = -1


class _FrameTileState:
    """État des tuiles d'un calque, lu dans CreativeCore une seule fois par image.

    Pendant une image, rien ne modifie les pixels : un instantané est donc exact.
    Avant, chaque tuile coûtait 3 appels ctypes dans le calcul d'occlusion et 2
    dans la synchronisation GPU, à chaque image, y compris pour les tuiles vides.
    """

    __slots__ = ("store", "resident", "swapped", "_revisions", "signature")

    def __init__(self, store) -> None:
        self.store = store
        # Un seul appel natif renvoie clés ET révisions de toutes les tuiles
        # résidentes (avant : un appel ctypes par tuile et par image).  Bridge
        # ancien ou magasin sans cette méthode : repli sur la lecture tuile à tuile.
        bulk = None
        reader = getattr(store, "resident_revisions", None)
        if callable(reader):
            bulk = reader()
        if bulk is not None:
            self.resident = frozenset(bulk)
            # `signature` (jamais modifié) identifie l'état exact du calque : deux
            # images consécutives avec la même signature n'ont rien à recalculer.
            self.signature: dict[tuple[int, int], int] | None = bulk
            self._revisions: dict[tuple[int, int], int] = dict(bulk)
        else:
            self.resident = frozenset(store.resident_keys())
            self.signature = None
            self._revisions = {}
        self.swapped = getattr(store, "_swapped", None) or {}

    def has_tile(self, key: tuple[int, int]) -> bool:
        # Même définition que TileStore.has_tile : résidente ou déchargée sur disque.
        return key in self.resident or key in self.swapped

    def revision(self, key: tuple[int, int]) -> int:
        revision = self._revisions.get(key)
        if revision is None:
            revision = self._revisions[key] = int(self.store.tile_revision(*key))
        return revision


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
        self.compatibility_report = {
            "presentation": False,
            "desktop_gl_3": False,
            "texture_atlas": False,
            "pbo_upload": False,
            "advanced_compositor": False,
            "reason": "not initialized",
        }

        self.blitter: QOpenGLTextureBlitter | None = None

        self.textures: OrderedDict[tuple[int, int, int], GPUTexture] = OrderedDict()
        # Le budget en octets est la vraie limite (une tuile 64x64 RGBA = 16 Ko : 512 Mo
        # tiennent ~32 000 tuiles).  Le plafond en nombre de tuiles ne sert que de
        # garde-fou : à 1024, un canevas de 2500x3000 (1880 tuiles visibles) dépassait
        # le cache, et un LRU plus petit que l'ensemble affiché évince chaque tuile
        # juste avant sa réutilisation : 100 % d'échecs, 1880 uploads GPU par image.
        self.max_cached_tiles = 65536
        self.max_cached_bytes = 512 * 1024 * 1024
        self.on_tile_ready = None
        self.texture_atlas = TextureAtlas()
        self.atlas_upload_backend = self._atlas_upload_backend
        self.atlas_texture = None
        self.atlas_gpu_ready = False
        self.atlas_texture_id = 0
        self.atlas_width = self.texture_atlas.size
        self.atlas_height = self.texture_atlas.size
        self.atlas_format = QOpenGLTexture.TextureFormat.RGBA8_UNorm

        self.dirty_layers: set[str] = set()
        self.dirty_rects: dict[str, QRect] = {}
        # prune_layers() runs at the top of every paintGL. Its job is to evict
        # cache entries for layers no longer in the document, which only ever
        # happens on add/remove/reorder — not on every dab or pan tick. Without
        # this guard it still did four full scans of potentially tens of
        # thousands of cached-tile entries (self.textures alone can hold up to
        # max_cached_tiles) on every single frame, even while idle.
        self._prune_last_live_keys: frozenset[str] | None = None
        self._opaque_tile_cache: dict[tuple[int, int, int], tuple[int, bool]] = {}
        # calque -> (signature des révisions, colonnes, lignes, tuiles opaques) : tant que
        # le calque ne change pas, l'occlusion ne coûte plus qu'une comparaison de dict.
        self._opaque_set_cache: dict[str, tuple[dict, int, int, frozenset]] = {}
        self._frame_active = False
        self._frame_tiles: dict[int, _FrameTileState] = {}
        # Passe de dessin en cache par calque : (texture, matrice) de chaque tuile.  Tant
        # que ni la vue ni les révisions ne changent, l'image suivante ne fait que
        # rejouer les appels de dessin ; pendant un trait, seules les tuiles dont la
        # révision a changé sont resynchronisées.  `_texture_generation` invalide tout
        # dès qu'une texture est détruite (éviction, nettoyage, calque supprimé).
        self._draw_cache: dict[str, dict] = {}
        self._texture_generation = 0
        self._cached_texture_bytes: int = 0  # running total to avoid O(n) sum on eviction
        self._gl_library = None
        self._pbo_buffers: list[QOpenGLBuffer] = []
        self._pbo_index = 0
        self._mipmaps_dirty: set[int] = set()
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

    @staticmethod
    def _blit_view_transform(
        target: QRectF, viewport: QRect, rotation: float = 0.0,
        flip_x: bool = False, flip_y: bool = False,
        content_rotation: float = 0.0,
        content_center: tuple[float, float] | None = None,
        content_translate: tuple[float, float] = (0.0, 0.0),
    ) -> QTransform:
        """Map a top-left tile through the GPU-only canvas view transform.

        The texture blitter receives an affine transform from texture space to
        clip space.  Keeping this conversion here means pan, zoom, rotation
        and mirror never require a CPU-sized intermediate image.
        """
        if not rotation and not flip_x and not flip_y and not content_rotation and content_translate == (0.0, 0.0):
            return CanvasGPURenderer._blit_transform(target, viewport)
        vw = max(1.0, float(viewport.width()))
        vh = max(1.0, float(viewport.height()))
        angle = radians(float(rotation))
        fx = -1.0 if flip_x else 1.0
        fy = -1.0 if flip_y else 1.0
        # CPU fallback applies the mirror first, then the rotation.
        a, b = cos(angle) * fx, sin(angle) * fx
        c, d = -sin(angle) * fy, cos(angle) * fy
        cx, cy = vw * 0.5, vh * 0.5
        tx = cx - a * cx - c * cy
        ty = cy - b * cx - d * cy
        if content_rotation or content_translate != (0.0, 0.0):
            ccx, ccy = content_center or (vw * 0.5, vh * 0.5)
            content_angle = radians(float(content_rotation))
            e, f = cos(content_angle), sin(content_angle)
            g, h = -sin(content_angle), cos(content_angle)
            ctx = ccx - e * ccx - g * ccy + float(content_translate[0])
            cty = ccy - f * ccx - h * ccy + float(content_translate[1])
            # View matrix after the active-layer preview transform.
            a, b, c, d, tx, ty = (
                a * e + c * f, b * e + d * f,
                a * g + c * h, b * g + d * h,
                a * ctx + c * cty + tx, b * ctx + d * cty + ty,
            )
        x = float(target.x())
        y_bottom = float(target.y() + target.height())
        w = float(target.width())
        h = float(target.height())
        # Texture v=0 is the bottom edge for the blitter's TopLeft origin.
        return QTransform(
            2.0 * a * w / vw, -2.0 * b * w / vh,
            -2.0 * c * h / vw, 2.0 * d * h / vh,
            2.0 * (a * x + c * y_bottom + tx) / vw - 1.0,
            1.0 - 2.0 * (b * x + d * y_bottom + ty) / vh,
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
        rect_x = int(getattr(rect, "x", 0))
        rect_y = int(getattr(rect, "y", 0))
        rect_w = int(getattr(rect, "w", getattr(rect, "width", lambda: 0)()))
        rect_h = int(getattr(rect, "h", getattr(rect, "height", lambda: 0)()))
        patch = source if source.width() == rect_w and source.height() == rect_h else source.copy(rect_x, rect_y, rect_w, rect_h)
        if self._upload_with_pbo(self.atlas_texture, patch, rect_x, rect_y):
            return
        if not self._ensure_gl_upload_function():
            return
        byte_count = patch.sizeInBytes()
        source = (ctypes.c_ubyte * byte_count).from_buffer(patch.bits())
        self.atlas_texture.bind()
        try:
            self._gl_library.glTexSubImage2D(
                0x0DE1, 0, rect_x, rect_y, patch.width(), patch.height(),
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

    def _prepare_texture_for_zoom(self, texture: QOpenGLTexture, zoom: float) -> None:
        """Regenerate the full mip chain only when minification needs it."""
        if isinstance(texture, int):
            texture_id = int(texture)
            texture = next((item.texture for item in self.textures.values()
                            if int(item.texture.textureId()) == texture_id), None)
            if texture is None:
                return
        if not self._mipmaps_dirty:
            return
        texture_id = int(texture.textureId())
        if float(zoom) < 1.0 and texture_id in self._mipmaps_dirty:
            self._generate_mipmaps(texture)
            self._mipmaps_dirty.discard(texture_id)

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
            self._mipmaps_dirty.add(int(texture.textureId()))
        finally:
            texture.release()
        return True

    def begin_frame(self) -> None:
        """Ouvre un instantané d'état de tuiles valable jusqu'à end_frame()."""
        self._frame_active = True
        self._frame_tiles = {}

    def end_frame(self) -> None:
        self._frame_active = False
        self._frame_tiles = {}

    def _frame_tile_state(self, store) -> _FrameTileState | None:
        """Instantané de la trame courante, ou None hors trame (appels directs)."""
        if not self._frame_active or store is None:
            return None
        state = self._frame_tiles.get(id(store))
        if state is None:
            state = self._frame_tiles[id(store)] = _FrameTileState(store)
        return state

    @staticmethod
    def _image_is_fully_opaque(image: QImage) -> bool:
        if image.isNull():
            return False
        if not image.hasAlphaChannel():
            return True
        rgba = image if image.format() == QImage.Format.Format_RGBA8888 else image.convertToFormat(
            QImage.Format.Format_RGBA8888
        )
        raw = memoryview(rgba.constBits()).cast("B")
        alpha = raw[3::4]
        # Comparaison en C : la version « all(value == 255 ... ) » parcourait chaque
        # octet en Python (0,7 ms par tuile de 64 x 64, 8,8 millions d'itérations
        # relevées sur une session de 20 s).
        return alpha.tobytes().count(b"\xff") == len(alpha)

    def _layer_opaque_tiles(self, layer, document_width: int,
                            document_height: int) -> set[tuple[int, int]]:
        """Return fully opaque resident tiles; unknown/swapped tiles stay conservative."""
        store = getattr(layer, "tile_store", None)
        tile_size = getattr(store, "tile_size", 64)
        columns = ceil(document_width / tile_size)
        rows = ceil(document_height / tile_size)
        opaque = set()
        image = None
        layer_id = str(getattr(layer, "id", "__anonymous__"))
        frame = self._frame_tile_state(store)
        signature = frame.signature if frame is not None else None
        if signature is not None:
            hit = self._opaque_set_cache.get(layer_id)
            if hit is not None and hit[1] == columns and hit[2] == rows and hit[0] == signature:
                return hit[3]  # lecture seule : l'appelant ne fait que l'unir à d'autres
        if frame is not None:
            # Seules les tuiles résidentes peuvent être opaques : on ne parcourt
            # plus toute la grille du document, et l'état vient de l'instantané.
            candidates = ((tx, ty) for tx, ty in frame.resident
                          if 0 <= tx < columns and 0 <= ty < rows)
        else:
            candidates = ((tx, ty) for ty in range(rows) for tx in range(columns))
        for tx, ty in candidates:
            key = (layer_id, tx, ty)
            if frame is not None:
                revision = frame.revision((tx, ty))
            elif store is not None:
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
        if signature is not None:
            opaque = frozenset(opaque)
            self._opaque_set_cache[layer_id] = (signature, columns, rows, opaque)
        return opaque

    def compute_occlusion(self, layers, document_width: int,
                          document_height: int) -> dict[object, set[tuple[int, int]]]:
        """Collect tiles covered by eligible opaque layers above each layer."""
        covered: set[tuple[int, int]] = set()
        occluded: dict[int, set[tuple[int, int]]] = {}
        for layer in reversed(layers):
            stable_key = str(getattr(layer, "id", "__anonymous__"))
            covered_for_layer = set(covered)
            occluded[stable_key] = covered_for_layer
            # Keep the historical object-identity lookup available to older
            # integrations while the renderer itself uses stable IDs.
            occluded[id(layer)] = covered_for_layer
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

        # The QtOpenGL binding has crashed on some PySide6/Python runtimes in
        # the shader-compositor and instanced-stroke paths.  Those paths are
        # disabled in Canvas; this renderer only uses the safe tile upload and
        # presentation path below.
        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:

            self.compatibility_report["reason"] = "no current OpenGL context"

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
                self.compatibility_report.update({
                    "desktop_gl_3": False,
                    "reason": "desktop OpenGL 3.0 required",
                })
                print(
                    "GPU indisponible : contexte OpenGL desktop/GLSL 3 requis "
                    f"(obtenu {'OpenGL ES' if context.isOpenGLES() else 'OpenGL'} {version[0]}.{version[1]})"
                )
                return False
        except (AttributeError, TypeError):
            # Keep compatibility with unusual Qt/platform bindings; creation
            # below remains the final capability check.
            pass

        # Do not use QOpenGLTextureBlitter here: its Python 3.14 binding can
        # select an invalid shader path and produce canvas artefacts.
        self.blitter = SafeTextureBlitter()

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

        # A successful presentation backend is a qualified baseline.  It does
        # not certify experimental compute/composite passes: callers can make
        # that distinction instead of presenting every GPU as equivalent.
        self.compatibility_report.update({
            "presentation": True,
            "desktop_gl_3": True,
            "texture_atlas": bool(self.atlas_gpu_ready),
            "pbo_upload": bool(self._pbo_buffers),
            "advanced_compositor": False,
            "reason": "safe tile presentation qualified",
        })

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
        self._mipmaps_dirty.add(int(texture.textureId()))
        return True

    # ==========================================================
    # DIRTY
    # ==========================================================

    def mark_layer_dirty(
        self,
        layer,
        rect: QRect | None = None,
    ) -> None:
        key = str(getattr(layer, "id", "__anonymous__"))
        self.dirty_layers.add(key)
        if rect is not None and not rect.isEmpty():
            previous = self.dirty_rects.get(key)
            value = QRect(rect) if previous is None else previous.united(rect)
            self.dirty_rects[key] = value
            # Compatibility for callers that inspected the old identity-keyed
            # map; all renderer paths continue to use the stable key above.
            self.dirty_rects[id(layer)] = QRect(value)
            # Never access ``layer.image`` here.  That compatibility property
            # materializes the whole tiled document, which turned a small pen
            # dab into a full-canvas CPU copy on every input event.  The atlas
            # is optional and the layer renderer already consumes the dirty
            # tile directly; only upload an atlas patch when an existing cache
            # was explicitly retained by a caller.
            cached_image = getattr(layer, "_image_cache", None)
            if cached_image is not None:
                self.mark_atlas_dirty(QRect(rect), cached_image)
        else:
            # No bounds means the caller may have changed arbitrary pixels.
            self.dirty_rects.pop(key, None)
            self.dirty_rects.pop(id(layer), None)

    def invalidate_layer_draw_cache(self, layer) -> None:
        """Drop _draw_tiled_layer_cached()'s cached tile-draw list for this
        one layer, forcing it to rebuild via sync_tile() on the next frame.

        That cache's only change-detection signal is `frame.signature`, a
        snapshot of layer.tile_store's own tile revisions - it has no way to
        notice that a layer's *mask* changed, since alpha_mask_store is a
        separate TileStore whose revisions never appear in that signature.
        Without this, painting on a mask left the previous frame's (pre-edit)
        texture ids cached and reused verbatim, even after sync_tile() itself
        was made mask-aware. Called alongside mark_layer_dirty() from the
        mask-paint code path only - ordinary raster edits already invalidate
        correctly through frame.signature's own diffing.
        """
        self._draw_cache.pop(str(getattr(layer, "id", "__anonymous__")), None)

    def prune_layers(self, layers) -> None:
        """Release cached textures for layers no longer in the document."""
        if QOpenGLContext.currentContext() is None:
            return
        live_keys = frozenset(str(getattr(layer, "id", "__anonymous__")) for layer in layers)
        if live_keys == self._prune_last_live_keys:
            return
        self._prune_last_live_keys = live_keys
        stale_keys = [key for key in self.textures if key[0] not in live_keys]
        if stale_keys:
            self._texture_generation += 1
        for key in stale_keys:
            gpu_texture = self.textures.pop(key)
            self._cached_texture_bytes -= max(0, gpu_texture.width) * max(0, gpu_texture.height) * 4
            try:
                if gpu_texture.texture.isCreated():
                    gpu_texture.texture.destroy()
            except RuntimeError:
                pass
        for key in [key for key in self._opaque_set_cache if key not in live_keys]:
            del self._opaque_set_cache[key]
        for key in [key for key in self._draw_cache if key not in live_keys]:
            del self._draw_cache[key]
        stale_opacity_keys = [key for key in self._opaque_tile_cache if key[0] not in live_keys]
        for key in stale_opacity_keys:
            self._opaque_tile_cache.pop(key, None)
        self.dirty_layers.intersection_update(live_keys)
        for key in self.dirty_rects.keys() - live_keys:
            self.dirty_rects.pop(key, None)

    # ==========================================================
    # TEXTURE
    # ==========================================================

    def _evict_texture_cache(self) -> None:
        """Evict by LRU while respecting both entry and byte budgets."""
        while (len(self.textures) > self.max_cached_tiles
               or self._cached_texture_bytes > self.max_cached_bytes):
            old_key, old_texture = self.textures.popitem(last=False)
            self._texture_generation += 1
            self._cached_texture_bytes -= max(0, old_texture.width) * max(0, old_texture.height) * 4
            try:
                if old_texture.texture.isCreated():
                    old_texture.texture.destroy()
            except RuntimeError:
                pass

    def _create_texture(
        self,
        image: QImage,
        tiled: bool = False,
    ) -> QOpenGLTexture:

        # Premultiplied alpha prevents linear texture filtering from mixing a
        # colored edge with the black RGB values of transparent neighbors.
        image = image.convertToFormat(
            QImage.Format.Format_RGBA8888_Premultiplied
        )

        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        texture.setSize(image.width(), image.height())
        # Independent mip chains on adjacent canvas tiles can produce a
        # visible one-pixel seam while a stroke is being updated. Tile
        # textures use one level and nearest magnification; the full-layer
        # path keeps the higher-quality mipmapped filtering.
        texture.setMipLevels(1 if tiled else self._mip_levels(image.width(), image.height()))
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
            QOpenGLTexture.Filter.Linear if tiled else QOpenGLTexture.Filter.LinearMipMapLinear
        )

        texture.setMagnificationFilter(
            QOpenGLTexture.Filter.Nearest if (tiled or PIXEL_NEAREST[0]) else QOpenGLTexture.Filter.Linear
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

        key = (str(getattr(layer, "id", "__anonymous__")), -1, -1)
        dirty_key = str(getattr(layer, "id", "__anonymous__"))

        width = layer.image.width()
        height = layer.image.height()

        cache_key = layer.image.cacheKey()

        existing = self.textures.get(
            key
        )

        dirty = dirty_key in self.dirty_layers

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
                dirty_rect = self.dirty_rects.get(dirty_key) if dirty else None
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
                self.textures.move_to_end(key)

                self.dirty_layers.discard(
                    dirty_key
                )
                self.dirty_rects.pop(dirty_key, None)

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

            self._cached_texture_bytes -= max(0, existing.width) * max(0, existing.height) * 4
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
        self.textures.move_to_end(key)
        self._cached_texture_bytes += width * height * 4
        self.transfer_stats["full_uploads"] += 1
        self.transfer_stats["full_upload_bytes"] += width * height * 4
        self._evict_texture_cache()

        self.dirty_layers.discard(dirty_key)
        self.dirty_rects.pop(dirty_key, None)

        return result

    def sync_tile(self, layer, tx: int, ty: int) -> GPUTexture | None:
        store = getattr(layer, "tile_store", None)
        if not self.initialized or self.blitter is None or store is None:
            return None
        frame = self._frame_tile_state(store)
        coordinates = (int(tx), int(ty))
        if frame is not None:
            if not frame.has_tile(coordinates):
                return None
            revision = frame.revision(coordinates)
        else:
            if not store.has_tile(tx, ty):
                return None
            revision = store.tile_revision(tx, ty)

        # This is the GPU texture upload used by the plain per-layer render
        # path: a single "normal" blend-mode layer with no groups is drawn
        # by Canvas._paint_gl_frame's own per-layer loop
        # (gpu_renderer.draw_layer -> _draw_tiled_layer -> sync_tile), never
        # through GPUTileCompositor.compose_tile() or
        # Canvas._ensure_projection() - both of those are reached only for
        # documents with a non-normal blend/clipping/groups (see
        # has_non_normal()). So a plain masked raster layer never touched
        # either of those two mask-aware paths, and this one built its
        # texture straight from the color tile with no knowledge of
        # alpha_mask_store at all. Mirrors _projection_tile_for_layer's own
        # masking (clone, apply via CreativeCore, raise rather than silently
        # draw unmasked). The mask tile's own revision is folded into the
        # cache key below because painting on the mask never touches
        # layer.tile_store, so the color tile's revision alone never changes
        # when a mask stroke is painted.
        mask_store = getattr(layer, "alpha_mask_store", None)
        mask_disabled = getattr(layer, "mask_disabled", False)
        mask_revision = None
        if mask_store is not None and not mask_disabled and mask_store.has_tile(tx, ty):
            if not mask_store.tile_is_resident(tx, ty):
                mask_store.request_tile_async(tx, ty, self.on_tile_ready)
                return None
            mask_revision = mask_store.tile_revision(tx, ty)
        revision = (revision, mask_revision)

        key = (str(getattr(layer, "id", "__anonymous__")), int(tx), int(ty))
        existing = self.textures.get(key)
        if existing is not None and existing.revision == revision:
            self.textures.move_to_end(key)
            return existing
        if existing is not None:
            if existing.texture.isCreated():
                # _evict_texture_cache() and prune_layers() guard their own
                # texture.destroy() calls the same way; this one was the odd
                # one out and could log a "destroy() called without a
                # current context" warning (and, on some drivers, raise) if a
                # tile is synced outside an active GL context.
                try:
                    existing.texture.destroy()
                except RuntimeError:
                    pass
            self._cached_texture_bytes -= max(0, existing.width) * max(0, existing.height) * 4
            del self.textures[key]

        resident = (coordinates in frame.resident) if frame is not None else store.tile_is_resident(tx, ty)
        if not resident:
            store.request_tile_async(tx, ty, self.on_tile_ready)
            return None
        image = store.tile(tx, ty)
        if mask_revision is not None:
            mask = mask_store.tile(tx, ty)
            masked_image = clone_image_native(image)
            if (masked_image is None or mask.size() != masked_image.size()
                    or not apply_alpha_mask_native(masked_image, mask)):
                raise RuntimeError("CreativeCore refused to apply the alpha mask")
            image = masked_image
        texture = self._create_texture(image, tiled=True)
        result = GPUTexture(
            texture=texture,
            cache_key=revision,
            width=image.width(),
            height=image.height(),
            revision=revision,
        )
        self.textures[key] = result
        self.textures.move_to_end(key)
        self._cached_texture_bytes += image.width() * image.height() * 4
        self.transfer_stats["full_uploads"] += 1
        self.transfer_stats["full_upload_bytes"] += image.sizeInBytes()
        self._evict_texture_cache()
        return result

    def _draw_tiled_layer_cached(
        self, layer, store, frame, tile_range, skip_occluded, occluded_tiles,
        zoom, offset_x, offset_y, device_pixel_ratio, vw_px, vh_px,
    ) -> None:
        """Passe simple (sans rotation/miroir/transformation) avec cache de dessin."""
        tx0, ty0, tx1, ty1 = tile_range
        occluded = occluded_tiles if skip_occluded else None
        params = (tx0, ty0, tx1, ty1, float(zoom), float(offset_x), float(offset_y),
                  float(device_pixel_ratio), vw_px, vh_px)
        layer_id = str(getattr(layer, "id", "__anonymous__"))
        signature = frame.signature
        entry = self._draw_cache.get(layer_id)
        generation = self._texture_generation
        usable = (entry is not None and entry["params"] == params
                  and entry["generation"] == generation and entry["complete"]
                  and (entry["occluded"] is occluded or entry["occluded"] == occluded))
        if usable and entry["signature"] is not signature and entry["signature"] != signature:
            old = entry["signature"]
            changed = [key for key in signature.keys() | old.keys()
                       if signature.get(key) != old.get(key)]
            items = entry["items"]
            complete = True
            for key in changed:
                if not (tx0 <= key[0] <= tx1 and ty0 <= key[1] <= ty1):
                    continue
                items.pop(key, None)
                if occluded is not None and key in occluded:
                    continue
                gpu_tile = self.sync_tile(layer, key[0], key[1])
                if gpu_tile is None:
                    complete = complete and not frame.has_tile(key)
                    continue
                items[key] = self._tile_draw_item(store, key, gpu_tile, zoom, offset_x,
                                                  offset_y, device_pixel_ratio, vw_px, vh_px)
            if self._texture_generation != generation:
                usable = False  # une éviction a pu détruire des textures déjà en cache
            else:
                entry["signature"] = signature
                entry["complete"] = complete
        if not usable:
            items = {}
            complete = True
            skipped = 0
            for ty in range(ty0, ty1 + 1):
                for tx in range(tx0, tx1 + 1):
                    key = (tx, ty)
                    if occluded is not None and key in occluded:
                        skipped += 1
                        continue
                    gpu_tile = self.sync_tile(layer, tx, ty)
                    if gpu_tile is None:
                        complete = complete and not frame.has_tile(key)
                        continue
                    items[key] = self._tile_draw_item(store, key, gpu_tile, zoom, offset_x,
                                                      offset_y, device_pixel_ratio, vw_px, vh_px)
            entry = self._draw_cache[layer_id] = {
                "params": params, "generation": self._texture_generation,
                "signature": signature, "occluded": occluded, "items": items,
                "complete": complete, "skipped": skipped,
            }
        self.transfer_stats["occluded_tile_draws"] += entry["skipped"]
        items = entry["items"]
        if not items:
            return
        blitter = self.blitter
        blitter.bind()
        try:
            blitter.setOpacity(float(layer.opacity))
            tiles_pass = getattr(blitter, "draw_tiles", None)
            if tiles_pass is not None:
                tiles_pass(items.values())
            else:
                for item in items.values():
                    blitter.blit_matrix(*item)
        finally:
            blitter.release()
        self.transfer_stats["tile_draw_calls"] += len(items)

    @staticmethod
    def _tile_draw_item(store, key, gpu_tile, zoom, offset_x, offset_y, dpr, vw_px, vh_px):
        doc_rect = store.tile_rect(key[0], key[1])
        left = (offset_x + doc_rect.x() * zoom) * dpr
        top = (offset_y + doc_rect.y() * zoom) * dpr
        tile_w = doc_rect.width() * zoom * dpr
        tile_h = doc_rect.height() * zoom * dpr
        return (gpu_tile.texture.textureId(),
                2.0 * tile_w / vw_px, 2.0 * tile_h / vh_px,
                2.0 * left / vw_px - 1.0,
                1.0 - 2.0 * (top + tile_h) / vh_px)

    def _draw_tiled_layer(
        self, layer, document, viewport_width, viewport_height, zoom, offset,
        transform_scale_x, transform_scale_y, is_transforming, device_pixel_ratio,
        occluded_tiles: set[tuple[int, int]] | None = None,
        view_rotation: float = 0.0, view_flip_x: bool = False, view_flip_y: bool = False,
        transform_rotation: float = 0.0,
        transform_translate_x: float = 0.0, transform_translate_y: float = 0.0,
    ) -> None:
        store = layer.tile_store
        if not self.initialized or self.blitter is None:
            return
        size = store.tile_size
        if zoom <= 0:
            return
        if view_rotation or view_flip_x or view_flip_y or transform_rotation:
            # Transform the viewport corners back into document space.  This
            # keeps the rotated path tiled: large documents do not upload or
            # draw their off-screen tiles merely because the view is rotated.
            angle = radians(float(view_rotation))
            fx = -1.0 if view_flip_x else 1.0
            fy = -1.0 if view_flip_y else 1.0
            a, b = cos(angle) * fx, sin(angle) * fx
            c, d = -sin(angle) * fy, cos(angle) * fy
            vw = viewport_width * device_pixel_ratio
            vh = viewport_height * device_pixel_ratio
            cx, cy = vw * 0.5, vh * 0.5
            zoom_physical = zoom * device_pixel_ratio
            if zoom_physical <= 0:
                return
            corners = []
            for sx_screen, sy_screen in ((0.0, 0.0), (vw, 0.0), (0.0, vh), (vw, vh)):
                dx, dy = sx_screen - cx, sy_screen - cy
                # A is orthonormal: its inverse is its transpose.
                px = cx + a * dx + b * dy
                py = cy + c * dx + d * dy
                corners.append(((px - offset.x() * device_pixel_ratio) / zoom_physical,
                                (py - offset.y() * device_pixel_ratio) / zoom_physical))
            left = max(0, floor(min(point[0] for point in corners)))
            top = max(0, floor(min(point[1] for point in corners)))
            right = min(document.width, floor(max(point[0] for point in corners)) + 1)
            bottom = min(document.height, floor(max(point[1] for point in corners)) + 1)
        elif is_transforming:
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
        # Compute viewport rect once outside the tile loop
        vp_w = viewport_width * device_pixel_ratio
        vp_h = viewport_height * device_pixel_ratio
        viewport = QRect(0, 0, int(vp_w), int(vp_h))
        simple = not (view_rotation or view_flip_x or view_flip_y or is_transforming)
        vw_px = max(1.0, float(viewport.width()))
        vh_px = max(1.0, float(viewport.height()))
        offset_x, offset_y = offset.x(), offset.y()
        skip_occluded = not is_transforming and bool(occluded_tiles)
        if simple:
            frame = self._frame_tile_state(store)
            if frame is not None and frame.signature is not None:
                self._draw_tiled_layer_cached(
                    layer, store, frame, (tx0, ty0, tx1, ty1), skip_occluded,
                    occluded_tiles, zoom, offset_x, offset_y, device_pixel_ratio,
                    vw_px, vh_px)
                return
        # 1) Synchroniser les textures (uploads, création) AVANT de lier le programme :
        #    ces appels touchent à l'état GL, et le blitter garde son programme et son
        #    VAO liés pendant toute la passe de dessin ci-dessous.
        pending = []
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                if skip_occluded and (tx, ty) in occluded_tiles:
                    self.transfer_stats["occluded_tile_draws"] += 1
                    continue
                gpu_tile = self.sync_tile(layer, tx, ty)
                if gpu_tile is not None:
                    pending.append((tx, ty, gpu_tile))
        if not pending:
            return
        # 2) Dessin.  Cas courant (ni rotation, ni miroir, ni transformation) : la
        #    matrice est calculée en flottants, sans QRectF/QTransform par tuile.
        needs_mips = float(zoom) < 1.0 and bool(self._mipmaps_dirty)
        blitter = self.blitter
        blitter.bind()
        try:
            blitter.setOpacity(float(layer.opacity))
            for tx, ty, gpu_tile in pending:
                doc_rect = store.tile_rect(tx, ty)
                if needs_mips:
                    self._prepare_texture_for_zoom(gpu_tile.texture, zoom)
                if simple:
                    left = (offset_x + doc_rect.x() * zoom) * device_pixel_ratio
                    top = (offset_y + doc_rect.y() * zoom) * device_pixel_ratio
                    tile_w = doc_rect.width() * zoom * device_pixel_ratio
                    tile_h = doc_rect.height() * zoom * device_pixel_ratio
                    blitter.blit_matrix(
                        gpu_tile.texture.textureId(),
                        2.0 * tile_w / vw_px, 2.0 * tile_h / vh_px,
                        2.0 * left / vw_px - 1.0,
                        1.0 - 2.0 * (top + tile_h) / vh_px,
                    )
                else:
                    if is_transforming:
                        x = document.width * 0.5 + (doc_rect.x() - document.width * 0.5) * transform_scale_x
                        y = document.height * 0.5 + (doc_rect.y() - document.height * 0.5) * transform_scale_y
                        width = doc_rect.width() * transform_scale_x
                        height = doc_rect.height() * transform_scale_y
                    else:
                        x, y = doc_rect.x(), doc_rect.y()
                        width, height = doc_rect.width(), doc_rect.height()
                    target = QRectF(
                        (offset_x + x * zoom) * device_pixel_ratio,
                        (offset_y + y * zoom) * device_pixel_ratio,
                        width * zoom * device_pixel_ratio,
                        height * zoom * device_pixel_ratio,
                    )
                    blitter.blit(
                        gpu_tile.texture.textureId(),
                        self._blit_view_transform(
                            target, viewport, view_rotation, view_flip_x, view_flip_y,
                            transform_rotation if is_transforming else 0.0,
                            ((offset_x + document.width * 0.5 * zoom) * device_pixel_ratio,
                             (offset_y + document.height * 0.5 * zoom) * device_pixel_ratio),
                            ((transform_translate_x if is_transforming else 0.0) * zoom * device_pixel_ratio,
                             (transform_translate_y if is_transforming else 0.0) * zoom * device_pixel_ratio),
                        ),
                        "top_left",
                    )
        finally:
            blitter.release()
        self.transfer_stats["tile_draw_calls"] += len(pending)

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
        view_rotation: float = 0.0,
        view_flip_x: bool = False,
        view_flip_y: bool = False,
        transform_rotation: float = 0.0,
        transform_translate_x: float = 0.0,
        transform_translate_y: float = 0.0,
    ) -> None:

        if skip_full_layer and not is_transforming:
            self.transfer_stats["occluded_tile_draws"] += 1
            return

        if getattr(layer, "tile_store", None) is not None and texture_override_id is None:
            self._draw_tiled_layer(
                layer, document, viewport_width, viewport_height, zoom, offset,
                transform_scale_x, transform_scale_y, is_transforming, device_pixel_ratio,
                occluded_tiles, view_rotation, view_flip_x, view_flip_y,
                transform_rotation, transform_translate_x, transform_translate_y,
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

        transform = self._blit_view_transform(
            target, viewport, view_rotation, view_flip_x, view_flip_y,
            transform_rotation,
            ((offset.x() + document.width * 0.5 * zoom) * device_pixel_ratio,
             (offset.y() + document.height * 0.5 * zoom) * device_pixel_ratio),
            (transform_translate_x * zoom * device_pixel_ratio,
             transform_translate_y * zoom * device_pixel_ratio),
        )

        # ------------------------------------------------------
        # Blit GPU
        # ------------------------------------------------------

        self.blitter.bind()

        self.blitter.setOpacity(
            float(layer.opacity)
        )

        self._prepare_texture_for_zoom(texture_id, zoom)
        self.blitter.blit(
            texture_id,
            transform,
            # QImage uploads are top-left; an active stroke FBO is rendered
            # in OpenGL's bottom-left coordinate space. Select the origin at
            # the single blit boundary so no upload/readback double-flip is
            # introduced.
            ("bottom_left" if texture_override_id is not None else "top_left"),
        )

        self.blitter.release()

    def draw_texture_tile(
        self, texture_id: int, tile_rect: QRect, viewport_width: float,
        viewport_height: float, zoom: float, offset, device_pixel_ratio: float = 1.0,
        view_rotation: float = 0.0, view_flip_x: bool = False, view_flip_y: bool = False,
    ) -> None:
        """Present a compositor-owned tile texture without CPU readback."""
        if not self.initialized or self.blitter is None or not texture_id:
            return
        target = QRectF(
            (offset.x() + tile_rect.x() * zoom) * device_pixel_ratio,
            (offset.y() + tile_rect.y() * zoom) * device_pixel_ratio,
            tile_rect.width() * zoom * device_pixel_ratio,
            tile_rect.height() * zoom * device_pixel_ratio,
        )
        viewport = QRectF(0, 0, viewport_width * device_pixel_ratio,
                          viewport_height * device_pixel_ratio).toRect()
        self.blitter.bind()
        self.blitter.setOpacity(1.0)
        # The caller passes a texture id here; tiled and full-layer paths both
        # defer mip generation until minification actually needs it.
        self._prepare_texture_for_zoom(texture_id, zoom)
        self.blitter.blit(
            int(texture_id),
            self._blit_view_transform(target, viewport, view_rotation, view_flip_x, view_flip_y),
            "bottom_left",
        )
        self.blitter.release()
        self.transfer_stats["tile_draw_calls"] += 1

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
        self._texture_generation += 1
        self._draw_cache.clear()

        for buffer in self._pbo_buffers:
            try:
                if buffer.isCreated():
                    buffer.destroy()
            except RuntimeError:
                pass

        self._pbo_buffers = []
        if self.atlas_texture is not None:
            try:
                if self.atlas_texture.isCreated():
                    self.atlas_texture.destroy()
            except RuntimeError:
                pass
            self.atlas_texture = None
            self.atlas_texture_id = 0
            self.atlas_gpu_ready = False
        self._pbo_buffers.clear()

        self.dirty_layers.clear()
        self.dirty_rects.clear()
        self._opaque_tile_cache.clear()
        self._opaque_set_cache.clear()

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
