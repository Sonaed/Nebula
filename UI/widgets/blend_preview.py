from __future__ import annotations

from array import array

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QColor, QImage, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QOpenGLTextureBlitter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from shiboken6 import delete as delete_qobject
from DOCUMENTS.blend_presets import BLEND_PARAMS


PREVIEW_SIZE = 256

_MODE_ID = {
    "normal": 0, "darken": 1, "multiply": 2, "color_burn": 3,
    "lighten": 4, "screen": 5, "color_dodge": 6, "overlay": 7,
    "soft_light": 8, "hard_light": 9, "difference": 10,
    "exclusion": 11, "hue": 12, "saturation": 13,
    "color": 14, "luminosity": 15,
}

_VERTEX_SHADER = """#version 330 core
in vec2 position;
in vec2 texCoord;
out vec2 uv;
void main() { uv = texCoord; gl_Position = vec4(position, 0.0, 1.0); }
"""

_FRAGMENT_SHADER = """#version 330 core
in vec2 uv;
out vec4 fragColor;
uniform sampler2D backdropTex;
uniform sampler2D sourceTex;
uniform float opacity;
uniform float intensity;
uniform float opposite_mix;
uniform float gamma_value;
uniform float mix_normal;
uniform float pivot;
uniform float clamp_value;
uniform float softness;
uniform float hue_shift;
uniform float saturation_boost;
uniform float offset_value;
vec3 rgb2hsl(vec3 c) {
    float hi=max(max(c.r,c.g),c.b), lo=min(min(c.r,c.g),c.b), d=hi-lo;
    float h=0.0, s=0.0, l=(hi+lo)*0.5;
    if (d>0.00001) {
        s=d/(1.0-abs(2.0*l-1.0));
        if (hi==c.r) h=mod((c.g-c.b)/d,6.0);
        else if (hi==c.g) h=(c.b-c.r)/d+2.0;
        else h=(c.r-c.g)/d+4.0;
        h=mod(h/6.0+1.0,1.0);
    }
    return vec3(h,s,l);
}
vec3 hsl2rgb(vec3 hsl) {
    float c=(1.0-abs(2.0*hsl.z-1.0))*hsl.y;
    float x=c*(1.0-abs(mod(hsl.x*6.0,2.0)-1.0));
    float m=hsl.z-c*0.5;
    vec3 v;
    if (hsl.x<1.0/6.0) v=vec3(c,x,0.0);
    else if (hsl.x<2.0/6.0) v=vec3(x,c,0.0);
    else if (hsl.x<3.0/6.0) v=vec3(0.0,c,x);
    else if (hsl.x<4.0/6.0) v=vec3(0.0,x,c);
    else if (hsl.x<5.0/6.0) v=vec3(x,0.0,c);
    else v=vec3(c,0.0,x);
    return v+m;
}
vec3 blend(vec3 b, vec3 s) {
    if (MODE_ID==1) return min(b,s);
    if (MODE_ID==2) return pow(max(b*s,vec3(0.0)),vec3(1.0/max(gamma_value,0.01)));
    if (MODE_ID==3) return 1.0-min(vec3(1.0),(1.0-b)/max(s,vec3(0.0001)));
    if (MODE_ID==4) return max(b,s);
    if (MODE_ID==5) return 1.0-(1.0-b)*(1.0-s);
    if (MODE_ID==6) return min(vec3(clamp_value<1.0 ? 1.0 : 16.0),b/max(1.0-s,vec3(0.0001)));
    if (MODE_ID==7 || MODE_ID==9) {
        vec3 lo=2.0*b*s, hi=1.0-2.0*(1.0-b)*(1.0-s);
        float t=MODE_ID==7 ? step(vec3(pivot),b).r : step(vec3(pivot),s).r;
        return mix(lo,hi,vec3(t));
    }
    if (MODE_ID==8) {
        vec3 soft=((1.0-2.0*s)*b*b+2.0*s*b);
        return mix(soft, mix(b, s, b), softness);
    }
    if (MODE_ID==10) return abs(b-s-offset_value);
    if (MODE_ID==11) return b+s-2.0*b*s;
    vec3 hb=rgb2hsl(b), hs=rgb2hsl(s);
    hs.x=fract(hs.x+hue_shift/360.0);
    hs.y=clamp(hs.y*saturation_boost,0.0,1.0);
    if (MODE_ID==12) return hsl2rgb(vec3(hs.x,hb.y,hb.z));
    if (MODE_ID==13) return hsl2rgb(vec3(hb.x,hs.y,hb.z));
    if (MODE_ID==14) return hsl2rgb(vec3(hs.x,hs.y,hb.z));
    if (MODE_ID==15) return hsl2rgb(vec3(hb.x,hb.y,hs.z));
    return s;
}
void main() {
    vec4 b=texture(backdropTex,uv), s=texture(sourceTex,uv);
    float a=clamp(s.a*opacity,0.0,1.0);
    vec3 effect=mix(s.rgb,blend(b.rgb,s.rgb),clamp(intensity,0.0,1.0));
    // Opposite blend is represented by a complementary preview mix where defined.
    vec3 opposite=1.0-blend(1.0-b.rgb,1.0-s.rgb);
    effect=mix(effect,opposite,clamp(opposite_mix,0.0,1.0));
    effect=mix(effect,s.rgb,clamp(mix_normal,0.0,1.0));
    fragColor=vec4(mix(b.rgb,effect,a),a+b.a*(1.0-a));
}
"""

