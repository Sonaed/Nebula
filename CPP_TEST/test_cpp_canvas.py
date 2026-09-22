import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTabletEvent
from PySide6.QtWidgets import QApplication, QWidget


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "build_cpp" / "libCreativeCoreBridge.so"

if not LIBRARY.exists():
    raise FileNotFoundError(
        f"Bibliothèque C++ introuvable : {LIBRARY}"
    )


lib = ctypes.CDLL(str(LIBRARY))

Handle = ctypes.c_void_p


lib.cs_brush_create.restype = Handle

lib.cs_brush_destroy.argtypes = [
    Handle
]

lib.cs_brush_set_size.argtypes = [
    Handle,
    ctypes.c_float
]

lib.cs_brush_set_opacity.argtypes = [
    Handle,
    ctypes.c_float
]

lib.cs_brush_set_flow.argtypes = [
    Handle,
    ctypes.c_float
]

lib.cs_brush_set_hardness.argtypes = [
    Handle,
    ctypes.c_float
]

lib.cs_brush_set_spacing.argtypes = [
    Handle,
    ctypes.c_float
]

lib.cs_brush_set_color.argtypes = [
    Handle,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.c_uint8
]

lib.cs_brush_begin_stroke.argtypes = [
    Handle,
    ctypes.c_float,
    ctypes.c_float,
    ctypes.c_float
]

lib.cs_brush_draw_segment.argtypes = [
    Handle,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_float,
    ctypes.c_float,
    ctypes.c_float,
    ctypes.c_float,
    ctypes.c_float,
    ctypes.c_float,
]

lib.cs_brush_end_stroke.argtypes = [
    Handle
]


