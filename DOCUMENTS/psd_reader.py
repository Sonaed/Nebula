"""Standalone Photoshop (.psd / .psb) reader.

Pure Python + NumPy: Nebula no longer needs psd-tools to open layered PSDs.
The reader decodes the structure Photoshop writes and keeps it editable:

* raster layers (RGB / Grayscale / CMYK, 8, 16 and 32 bits, raw, RLE, ZIP and
  ZIP-with-prediction channels, PSD and PSB);
* folders (open/closed, nested, pass-through), visibility, opacity and *fill*
  opacity (``iOpa``), clipping masks, transparency lock, colour labels;
* pixel layer masks with their default colour, disabled / inverted flags and the
  "real" user mask of layers that also carry a vector mask;
* adjustment layers - Gradient Map (``grdm``), Color Lookup / 3D LUT
  (``clrL``), Curves, Levels, Hue/Saturation, Brightness/Contrast, Exposure,
  Vibrance, Color Balance, Selective Color, Invert, Posterize, Threshold - and
  Solid Color fill layers;
* the flattened composite and the embedded ICC profile.

Everything is decoded into plain data (``numpy`` arrays, dicts).  Building the
Nebula document from it is ``DOCUMENTS.format_psd``'s job, so this module can
be tested and reused without Qt.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import mmap
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from DOCUMENTS.psd_descriptor import DescriptorError, parse_versioned_descriptor

SECTION_NONE, SECTION_OPEN, SECTION_CLOSED, SECTION_END = 0, 1, 2, 3
_BIG_KEYS_PSB = {b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn",
                 b"Alph", b"FMsk", b"lnk2", b"FEid", b"FXid", b"PxSD"}
ADJUSTMENT_KEYS = {b"grdm", b"clrL", b"curv", b"levl", b"hue2", b"hue ", b"brit",
                   b"expA", b"vibA", b"blnc", b"selc", b"nvrt", b"post", b"thrs",
                   b"phfl", b"mixr", b"blwh", b"CgEd"}
FILL_KEYS = {b"SoCo", b"GdFl", b"PtFl"}
LABEL_COLORS = {1: "red", 2: "orange", 3: "yellow", 4: "green", 5: "blue", 6: "violet",
                7: "gray"}


class PSDError(ValueError):
    """The file is not a PSD this reader can decode."""


@dataclass
class PSDMask:
    left: int
    top: int
    right: int
    bottom: int
    default_color: int = 255
    disabled: bool = False
    invert: bool = False
    data: np.ndarray | None = None      # uint8 (bottom-top, right-left)

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass
class PSDLayer:
    name: str
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    blend_key: str = "norm"
    opacity: int = 255
    fill_opacity: int = 255
    clipping: bool = False
    hidden: bool = False
    transparency_locked: bool = False
    section: int = SECTION_NONE
    section_blend_key: str | None = None
    rgba: np.ndarray | None = None       # uint8 (h, w, 4), straight alpha
    mask: PSDMask | None = None
    adjustment: dict | None = None
    fill: dict | None = None
    has_vector_mask: bool = False
    effects: list[dict] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    layer_id: int | None = None
    label_color: str | None = None
    tagged_keys: list[str] = field(default_factory=list)
    children: list["PSDLayer"] = field(default_factory=list)   # bottom -> top
    parent: "PSDLayer | None" = field(default=None, repr=False)

    _pixel_loader: object = field(default=None, repr=False, compare=False)

    def decode_pixels(self) -> None:
        """Materialize this layer only; metadata and hierarchy are already available."""
        if self._pixel_loader is not None:
            loader = self._pixel_loader
            loader()
            self._pixel_loader = None

    def release_pixels(self) -> None:
        self.rgba = None
        if self.mask is not None:
            self.mask.data = None

    @property
    def is_group(self) -> bool:
        return self.section in (SECTION_OPEN, SECTION_CLOSED)

    @property
    def kind(self) -> str:
        if self.is_group:
            return "group"
        if self.adjustment is not None:
            return "adjustment"
        if self.fill is not None:
            return "fill"
        return "pixel"

    @property
    def visible(self) -> bool:
        return not self.hidden

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def effective_blend_key(self) -> str:
        return self.section_blend_key or self.blend_key if self.is_group else self.blend_key


@dataclass
class PSDFile:
    width: int
    height: int
    depth: int
    color_mode: int
    version: int
    layers: list[PSDLayer]            # flat, bottom -> top, markers removed
    root: list[PSDLayer]              # tree, bottom -> top
    icc_profile: bytes = b""
    composite: np.ndarray | None = None   # uint8 (h, w, 4)
    warnings: list[str] = field(default_factory=list)

    _mapped_source: object = field(default=None, repr=False, compare=False)
    _composite_offset: int = field(default=0, repr=False, compare=False)
    _channel_count: int = field(default=4, repr=False, compare=False)

    def close(self) -> None:
        for layer in self.descendants():
            layer._pixel_loader = None
        if self._mapped_source is not None:
            self._mapped_source.close()
            self._mapped_source = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def descendants(self):
        def walk(items):
            for item in items:
                yield item
                if item.is_group:
                    yield from walk(item.children)
        yield from walk(self.root)


# --------------------------------------------------------------------------
# Low-level decoding
# --------------------------------------------------------------------------

def _native_unpackbits():
    """``cs_psd_unpackbits`` from CreativeCore when the bridge exports it."""
    try:
        from CORE.native_bridge import load_creative_core
        library = load_creative_core()
    except Exception:  # noqa: BLE001 - Qt/bridge absent: pure fallback
        return None
    function = getattr(library, "cs_psd_unpackbits", None) if library is not None else None
    if function is None:
        return None
    function.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    function.restype = ctypes.c_long
    return function


_UNPACK = None
_UNPACK_RESOLVED = False


def unpackbits(data: bytes, expected: int) -> bytes:
    """Decode Apple PackBits (the PSD "RLE" compression)."""
    global _UNPACK, _UNPACK_RESOLVED
    if not _UNPACK_RESOLVED:
        _UNPACK = _native_unpackbits()
        _UNPACK_RESOLVED = True
    if _UNPACK is not None:
        output = ctypes.create_string_buffer(expected)
        written = _UNPACK(data, len(data), output, expected)
        if written >= 0:
            return output.raw[:expected] if written >= expected else (
                output.raw[:written] + bytes(expected - written))
    result = bytearray()
    index, length = 0, len(data)
    while index < length and len(result) < expected:
        header = data[index]
        index += 1
        if header < 128:
            count = header + 1
            result += data[index:index + count]
            index += count
        elif header > 128:
            count = 257 - header
            if index < length:
                result += bytes((data[index],)) * count
            index += 1
        # 128 is a no-op
    if len(result) < expected:
        result += bytes(expected - len(result))
    return bytes(result[:expected])


def _unpredict(raw: bytes, width: int, height: int, depth: int) -> bytes:
    if depth == 8:
        rows = np.frombuffer(raw, dtype=np.uint8)[:width * height].reshape(height, width)
        return np.cumsum(rows, axis=1, dtype=np.uint8).tobytes()
    if depth == 16:
        rows = np.frombuffer(raw, dtype=">u2")[:width * height].reshape(height, width)
        return np.cumsum(rows.astype(np.uint16), axis=1, dtype=np.uint16).astype(">u2").tobytes()
    if depth == 32:
        planes = np.frombuffer(raw, dtype=np.uint8)[:width * height * 4].reshape(height, width * 4)
        planes = np.cumsum(planes, axis=1, dtype=np.uint8)
        # Bytes are stored as four planes (all MSB, ..., all LSB) per row.
        split = planes.reshape(height, 4, width).transpose(0, 2, 1)
        return np.ascontiguousarray(split).tobytes()
    raise PSDError(f"profondeur {depth} bits non gérée")


def _to_uint8(raw: bytes, width: int, height: int, depth: int) -> np.ndarray:
    count = width * height
    if depth == 8:
        values = np.frombuffer(raw, dtype=np.uint8, count=count)
    elif depth == 16:
        values = (np.frombuffer(raw, dtype=">u2", count=count) >> 8).astype(np.uint8)
    elif depth == 32:
        linear = np.clip(np.frombuffer(raw, dtype=">f4", count=count).astype(np.float32), 0.0, 1.0)
        encoded = np.where(linear <= 0.0031308, linear * 12.92,
                           1.055 * np.power(linear, 1.0 / 2.4) - 0.055)
        values = np.rint(encoded * 255.0).astype(np.uint8)
    elif depth == 1:
        packed = np.frombuffer(raw, dtype=np.uint8)
        row_bytes = (width + 7) // 8
        bits = np.unpackbits(packed[:row_bytes * height].reshape(height, row_bytes), axis=1)
        return np.where(bits[:, :width] == 1, 0, 255).astype(np.uint8)
    else:
        raise PSDError(f"profondeur {depth} bits non gérée")
    return values.reshape(height, width)


class _Stream:
    def __init__(self, data: bytes, psb: bool) -> None:
        self.data = data
        self.o = 0
        self.psb = psb

    def take(self, n: int) -> bytes:
        if n < 0 or self.o + n > len(self.data):
            raise PSDError("fichier PSD tronqué")
        chunk = self.data[self.o:self.o + n]
        self.o += n
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize(">" + fmt)
        values = struct.unpack_from(">" + fmt, self.data, self.o)
        self.o += size
        return values

    def u8(self) -> int:
        return self.unpack("B")[0]

    def u16(self) -> int:
        return self.unpack("H")[0]

    def i16(self) -> int:
        return self.unpack("h")[0]

    def u32(self) -> int:
        return self.unpack("I")[0]

    def i32(self) -> int:
        return self.unpack("i")[0]

    def length(self) -> int:
        return self.unpack("Q")[0] if self.psb else self.u32()


def _decode_channel(stream: _Stream, length: int, width: int, height: int,
                    depth: int) -> np.ndarray | None:
    """Decode one layer channel; returns uint8 (height, width) or None if empty."""
    end = stream.o + length
    if length < 2:
        stream.o = end
        return None
    compression = stream.u16()
    try:
        if width <= 0 or height <= 0:
            return None
        bytes_per_row = (width * depth + 7) // 8
        expected = bytes_per_row * height
        if compression == 0:
            raw = stream.data[stream.o:stream.o + expected]
        elif compression == 1:
            size_fmt = ">I" if stream.psb else ">H"
            size_bytes = 4 if stream.psb else 2
            counts = np.frombuffer(stream.data, dtype=size_fmt, count=height, offset=stream.o).copy()
            start = stream.o + height * size_bytes
            total = int(counts.sum())
            raw = unpackbits(stream.data[start:start + total], expected)
        elif compression in (2, 3):
            raw = zlib.decompress(stream.data[stream.o:end])
            if compression == 3:
                raw = _unpredict(raw, width, height, depth)
        else:
            raise PSDError(f"compression {compression} inconnue")
        if len(raw) < expected:
            raw = raw + bytes(expected - len(raw))
        return _to_uint8(raw, width, height, depth)
    finally:
        stream.o = end


# --------------------------------------------------------------------------
# Adjustment payloads
# --------------------------------------------------------------------------

def _unicode_at(data: bytes, offset: int) -> tuple[str, int]:
    count = struct.unpack_from(">I", data, offset)[0]
    text = data[offset + 4:offset + 4 + count * 2].decode("utf-16-be", "replace").rstrip("\0")
    return text, offset + 4 + count * 2


def _color_from_components(mode: int, values) -> tuple[int, int, int]:
    """Photoshop colour record (mode + four u16) -> sRGB 8 bits."""
    a, b, c, d = values
    if mode == 0:        # RGB, 0..65535
        return (a >> 8, b >> 8, c >> 8)
    if mode == 1:        # HSB
        import colorsys
        r, g, bl = colorsys.hsv_to_rgb(a / 65536.0, b / 65535.0, c / 65535.0)
        return (round(r * 255), round(g * 255), round(bl * 255))
    if mode == 2:        # CMYK, 0 = 100% ink
        cyan, magenta, yellow, black = (1.0 - v / 65535.0 for v in (a, b, c, d))
        return tuple(round(255 * (1.0 - min(1.0, x * (1.0 - black) + black)))
                     for x in (cyan, magenta, yellow))
    if mode == 8:        # grayscale 0..10000
        value = round(255 * (1.0 - a / 10000.0))
        return (value, value, value)
    if mode == 7:        # Lab
        return _lab_to_rgb(a / 100.0, b / 100.0, c / 100.0)
    return (a >> 8, b >> 8, c >> 8)


def _lab_to_rgb(lightness: float, a: float, b: float) -> tuple[int, int, int]:
    y = (lightness + 16.0) / 116.0
    x, z = a / 500.0 + y, y - b / 200.0

    def f(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787
    x, y, z = 0.95047 * f(x), 1.0 * f(y), 1.08883 * f(z)
    r = x * 3.2406 + y * -1.5372 + z * -0.4986
    g = x * -0.9689 + y * 1.8758 + z * 0.0415
    bl = x * 0.0557 + y * -0.2040 + z * 1.0570

    def gamma(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return tuple(round(255 * gamma(v)) for v in (r, g, bl))


def _descriptor_color(color) -> tuple[int, int, int]:
    if not isinstance(color, dict):
        return (0, 0, 0)
    cls = color.get("_class", "")
    if cls == "RGBC" or "Rd  " in color:
        def channel(key):
            value = color.get(key, 0.0)
            return value[1] if isinstance(value, tuple) else value
        return tuple(int(round(max(0.0, min(255.0, float(channel(k))))))
                     for k in ("Rd  ", "Grn ", "Bl  "))
    if cls == "Grsc":
        gray = color.get("Gry ", 0.0)
        gray = gray[1] if isinstance(gray, tuple) else gray
        value = round(255 * (1.0 - float(gray) / 100.0))
        return (value, value, value)
    if cls == "HSBC":
        import colorsys
        hue = color.get("H   ", ("#Ang", 0.0))
        hue = hue[1] if isinstance(hue, tuple) else hue
        r, g, b = colorsys.hsv_to_rgb(float(hue) / 360.0, float(color.get("Strt", 0.0)) / 100.0,
                                      float(color.get("Brgh", 0.0)) / 100.0)
        return (round(r * 255), round(g * 255), round(b * 255))
    if cls == "LbCl":
        return _lab_to_rgb(float(color.get("Lmnc", 0.0)), float(color.get("A   ", 0.0)),
                           float(color.get("B   ", 0.0)))
    if cls == "CMYC":
        c, m, y, k = (float(color.get(key, 0.0)) / 100.0 for key in ("Cyn ", "Mgnt", "Ylw ", "Blck"))
        return tuple(round(255 * (1.0 - min(1.0, x * (1.0 - k) + k))) for x in (c, m, y))
    return (0, 0, 0)


def parse_gradient_map(data: bytes) -> dict:
    """``grdm``: Photoshop gradient map (versions 1 and 3)."""
    o = 0
    version = struct.unpack_from(">H", data, o)[0]
    o += 2
    reverse, dither = bool(data[o]), bool(data[o + 1])
    o += 2
    method = "Gcls"
    if version >= 3:
        method = data[o:o + 4].decode("latin-1")
        o += 4
    name, o = _unicode_at(data, o)
    color_count = struct.unpack_from(">H", data, o)[0]
    o += 2
    colors = []
    for _ in range(color_count):
        location, midpoint, mode = struct.unpack_from(">IIH", data, o)
        components = struct.unpack_from(">4H", data, o + 10)
        o += 20
        colors.append({"location": location / 4096.0, "midpoint": midpoint / 100.0,
                       "color": list(_color_from_components(mode, components))})
    alpha_count = struct.unpack_from(">H", data, o)[0]
    o += 2
    alphas = []
    for _ in range(alpha_count):
        location, midpoint, opacity = struct.unpack_from(">IIH", data, o)
        o += 10
        alphas.append({"location": location / 4096.0, "midpoint": midpoint / 100.0,
                       "opacity": min(255, opacity) / 255.0})
    smoothness = 1.0
    try:
        _expansion, interpolation = struct.unpack_from(">HH", data, o)
        smoothness = max(0.0, min(1.0, interpolation / 4096.0))
    except struct.error:
        pass
    return {"kind": "gradient_map",
            "gradient_map": {"name": name, "reverse": reverse, "dither": dither,
                             "method": method, "smoothness": smoothness,
                             "stops": sorted(colors, key=lambda item: item["location"]),
                             "opacity_stops": sorted(alphas, key=lambda item: item["location"])}}


def parse_cube_lut(text: str) -> tuple[int, np.ndarray, tuple, tuple]:
    """Adobe/Resolve ``.cube`` 3D LUT -> (size, float32 table, domain_min, domain_max).

    The table is laid out red-fastest: ``table[b, g, r] = (R, G, B)``.
    """
    size = 0
    domain_min, domain_max = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    values: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif head == "DOMAIN_MIN":
            domain_min = tuple(float(v) for v in line.split()[1:4])
        elif head == "DOMAIN_MAX":
            domain_max = tuple(float(v) for v in line.split()[1:4])
        elif head in ("TITLE", "LUT_1D_SIZE", "LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
            if head.startswith("LUT_1D"):
                raise PSDError("LUT 1D non gérée")
            continue
        elif head[0].isdigit() or head[0] in "-.":
            parts = line.split()
            if len(parts) >= 3:
                values.extend(float(v) for v in parts[:3])
    if size < 2 or len(values) < size ** 3 * 3:
        raise PSDError("LUT 3D .cube invalide")
    table = np.asarray(values[:size ** 3 * 3], dtype=np.float32).reshape(size, size, size, 3)
    return size, table, domain_min, domain_max


def encode_lut(size: int, table: np.ndarray, domain_min=(0.0, 0.0, 0.0),
               domain_max=(1.0, 1.0, 1.0), name: str = "") -> dict:
    """Serializable (JSON) form of a 3D LUT stored in an adjustment dict."""
    lo = np.asarray(domain_min, dtype=np.float32)
    hi = np.asarray(domain_max, dtype=np.float32)
    normalized = np.clip((table - lo) / np.maximum(hi - lo, 1e-6), 0.0, 1.0)
    quantized = np.rint(normalized * 65535.0).astype("<u2").tobytes()
    return {"size": int(size), "name": name, "encoding": "u16le-rgb-rfast",
            "sha1": hashlib.sha1(quantized).hexdigest(),
            "data": base64.b64encode(zlib.compress(quantized, 6)).decode("ascii")}


def parse_color_lookup(data: bytes) -> dict:
    """``clrL``: Color Lookup adjustment carrying an embedded 3D LUT."""
    version = struct.unpack_from(">H", data, 0)[0]
    if version != 1:
        raise PSDError(f"Correspondance de couleur v{version} non gérée")
    desc = parse_versioned_descriptor(data, 2)
    lut_format = str(desc.get("LUTFormat", ""))
    payload = desc.get("LUT3DFileData")
    name = str(desc.get("LUT3DFileName") or desc.get("Nm  ") or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if not isinstance(payload, bytes) or not payload:
        raise PSDError("Correspondance de couleur sans données LUT (profil abstrait)")
    if "CUBE" not in lut_format.upper() and b"LUT_3D_SIZE" not in payload[:4096]:
        raise PSDError(f"format de LUT {lut_format!r} non géré")
    size, table, low, high = parse_cube_lut(payload.decode("latin-1"))
    return {"kind": "color_lookup", "color_lookup": encode_lut(size, table, low, high, name)}


def _curve_points(points) -> list[list[int]]:
    return [[int(x), int(y)] for x, y in sorted(points)]


def parse_curves(data: bytes) -> dict:
    o = 1                                   # padding byte
    version = struct.unpack_from(">H", data, o)[0]
    o += 2
    if version not in (1, 4):
        raise PSDError(f"Courbes v{version} non gérées")
    bitmap = struct.unpack_from(">I", data, o)[0]
    o += 4
    result = {"points": [[0, 0], [255, 255]], "channels": {}}
    names = {0: None, 1: "red", 2: "green", 3: "blue"}
    for bit in range(32):
        if not bitmap & (1 << bit):
            continue
        count = struct.unpack_from(">H", data, o)[0]
        o += 2
        points = []
        for _ in range(count):
            output, value = struct.unpack_from(">HH", data, o)
            o += 4
            points.append((value, output))
        if bit in names:
            if names[bit] is None:
                result["points"] = _curve_points(points)
            else:
                result["channels"][names[bit]] = _curve_points(points)
    return {"kind": "curves", "curves": result}


def _levels_table(record) -> list[list[int]]:
    in_black, in_white, out_black, out_white, gamma = record
    gamma = max(0.01, gamma / 100.0)
    x = np.arange(256, dtype=np.float64)
    t = np.clip((x - in_black) / max(1, in_white - in_black), 0.0, 1.0)
    y = np.power(t, 1.0 / gamma) * (out_white - out_black) + out_black
    y = np.rint(np.clip(y, 0, 255)).astype(int)
    return [[int(i), int(v)] for i, v in enumerate(y)]


def parse_levels(data: bytes) -> dict:
    version = struct.unpack_from(">H", data, 0)[0]
    if version != 2:
        raise PSDError(f"Niveaux v{version} non gérés")
    records = [struct.unpack_from(">5H", data, 2 + index * 10) for index in range(4)]
    identity = (0, 255, 0, 255, 100)
    channels = {name: _levels_table(record) for name, record in
                zip(("red", "green", "blue"), records[1:]) if tuple(record) != identity}
    return {"kind": "curves", "curves": {"points": _levels_table(records[0]),
                                         "channels": channels}, "source": "levels"}


def parse_hue_saturation(data: bytes) -> dict:
    version = struct.unpack_from(">H", data, 0)[0]
    if version != 2:
        raise PSDError(f"Teinte/Saturation v{version} non gérée")
    colorize = bool(data[2])
    colorize_values = struct.unpack_from(">3h", data, 4)
    master = struct.unpack_from(">3h", data, 10)
    result = {"kind": "hue_saturation",
              "hue_saturation": {"hue": float(master[0]), "saturation": float(master[1]),
                                 "lightness": float(master[2])}}
    if colorize:
        result["colorize"] = {"hue": colorize_values[0], "saturation": colorize_values[1],
                              "lightness": colorize_values[2]}
    return result


def parse_brightness_contrast(data: bytes) -> dict:
    brightness, contrast = struct.unpack_from(">hh", data, 0)
    legacy = bool(data[7]) if len(data) > 7 else True
    x = np.arange(256, dtype=np.float64)
    if legacy:
        y = (x + brightness * 2.55 - 127.5) * (1.0 + contrast / 100.0) + 127.5
    else:
        factor = (259.0 * (contrast + 255.0)) / (255.0 * (259.0 - contrast)) if contrast < 259 else 1.0
        y = factor * (x + brightness * 1.5 - 128.0) + 128.0
    y = np.rint(np.clip(y, 0, 255)).astype(int)
    return {"kind": "curves", "curves": {"points": [[int(i), int(v)] for i, v in enumerate(y)],
                                         "channels": {}}, "source": "brightness_contrast"}


def parse_exposure(data: bytes) -> dict:
    _version, exposure, offset, gamma = struct.unpack_from(">Hfff", data, 0)
    return {"kind": "exposure", "exposure": {"exposure": float(exposure), "offset": float(offset),
                                             "gamma": float(gamma) or 1.0}}


def parse_vibrance(data: bytes) -> dict:
    desc = parse_versioned_descriptor(data, 0)
    return {"kind": "vibrance", "vibrance": {"vibrance": float(desc.get("vibrance", 0)),
                                             "saturation": float(desc.get("Strt", 0))}}


def parse_color_balance(data: bytes) -> dict:
    values = struct.unpack_from(">9h", data, 0)
    return {"kind": "color_balance",
            "color_balance": {"shadows": list(values[0:3]), "midtones": list(values[3:6]),
                              "highlights": list(values[6:9])}}


def parse_selective_color(data: bytes) -> dict:
    _version, method = struct.unpack_from(">HH", data, 0)
    bands = ("reds", "yellows", "greens", "cyans", "blues", "magentas", "whites",
             "neutrals", "blacks")
    channels = {}
    for index, band in enumerate(bands):
        record = struct.unpack_from(">4h", data, 4 + (index + 1) * 8)
        if any(record):
            channels[band] = [float(v) for v in record]
    return {"kind": "selective_color", "selective_color": {"channels": channels},
            "method": "absolute" if method else "relative"}


def parse_adjustment(key: bytes, data: bytes) -> dict:
    if key == b"grdm":
        return parse_gradient_map(data)
    if key == b"clrL":
        return parse_color_lookup(data)
    if key == b"curv":
        return parse_curves(data)
    if key == b"levl":
        return parse_levels(data)
    if key == b"hue2":
        return parse_hue_saturation(data)
    if key == b"brit":
        return parse_brightness_contrast(data)
    if key == b"expA":
        return parse_exposure(data)
    if key == b"vibA":
        return parse_vibrance(data)
    if key == b"blnc":
        return parse_color_balance(data)
    if key == b"selc":
        return parse_selective_color(data)
    if key == b"nvrt":
        return {"kind": "invert"}
    if key == b"post":
        return {"kind": "posterize", "posterize": int(struct.unpack_from(">H", data, 0)[0])}
    if key == b"thrs":
        return {"kind": "threshold", "threshold": int(struct.unpack_from(">H", data, 0)[0])}
    names = {b"phfl": "Filtre photo", b"mixr": "Mélangeur de couches",
             b"blwh": "Noir et blanc", b"hue ": "Teinte/Saturation (ancienne)",
             b"CgEd": "Luminosité/Contraste"}
    raise PSDError(f"réglage « {names.get(key, key.decode('latin-1'))} » non pris en charge")


def _parse_brightness_descriptor(data: bytes) -> dict:
    desc = parse_versioned_descriptor(data, 0)
    brightness = int(desc.get("Brgh", 0))
    contrast = int(desc.get("Cntr", 0))
    legacy = bool(desc.get("useLegacy", False))
    packed = struct.pack(">hhHBB", brightness, contrast, 0, 0, 1 if legacy else 0)
    return parse_brightness_contrast(packed)


def parse_fill(key: bytes, data: bytes) -> dict:
    if key == b"SoCo":
        desc = parse_versioned_descriptor(data, 0)
        return {"kind": "solid_color", "color": list(_descriptor_color(desc.get("Clr ")))}
    return {"kind": "gradient_fill" if key == b"GdFl" else "pattern_fill"}


def _parse_effects(data: bytes) -> list[dict]:
    """``lfx2``: map the common layer styles onto Nebula's native effects."""
    try:
        desc = parse_versioned_descriptor(data, 4)
    except (DescriptorError, struct.error):
        return []
    if desc.get("masterFXSwitch") is False:
        return []
    result = []

    def angle_offset(item):
        import math
        angle = item.get("lagl", ("#Ang", 120.0))
        angle = float(angle[1] if isinstance(angle, tuple) else angle)
        distance = item.get("Dstn", ("#Pxl", 5.0))
        distance = float(distance[1] if isinstance(distance, tuple) else distance)
        return (round(-math.cos(math.radians(angle)) * distance),
                round(math.sin(math.radians(angle)) * distance))

    def size_of(item, key="blur"):
        value = item.get(key, ("#Pxl", 5.0))
        return int(round(float(value[1] if isinstance(value, tuple) else value)))

    def opacity_of(item):
        value = item.get("Opct", ("#Prc", 100.0))
        return int(round(2.55 * float(value[1] if isinstance(value, tuple) else value)))

    for key, kind in (("DrSh", "drop_shadow"), ("OrGl", "outer_glow"), ("FrFX", "stroke")):
        item = desc.get(key)
        if not isinstance(item, dict) or not item.get("enab", False):
            continue
        color = list(_descriptor_color(item.get("Clr "))) + [opacity_of(item)]
        effect = {"type": kind, "enabled": True, "color": color}
        if kind == "drop_shadow":
            effect["offset_x"], effect["offset_y"] = angle_offset(item)
            effect["size"] = max(1, size_of(item))
        elif kind == "outer_glow":
            effect["offset_x"] = effect["offset_y"] = 0
            effect["size"] = max(1, size_of(item))
        else:
            effect["size"] = max(1, size_of(item, "Sz  "))
        result.append(effect)
    return result


