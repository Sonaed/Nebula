"""Test-only NumPy oracle for checking CreativeCore compositing parity."""
from __future__ import annotations

import sys

import numpy as np
from PySide6.QtGui import QImage


_OPPOSITE = {
    "multiply": "screen", "screen": "multiply",
    "overlay": "hard_light", "hard_light": "overlay",
    "color_dodge": "color_burn", "color_burn": "color_dodge",
    "hue": "luminosity", "luminosity": "hue",
}
_BOUNDS = {
    "opacity": (0.0, 1.0), "opposite_mix": (0.0, 1.0),
    "intensity": (0.0, 1.0), "gamma": (0.5, 2.5),
    "mix_normal": (0.0, 1.0), "pivot": (0.0, 1.0),
    "clamp": (0.0, 1.0), "softness": (0.0, 1.0),
    "hue_shift": (-180.0, 180.0), "saturation_boost": (0.0, 2.0),
    "offset": (0.0, 1.0),
}
_DEFAULTS = {
    "opacity": 1.0, "opposite_mix": 0.0, "intensity": 1.0,
    "gamma": 1.0, "mix_normal": 0.0, "pivot": 0.5,
    "clamp": 1.0, "softness": 0.5, "hue_shift": 0.0,
    "saturation_boost": 1.0, "offset": 0.0,
}


def _safe_parameter(params: dict, key: str, default: float) -> float:
    minimum, maximum = _BOUNDS[key]
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        return default
    if not np.isfinite(value):
        return default
    return min(maximum, max(minimum, value))


def _hsl(rgb: np.ndarray):
    maximum, minimum = rgb.max(axis=2), rgb.min(axis=2)
    delta = maximum - minimum
    lightness = (maximum + minimum) * 0.5
    saturation = np.divide(delta, 1.0 - np.abs(2.0 * lightness - 1.0),
                           out=np.zeros_like(delta), where=delta > 1e-8)
    hue = np.zeros_like(delta)
    nonzero = delta > 1e-8
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = nonzero & (maximum == red)
    hue[mask] = ((green[mask] - blue[mask]) / delta[mask]) % 6.0
    mask = nonzero & (maximum == green)
    hue[mask] = ((blue[mask] - red[mask]) / delta[mask]) + 2.0
    mask = nonzero & (maximum == blue)
    hue[mask] = ((red[mask] - green[mask]) / delta[mask]) + 4.0
    return (hue / 6.0) % 1.0, saturation, lightness


def _from_hsl(hue: np.ndarray, saturation: np.ndarray, lightness: np.ndarray):
    chroma = (1.0 - np.abs(2.0 * lightness - 1.0)) * saturation
    x = chroma * (1.0 - np.abs((hue * 6.0) % 2.0 - 1.0))
    zero = np.zeros_like(chroma)
    sectors = np.floor(hue * 6.0).astype(np.int8) % 6
    rgb = np.stack((
        np.select([sectors == 0, sectors == 1, sectors == 2, sectors == 3, sectors == 4, sectors == 5],
                  [chroma, chroma, zero, zero, x, x]),
        np.select([sectors == 0, sectors == 1, sectors == 2, sectors == 3, sectors == 4, sectors == 5],
                  [x, chroma, chroma, x, zero, zero]),
        np.select([sectors == 0, sectors == 1, sectors == 2, sectors == 3, sectors == 4, sectors == 5],
                  [zero, zero, x, chroma, chroma, x]),
    ), axis=2)
    return rgb + (lightness - chroma * 0.5)[..., None]


