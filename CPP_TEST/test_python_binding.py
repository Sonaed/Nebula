import ctypes
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LIBRARY = (
    ROOT
    / "build_cpp"
    / "libCreativeCoreBridge.so"
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
    ctypes.c_float
]

lib.cs_brush_end_stroke.argtypes = [
    Handle
]


WIDTH = 512
HEIGHT = 512
BYTES_PER_LINE = WIDTH * 4


buffer = bytearray(
    [255] *
    (
        WIDTH *
        HEIGHT *
        4
    )
)


# Alpha à 255 pour toute l'image.
for i in range(3, len(buffer), 4):
    buffer[i] = 255


pixels = (
    (ctypes.c_uint8 * len(buffer))
    .from_buffer(buffer)
)


brush = lib.cs_brush_create()


if not brush:
    raise RuntimeError(
        "Impossible de créer BrushEngine"
    )


try:
    lib.cs_brush_set_size(
        brush,
        50.0
    )

    lib.cs_brush_set_opacity(
        brush,
        1.0
    )

    lib.cs_brush_set_flow(
        brush,
        1.0
    )

    lib.cs_brush_set_hardness(
        brush,
        0.8
    )

    lib.cs_brush_set_spacing(
        brush,
        0.15
    )

    lib.cs_brush_set_color(
        brush,
        20,
        40,
        220,
        255
    )

    lib.cs_brush_begin_stroke(
        brush,
        40.0,
        256.0,
        0.25
    )

    lib.cs_brush_draw_segment(
        brush,
        pixels,
        WIDTH,
        HEIGHT,
        BYTES_PER_LINE,
        40.0,
        256.0,
        0.25,
        470.0,
        256.0,
        1.0
    )

    lib.cs_brush_end_stroke(
        brush
    )

finally:
    lib.cs_brush_destroy(
        brush
    )


center = (
    buffer[
        (256 * BYTES_PER_LINE) + (256 * 4)
    ],
    buffer[
        (256 * BYTES_PER_LINE) + (256 * 4) + 1
    ],
    buffer[
        (256 * BYTES_PER_LINE) + (256 * 4) + 2
    ],
    buffer[
        (256 * BYTES_PER_LINE) + (256 * 4) + 3
    ],
)


print(
    "Python -> C++ binding OK"
)

print(
    "Pixel centre :",
    center
)

if center[:3] == (255, 255, 255):
    print(
        "ERREUR : le moteur n'a pas modifié le buffer"
    )
else:
    print(
        "Buffer modifié par CreativeCore"
    )