# --------------------------------------------------------------------------
# File structure
# --------------------------------------------------------------------------

def _read_tagged_blocks(stream: _Stream, end: int, layer: PSDLayer, warnings: list[str],
                        psb: bool) -> None:
    while stream.o + 12 <= end:
        signature = stream.take(4)
        if signature not in (b"8BIM", b"8B64"):
            stream.o = end
            return
        key = stream.take(4)
        size = stream.unpack("Q")[0] if psb and key in _BIG_KEYS_PSB else stream.u32()
        start = stream.o
        data = stream.data[start:start + size]
        layer.tagged_keys.append(key.decode("latin-1"))
        try:
            if key == b"luni":
                layer.name, _ = _unicode_at(data, 0)
            elif key == b"lsct":
                layer.section = struct.unpack_from(">I", data, 0)[0]
                if size >= 12 and data[4:8] == b"8BIM":
                    layer.section_blend_key = data[8:12].decode("latin-1")
            elif key == b"iOpa":
                layer.fill_opacity = data[0]
            elif key == b"lyid":
                layer.layer_id = struct.unpack_from(">I", data, 0)[0]
            elif key == b"lclr":
                layer.label_color = LABEL_COLORS.get(struct.unpack_from(">H", data, 0)[0])
            elif key == b"lspf":
                flags = struct.unpack_from(">I", data, 0)[0]
                layer.transparency_locked = bool(flags & 1) or layer.transparency_locked
            elif key in ADJUSTMENT_KEYS:
                if key == b"CgEd":
                    layer.adjustment = _parse_brightness_descriptor(data)
                elif key == b"brit" and layer.adjustment is not None:
                    pass            # CgEd (descriptor) already decoded, it is newer
                else:
                    layer.adjustment = parse_adjustment(key, data)
            elif key in FILL_KEYS:
                layer.fill = parse_fill(key, data)
            elif key in (b"vmsk", b"vsms"):
                layer.has_vector_mask = True
            elif key == b"lfx2":
                layer.effects = _parse_effects(data)
            elif key in (b"SoLd", b"PlLd", b"SoLE"):
                layer.unsupported.append("objet dynamique (pixels rastérisés conservés)")
            elif key in (b"TySh", b"tySh"):
                layer.unsupported.append("texte (pixels rastérisés conservés)")
        except (PSDError, DescriptorError, struct.error, IndexError, ValueError) as error:
            layer.unsupported.append(str(error))
            if key in ADJUSTMENT_KEYS:
                layer.adjustment = {"kind": "unsupported", "reason": str(error)}
        stream.o = start + size
        # 4-byte padding is included in `size` by Photoshop; odd sizes are
        # padded to even by some writers.
    stream.o = end


