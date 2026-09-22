"""Shared loader and ctypes declarations for the CreativeCore C ABI.

The bridge is the boundary between PySide6 presentation adapters and the
native document/drawing engine. Keep symbol declarations centralized here so
all Python-facing components use the same ABI contract.
"""
from __future__ import annotations

import ctypes
import math
import sys
from array import array
from pathlib import Path

_LIBRARY = None


def _candidate_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[1]
    if sys.platform == "win32":
        names = ("CreativeCoreBridge.dll",)
    elif sys.platform == "darwin":
        names = ("libCreativeCoreBridge.dylib", "libCreativeCoreBridge.so")
    else:
        names = ("libCreativeCoreBridge.so",)
    return tuple(root / build / name for build in ("build_cpp_native", "build_cpp")
                 for name in names)


def load_creative_core():
    """Return the process-wide CreativeCore bridge, or ``None`` if unbuilt."""
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    for path in _candidate_paths():
        if not path.is_file():
            continue
        try:
            library = ctypes.CDLL(str(path))
            _configure_selection(library)
            _configure_tile_store(library)
            _configure_texture_atlas(library)
            _configure_lz4(library)
            _configure_transforms(library)
            _configure_gradients(library)
            _configure_canvas_api(library)
            _configure_document_codecs(library)
            _configure_layer_stack(library)
            _configure_layer_composite(library)
            _configure_document_state(library)
            _LIBRARY = library
            return _LIBRARY
        except (OSError, AttributeError):
            continue
    return None