def _blend_rgb(backdrop: np.ndarray, source: np.ndarray, mode: str, params: dict):
    b, s = backdrop, source
    if mode == "darken": return np.minimum(b, s)
    if mode == "multiply":
        return np.power(np.clip(b * s, 0.0, 1.0), 1.0 / max(0.01, float(params.get("gamma", 1.0))))
    if mode == "lighten": return np.maximum(b, s)
    if mode == "screen":
        value = 1.0 - (1.0 - b) * (1.0 - s)
        return np.power(np.clip(value, 0.0, 1.0), 1.0 / max(0.01, float(params.get("gamma", 1.0))))
    if mode == "color_burn":
        value = 1.0 - np.divide(1.0 - b, s, out=np.ones_like(b), where=s > 1e-8)
        return np.minimum(np.clip(value, 0.0, 1.0), float(params.get("clamp", 1.0)))
    if mode == "color_dodge":
        value = np.divide(b, 1.0 - s, out=np.ones_like(b), where=s < 1.0 - 1e-8)
        return np.minimum(np.clip(value, 0.0, 1.0), float(params.get("clamp", 1.0)))
    if mode in ("overlay", "hard_light"):
        pivot = min(0.9999, max(0.0001, float(params.get("pivot", 0.5))))
        low = b * s / pivot
        high = 1.0 - (1.0 - b) * (1.0 - s) / (1.0 - pivot)
        return np.where((b if mode == "overlay" else s) < pivot, low, high)
    if mode == "soft_light":
        d = np.where(b <= 0.25, ((16.0 * b - 12.0) * b + 4.0) * b, np.sqrt(np.clip(b, 0.0, 1.0)))
        standard = np.where(s <= 0.5, b - (1.0 - 2.0 * s) * b * (1.0 - b), b + (2.0 * s - 1.0) * (d - b))
        strength = (float(params.get("softness", 0.5)) - 0.5) * 2.0
        return np.clip(b + (standard - b) * strength, 0.0, 1.0)
    if mode == "difference": return np.abs(b - np.clip(s + float(params.get("offset", 0.0)), 0.0, 1.0))
    if mode == "exclusion":
        shifted = np.clip(s + float(params.get("offset", 0.0)), 0.0, 1.0)
        return b + shifted - 2.0 * b * shifted
    if mode in ("hue", "saturation", "color", "luminosity"):
        hb, sb, lb = _hsl(b)
        hs, ss, ls = _hsl(s)
        hs = (hs + float(params.get("hue_shift", 0.0)) / 360.0) % 1.0
        ss = np.clip(ss * float(params.get("saturation_boost", 1.0)), 0.0, 1.0)
        if mode == "hue": return _from_hsl(hs, sb, lb)
        if mode == "saturation": return _from_hsl(hb, ss, lb)
        if mode == "color": return _from_hsl(hs, ss, lb)
        return _from_hsl(hb, sb, ls)
    return s


def _composite_candidate(backdrop_rgb, backdrop_a, source_rgb, source_a, mode, params):
    blend = _blend_rgb(backdrop_rgb, source_rgb, mode, params)
    out_a = source_a + backdrop_a * (1.0 - source_a)
    premultiplied = (source_rgb * source_a[..., None] * (1.0 - backdrop_a[..., None])
                     + blend * (source_a * backdrop_a)[..., None]
                     + backdrop_rgb * backdrop_a[..., None] * (1.0 - source_a[..., None]))
    out_rgb = np.divide(premultiplied, out_a[..., None], out=np.zeros_like(premultiplied),
                        where=out_a[..., None] > 1e-8)
    return out_rgb, out_a