def _read_mask_data(stream: _Stream, layer: PSDLayer) -> tuple[PSDMask | None, PSDMask | None]:
    size = stream.u32()
    end = stream.o + size
    if size == 0:
        return None, None
    top, left, bottom, right = stream.unpack("4i")
    default = stream.u8()
    flags = stream.u8()
    user = PSDMask(left, top, right, bottom, default, bool(flags & 2), bool(flags & 4))
    real = None
    if flags & 16 and stream.o < end:
        parameters = stream.u8()
        for bit, width in ((1, 1), (2, 8), (4, 1), (8, 8)):
            if parameters & bit:
                stream.o += width
    if size >= 36 and end - stream.o >= 18:
        real_flags = stream.u8()
        real_default = stream.u8()
        rtop, rleft, rbottom, rright = stream.unpack("4i")
        real = PSDMask(rleft, rtop, rright, rbottom, real_default, bool(real_flags & 2),
                       bool(real_flags & 4))
    stream.o = end
    return user, real


def _read_layer_records(stream: _Stream, psd_depth: int, color_mode: int,
                        warnings: list[str], lazy_layers: bool = False) -> list[PSDLayer]:
    psb = stream.psb
    count = stream.i16()
    count = abs(count)
    records = []
    for _ in range(count):
        top, left, bottom, right = stream.unpack("4i")
        channel_count = stream.u16()
        channels = []
        for _c in range(channel_count):
            channel_id = stream.i16()
            channels.append((channel_id, stream.length()))
        if stream.take(4) != b"8BIM":
            raise PSDError("signature de mode de fusion invalide")
        blend_key = stream.take(4).decode("latin-1")
        opacity, clipping, flags, _filler = stream.unpack("4B")
        extra_length = stream.u32()
        extra_end = stream.o + extra_length
        layer = PSDLayer(name="Calque", left=left, top=top, right=right, bottom=bottom,
                         blend_key=blend_key, opacity=opacity, clipping=clipping != 0,
                         hidden=bool(flags & 2), transparency_locked=bool(flags & 1))
        user_mask, real_mask = _read_mask_data(stream, layer)
        blending = stream.u32()
        stream.o += blending
        name_length = stream.u8()
        layer.name = stream.take(name_length).decode("mac_roman", "replace")
        stream.o += (4 - (name_length + 1) % 4) % 4
        _read_tagged_blocks(stream, extra_end, layer, warnings, psb)
        stream.o = extra_end
        layer.mask = real_mask if real_mask is not None else user_mask
        records.append((layer, channels, user_mask, real_mask))
    # Record offsets without retaining decoded pixels for every layer.
    result = []
    for layer, channels, user_mask, real_mask in records:
        offset = stream.o
        end = offset + sum(length for _, length in channels)
        if end > len(stream.data):
            raise PSDError("fichier PSD tronqué")
        def load(layer=layer, channels=channels, user_mask=user_mask,
                 real_mask=real_mask, offset=offset):
            local = _Stream(stream.data, stream.psb)
            local.o = offset
            _decode_layer_pixels(local, layer, channels, user_mask, real_mask,
                                 psd_depth, color_mode)
        if lazy_layers:
            layer._pixel_loader = load
        else:
            load()
        stream.o = end
        result.append(layer)
    return result