def _configure_selection(library) -> None:
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_selection_combine.argtypes = [byte_ptr, byte_ptr, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_selection_combine.restype = ctypes.c_int
    library.cs_selection_invert.argtypes = [byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_selection_invert.restype = ctypes.c_int
    library.cs_selection_bounds.argtypes = [byte_ptr, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, *([ctypes.POINTER(ctypes.c_int)] * 4)]
    library.cs_selection_bounds.restype = ctypes.c_int
    library.cs_selection_contains.argtypes = [byte_ptr, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    library.cs_selection_contains.restype = ctypes.c_int


def _configure_tile_store(library) -> None:
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    handle = ctypes.c_void_p
    library.cs_tile_store_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_create.restype = handle
    library.cs_tile_store_destroy.argtypes = [handle]
    library.cs_tile_store_set.argtypes = [handle, ctypes.c_int, ctypes.c_int, byte_ptr,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_set.restype = ctypes.c_int
    class TileWrite(ctypes.Structure):
        _fields_ = [("tile_x", ctypes.c_int), ("tile_y", ctypes.c_int),
                    ("pixels", byte_ptr), ("width", ctypes.c_int),
                    ("height", ctypes.c_int), ("stride", ctypes.c_int),
                    ("image_format", ctypes.c_int)]
    library._cs_tile_write_type = TileWrite
    library.cs_tile_store_set_many.argtypes = [handle, ctypes.POINTER(TileWrite), ctypes.c_int]
    library.cs_tile_store_set_many.restype = ctypes.c_int
    library.cs_tile_store_write_image.argtypes = [handle, byte_ptr, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    library.cs_tile_store_write_image.restype = ctypes.c_int
    library.cs_tile_store_copy.argtypes = [handle, ctypes.c_int, ctypes.c_int, byte_ptr,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_copy.restype = ctypes.c_int
    library.cs_tile_store_copy_store.argtypes = [handle, handle]
    library.cs_tile_store_copy_store.restype = ctypes.c_int
    library.cs_tile_store_materialize.argtypes = [handle, byte_ptr, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_materialize.restype = ctypes.c_int
    library.cs_tile_store_info.argtypes = [handle, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64)]
    library.cs_tile_store_info.restype = ctypes.c_int
    library.cs_tile_store_copy_keys.argtypes = [handle, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    library.cs_tile_store_copy_keys.restype = ctypes.c_int
    library.cs_tile_store_remove.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_remove.restype = ctypes.c_int
    library.cs_tile_store_write_png.argtypes = [handle, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
    library.cs_tile_store_write_png.restype = ctypes.c_int64
    library.cs_tile_store_load_png.argtypes = [handle, ctypes.c_int, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_uint64]
    library.cs_tile_store_load_png.restype = ctypes.c_int
    library.cs_image_write_png.argtypes = [ctypes.c_char_p, byte_ptr,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_image_write_png.restype = ctypes.c_int64
    library.cs_image_fill.argtypes = [byte_ptr, *([ctypes.c_int] * 8)]
    library.cs_image_fill.restype = ctypes.c_int
    library.cs_image_fill_rect.argtypes = [byte_ptr, *([ctypes.c_int] * 12)]
    library.cs_image_fill_rect.restype = ctypes.c_int
    library.cs_render_brush_preset_art.argtypes = [
        byte_ptr, *([ctypes.c_int] * 4), byte_ptr, *([ctypes.c_int] * 4),
        ctypes.c_float, ctypes.c_float,
        *([ctypes.c_int] * 4),
    ]
    library.cs_render_brush_preset_art.restype = ctypes.c_int
    library.cs_apply_alpha_mask.argtypes = [
        byte_ptr, *([ctypes.c_int] * 4), byte_ptr, *([ctypes.c_int] * 4),
    ]
    library.cs_apply_alpha_mask.restype = ctypes.c_int
    library.cs_tile_store_clear.argtypes = [handle]
    library.cs_tile_store_resize.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    library.cs_tile_store_allocated_bytes.argtypes = [handle]
    library.cs_tile_store_allocated_bytes.restype = ctypes.c_int64


def _configure_texture_atlas(library) -> bool:
    names = ("cs_texture_atlas_create", "cs_texture_atlas_destroy",
             "cs_texture_atlas_add", "cs_texture_atlas_write",
             "cs_texture_atlas_copy")
    if any(not hasattr(library, name) for name in names):
        return False
    handle = ctypes.c_void_p
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_texture_atlas_create.argtypes = [ctypes.c_int, ctypes.c_int]
    library.cs_texture_atlas_create.restype = handle
    library.cs_texture_atlas_destroy.argtypes = [handle]
    library.cs_texture_atlas_destroy.restype = None
    library.cs_texture_atlas_add.argtypes = [handle, ctypes.c_int, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_int),
                                             ctypes.POINTER(ctypes.c_int)]
    library.cs_texture_atlas_add.restype = ctypes.c_int
    for name in ("cs_texture_atlas_write", "cs_texture_atlas_copy"):
        function = getattr(library, name)
        function.argtypes = [handle, ctypes.c_int, ctypes.c_int, byte_ptr,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int]
        function.restype = ctypes.c_int
    return True


class NativeTextureAtlasHandle:
    """Owns the packed RGBA atlas; Python retains only key-to-rect metadata."""

    def __init__(self, library, size: int, padding: int):
        self._library = library
        self._handle = library.cs_texture_atlas_create(int(size), int(padding))

    def __bool__(self):
        return bool(self._handle)

    def close(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_texture_atlas_destroy(handle)

    def __del__(self):
        # The atlas is independent of an OpenGL context; release it even when
        # QWidget teardown happens after the context has already disappeared.
        try:
            self.close()
        except Exception:
            pass

    def add(self, width: int, height: int):
        if not self._handle:
            return None
        x, y = ctypes.c_int(), ctypes.c_int()
        if not self._library.cs_texture_atlas_add(self._handle, int(width), int(height),
                                                  ctypes.byref(x), ctypes.byref(y)):
            return None
        return x.value, y.value

    def write(self, x: int, y: int, image) -> bool:
        if not self._handle:
            return False
        return bool(self._library.cs_texture_atlas_write(
            self._handle, int(x), int(y), qimage_pointer(image), image.width(),
            image.height(), image.bytesPerLine()))

    def copy(self, x: int, y: int, width: int, height: int):
        from PySide6.QtGui import QImage
        if not self._handle or width <= 0 or height <= 0:
            return QImage()
        image = QImage(int(width), int(height), QImage.Format.Format_RGBA8888)
        if not self._library.cs_texture_atlas_copy(
                self._handle, int(x), int(y), qimage_pointer(image), image.width(),
                image.height(), image.bytesPerLine()):
            return QImage()
        return image


def _configure_history_cursor(library) -> bool:
    names = (
        "cs_history_cursor_create", "cs_history_cursor_destroy",
        "cs_history_cursor_reset", "cs_history_cursor_begin_transaction",
        "cs_history_cursor_commit_transaction", "cs_history_cursor_cancel_transaction",
        "cs_history_cursor_transaction_open", "cs_history_cursor_transaction_mode",
        "cs_history_cursor_append",
        "cs_history_cursor_append_state", "cs_history_cursor_state_size",
        "cs_history_cursor_copy_state",
        "cs_history_cursor_discard_oldest", "cs_history_cursor_set_maximum",
        "cs_history_cursor_undo", "cs_history_cursor_redo",
        "cs_history_cursor_synchronize", "cs_history_cursor_count",
        "cs_history_cursor_index", "cs_history_cursor_maximum",
        "cs_history_validate_layer_state",
    )
    if any(not hasattr(library, name) for name in names):
        return False
    handle = ctypes.c_void_p
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_history_cursor_create.argtypes = [ctypes.c_int]
    library.cs_history_cursor_create.restype = handle
    library.cs_history_cursor_destroy.argtypes = [handle]
    library.cs_history_cursor_destroy.restype = None
    library.cs_history_cursor_reset.argtypes = [handle]
    library.cs_history_cursor_reset.restype = None
    library.cs_history_cursor_begin_transaction.argtypes = [handle,
        ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_history_cursor_begin_transaction.restype = ctypes.c_int
    for name in ("cs_history_cursor_commit_transaction",
                 "cs_history_cursor_cancel_transaction",
                 "cs_history_cursor_transaction_open",
                 "cs_history_cursor_transaction_mode"):
        function = getattr(library, name)
        function.argtypes = [handle]
        function.restype = ctypes.c_int
    library.cs_history_cursor_append.argtypes = [handle,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    library.cs_history_cursor_append.restype = ctypes.c_int
    library.cs_history_cursor_append_state.argtypes = [
        handle, byte_ptr, ctypes.c_uint32, byte_ptr, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ]
    library.cs_history_cursor_append_state.restype = ctypes.c_int
    library.cs_history_cursor_state_size.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    library.cs_history_cursor_state_size.restype = ctypes.c_uint32
    library.cs_history_cursor_copy_state.argtypes = [
        handle, ctypes.c_int, ctypes.c_int, byte_ptr, ctypes.c_uint32,
    ]
    library.cs_history_cursor_copy_state.restype = ctypes.c_int
    library.cs_history_cursor_discard_oldest.argtypes = [handle, ctypes.c_int]
    library.cs_history_cursor_discard_oldest.restype = ctypes.c_int
    library.cs_history_cursor_set_maximum.argtypes = [handle, ctypes.c_int]
    library.cs_history_cursor_set_maximum.restype = ctypes.c_int
    library.cs_history_cursor_undo.argtypes = [handle]
    library.cs_history_cursor_undo.restype = ctypes.c_int
    library.cs_history_cursor_redo.argtypes = [handle]
    library.cs_history_cursor_redo.restype = ctypes.c_int
    library.cs_history_cursor_synchronize.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    library.cs_history_cursor_synchronize.restype = None
    library.cs_history_validate_layer_state.argtypes = [
        byte_ptr, ctypes.c_uint32, ctypes.c_int, ctypes.c_int,
    ]
    library.cs_history_validate_layer_state.restype = ctypes.c_int
    for name in ("cs_history_cursor_count", "cs_history_cursor_index",
                 "cs_history_cursor_maximum"):
        function = getattr(library, name)
        function.argtypes = [handle]
        function.restype = ctypes.c_int
    return True


def validate_history_layer_state(payload: bytes, width: int, height: int) -> bool | None:
    """Validate a structural history snapshot in CreativeCore."""
    library = load_creative_core()
    if library is None or not _configure_history_cursor(library):
        return None
    data = bytes(payload)
    if not data or len(data) > 16 * 1024 * 1024:
        return False
    buffer = ctypes.create_string_buffer(data, len(data))
    return bool(library.cs_history_validate_layer_state(
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)), len(data),
        int(width), int(height)))


def _configure_history_payload(library) -> bool:
    names = (
        "cs_history_payload_create", "cs_history_payload_destroy",
        "cs_history_payload_append", "cs_history_payload_append_many",
        "cs_history_payload_tile_info",
        "cs_history_payload_copy_tile", "cs_history_payload_count",
        "cs_history_payload_allocated_bytes", "cs_history_payload_clear",
        "cs_history_payload_apply_to_tile_stores",
    )
    if any(not hasattr(library, name) for name in names):
        return False
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    class ImageView(ctypes.Structure):
        _fields_ = [("pixels", byte_ptr), ("width", ctypes.c_int),
                    ("height", ctypes.c_int), ("stride", ctypes.c_int),
                    ("image_format", ctypes.c_int)]
    class ImagePair(ctypes.Structure):
        _fields_ = [("before", ImageView), ("after", ImageView),
                    ("has_before", ctypes.c_int), ("has_after", ctypes.c_int)]
    library._cs_image_view_type = ImageView
    library._cs_history_image_pair_type = ImagePair
    class HistoryStoreWrite(ctypes.Structure):
        _fields_ = [("store", ctypes.c_void_p), ("payload_index", ctypes.c_int),
                    ("tile_x", ctypes.c_int), ("tile_y", ctypes.c_int)]
    library._cs_history_store_write_type = HistoryStoreWrite
    handle = ctypes.c_void_p
    library.cs_history_payload_create.argtypes = []
    library.cs_history_payload_create.restype = handle
    library.cs_history_payload_destroy.argtypes = [handle]
    library.cs_history_payload_destroy.restype = None
    library.cs_history_payload_append.argtypes = [handle,
        ctypes.POINTER(ImageView), ctypes.POINTER(ImageView)]
    library.cs_history_payload_append.restype = ctypes.c_int
    library.cs_history_payload_append_many.argtypes = [handle,
        ctypes.POINTER(ImagePair), ctypes.c_int, ctypes.POINTER(ctypes.c_int),
        ctypes.c_int]
    library.cs_history_payload_append_many.restype = ctypes.c_int
    library.cs_history_payload_tile_info.argtypes = [handle, ctypes.c_int,
        ctypes.c_int, *([ctypes.POINTER(ctypes.c_int)] * 4)]
    library.cs_history_payload_tile_info.restype = ctypes.c_int
    library.cs_history_payload_copy_tile.argtypes = [handle, ctypes.c_int,
        ctypes.c_int, byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int]
    library.cs_history_payload_copy_tile.restype = ctypes.c_int
    library.cs_history_payload_count.argtypes = [handle]
    library.cs_history_payload_count.restype = ctypes.c_int
    library.cs_history_payload_allocated_bytes.argtypes = [handle]
    library.cs_history_payload_allocated_bytes.restype = ctypes.c_int64
    library.cs_history_payload_clear.argtypes = [handle]
    library.cs_history_payload_clear.restype = None
    library.cs_history_payload_apply_to_tile_stores.argtypes = [handle,
        ctypes.POINTER(HistoryStoreWrite), ctypes.c_int, ctypes.c_int]
    library.cs_history_payload_apply_to_tile_stores.restype = ctypes.c_int
    return True


def _configure_lz4(library) -> bool:
    names = ("cs_lz4_available", "cs_lz4_compress_bound",
             "cs_lz4_compress", "cs_lz4_decompress", "cs_cslz_max_encoded_size",
             "cs_cslz_encode", "cs_cslz_decode_info", "cs_cslz_decode")
    if any(not hasattr(library, name) for name in names):
        return False
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_lz4_available.argtypes = []
    library.cs_lz4_available.restype = ctypes.c_int
    library.cs_lz4_compress_bound.argtypes = [ctypes.c_int]
    library.cs_lz4_compress_bound.restype = ctypes.c_int
    library.cs_lz4_compress.argtypes = [byte_ptr, ctypes.c_int, byte_ptr,
        ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    library.cs_lz4_compress.restype = ctypes.c_int
    library.cs_lz4_decompress.argtypes = [byte_ptr, ctypes.c_int, byte_ptr,
        ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    library.cs_lz4_decompress.restype = ctypes.c_int
    library.cs_cslz_max_encoded_size.argtypes = [ctypes.c_int]
    library.cs_cslz_max_encoded_size.restype = ctypes.c_int
    library.cs_cslz_encode.argtypes = [byte_ptr, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, byte_ptr, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    library.cs_cslz_encode.restype = ctypes.c_int
    library.cs_cslz_decode_info.argtypes = [byte_ptr, ctypes.c_int,
        *([ctypes.POINTER(ctypes.c_int)] * 5)]
    library.cs_cslz_decode_info.restype = ctypes.c_int
    library.cs_cslz_decode.argtypes = [byte_ptr, ctypes.c_int, byte_ptr,
        ctypes.c_int]
    library.cs_cslz_decode.restype = ctypes.c_int
    return True


def _configure_document_state(library) -> None:
    """Declare the native document/layer metadata ABI once."""
    handle = ctypes.c_void_p
    library.cs_document_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.cs_document_create.restype = handle
    library.cs_document_destroy.argtypes = [handle]
    library.cs_document_destroy.restype = None
    library.cs_document_add_layer.argtypes = [handle, ctypes.c_char_p,
                                              ctypes.POINTER(ctypes.c_int)]
    library.cs_document_add_layer.restype = ctypes.c_int
    library.cs_document_reset_layers.argtypes = [handle]
    library.cs_document_reset_layers.restype = None
    library.cs_document_create_group.argtypes = [handle, ctypes.POINTER(ctypes.c_int),
        ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    library.cs_document_create_group.restype = ctypes.c_int
    library.cs_document_remove_group.argtypes = [handle, ctypes.c_int]
    library.cs_document_remove_group.restype = ctypes.c_int
    library.cs_document_set_group_property.argtypes = [
        handle, ctypes.c_int, ctypes.c_int, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double)]
    library.cs_document_set_group_property.restype = ctypes.c_int
    library.cs_document_reset_groups.argtypes = [handle]
    library.cs_document_reset_groups.restype = None
    library.cs_document_group_count.argtypes = [handle]
    library.cs_document_group_count.restype = ctypes.c_int
    library.cs_document_group_for_layer.argtypes = [handle, ctypes.c_int]
    library.cs_document_group_for_layer.restype = ctypes.c_int
    library.cs_document_remove_layer.argtypes = [handle, ctypes.c_int]
    library.cs_document_remove_layer.restype = ctypes.c_int
    library.cs_document_reorder_layers.argtypes = [handle,
        ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int]
    library.cs_document_reorder_layers.restype = ctypes.c_int
    library.cs_document_select_layer.argtypes = [handle, ctypes.c_int]
    library.cs_document_select_layer.restype = ctypes.c_int
    library.cs_document_rename_layer.argtypes = [handle, ctypes.c_int, ctypes.c_char_p]
    library.cs_document_rename_layer.restype = ctypes.c_int
    library.cs_document_set_layer_property.argtypes = [
        handle, ctypes.c_int, ctypes.c_int, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double)]
    library.cs_document_set_layer_property.restype = ctypes.c_int
    library.cs_document_layer_count.argtypes = [handle]
    library.cs_document_layer_count.restype = ctypes.c_int
    library.cs_document_active_layer.argtypes = [handle]
    library.cs_document_active_layer.restype = ctypes.c_int
    library.cs_document_layer_info.argtypes = [
        handle, ctypes.c_int, ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int)]
    library.cs_document_layer_info.restype = ctypes.c_int
    library.cs_document_copy_layer_name.argtypes = [
        handle, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    library.cs_document_copy_layer_name.restype = ctypes.c_int


class NativeDocumentStateHandle:
    """C++-owned document/layer structure used by Qt-facing models."""

    def __init__(self, library, width: int, height: int, dpi: int):
        self._library = library
        self._handle = library.cs_document_create(int(width), int(height), int(dpi))

    def __bool__(self):
        return bool(self._handle)

    def close(self):
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_document_destroy(handle)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def layer_count(self) -> int:
        return int(self._library.cs_document_layer_count(self._handle)) if self._handle else 0

    @property
    def active_layer(self) -> int:
        return int(self._library.cs_document_active_layer(self._handle)) if self._handle else -1

    def add_layer(self, name: str) -> int | None:
        if not self._handle:
            return None
        index = ctypes.c_int()
        encoded = str(name).encode("utf-8")
        if not self._library.cs_document_add_layer(self._handle, encoded,
                                                   ctypes.byref(index)):
            return None
        return int(index.value)

    def reset_layers(self) -> None:
        if self._handle:
            self._library.cs_document_reset_layers(self._handle)

    def create_group(self, indices, name: str) -> int | None:
        if not self._handle or not indices:
            return None
        values = (ctypes.c_int * len(indices))(*(int(item) for item in indices))
        group_index = ctypes.c_int(-1)
        if not self._library.cs_document_create_group(
                self._handle, values, len(indices), str(name).encode("utf-8"),
                ctypes.byref(group_index)):
            return None
        return int(group_index.value)

    def remove_group(self, group_index: int) -> bool:
        return bool(self._handle and self._library.cs_document_remove_group(
            self._handle, int(group_index)))

    def set_group_property(self, group_index: int, property_id: int,
                           requested: float) -> float | None:
        if not self._handle:
            return None
        output = ctypes.c_double()
        if not self._library.cs_document_set_group_property(
                self._handle, int(group_index), int(property_id), float(requested),
                ctypes.byref(output)):
            return None
        return float(output.value)

    def reset_groups(self) -> None:
        if self._handle:
            self._library.cs_document_reset_groups(self._handle)

    @property
    def group_count(self) -> int:
        return int(self._library.cs_document_group_count(self._handle)) if self._handle else 0

    def group_for_layer(self, index: int) -> int:
        return int(self._library.cs_document_group_for_layer(
            self._handle, int(index))) if self._handle else -1

    def remove_layer(self, index: int) -> bool:
        return bool(self._handle and self._library.cs_document_remove_layer(
            self._handle, int(index)))

    def select_layer(self, index: int) -> bool:
        return bool(self._handle and self._library.cs_document_select_layer(
            self._handle, int(index)))

    def reorder_layers(self, order, active_index: int) -> bool:
        if not self._handle or not order:
            return False
        values = (ctypes.c_int * len(order))(*(int(item) for item in order))
        return bool(self._library.cs_document_reorder_layers(
            self._handle, values, len(order), int(active_index)))

    def rename_layer(self, index: int, name: str) -> bool:
        return bool(self._handle and self._library.cs_document_rename_layer(
            self._handle, int(index), str(name).encode("utf-8")))

    def set_layer_property(self, index: int, property_id: int,
                           requested: float) -> float | None:
        if not self._handle:
            return None
        output = ctypes.c_double()
        if not self._library.cs_document_set_layer_property(
                self._handle, int(index), int(property_id), float(requested),
                ctypes.byref(output)):
            return None
        return float(output.value)

    def layer_info(self, index: int) -> dict | None:
        if not self._handle:
            return None
        native_id = ctypes.c_uint64()
        visible, locked, lock_alpha, clipping = (ctypes.c_int() for _ in range(4))
        opacity = ctypes.c_float()
        if not self._library.cs_document_layer_info(
                self._handle, int(index), ctypes.byref(native_id),
                ctypes.byref(visible), ctypes.byref(opacity), ctypes.byref(locked),
                ctypes.byref(lock_alpha), ctypes.byref(clipping)):
            return None
        capacity = 4096
        name = ctypes.create_string_buffer(capacity)
        if self._library.cs_document_copy_layer_name(
                self._handle, int(index), name, capacity) < 0:
            return None
        return {"id": int(native_id.value), "name": name.value.decode("utf-8"),
                "visible": bool(visible.value), "opacity": float(opacity.value),
                "locked": bool(locked.value), "lock_alpha": bool(lock_alpha.value),
                "clipping": bool(clipping.value)}


class NativeTileStoreHandle:
    """Owns a native sparse-tile store and contains its complete ctypes ABI.

    The document/UI adapter should exchange QImages and Python coordinates;
    raw pointers, out-parameters, and C arrays stay confined to this bridge.
    """

    def __init__(self, library, width: int, height: int, tile_size: int):
        self._library = library
        self._handle = library.cs_tile_store_create(int(width), int(height), int(tile_size))

    def __bool__(self):
        return bool(self._handle)

    def close(self):
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_tile_store_destroy(handle)

    def info(self, tx, ty):
        if not self._handle:
            return None
        resident, revision, access = ctypes.c_int(), ctypes.c_uint64(), ctypes.c_uint64()
        if not self._library.cs_tile_store_info(self._handle, int(tx), int(ty),
                ctypes.byref(resident), ctypes.byref(revision), ctypes.byref(access)):
            return None
        return bool(resident.value), int(revision.value), int(access.value)

    def keys(self):
        if not self._handle:
            return set()
        count = self._library.cs_tile_store_copy_keys(self._handle, None, 0)
        if count <= 0:
            return set()
        values = (ctypes.c_int * (count * 2))()
        copied = self._library.cs_tile_store_copy_keys(self._handle, values, count)
        return {(values[i * 2], values[i * 2 + 1]) for i in range(max(0, copied))}

    def count(self):
        return len(self.keys())

    def remove(self, tx, ty):
        return bool(self._handle and self._library.cs_tile_store_remove(
            self._handle, int(tx), int(ty)))

    def _image_call(self, symbol, image, *args):
        return bool(self._library.__getattribute__(symbol)(self._handle, *args,
            qimage_pointer(image), image.width(), image.height(),
            image.bytesPerLine(), image.format().value))

    def set(self, tx, ty, image):
        return self._image_call("cs_tile_store_set", image, int(tx), int(ty))

    def set_many(self, writes):
        if not self._handle:
            return False
        tile_type = self._library._cs_tile_write_type
        keepalive = []
        records = []
        for tx, ty, image in writes:
            pixels = qimage_pointer(image)
            keepalive.append(pixels)
            records.append(tile_type(int(tx), int(ty), pixels, image.width(),
                image.height(), image.bytesPerLine(), image.format().value))
        array_type = tile_type * max(1, len(records))
        array_value = array_type(*records) if records else array_type()
        return bool(self._library.cs_tile_store_set_many(
            self._handle, array_value, len(records)))

    def copy(self, tx, ty, image):
        return self._image_call("cs_tile_store_copy", image, int(tx), int(ty))

    def copy_resident_from(self, source: "NativeTileStoreHandle") -> bool:
        return bool(self._handle and source and self._library.cs_tile_store_copy_store(
            self._handle, source._handle))

    def materialize(self, image):
        return self._image_call("cs_tile_store_materialize", image)

    def write_image(self, image, rect, capacity):
        changed = (ctypes.c_int * max(1, int(capacity) * 2))()
        count = self._library.cs_tile_store_write_image(self._handle,
            qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
            image.format().value, int(rect.x()), int(rect.y()), int(rect.width()),
            int(rect.height()), changed, int(capacity))
        if count < 0:
            return None
        return {(changed[i * 2], changed[i * 2 + 1]) for i in range(count)}

    def load_png(self, tx, ty, path, revision):
        return bool(self._handle and self._library.cs_tile_store_load_png(
            self._handle, int(tx), int(ty), str(path).encode("utf-8"), int(revision)))

    def write_png(self, tx, ty, path):
        return int(self._library.cs_tile_store_write_png(self._handle, int(tx), int(ty),
            str(path).encode("utf-8"))) if self._handle else 0

    def resize(self, width, height):
        if self._handle:
            self._library.cs_tile_store_resize(self._handle, int(width), int(height))

    def clear(self):
        if self._handle:
            self._library.cs_tile_store_clear(self._handle)

    def allocated_bytes(self):
        return int(self._library.cs_tile_store_allocated_bytes(self._handle)) if self._handle else 0


class NativeHistoryCursorHandle:
    """C++-owned undo timeline cursor and branch/retention policy."""

    def __init__(self, library, maximum_steps: int):
        self._library = library
        self._handle = library.cs_history_cursor_create(int(maximum_steps))

    def __bool__(self):
        return bool(self._handle)

    def close(self):
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_history_cursor_destroy(handle)

    def reset(self):
        if self._handle:
            self._library.cs_history_cursor_reset(self._handle)

    def begin_transaction(self, dirty_only=False, selection_only=False,
                          structure_only=False) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_begin_transaction(
            self._handle, int(bool(dirty_only)), int(bool(selection_only)),
            int(bool(structure_only))))

    def commit_transaction(self) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_commit_transaction(
            self._handle))

    def cancel_transaction(self) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_cancel_transaction(
            self._handle))

    @property
    def transaction_open(self) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_transaction_open(
            self._handle))

    @property
    def transaction_mode(self) -> int:
        if not self._handle:
            return None
        return {0: "general", 1: "dirty", 2: "selection", 3: "structure"}.get(
            int(self._library.cs_history_cursor_transaction_mode(self._handle)))

    def append(self):
        truncated, discarded = ctypes.c_int(), ctypes.c_int()
        if not self._handle or not self._library.cs_history_cursor_append(
                self._handle, ctypes.byref(truncated), ctypes.byref(discarded)):
            return 0, 0
        return int(truncated.value), int(discarded.value)

    def append_state(self, before: bytes, after: bytes):
        """Append document metadata to the native timeline atomically."""
        before_data = bytes(before)
        after_data = bytes(after)
        before_buffer = ctypes.create_string_buffer(before_data) if before_data else None
        after_buffer = ctypes.create_string_buffer(after_data) if after_data else None
        before_ptr = ctypes.cast(before_buffer, ctypes.POINTER(ctypes.c_uint8)) if before_buffer else None
        after_ptr = ctypes.cast(after_buffer, ctypes.POINTER(ctypes.c_uint8)) if after_buffer else None
        truncated, discarded = ctypes.c_int(), ctypes.c_int()
        if not self._handle or not self._library.cs_history_cursor_append_state(
                self._handle, before_ptr, len(before_data), after_ptr, len(after_data),
                ctypes.byref(truncated), ctypes.byref(discarded)):
            return None
        return int(truncated.value), int(discarded.value)

    def state(self, index: int, side: int) -> bytes | None:
        if not self._handle:
            return None
        size = int(self._library.cs_history_cursor_state_size(
            self._handle, int(index), int(side)))
        if size <= 0 or size > 16 * 1024 * 1024:
            return None
        output = (ctypes.c_uint8 * size)()
        if not self._library.cs_history_cursor_copy_state(
                self._handle, int(index), int(side), output, size):
            return None
        return bytes(output)

    def discard_oldest(self, count: int) -> int:
        return int(self._library.cs_history_cursor_discard_oldest(
            self._handle, int(count))) if self._handle else 0

    def set_maximum(self, maximum_steps: int) -> int:
        return int(self._library.cs_history_cursor_set_maximum(
            self._handle, int(maximum_steps))) if self._handle else 0

    def undo(self) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_undo(self._handle))

    def redo(self) -> bool:
        return bool(self._handle and self._library.cs_history_cursor_redo(self._handle))

    def synchronize(self, step_count: int, index: int) -> None:
        if self._handle:
            self._library.cs_history_cursor_synchronize(
                self._handle, int(step_count), int(index))

    @property
    def count(self):
        return int(self._library.cs_history_cursor_count(self._handle)) if self._handle else 0

    @property
    def index(self):
        return int(self._library.cs_history_cursor_index(self._handle)) if self._handle else 0

    @property
    def maximum(self):
        return int(self._library.cs_history_cursor_maximum(self._handle)) if self._handle else 0


class NativeHistoryPayloadHandle:
    """C++-owned immutable tile images for an undo step."""

    def __init__(self, library):
        self._library = library
        self._handle = library.cs_history_payload_create()

    def __bool__(self):
        return bool(self._handle)

    def close(self):
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_history_payload_destroy(handle)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def append(self, before, after):
        view_type = self._library._cs_image_view_type
        retained = []
        def view(image):
            if image is None or image.isNull():
                return None
            pointer = qimage_pointer(image)
            retained.append(pointer)
            return view_type(pointer, image.width(), image.height(),
                             image.bytesPerLine(), image.format().value)
        old_view, new_view = view(before), view(after)
        old_ref = ctypes.byref(old_view) if old_view is not None else None
        new_ref = ctypes.byref(new_view) if new_view is not None else None
        return int(self._library.cs_history_payload_append(
            self._handle, old_ref, new_ref)) if self._handle else 0

    def append_many(self, items):
        if not self._handle:
            return None
        view_type = self._library._cs_image_view_type
        pair_type = self._library._cs_history_image_pair_type
        pixel_buffers, pairs = [], []

        def make_view(image):
            if image is None or image.isNull():
                return None
            pixels = qimage_pointer(image)
            pixel_buffers.append(pixels)
            return view_type(pixels, image.width(), image.height(),
                             image.bytesPerLine(), image.format().value)

        for before, after in items:
            before_view, after_view = make_view(before), make_view(after)
            pair = pair_type()
            if before_view is not None:
                pair.before = before_view
                pair.has_before = 1
            if after_view is not None:
                pair.after = after_view
                pair.has_after = 1
            pairs.append(pair)
        count = len(pairs)
        pair_array_type = pair_type * max(1, count)
        pair_array = pair_array_type(*pairs) if pairs else pair_array_type()
        indices = (ctypes.c_int * max(1, count))()
        if not self._library.cs_history_payload_append_many(
                self._handle, pair_array, count, indices, count):
            return None
        return list(indices[:count])

    def apply_to_stores(self, writes, side: int) -> bool:
        if not self._handle:
            return False
        write_type = self._library._cs_history_store_write_type
        entries = (write_type * max(1, len(writes)))(*[
            write_type(store._handle, int(index), int(tx), int(ty))
            for store, index, tx, ty in writes
        ])
        return bool(self._library.cs_history_payload_apply_to_tile_stores(
            self._handle, entries, len(writes), int(side)))

    def tile(self, index: int, side: int):
        from PySide6.QtGui import QImage
        present, width, height, image_format = (ctypes.c_int() for _ in range(4))
        if not self._handle or not self._library.cs_history_payload_tile_info(
                self._handle, int(index), int(side), ctypes.byref(present),
                ctypes.byref(width), ctypes.byref(height), ctypes.byref(image_format)):
            raise IndexError("Native history tile index is invalid")
        if not present.value:
            return None
        image = QImage(width.value, height.value, QImage.Format(image_format.value))
        if image.isNull() or not self._library.cs_history_payload_copy_tile(
                self._handle, int(index), int(side), qimage_pointer(image),
                image.width(), image.height(), image.bytesPerLine(), image.format().value):
            raise OSError("Could not copy native history tile")
        return image

    @property
    def count(self):
        return int(self._library.cs_history_payload_count(self._handle)) if self._handle else 0

    @property
    def allocated_bytes(self):
        return int(self._library.cs_history_payload_allocated_bytes(
            self._handle)) if self._handle else 0

    def clear(self):
        if self._handle:
            self._library.cs_history_payload_clear(self._handle)


def create_native_tile_store(width: int, height: int, tile_size: int):
    library = load_creative_core()
    if library is None:
        return None
    handle = NativeTileStoreHandle(library, width, height, tile_size)
    return handle if handle else None


def create_native_history_cursor(maximum_steps: int):
    library = load_creative_core()
    if library is None or not _configure_history_cursor(library):
        return None
    cursor = NativeHistoryCursorHandle(library, maximum_steps)
    return cursor if cursor else None


def create_native_history_payload():
    library = load_creative_core()
    if library is None or not _configure_history_payload(library):
        return None
    payload = NativeHistoryPayloadHandle(library)
    return payload if payload else None


def write_image_png(path, image) -> int:
    library = load_creative_core()
    if library is None:
        return 0
    return int(library.cs_image_write_png(str(path).encode("utf-8"), qimage_pointer(image),
        image.width(), image.height(), image.bytesPerLine(), image.format().value))


def lz4_compress_bytes(data: bytes):
    """Compress bytes in CreativeCore; return None when LZ4 is unavailable."""
    if not data:
        return None
    library = load_creative_core()
    if library is None or not _configure_lz4(library) or not library.cs_lz4_available():
        return None
    capacity = int(library.cs_lz4_compress_bound(len(data)))
    if capacity <= 0:
        return None
    source = ctypes.create_string_buffer(data, len(data))
    output = ctypes.create_string_buffer(capacity)
    written = ctypes.c_int()
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    if not library.cs_lz4_compress(ctypes.cast(source, byte_ptr), len(data),
                                   ctypes.cast(output, byte_ptr), capacity,
                                   ctypes.byref(written)):
        return None
    return output.raw[:written.value]


def lz4_decompress_bytes(data: bytes, expected_size: int):
    """Decompress a legacy LZ4 block; return None when the codec is unavailable."""
    if not data or expected_size <= 0:
        raise ValueError("invalid LZ4 tile size")
    library = load_creative_core()
    if library is None or not _configure_lz4(library) or not library.cs_lz4_available():
        return None
    source = ctypes.create_string_buffer(data, len(data))
    output = ctypes.create_string_buffer(int(expected_size))
    written = ctypes.c_int()
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    if not library.cs_lz4_decompress(ctypes.cast(source, byte_ptr), len(data),
            ctypes.cast(output, byte_ptr),
            int(expected_size), ctypes.byref(written)) or written.value != expected_size:
        raise ValueError("invalid LZ4 tile")
    return output.raw[:written.value]


def encode_cslz_bytes(rgba: bytes, width: int, height: int, stride: int):
    library = load_creative_core()
    if library is None or not _configure_lz4(library):
        return None
    raw_size = int(stride) * int(height)
    if (width <= 0 or height <= 0 or stride < width * 4 or raw_size != len(rgba)
            or raw_size > 16 * 1024 * 1024):
        raise ValueError("invalid CSLZ source dimensions")
    capacity = int(library.cs_cslz_max_encoded_size(raw_size))
    if capacity <= 0:
        raise ValueError("CSLZ source exceeds the codec limit")
    source = ctypes.create_string_buffer(rgba, len(rgba))
    output = ctypes.create_string_buffer(capacity)
    written = ctypes.c_int()
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    if not library.cs_cslz_encode(ctypes.cast(source, byte_ptr), int(width),
            int(height), int(stride), ctypes.cast(output, byte_ptr), capacity,
            ctypes.byref(written)):
        return None
    return output.raw[:written.value]


def decode_cslz_bytes(encoded: bytes, expected_size=None):
    """Validate and decode a complete legacy CSLZ record in CreativeCore."""
    library = load_creative_core()
    if library is None or not _configure_lz4(library):
        return None
    source = ctypes.create_string_buffer(encoded, len(encoded))
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    inputs = ctypes.cast(source, byte_ptr)
    width, height, stride, raw_size, compressed = (ctypes.c_int() for _ in range(5))
    if not library.cs_cslz_decode_info(inputs, len(encoded), ctypes.byref(width),
            ctypes.byref(height), ctypes.byref(stride), ctypes.byref(raw_size),
            ctypes.byref(compressed)):
        raise ValueError("invalid CSLZ record")
    if expected_size is not None and (width.value, height.value) != (
            int(expected_size.width()), int(expected_size.height())):
        raise ValueError("CSLZ dimensions do not match the expected tile")
    output = ctypes.create_string_buffer(raw_size.value)
    if not library.cs_cslz_decode(inputs, len(encoded),
            ctypes.cast(output, byte_ptr), raw_size.value):
        raise ValueError("invalid CSLZ pixel payload")
    return output.raw[:raw_size.value], width.value, height.value, stride.value, bool(compressed.value)


def _configure_transforms(library) -> None:
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_transform_layer.argtypes = [byte_ptr, byte_ptr,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        byte_ptr, ctypes.c_int, byte_ptr, ctypes.c_int,
        *([ctypes.c_float] * 5), ctypes.POINTER(ctypes.c_int)]
    library.cs_transform_layer.restype = ctypes.c_int
    library.cs_translate_image.argtypes = [byte_ptr, *([ctypes.c_int] * 4),
        byte_ptr, *([ctypes.c_int] * 3)]
    library.cs_translate_image.restype = ctypes.c_int


def _configure_gradients(library) -> None:
    library.cs_apply_linear_gradient.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), *([ctypes.c_int] * 4),
        *([ctypes.c_float] * 4), *([ctypes.c_int] * 4),
    ]
    library.cs_apply_linear_gradient.restype = ctypes.c_int


def _configure_canvas_api(library) -> None:
    """Declare the stroke and raster ABI once for every Qt-facing adapter."""
    handle = ctypes.c_void_p
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    int_ptr = ctypes.POINTER(ctypes.c_int)
    double_ptr = ctypes.POINTER(ctypes.c_double)
    library.cs_shape_path.argtypes = [ctypes.c_int, *([ctypes.c_double] * 4),
        double_ptr, ctypes.c_int, int_ptr]
    library.cs_shape_path.restype = ctypes.c_int
    library.cs_crop_rect.argtypes = [*([ctypes.c_int] * 8), *([int_ptr] * 4)]
    library.cs_crop_rect.restype = ctypes.c_int
    library.cs_crop_image.argtypes = [byte_ptr, *([ctypes.c_int] * 8), byte_ptr,
                                      ctypes.c_int, ctypes.c_int]
    library.cs_crop_image.restype = ctypes.c_int
    library.cs_copy_image_rect.argtypes = [byte_ptr, *([ctypes.c_int] * 6), byte_ptr,
                                           *([ctypes.c_int] * 8)]
    library.cs_copy_image_rect.restype = ctypes.c_int
    library.cs_draw_text.argtypes = [byte_ptr, *([ctypes.c_int] * 4), ctypes.c_char_p,
                                     ctypes.c_char_p, ctypes.c_double, ctypes.c_double,
                                     *([ctypes.c_int] * 4)]
    library.cs_draw_text.restype = ctypes.c_int
    library.cs_tile_range_for_rect.argtypes = [*([ctypes.c_int] * 7), *([int_ptr] * 4)]
    library.cs_tile_range_for_rect.restype = ctypes.c_int
    library.cs_brush_create.argtypes = []
    library.cs_brush_create.restype = handle
    library.cs_brush_destroy.argtypes = [handle]
    library.cs_brush_destroy.restype = None
    library.cs_brush_set_smoothing.argtypes = [handle, ctypes.c_float]
    library.cs_brush_set_smoothing.restype = None
    library.cs_brush_smooth_point.argtypes = [handle, ctypes.c_float, ctypes.c_float,
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
    library.cs_brush_smooth_point.restype = ctypes.c_int
    float_setters = (
        "cs_brush_set_size", "cs_brush_set_opacity", "cs_brush_set_flow",
        "cs_brush_set_hardness", "cs_brush_set_spacing", "cs_brush_set_roundness",
        "cs_brush_set_angle", "cs_brush_set_scatter", "cs_brush_set_size_jitter",
        "cs_brush_set_rotation_jitter", "cs_brush_set_velocity_size",
        "cs_brush_set_velocity_opacity", "cs_brush_set_velocity_flow",
        "cs_brush_set_texture_strength", "cs_brush_set_texture_scale",
        "cs_brush_set_texture_random_scale", "cs_brush_set_texture_random_offset",
        "cs_brush_set_texture_brightness", "cs_brush_set_texture_contrast",
        "cs_brush_set_hue_jitter", "cs_brush_set_saturation_jitter",
        "cs_brush_set_brightness_jitter", "cs_brush_set_gradient_amount",
        "cs_brush_set_paint_mix", "cs_brush_set_wetness", "cs_brush_set_pickup",
        "cs_brush_set_dilution", "cs_brush_set_smudge", "cs_brush_set_paint_persistence",
        "cs_brush_set_color_carry", "cs_brush_set_minimum_size",
        "cs_brush_set_minimum_opacity", "cs_brush_set_minimum_flow",
    )
    int_setters = (
        "cs_brush_set_eraser", "cs_brush_set_texture_mirror",
        "cs_brush_set_texture_affect_opacity", "cs_brush_set_dirty_color",
        "cs_brush_set_stroke_gradient", "cs_brush_set_linear_gradient",
        "cs_brush_set_radial_gradient", "cs_brush_set_wet_mix",
        "cs_brush_set_sample_canvas", "cs_brush_set_smudge_tool",
        "cs_brush_set_pressure_size", "cs_brush_set_pressure_opacity",
        "cs_brush_set_pressure_flow",
    )
    for name in float_setters:
        function = getattr(library, name)
        function.argtypes = [handle, ctypes.c_float]
        function.restype = None
    for name in int_setters:
        function = getattr(library, name)
        function.argtypes = [handle, ctypes.c_int]
        function.restype = None
    library.cs_brush_set_color.argtypes = [handle, *([ctypes.c_uint8] * 4)]
    library.cs_brush_set_color.restype = None
    library.cs_brush_set_gradient_color.argtypes = [handle, *([ctypes.c_uint8] * 4)]
    library.cs_brush_set_gradient_color.restype = None
    library.cs_brush_set_blend_mode.argtypes = [handle, ctypes.c_int]
    library.cs_brush_set_blend_mode.restype = None
    library.cs_brush_begin_stroke.argtypes = [handle, *([ctypes.c_float] * 3)]
    library.cs_brush_begin_stroke.restype = None
    library.cs_brush_draw_segment.argtypes = [
        handle, byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        *([ctypes.c_float] * 6),
    ]
    library.cs_brush_draw_segment_clone.argtypes = [
        handle, byte_ptr, byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, *([ctypes.c_float] * 10),
    ]
    library.cs_brush_draw_segment_clone.restype = None
    library.cs_brush_end_stroke.argtypes = [handle]
    library.cs_brush_end_stroke.restype = None

    library.cs_image_restore_alpha_rect.argtypes = [
        byte_ptr, byte_ptr, *([ctypes.c_int] * 8),
    ]
    library.cs_image_restore_alpha_rect.restype = None
    library.cs_image_restore_alpha_tile.argtypes = [
        byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        *([ctypes.c_int] * 6),
    ]
    library.cs_image_restore_alpha_tile.restype = ctypes.c_int
    optional = {
        "cs_filter_brush_segment": (
            [byte_ptr, *([ctypes.c_int] * 3), *([ctypes.c_float] * 9), ctypes.c_int],
            None,
        ),
        "cs_brush_set_texture_path": ([handle, ctypes.c_char_p], ctypes.c_int),
        "cs_brush_clear_texture": ([handle], None),
        "cs_brush_set_bitmap_tip_path": ([handle, ctypes.c_char_p], ctypes.c_int),
        "cs_brush_set_bitmap_tip_png": ([handle, byte_ptr, ctypes.c_uint64], ctypes.c_int),
        "cs_brush_clear_bitmap_tip": ([handle], None),
        "cs_brush_draw_segment_tilt": (
            [handle, byte_ptr, *([ctypes.c_int] * 3), *([ctypes.c_float] * 10)], None,
        ),
        "cs_fill": (
            [byte_ptr, *([ctypes.c_int] * 7), *([ctypes.c_uint8] * 4),
             int_ptr, int_ptr, int_ptr, int_ptr], ctypes.c_int,
        ),
        "cs_fill_bounds": (
            [byte_ptr, *([ctypes.c_int] * 7), int_ptr, int_ptr, int_ptr, int_ptr],
            ctypes.c_int,
        ),
        "cs_magic_wand": (
            [byte_ptr, *([ctypes.c_int] * 7), byte_ptr, ctypes.c_int], ctypes.c_int,
        ),
    }
    for name, (arguments, result) in optional.items():
        function = getattr(library, name, None)
        if function is not None:
            function.argtypes = arguments
            function.restype = result
    shape_mask = getattr(library, "cs_selection_shape_mask", None)
    if shape_mask is not None:
        shape_mask.argtypes = [
            byte_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ]
        shape_mask.restype = ctypes.c_int


def _configure_document_codecs(library) -> None:
    """Configure Nebula serialization and read-only Atlas import ABI."""
    handle = ctypes.c_void_p
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    library.cs_nebula_writer_create.argtypes = [
        ctypes.c_char_p, byte_ptr, ctypes.c_uint32, ctypes.c_uint32,
    ]
    library.cs_nebula_writer_create.restype = handle
    library.cs_nebula_writer_add_tile.argtypes = [
        handle, ctypes.c_uint32, byte_ptr, ctypes.c_uint64,
    ]
    library.cs_nebula_writer_add_tile.restype = ctypes.c_int
    library.cs_nebula_writer_finish.argtypes = [handle]
    library.cs_nebula_writer_finish.restype = ctypes.c_int
    library.cs_nebula_writer_cancel.argtypes = [handle]
    library.cs_nebula_writer_cancel.restype = None
    library.cs_nebula_reader_open.argtypes = [ctypes.c_char_p]
    library.cs_nebula_reader_open.restype = handle
    library.cs_nebula_reader_metadata_size.argtypes = [handle]
    library.cs_nebula_reader_metadata_size.restype = ctypes.c_uint32
    library.cs_nebula_reader_copy_metadata.argtypes = [
        handle, byte_ptr, ctypes.c_uint32,
    ]
    library.cs_nebula_reader_copy_metadata.restype = ctypes.c_int
    library.cs_nebula_reader_chunk_count.argtypes = [handle]
    library.cs_nebula_reader_chunk_count.restype = ctypes.c_uint32
    library.cs_nebula_reader_next_tile.argtypes = [
        handle, ctypes.POINTER(ctypes.c_uint32), byte_ptr, ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
    ]
    library.cs_nebula_reader_next_tile.restype = ctypes.c_int
    library.cs_nebula_reader_close.argtypes = [handle]
    library.cs_nebula_reader_close.restype = None
    library.cs_nebula_validate_manifest.argtypes = [byte_ptr,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    library.cs_nebula_validate_manifest.restype = ctypes.c_int

    u32_ptr = ctypes.POINTER(ctypes.c_uint32)
    library.cs_atlas_reader_open.argtypes = [ctypes.c_char_p]
    library.cs_atlas_reader_open.restype = handle
    library.cs_atlas_reader_document_info.argtypes = [
        handle, ctypes.c_char_p, ctypes.c_uint32,
        ctypes.c_char_p, ctypes.c_uint32,
        u32_ptr, u32_ptr, u32_ptr, u32_ptr,
        ctypes.c_char_p, ctypes.c_uint32,
    ]
    library.cs_atlas_reader_document_info.restype = ctypes.c_int
    library.cs_atlas_reader_layer_info.argtypes = [
        handle, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p, ctypes.c_uint32,
    ]
    library.cs_atlas_reader_layer_info.restype = ctypes.c_int
    library.cs_atlas_reader_copy_layer.argtypes = [
        handle, ctypes.c_uint32, byte_ptr, ctypes.c_uint64,
    ]
    library.cs_atlas_reader_copy_layer.restype = ctypes.c_int
    library.cs_atlas_reader_close.argtypes = [handle]
    library.cs_atlas_reader_close.restype = None


def _configure_layer_stack(library) -> None:
    int_ptr = ctypes.POINTER(ctypes.c_int)
    library.cs_layer_stack_move.argtypes = [
        int_ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        int_ptr, int_ptr,
    ]
    library.cs_layer_stack_move.restype = ctypes.c_int
    property_function = getattr(library, "cs_layer_property_update", None)
    if property_function is not None:
        property_function.argtypes = [ctypes.c_int, ctypes.c_double,
                                      ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
        property_function.restype = ctypes.c_int
    remove_function = getattr(library, "cs_layer_stack_remove", None)
    if remove_function is not None:
        remove_function.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, int_ptr, int_ptr,
        ]
        remove_function.restype = ctypes.c_int
    visible_merge_function = getattr(library, "cs_layer_stack_plan_visible_merge", None)
    if visible_merge_function is not None:
        visible_merge_function.argtypes = [int_ptr, ctypes.c_int, ctypes.c_int,
                                           int_ptr, int_ptr, int_ptr]
        visible_merge_function.restype = ctypes.c_int
    visible_group_merge_function = getattr(
        library, "cs_layer_stack_plan_visible_merge_groups", None)
    if visible_group_merge_function is not None:
        visible_group_merge_function.argtypes = [int_ptr, int_ptr, int_ptr,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, int_ptr, int_ptr, int_ptr, int_ptr]
        visible_group_merge_function.restype = ctypes.c_int
    group_function = getattr(library, "cs_layer_group_normalize", None)
    if group_function is not None:
        group_function.argtypes = [int_ptr, ctypes.c_int, int_ptr, ctypes.c_int,
                                   int_ptr, ctypes.c_int, int_ptr]
        group_function.restype = ctypes.c_int
    composite_runs_function = getattr(library, "cs_layer_stack_plan_composite_runs", None)
    if composite_runs_function is not None:
        composite_runs_function.argtypes = [int_ptr, ctypes.c_int, int_ptr, int_ptr,
                                            int_ptr, ctypes.c_int, int_ptr]
        composite_runs_function.restype = ctypes.c_int
    cleanup_function = getattr(library, "cs_layer_stack_plan_group_cleanup", None)
    if cleanup_function is not None:
        cleanup_function.argtypes = [int_ptr, int_ptr, ctypes.c_int, ctypes.c_int,
                                     int_ptr, int_ptr, ctypes.c_int]
        cleanup_function.restype = ctypes.c_int
    geometry_function = getattr(library, "cs_document_validate_geometry", None)
    if geometry_function is not None:
        geometry_function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_uint64]
        geometry_function.restype = ctypes.c_int


def configure_projection_api(library, native_layer_type, native_tile_type):
    """Declare the callback-driven projection ABI in the shared bridge."""
    callback_type = ctypes.CFUNCTYPE(
        None, ctypes.c_uint64, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
    )
    handle = ctypes.c_void_p
    library.cs_projection_start.argtypes = [callback_type, ctypes.c_void_p]
    library.cs_projection_start.restype = handle
    library.cs_projection_stop.argtypes = [handle]
    library.cs_projection_stop.restype = None
    library.cs_projection_set_callback.argtypes = [handle, callback_type, ctypes.c_void_p]
    library.cs_projection_set_callback.restype = None
    library.cs_projection_set_threads.argtypes = [handle, ctypes.c_int]
    library.cs_projection_set_threads.restype = None
    library.cs_projection_invalidate.argtypes = [
        handle, ctypes.c_uint64, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(native_layer_type), ctypes.c_int,
    ]
    library.cs_projection_invalidate.restype = ctypes.c_int
    batch_function = getattr(library, "cs_projection_invalidate_batch", None)
    if batch_function is not None:
        batch_function.argtypes = [handle, ctypes.POINTER(native_tile_type), ctypes.c_int]
        batch_function.restype = ctypes.c_int
    return callback_type, batch_function


_BLEND_MODE_IDS = {
    "normal": 0, "darken": 1, "multiply": 2, "color_burn": 3,
    "lighten": 4, "screen": 5, "color_dodge": 6, "overlay": 7,
    "soft_light": 8, "hard_light": 9, "difference": 10, "exclusion": 11,
}
_PARAMETER_MODE_IDS = {**_BLEND_MODE_IDS, "hue": 12, "saturation": 13,
                       "color": 14, "luminosity": 15}
_PARAMETER_KEYS = ("opacity", "opposite_mix", "intensity", "gamma", "mix_normal",
                   "pivot", "clamp", "softness", "hue_shift",
                   "saturation_boost", "offset")
_PARAMETER_DEFAULTS = (1.0, 0.0, 1.0, 1.0, 0.0, 0.5, 1.0, 0.5, 0.0, 1.0, 0.0)


def _configure_layer_composite(library) -> None:
    byte_ptr = ctypes.POINTER(ctypes.c_uint8)
    class CompositeLayer(ctypes.Structure):
        _fields_ = [("pixels", byte_ptr), ("stride", ctypes.c_int),
                    ("image_format", ctypes.c_int), ("opacity", ctypes.c_float),
                    ("mode", ctypes.c_int), ("visible", ctypes.c_int)]
    library._cs_composite_layer_type = CompositeLayer
    class AdvancedCompositeLayer(ctypes.Structure):
        _fields_ = [("pixels", byte_ptr), ("stride", ctypes.c_int),
                    ("opacity", ctypes.c_float), ("mode", ctypes.c_int),
                    ("visible", ctypes.c_int), ("clipping", ctypes.c_int),
                    ("parameters", ctypes.c_float * 11)]
    library._cs_advanced_composite_layer_type = AdvancedCompositeLayer
    library.cs_composite_layers_advanced.argtypes = [byte_ptr, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(AdvancedCompositeLayer), ctypes.c_int]
    library.cs_composite_layers_advanced.restype = ctypes.c_int
    library.cs_composite_layers.argtypes = [byte_ptr, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(CompositeLayer), ctypes.c_int]
    library.cs_composite_layers.restype = ctypes.c_int
    library.cs_composite_layer_in_place.argtypes = [
        byte_ptr, byte_ptr, *([ctypes.c_int] * 6), ctypes.c_float, ctypes.c_int,
    ]
    library.cs_composite_layer_in_place.restype = ctypes.c_int


def composite_layers_native(width: int, height: int, layers):
    """Composite standard blend layers in one native call; None means unsupported."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or width <= 0 or height <= 0:
        return None
    entries = []
    keepalive = []
    for layer in layers:
        if not layer.visible:
            entries.append((None, 0, 0, 0.0, 0, 0))
            continue
        image = layer.image
        if image.isNull() or image.width() != width or image.height() != height:
            return None
        mode = _BLEND_MODE_IDS.get(str(getattr(layer, "blend_mode", "normal")).lower())
        if mode is None:
            return None
        if image.format() not in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
            image = image.convertToFormat(QImage.Format.Format_ARGB32)
        if image.isNull():
            return None
        keepalive.append(image)
        entries.append((qimage_pointer(image), image.bytesPerLine(), image.format().value,
                        float(layer.opacity), mode, 1))
    composite_type = library._cs_composite_layer_type
    native_layers = (composite_type * len(entries))(*[
        composite_type(pointer, stride, image_format, opacity, mode, visible)
        for pointer, stride, image_format, opacity, mode, visible in entries
    ])
    output = QImage(width, height, QImage.Format.Format_ARGB32)
    if not library.cs_composite_layers(qimage_pointer(output), width, height,
            output.bytesPerLine(), output.format().value, native_layers, len(entries)):
        return None
    return output


def composite_layers_advanced(width: int, height: int, layers):
    """Composite parameterized and clipped layers in one CreativeCore call."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or width <= 0 or height <= 0:
        return None
    entries = []
    keepalive = []
    for layer in layers:
        if not layer.visible:
            entries.append((None, 0, 0.0, 0, 0, 0, _PARAMETER_DEFAULTS))
            continue
        image = layer.image
        if image.isNull() or image.width() != width or image.height() != height:
            return None
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        mode = _PARAMETER_MODE_IDS.get(str(getattr(layer, "blend_mode", "normal")).lower())
        if image.isNull() or mode is None:
            return None
        raw = getattr(layer, "blend_parameters", {}) or {}
        values = []
        for key, default in zip(_PARAMETER_KEYS, _PARAMETER_DEFAULTS):
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError, AttributeError):
                value = default
            values.append(value if math.isfinite(value) else default)
        keepalive.append(image)
        entries.append((qimage_pointer(image), image.bytesPerLine(), float(layer.opacity),
                        mode, 1, int(bool(getattr(layer, "clipping", False))), values))
    native_type = library._cs_advanced_composite_layer_type
    native_layers = (native_type * len(entries))(*[
        native_type(pointer, stride, opacity, mode, visible, clipping,
                    (ctypes.c_float * 11)(*parameters))
        for pointer, stride, opacity, mode, visible, clipping, parameters in entries
    ])
    output = QImage(width, height, QImage.Format.Format_ARGB32)
    if not library.cs_composite_layers_advanced(
            qimage_pointer(output), width, height, output.bytesPerLine(),
            native_layers, len(entries)):
        return None
    return output


def composite_layer_in_place(target, source, opacity: float, blend_mode: str):
    """Use CreativeCore for a single layer merge; return None if unavailable."""
    library = load_creative_core()
    mode = _BLEND_MODE_IDS.get(str(blend_mode or "normal").lower())
    if library is None or mode is None:
        return None
    return bool(library.cs_composite_layer_in_place(
        qimage_pointer(target), qimage_pointer(source), target.width(), target.height(),
        target.bytesPerLine(), source.bytesPerLine(), target.format().value,
        source.format().value, opacity, mode,
    ))


def restore_image_alpha_rect(destination, source, x: int, y: int,
                             width: int, height: int) -> bool:
    """Restore only alpha bytes from a same-sized QImage snapshot rectangle."""
    library = load_creative_core()
    if library is None or destination.size() != source.size():
        return False
    library.cs_image_restore_alpha_rect(
        qimage_pointer(destination), qimage_pointer(source),
        destination.width(), destination.height(), destination.bytesPerLine(),
        source.bytesPerLine(), int(x), int(y), int(width), int(height),
    )
    return True


def restore_image_alpha_tile(destination, source, dst_x: int, dst_y: int,
                             src_x: int, src_y: int, width: int, height: int) -> bool:
    """Restore alpha from a tile-sized snapshot into the matching document region."""
    library = load_creative_core()
    if library is None or destination.isNull() or source.isNull():
        return False
    return bool(library.cs_image_restore_alpha_tile(
        qimage_pointer(destination), destination.width(), destination.height(),
        destination.bytesPerLine(), qimage_pointer(source), source.width(),
        source.height(), source.bytesPerLine(), int(dst_x), int(dst_y),
        int(src_x), int(src_y), int(width), int(height)))


def filter_brush_segment(image, start_x: float, start_y: float,
                         start_pressure: float, end_x: float, end_y: float,
                         end_pressure: float, size: float, spacing: float,
                         opacity: float, sharpen: bool) -> bool | None:
    """Run the native local blur/sharpen dab path, or return None offline."""
    library = load_creative_core()
    function = getattr(library, "cs_filter_brush_segment", None) if library else None
    if function is None:
        return None
    function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        float(start_x), float(start_y), float(start_pressure),
        float(end_x), float(end_y), float(end_pressure), float(size),
        float(spacing), float(opacity), int(bool(sharpen)),
    )
    return True


def native_flood_fill(image, x: int, y: int, tolerance: int, color,
                      library=None):
    """Run CreativeCore's connected fill; return its bounds or None offline."""
    from PySide6.QtGui import QImage

    function = getattr(library, "cs_fill", None) if library else None
    if (function is None or image.format() not in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)):
        return None
    bounds = [ctypes.c_int() for _ in range(4)]
    if not function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, int(x), int(y), int(tolerance), color.red(),
        color.green(), color.blue(), color.alpha(),
        *(ctypes.byref(value) for value in bounds),
    ):
        return (0, 0, 0, 0)
    return tuple(value.value for value in bounds)


def native_flood_fill_bounds(image, x: int, y: int, tolerance: int, library=None):
    """Return the connected fill's bounds without modifying its image."""
    from PySide6.QtGui import QImage

    function = getattr(library or load_creative_core(), "cs_fill_bounds", None)
    if (function is None or image.format() not in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)):
        return None
    bounds = [ctypes.c_int() for _ in range(4)]
    if not function(qimage_pointer(image), image.width(), image.height(),
                    image.bytesPerLine(), image.format().value, int(x), int(y),
                    int(tolerance), *(ctypes.byref(value) for value in bounds)):
        return None
    return tuple(value.value for value in bounds)


