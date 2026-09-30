"""GPU compositor for visible document tiles.

CreativeCore stays authoritative: this class never writes document pixels and
is deliberately bypassed for parameterised blend modes and adjustment layers.
Editable raster masks are sampled directly in the shader: CreativeCore stays
authoritative and supplies the exact same per-pixel alpha coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import ctypes
import ctypes.util
import os

from PySide6.QtCore import QSize
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
    QOpenGLShader, QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)


VERTEX_SHADER = """#version 330 core
out vec2 vUv;
void main() {
    const vec2 p[3] = vec2[3](vec2(-1.,-1.), vec2(3.,-1.), vec2(-1.,3.));
    vec2 xy = p[gl_VertexID];
    gl_Position = vec4(xy, 0., 1.);
    vUv = xy * .5 + .5;
}
"""

# The formula mirrors CPP_CORE/src/projection_compositor.cpp for the standard
# modes. Inputs and output are premultiplied textures; blend math is performed
# in straight colour and premultiplied only at the final write.
FRAGMENT_SHADER = """#version 330 core
in vec2 vUv;
uniform sampler2D uBackdrop;
uniform sampler2D uSource;
uniform sampler2D uMask;
uniform sampler2D uClip;
uniform int uMode;
uniform float uOpacity;
uniform int uUseMask;
uniform int uUseClip;
uniform int uPreserveAlpha;
uniform int uAlphaOnly;
uniform int uSourceFlipY;
out vec4 fragColor;
vec3 straight(vec4 p) { return p.a > 1e-6 ? p.rgb / p.a : vec3(0.); }
vec3 blend(vec3 b, vec3 s) {
  if (uMode == 1) return min(b,s);
  if (uMode == 2) return b*s;
  if (uMode == 3) return min(vec3(1.), max(vec3(0.), 1. - (1.-b)/max(s,vec3(1e-8))));
  if (uMode == 4) return max(b,s);
  if (uMode == 5) return 1. - (1.-b)*(1.-s);
  if (uMode == 6) return min(vec3(1.), max(vec3(0.), b/max(1.-s,vec3(1e-8))));
  if (uMode == 7) return mix(2.*b*s, 1.-2.*(1.-b)*(1.-s), step(vec3(.5),b));
  if (uMode == 8) { vec3 d=mix(((16.*b-12.)*b+4.)*b, sqrt(clamp(b,0.,1.)), step(vec3(.25),b)); return mix(b-(1.-2.*s)*b*(1.-b), b+(2.*s-1.)*(d-b), step(vec3(.5),s)); }
  if (uMode == 9) return mix(2.*b*s, 1.-2.*(1.-b)*(1.-s), step(vec3(.5),s));
  if (uMode == 10) return abs(b-s);
  if (uMode == 11) return b+s-2.*b*s;
  return s;
}
void main() {
  // QOpenGLTexture uploads originate from QImage (top-left), whereas the FBO
  // is sampled bottom-left. Flip only the uploaded source, never the FBO.
  vec4 back = texture(uBackdrop, vUv);
  vec4 src = texture(uSource, uSourceFlipY != 0 ? vec2(vUv.x, 1.-vUv.y) : vUv);
  // Mask tiles use the same top-left QImage orientation as layer tiles.
  float maskAlpha = uUseMask != 0 ? texture(uMask, vec2(vUv.x, 1.-vUv.y)).a : 1.;
  float sa = clamp(src.a * maskAlpha * uOpacity, 0., 1.);
  if (uUseClip != 0) sa *= texture(uClip, vUv).a;
  if (uAlphaOnly != 0) { fragColor = vec4(0., 0., 0., sa); return; }
  float ba = back.a;
  vec3 b = straight(back), s = straight(src);
  vec3 mixed = blend(b, s);
  float oa = uPreserveAlpha != 0 ? ba : sa + ba*(1.-sa);
  vec3 premul = s*sa*(1.-ba) + mixed*(sa*ba) + b*ba*(1.-sa);
  fragColor = vec4(premul, oa);
}
"""


class NativeGL:
    """OpenGL calls used by the compositor, without PySide's unsafe wrapper."""

    def __init__(self) -> None:
        name = ctypes.util.find_library("GL")
        if not name:
            raise RuntimeError("libGL indisponible")
        self.library = ctypes.CDLL(name)
        signatures = {
            "glViewport": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], None),
            "glDisable": ([ctypes.c_uint], None),
            "glClearColor": ([ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float], None),
            "glClear": ([ctypes.c_uint], None),
            "glBindVertexArray": ([ctypes.c_uint], None),
            "glActiveTexture": ([ctypes.c_uint], None),
            "glBindTexture": ([ctypes.c_uint, ctypes.c_uint], None),
            "glUniform1i": ([ctypes.c_int, ctypes.c_int], None),
            "glUniform1f": ([ctypes.c_int, ctypes.c_float], None),
            "glDrawArrays": ([ctypes.c_uint, ctypes.c_int, ctypes.c_int], None),
            "glGetError": ([], ctypes.c_uint),
        }
        for symbol, (arguments, result) in signatures.items():
            function = getattr(self.library, symbol)
            function.argtypes = arguments
            function.restype = result
            setattr(self, symbol, function)


