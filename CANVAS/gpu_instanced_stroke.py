"""Instanced OpenGL renderer for simple round brush/eraser strokes.

The active layer is copied to a temporary FBO at stroke start. Dabs are
submitted as per-instance center/size/opacity/rotation records and drawn in
batches. At stroke end only the dirty rectangle is read back into the CPU tile
store, which keeps the existing document and tile-history formats authoritative.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import math
import struct

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage, QOpenGLContext, QPainter
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLPaintDevice,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
    QOpenGLFunctions_3_3_Core,
)


VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec2 aCenter;
layout(location = 1) in vec3 aInstance; // diameter, opacity, rotation radians
uniform vec2 uCanvasSize;
out vec2 vLocal;
out float vOpacity;
void main() {
    const vec2 corners[4] = vec2[4](
        vec2(-1.0, -1.0), vec2(1.0, -1.0),
        vec2(-1.0, 1.0), vec2(1.0, 1.0)
    );
    vec2 corner = corners[gl_VertexID];
    float c = cos(aInstance.z), s = sin(aInstance.z);
    vec2 rotated = vec2(corner.x * c - corner.y * s,
                        corner.x * s + corner.y * c);
    vec2 pixel = aCenter + rotated * (aInstance.x * 0.5);
    gl_Position = vec4(pixel.x / uCanvasSize.x * 2.0 - 1.0,
                       1.0 - pixel.y / uCanvasSize.y * 2.0, 0.0, 1.0);
    vLocal = corner;
    vOpacity = aInstance.y;
}
"""

FRAGMENT_SHADER = """#version 330 core
in vec2 vLocal;
in float vOpacity;
uniform vec4 uColor;
uniform float uHardness;
uniform int uEraser;
out vec4 fragColor;
void main() {
    float radius = length(vLocal);
    float softness = max(0.001, 1.0 - uHardness);
    float coverage = 1.0 - smoothstep(1.0 - softness, 1.0, radius);
    float alpha = clamp(coverage * vOpacity * uColor.a, 0.0, 1.0);
    if (uEraser != 0) {
        fragColor = vec4(0.0, 0.0, 0.0, alpha);
    } else {
        fragColor = vec4(uColor.rgb * alpha, alpha);
    }
}
"""