def native_magic_wand(image, x: int, y: int, tolerance: int, mask,
                      library=None) -> bool | None:
    """Fill a preallocated selection mask with CreativeCore, or return None."""
    from PySide6.QtGui import QImage

    function = getattr(library, "cs_magic_wand", None) if library else None
    if (function is None or image.format() not in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888)):
        return None
    return bool(function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, int(x), int(y), int(tolerance),
        qimage_pointer(mask), mask.bytesPerLine(),
    ))


_SELECTION_OPERATION_IDS = {"replace": 0, "add": 1, "subtract": 2, "intersect": 3}


def native_selection_combine(destination, candidate, operation: str) -> bool | None:
    """Combine same-sized ARGB32 selection masks through CreativeCore."""
    from PySide6.QtGui import QImage

    operation = getattr(operation, "value", operation)
    library = load_creative_core()
    if (library is None or str(operation) not in _SELECTION_OPERATION_IDS
            or destination.size() != candidate.size()
            or destination.format() != QImage.Format.Format_ARGB32
            or candidate.format() != QImage.Format.Format_ARGB32):
        return None
    return bool(library.cs_selection_combine(
        qimage_pointer(destination), qimage_pointer(candidate),
        destination.width(), destination.height(), destination.bytesPerLine(),
        candidate.bytesPerLine(), _SELECTION_OPERATION_IDS[str(operation)],
    ))