def _decode_layer_pixels(stream, layer, channels, user_mask, real_mask, psd_depth, color_mode):
    planes = {}
    for channel_id, length in channels:
        if channel_id in (-2, -3):
            mask = real_mask if channel_id == -3 and real_mask is not None else user_mask
            if mask is not None:
                mask.data = _decode_channel(stream, length, mask.width, mask.height, psd_depth)
                planes[channel_id] = mask
            else:
                stream.o += length
            continue
        planes[channel_id] = _decode_channel(stream, length, layer.width, layer.height,
                                             psd_depth)
    layer.rgba = _assemble_rgba(planes, layer.width, layer.height, color_mode)
    # A layer with a vector mask stores its rasterized vector mask in -2 and
    # the painted pixel mask in -3; keep the pixel mask (vector masks are
    # reported, not re-rasterized).
    pixel_mask = planes.get(-3) or planes.get(-2)
    if isinstance(pixel_mask, PSDMask):
        layer.mask = pixel_mask
    elif user_mask is not None and user_mask.width == 0 and user_mask.height == 0:
        layer.mask = user_mask           # empty-bounds mask: default colour only
    if layer.has_vector_mask:
        layer.unsupported.append("masque vectoriel non rastérisé")


def _assemble_rgba(planes: dict, width: int, height: int, color_mode: int) -> np.ndarray | None:
    if width <= 0 or height <= 0:
        return None
    zeros = np.broadcast_to(np.uint8(0), (height, width))

    def plane(index, default=zeros):
        value = planes.get(index)
        return value if isinstance(value, np.ndarray) else default

    alpha = plane(-1, np.broadcast_to(np.uint8(255), (height, width)))
    if color_mode in (1, 8, 0):          # grayscale / duotone / bitmap
        gray = plane(0)
        rgb = (gray, gray, gray)
    elif color_mode == 4:                # CMYK, stored inverted (255 = no ink)
        c, m, y, k = (plane(i).astype(np.uint16) for i in range(4))
        rgb = tuple(((v * k + 127) // 255).astype(np.uint8) for v in (c, m, y))
    elif color_mode == 9:                # Lab: approximate through L only
        gray = plane(0)
        rgb = (gray, gray, gray)
    else:
        rgb = (plane(0), plane(1), plane(2))
    return np.dstack((*rgb, alpha))


def _build_tree(flat: list[PSDLayer], warnings: list[str]) -> tuple[list[PSDLayer], list[PSDLayer]]:
    """Turn the bottom-to-top record list (with folder markers) into a tree."""
    root: list[PSDLayer] = []
    stack: list[list[PSDLayer]] = [root]
    pending: list[None] = []
    layers: list[PSDLayer] = []
    for layer in flat:
        if layer.section == SECTION_END:
            children: list[PSDLayer] = []
            stack.append(children)
            pending.append(None)
            continue
        if layer.is_group:
            if len(stack) == 1:
                warnings.append(f"{layer.name} : dossier sans marqueur de fin, vide")
                layer.children = []
            else:
                layer.children = stack.pop()
                pending.pop()
            for child in layer.children:
                child.parent = layer
            stack[-1].append(layer)
            layers.append(layer)
            continue
        stack[-1].append(layer)
        layers.append(layer)
    while len(stack) > 1:                      # unterminated folders: flatten into parent
        orphans = stack.pop()
        stack[-1].extend(orphans)
        warnings.append("dossier PSD non fermé : contenu remonté d'un niveau")
    return root, layers


def _read_composite(stream: _Stream, width: int, height: int, channels: int, depth: int,
                    color_mode: int) -> np.ndarray | None:
    if stream.o + 2 > len(stream.data):
        return None
    compression = stream.u16()
    bytes_per_row = (width * depth + 7) // 8
    plane_bytes = bytes_per_row * height
    planes = []
    if compression == 0:
        for index in range(channels):
            raw = stream.data[stream.o + index * plane_bytes:stream.o + (index + 1) * plane_bytes]
            planes.append(_to_uint8(raw, width, height, depth))
    elif compression == 1:
        size_fmt = ">I" if stream.psb else ">H"
        size_bytes = 4 if stream.psb else 2
        counts = np.frombuffer(stream.data, dtype=size_fmt, count=height * channels,
                               offset=stream.o).astype(np.int64)
        position = stream.o + height * channels * size_bytes
        for index in range(channels):
            total = int(counts[index * height:(index + 1) * height].sum())
            raw = unpackbits(stream.data[position:position + total], plane_bytes)
            position += total
            planes.append(_to_uint8(raw, width, height, depth))
    else:
        raw = zlib.decompress(stream.data[stream.o:])
        if compression == 3:
            raw = b"".join(_unpredict(raw[i * plane_bytes:(i + 1) * plane_bytes], width, height, depth)
                           for i in range(channels))
        for index in range(channels):
            planes.append(_to_uint8(raw[index * plane_bytes:(index + 1) * plane_bytes],
                                    width, height, depth))
    mapping = {index: plane for index, plane in enumerate(planes)}
    color_count = {1: 1, 8: 1, 0: 1, 4: 4, 9: 3}.get(color_mode, 3)
    if len(planes) > color_count:
        mapping[-1] = planes[color_count]
    return _assemble_rgba(mapping, width, height, color_mode)


def _read_composite_region(stream: _Stream, width: int, height: int, channels: int,
                           depth: int, color_mode: int, rect) -> np.ndarray:
    """Decode one composite rectangle without materializing raw/RLE planes."""
    x, y, region_width, region_height = (int(value) for value in rect)
    x, y = max(0, x), max(0, y)
    region_width, region_height = min(region_width, width - x), min(region_height, height - y)
    if region_width <= 0 or region_height <= 0:
        return np.zeros((0, 0, 4), dtype=np.uint8)
    start = stream.o
    compression = stream.u16()
    # ZIP streams are document-wide; random row access requires inflating the
    # stream first.  Raw and PackBits files, common for production composites,
    # remain strictly viewport-bounded below.
    if compression == 2 and depth != 1:
        return _read_zip_composite_region(stream, width, height, channels, depth, color_mode,
                                          x, y, region_width, region_height)
    if compression == 3 and depth != 1:
        return _read_zip_prediction_region(stream, width, height, channels, depth, color_mode,
                                           x, y, region_width, region_height)
    if depth == 1:
        stream.o = start
        full = _read_composite(stream, width, height, channels, depth, color_mode)
        return full[y:y + region_height, x:x + region_width].copy()
    bytes_per_row = (width * depth + 7) // 8
    bytes_per_pixel = depth // 8
    if bytes_per_pixel <= 0:
        raise PSDError("profondeur composite non gérée")
    cropped_row_bytes = region_width * bytes_per_pixel
    planes = []
    if compression == 0:
        plane_bytes = bytes_per_row * height
        data_start = stream.o
        for channel in range(channels):
            base = data_start + channel * plane_bytes
            raw = b"".join(stream.data[base + row * bytes_per_row + x * bytes_per_pixel:
                                      base + row * bytes_per_row + x * bytes_per_pixel + cropped_row_bytes]
                           for row in range(y, y + region_height))
            planes.append(_to_uint8(raw, region_width, region_height, depth))
    elif compression == 1:
        size_fmt = ">I" if stream.psb else ">H"
        size_bytes = 4 if stream.psb else 2
        counts = np.frombuffer(stream.data, dtype=size_fmt, count=height * channels,
                               offset=stream.o).astype(np.int64)
        offsets = np.empty(len(counts), dtype=np.int64)
        position = stream.o + len(counts) * size_bytes
        for index, count in enumerate(counts):
            offsets[index] = position
            position += int(count)
        for channel in range(channels):
            rows = []
            for row in range(y, y + region_height):
                index = channel * height + row
                packed = stream.data[offsets[index]:offsets[index] + counts[index]]
                decoded = unpackbits(packed, bytes_per_row)
                begin = x * bytes_per_pixel
                rows.append(decoded[begin:begin + cropped_row_bytes])
            planes.append(_to_uint8(b"".join(rows), region_width, region_height, depth))
    else:
        raise PSDError(f"compression composite {compression} inconnue")
    mapping = {index: plane for index, plane in enumerate(planes)}
    color_count = {1: 1, 8: 1, 0: 1, 4: 4, 9: 3}.get(color_mode, 3)
    if len(planes) > color_count:
        mapping[-1] = planes[color_count]
    return _assemble_rgba(mapping, region_width, region_height, color_mode)


def _read_zip_composite_region(stream: _Stream, width: int, height: int, channels: int,
                               depth: int, color_mode: int, x: int, y: int,
                               region_width: int, region_height: int) -> np.ndarray:
    """Inflate ZIP composite data in bounded chunks, retaining only one region."""
    bytes_per_row = (width * depth + 7) // 8
    bytes_per_pixel = depth // 8
    cropped_row_bytes = region_width * bytes_per_pixel
    plane_bytes = bytes_per_row * height
    buffers = [bytearray(cropped_row_bytes * region_height) for _ in range(channels)]
    targets = []
    for channel in range(channels):
        for local_row, row in enumerate(range(y, y + region_height)):
            start = channel * plane_bytes + row * bytes_per_row + x * bytes_per_pixel
            targets.append((start, start + cropped_row_bytes, channel, local_row * cropped_row_bytes))
    inflater = zlib.decompressobj()
    compressed = memoryview(stream.data)[stream.o:]
    produced = 0
    while compressed:
        chunk = inflater.decompress(compressed, 1024 * 1024)
        compressed = inflater.unconsumed_tail
        if chunk:
            end = produced + len(chunk)
            for start, stop, channel, destination in targets:
                left, right = max(start, produced), min(stop, end)
                if left < right:
                    source_offset = left - produced
                    target_offset = destination + left - start
                    buffers[channel][target_offset:target_offset + right - left] = \
                        chunk[source_offset:source_offset + right - left]
            produced = end
        elif not compressed:
            break
    tail = inflater.flush()
    if tail:
        end = produced + len(tail)
        for start, stop, channel, destination in targets:
            left, right = max(start, produced), min(stop, end)
            if left < right:
                source_offset = left - produced
                target_offset = destination + left - start
                buffers[channel][target_offset:target_offset + right - left] = \
                    tail[source_offset:source_offset + right - left]
    planes = [_to_uint8(bytes(raw), region_width, region_height, depth) for raw in buffers]
    mapping = {index: plane for index, plane in enumerate(planes)}
    color_count = {1: 1, 8: 1, 0: 1, 4: 4, 9: 3}.get(color_mode, 3)
    if len(planes) > color_count:
        mapping[-1] = planes[color_count]
    return _assemble_rgba(mapping, region_width, region_height, color_mode)


def _read_zip_prediction_region(stream: _Stream, width: int, height: int, channels: int,
                                depth: int, color_mode: int, x: int, y: int,
                                region_width: int, region_height: int) -> np.ndarray:
    """Stream ZIP-with-prediction rows; prediction only needs one row at a time."""
    bytes_per_row = (width * depth + 7) // 8
    bytes_per_pixel = depth // 8
    cropped_row_bytes = region_width * bytes_per_pixel
    buffers = [bytearray(cropped_row_bytes * region_height) for _ in range(channels)]
    inflater = zlib.decompressobj()
    compressed = memoryview(stream.data)[stream.o:]
    pending = bytearray()
    channel, row = 0, 0

    def consume(data):
        nonlocal channel, row
        pending.extend(data)
        while len(pending) >= bytes_per_row and channel < channels:
            encoded = bytes(pending[:bytes_per_row])
            del pending[:bytes_per_row]
            if depth == 8:
                restored = np.cumsum(np.frombuffer(encoded, dtype=np.uint8), dtype=np.uint8).tobytes()
            elif depth == 16:
                values = np.frombuffer(encoded, dtype=">u2")
                restored = np.cumsum(values.astype(np.uint16), dtype=np.uint16).astype(">u2").tobytes()
            elif depth == 32:
                values = np.cumsum(np.frombuffer(encoded, dtype=np.uint8), dtype=np.uint8)
                restored = np.ascontiguousarray(values.reshape(4, width).transpose(1, 0)).tobytes()
            else:
                raise PSDError("profondeur composite ZIP prédictive non gérée")
            if y <= row < y + region_height:
                start = x * bytes_per_pixel
                destination = (row - y) * cropped_row_bytes
                buffers[channel][destination:destination + cropped_row_bytes] = \
                    restored[start:start + cropped_row_bytes]
            row += 1
            if row == height:
                channel, row = channel + 1, 0

    while compressed:
        chunk = inflater.decompress(compressed, 1024 * 1024)
        compressed = inflater.unconsumed_tail
        if chunk:
            consume(chunk)
        elif not compressed:
            break
    consume(inflater.flush())
    if channel != channels or pending:
        raise PSDError("composite ZIP prédictif tronqué")
    planes = [_to_uint8(bytes(raw), region_width, region_height, depth) for raw in buffers]
    mapping = {index: plane for index, plane in enumerate(planes)}
    color_count = {1: 1, 8: 1, 0: 1, 4: 4, 9: 3}.get(color_mode, 3)
    if len(planes) > color_count:
        mapping[-1] = planes[color_count]
    return _assemble_rgba(mapping, region_width, region_height, color_mode)


def read_composite_regions(source, regions) -> tuple[tuple[int, int], dict[tuple[int, int, int, int], np.ndarray]]:
    """Read composite rectangles while retaining only their decoded pixels.

    This is the progressive-import entry point: PSD metadata is parsed once,
    then raw/RLE channel rows are decoded only for the requested rectangles.
    """
    with read_psd(source, composite=False, lazy_layers=True) as psd:
        if not psd._composite_offset:
            raise PSDError("PSD sans composite intégré")
        stream = _Stream(psd._mapped_source, psd.version == 2)
        result = {}
        for rect in regions:
            stream.o = psd._composite_offset
            result[tuple(rect)] = _read_composite_region(
                stream, psd.width, psd.height, _composite_channel_count(psd), psd.depth,
                psd.color_mode, rect)
        return (psd.width, psd.height), result


def _composite_channel_count(psd: PSDFile) -> int:
    """Channel count is stored in the PSD header; retain it on parsed files."""
    return getattr(psd, "_channel_count", 4)


def read_psd(source, *, composite: bool = True, lazy_layers: bool = False) -> PSDFile:
    """Parse PSD/PSB, mapping path inputs without a whole-file bytes copy.

    With lazy_layers=True, call layer.decode_pixels() before consuming pixels
    and release_pixels() after transferring them. Use the result as a context
    manager (or call close()) to release the mapped file.
    """
    mapped = None
    try:
        if not isinstance(source, (bytes, bytearray, memoryview)):
            with open(source, "rb") as handle:
                if not handle.seek(0, 2):
                    raise PSDError("fichier PSD vide")
                mapped = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            source = mapped
        result = _read_psd(source, composite=composite, lazy_layers=lazy_layers)
        if lazy_layers:
            result._mapped_source = mapped
            mapped = None
        return result
    except PSDError:
        raise
    except (struct.error, IndexError, zlib.error, OverflowError, MemoryError, ValueError) as error:
        raise PSDError(f"fichier PSD endommagé ou tronqué ({error})") from error
    finally:
        if mapped is not None:
            mapped.close()


def _read_psd(source, *, composite: bool = True, lazy_layers: bool = False) -> PSDFile:
    data = source if isinstance(source, (bytes, mmap.mmap)) else bytes(source)
    if data[:4] != b"8BPS":
        raise PSDError("ce fichier n'est pas un document Photoshop")
    version = struct.unpack_from(">H", data, 4)[0]
    if version not in (1, 2):
        raise PSDError(f"version PSD {version} inconnue")
    channels, height, width, depth, color_mode = struct.unpack_from(">HIIHH", data, 12)
    if color_mode not in (0, 1, 3, 4, 8, 9):
        raise PSDError({2: "mode couleurs indexées", 7: "mode multicouche"}.get(
            color_mode, f"mode colorimétrique {color_mode}") + " non pris en charge")
    if depth not in (1, 8, 16, 32):
        raise PSDError(f"profondeur {depth} bits non gérée")
    stream = _Stream(data, version == 2)
    stream.o = 26
    colour_data = stream.u32()
    stream.o += colour_data                        # colour mode data
    resources_length = stream.u32()
    resources_end = stream.o + resources_length
    icc = b""
    while stream.o + 12 <= resources_end:
        if stream.take(4) not in (b"8BIM", b"MeSa", b"AgHg", b"PHUT", b"DCSR"):
            break
        resource_id = stream.u16()
        name_length = stream.u8()
        stream.o += name_length + ((name_length + 1) % 2)
        size = stream.u32()
        if resource_id == 1039:
            icc = data[stream.o:stream.o + size]
        stream.o += size + (size % 2)
    stream.o = resources_end
    warnings: list[str] = []
    section_length = stream.length()
    section_end = stream.o + section_length
    flat: list[PSDLayer] = []
    if section_length:
        info_length = stream.length()
        info_end = stream.o + info_length
        if info_length:
            flat = _read_layer_records(stream, depth, color_mode, warnings, lazy_layers)
        stream.o = info_end
        # Global mask info, then global tagged blocks that may hold the layers
        # of 16/32-bit documents (Lr16 / Lr32).
        if stream.o + 4 <= section_end:
            global_mask = stream.u32()
            stream.o += global_mask
        while not flat and stream.o + 12 <= section_end:
            if stream.take(4) not in (b"8BIM", b"8B64"):
                break
            key = stream.take(4)
            size = stream.unpack("Q")[0] if stream.psb and key in _BIG_KEYS_PSB else stream.u32()
            start = stream.o
            if key in (b"Lr16", b"Lr32", b"Layr") and size:
                flat = _read_layer_records(stream, depth, color_mode, warnings, lazy_layers)
            stream.o = start + size
            if stream.o % 4:
                stream.o += 4 - stream.o % 4
    stream.o = section_end
    composite_offset = stream.o
    merged = None
    if composite:
        try:
            merged = _read_composite(stream, width, height, channels, depth, color_mode)
        except (PSDError, zlib.error, ValueError, struct.error) as error:
            warnings.append(f"image composite illisible ({error})")
    root, layers = _build_tree(flat, warnings)
    return PSDFile(width=width, height=height, depth=depth, color_mode=color_mode,
                   version=version, layers=layers, root=root, icc_profile=icc,
                   composite=merged, warnings=warnings, _composite_offset=composite_offset,
                   _channel_count=channels)


__all__ = ["PSDFile", "PSDLayer", "PSDMask", "PSDError", "read_psd", "unpackbits",
           "read_composite_regions", "parse_cube_lut", "encode_lut", "parse_gradient_map", "SECTION_NONE",
           "SECTION_OPEN", "SECTION_CLOSED", "SECTION_END"]
