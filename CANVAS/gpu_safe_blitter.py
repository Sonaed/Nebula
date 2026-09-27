"""Small OpenGL 3.3 texture blitter independent from Qt's broken wrapper."""
from __future__ import annotations

import ctypes
import ctypes.util
import struct

from PySide6.QtGui import QOpenGLContext, QTransform
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                              QOpenGLVertexArrayObject)

VERTEX = """#version 330 core
layout(location=0) in vec2 aPosition;
uniform vec4 uMatrix; uniform vec2 uTranslate; uniform vec4 uRect; uniform int uUseRect;
out vec2 vUv;
void main(){ if(uUseRect!=0){ gl_Position=vec4(uRect.x*aPosition.x+uRect.z, uRect.y*aPosition.y+uRect.w,0.,1.); vUv=aPosition; return; } gl_Position=vec4(uMatrix.x*aPosition.x+uMatrix.y*aPosition.y+uTranslate.x, uMatrix.z*aPosition.x+uMatrix.w*aPosition.y+uTranslate.y,0.,1.); vUv=aPosition; }
"""
FRAGMENT = """#version 330 core
in vec2 vUv; uniform sampler2D uTexture; uniform float uOpacity; uniform int uFlipY; out vec4 fragColor;
void main(){ vec2 uv=vec2(vUv.x, uFlipY != 0 ? 1.-vUv.y : vUv.y); fragColor=texture(uTexture,uv)*uOpacity; }
"""