def native_selection_invert(image) -> bool | None:
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or image.format() != QImage.Format.Format_ARGB32:
        return None
    return bool(library.cs_selection_invert(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
    ))


def native_selection_bounds(image):
    """Return (x, y, width, height), including zero bounds when empty."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or image.format() != QImage.Format.Format_ARGB32:
        return None
    values = [ctypes.c_int() for _ in range(4)]
    if not library.cs_selection_bounds(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        *(ctypes.byref(value) for value in values),
    ):
        return None
    return tuple(value.value for value in values)


def native_selection_contains(image, x: int, y: int) -> bool | None:
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or image.format() != QImage.Format.Format_ARGB32:
        return None
    selected = ctypes.c_int()
    if not library.cs_selection_contains(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        int(x), int(y), ctypes.byref(selected),
    ):
        return None
    return bool(selected.value)


def native_selection_shape_mask(mask, shape: str, points) -> bool | None:
    """Rasterize selection geometry in CreativeCore; return None offline."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    function = getattr(library, "cs_selection_shape_mask", None) if library else None
    shape_id = {"select_rectangle": 0, "select_ellipse": 1, "lasso": 2}.get(shape)
    if (function is None or shape_id is None
            or mask.format() != QImage.Format.Format_ARGB32):
        return None
    coordinates = array("f")
    for point in points:
        coordinates.append(float(point.x()))
        coordinates.append(float(point.y()))
    point_count = len(coordinates) // 2
    native_points = (ctypes.cast(
        ctypes.addressof(ctypes.c_char.from_buffer(coordinates)),
        ctypes.POINTER(ctypes.c_float),
    ) if coordinates else None)
    return bool(function(
        qimage_pointer(mask), mask.width(), mask.height(), mask.bytesPerLine(),
        shape_id, native_points, point_count,
    ))


