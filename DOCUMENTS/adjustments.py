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
    vibrance: VibranceAdjustment = field(default_factory=VibranceAdjustment)
    color_balance: ColorBalanceAdjustment = field(default_factory=ColorBalanceAdjustment)
    threshold: int = 128
    posterize: int = 4
    parametric_curves: ParametricCurvesAdjustment = field(default_factory=ParametricCurvesAdjustment)
    selective_color: SelectiveColorAdjustment = field(default_factory=SelectiveColorAdjustment)
    luminosity_mask: LuminosityMaskAdjustment = field(default_factory=LuminosityMaskAdjustment)


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
    result.detach()  # convertToFormat partage les données si le format est déjà bon
    return result


def _apply_tables(image: QImage, red, green, blue) -> QImage:
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


__all__ = ["AdjustmentLayerSpec", "CurvesAdjustment", "LevelsAdjustment",
           "HueSaturationAdjustment", "ExposureAdjustment", "VibranceAdjustment",
           "ColorBalanceAdjustment", "ParametricCurvesAdjustment",
           "SelectiveColorAdjustment", "LuminosityMaskAdjustment",
           "apply_adjustment", "apply_curves",
           "apply_levels", "apply_hue_saturation", "apply_exposure",
           "apply_vibrance", "apply_invert", "apply_threshold", "apply_posterize",
           "apply_color_balance", "apply_parametric_curves", "apply_selective_color",
           "apply_layer_effects"]
