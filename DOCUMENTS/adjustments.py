"""Non-destructive raster adjustment primitives used by adjustment layers.

The functions operate on RGBA8888 images and return a new image, leaving the
source untouched.  They intentionally keep the model independent of widgets,
which makes the same pipeline usable by previews, export and PSD import.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from PySide6.QtGui import QImage
from CORE.native_bridge import apply_rgb_lut_native
from CORE.native_filters import load_filters


@dataclass(frozen=True)
class CurvesAdjustment:
    points: tuple[tuple[int, int], ...] = ((0, 0), (255, 255))
    channels: dict[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class LevelsAdjustment:
    black: int = 0
    white: int = 255
    gamma: float = 1.0
    output_black: int = 0
    output_white: int = 255


@dataclass(frozen=True)
class HueSaturationAdjustment:
    hue: float = 0.0
    saturation: float = 0.0
    lightness: float = 0.0


@dataclass(frozen=True)
class ExposureAdjustment:
    exposure: float = 0.0
    offset: float = 0.0
    gamma: float = 1.0


@dataclass(frozen=True)
class BrightnessContrastAdjustment:
    """Photoshop-style channel brightness/contrast, stored in percent."""
    brightness: float = 0.0
    contrast: float = 0.0


@dataclass(frozen=True)
class VibranceAdjustment:
    vibrance: float = 0.0
    saturation: float = 0.0


@dataclass(frozen=True)
class ColorBalanceAdjustment:
    shadows: tuple[float, float, float] = (0.0, 0.0, 0.0)
    midtones: tuple[float, float, float] = (0.0, 0.0, 0.0)
    highlights: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ParametricCurvesAdjustment:
    black: float = 0.0
    shadows: float = 0.0
    midtones: float = 0.0
    highlights: float = 0.0
    white: float = 0.0


@dataclass(frozen=True)
class SelectiveColorAdjustment:
    channels: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class LuminosityMaskAdjustment:
    mode: str = "none"
    amount: float = 1.0
    feather: float = 0.15
    invert: bool = False


@dataclass
class AdjustmentLayerSpec:
    kind: str
    curves: CurvesAdjustment = field(default_factory=CurvesAdjustment)
    levels: LevelsAdjustment = field(default_factory=LevelsAdjustment)
    hue_saturation: HueSaturationAdjustment = field(default_factory=HueSaturationAdjustment)
    exposure: ExposureAdjustment = field(default_factory=ExposureAdjustment)
    brightness_contrast: BrightnessContrastAdjustment = field(default_factory=BrightnessContrastAdjustment)
    vibrance: VibranceAdjustment = field(default_factory=VibranceAdjustment)
    color_balance: ColorBalanceAdjustment = field(default_factory=ColorBalanceAdjustment)
    threshold: int = 128
    posterize: int = 4
    parametric_curves: ParametricCurvesAdjustment = field(default_factory=ParametricCurvesAdjustment)
    selective_color: SelectiveColorAdjustment = field(default_factory=SelectiveColorAdjustment)
    luminosity_mask: LuminosityMaskAdjustment = field(default_factory=LuminosityMaskAdjustment)
    # Photoshop-compatible adjustments (PSD import, ABI 5).  Plain dicts so
    # the document model stays JSON-serializable:
    #   gradient_map = {"stops": [{"location", "midpoint", "color"}], "reverse",
    #                   "method", "smoothness"}
    #   color_lookup = {"size", "encoding", "sha1", "data"} (see psd_reader.encode_lut)
    gradient_map: dict = field(default_factory=dict)
    color_lookup: dict = field(default_factory=dict)


# Kinds that deliberately leave the pixels unchanged: an imported Photoshop
# adjustment Nebula cannot evaluate keeps its place (and its settings) in the
# stack instead of breaking the whole projection.
PASSTHROUGH_KINDS = {"unsupported", "none"}


_OUTDATED = "Ce réglage requiert un CreativeCore récent (filtres ABI >= 4)."


def _native_filters():
    """Bibliothèque de filtres native, ou erreur explicite.

    Il n'existe volontairement aucun repli Python : les pixels ne sont jamais
    recalculés côté interface (voir test_architecture_boundaries).
    """
    filters = load_filters()
    if filters is None or not filters.supports_adjustments:
        raise RuntimeError(_OUTDATED)
    return filters


def _rgba_copy(image: QImage) -> QImage:
    """Copie RGBA8888 détachée : l'original n'est jamais modifié."""
    result = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if result.isNull():
        return result
    if hasattr(result, "detach"):
        result.detach()  # convertToFormat partage les données si le format est déjà bon
    return result


class _TableCapture(Exception):
    """Raised inside _apply_tables while stack_table() records a LUT."""

    def __init__(self, tables):
        super().__init__("table captured")
        self.tables = tables


_CAPTURING = False


def _apply_tables(image: QImage, red, green, blue) -> QImage:
    if _CAPTURING:
        raise _TableCapture(tuple(bytes(np.asarray(t, dtype=np.uint8).reshape(256))
                                  for t in (red, green, blue)))
    result = apply_rgb_lut_native(image, red, green, blue)
    if result is None:
        raise RuntimeError("CreativeCore est requis pour appliquer ce réglage "
                           "(cs_apply_rgb_lut indisponible).")
    return result


def apply_curves(image: QImage, adjustment: CurvesAdjustment) -> QImage:
    def lut_for(points):
        points = sorted((max(0, min(255, int(x))), max(0, min(255, int(y)))) for x, y in points)
        if not points or points[0][0] != 0:
            points.insert(0, (0, 0))
        if points[-1][0] != 255:
            points.append((255, 255))
        return np.interp(np.arange(256), [p[0] for p in points], [p[1] for p in points])
    master = np.rint(lut_for(adjustment.points)).clip(0, 255).astype(np.uint8)
    channels = []
    for channel, component in (("red", 0), ("green", 1), ("blue", 2)):
        points = adjustment.channels.get(channel)
        lut = (np.rint(lut_for(points)).clip(0, 255).astype(np.uint8)
               if points else np.arange(256, dtype=np.uint8))
        channels.append(lut[master])
    return _apply_tables(image, *channels)


def apply_levels(image: QImage, adjustment: LevelsAdjustment) -> QImage:
    black, white = sorted((max(0, min(254, int(adjustment.black))),
                           max(1, min(255, int(adjustment.white)))))
    gamma = max(0.01, float(adjustment.gamma))
    out_black = max(0, min(255, int(adjustment.output_black)))
    out_white = max(out_black, min(255, int(adjustment.output_white)))
    lut = np.arange(256, dtype=np.float32)
    lut = np.clip((lut - black) / max(1, white - black), 0.0, 1.0)
    lut = np.power(lut, 1.0 / gamma) * (out_white - out_black) + out_black
    table = np.rint(lut).clip(0, 255).astype(np.uint8)
    return _apply_tables(image, table, table, table)


def apply_hue_saturation(image: QImage, adjustment: HueSaturationAdjustment) -> QImage:
    filters = _native_filters()
    result = _rgba_copy(image)
    if not result.isNull():
        filters.hue_saturation(result.bits(), result.width(), result.height(),
                               adjustment.hue, adjustment.saturation, adjustment.lightness,
                               stride=result.bytesPerLine())
    return result


def apply_exposure(image: QImage, adjustment: ExposureAdjustment) -> QImage:
    # Réglage purement par canal : une table de 256 entrées suffit (l'application
    # aux pixels reste native).  Même arithmétique float32 que l'ancien code.
    values = np.arange(256, dtype=np.float32) / 255.0
    values = np.clip(values * (2.0 ** float(adjustment.exposure)) + float(adjustment.offset), 0.0, 1.0)
    values = np.power(values, 1.0 / max(0.01, float(adjustment.gamma)))
    table = np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)
    return _apply_tables(image, table, table, table)


def apply_brightness_contrast(image: QImage, adjustment: BrightnessContrastAdjustment) -> QImage:
    """Apply the CreativeCore LUT builder through the shared native pixel path."""
    filters = _native_filters()
    table = filters.brightness_contrast_lut(
        max(-100.0, min(100.0, float(adjustment.brightness))),
        max(-100.0, min(100.0, float(adjustment.contrast))),
    )
    return _apply_tables(image, table, table, table)


def apply_vibrance(image: QImage, adjustment: VibranceAdjustment) -> QImage:
    filters = _native_filters()
    result = _rgba_copy(image)
    if not result.isNull():
        filters.vibrance(result.bits(), result.width(), result.height(),
                         adjustment.vibrance, adjustment.saturation,
                         stride=result.bytesPerLine())
    return result


def apply_invert(image: QImage) -> QImage:
    table = np.arange(255, -1, -1, dtype=np.uint8)
    return _apply_tables(image, table, table, table)


def apply_threshold(image: QImage, threshold: int = 128) -> QImage:
    filters = _native_filters()
    result = _rgba_copy(image)
    if not result.isNull():
        filters.threshold(result.bits(), result.width(), result.height(),
                          max(0, min(255, int(threshold))), stride=result.bytesPerLine())
    return result


def apply_posterize(image: QImage, levels: int = 4) -> QImage:
    levels = max(2, min(32, int(levels)))
    table = (np.floor(np.arange(256, dtype=np.float32) * levels / 256.0) *
             (255.0 / (levels - 1))).clip(0, 255).astype(np.uint8)
    return _apply_tables(image, table, table, table)


def apply_color_balance(image: QImage, adjustment: ColorBalanceAdjustment) -> QImage:
    filters = _native_filters()
    result = _rgba_copy(image)
    if not result.isNull():
        filters.color_balance(result.bits(), result.width(), result.height(),
                              adjustment.shadows, adjustment.midtones, adjustment.highlights,
                              stride=result.bytesPerLine())
    return result


def apply_parametric_curves(image: QImage, adjustment: ParametricCurvesAdjustment) -> QImage:
    x = np.arange(256, dtype=np.float32) / 255.0
    values = np.array((0.0, 0.25, 0.5, 0.75, 1.0), dtype=np.float32)
    shifts = np.array((adjustment.black, adjustment.shadows, adjustment.midtones,
                       adjustment.highlights, adjustment.white), dtype=np.float32) / 100.0
    anchors = np.clip(values + shifts * 0.25, 0.0, 1.0)
    lut = np.interp(x, values, anchors)
    table = np.rint(lut * 255.0).clip(0, 255).astype(np.uint8)
    return _apply_tables(image, table, table, table)


def apply_selective_color(image: QImage, adjustment: SelectiveColorAdjustment) -> QImage:
    """Couleur sélective, entièrement calculée par CreativeCore.

    Aucun repli Python : le noyau natif reproduit bit à bit l'ancienne version
    NumPy (vérifié par CPP_TEST/test_native_filters.py).  Sans bridge à jour on
    échoue explicitement plutôt que de recalculer les pixels côté Python.
    """
    filters = load_filters()
    if filters is None or not filters.supports_selective_color:
        raise RuntimeError(
            "La couleur sélective requiert un CreativeCore récent (filtres ABI >= 3).")
    # convertToFormat renvoie une image partagée si le format est déjà bon ;
    # bits() la détache, l'original n'est donc jamais modifié.
    result = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if result.isNull():
        return result
    filters.selective_color(result.bits(), result.width(), result.height(),
                            adjustment.channels, stride=result.bytesPerLine())
    return result


_GRADIENT_CACHE: dict[str, bytes] = {}


def gradient_map_table(settings: dict) -> bytes:
    """Cached wrapper: the table only depends on the settings, never the pixels."""
    key = repr(settings)
    table = _GRADIENT_CACHE.get(key)
    if table is None:
        if len(_GRADIENT_CACHE) > 64:
            _GRADIENT_CACHE.clear()
        table = _GRADIENT_CACHE[key] = _build_gradient_map_table(settings)
    return table


def _build_gradient_map_table(settings: dict) -> bytes:
    """256 RGBA entries (1024 bytes) for a Photoshop gradient map.

    Colour stops are interpolated linearly with Photoshop's midpoint bias
    (``midpoint`` = where the 50 % mix sits between two stops).  Measured
    against Photoshop 2026 composites this is within a few levels of the
    "Classic" smooth gradient, closer than a smoothstep approximation.
    """
    stops = sorted((dict(stop) for stop in settings.get("stops", ()) if "color" in stop),
                   key=lambda stop: float(stop.get("location", 0.0)))
    if not stops:
        stops = [{"location": 0.0, "color": (0, 0, 0)}, {"location": 1.0, "color": (255, 255, 255)}]
    locations = np.array([max(0.0, min(1.0, float(stop.get("location", 0.0)))) for stop in stops])
    colors = np.array([[float(c) for c in list(stop["color"])[:3]] for stop in stops])
    x = np.linspace(0.0, 1.0, 256)
    table = np.empty((256, 3), dtype=np.float64)
    for index, t in enumerate(x):
        if t <= locations[0]:
            table[index] = colors[0]
            continue
        if t >= locations[-1]:
            table[index] = colors[-1]
            continue
        k = int(np.searchsorted(locations, t, side="right") - 1)
        k = max(0, min(len(stops) - 2, k))
        span = max(1e-9, locations[k + 1] - locations[k])
        u = (t - locations[k]) / span
        midpoint = max(0.01, min(0.99, float(stops[k + 1].get("midpoint", 0.5))))
        if abs(midpoint - 0.5) > 1e-6:
            u = u ** (np.log(0.5) / np.log(midpoint))
        table[index] = colors[k] * (1.0 - u) + colors[k + 1] * u
    if settings.get("reverse"):
        table = table[::-1]
    rgba = np.empty((256, 4), dtype=np.uint8)
    rgba[:, :3] = np.rint(np.clip(table, 0, 255)).astype(np.uint8)
    rgba[:, 3] = 255
    return rgba.tobytes()


_LUT_CACHE: dict[str, tuple[int, np.ndarray]] = {}


def decode_color_lookup(settings: dict) -> tuple[int, np.ndarray]:
    """(size, float32 table) of a stored 3D LUT, cached by content hash."""
    import base64
    import zlib
    key = str(settings.get("sha1") or "")
    cached = _LUT_CACHE.get(key) if key else None
    if cached is not None:
        return cached
    size = int(settings.get("size", 0))
    if size < 2 or size > 256:
        raise ValueError("LUT 3D : taille invalide")
    raw = zlib.decompress(base64.b64decode(str(settings.get("data", ""))))
    values = np.frombuffer(raw, dtype="<u2").astype(np.float32) / 65535.0
    if values.size != size ** 3 * 3:
        raise ValueError("LUT 3D : données tronquées")
    result = (size, np.ascontiguousarray(values))
    if key:
        if len(_LUT_CACHE) > 16:
            _LUT_CACHE.clear()
        _LUT_CACHE[key] = result
    return result


def _psd_filters():
    filters = load_filters()
    if filters is None or not getattr(filters, "supports_psd_adjustments", False):
        raise RuntimeError("Ce réglage Photoshop requiert un CreativeCore récent (filtres ABI >= 5) : "
                           "recompilez Nebula (cmake --build).")
    return filters


def apply_gradient_map(image: QImage, settings: dict) -> QImage:
    filters = _psd_filters()
    result = _rgba_copy(image)
    if not result.isNull():
        filters.gradient_map(result.bits(), result.width(), result.height(),
                             gradient_map_table(settings), stride=result.bytesPerLine())
    return result


def apply_color_lookup(image: QImage, settings: dict) -> QImage:
    filters = _psd_filters()
    size, table = decode_color_lookup(settings)
    result = _rgba_copy(image)
    if not result.isNull():
        filters.lut3d(result.bits(), result.width(), result.height(), table, size,
                      stride=result.bytesPerLine())
    return result


def spec_from_dict(value) -> AdjustmentLayerSpec | None:
    """Build the evaluation spec of an adjustment layer from its stored dict."""
    if not isinstance(value, dict):
        return None
    def section(name):
        item = value.get(name, {})
        return item if isinstance(item, dict) else {}
    curves = section("curves")
    levels = section("levels")
    hsl = section("hue_saturation")
    exposure = section("exposure")
    brightness_contrast = section("brightness_contrast")
    vibrance = section("vibrance")
    balance = section("color_balance")
    parametric = section("parametric_curves")
    selective = section("selective_color")
    luminosity = section("luminosity_mask")
    return AdjustmentLayerSpec(
        kind=str(value.get("kind", "")),
        curves=CurvesAdjustment(
            tuple(tuple(point) for point in curves.get("points", ((0, 0), (255, 255)))),
            {str(channel): tuple(tuple(point) for point in points)
             for channel, points in dict(curves.get("channels", {}) or {}).items()
             if str(channel) in {"red", "green", "blue"} and isinstance(points, (list, tuple))},
        ),
        levels=LevelsAdjustment(**{key: levels[key] for key in
                                   ("black", "white", "gamma", "output_black", "output_white")
                                   if key in levels}),
        hue_saturation=HueSaturationAdjustment(**{key: hsl[key] for key in
                                                  ("hue", "saturation", "lightness") if key in hsl}),
        exposure=ExposureAdjustment(**{key: exposure[key] for key in
                                       ("exposure", "offset", "gamma") if key in exposure}),
        brightness_contrast=BrightnessContrastAdjustment(**{
            key: brightness_contrast[key] for key in ("brightness", "contrast")
            if key in brightness_contrast}),
        vibrance=VibranceAdjustment(**{key: vibrance[key] for key in
                                       ("vibrance", "saturation") if key in vibrance}),
        color_balance=ColorBalanceAdjustment(**{
            key: tuple(balance[key]) for key in ("shadows", "midtones", "highlights")
            if key in balance and isinstance(balance[key], (list, tuple)) and len(balance[key]) == 3}),
        threshold=int(value.get("threshold", 128)),
        posterize=int(value.get("posterize", 4)),
        parametric_curves=ParametricCurvesAdjustment(**{key: parametric[key] for key in
            ("black", "shadows", "midtones", "highlights", "white") if key in parametric}),
        selective_color=SelectiveColorAdjustment(channels={
            str(key): tuple(values) for key, values in dict(selective.get("channels", {}) or {}).items()
            if isinstance(values, (list, tuple)) and len(values) == 4}),
        luminosity_mask=LuminosityMaskAdjustment(**{key: luminosity[key] for key in
            ("mode", "amount", "feather", "invert") if key in luminosity}),
        gradient_map=section("gradient_map"),
        color_lookup=section("color_lookup"),
    )


_STACK_TABLE_CACHE: dict[str, tuple] = {}


def stack_table(value) -> tuple | None:
    """Native stack form of an adjustment layer: (kind, table, size) or None.

    kind: 0 = three 256-entry RGB tables (768 bytes), 1 = gradient map
    (1024 bytes RGBA), 2 = 3D LUT (float32, size³×3).  None means the
    adjustment needs the per-tile Python path (hue/saturation, vibrance,
    colour balance, selective colour, threshold, luminosity masks...).
    """
    global _CAPTURING
    spec = spec_from_dict(value)
    if spec is None:
        return None
    if str(spec.luminosity_mask.mode).lower() not in _MASK_OFF:
        return None
    kind = str(spec.kind).lower()
    key = repr(value)
    cached = _STACK_TABLE_CACHE.get(key)
    if cached is not None:
        return cached
    result = None
    if kind in {"gradient_map", "gradient-map"}:
        result = (1, gradient_map_table(spec.gradient_map), 0)
    elif kind in {"color_lookup", "color-lookup", "lut3d"}:
        size, table = decode_color_lookup(spec.color_lookup)
        result = (2, np.ascontiguousarray(table, dtype=np.float32), size)
    elif kind in PASSTHROUGH_KINDS:
        identity = bytes(range(256))
        result = (0, identity * 3, 0)
    else:
        builders = {
            "curves": lambda: apply_curves(None, spec.curves),
            "levels": lambda: apply_levels(None, spec.levels),
            "exposure": lambda: apply_exposure(None, spec.exposure),
            "brightness_contrast": lambda: apply_brightness_contrast(None, spec.brightness_contrast),
            "brightness-contrast": lambda: apply_brightness_contrast(None, spec.brightness_contrast),
            "invert": lambda: apply_invert(None), "negative": lambda: apply_invert(None),
            "posterize": lambda: apply_posterize(None, spec.posterize),
            "parametric_curves": lambda: apply_parametric_curves(None, spec.parametric_curves),
            "parametric-curves": lambda: apply_parametric_curves(None, spec.parametric_curves),
        }
        builder = builders.get(kind)
        if builder is None:
            return None
        _CAPTURING = True
        try:
            builder()
        except _TableCapture as captured:
            result = (0, b"".join(captured.tables), 0)
        except Exception:  # noqa: BLE001 - unexpected: use the Python path
            return None
        finally:
            _CAPTURING = False
        if result is None:
            return None
    if len(_STACK_TABLE_CACHE) > 64:
        _STACK_TABLE_CACHE.clear()
    _STACK_TABLE_CACHE[key] = result
    return result


_MASK_OFF = {"none", "", "off"}


def apply_adjustment(image: QImage, spec: AdjustmentLayerSpec) -> QImage:
    kind = str(spec.kind).lower()
    mask_mode = str(spec.luminosity_mask.mode).lower()
    if kind == "curves":
        adjusted = apply_curves(image, spec.curves)
    elif kind == "levels":
        adjusted = apply_levels(image, spec.levels)
    elif kind in {"hue_saturation", "hue-saturation", "hsl"}:
        adjusted = apply_hue_saturation(image, spec.hue_saturation)
    elif kind == "exposure":
        adjusted = apply_exposure(image, spec.exposure)
    elif kind in {"brightness_contrast", "brightness-contrast"}:
        adjusted = apply_brightness_contrast(image, spec.brightness_contrast)
    elif kind == "vibrance":
        adjusted = apply_vibrance(image, spec.vibrance)
    elif kind in {"invert", "negative"}:
        adjusted = apply_invert(image)
    elif kind == "threshold":
        adjusted = apply_threshold(image, spec.threshold)
    elif kind == "posterize":
        adjusted = apply_posterize(image, spec.posterize)
    elif kind in {"color_balance", "color-balance"}:
        adjusted = apply_color_balance(image, spec.color_balance)
    elif kind in {"parametric_curves", "parametric-curves"}:
        adjusted = apply_parametric_curves(image, spec.parametric_curves)
    elif kind in {"selective_color", "selective-color"}:
        adjusted = apply_selective_color(image, spec.selective_color)
    elif kind in {"gradient_map", "gradient-map"}:
        adjusted = apply_gradient_map(image, spec.gradient_map)
    elif kind in {"color_lookup", "color-lookup", "lut3d"}:
        adjusted = apply_color_lookup(image, spec.color_lookup)
    elif kind in PASSTHROUGH_KINDS:
        adjusted = image
    elif kind == "luminosity_mask":
        adjusted = image
    else:
        raise ValueError(f"Unknown adjustment layer: {spec.kind}")
    if mask_mode in _MASK_OFF:
        return adjusted
    # Mélange source/résultat selon la luminance de la source, calculé nativement.
    filters = _native_filters()
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)  # lecture seule
    result = _rgba_copy(adjusted)
    if source.isNull() or result.isNull():
        return result
    if source.size() != result.size():
        raise ValueError("Le réglage ne doit pas modifier les dimensions de l'image")
    mask = spec.luminosity_mask
    filters.luminosity_blend(result.bits(), result.width(), result.height(),
                             source.constBits(), mask_mode, mask.amount, mask.feather,
                             mask.invert, stride=result.bytesPerLine(),
                             source_stride=source.bytesPerLine())
    return result


_SHADOW_KINDS = {"drop_shadow", "dropshadow", "outer_glow"}


def apply_layer_effects(image: QImage, effects: list[dict] | None) -> QImage:
    """Effets de calque PSD portables (ombre portée, lueur externe, contour).

    Sans effet reconnu, l'image est renvoyée telle quelle : ce chemin est appelé
    pour chaque tuile projetée et ne doit rien recopier.  Sinon les pixels sont
    traités par CreativeCore ; l'ombre passe SOUS le calque.
    """
    known = [effect for effect in (effects or [])
             if str(effect.get("type", effect.get("kind", ""))).lower() in _SHADOW_KINDS | {"stroke"}]
    if not known:
        return image
    filters = _native_filters()
    result = _rgba_copy(image)
    if result.isNull():
        return result
    for effect in known:
        kind = str(effect.get("type", effect.get("kind", ""))).lower()
        if kind in _SHADOW_KINDS:
            filters.drop_shadow(result.bits(), result.width(), result.height(),
                                int(effect.get("offset_x", 4)), int(effect.get("offset_y", 4)),
                                max(1, min(32, int(effect.get("size", 6)))),
                                effect.get("color", (0, 0, 0, 160)), stride=result.bytesPerLine())
        else:
            filters.stroke(result.bits(), result.width(), result.height(),
                           max(1, min(32, int(effect.get("size", 2)))),
                           effect.get("color", (255, 255, 255, 255)), stride=result.bytesPerLine())
    return result


__all__ = ["spec_from_dict", "gradient_map_table", "decode_color_lookup", "apply_gradient_map",
           "apply_color_lookup", "PASSTHROUGH_KINDS", "AdjustmentLayerSpec", "CurvesAdjustment", "LevelsAdjustment",
           "HueSaturationAdjustment", "ExposureAdjustment", "VibranceAdjustment",
           "ColorBalanceAdjustment", "ParametricCurvesAdjustment",
           "SelectiveColorAdjustment", "LuminosityMaskAdjustment",
           "apply_adjustment", "apply_curves",
           "apply_levels", "apply_hue_saturation", "apply_exposure",
           "apply_vibrance", "apply_invert", "apply_threshold", "apply_posterize",
           "apply_color_balance", "apply_parametric_curves", "apply_selective_color",
           "apply_layer_effects"]