def read_atlas_project(path: str | Path):
    """Decode a bounded Atlas document through CreativeCore, or return None."""
    library = load_creative_core()
    if library is None:
        return None
    reader = library.cs_atlas_reader_open(str(path).encode("utf-8"))
    if not reader:
        return None
    try:
        name = ctypes.create_string_buffer(1 << 20)
        author = ctypes.create_string_buffer(1 << 20)
        background = ctypes.create_string_buffer(1 << 20)
        width, height, dpi, count = (ctypes.c_uint32() for _ in range(4))
        if not library.cs_atlas_reader_document_info(
            reader, name, len(name), author, len(author), ctypes.byref(width),
            ctypes.byref(height), ctypes.byref(dpi), ctypes.byref(count),
            background, len(background),
        ):
            return None
        w, h, layer_count = int(width.value), int(height.value), int(count.value)
        pixels_per_layer = w * h
        rgba_bytes = pixels_per_layer * 4
        if (w <= 0 or h <= 0 or w > 100_000 or h > 100_000
                or pixels_per_layer > 64 * 1024 * 1024
                or layer_count <= 0 or layer_count > 100_000
                or rgba_bytes * layer_count > 512 * 1024 * 1024):
            return None

        layers = []
        buffer_type = ctypes.c_uint8 * rgba_bytes
        for index in range(layer_count):
            layer_name = ctypes.create_string_buffer(1 << 20)
            blend = ctypes.create_string_buffer(1 << 20)
            opacity = ctypes.c_float()
            visible = ctypes.c_int()
            if not library.cs_atlas_reader_layer_info(
                reader, index, layer_name, len(layer_name), ctypes.byref(opacity),
                ctypes.byref(visible), blend, len(blend),
            ):
                return None
            pixels = buffer_type()
            if not library.cs_atlas_reader_copy_layer(reader, index, pixels, rgba_bytes):
                return None
            layers.append({
                "name": layer_name.value.decode("utf-8", "replace"),
                "blend": blend.value.decode("utf-8", "replace"),
                "opacity": float(opacity.value),
                "visible": bool(visible.value),
                "pixels": ctypes.string_at(pixels, rgba_bytes),
            })
        return {
            "name": name.value.decode("utf-8", "replace"),
            "author": author.value.decode("utf-8", "replace"),
            "background": background.value.decode("utf-8", "replace"),
            "width": w, "height": h, "dpi": int(dpi.value), "layers": layers,
        }
    finally:
        library.cs_atlas_reader_close(reader)


