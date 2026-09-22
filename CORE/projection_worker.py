"""Native CreativeCore tile projection worker."""
from __future__ import annotations

import ctypes
from PySide6.QtCore import QSettings
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from CORE.native_bridge import configure_projection_api


_MODES = ("normal", "darken", "multiply", "color_burn", "lighten", "screen",
          "color_dodge", "overlay", "soft_light", "hard_light", "difference",
          "exclusion", "hue", "saturation", "color", "luminosity")
_MODE_IDS = {name: i for i, name in enumerate(_MODES)}
_PARAMS = ("opacity", "opposite_mix", "intensity", "gamma", "mix_normal", "pivot",
           "clamp", "softness", "hue_shift", "saturation_boost", "offset")
_DEFAULTS = (1., 0., 1., 1., 0., .5, 1., .5, 0., 1., 0.)


@dataclass(frozen=True)
class ProjectionLayer:
    image: QImage
    visible: bool
    opacity: float
    blend_mode: str
    blend_parameters: dict
    clipping: bool = False


class _NativeLayer(ctypes.Structure):
    _fields_ = [("rgba", ctypes.POINTER(ctypes.c_uint8)), ("width", ctypes.c_int),
                ("height", ctypes.c_int), ("stride", ctypes.c_int),
                ("visible", ctypes.c_int), ("opacity", ctypes.c_float),
                ("blend_mode", ctypes.c_int), ("blend_parameters", ctypes.c_float * 11),
                ("parameterized", ctypes.c_int), ("clipping", ctypes.c_int)]


class _NativeTile(ctypes.Structure):
    _fields_ = [("generation", ctypes.c_uint64), ("tile_x", ctypes.c_int),
                ("tile_y", ctypes.c_int), ("width", ctypes.c_int),
                ("height", ctypes.c_int), ("layers", ctypes.POINTER(_NativeLayer)),
                ("layer_count", ctypes.c_int)]


class ProjectionWorker(QObject):
    """Copies immutable tile snapshots to CreativeCore; OpenGL stays on the UI thread."""

    projected = Signal(int, int, int, object)
    failed = Signal(int, int, int, str)
    _native_result = Signal(int, int, int, object, str)

    def __init__(self, parent=None, native_library=None):
        super().__init__(parent)
        self._generation = 0
        self._closed = False
        self._native_handle = None
        self._native_callback = None
        self._native_result.connect(self._deliver_native_result)
        self.native_enabled = self._start_native(native_library)
        if not self.native_enabled:
            raise RuntimeError("CreativeCore est requis pour projeter les calques")

    def _start_native(self, library) -> bool:
        if library is None:
            return False
        try:
            callback_type, batch_function = configure_projection_api(
                library, _NativeLayer, _NativeTile
            )

            def receive(generation, tx, ty, pixels, width, height, stride, error, _user):
                try:
                    message = error.decode("utf-8", "replace") if error else ""
                    image = None
                    if not message and pixels and width > 0 and height > 0 and stride >= width * 4:
                        borrowed = (ctypes.c_uint8 * (stride * height)).from_address(
                            ctypes.addressof(pixels.contents))
                        image = QImage(borrowed, width, height, stride,
                                       QImage.Format.Format_RGBA8888).copy()
                    self._native_result.emit(int(generation), int(tx), int(ty), image, message)
                except Exception as exc:
                    self._native_result.emit(int(generation), int(tx), int(ty), None, str(exc))

            self._native_callback = callback_type(receive)
            self._native_library = library
            self._native_batch_function = batch_function
            self._native_handle = library.cs_projection_start(self._native_callback, None)
            if self._native_handle:
                settings = QSettings("CreativeSystem", "CreativeSystem")
                configured = str(settings.value("cpu/threads", "Automatic"))
                try:
                    thread_count = 0 if configured == "Automatic" else int(configured)
                except ValueError:
                    thread_count = 0
                self.set_thread_count(thread_count)
            return bool(self._native_handle)
        except (AttributeError, OSError, TypeError):
            self._native_handle = None
            return False

    def set_thread_count(self, count: int) -> None:
        """Configure the native projection worker; zero selects automatic sizing."""
        if self._native_handle:
            self._native_library.cs_projection_set_threads(
                self._native_handle, max(0, min(64, int(count)))
            )

    def request(self, tile_inputs: dict) -> int:
        self._generation += 1
        generation = self._generation
        if self._closed:
            return generation

        native_tiles, tile_keepalive = [], []
        for (tx, ty), (width, height, layers) in tile_inputs.items():
            native_layers, keepalive = [], []
            for layer in layers:
                image = layer.image.convertToFormat(QImage.Format.Format_RGBA8888).copy()
                bits = (ctypes.c_uint8 * image.sizeInBytes()).from_buffer(image.bits())
                params = dict(layer.blend_parameters or {})
                values = [float(params.get(name, default))
                          for name, default in zip(_PARAMS, _DEFAULTS)]
                native_layers.append(_NativeLayer(
                    ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), image.width(), image.height(),
                    image.bytesPerLine(), int(bool(layer.visible)), float(layer.opacity),
                    _MODE_IDS.get(str(layer.blend_mode).lower(), 0), (ctypes.c_float * 11)(*values),
                    int(bool(layer.blend_parameters)), int(bool(layer.clipping))))
                keepalive.extend((image, bits))
            array = (_NativeLayer * len(native_layers))(*native_layers)
            tile_keepalive.extend(keepalive)
            tile_keepalive.append(array)
            native_tiles.append(_NativeTile(generation, tx, ty, width, height,
                                            array, len(native_layers)))
        if self._native_batch_function is not None and native_tiles:
            tiles_array = (_NativeTile * len(native_tiles))(*native_tiles)
            ok = self._native_batch_function(self._native_handle, tiles_array, len(native_tiles))
            if not ok:
                for tile in native_tiles:
                    self.failed.emit(generation, tile.tile_x, tile.tile_y,
                                     "CreativeCore rejected projection batch")
        else:
            for tile in native_tiles:
                ok = self._native_library.cs_projection_invalidate(
                    self._native_handle, tile.generation, tile.tile_x, tile.tile_y,
                    tile.width, tile.height, tile.layers, tile.layer_count)
                if not ok:
                    self.failed.emit(generation, tile.tile_x, tile.tile_y,
                                     "CreativeCore rejected projection request")
        return generation

    def _deliver_native_result(self, generation, tx, ty, image, error):
        if error or image is None:
            self.failed.emit(generation, tx, ty, error or "Native projection returned no image")
        else:
            self.projected.emit(generation, tx, ty, image)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._native_handle:
            self._native_library.cs_projection_stop(self._native_handle)
            self._native_handle = None
