import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from CORE.application import CreativeSystem


def main():
    # QOpenGLTextureBlitter has a legacy GLSL-ES shader path which can try to
    # compile ``layout(blend_support_*)`` qualifiers on drivers exposing
    # GL_KHR_blend_equation_advanced.  On a desktop Linux session this may
    # result in GLSL 1.00 compile errors (and a transparent/flickering canvas).
    # Request a desktop compatibility context before QApplication is created;
    # the renderer still keeps its CPU fallback when no such context exists.
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
        True,
    )

    surface_format = QSurfaceFormat()
    surface_format.setRenderableType(
        QSurfaceFormat.RenderableType.OpenGL
    )
    surface_format.setVersion(3, 3)
    surface_format.setProfile(
        QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile
    )
    surface_format.setSwapBehavior(
        QSurfaceFormat.SwapBehavior.DoubleBuffer
    )
    surface_format.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication(sys.argv)

    window = CreativeSystem()
    window.run()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