class NebulaWriterHandle:
    """Scoped native Nebula writer; keeps raw ABI details in this bridge."""

    def __init__(self, library, handle) -> None:
        self._library = library
        self._handle = handle
        self._tile_buffer = None
        self._tile_buffer_capacity = 0

    def add_tile(self, chunk_id: int, raw: bytes) -> bool:
        if not self._handle or not raw:
            return False
        if self._tile_buffer_capacity < len(raw):
            self._tile_buffer = (ctypes.c_uint8 * len(raw))()
            self._tile_buffer_capacity = len(raw)
        ctypes.memmove(self._tile_buffer, raw, len(raw))
        byte_ptr = ctypes.cast(self._tile_buffer, ctypes.POINTER(ctypes.c_uint8))
        return bool(self._library.cs_nebula_writer_add_tile(
            self._handle, int(chunk_id), byte_ptr, len(raw),
        ))

    def finish(self) -> bool:
        if not self._handle:
            return False
        handle, self._handle = self._handle, None
        return bool(self._library.cs_nebula_writer_finish(handle))

    def cancel(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_nebula_writer_cancel(handle)


class NebulaReaderHandle:
    """Scoped native Nebula reader that returns owned Python byte buffers."""

    def __init__(self, library, handle) -> None:
        self._library = library
        self._handle = handle
        self._tile_buffer = None
        self._tile_buffer_capacity = 0

    def metadata(self, maximum_bytes: int) -> bytes | None:
        if not self._handle:
            return None
        size = int(self._library.cs_nebula_reader_metadata_size(self._handle))
        if not 0 < size <= int(maximum_bytes):
            return None
        buffer = (ctypes.c_uint8 * size)()
        if not self._library.cs_nebula_reader_copy_metadata(
            self._handle, buffer, size,
        ):
            return None
        return bytes(buffer)

    def chunk_count(self) -> int:
        if not self._handle:
            return 0
        return int(self._library.cs_nebula_reader_chunk_count(self._handle))

    def next_tile(self, maximum_bytes: int):
        if not self._handle or maximum_bytes <= 0:
            return None
        chunk_id, raw_size = ctypes.c_uint32(), ctypes.c_uint64()
        if self._tile_buffer_capacity < int(maximum_bytes):
            self._tile_buffer = (ctypes.c_uint8 * int(maximum_bytes))()
            self._tile_buffer_capacity = int(maximum_bytes)
        buffer = self._tile_buffer
        status = self._library.cs_nebula_reader_next_tile(
            self._handle, ctypes.byref(chunk_id), buffer, int(maximum_bytes),
            ctypes.byref(raw_size),
        )
        if status != 1 or raw_size.value > maximum_bytes:
            return None
        return int(chunk_id.value), bytes(buffer[:raw_size.value])

    def close(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            self._library.cs_nebula_reader_close(handle)


def create_nebula_writer(path: str | Path, metadata: bytes, chunk_count: int):
    library = load_creative_core()
    if library is None or not metadata or chunk_count < 0:
        return None
    buffer = ctypes.create_string_buffer(metadata)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8))
    handle = library.cs_nebula_writer_create(
        str(path).encode("utf-8"), pointer, len(metadata), int(chunk_count),
    )
    return NebulaWriterHandle(library, handle) if handle else None