def _qimage_rgba(image: QImage, x: int = 0, y: int = 0,
                 width: int | None = None, height: int | None = None) -> np.ndarray:
    width = image.width() - x if width is None else width
    height = image.height() - y if height is None else height
    source = image
    if source.format() not in (QImage.Format.Format_ARGB32,
            QImage.Format.Format_ARGB32_Premultiplied, QImage.Format.Format_RGB32,
            QImage.Format.Format_RGBA8888, QImage.Format.Format_RGBA8888_Premultiplied):
        source = source.convertToFormat(QImage.Format.Format_ARGB32)
    row_bytes = source.bytesPerLine()
    raw = np.frombuffer(source.constBits(), dtype=np.uint8,
                        count=row_bytes * source.height()).reshape(source.height(), row_bytes)
    pixels = raw[y:y + height, x * 4:(x + width) * 4].reshape(height, width, 4)
    pixels = pixels.astype(np.float32) / 255.0
    source_format = source.format()
    if source_format in (QImage.Format.Format_ARGB32, QImage.Format.Format_ARGB32_Premultiplied,
                         QImage.Format.Format_RGB32):
        if sys.byteorder == "little":
            rgb, alpha = pixels[..., [2, 1, 0]], pixels[..., 3]
        else:
            rgb, alpha = pixels[..., 1:4], pixels[..., 0]
    else:
        rgb, alpha = pixels[..., :3], pixels[..., 3]
    if source_format == QImage.Format.Format_RGB32:
        alpha = np.ones((height, width), dtype=np.float32)
    elif source_format in (QImage.Format.Format_ARGB32_Premultiplied,
                           QImage.Format.Format_RGBA8888_Premultiplied):
        rgb = np.divide(rgb, alpha[..., None], out=np.zeros_like(rgb), where=alpha[..., None] > 1e-8)
    return np.concatenate((rgb, alpha[..., None]), axis=2)


def composite_reference(width: int, height: int, layers) -> QImage:
    output = QImage(width, height, QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(output.bits(), dtype=np.uint8,
                           count=width * height * 4).reshape(height, width, 4)
    for y in range(0, height, 512):
        tile_height = min(512, height - y)
        for x in range(0, width, 512):
            tile_width = min(512, width - x)
            rgb = np.zeros((tile_height, tile_width, 3), dtype=np.float32)
            alpha = np.zeros((tile_height, tile_width), dtype=np.float32)
            clip_alpha = np.zeros((tile_height, tile_width), dtype=np.float32)
            for layer in layers:
                if not layer.visible:
                    continue
                raw = getattr(layer, "blend_parameters", {}) or {}
                raw = dict(raw) if isinstance(raw, dict) else {}
                params = {key: _safe_parameter(raw, key, default) for key, default in _DEFAULTS.items()}
                source = _qimage_rgba(layer.image, x, y, tile_width, tile_height)
                src_rgb = source[..., :3]
                src_alpha = np.clip(source[..., 3] * float(layer.opacity) * params["opacity"], 0.0, 1.0)
                clipped = bool(getattr(layer, "clipping", False))
                if clipped:
                    src_alpha *= clip_alpha
                else:
                    clip_alpha = src_alpha.copy()
                mode = str(getattr(layer, "blend_mode", "normal")).lower()
                mode_result = _composite_candidate(rgb, alpha, src_rgb, src_alpha, mode, params)
                normal_result = _composite_candidate(rgb, alpha, src_rgb, src_alpha, "normal", params)
                opposite = _OPPOSITE.get(mode)
                weights = [(mode_result, params["intensity"] * (1 - params["mix_normal"]) * (1 - params["opposite_mix"])),
                           (normal_result, 1 - params["intensity"] * (1 - params["mix_normal"]))]
                if opposite:
                    weights.append((_composite_candidate(rgb, alpha, src_rgb, src_alpha, opposite, params),
                                    params["intensity"] * (1 - params["mix_normal"]) * params["opposite_mix"]))
                total = sum(weight for _, weight in weights)
                if total <= 0:
                    continue
                mixed_alpha = sum(result[1] * weight for result, weight in weights) / total
                mixed_premul = sum(result[0] * result[1][..., None] * weight
                                   for result, weight in weights) / total
                rgb = np.divide(mixed_premul, mixed_alpha[..., None], out=np.zeros_like(mixed_premul),
                                where=mixed_alpha[..., None] > 1e-8)
                alpha = alpha if clipped else mixed_alpha
            pixels[y:y + tile_height, x:x + tile_width, :3] = np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)
            pixels[y:y + tile_height, x:x + tile_width, 3] = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    return output
