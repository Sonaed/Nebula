"""Photoshop brush (.abr) import.

Supports the modern "8BIM" layout (ABR versions 6, 7, 9 and 10, i.e. every
Photoshop since CS), which holds three sections:

* ``samp`` — sampled brush tips (8-bit grayscale, raw or PackBits RLE);
* ``patt`` — patterns used as brush textures (grayscale / RGB, RLE);
* ``desc`` — an ActionDescriptor with every brush preset: name, tip link,
  diameter, spacing, angle, roundness, hardness, pen-pressure dynamics,
  scatter and texture.

Each Photoshop preset becomes a Nebula preset.  Things Nebula's engine has no
equivalent for (dual brush, colour dynamics, brush pose) are skipped and
listed in the import report instead of being silently approximated.
Legacy ABR v1/v2 (Photoshop 7 and older) is rejected with a clear message.
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

MAX_TIP = 1024        # px; larger tips are downscaled (they are drawn smaller anyway)
MAX_PATTERN = 1024


class AbrError(ValueError):
    pass


# ── low-level readers ──────────────────────────────────────────────────────

def _packbits(source: bytes, size: int) -> bytes:
    out = bytearray()
    i = 0
    while len(out) < size and i < len(source):
        code = source[i]
        i += 1
        if code < 128:
            out += source[i:i + code + 1]
            i += code + 1
        elif code > 128:
            if i < len(source):
                out += bytes([source[i]]) * (257 - code)
            i += 1
    return bytes(out[:size]).ljust(size, b"\0")


class _Reader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def take(self, count: int) -> bytes:
        if self.offset + count > len(self.data):
            raise AbrError("fichier tronqué")
        value = self.data[self.offset:self.offset + count]
        self.offset += count
        return value

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def key(self) -> str:
        length = self.u32()
        return self.take(length if length else 4).decode("latin-1")

    def ustr(self) -> str:
        length = self.u32()
        return self.take(2 * length).decode("utf-16-be", "replace").rstrip("\0")


def _value(reader: _Reader, kind: str):
    if kind in ("Objc", "GlbO"):
        return _descriptor(reader)
    if kind == "VlLs":
        return [_value(reader, reader.take(4).decode("latin-1")) for _ in range(reader.u32())]
    if kind == "doub":
        return reader.f64()
    if kind == "UntF":
        unit = reader.take(4).decode("latin-1")
        return {"unit": unit, "v": reader.f64()}
    if kind == "UnFl":
        reader.take(4)
        return [reader.f64() for _ in range(reader.u32())]
    if kind == "TEXT":
        return reader.ustr()
    if kind == "enum":
        reader.key()
        return {"enum": reader.key()}
    if kind == "long":
        return reader.i32()
    if kind == "comp":
        return struct.unpack(">q", reader.take(8))[0]
    if kind == "bool":
        return bool(reader.take(1)[0])
    if kind in ("type", "GlbC"):
        reader.ustr()
        return {"class": reader.key()}
    if kind in ("tdta", "alis", "Pth "):
        reader.take(reader.u32())
        return None
    if kind == "obj ":
        for _ in range(reader.u32()):
            ref = reader.take(4).decode("latin-1")
            if ref == "prop":
                reader.ustr(); reader.key(); reader.key()
            elif ref == "Clss":
                reader.ustr(); reader.key()
            elif ref == "Enmr":
                reader.ustr(); reader.key(); reader.key(); reader.key()
            elif ref == "rele":
                reader.ustr(); reader.key(); reader.i32()
            elif ref in ("Idnt", "indx"):
                reader.i32()
            elif ref == "name":
                reader.ustr(); reader.key(); reader.ustr()
            else:
                raise AbrError(f"référence inconnue {ref!r}")
        return None
    raise AbrError(f"type de descripteur inconnu {kind!r}")


def _descriptor(reader: _Reader) -> dict:
    reader.ustr()
    result = {"_class": reader.key()}
    for _ in range(reader.u32()):
        name = reader.key()
        result[name] = _value(reader, reader.take(4).decode("latin-1"))
    return result


def _sections(data: bytes) -> dict[str, bytes]:
    sections = {}
    offset = 4
    while offset + 12 <= len(data) and data[offset:offset + 4] == b"8BIM":
        name = data[offset + 4:offset + 8].decode("latin-1")
        size = struct.unpack(">I", data[offset + 8:offset + 12])[0]
        sections[name] = data[offset + 12:offset + 12 + size]
        offset += 12 + size
    return sections


# ── sections ────────────────────────────────────────────────────────────────

def _read_tips(samp: bytes, subversion: int) -> dict[str, QImage]:
    tips: dict[str, QImage] = {}
    offset = 0
    while offset + 4 <= len(samp):
        length = struct.unpack(">I", samp[offset:offset + 4])[0]
        start = offset + 4
        following = start + ((length + 3) // 4) * 4
        key_length = samp[start]
        uuid = samp[start + 1:start + 1 + key_length].decode("latin-1")
        cursor = start + (47 if subversion == 1 else 301)
        top, left, bottom, right = struct.unpack(">4i", samp[cursor:cursor + 16])
        depth = struct.unpack(">H", samp[cursor + 16:cursor + 18])[0]
        compression = samp[cursor + 18]
        cursor += 19
        width, height = right - left, bottom - top
        if depth == 8 and 0 < width <= 8192 and 0 < height <= 8192:
            if compression == 0:
                pixels = samp[cursor:cursor + width * height]
            else:
                counts = struct.unpack(f">{height}H", samp[cursor:cursor + 2 * height])
                cursor += 2 * height
                rows = []
                for count in counts:
                    rows.append(_packbits(samp[cursor:cursor + count], width))
                    cursor += count
                pixels = b"".join(rows)
            tips[uuid] = _image_from_rows(pixels, width, height, QImage.Format.Format_Grayscale8, 1)
        offset = following
    return tips


def _read_patterns(patt: bytes) -> dict[str, tuple[str, QImage]]:
    patterns: dict[str, tuple[str, QImage]] = {}
    offset = 0
    while offset + 4 <= len(patt):
        length = struct.unpack(">I", patt[offset:offset + 4])[0]
        start = offset + 4
        following = start + ((length + 3) // 4) * 4
        try:
            reader = _Reader(patt, start)
            reader.u32()                         # version
            mode = reader.u32()
            reader.take(4)                       # height, width (u16 each)
            name = reader.ustr()
            uuid = reader.take(reader.take(1)[0]).decode("latin-1")
            if mode == 2:
                reader.take(768)                 # indexed palette
            reader.take(8)                       # VMAL version + length
            reader.take(16)                      # rectangle
            channel_count = reader.u32()
            channels = []
            for _ in range(channel_count + 2):
                if reader.offset + 4 > start + length:
                    break
                if not reader.u32():
                    continue
                channel_length = reader.u32()
                channel_end = reader.offset + channel_length
                reader.u32()                     # depth
                top, left, bottom, right = struct.unpack(">4I", reader.take(16))
                reader.take(2)
                compression = reader.take(1)[0]
                width, height = right - left, bottom - top
                if compression == 0:
                    pixels = reader.take(width * height)
                else:
                    counts = struct.unpack(f">{height}H", reader.take(2 * height))
                    pixels = b"".join(_packbits(reader.take(count), width) for count in counts)
                channels.append((width, height, pixels))
                reader.offset = channel_end
            if channels:
                width, height, first = channels[0]
                if mode == 3 and len(channels) >= 3:   # RGB → luminance
                    import numpy as np
                    r, g, b = (np.frombuffer(c[2], np.uint8).astype(np.float32) for c in channels[:3])
                    first = np.clip(0.299 * r + 0.587 * g + 0.114 * b, 0, 255).astype(np.uint8).tobytes()
                patterns[uuid] = (name, _image_from_rows(
                    first, width, height, QImage.Format.Format_Grayscale8, 1))
        except (AbrError, struct.error, ValueError):
            pass
        offset = following
    return patterns


def _image_from_rows(pixels: bytes, width: int, height: int, fmt, channels: int) -> QImage:
    """Qt-owned image filled row by row (no dependence on a Python buffer)."""
    image = QImage(width, height, fmt)
    stride = image.bytesPerLine()
    bits = image.bits()
    row = width * channels
    for y in range(height):
        bits[y * stride:y * stride + row] = pixels[y * row:(y + 1) * row]
    return image


# ── conversion ─────────────────────────────────────────────────────────────

def _png_base64(image: QImage) -> str:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return base64.b64encode(bytes(data)).decode("ascii")


def _tip_image(tip: QImage) -> QImage:
    """Square, centred RGBA mask (alpha = paint) as Nebula bitmap tips expect."""
    import numpy as np
    if max(tip.width(), tip.height()) > MAX_TIP:
        tip = tip.scaled(MAX_TIP, MAX_TIP, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    tip = tip.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height = tip.width(), tip.height()
    side = max(width, height)
    gray = np.frombuffer(tip.constBits(), np.uint8).reshape(height, tip.bytesPerLine())[:, :width]
    square = np.zeros((side, side), np.uint8)
    square[(side - height) // 2:(side - height) // 2 + height,
           (side - width) // 2:(side - width) // 2 + width] = gray
    rgba = np.ascontiguousarray(np.stack([square] * 4, axis=-1)).tobytes()
    return _image_from_rows(rgba, side, side, QImage.Format.Format_RGBA8888, 4)


def _number(node, default=0.0) -> float:
    if isinstance(node, dict) and "v" in node:
        return float(node["v"])
    if isinstance(node, (int, float)):
        return float(node)
    return float(default)


def _pen_controlled(variation) -> bool:
    return isinstance(variation, dict) and variation.get("bVTy") == 2   # 2 = pen pressure


@dataclass
class AbrBrush:
    name: str
    settings: dict
    notes: list[str] = field(default_factory=list)


def convert_preset(preset: dict, tips: dict, patterns: dict) -> AbrBrush | None:
    tip = preset.get("Brsh") or {}
    name = str(preset.get("Nm  ") or tip.get("Nm  ") or "Pinceau importé").strip()
    notes: list[str] = []
    diameter = _number(tip.get("Dmtr"), 30.0)
    # Start from the complete default state: loading a preset only updates
    # the keys it contains, so a partial preset would inherit wet mixing or
    # a texture from whatever brush was active before.
    from TOOLS.brush_settings_state import DEFAULT_BRUSH_SETTINGS
    settings: dict = {key: value for key, value in DEFAULT_BRUSH_SETTINGS.items()
                      if key not in ("color", "gradientColor")}
    settings["_csbr_texture_png"] = ""
    settings["_csbr_dual_tip_png"] = ""
    settings.update({
        "size": max(1.0, min(1000.0, diameter)),
        "opacity": 1.0, "flow": 1.0,
        "spacing": max(0.01, min(5.0, _number(tip.get("Spcn"), 25.0) / 100.0)),
        "angle": _number(tip.get("Angl"), 0.0),
        "roundness": max(0.01, min(1.0, _number(tip.get("Rndn"), 100.0) / 100.0)),
        "hardness": 1.0,
        "pressureSize": False, "pressureOpacity": False, "pressureFlow": False,
        "minimumSize": 0.01, "minimumOpacity": 0.0, "minimumFlow": 0.0,
        "scatter": 0.0, "sizeJitter": 0.0, "rotationJitter": 0.0,
        "directionFollow": 0.0, "textureStrength": 0.0, "textureCanvasSpace": False,
        "eraser": False, "smudgeTool": False, "wetMix": False,
    })
    if tip.get("_class") == "computedBrush":
        settings["hardness"] = max(0.0, min(1.0, _number(tip.get("Hrdn"), 100.0) / 100.0))
        settings["_csbr_bitmap_tip_png"] = ""
    else:
        image = tips.get(tip.get("sampledData", ""))
        if image is None:
            return None                      # tip missing from the file
        settings["_csbr_bitmap_tip_png"] = _png_base64(_tip_image(image))

    if preset.get("useTipDynamics"):
        size_dyn = preset.get("szVr")
        if _pen_controlled(size_dyn):
            settings["pressureSize"] = True
            settings["minimumSize"] = max(0.01, _number(preset.get("minimumDiameter"), 0.0) / 100.0)
        if isinstance(size_dyn, dict):
            settings["sizeJitter"] = min(1.0, _number(size_dyn.get("jitter")) / 100.0)
        angle_dyn = preset.get("angleDynamics")
        if isinstance(angle_dyn, dict):
            settings["rotationJitter"] = min(360.0, _number(angle_dyn.get("jitter")) * 3.6)
            if angle_dyn.get("bVTy") == 6:   # 6 = initial direction / direction
                settings["directionFollow"] = 1.0

    if preset.get("usePaintDynamics"):
        for key, flag, minimum in (("opVr", "pressureOpacity", "minimumOpacity"),
                                   ("prVr", "pressureFlow", "minimumFlow")):
            variation = preset.get(key)
            if _pen_controlled(variation):
                settings[flag] = True
                settings[minimum] = min(1.0, _number(variation.get("Mnm ")) / 100.0)

    if preset.get("useScatter"):
        settings["scatter"] = min(5.0, _number(preset.get("Sctr"), 0.0) / 100.0)

    if preset.get("useTexture"):
        pattern = patterns.get((preset.get("Txtr") or {}).get("Idnt", ""))
        if pattern is not None:
            pattern_name, pattern_image = pattern
            width = pattern_image.width()
            scale = _number(preset.get("textureScale"), 100.0) / 100.0
            if max(pattern_image.width(), pattern_image.height()) > MAX_PATTERN:
                pattern_image = pattern_image.scaled(
                    MAX_PATTERN, MAX_PATTERN, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            if preset.get("InvT"):
                pattern_image.invertPixels()
            settings.update(
                _csbr_texture_png=_png_base64(pattern_image),
                textureCanvasSpace=not bool(preset.get("TxtC")),
                textureScale=max(0.05, width * scale / 256.0),
                textureStrength=min(0.9, _number(preset.get("textureDepth"), 100.0) / 100.0),
                textureRandomOffset=0.0, textureRandomScale=0.0, textureMirror=False,
                textureAffectOpacity=True,
            )
        else:
            notes.append("texture absente du fichier")

    dual = preset.get("dualBrush")
    if isinstance(dual, dict) and dual.get("useDualBrush"):
        second = dual.get("Brsh") or {}
        second_diameter = _number(second.get("Dmtr"), diameter)
        settings.update(
            dualBrush=True,
            dualSizeRatio=max(0.05, min(10.0, second_diameter / max(1.0, diameter))),
            dualSpacing=max(0.01, min(10.0, _number(second.get("Spcn"), 25.0) / 100.0)),
            dualScatter=(min(10.0, _number((dual.get("scatterDynamics") or {}).get("jitter")) / 100.0)
                         if dual.get("useScatter") else 0.0),
            dualCount=float(max(1, min(16, round(_number(dual.get("Cnt "), 1.0))))),
            dualHardness=1.0, _csbr_dual_tip_png="",
        )
        if second.get("_class") == "computedBrush":
            settings["dualHardness"] = max(0.0, min(1.0, _number(second.get("Hrdn"), 100.0) / 100.0))
        else:
            second_tip = tips.get(second.get("sampledData", ""))
            if second_tip is not None:
                settings["_csbr_dual_tip_png"] = _png_base64(_tip_image(second_tip))
            else:
                settings["dualBrush"] = False
                notes.append("pointe secondaire absente du fichier")
        mode = (dual.get("BlnM") or {}).get("enum", "")
        modes = {"Mltp": 0, "Drkn": 1, "CBrn": 2, "linearBurn": 3, "Ovrl": 4,
                 "CDdg": 5, "hardMix": 6, "linearHeight": 7}
        settings["dualMode"] = float(modes.get(mode, 0))
        if mode and mode not in modes:
            notes.append("double pointe : mode de fusion approché par Produit")
    if preset.get("useColorDynamics"):
        # Photoshop: hue jitter 100 % = ±180°; saturation/brightness in %.
        settings["hueJitter"] = min(180.0, _number(preset.get("H   ")) * 1.8)
        settings["saturationJitter"] = min(1.0, _number(preset.get("Strt")) / 100.0)
        settings["brightnessJitter"] = min(1.0, _number(preset.get("Brgh")) / 100.0)
    return AbrBrush(name, settings, notes)


@dataclass
class AbrFile:
    version: int
    brushes: list[AbrBrush]
    skipped: int = 0


def read_abr(path: str | Path) -> AbrFile:
    data = Path(path).read_bytes()
    if len(data) < 4:
        raise AbrError("fichier vide")
    version, subversion = struct.unpack(">HH", data[:4])
    if version in (1, 2):
        raise AbrError("format .abr de Photoshop 7 ou antérieur, non pris en charge")
    if version not in (6, 7, 9, 10):
        raise AbrError(f"version .abr {version} inconnue")
    sections = _sections(data)
    if "samp" not in sections and "desc" not in sections:
        raise AbrError("aucune section de pinceau trouvée")
    try:
        tips = _read_tips(sections.get("samp", b""), subversion)
        patterns = _read_patterns(sections.get("patt", b""))
        presets: list[dict] = []
        if sections.get("desc"):
            reader = _Reader(sections["desc"])
            reader.u32()
            presets = list(_descriptor(reader).get("Brsh") or [])
    except (struct.error, IndexError, UnicodeDecodeError) as error:
        raise AbrError(f"fichier .abr endommagé ({error})") from error
    brushes: list[AbrBrush] = []
    skipped = 0
    if presets:
        for preset in presets:
            brush = convert_preset(preset, tips, patterns) if isinstance(preset, dict) else None
            if brush is None:
                skipped += 1
            else:
                brushes.append(brush)
    else:  # tips without presets: one plain brush per tip
        for index, image in enumerate(tips.values(), start=1):
            brushes.append(AbrBrush(f"Pointe {index}", {
                "size": float(min(1000, max(image.width(), image.height()))), "spacing": 0.25,
                "_csbr_bitmap_tip_png": _png_base64(_tip_image(image))}))
    return AbrFile(version, brushes, skipped)


def import_abr(path: str | Path, manager) -> tuple[list[str], list[str]]:
    """Add every brush of *path* to *manager*; return (names, report lines)."""
    abr = read_abr(path)
    category = f"Importé — {Path(path).stem}"[:60]
    manager.add_category(category)
    names: list[str] = []
    report: list[str] = []
    taken = set(manager.list_presets())
    for brush in abr.brushes:
        base = brush.name or "Pinceau importé"
        if manager.canonical(base) != base:      # would alias a factory preset
            base = f"{base} (ABR)"
        name, counter = base, 2
        while name in taken:
            name, counter = f"{base} ({counter})", counter + 1
        taken.add(name)
        try:
            manager.save(name, brush.settings)
        except (OSError, PermissionError) as error:
            report.append(f"{name} : échec d'enregistrement ({error})")
            continue
        manager.set_metadata(name, category=category)
        names.append(name)
        if brush.notes:
            report.append(f"{name} : " + ", ".join(brush.notes))
    if abr.skipped:
        report.append(f"{abr.skipped} pinceau(x) sans pointe dans le fichier, ignoré(s)")
    return names, report


__all__ = ["AbrError", "read_abr", "import_abr"]