def open_nebula_reader(path: str | Path):
    library = load_creative_core()
    if library is None:
        return None
    handle = library.cs_nebula_reader_open(str(path).encode("utf-8"))
    return NebulaReaderHandle(library, handle) if handle else None


def validate_nebula_manifest(metadata: bytes, chunk_count: int):
    """Validate a complete Nebula manifest and return its canvas geometry."""
    library = load_creative_core()
    if library is None:
        return None
    _configure_document_codecs(library)
    data = bytes(metadata)
    if not data or len(data) > 64 * 1024 * 1024:
        return False
    source = ctypes.create_string_buffer(data, len(data))
    width, height, dpi = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    if not library.cs_nebula_validate_manifest(
            ctypes.cast(source, ctypes.POINTER(ctypes.c_uint8)), len(data),
            int(chunk_count), ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(dpi)):
        return False
    return width.value, height.value, dpi.value


def apply_linear_gradient_native(image, start_x: float, start_y: float,
                                 end_x: float, end_y: float, color) -> bool | None:
    """Apply the native raster gradient, returning None if CreativeCore is absent."""
    library = load_creative_core()
    if library is None:
        return None
    return bool(library.cs_apply_linear_gradient(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, float(start_x), float(start_y), float(end_x),
        float(end_y), color.red(), color.green(), color.blue(), color.alpha(),
    ))


def native_shape_path(shape: str, start_x: float, start_y: float,
                      end_x: float, end_y: float):
    """Generate a line/rectangle/ellipse path in CreativeCore, or None offline."""
    shape_id = {"line": 0, "rectangle": 1, "ellipse": 2}.get(shape)
    library = load_creative_core()
    function = getattr(library, "cs_shape_path", None) if library else None
    if shape_id is None or function is None:
        return None
    capacity = 722
    output = (ctypes.c_double * (capacity * 2))()
    count = ctypes.c_int()
    if not function(shape_id, float(start_x), float(start_y),
                    float(end_x), float(end_y), output, capacity,
                    ctypes.byref(count)):
        return None
    return [(output[index * 2], output[index * 2 + 1])
            for index in range(count.value)]


def native_crop_rect(start_x: int, start_y: int, end_x: int, end_y: int,
                     bounds_x: int, bounds_y: int, bounds_width: int,
                     bounds_height: int):
    """Return the clipped inclusive crop bounds, or None if CreativeCore is absent."""
    library = load_creative_core()
    function = getattr(library, "cs_crop_rect", None) if library else None
    if function is None:
        return None
    output = [ctypes.c_int() for _ in range(4)]
    if not function(start_x, start_y, end_x, end_y, bounds_x, bounds_y,
                    bounds_width, bounds_height, *(ctypes.byref(v) for v in output)):
        return None
    return tuple(value.value for value in output)


def crop_image_native(image, rect, output_format=None):
    """Crop pixels in CreativeCore and return a new QImage, or None offline."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    function = getattr(library, "cs_crop_image", None) if library else None
    if function is None or image.isNull() or rect.isEmpty():
        return None
    output = QImage(rect.width(), rect.height(),
                    image.format() if output_format is None else output_format)
    if output.isNull():
        return None
    if not function(qimage_pointer(image), image.width(), image.height(),
                    image.bytesPerLine(), image.format().value,
                    rect.x(), rect.y(), rect.width(), rect.height(),
                    qimage_pointer(output), output.bytesPerLine(),
                    output.format().value):
        return None
    return output


def copy_image_rect_native(source, destination, source_rect, destination_x: int,
                           destination_y: int) -> bool | None:
    """Copy a Qt image region through CreativeCore, or return None offline."""
    library = load_creative_core()
    function = getattr(library, "cs_copy_image_rect", None) if library else None
    if function is None or source.isNull() or destination.isNull() or source_rect.isEmpty():
        return None
    return bool(function(
        qimage_pointer(source), source.width(), source.height(), source.bytesPerLine(),
        source.format().value, source_rect.x(), source_rect.y(),
        qimage_pointer(destination), destination.width(), destination.height(),
        destination.bytesPerLine(), destination.format().value,
        int(destination_x), int(destination_y), source_rect.width(), source_rect.height(),
    ))


def fill_image_native(image, color) -> bool | None:
    """Fill a Qt image through CreativeCore, or return None offline."""
    library = load_creative_core()
    function = getattr(library, "cs_image_fill", None) if library else None
    if function is None or image.isNull():
        return None
    return bool(function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, color.red(), color.green(), color.blue(), color.alpha(),
    ))


def fill_image_rect_native(image, rect, color) -> bool | None:
    """Fill a clipped image rectangle through CreativeCore."""
    library = load_creative_core()
    function = getattr(library, "cs_image_fill_rect", None) if library else None
    if function is None or image.isNull():
        return None
    return bool(function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, int(rect.x()), int(rect.y()), int(rect.width()),
        int(rect.height()), color.red(), color.green(), color.blue(), color.alpha(),
    ))


def render_brush_preset_art_native(texture, preview, hardness: float, size: float,
                                   color) -> bool | None:
    """Render preset tip/preview art in CreativeCore."""
    library = load_creative_core()
    function = getattr(library, "cs_render_brush_preset_art", None) if library else None
    if function is None or texture.isNull() or preview.isNull():
        return None
    return bool(function(
        qimage_pointer(texture), texture.width(), texture.height(),
        texture.bytesPerLine(), texture.format().value, qimage_pointer(preview),
        preview.width(), preview.height(), preview.bytesPerLine(), preview.format().value,
        float(hardness), float(size), color.red(), color.green(), color.blue(), color.alpha(),
    ))


def apply_alpha_mask_native(image, mask) -> bool | None:
    """Multiply image alpha by a same-sized native mask."""
    library = load_creative_core()
    function = getattr(library, "cs_apply_alpha_mask", None) if library else None
    if function is None or image.isNull() or mask.isNull():
        return None
    return bool(function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, qimage_pointer(mask), mask.width(), mask.height(),
        mask.bytesPerLine(), mask.format().value,
    ))


def clone_image_native(image):
    """Clone a supported QImage through CreativeCore, or return None offline."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    if image.isNull():
        return QImage()
    clone = QImage(image.size(), image.format())
    if clone.isNull():
        return None
    if not copy_image_rect_native(image, clone, QRect(image.rect()), 0, 0):
        return None
    return clone