class GPUInstancedStrokeRenderer:
    MAX_INSTANCES_PER_DRAW = 16384
    MAX_FBO_PIXELS = 16_777_216
    INSTANCE_BYTES = 20  # x, y, diameter, opacity, rotation

    def __init__(self, canvas) -> None:
        self.canvas = canvas
        self.gl = None
        self.program: QOpenGLShaderProgram | None = None
        self.vao: QOpenGLVertexArrayObject | None = None
        self.instance_buffer: QOpenGLBuffer | None = None
        self.fbo: QOpenGLFramebufferObject | None = None
        self.layer = None
        self.settings: dict = {}
        self.base_image: QImage | None = None
        self.instances: list[tuple[float, float, float, float, float]] = []
        self.replay_segments: list[tuple[QPoint, QPoint, float, float]] = []
        self.dirty_rect = QRect()
        self.start_point = QPoint()
        self.start_pressure = 1.0
        self.color = QColor(0, 0, 0, 255)
        self.hardness = 0.8
        self.eraser = False
        self.active = False
        self.pending_finish = False
        self.frame_stats = {"draw_calls": 0, "instances": 0, "readback_bytes": 0}
        self.last_stroke_stats = {}

    @staticmethod
    def supports(settings: dict, tool: str, width: int, height: int,
                 symmetry_horizontal: bool, symmetry_vertical: bool) -> bool:
        if tool not in ("brush", "eraser") or width * height > GPUInstancedStrokeRenderer.MAX_FBO_PIXELS:
            return False
        if symmetry_horizontal or symmetry_vertical:
            return False
        if float(settings.get("roundness", 1.0)) < 0.999:
            return False
        neutral = (
            "scatter", "sizeJitter", "rotationJitter", "velocitySize",
            "velocityOpacity", "velocityFlow", "tiltSize", "tiltOpacity",
            "tiltAngle", "randomSize", "randomOpacity", "pressureSpacing",
            "velocitySpacing", "textureStrength", "textureRandomScale",
            "textureRandomOffset", "textureBrightness", "wetness", "pickup",
            "dilution", "smudge", "hueJitter", "saturationJitter",
            "brightnessJitter", "gradientAmount",
        )
        if any(abs(float(settings.get(key, 0.0))) > 1e-6 for key in neutral):
            return False
        if (settings.get("adaptiveSpacing") or settings.get("strokeGradient")
                or settings.get("dirtyColor") or settings.get("wetMix")
                or settings.get("smudgeTool") or int(settings.get("blendMode", 0)) != 0):
            return False
        return True

    def begin(self, layer, image: QImage, settings: dict, position: QPoint,
              pressure: float, eraser: bool = False) -> bool:
        if self.active or self.base_image is not None or image.isNull():
            return False
        self.layer = layer
        self.base_image = image.copy()
        self.settings = dict(settings)
        self.start_point = QPoint(position)
        self.start_pressure = max(0.0, min(1.0, float(pressure)))
        rgb = settings.get("color", [0, 0, 0, 255])
        self.color = QColor(*(list(rgb)[:4]))
        self.hardness = max(0.0, min(1.0, float(settings.get("hardness", 0.8))))
        self.eraser = bool(eraser)
        self.instances.clear()
        self.replay_segments = []
        self.dirty_rect = self.canvas._brush_dirty_rect(position, position)
        self.frame_stats = {"draw_calls": 0, "instances": 0, "readback_bytes": 0}
        self.pending_finish = False
        self._append_segment(position, position, pressure, pressure, include_replay=False)
        self.active = True
        return True

    def queue_segment(self, start: QPoint, end: QPoint,
                      start_pressure: float, end_pressure: float,
                      dirty_rect: QRect) -> None:
        if not self.active or self.pending_finish:
            return
        self._append_segment(start, end, start_pressure, end_pressure)
        if not dirty_rect.isEmpty():
            self.dirty_rect = QRect(dirty_rect) if self.dirty_rect.isEmpty() else self.dirty_rect.united(dirty_rect)

    def request_finish(self) -> None:
        if self.active:
            self.pending_finish = True

    def texture_for(self, layer) -> int | None:
        if self.active and self.layer is layer and self.fbo is not None and self.fbo.isValid():
            return int(self.fbo.texture())
        return None

    def _effective_size(self, pressure: float) -> float:
        size = max(0.1, float(self.settings.get("size", 10.0)))
        if self.settings.get("pressureSize", True):
            minimum = max(0.0, min(1.0, float(self.settings.get("minimumSize", 0.01))))
            size *= minimum + (1.0 - minimum) * max(0.0, min(1.0, pressure))
        return max(0.1, size)

    def _effective_opacity(self, pressure: float) -> float:
        opacity = max(0.0, min(1.0, float(self.settings.get("opacity", 1.0))))
        flow = max(0.0, min(1.0, float(self.settings.get("flow", 1.0))))
        if self.settings.get("pressureOpacity", False):
            minimum = max(0.0, min(1.0, float(self.settings.get("minimumOpacity", 0.0))))
            opacity *= minimum + (1.0 - minimum) * max(0.0, min(1.0, pressure))
        if self.settings.get("pressureFlow", False):
            minimum = max(0.0, min(1.0, float(self.settings.get("minimumFlow", 0.0))))
            flow *= minimum + (1.0 - minimum) * max(0.0, min(1.0, pressure))
        return opacity * flow

    def _append_segment(self, start: QPoint, end: QPoint,
                        start_pressure: float, end_pressure: float,
                        include_replay: bool = True) -> None:
        if include_replay:
            self.replay_segments.append((QPoint(start), QPoint(end), float(start_pressure), float(end_pressure)))
        dx, dy = end.x() - start.x(), end.y() - start.y()
        distance = math.hypot(dx, dy)
        size0, size1 = self._effective_size(start_pressure), self._effective_size(end_pressure)
        spacing = max(0.001, float(self.settings.get("spacing", 0.15)))
        steps = max(1, math.ceil(distance / max(0.5, (size0 + size1) * 0.5 * spacing)))
        rotation = math.radians(float(self.settings.get("angle", 0.0)))
        for index in range(steps + 1):
            t = index / steps
            pressure = start_pressure + (end_pressure - start_pressure) * t
            self.instances.append((
                start.x() + dx * t,
                start.y() + dy * t,
                size0 + (size1 - size0) * t,
                self._effective_opacity(pressure),
                rotation,
            ))

    def process(self) -> bool:
        """Run queued GL work inside Canvas.paintGL; returns True if a stroke committed."""
        if not self.active or QOpenGLContext.currentContext() is None:
            return False
        try:
            if self.program is None:
                self._initialize_gl()
            if self.fbo is None:
                self._create_fbo()
            if self.instances:
                self._draw_instances()
            if self.pending_finish:
                self._commit_readback()
                self._release_stroke()
                return True
            return False
        except Exception as exc:
            # A GL setup failure replays the queued input through the existing
            # CreativeCore implementation so a partially initialized GPU path
            # never drops the user's stroke.
            self._fallback_to_creative_core(exc)
            return True

    def _initialize_gl(self) -> None:
        self.gl = QOpenGLFunctions_3_3_Core()
        if not self.gl.initializeOpenGLFunctions():
            raise RuntimeError("OpenGL 3.3 functions indisponibles")
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER):
            raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        self.program = program
        self.vao = QOpenGLVertexArrayObject()
        self.instance_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not self.vao.create() or not self.instance_buffer.create():
            raise RuntimeError("Création du buffer d'instances OpenGL impossible")
        self.vao.bind()
        self.instance_buffer.bind()
        self.instance_buffer.allocate(self.INSTANCE_BYTES)
        self.program.bind()
        self.program.enableAttributeArray(0)
        self.program.setAttributeBuffer(0, 0x1406, 0, 2, self.INSTANCE_BYTES)
        self.gl.glVertexAttribDivisor(0, 1)
        self.program.enableAttributeArray(1)
        self.program.setAttributeBuffer(1, 0x1406, 8, 3, self.INSTANCE_BYTES)
        self.gl.glVertexAttribDivisor(1, 1)
        self.program.release()
        self.instance_buffer.release()
        self.vao.release()

    def _create_fbo(self) -> None:
        image = self.base_image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        fmt.setInternalTextureFormat(0x8058)  # GL_RGBA8
        fbo = QOpenGLFramebufferObject(image.size(), fmt)
        if not fbo.isValid() or not fbo.bind():
            raise RuntimeError("Création du FBO de stroke impossible")
        self.gl.glViewport(0, 0, image.width(), image.height())
        self.gl.glDisable(0x0BE2)
        self.gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        self.gl.glClear(0x00004000)
        paint_device = QOpenGLPaintDevice(image.width(), image.height())
        painter = QPainter(paint_device)
        if not painter.isActive():
            fbo.release()
            raise RuntimeError("Initialisation QPainter du FBO impossible")
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(0, 0, image)
        painter.end()
        fbo.bind()
        fbo.release()
        self.fbo = fbo

    def _draw_instances(self) -> None:
        all_instances = self.instances
        self.instances = []
        width, height = self.base_image.width(), self.base_image.height()
        # Isolate all mutable GL state from the main canvas composite.
        viewport = self.gl.glGetIntegerv(0x0BA2)  # GL_VIEWPORT (PySide returns tuple)
        if not hasattr(viewport, "__len__") or len(viewport) != 4:
            viewport = (0, 0, width, height)
        blend_was_enabled = bool(self.gl.glIsEnabled(0x0BE2))
        blend_src_rgb = int(self.gl.glGetIntegerv(0x80C9))
        blend_dst_rgb = int(self.gl.glGetIntegerv(0x80C8))
        blend_src_a = int(self.gl.glGetIntegerv(0x80CB))
        blend_dst_a = int(self.gl.glGetIntegerv(0x80CA))
        self.vao.bind()
        self.program.bind()
        self.program.setUniformValue(self.program.uniformLocation("uCanvasSize"), float(width), float(height))
        self.program.setUniformValue(self.program.uniformLocation("uColor"), self.color)
        self.program.setUniformValue(self.program.uniformLocation("uHardness"), self.hardness)
        self.program.setUniformValue(self.program.uniformLocation("uEraser"), 1 if self.eraser else 0)
        self.fbo.bind()
        self.gl.glViewport(0, 0, width, height)
        self.gl.glEnable(0x0BE2)
        if self.eraser:
            self.gl.glBlendFuncSeparate(0, 0x0303, 0, 0x0303)
        else:
            self.gl.glBlendFuncSeparate(1, 0x0303, 1, 0x0303)
        self.instance_buffer.bind()
        for first in range(0, len(all_instances), self.MAX_INSTANCES_PER_DRAW):
            batch = all_instances[first:first + self.MAX_INSTANCES_PER_DRAW]
            packed = b"".join(struct.pack("<5f", *instance) for instance in batch)
            self.instance_buffer.allocate(packed, len(packed))
            self.gl.glDrawArraysInstanced(0x0005, 0, 4, len(batch))  # GL_TRIANGLE_STRIP
            self.frame_stats["draw_calls"] += 1
            self.frame_stats["instances"] += len(batch)
        self.instance_buffer.release()
        self.program.release()
        self.vao.release()
        self.fbo.release()
        # QOpenGLFramebufferObject::release restores the previous FBO on most
        # backends; explicitly bind the default target to avoid leaking the
        # temporary stroke target into the final layer composite.
        self.gl.glBindFramebuffer(0x8D40, 0)  # GL_FRAMEBUFFER
        self.gl.glViewport(viewport[0], viewport[1], viewport[2], viewport[3])
        if blend_was_enabled:
            self.gl.glEnable(0x0BE2)
        else:
            self.gl.glDisable(0x0BE2)
        self.gl.glBlendFuncSeparate(blend_src_rgb, blend_dst_rgb,
                                    blend_src_a, blend_dst_a)

    def _commit_readback(self) -> None:
        if self.dirty_rect.isEmpty() or self.fbo is None:
            return
        bounds = QRect(0, 0, self.base_image.width(), self.base_image.height())
        rect = self.dirty_rect.intersected(bounds)
        if rect.isEmpty():
            return
        self.fbo.bind()
        raw = (ctypes.c_ubyte * (rect.width() * rect.height() * 4))()
        gl_y = self.base_image.height() - rect.y() - rect.height()
        library = self.canvas.gpu_renderer._gl_library
        if library is None:
            library_name = ctypes.util.find_library("GL")
            if not library_name:
                raise RuntimeError("libGL indisponible pour la lecture du FBO")
            library = ctypes.CDLL(library_name)
            self.canvas.gpu_renderer._gl_library = library
        library.glReadPixels.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
        ]
        library.glReadPixels.restype = None
        library.glReadPixels(rect.x(), gl_y, rect.width(), rect.height(),
                             0x1908, 0x1401, ctypes.c_void_p(ctypes.addressof(raw)))
        self.fbo.release()
        patch = QImage(bytes(raw), rect.width(), rect.height(), rect.width() * 4,
                       QImage.Format.Format_RGBA8888_Premultiplied).mirrored(False, True).copy()
        image = self.layer.image
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(rect.topLeft(), patch)
        painter.end()
        self.layer.commit_image_cache(rect, force=True)
        self.canvas.tile_history.mark_dirty(self.layer, rect)
        self.canvas.gpu_renderer.mark_layer_dirty(self.layer, rect)
        self.frame_stats["readback_bytes"] += patch.sizeInBytes()
        self.last_stroke_stats = dict(self.frame_stats)
        self.canvas.commit_stroke_history()
        self.canvas.canvas_brush_end_stroke()
        self.canvas.update()

    def _fallback_to_creative_core(self, error: Exception) -> None:
        print(f"GPU brush instancié indisponible, reprise CreativeCore : {error}")
        if self.base_image is None:
            self._release_stroke()
            return
        image = self.base_image.copy()
        first = self.start_point
        image = self.canvas._cpp_begin_stroke(image, first, self.start_pressure) or image
        dirty = QRect()
        for start, end, p0, p1 in self.replay_segments:
            image = self.canvas._cpp_draw_segment(image, start, end, p0, p1) or image
            segment_dirty = self.canvas._brush_dirty_rect(start, end)
            dirty = segment_dirty if dirty.isEmpty() else dirty.united(segment_dirty)
        self.canvas._cpp_end_stroke()
        self.layer.adopt_image_cache(image)
        if not dirty.isEmpty():
            self.canvas.sync_gpu_layer(dirty)
            self.canvas.tile_history.mark_dirty(self.layer, dirty)
        self.canvas.commit_stroke_history()
        self.canvas.canvas_brush_end_stroke()
        self._release_stroke()
        self.canvas.update()

    def _release_stroke(self) -> None:
        if self.fbo is not None:
            self.fbo.release()
            self.fbo = None
        if self.instance_buffer is not None:
            self.instance_buffer.destroy()
            self.instance_buffer = None
        if self.vao is not None:
            self.vao.destroy()
            self.vao = None
        if self.program is not None:
            self.program.removeAllShaders()
            self.program = None
        self.layer = None
        self.base_image = None
        self.settings.clear()
        self.instances.clear()
        self.replay_segments.clear()
        self.dirty_rect = QRect()
        self.active = False
        self.pending_finish = False

    def cleanup(self) -> None:
        if QOpenGLContext.currentContext() is not None:
            self._release_stroke()