@dataclass
class CompositeTile:
    first: QOpenGLFramebufferObject
    second: QOpenGLFramebufferObject
    clip: QOpenGLFramebufferObject
    revision: tuple
    result_first: bool

    @property
    def texture_id(self) -> int:
        return int((self.first if self.result_first else self.second).texture())


class GPUTileCompositor:
    """Ping-pong FBO compositor with a bounded visible-tile cache."""

    SUPPORTED_MODES = frozenset(range(12))
    MAX_TILE_CACHE = 256  # evict LRU tiles beyond this count

    def __init__(self, renderer) -> None:
        self.renderer = renderer
        self.gl = None
        self.program: QOpenGLShaderProgram | None = None
        self.vao: QOpenGLVertexArrayObject | None = None
        self.vao_id = 0
        self.tiles: dict[tuple[int, int], CompositeTile] = {}
        # One persistent ping-pong target per active group depth.  Reusing
        # these FBOs avoids allocating/releasing nested temporaries during a
        # paint; that lifetime pattern was the source of driver instability on
        # some Wayland stacks.
        self._group_targets: list[CompositeTile] = []
        self.frame_stats = {"composite_passes": 0, "composite_tiles": 0, "composite_fallbacks": 0}
        self.last_error = ""
        # Cached uniform locations (populated after _initialize)
        self._uloc: dict[str, int] = {}
        # supports() cache: keyed on a cheap document signature
        self._supports_cache: tuple | None = None  # (signature, result)

    @staticmethod
    def _supports_signature(document) -> tuple:
        """Cheap fingerprint of the document structure that affects compositing."""
        layers = tuple(
            (str(getattr(l, "id", id(l))), bool(l.visible),
             str(getattr(l, "blend_mode", "normal")), float(getattr(l, "opacity", 1.0)),
             bool(getattr(l, "blend_parameters", None)), str(getattr(l, "layer_kind", "raster")),
             bool(getattr(l, "clipping", False)))
            for l in document.layers
        )
        groups = tuple(
            (str(g.id), tuple(g.layer_ids), str(g.parent_id), bool(g.visible),
             str(g.blend_mode), float(g.opacity), bool(getattr(g, "blend_parameters", None)))
            for g in getattr(document, "layer_groups", ())
        )
        return layers, groups

    def supports_cached(self, document) -> bool:
        """Like supports() but caches the result until the document structure changes."""
        sig = self._supports_signature(document)
        if self._supports_cache is not None and self._supports_cache[0] == sig:
            return self._supports_cache[1]
        result = self.supports(document)
        self._supports_cache = (sig, result)
        return result

    @staticmethod
    def supports(document) -> bool:
        # Group isolation is implemented with persistent FBOs below, but it
        # stays opt-in until it has passed the hardware qualification suite on
        # the running driver.  The CPU/native projection remains pixel-exact
        # and is never a visual fallback from a half-validated GPU path.
        if (getattr(document, "layer_groups", None)
                and os.getenv("CREATIVESYSTEM_EXPERIMENTAL_GPU_GROUPS") != "1"):
            return False
        def supported_mode(value) -> bool:
            try:
                from DOCUMENTS.blend_modes import BLEND_MODES
                return BLEND_MODES.index(str(value).lower()) in GPUTileCompositor.SUPPORTED_MODES
            except (ValueError, AttributeError):
                return False
        for layer in document.layers:
            if not layer.visible:
                continue
            # Clipping sets follow Photoshop's isolated "atop" rule, which only
            # the CPU/native projection (DOCUMENTS.blend_modes.resolve_stack)
            # implements.
            if bool(getattr(layer, "clipping", False)):
                return False
            if (getattr(layer, "blend_parameters", None)
                    or getattr(layer, "layer_kind", "raster") != "raster"
                    or not supported_mode(getattr(layer, "blend_mode", "normal"))):
                return False
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
        groups = {group.id: group for group in getattr(document, "layer_groups", ())}
        root_coverage: set[int] = set()
        for group in groups.values():
            members = [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]
            if (not members or members != list(range(min(members), max(members) + 1))
                    or getattr(group, "blend_parameters", None)
                    or not supported_mode(getattr(group, "blend_mode", "normal"))):
                return False
            if group.parent_id is not None:
                parent = groups.get(group.parent_id)
                parent_members = set(positions[layer_id] for layer_id in getattr(parent, "layer_ids", ())
                                     if layer_id in positions) if parent is not None else set()
                if not parent or not set(members).issubset(parent_members):
                    return False
            elif root_coverage.intersection(members):
                return False
            elif group.parent_id is None:
                root_coverage.update(members)
        return True

    def _initialize(self) -> None:
        if self.program is not None:
            return
        if QOpenGLContext.currentContext() is None:
            raise RuntimeError("no current OpenGL context")
        self.gl = NativeGL()
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER):
            raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("GPU composite VAO unavailable")
        self.program = program
        self.vao = vao
        self.vao_id = int(vao.objectId())
        # Cache all uniform locations once — avoids per-draw string lookups
        self._uloc = {name: program.uniformLocation(name)
                      for name in ("uBackdrop", "uSource", "uMask", "uClip",
                                   "uMode", "uOpacity", "uUseMask", "uUseClip",
                                   "uPreserveAlpha", "uAlphaOnly", "uSourceFlipY")}

    @staticmethod
    def _new_fbo(size: QSize) -> QOpenGLFramebufferObject:
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        fmt.setInternalTextureFormat(0x8058)  # GL_RGBA8
        fbo = QOpenGLFramebufferObject(size, fmt)
        if not fbo.isValid():
            raise RuntimeError("GPU composite FBO unavailable")
        return fbo

    def _clear(self, fbo: QOpenGLFramebufferObject) -> None:
        fbo.bind()
        self.gl.glViewport(0, 0, fbo.width(), fbo.height())
        self.gl.glDisable(0x0BE2)  # GL_BLEND
        self.gl.glClearColor(0., 0., 0., 0.)
        self.gl.glClear(0x00004000)  # GL_COLOR_BUFFER_BIT
        fbo.release()

    def _static_signature(self, document) -> tuple:
        """Frame-constant parts of _revision(): id, blend mode, opacity,
        clipping and every group's metadata don't vary by tile, only each
        layer's two tile-revision numbers do. compose_tile() is called once
        per VISIBLE tile every frame, so without this split these `str()`/
        `getattr()` chains over every visible layer and every group were
        redone once per tile - the same "recompute what didn't change" cost
        as the CPU projection signature (see canvas.py's
        _layer_static_signature/_groups_static_signature)."""
        layers = tuple(
            (layer, (str(getattr(layer, "id", id(layer))),
                    str(getattr(layer, "blend_mode", "normal")),
                    float(getattr(layer, "opacity", 1.0)),
                    bool(getattr(layer, "clipping", False))))
            for layer in document.layers if layer.visible
        )
        groups = tuple((str(group.id), tuple(group.layer_ids), str(group.parent_id), bool(group.visible),
                        str(group.blend_mode), float(group.opacity))
                       for group in getattr(document, "layer_groups", ()))
        return layers, groups

    def _revision(self, document, tx: int, ty: int, static: tuple | None = None) -> tuple:
        if static is None:
            static = self._static_signature(document)
        static_layers, groups = static
        layers = tuple(
            (meta, layer.tile_store.tile_revision(tx, ty) if layer.tile_store.has_tile(tx, ty) else -1,
             getattr(getattr(layer, "alpha_mask_store", None), "tile_revision", lambda *_: -1)(tx, ty)
             if getattr(getattr(layer, "alpha_mask_store", None), "has_tile", lambda *_: False)(tx, ty) else -1)
            for layer, meta in static_layers
        )
        return layers, groups

    def _clear_tile(self, target: CompositeTile) -> None:
        self._clear(target.first); self._clear(target.second); self._clear(target.clip)

    def _group_target(self, depth: int, size: QSize) -> CompositeTile:
        """Return a persistent isolated target for one group nesting level."""
        while len(self._group_targets) <= depth:
            self._group_targets.append(CompositeTile(
                self._new_fbo(size), self._new_fbo(size), self._new_fbo(size), (), True))
        target = self._group_targets[depth]
        if target.first.size() != size:
            for fbo in (target.first, target.second, target.clip):
                fbo.release()
            target = CompositeTile(self._new_fbo(size), self._new_fbo(size),
                                   self._new_fbo(size), (), True)
            self._group_targets[depth] = target
        self._clear_tile(target)
        return target

    def _group_entries(self, document, tx: int, ty: int, size: QSize):
        """Build isolated FBO entries for contiguous nested raster groups."""
        groups = {group.id: group for group in document.layer_groups}
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
        children = {group_id: [] for group_id in groups}
        roots = []
        for group in groups.values():
            if group.parent_id is None:
                roots.append(group)
            else:
                children[group.parent_id].append(group)

        def members(group):
            return [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]

        def render_group(group, depth: int):
            owned = members(group)
            child_groups = sorted(children[group.id], key=lambda child: min(members(child)))
            child_at = {min(members(child)): child for child in child_groups}
            child_positions = {position for child in child_groups for position in members(child)}
            entries = []
            index = min(owned)
            while index <= max(owned):
                child = child_at.get(index)
                if child is not None:
                    entries.append(render_group(child, depth + 1))
                    index = max(members(child)) + 1
                elif index not in child_positions:
                    entries.append(document.layers[index])
                    index += 1
                else:
                    index += 1
            target = self._group_target(depth, size)
            self._draw_stack(entries, target, tx, ty)
            return SimpleNamespace(
                id=f"gpu-group:{group.id}", visible=group.visible,
                opacity=group.opacity, blend_mode=group.blend_mode,
                blend_parameters={}, clipping=False,
                _gpu_texture=target.texture_id,
            )

        roots_at = {min(members(group)): group for group in roots}
        root_coverage = {position for group in roots for position in members(group)}
        entries = []
        index = 0
        while index < len(document.layers):
            group = roots_at.get(index)
            if group is not None:
                entries.append(render_group(group, 0))
                index = max(members(group)) + 1
            elif index not in root_coverage:
                entries.append(document.layers[index])
                index += 1
            else:
                index += 1
        return entries

    def _draw_stack(self, entries, target: CompositeTile, tx: int, ty: int) -> None:
        """Composite the supported raster layer stack."""
        current, alternate = target.first, target.second
        from DOCUMENTS.blend_modes import BLEND_MODES
        for layer in entries:
            if not getattr(layer, "visible", True):
                continue
            source_id = int(getattr(layer, "_gpu_texture", 0))
            source_flip = 0 if source_id else 1
            if not source_id:
                if not layer.tile_store.has_tile(tx, ty):
                    continue
                source = self.renderer.sync_tile(layer, tx, ty)
                if source is None:
                    raise RuntimeError("GPU source tile unavailable")
                source_id = int(source.texture.textureId())
            mask_texture = None
            mask_store = getattr(layer, "alpha_mask_store", None)
            if mask_store is not None and mask_store.has_tile(tx, ty):
                mask_layer = SimpleNamespace(id=f"{layer.id}:alpha-mask", tile_store=mask_store)
                mask_texture = self.renderer.sync_tile(mask_layer, tx, ty)
                if mask_texture is None:
                    raise RuntimeError("GPU mask tile unavailable")
            mode = BLEND_MODES.index(str(getattr(layer, "blend_mode", "normal")).lower())
            if not alternate.bind():
                raise RuntimeError("GPU composite FBO bind failed")
            self.gl.glViewport(0, 0, alternate.width(), alternate.height())
            self.gl.glDisable(0x0BE2); self.gl.glDisable(0x0B71); self.gl.glDisable(0x0B44)
            for unit, texture in ((0x84C0, int(current.texture())), (0x84C1, source_id),
                                  (0x84C2, int(mask_texture.texture.textureId()) if mask_texture else source_id),
                                  (0x84C3, int(target.clip.texture()))):
                self.gl.glActiveTexture(unit); self.gl.glBindTexture(0x0DE1, texture)
            clipping = bool(getattr(layer, "clipping", False))
            ul = self._uloc
            self.gl.glUniform1i(ul["uMode"], mode)
            self.gl.glUniform1f(ul["uOpacity"], float(getattr(layer, "opacity", 1.0)))
            self.gl.glUniform1i(ul["uUseMask"], 1 if mask_texture else 0)
            self.gl.glUniform1i(ul["uUseClip"], 1 if clipping else 0)
            self.gl.glUniform1i(ul["uPreserveAlpha"], 1 if clipping else 0)
            self.gl.glUniform1i(ul["uAlphaOnly"], 0)
            self.gl.glUniform1i(ul["uSourceFlipY"], source_flip)
            while self.gl.glGetError(): pass
            self.gl.glDrawArrays(0x0004, 0, 3)
            if (error := int(self.gl.glGetError())):
                raise RuntimeError(f"GPU composite GL error 0x{error:04x}")
            alternate.release(); current, alternate = alternate, current
            self.frame_stats["composite_passes"] += 1
            if not clipping:
                if not target.clip.bind():
                    raise RuntimeError("GPU clip FBO bind failed")
                self.gl.glViewport(0, 0, target.clip.width(), target.clip.height())
                self.gl.glUniform1i(ul["uUseClip"], 0)
                self.gl.glUniform1i(ul["uPreserveAlpha"], 0)
                self.gl.glUniform1i(ul["uAlphaOnly"], 1)
                self.gl.glUniform1i(ul["uSourceFlipY"], source_flip)
                self.gl.glDrawArrays(0x0004, 0, 3)
                if (error := int(self.gl.glGetError())):
                    raise RuntimeError(f"GPU clip alpha GL error 0x{error:04x}")
                target.clip.release(); self.frame_stats["composite_passes"] += 1
        target.result_first = current is target.first

    def compose_tile(self, document, tx: int, ty: int, static: tuple | None = None,
                     supports: bool | None = None) -> int | None:
        """Return a premultiplied composited tile texture, or None for fallback.

        `static` and `supports`, when supplied by a caller composing several
        tiles from the same document in one frame, are `_static_signature(document)`
        and `supports_cached(document)` computed once up front rather than
        re-derived here on every tile - `supports_cached` still has to rebuild
        `_supports_signature(document)` (another full pass over every layer
        and group) to know whether its cached boolean is still valid, so
        calling it once per tile paid that cost once per tile instead of once
        per frame, on top of the `_static_signature` duplication already
        fixed above.
        """
        if supports is None:
            supports = self.supports_cached(document)
        if not supports:
            self.frame_stats["composite_fallbacks"] += 1; return None
        try:
            self._initialize(); revision = self._revision(document, tx, ty, static)
            cached = self.tiles.get((tx, ty))
            if cached is not None and cached.revision == revision:
                # Refresh LRU order so later misses cannot evict a texture
                # already queued for drawing in the current viewport.
                self.tiles.pop((tx, ty))
                self.tiles[(tx, ty)] = cached
                return cached.texture_id
            tile_size = next((layer.tile_store.tile_size for layer in document.layers if layer.visible), 0)
            if tile_size <= 0: return None
            if cached is None:
                cached = CompositeTile(self._new_fbo(QSize(tile_size, tile_size)), self._new_fbo(QSize(tile_size, tile_size)), self._new_fbo(QSize(tile_size, tile_size)), revision, True); self.tiles[(tx, ty)] = cached
            self._clear_tile(cached)
            if not self.vao_id: raise RuntimeError("GPU composite VAO unavailable")
            self.gl.glBindVertexArray(self.vao_id); self.program.bind()
            # Sampler slot bindings only need to be set once per program activation
            ul = self._uloc
            for name, slot in (("uBackdrop", 0), ("uSource", 1), ("uMask", 2), ("uClip", 3)):
                self.gl.glUniform1i(ul[name], slot)
            entries = (self._group_entries(document, tx, ty, QSize(tile_size, tile_size))
                       if document.layer_groups else document.layers)
            self._draw_stack(entries, cached, tx, ty)
            self.program.release(); self.gl.glBindVertexArray(0)
            cached.revision = revision; self.frame_stats["composite_tiles"] += 1
            # Evict oldest tiles when cache grows too large
            while len(self.tiles) > self.MAX_TILE_CACHE:
                old_key = next(iter(self.tiles))
                old_tile = self.tiles.pop(old_key)
                for fbo in (old_tile.first, old_tile.second, old_tile.clip):
                    try:
                        fbo.release()
                    except Exception:
                        pass
            return cached.texture_id
        except Exception as error:
            self.last_error = str(error); self.frame_stats["composite_fallbacks"] += 1; return None

    def cleanup(self) -> None:
        self.tiles.clear()
        self._group_targets.clear()
        if self.program is not None:
            self.program.removeAllShaders()
        self.program = None
        if self.vao is not None:
            self.vao.destroy()
        self.vao = None
        self.vao_id = 0
        self.gl = None
        self._uloc = {}
        self._supports_cache = None