def draw_text_native(image, text: str, font, x: float, y: float, color) -> bool | None:
    """Draw a document text object through CreativeCore, or return None offline."""
    library = load_creative_core()
    function = getattr(library, "cs_draw_text", None) if library else None
    if function is None or image.isNull():
        return None
    text_bytes = str(text).encode("utf-8")
    font_bytes = font.toString().encode("utf-8")
    return bool(function(
        qimage_pointer(image), image.width(), image.height(), image.bytesPerLine(),
        image.format().value, text_bytes, font_bytes, float(x), float(y),
        color.red(), color.green(), color.blue(), color.alpha(),
    ))


def native_tile_range_for_rect(canvas_width: int, canvas_height: int, tile_size: int,
                               rect_x: int, rect_y: int, rect_width: int,
                               rect_height: int):
    """Return the native half-open tile range intersecting a canvas rectangle."""
    library = load_creative_core()
    function = getattr(library, "cs_tile_range_for_rect", None) if library else None
    if function is None:
        return None
    output = [ctypes.c_int() for _ in range(4)]
    if not function(canvas_width, canvas_height, tile_size,
                    rect_x, rect_y, rect_width, rect_height,
                    *(ctypes.byref(value) for value in output)):
        return None
    return tuple(value.value for value in output)


def transform_raster_native(image, selection_image, translate_x: float,
                            translate_y: float, scale_x: float, scale_y: float,
                            rotation: float):
    """Run CreativeCore's affine image/mask transform; return None offline."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None:
        return None
    source = image if image.format() in (
        QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888
    ) else image.convertToFormat(QImage.Format.Format_ARGB32)
    output = QImage(image.size(), QImage.Format.Format_ARGB32)
    output_selection = (QImage(image.size(), QImage.Format.Format_ARGB32)
                        if selection_image is not None else None)
    used_selection = ctypes.c_int()
    ok = library.cs_transform_layer(
        qimage_pointer(source),
        qimage_pointer(selection_image) if selection_image is not None else None,
        image.width(), image.height(), source.bytesPerLine(),
        selection_image.bytesPerLine() if selection_image is not None else 0,
        source.format().value, qimage_pointer(output), output.bytesPerLine(),
        qimage_pointer(output_selection) if output_selection is not None else None,
        output_selection.bytesPerLine() if output_selection is not None else 0,
        float(translate_x), float(translate_y), float(scale_x), float(scale_y),
        float(rotation), ctypes.byref(used_selection),
    )
    if not ok:
        return None
    return output, output_selection if used_selection.value else None


def translate_image_native(image, dx: int, dy: int):
    """Translate an image by integer pixels using clipped native row copies."""
    from PySide6.QtGui import QImage

    library = load_creative_core()
    if library is None or image.isNull() or image.format() not in (
            QImage.Format.Format_ARGB32, QImage.Format.Format_RGBA8888):
        return None
    output = QImage(image.size(), image.format())
    if not library.cs_translate_image(qimage_pointer(image), image.width(), image.height(),
            image.bytesPerLine(), image.format().value, qimage_pointer(output),
            output.bytesPerLine(), int(dx), int(dy)):
        return None
    return output


def move_layer_stack(group_ids, active_index: int, direction: int):
    """Return the native output permutation and active index, or None offline."""
    library = load_creative_core()
    if library is None:
        return None
    count = len(group_ids)
    if not count:
        return False
    int_array = ctypes.c_int * count
    inputs = int_array(*(int(value) for value in group_ids))
    output = int_array()
    active_after = ctypes.c_int(-1)
    if not library.cs_layer_stack_move(
        inputs, count, int(active_index), int(direction),
        output, ctypes.byref(active_after),
    ):
        return False
    return list(output), active_after.value


def remove_layer_stack(layer_count: int, remove_index: int, active_index: int):
    """Return the native post-removal permutation, or None if unavailable."""
    library = load_creative_core()
    function = getattr(library, "cs_layer_stack_remove", None) if library else None
    if function is None:
        return None
    if layer_count <= 1:
        return False
    output = (ctypes.c_int * (layer_count - 1))()
    active_after = ctypes.c_int(-1)
    if not function(layer_count, int(remove_index), int(active_index), output,
                    ctypes.byref(active_after)):
        return False
    return list(output), active_after.value


def plan_visible_layer_merge(effective_visibility, active_index: int):
    """Return visible-merge survivor mask, target and new active index."""
    visibility = [int(bool(value)) for value in effective_visibility]
    if not visibility:
        return False
    library = load_creative_core()
    function = (getattr(library, "cs_layer_stack_plan_visible_merge", None)
                if library else None)
    if function is None:
        return None
    count = len(visibility)
    inputs = (ctypes.c_int * count)(*visibility)
    keep = (ctypes.c_int * count)()
    target = ctypes.c_int(-1)
    active_after = ctypes.c_int(-1)
    if not function(inputs, count, int(active_index), keep,
                    ctypes.byref(target), ctypes.byref(active_after)):
        return False
    return list(keep), target.value, active_after.value


def plan_visible_layer_merge_groups(layer_visibility, group_membership,
                                   group_visibility, active_index: int):
    """Plan effective group visibility and visible merge in CreativeCore."""
    library = load_creative_core()
    function = (getattr(library, "cs_layer_stack_plan_visible_merge_groups", None)
                if library else None)
    if function is None:
        return None
    layers = [int(bool(value)) for value in layer_visibility]
    memberships = [int(value) for value in group_membership]
    groups = [int(bool(value)) for value in group_visibility]
    if not layers or len(layers) != len(memberships):
        return False
    layer_count, group_count = len(layers), len(groups)
    int_array = ctypes.c_int * max(1, layer_count, group_count)
    layer_values = int_array(*layers)
    membership_values = int_array(*memberships)
    group_values = int_array(*groups)
    effective, keep = int_array(), int_array()
    target, active_after = ctypes.c_int(-1), ctypes.c_int(-1)
    if not function(layer_values, membership_values, group_values, layer_count,
                    group_count, int(active_index), effective, keep,
                    ctypes.byref(target), ctypes.byref(active_after)):
        return False
    return (list(effective[:layer_count]), list(keep[:layer_count]),
            target.value, active_after.value)


def update_layer_property(property_id: int, current_value: float,
                          requested_value: float = 0.0):
    """Apply CreativeCore's layer-property toggle/clamp rule, or return None."""
    library = load_creative_core()
    function = getattr(library, "cs_layer_property_update", None) if library else None
    if function is None:
        return None
    output = ctypes.c_double()
    if not function(int(property_id), float(current_value), float(requested_value),
                    ctypes.byref(output)):
        return False
    return output.value


def normalize_layer_group(requested_indices, grouped_layers):
    """Normalize and validate a group selection in CreativeCore, or return None offline."""
    library = load_creative_core()
    function = getattr(library, "cs_layer_group_normalize", None) if library else None
    if function is None:
        return None
    layer_count = len(grouped_layers)
    requested = list(requested_indices)
    output_capacity = max(1, len(requested))
    int_array = ctypes.c_int * output_capacity
    inputs = int_array(*(int(value) for value in requested))
    grouped = (ctypes.c_int * max(1, layer_count))(
        *(int(bool(value)) for value in grouped_layers))
    output = int_array()
    output_count = ctypes.c_int()
    if not function(inputs, len(requested), grouped, layer_count, output,
                    output_capacity, ctypes.byref(output_count)):
        return False
    return list(output[:output_count.value])


def plan_layer_composite_runs(group_ids):
    """Plan ordered document layer/group runs in CreativeCore; None if unavailable."""
    library = load_creative_core()
    function = (getattr(library, "cs_layer_stack_plan_composite_runs", None)
                if library else None)
    if function is None:
        return None
    count = len(group_ids)
    if count <= 0:
        return False
    int_array = ctypes.c_int * count
    groups = int_array(*(int(value) for value in group_ids))
    starts, ends, run_groups = int_array(), int_array(), int_array()
    run_count = ctypes.c_int()
    if not function(groups, count, starts, ends, run_groups, count,
                    ctypes.byref(run_count)):
        return False
    return list(zip(starts[:run_count.value], ends[:run_count.value],
                     run_groups[:run_count.value]))


def plan_layer_group_cleanup(layer_group_ids, keep_layers, group_count):
    """Plan structural group cleanup in CreativeCore after layer mutation."""
    library = load_creative_core()
    function = (getattr(library, "cs_layer_stack_plan_group_cleanup", None)
                if library else None)
    if function is None:
        return None
    if len(layer_group_ids) != len(keep_layers):
        return False
    count = len(layer_group_ids)
    if count <= 0 or group_count < 0:
        return False
    int_array = ctypes.c_int * max(1, count, group_count)
    memberships = int_array(*(int(value) for value in layer_group_ids))
    keep = int_array(*(int(bool(value)) for value in keep_layers))
    kept_groups = int_array()
    surviving = int_array()
    surviving_count = function(memberships, keep, count, int(group_count),
                                kept_groups, surviving, count)
    if surviving_count < 0:
        return False
    return (list(kept_groups[:group_count]), list(surviving[:surviving_count]))


def validate_document_geometry(width: int, height: int, dpi: int,
                               maximum_dimension: int = 100000,
                               maximum_pixels: int = 64 * 1024 * 1024):
    """Validate document dimensions before any dense UI image allocation."""
    library = load_creative_core()
    function = getattr(library, "cs_document_validate_geometry", None) if library else None
    if function is None:
        return None
    return bool(function(int(width), int(height), int(dpi), int(maximum_dimension),
                         int(maximum_pixels)))


def create_native_document_state(width: int, height: int, dpi: int):
    """Create the native structural document model for a Qt document."""
    library = load_creative_core()
    if library is None:
        return None
    state = NativeDocumentStateHandle(library, width, height, dpi)
    return state if state else None


def qimage_pointer(image):
    """Expose a writable QImage buffer for the duration of one ABI call."""
    bits = image.bits()
    return ctypes.cast(ctypes.addressof(ctypes.c_char.from_buffer(bits)),
                       ctypes.POINTER(ctypes.c_uint8))
