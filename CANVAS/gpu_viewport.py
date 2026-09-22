from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtOpenGL import QOpenGLTexture, QOpenGLTextureBlitter
from PySide6.QtOpenGLWidgets import QOpenGLWidget


class GPUViewport(QOpenGLWidget):
    """
    Viewport 2D GPU indépendant.

    L'image reste une QImage côté CPU.
    L'affichage et le zoom sont effectués par OpenGL.
    """

    def __init__(self, image: QImage | None = None) -> None:
        super().__init__()

        self.setUpdateBehavior(
            QOpenGLWidget.UpdateBehavior.PartialUpdate
        )

        self.image = (
            image.copy()
            if image is not None
            else QImage()
        )

        self.texture: QOpenGLTexture | None = None
        self.blitter: QOpenGLTextureBlitter | None = None

        self.gpu_ready = False

        self.zoom = 1.0
        self.min_zoom = 0.05
        self.max_zoom = 20.0

        self.offset = QPointF(
            0.0,
            0.0
        )

        self.panning = False
        self.pan_start = QPointF()
        self.offset_start = QPointF()

        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus
        )

    # ==========================================================
    # OPENGL
    # ==========================================================

    def initializeGL(self) -> None:

        self.blitter = QOpenGLTextureBlitter()

        if not self.blitter.create():
            print(
                "ERREUR : QOpenGLTextureBlitter.create() a échoué."
            )
            self.blitter = None
            return

        self._upload_texture()

        self.gpu_ready = True

        print("✓ GPUViewport OpenGL initialisé")

    def resizeGL(
        self,
        width: int,
        height: int,
    ) -> None:

        self.update()

    def paintGL(self) -> None:

        from PySide6.QtGui import QOpenGLContext

        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:
            return

        gl = context.functions()

        # GL_COLOR_BUFFER_BIT
        gl.glClearColor(
            0.07,
            0.07,
            0.07,
            1.0,
        )

        gl.glClear(
            0x00004000
        )

        if (
            not self.gpu_ready
            or self.texture is None
            or self.blitter is None
            or not self.texture.isCreated()
        ):
            return

        width = (
            self.image.width()
            * self.zoom
        )

        height = (
            self.image.height()
            * self.zoom
        )

        target = QRectF(
            self.offset.x(),
            self.offset.y(),
            width,
            height,
        )

        viewport = QRectF(
            0.0,
            0.0,
            float(self.width()),
            float(self.height()),
        )

        transform = (
            QOpenGLTextureBlitter.targetTransform(
                target,
                viewport.toRect(),
            )
        )

        gl.glEnable(
            0x0BE2
        )

        # GL_SRC_ALPHA / GL_ONE_MINUS_SRC_ALPHA
        gl.glBlendFunc(
            0x0302,
            0x0303,
        )

        self.blitter.bind()

        self.blitter.setOpacity(
            1.0
        )

        self.blitter.blit(
            self.texture.textureId(),
            transform,
            QOpenGLTextureBlitter.Origin.OriginTopLeft,
        )

        self.blitter.release()

        gl.glDisable(
            0x0BE2
        )

    # ==========================================================
    # TEXTURE GPU
    # ==========================================================

    def _upload_texture(self) -> None:

        if self.image.isNull():
            return

        if self.blitter is None:
            return

        from PySide6.QtGui import QOpenGLContext

        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:
            return

        # ------------------------------------------------------
        # Première création
        # ------------------------------------------------------

        if self.texture is None:

            image = self.image.convertToFormat(
                QImage.Format.Format_RGBA8888
            )

            self.texture = QOpenGLTexture(
                image,
                QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps,
            )

            self.texture.setMinificationFilter(
                QOpenGLTexture.Filter.Linear
            )

            self.texture.setMagnificationFilter(
                QOpenGLTexture.Filter.Linear
            )

            self.texture.setWrapMode(
                QOpenGLTexture.CoordinateDirection.DirectionS,
                QOpenGLTexture.WrapMode.ClampToEdge,
            )

            self.texture.setWrapMode(
                QOpenGLTexture.CoordinateDirection.DirectionT,
                QOpenGLTexture.WrapMode.ClampToEdge,
            )

            print(
                "✓ Texture GPU créée :",
                image.width(),
                "x",
                image.height(),
            )

            return

        # ------------------------------------------------------
        # Changement de taille :
        # nouvelle texture
        # ------------------------------------------------------

        if (
            self.texture.width()
            != self.image.width()
            or self.texture.height()
            != self.image.height()
        ):

            self.texture.destroy()

            image = self.image.convertToFormat(
                QImage.Format.Format_RGBA8888
            )

            self.texture = QOpenGLTexture(
                image,
                QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps,
            )

            self.texture.setMinificationFilter(
                QOpenGLTexture.Filter.Linear
            )

            self.texture.setMagnificationFilter(
                QOpenGLTexture.Filter.Linear
            )

            self.texture.setWrapMode(
                QOpenGLTexture.CoordinateDirection.DirectionS,
                QOpenGLTexture.WrapMode.ClampToEdge,
            )

            self.texture.setWrapMode(
                QOpenGLTexture.CoordinateDirection.DirectionT,
                QOpenGLTexture.WrapMode.ClampToEdge,
            )

            return

        # ------------------------------------------------------
        # Même taille :
        # upload des pixels uniquement
        # ------------------------------------------------------

        image = self.image.convertToFormat(
            QImage.Format.Format_RGBA8888
        )

        self.texture.bind()

        self.texture.setData(
            QOpenGLTexture.PixelFormat.RGBA,
            QOpenGLTexture.PixelType.UInt8,
            image.constBits(),
        )

        self.texture.release()

    # ==========================================================
    # API
    # ==========================================================

    def set_image(
        self,
        image: QImage,
    ) -> None:

        self.image = image.copy()

        if (
            self.gpu_ready
            and self.context() is not None
        ):

            self.makeCurrent()

            try:
                self._upload_texture()
            finally:
                self.doneCurrent()

        self.update()

    def fit_image(self) -> None:

        if self.image.isNull():
            return

        if (
            self.image.width() <= 0
            or self.image.height() <= 0
        ):
            return

        scale_x = (
            self.width()
            / self.image.width()
        )

        scale_y = (
            self.height()
            / self.image.height()
        )

        self.zoom = min(
            scale_x,
            scale_y,
        ) * 0.90

        self.zoom = max(
            self.min_zoom,
            min(
                self.zoom,
                self.max_zoom,
            ),
        )

        self.offset = QPointF(
            (
                self.width()
                - self.image.width()
                * self.zoom
            ) * 0.5,
            (
                self.height()
                - self.image.height()
                * self.zoom
            ) * 0.5,
        )

        self.update()

    # ==========================================================
    # SOURIS
    # ==========================================================

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:

        if (
            event.button()
            == Qt.MouseButton.MiddleButton
        ):

            self.panning = True

            self.pan_start = (
                event.position()
            )

            self.offset_start = (
                self.offset
            )

            self.setCursor(
                Qt.CursorShape.ClosedHandCursor
            )

            event.accept()

            return

        super().mousePressEvent(
            event
        )

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:

        if self.panning:

            delta = (
                event.position()
                - self.pan_start
            )

            self.offset = (
                self.offset_start
                + delta
            )

            self.update()

            event.accept()

            return

        super().mouseMoveEvent(
            event
        )

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:

        if (
            event.button()
            == Qt.MouseButton.MiddleButton
        ):

            self.panning = False

            self.setCursor(
                Qt.CursorShape.ArrowCursor
            )

            event.accept()

            return

        super().mouseReleaseEvent(
            event
        )

    # ==========================================================
    # ZOOM
    # ==========================================================

    def wheelEvent(
        self,
        event: QWheelEvent,
    ) -> None:

        delta = (
            event.angleDelta().y()
        )

        if delta == 0:
            return

        mouse = (
            event.position()
        )

        old_zoom = self.zoom

        if delta > 0:
            self.zoom *= 1.15
        else:
            self.zoom /= 1.15

        self.zoom = max(
            self.min_zoom,
            min(
                self.zoom,
                self.max_zoom,
            ),
        )

        if self.zoom != old_zoom:

            image_position = (
                mouse
                - self.offset
            ) / old_zoom

            self.offset = (
                mouse
                - image_position
                * self.zoom
            )

        self.update()

        event.accept()

    # ==========================================================
    # NETTOYAGE
    # ==========================================================

    def cleanup_gpu(self) -> None:

        if (
            not self.gpu_ready
            and self.texture is None
            and self.blitter is None
        ):
            return

        try:
            self.makeCurrent()
        except RuntimeError:
            return

        try:

            if self.texture is not None:

                if self.texture.isCreated():
                    self.texture.destroy()

                self.texture = None

            if self.blitter is not None:

                if self.blitter.isCreated():
                    self.blitter.destroy()

                self.blitter = None

            self.gpu_ready = False

        finally:

            self.doneCurrent()

    def closeEvent(
        self,
        event,
    ) -> None:

        self.cleanup_gpu()

        super().closeEvent(
            event
        )