class CppCanvas(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "CreativeCore - C++ Canvas Test"
        )

        self.setMinimumSize(
            1000,
            700
        )

        self.canvas_width = 1000
        self.canvas_height = 700

        self.previous_pos = None
        self.previous_pressure = 1.0
        self.drawing = False
        self.tablet_drawing = False
        self.tablet_pressure = 1.0

        # --------------------------------------------------
        # Buffer RGBA partagé avec QImage
        # --------------------------------------------------

        self.buffer = bytearray(
            self.canvas_width *
            self.canvas_height *
            4
        )

        # Fond blanc opaque.
        for y in range(self.canvas_height):
            row_start = (
                y *
                self.canvas_width *
                4
            )

            for x in range(self.canvas_width):
                i = row_start + x * 4

                self.buffer[i + 0] = 255
                self.buffer[i + 1] = 255
                self.buffer[i + 2] = 255
                self.buffer[i + 3] = 255

        self.byte_array = (
            ctypes.c_uint8 *
            len(self.buffer)
        ).from_buffer(
            self.buffer
        )

        self.image = QImage(
            self.buffer,
            self.canvas_width,
            self.canvas_height,
            self.canvas_width * 4,
            QImage.Format.Format_RGBA8888
        )

        # --------------------------------------------------
        # Brush C++
        # --------------------------------------------------

        self.brush = (
            lib.cs_brush_create()
        )

        if not self.brush:
            raise RuntimeError(
                "Impossible de créer BrushEngine C++"
            )

        lib.cs_brush_set_size(
            self.brush,
            50.0
        )

        lib.cs_brush_set_opacity(
            self.brush,
            1.0
        )

        lib.cs_brush_set_flow(
            self.brush,
            1.0
        )

        lib.cs_brush_set_hardness(
            self.brush,
            0.80
        )

        lib.cs_brush_set_spacing(
            self.brush,
            0.12
        )

        lib.cs_brush_set_color(
            self.brush,
            20,
            60,
            220,
            255
        )

        self.setMouseTracking(
            True
        )

        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus
        )

    def __del__(self):
        brush = getattr(
            self,
            "brush",
            None
        )

        if brush:
            lib.cs_brush_destroy(
                brush
            )

            self.brush = None

    def tabletEvent(self, event):
        event_type = event.type()

        # -----------------------------------------------
        # Pression
        # -----------------------------------------------
        pressure = max(
            0.0,
            min(
                1.0,
                float(event.pressure())
            )
        )

        position = event.position()

        x = float(position.x())
        y = float(position.y())

        # Diagnostic temporaire : affiche la pression
        # uniquement pendant un TabletMove / Press.
        if event_type in (
            event.Type.TabletPress,
            event.Type.TabletMove,
        ):
            print(
                f"Tablet pressure: {pressure:.3f}",
                end="\\r",
                flush=True
            )

        # -----------------------------------------------
        # Début du stroke
        # -----------------------------------------------
        if event_type == event.Type.TabletPress:
            self.previous_pos = QPoint(
                int(x),
                int(y)
            )

            self.previous_pressure = pressure
            self.tablet_pressure = pressure
            self.tablet_drawing = True
            self.drawing = True

            lib.cs_brush_begin_stroke(
                self.brush,
                ctypes.c_float(x),
                ctypes.c_float(y),
                ctypes.c_float(pressure)
            )

            self.update()

            event.accept()
            return

        # -----------------------------------------------
        # Stroke en cours
        # -----------------------------------------------
        if event_type == event.Type.TabletMove:
            if not self.tablet_drawing:
                event.accept()
                return

            if self.previous_pos is None:
                self.previous_pos = QPoint(
                    int(x),
                    int(y)
                )

                self.previous_pressure = pressure

                event.accept()
                return

            start_x = float(
                self.previous_pos.x()
            )

            start_y = float(
                self.previous_pos.y()
            )

            lib.cs_brush_draw_segment(
                self.brush,
                self.byte_array,
                self.canvas_width,
                self.canvas_height,
                self.canvas_width * 4,
                ctypes.c_float(start_x),
                ctypes.c_float(start_y),
                ctypes.c_float(
                    self.previous_pressure
                ),
                ctypes.c_float(x),
                ctypes.c_float(y),
                ctypes.c_float(pressure),
            )

            self.previous_pos = QPoint(
                int(x),
                int(y)
            )

            self.previous_pressure = pressure
            self.tablet_pressure = pressure

            self.update()

            event.accept()
            return

        # -----------------------------------------------
        # Fin du stroke
        # -----------------------------------------------
        if event_type == event.Type.TabletRelease:
            if self.tablet_drawing:
                lib.cs_brush_end_stroke(
                    self.brush
                )

            self.tablet_drawing = False
            self.drawing = False

            self.previous_pos = None
            self.previous_pressure = 1.0
            self.tablet_pressure = 1.0

            print(
                "\nTablet stroke terminé"
            )

            self.update()

            event.accept()
            return

        event.accept()

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        return self.size()

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(
            self.rect(),
            QColor(
                35,
                35,
                35
            )
        )

        # Le QImage possède la même mémoire que self.buffer.
        painter.drawImage(
            0,
            0,
            self.image
        )

        painter.end()

    def mousePressEvent(self, event):
        if self.tablet_drawing:
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        position = event.position()

        x = position.x()
        y = position.y()

        self.previous_pos = QPoint(
            int(x),
            int(y)
        )

        self.previous_pressure = 1.0
        self.drawing = True

        lib.cs_brush_begin_stroke(
            self.brush,
            ctypes.c_float(x),
            ctypes.c_float(y),
            ctypes.c_float(
                self.previous_pressure
            )
        )

        self.update()

    def mouseMoveEvent(self, event):
        if self.tablet_drawing:
            return

        if not self.drawing:
            return

        buttons = event.buttons()

        if not (
            buttons &
            Qt.MouseButton.LeftButton
        ):
            return

        if self.previous_pos is None:
            return

        position = event.position()

        x = position.x()
        y = position.y()

        start_x = float(
            self.previous_pos.x()
        )

        start_y = float(
            self.previous_pos.y()
        )

        end_x = float(x)
        end_y = float(y)

        start_pressure = (
            self.previous_pressure
        )

        # Souris = pression constante.
        end_pressure = 1.0

        lib.cs_brush_draw_segment(
            self.brush,
            self.byte_array,
            self.canvas_width,
            self.canvas_height,
            self.canvas_width * 4,
            ctypes.c_float(start_x),
            ctypes.c_float(start_y),
            ctypes.c_float(start_pressure),
            ctypes.c_float(end_x),
            ctypes.c_float(end_y),
            ctypes.c_float(end_pressure),
        )

        self.previous_pos = QPoint(
            int(x),
            int(y)
        )

        self.previous_pressure = (
            end_pressure
        )

        self.update()

    def mouseReleaseEvent(self, event):
        if self.tablet_drawing:
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.drawing:
            lib.cs_brush_end_stroke(
                self.brush
            )

        self.drawing = False
        self.previous_pos = None

        self.update()


def main():
    app = QApplication(
        sys.argv
    )

    window = CppCanvas()

    window.show()

    print(
        "CreativeCore -> PySide6 Canvas OK"
    )

    print(
        "Souris : clic gauche | XP-Pen : stylet."
    )

    print(
        "La pression XP-Pen est envoyée directement au C++."
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(
        main()
    )