_PARAMETER_DEFAULTS = {
    "opacity": 1.0, "intensity": 1.0, "opposite_mix": 0.0,
    "gamma": 1.0, "mix_normal": 0.0, "pivot": 0.5,
    "clamp": 1.0, "softness": 0.5, "hue_shift": 0.0,
    "saturation_boost": 1.0, "offset": 0.0,
}


class BlendPreviewWidget(QOpenGLWidget):
    """Small live blend preview; shader compilation is tied to mode changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.setMinimumSize(128, 128)
        self.mode = "normal"
        self.parameters: dict[str, float] = {}
        self.program: QOpenGLShaderProgram | None = None
        self._programs: dict[str, QOpenGLShaderProgram] = {}
        self.vertex_buffer: QOpenGLBuffer | None = None
        self.fbo: QOpenGLFramebufferObject | None = None
        self.blitter: QOpenGLTextureBlitter | None = None
        self.backdrop_texture: QOpenGLTexture | None = None
        self.source_texture: QOpenGLTexture | None = None
        self._images_dirty = True
        self._dirty_uniforms: set[str] = set()
        self.backdrop_image = self._sample_image(QImage(), QColorValue.BACKDROP)
        self.source_image = self._sample_image(QImage(), QColorValue.SOURCE)
        self._draw_timer = QTimer(self)
        self._draw_timer.setSingleShot(True)
        self._draw_timer.setInterval(16)
        self._draw_timer.timeout.connect(self._request_preview_update)
        self.shader_compile_count = 0
        self.fbo_creation_count = 0
        self.frame_request_count = 0
        self.preview_render_count = 0
        self.uniform_upload_count = 0
        self._connected_gl_context: QOpenGLContext | None = None
        self._gl_cleanup_in_progress = False

    @staticmethod
    def _sample_image(image: QImage, fallback) -> QImage:
        if image.isNull():
            image = QImage(PREVIEW_SIZE, PREVIEW_SIZE, QImage.Format.Format_RGBA8888)
            image.fill(QColor(*fallback))
        else:
            image = image.scaled(PREVIEW_SIZE, PREVIEW_SIZE)
        return image.convertToFormat(QImage.Format.Format_RGBA8888)

    def set_images(self, backdrop: QImage, source: QImage) -> None:
        self.backdrop_image = self._sample_image(backdrop, QColorValue.BACKDROP)
        self.source_image = self._sample_image(source, QColorValue.SOURCE)
        self._images_dirty = True
        self._schedule_preview()

    def set_mode(self, mode: str) -> None:
        mode = mode if mode in _MODE_ID else "normal"
        if self.mode == mode and self.program is not None:
            return
        self.mode = mode
        self._compile_selected_mode()
        self._schedule_preview()

    def set_parameter(self, key: str, value: float) -> None:
        self.parameters[key] = float(value)
        if self._uniform_for_key(key) is not None:
            self._dirty_uniforms.add(key)
        self._schedule_preview()

    def _uniform_for_key(self, key: str) -> str | None:
        return next(
            (item["uniform"] for item in BLEND_PARAMS.get(self.mode, ()) if item["key"] == key),
            None,
        )

    def _schedule_preview(self) -> None:
        # Coalesce rapid input to at most one frame per interval. Restarting
        # an active single-shot timer would starve live preview during a drag.
        if not self._draw_timer.isActive():
            self._draw_timer.start()

    def _request_preview_update(self) -> None:
        self.frame_request_count += 1
        self.update()

    def set_parameters(self, mode: str, values: dict) -> None:
        self.set_mode(mode)
        for key, value in values.items():
            self.set_parameter(key, value)

    def _compile_selected_mode(self) -> None:
        if not self.isValid():
            self.program = None
            return
        # initializeGL() is entered with this widget's context already
        # current. Do not call doneCurrent() in that case: Qt owns the
        # current-context lifetime for the duration of the callback.
        context_already_current = QOpenGLContext.currentContext() == self.context()
        if not context_already_current:
            self.makeCurrent()
        try:
            cached = self._programs.get(self.mode)
            if cached is not None:
                self.program = cached
                cached.bind()
                self._update_all_uniforms()
                cached.release()
                return
            program = QOpenGLShaderProgram(self)
            source = f"#version 330 core\n#define MODE_ID {_MODE_ID[self.mode]}\n" + _FRAGMENT_SHADER.split("\n",1)[1]
            if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX_SHADER):
                self.program = None
                return
            if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, source):
                self.program = None
                return
            program.bindAttributeLocation("position", 0)
            program.bindAttributeLocation("texCoord", 1)
            if not program.link():
                self.program = None
                return
            self.program = program
            self._programs[self.mode] = program
            self.shader_compile_count += 1
            program.bind()
            self._update_all_uniforms()
            program.release()
        finally:
            if not context_already_current:
                self.doneCurrent()

    def _update_all_uniforms(self) -> None:
        if self.program is None:
            return
        for name, unit in (("backdropTex", 0), ("sourceTex", 1)):
            location = self.program.uniformLocation(name)
            if location >= 0:
                self.program.setUniformValue1i(location, unit)
        for key in _PARAMETER_DEFAULTS:
            value = float(self.parameters.get(key, _PARAMETER_DEFAULTS[key]))
            uniform = self._uniform_for_key(key)
            if uniform is None:
                continue
            location = self.program.uniformLocation(uniform)
            if location >= 0:
                self.program.setUniformValue1f(location, value)

    def initializeGL(self) -> None:
        context = QOpenGLContext.currentContext()
        if context is None:
            return
        if context != self._connected_gl_context:
            previous = self._connected_gl_context
            if previous is not None:
                try:
                    previous.aboutToBeDestroyed.disconnect(self.cleanup_gl_resources)
                except (RuntimeError, TypeError):
                    pass
            context.aboutToBeDestroyed.connect(self.cleanup_gl_resources)
            self._connected_gl_context = context

        self.fbo = QOpenGLFramebufferObject(PREVIEW_SIZE, PREVIEW_SIZE)
        self.fbo_creation_count += 1
        self.blitter = QOpenGLTextureBlitter()
        if not self.blitter.create():
            self.blitter = None
        self.vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vertex_buffer.create()
        self.vertex_buffer.bind()
        vertices = array("f", (-1,-1, 0,0, 1,-1, 1,0, -1,1, 0,1, 1,1, 1,1)).tobytes()
        self.vertex_buffer.allocate(vertices, len(vertices))
        self.vertex_buffer.release()
        self._upload_images()
        self._compile_selected_mode()

    def cleanup_gl_resources(self) -> None:
        """Release context-owned preview objects before Qt recreates its GL context."""
        if self._gl_cleanup_in_progress:
            return
        context = self._connected_gl_context or self.context()
        if context is None:
            return

        self._gl_cleanup_in_progress = True
        made_current = QOpenGLContext.currentContext() != context
        try:
            if made_current:
                self.makeCurrent()
            if QOpenGLContext.currentContext() != context:
                return

            for texture in (self.backdrop_texture, self.source_texture):
                if texture is not None and texture.isCreated():
                    texture.destroy()
            self.backdrop_texture = None
            self.source_texture = None

            if self.vertex_buffer is not None:
                if self.vertex_buffer.isCreated():
                    self.vertex_buffer.destroy()
                self.vertex_buffer = None

            if self.fbo is not None:
                self.fbo.release()
                self.fbo = None

            if self.blitter is not None:
                if self.blitter.isCreated():
                    self.blitter.destroy()
                self.blitter = None

            for program in self._programs.values():
                delete_qobject(program)
            self._programs.clear()
            self.program = None
            self._dirty_uniforms.clear()
            self._images_dirty = True
        except RuntimeError as error:
            print(f"Blend preview OpenGL cleanup : {error}")
        finally:
            if made_current and QOpenGLContext.currentContext() == context:
                self.doneCurrent()
            self._gl_cleanup_in_progress = False

    def _upload_images(self) -> None:
        for texture in (self.backdrop_texture, self.source_texture):
            if texture is not None and texture.isCreated():
                texture.destroy()
        self.backdrop_texture = QOpenGLTexture(self.backdrop_image)
        self.source_texture = QOpenGLTexture(self.source_image)
        for texture in (self.backdrop_texture, self.source_texture):
            texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        self._images_dirty = False

    def paintGL(self) -> None:
        if self._draw_timer.isActive():
            # A spontaneous Qt paint can satisfy a pending preview request.
            self._draw_timer.stop()
        if (self.fbo is None or self.program is None or self.vertex_buffer is None
                or self.blitter is None):
            return
        if self._images_dirty or self.backdrop_texture is None or self.source_texture is None:
            self._upload_images()
        if not self.fbo.bind():
            return
        functions = self.context().functions()
        functions.glViewport(0, 0, PREVIEW_SIZE, PREVIEW_SIZE)
        functions.glDisable(0x0BE2)  # GL_BLEND: shader outputs the final pixel.
        functions.glClear(0x00004000)
        self.program.bind()
        for key in tuple(self._dirty_uniforms):
            uniform = self._uniform_for_key(key)
            location = self.program.uniformLocation(uniform) if uniform else -1
            if location >= 0:
                self.program.setUniformValue1f(location, float(self.parameters[key]))
                self.uniform_upload_count += 1
        self._dirty_uniforms.clear()
        self.backdrop_texture.bind(0)
        self.source_texture.bind(1)
        self.vertex_buffer.bind()
        self.program.enableAttributeArray(0)
        self.program.enableAttributeArray(1)
        self.program.setAttributeBuffer(0, 0x1406, 0, 2, 4 * 4)
        self.program.setAttributeBuffer(1, 0x1406, 2 * 4, 2, 4 * 4)
        functions.glDrawArrays(0x0005, 0, 4)
        self.program.disableAttributeArray(0)
        self.program.disableAttributeArray(1)
        self.vertex_buffer.release()
        self.program.release()
        self.source_texture.release()
        self.backdrop_texture.release()
        self.fbo.release()
        self.preview_render_count += 1
        functions.glBindFramebuffer(0x8D40, self.defaultFramebufferObject())
        ratio = self.devicePixelRatioF()
        target = QRectF(0, 0, self.width() * ratio, self.height() * ratio)
        functions.glViewport(0, 0, round(target.width()), round(target.height()))
        self.blitter.bind()
        self.blitter.setOpacity(1.0)
        self.blitter.blit(
            self.fbo.texture(),
            QOpenGLTextureBlitter.targetTransform(target, target.toRect()),
            QOpenGLTextureBlitter.Origin.OriginBottomLeft,
        )
        self.blitter.release()

    def resizeGL(self, _width: int, _height: int) -> None:
        # The FBO stays fixed at PREVIEW_SIZE; widget resizes allocate nothing.
        pass


class QColorValue:
    BACKDROP = (70, 95, 125, 255)
    SOURCE = (200, 80, 110, 210)