class SafeTextureBlitter:
    """Subset of QOpenGLTextureBlitter used by CanvasGPURenderer."""
    def __init__(self) -> None:
        self.gl = None; self.program = None; self.vao = None; self.buffer = None
        self.opacity = 1.0
        self._loc = None; self._bound = False; self._flip = None

    def create(self) -> bool:
        try:
            # Do not use QOpenGLFunctions_3_3_Core here.  With the current
            # PySide6/Python 3.14 combination, merely constructing that
            # wrapper can crash the interpreter inside Shiboken before an
            # exception can be raised.  libGL calls are ABI-stable and are
            # also what the texture uploader uses in gpu_renderer.py.
            library_name = ctypes.util.find_library("GL")
            if not library_name:
                return False
            self.gl = ctypes.CDLL(library_name)
            self.gl.glActiveTexture.argtypes = [ctypes.c_uint]
            self.gl.glBindTexture.argtypes = [ctypes.c_uint, ctypes.c_uint]
            self.gl.glUniform1i.argtypes = [ctypes.c_int, ctypes.c_int]
            self.gl.glUniform1f.argtypes = [ctypes.c_int, ctypes.c_float]
            self.gl.glUniform4f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
            self.gl.glUniform2f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float]
            self.gl.glDrawArrays.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
            program = QOpenGLShaderProgram()
            if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX): return False
            if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT): return False
            if not program.link(): return False
            vao = QOpenGLVertexArrayObject(); buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not vao.create() or not buffer.create(): return False
            vao.bind(); buffer.bind()
            buffer.allocate(struct.pack("<8f", 0,0, 1,0, 0,1, 1,1), 32)
            program.bind(); program.enableAttributeArray(0); program.setAttributeBuffer(0, 0x1406, 0, 2, 8)
            program.release(); buffer.release(); vao.release()
            self.program, self.vao, self.buffer = program, vao, buffer
            return True
        except Exception:
            self.destroy(); return False

    # Une passe de dessin (une couche) fait bind() -> N x blit_matrix()/blit() -> release().
    # Programme, VAO, unité de texture, opacité et sens vertical ne sont réglés
    # qu'une fois par passe ; avant, chaque tuile refaisait tout cela, avec six
    # recherches d'emplacement d'uniform (uniformLocation) par tuile.
    def _locations(self) -> None:
        if self._loc is None:
            program = self.program
            self._loc = {name: program.uniformLocation(name) for name in
                         ("uTexture", "uOpacity", "uFlipY", "uMatrix", "uTranslate", "uRect", "uUseRect")}

    def bind(self) -> None:
        if self._bound or not self.program or not self.vao or not self.gl:
            return
        self._locations()
        self.vao.bind(); self.program.bind()
        self.gl.glActiveTexture(0x84C0)
        self.gl.glUniform1i(self._loc["uTexture"], 0)
        self.gl.glUniform1f(self._loc["uOpacity"], self.opacity)
        self._flip = None
        self._bound = True

    def release(self) -> None:
        if not self._bound:
            return
        self.program.release(); self.vao.release()
        self._bound = False

    def setOpacity(self, opacity: float) -> None:
        opacity = float(opacity)
        if opacity != self.opacity and self._bound:
            self.gl.glUniform1f(self._loc["uOpacity"], opacity)
        self.opacity = opacity

    def _set_flip(self, flip: int) -> None:
        if flip != self._flip:
            self.gl.glUniform1i(self._loc["uFlipY"], flip)
            self._flip = flip

    def _draw(self, texture_id: int, m11: float, m21: float, m12: float, m22: float,
              dx: float, dy: float, flip: int) -> None:
        loc, gl = self._loc, self.gl
        # L'unité active est ré-imposée : la création/mise à jour d'une texture
        # (Qt, PBO) peut avoir laissé une autre unité active.
        gl.glActiveTexture(0x84C0)
        gl.glBindTexture(0x0DE1, int(texture_id))
        self._set_flip(flip)
        gl.glUniform4f(loc["uMatrix"], m11, m21, m12, m22)
        gl.glUniform2f(loc["uTranslate"], dx, dy)
        gl.glDrawArrays(0x0005, 0, 4)

    def draw_tiles(self, items) -> None:
        """Rejoue une liste de tuiles simples (texture, sx, sy, tx, ty).

        Trois appels GL par tuile (texture, rectangle, dessin) au lieu de cinq : unité
        de texture, sens vertical et mode « rectangle » ne sont réglés qu'une fois.
        """
        if not self.program or not self.vao or not self.gl:
            return
        temporary = not self._bound
        if temporary:
            self.bind()
        gl, loc = self.gl, self._loc
        gl.glActiveTexture(0x84C0)
        self._set_flip(1)
        gl.glUniform1i(loc["uUseRect"], 1)
        rect_location = loc["uRect"]
        bind_texture, set_rect, draw = gl.glBindTexture, gl.glUniform4f, gl.glDrawArrays
        try:
            for texture_id, scale_x, scale_y, translate_x, translate_y in items:
                bind_texture(0x0DE1, texture_id)
                set_rect(rect_location, scale_x, scale_y, translate_x, translate_y)
                draw(0x0005, 0, 4)
        finally:
            gl.glUniform1i(loc["uUseRect"], 0)
            if temporary:
                self.release()

    def blit_matrix(self, texture_id: int, scale_x: float, scale_y: float,
                    translate_x: float, translate_y: float) -> None:
        """Tuile sans rotation ni miroir, origine haut-gauche (cas courant du canevas)."""
        if not self.program or not self.vao or not self.gl:
            return
        temporary = not self._bound
        if temporary:
            self.bind()
        self._draw(texture_id, scale_x, 0.0, 0.0, scale_y, translate_x, translate_y, 1)
        if temporary:
            self.release()

    def blit(self, texture_id: int, transform: QTransform, origin) -> None:
        if not self.program or not self.vao or not self.gl: return
        # QOpenGLTextureBlitter.OriginTopLeft is enum value 0 in Qt; use its name
        # when available to avoid depending on binding enum integer details.
        flip = 1 if str(origin).lower() in {"top_left", "topleft"} else 0
        temporary = not self._bound
        if temporary:
            self.bind()
        self._draw(texture_id, transform.m11(), transform.m21(), transform.m12(),
                   transform.m22(), transform.dx(), transform.dy(), flip)
        if temporary:
            self.release()

    def isCreated(self) -> bool: return self.program is not None
    def destroy(self) -> None:
        if self.buffer is not None: self.buffer.destroy()
        if self.vao is not None: self.vao.destroy()
        if self.program is not None: self.program.removeAllShaders()
        self._loc = None; self._bound = False; self._flip = None
        self.buffer = self.vao = self.program = self.gl = None
