"""Adaptateur Python des filtres raster CreativeCore (``cs_filter_*``).

Aucun traitement de pixels n'est fait ici : ce module ne fait que valider les
tampons et déléguer au moteur natif (règle d'architecture de Nebula). NumPy
n'est pas requis ; n'importe quel objet supportant le protocole buffer
inscriptible convient (``bytearray``, ``memoryview`` sur ``QImage.bits()``,
tableau ctypes, ``numpy.ndarray``...), au format RGBA8888 en alpha droit.

Les fonctions C ne peuvent pas connaître la taille réelle d'un tampon : la
vérification de longueur faite ici est la seule barrière contre un dépassement.

Utilisation::

    filters = load_filters()
    if filters is not None:
        filters.gaussian_blur(image_bytes, width, height, sigma=4.0)
"""
from __future__ import annotations

import ctypes
from typing import Optional

ABI_VERSION = 5          # version que cet adaptateur attend au mieux
# Modes du mélange par luminosité ; tout autre nom = masque plein (comportement
# historique).  Alias français conservés.
LUMINOSITY_MODES = {"lights": 1, "highlights": 1, "lumières": 1, "shadows": 2, "ombres": 2,
                    "midtones": 3, "midtone": 3, "tons_moyens": 3}
SELECTIVE_BANDS = ("reds", "yellows", "greens", "cyans", "blues", "magentas",
                   "whites", "neutrals", "blacks")
MIN_ABI_VERSION = 1      # les filtres simples existent depuis l'ABI 1
DESCRIPTOR_BYTES = 76
EDGE_CLAMP = 0
EDGE_WRAP = 1

# Identifiants stables des types de filtre (écrits dans les fichiers : ne jamais
# renuméroter).  Paramètres : voir CPP_CORE/include/filter_layer.h.
FILTER_KINDS = {
    "gaussian_blur": 1, "box_blur": 2, "motion_blur": 3, "unsharp_mask": 4,
    "median": 5, "pixelate": 6, "edge_detect": 7, "emboss": 8, "invert": 9,
    "desaturate": 10, "hsv_adjust": 11, "posterize": 12, "threshold": 13,
    "noise": 14, "color_to_alpha": 15, "levels": 16, "brightness_contrast": 17,
    "curve": 18,
}
LAYER_KIND_RASTER = 0
LAYER_KIND_FILTER = 1

_BytePtr = ctypes.POINTER(ctypes.c_uint8)


class _StackEntry(ctypes.Structure):
    _fields_ = [("is_filter", ctypes.c_int), ("visible", ctypes.c_int),
                ("opacity", ctypes.c_float), ("raster_id", ctypes.c_int),
                ("payload", _BytePtr), ("payload_size", ctypes.c_int)]


_ComposeFn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                              ctypes.c_int, _BytePtr, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, _BytePtr)
_CoverageFn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, _BytePtr)


def raster_entry(raster_id: int, visible: bool = True) -> tuple:
    """Entrée de pile : calque raster identifié par ``raster_id``."""
    return ("raster", int(raster_id), bool(visible))


def filter_entry(payload: bytes, opacity: float = 1.0, visible: bool = True) -> tuple:
    """Entrée de pile : calque de filtre (charge de :meth:`NativeFilters.encode_filter`)."""
    return ("filter", bytes(payload), float(opacity), bool(visible))


def _view(pointer, length: int, readonly: bool = False):
    """Vue mémoire d'octets sur ``length`` octets natifs (valide pendant l'appel).

    ``cast("B")`` est nécessaire : le format natif d'un tableau ctypes (``<B``)
    n'autorise pas l'affectation par tranche.
    """
    view = memoryview((ctypes.c_uint8 * length).from_address(
        ctypes.addressof(pointer.contents))).cast("B")
    return view.toreadonly() if readonly else view


class FilterError(RuntimeError):
    """Le moteur natif a refusé l'opération (argument invalide)."""


def _writable_pointer(buffer, needed: int, what: str):
    view = memoryview(buffer)
    if view.readonly:
        raise ValueError(f"{what} doit être un tampon inscriptible")
    view = view.cast("B")
    if len(view) < needed:
        raise ValueError(f"{what} trop court : {len(view)} octets, {needed} requis")
    array = (ctypes.c_uint8 * len(view)).from_buffer(view)
    return array, view  # garder `view` vivant tant que le pointeur est utilisé


def _readable_pointer(buffer, needed: int, what: str):
    view = memoryview(buffer).cast("B")
    if len(view) < needed:
        raise ValueError(f"{what} trop court : {len(view)} octets, {needed} requis")
    if view.readonly:
        array = (ctypes.c_uint8 * len(view)).from_buffer_copy(view)
        return array, view
    return (ctypes.c_uint8 * len(view)).from_buffer(view), view


class NativeFilters:
    """Façade typée au-dessus de l'ABI ``cs_filter_*``."""

    def __init__(self, library) -> None:
        self._lib = library
        _declare(library)
        version = library.cs_filter_abi_version()
        if not MIN_ABI_VERSION <= version <= ABI_VERSION:
            raise OSError(f"ABI des filtres incompatible : {version} "
                          f"(attendu {MIN_ABI_VERSION}..{ABI_VERSION})")
        self.abi_version = version
        if version >= 2:
            _declare_layers(library)

    @property
    def supports_selective_color(self) -> bool:
        """Vrai si le bridge exporte ``cs_filter_selective_color`` (ABI >= 3)."""
        return self.abi_version >= 3

    @property
    def supports_adjustments(self) -> bool:
        """Vrai si le bridge exporte les noyaux de calques de réglage (ABI >= 4)."""
        return self.abi_version >= 4

    @property
    def supports_psd_adjustments(self) -> bool:
        """Vrai si le bridge exporte courbe de dégradé, LUT 3D et outils alpha (ABI >= 5)."""
        return self.abi_version >= 5

    def _require_psd(self) -> None:
        if not self.supports_psd_adjustments:
            raise FilterError("ce bridge est antérieur aux réglages Photoshop (ABI < 5) : "
                              "recompilez CreativeCore")

    def _require_adjustments(self) -> None:
        if not self.supports_adjustments:
            raise FilterError("ce bridge est antérieur aux calques de réglage natifs (ABI < 4)")

    @property
    def supports_filter_layers(self) -> bool:
        """Vrai si le bridge sait décrire, stocker et évaluer des calques de filtre."""
        return self.abi_version >= 2

    def _require_layers(self) -> None:
        if not self.supports_filter_layers:
            raise FilterError("ce bridge est antérieur aux calques de filtre (ABI < 2)")

    # ------------------------------------------------------------ interne --

    def _geometry(self, pixels, width: int, height: int, stride: Optional[int]):
        if width <= 0 or height <= 0:
            raise ValueError("width et height doivent être positifs")
        stride = width * 4 if stride is None else int(stride)
        if stride < width * 4:
            raise ValueError("stride < width * 4")
        needed = stride * (height - 1) + width * 4
        array, keep = _writable_pointer(pixels, needed, "pixels")
        return array, keep, stride

    def _mask(self, mask, width: int, height: int, mask_stride: Optional[int]):
        if mask is None:
            return None, None, 0
        mask_stride = width if mask_stride is None else int(mask_stride)
        if mask_stride < width:
            raise ValueError("mask_stride < width")
        needed = mask_stride * (height - 1) + width
        array, keep = _readable_pointer(mask, needed, "mask")
        return array, keep, mask_stride

    def _call(self, name: str, pixels, width, height, stride, mask, mask_stride,
              build):
        array, keep_p, stride = self._geometry(pixels, width, height, stride)
        marray, keep_m, mask_stride = self._mask(mask, width, height, mask_stride)
        ok = build(getattr(self._lib, name), array, stride, marray, mask_stride)
        del keep_p, keep_m  # libère les exports de buffer (redimensionnement possible)
        if not ok:
            raise FilterError(f"{name} : arguments refusés par CreativeCore")

    # -------------------------------------------------------------- flous --

    def gaussian_blur(self, pixels, width, height, sigma_x, sigma_y=None, *,
                      edge=EDGE_CLAMP, mask=None, stride=None, mask_stride=None):
        sigma_y = sigma_x if sigma_y is None else sigma_y
        self._call("cs_filter_gaussian_blur", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(sigma_x),
                                              float(sigma_y), int(edge), m, ms))

    def box_blur(self, pixels, width, height, radius_x, radius_y=None, *,
                 edge=EDGE_CLAMP, mask=None, stride=None, mask_stride=None):
        radius_y = radius_x if radius_y is None else radius_y
        self._call("cs_filter_box_blur", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(radius_x),
                                              int(radius_y), int(edge), m, ms))

    def motion_blur(self, pixels, width, height, angle_degrees, length, *,
                    edge=EDGE_CLAMP, mask=None, stride=None, mask_stride=None):
        self._call("cs_filter_motion_blur", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s,
                                              float(angle_degrees), float(length),
                                              int(edge), m, ms))

    def unsharp_mask(self, pixels, width, height, sigma, amount, threshold=0, *,
                     edge=EDGE_CLAMP, mask=None, stride=None, mask_stride=None):
        self._call("cs_filter_unsharp_mask", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(sigma),
                                              float(amount), int(threshold),
                                              int(edge), m, ms))

    def median(self, pixels, width, height, radius, *, mask=None, stride=None,
               mask_stride=None):
        self._call("cs_filter_median", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(radius), m, ms))

    def pixelate(self, pixels, width, height, block_width, block_height=None, *,
                 mask=None, stride=None, mask_stride=None):
        block_height = block_width if block_height is None else block_height
        self._call("cs_filter_pixelate", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(block_width),
                                              int(block_height), m, ms))

    # ------------------------------------------------- contours et relief --

    def edge_detect(self, pixels, width, height, strength=1.0, *, mask=None,
                    stride=None, mask_stride=None):
        self._call("cs_filter_edge_detect", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(strength),
                                              m, ms))

    def emboss(self, pixels, width, height, angle_degrees=135.0, depth=1.0, *,
               mask=None, stride=None, mask_stride=None):
        self._call("cs_filter_emboss", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s,
                                              float(angle_degrees), float(depth),
                                              m, ms))

    # ------------------------------------------------------------ couleur --

    def invert(self, pixels, width, height, *, mask=None, stride=None,
               mask_stride=None):
        self._call("cs_filter_invert", pixels, width, height, stride, mask,
                   mask_stride, lambda fn, a, s, m, ms: fn(a, width, height, s, m, ms))

    def desaturate(self, pixels, width, height, mode=0, *, mask=None, stride=None,
                   mask_stride=None):
        self._call("cs_filter_desaturate", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(mode), m, ms))

    def hsv_adjust(self, pixels, width, height, hue_degrees=0.0, saturation=0.0,
                   value=0.0, *, mask=None, stride=None, mask_stride=None):
        self._call("cs_filter_hsv_adjust", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(hue_degrees),
                                              float(saturation), float(value), m, ms))

    def selective_color(self, pixels, width, height, channels, *, mask=None,
                        stride=None, mask_stride=None):
        """Couleur sélective ; ``channels`` : nom de bande -> (C, M, Y, K) en %.

        Les noms inconnus sont ignorés (comme l'ancienne version NumPy) ; une
        bande absente n'est pas appliquée.
        """
        if not self.supports_selective_color:
            raise FilterError("ce bridge est antérieur à la couleur sélective (ABI < 3)")
        values = (ctypes.c_double * (len(SELECTIVE_BANDS) * 4))()
        enabled = 0
        for index, name in enumerate(SELECTIVE_BANDS):
            band = channels.get(name)
            if band is None:
                continue
            band = tuple(float(v) for v in band)
            if len(band) != 4:
                raise ValueError(f"bande {name!r} : 4 valeurs (C, M, Y, K) attendues")
            values[index * 4:index * 4 + 4] = band
            enabled |= 1 << index
        self._call("cs_filter_selective_color", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, values, enabled, m, ms))

    def hue_saturation(self, pixels, width, height, hue_degrees=0.0, saturation=0.0,
                       lightness=0.0, *, mask=None, stride=None, mask_stride=None):
        """Teinte (degrés) / saturation et clarté (%) : réglage « Teinte/Saturation »."""
        self._require_adjustments()
        self._call("cs_filter_hue_saturation", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(hue_degrees),
                                              float(saturation), float(lightness), m, ms))

    def vibrance(self, pixels, width, height, vibrance=0.0, saturation=0.0, *,
                 mask=None, stride=None, mask_stride=None):
        self._require_adjustments()
        self._call("cs_filter_vibrance", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(vibrance),
                                              float(saturation), m, ms))

    def color_balance(self, pixels, width, height, shadows=(0, 0, 0), midtones=(0, 0, 0),
                      highlights=(0, 0, 0), *, mask=None, stride=None, mask_stride=None):
        """Balance des couleurs : trois décalages RGB (%) par plage de luminance."""
        self._require_adjustments()
        groups = (tuple(shadows), tuple(midtones), tuple(highlights))
        if any(len(group) != 3 for group in groups):
            raise ValueError("chaque plage attend 3 valeurs (R, G, B)")
        values = (ctypes.c_double * 9)(*(float(v) for group in groups for v in group))
        self._call("cs_filter_color_balance", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, values, m, ms))

    def luminosity_blend(self, pixels, width, height, source, mode, amount=1.0,
                         feather=0.15, invert=False, *, stride=None, source_stride=None):
        """Mélange ``pixels`` (résultat d'un réglage) avec ``source`` selon la
        luminance de ``source``.  ``mode`` : voir :data:`LUMINOSITY_MODES`."""
        self._require_adjustments()
        code = LUMINOSITY_MODES.get(str(mode).lower(), 0) if not isinstance(mode, int) else int(mode)
        array, keep_p, stride = self._geometry(pixels, width, height, stride)
        source_stride = width * 4 if source_stride is None else int(source_stride)
        if source_stride < width * 4:
            raise ValueError("source_stride < width * 4")
        needed = source_stride * (height - 1) + width * 4
        source_array, keep_s = _readable_pointer(source, needed, "source")
        ok = self._lib.cs_filter_luminosity_blend(
            array, width, height, stride, source_array, source_stride, int(code),
            float(amount), float(feather), 1 if invert else 0)
        del keep_p, keep_s
        if not ok:
            raise FilterError("cs_filter_luminosity_blend : arguments refusés par CreativeCore")

    def drop_shadow(self, pixels, width, height, offset_x=4, offset_y=4, size=6,
                    color=(0, 0, 0, 160), *, stride=None):
        """Ombre portée / lueur externe, placée sous le calque (RGBA droit)."""
        self._require_adjustments()
        r, g, b, a = self._effect_color(color)
        array, keep, stride = self._geometry(pixels, width, height, stride)
        ok = self._lib.cs_filter_drop_shadow(array, width, height, stride, int(offset_x),
                                             int(offset_y), int(size), r, g, b, a)
        del keep
        if not ok:
            raise FilterError("cs_filter_drop_shadow : arguments refusés par CreativeCore")

    def stroke(self, pixels, width, height, size=2, color=(255, 255, 255, 255), *,
               stride=None):
        """Contour extérieur de la forme opaque (dilatation carrée de ``size`` px)."""
        self._require_adjustments()
        r, g, b, a = self._effect_color(color)
        array, keep, stride = self._geometry(pixels, width, height, stride)
        ok = self._lib.cs_filter_stroke(array, width, height, stride, int(size), r, g, b, a)
        del keep
        if not ok:
            raise FilterError("cs_filter_stroke : arguments refusés par CreativeCore")

    def gradient_map(self, pixels, width, height, table, *, mask=None, stride=None,
                     mask_stride=None):
        """Courbe de transfert de dégradé : ``table`` = 256 couleurs RGBA (1024 octets)."""
        self._require_psd()
        data = bytes(table)
        if len(data) != 1024:
            raise ValueError("la table d'une courbe de dégradé fait 1024 octets")
        table_array = (ctypes.c_uint8 * 1024).from_buffer_copy(data)
        self._call("cs_filter_gradient_map", pixels, width, height, stride, mask, mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, table_array, m, ms))

    def lut3d(self, pixels, width, height, table, size, *, mask=None, stride=None,
              mask_stride=None):
        """LUT 3D : ``table`` = size³×3 floats 0..1 (rouge le plus rapide)."""
        self._require_psd()
        size = int(size)
        count = size ** 3 * 3
        try:
            import numpy as np
            values = np.ascontiguousarray(table, dtype=np.float32).reshape(-1)
            if values.size != count:
                raise ValueError
            table_array = (ctypes.c_float * count).from_buffer_copy(values.tobytes())
        except ImportError:
            values = [float(v) for v in table]
            if len(values) != count:
                raise ValueError("taille de LUT 3D incohérente")
            table_array = (ctypes.c_float * count)(*values)
        except ValueError:
            raise ValueError("taille de LUT 3D incohérente") from None
        self._call("cs_filter_lut3d", pixels, width, height, stride, mask, mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, table_array, size, m, ms))

    def set_alpha(self, pixels, width, height, alpha=255, *, stride=None):
        self._require_psd()
        array, keep, stride = self._geometry(pixels, width, height, stride)
        ok = self._lib.cs_filter_set_alpha(array, width, height, stride, int(alpha))
        del keep
        if not ok:
            raise FilterError("cs_filter_set_alpha : arguments refusés par CreativeCore")

    def copy_alpha(self, pixels, width, height, source, *, stride=None, source_stride=None):
        """Copie l'alpha de ``source`` (RGBA8888 même taille) dans ``pixels``."""
        self._require_psd()
        array, keep_p, stride = self._geometry(pixels, width, height, stride)
        source_array, keep_s, source_stride = self._readable_pair(
            source, width, height, source_stride, "source")
        ok = self._lib.cs_filter_copy_alpha(array, width, height, stride, source_array,
                                            source_stride)
        del keep_p, keep_s
        if not ok:
            raise FilterError("cs_filter_copy_alpha : arguments refusés par CreativeCore")

    def _readable_pair(self, source, width, height, source_stride, what):
        source_stride = width * 4 if source_stride is None else int(source_stride)
        if source_stride < width * 4:
            raise ValueError(f"{what}_stride < width * 4")
        needed = source_stride * (height - 1) + width * 4
        array, keep = _readable_pointer(source, needed, what)
        return array, keep, source_stride

    def blend_by_alpha(self, pixels, width, height, changed, mask_source, *, stride=None,
                       changed_stride=None, mask_stride=None):
        """Réglage écrêté : ``pixels`` = mélange de ``pixels`` et ``changed`` selon l'alpha
        de ``mask_source`` (l'alpha de ``pixels`` est conservé)."""
        self._require_adjustments()
        array, keep_p, stride = self._geometry(pixels, width, height, stride)
        changed_array, keep_c, changed_stride = self._readable_pair(
            changed, width, height, changed_stride, "changed")
        mask_array, keep_m, mask_stride = self._readable_pair(
            mask_source, width, height, mask_stride, "mask_source")
        ok = self._lib.cs_filter_blend_by_alpha(array, width, height, stride, changed_array,
                                                changed_stride, mask_array, mask_stride)
        del keep_p, keep_c, keep_m
        if not ok:
            raise FilterError("cs_filter_blend_by_alpha : arguments refusés par CreativeCore")

    def selection_feather(self, mask, width, height, radius, *, stride=None):
        """Adoucit un masque de sélection 32 bits (valeur = octet alpha)."""
        self._require_adjustments()
        array, keep, stride = self._geometry(mask, width, height, stride)
        ok = self._lib.cs_filter_selection_feather(array, width, height, stride, int(radius))
        del keep
        if not ok:
            raise FilterError("cs_filter_selection_feather : arguments refusés par CreativeCore")

    def selection_morph(self, mask, width, height, radius, grow, *, stride=None):
        """Dilate (``grow``) ou érode un masque de sélection d'un rayon carré."""
        self._require_adjustments()
        array, keep, stride = self._geometry(mask, width, height, stride)
        ok = self._lib.cs_filter_selection_morph(array, width, height, stride, int(radius),
                                                 1 if grow else 0)
        del keep
        if not ok:
            raise FilterError("cs_filter_selection_morph : arguments refusés par CreativeCore")

    def select_color_range(self, mask, width, height, source, color, tolerance=16, *,
                           stride=None, source_stride=None):
        """Sélection douce autour de ``color`` (r, g, b) dans l'image RGBA ``source``."""
        self._require_adjustments()
        r, g, b = (int(v) for v in color[:3])
        array, keep_m, stride = self._geometry(mask, width, height, stride)
        source_array, keep_s, source_stride = self._readable_pair(
            source, width, height, source_stride, "source")
        ok = self._lib.cs_filter_select_color_range(array, width, height, stride, source_array,
                                                    source_stride, r, g, b, int(tolerance))
        del keep_m, keep_s
        if not ok:
            raise FilterError("cs_filter_select_color_range : arguments refusés par CreativeCore")

    @staticmethod
    def _effect_color(color) -> tuple:
        values = [int(v) for v in color]
        if len(values) == 3:
            values.append(255)
        if len(values) != 4:
            raise ValueError("une couleur d'effet attend 3 ou 4 composantes")
        return tuple(max(0, min(255, v)) for v in values)

    def posterize(self, pixels, width, height, levels, *, mask=None, stride=None,
                  mask_stride=None):
        self._call("cs_filter_posterize", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(levels), m, ms))

    def threshold(self, pixels, width, height, level, *, mask=None, stride=None,
                  mask_stride=None):
        self._call("cs_filter_threshold", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(level), m, ms))

    def add_noise(self, pixels, width, height, amount, *, seed=1, gaussian=True,
                  monochrome=False, affect_alpha=False, mask=None, stride=None,
                  mask_stride=None):
        self._call("cs_filter_add_noise", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, float(amount),
                                              int(seed) & 0xFFFFFFFFFFFFFFFF,
                                              int(bool(gaussian)),
                                              int(bool(monochrome)),
                                              int(bool(affect_alpha)), m, ms))

    def color_to_alpha(self, pixels, width, height, color, tolerance=0.0, *,
                       mask=None, stride=None, mask_stride=None):
        red, green, blue = (int(c) for c in color[:3])
        self._call("cs_filter_color_to_alpha", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, red, green, blue,
                                              float(tolerance), m, ms))

    # --------------------------------------------------------------- LUT ---

    def levels_lut(self, in_black=0, in_white=255, gamma=1.0, out_black=0,
                   out_white=255) -> bytes:
        lut = (ctypes.c_uint8 * 256)()
        self._lib.cs_filter_build_levels_lut(int(in_black), int(in_white),
                                             float(gamma), int(out_black),
                                             int(out_white), lut)
        return bytes(lut)

    def brightness_contrast_lut(self, brightness=0.0, contrast=0.0) -> bytes:
        lut = (ctypes.c_uint8 * 256)()
        self._lib.cs_filter_build_brightness_contrast_lut(float(brightness),
                                                          float(contrast), lut)
        return bytes(lut)

    def curve_lut(self, points) -> bytes:
        """LUT d'une courbe monotone passant par ``[(x, y), ...]`` dans [0, 1]²."""
        points = list(points)
        count = len(points)
        xs = (ctypes.c_double * count)(*(float(p[0]) for p in points))
        ys = (ctypes.c_double * count)(*(float(p[1]) for p in points))
        lut = (ctypes.c_uint8 * 256)()
        if not self._lib.cs_filter_build_curve_lut(xs, ys, count, lut):
            raise FilterError("points de courbe invalides (x croissants dans [0, 1], 2 minimum)")
        return bytes(lut)

    def apply_lut(self, pixels, width, height, red, green=None, blue=None, *,
                  mask=None, stride=None, mask_stride=None):
        green = red if green is None else green
        blue = red if blue is None else blue
        for name, table in (("red", red), ("green", green), ("blue", blue)):
            if len(table) != 256:
                raise ValueError(f"LUT {name} : 256 entrées requises")
        r = (ctypes.c_uint8 * 256).from_buffer_copy(bytes(red))
        g = (ctypes.c_uint8 * 256).from_buffer_copy(bytes(green))
        b = (ctypes.c_uint8 * 256).from_buffer_copy(bytes(blue))
        self._call("cs_filter_apply_lut", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, r, g, b, m, ms))


    # ---------------------------------------------- calques de filtre (ABI 2) --

    def encode_filter(self, kind, params=(), *, edge=EDGE_CLAMP, point_count=0) -> bytes:
        """Charge binaire de 76 octets (versionnée, CRC32) décrivant un filtre.

        ``kind`` : nom de :data:`FILTER_KINDS` ou identifiant entier. ``params`` :
        au plus 8 nombres (voir ``filter_layer.h`` pour le sens de chacun). Pour
        ``curve``, ``point_count`` (2 à 4) et ``params = x0, y0, x1, y1, ...``.
        """
        self._require_layers()
        kind_id = FILTER_KINDS[kind] if isinstance(kind, str) else int(kind)
        values = [float(v) for v in params]
        if len(values) > 8:
            raise ValueError("8 paramètres au maximum")
        values += [0.0] * (8 - len(values))
        out = (ctypes.c_uint8 * DESCRIPTOR_BYTES)()
        size = ctypes.c_int(0)
        if not self._lib.cs_filter_descriptor_encode(
                kind_id, int(edge), int(point_count), (ctypes.c_double * 8)(*values),
                out, DESCRIPTOR_BYTES, ctypes.byref(size)):
            raise FilterError("descripteur de filtre invalide (type ou paramètres hors plage)")
        return bytes(out[:size.value])

    def decode_filter(self, payload: bytes) -> dict:
        """Inverse de :meth:`encode_filter` ; lève :class:`FilterError` si la charge est altérée."""
        self._require_layers()
        raw = bytes(payload)
        buffer = (ctypes.c_uint8 * max(1, len(raw))).from_buffer_copy(raw or b"\0")
        kind, edge, points = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        params = (ctypes.c_double * 8)()
        if not self._lib.cs_filter_descriptor_decode(buffer, len(raw), ctypes.byref(kind),
                                                     ctypes.byref(edge), ctypes.byref(points),
                                                     params):
            raise FilterError("charge de filtre invalide ou corrompue")
        return {"kind": kind.value, "edge": edge.value, "point_count": points.value,
                "params": tuple(params)}

    def _payload_buffer(self, payload: bytes):
        raw = bytes(payload)
        return (ctypes.c_uint8 * max(1, len(raw))).from_buffer_copy(raw or b"\0"), len(raw)

    def filter_reach(self, payload: bytes) -> int:
        """Pixels voisins lus de chaque côté (0 = filtre ponctuel)."""
        self._require_layers()
        buffer, size = self._payload_buffer(payload)
        reach = ctypes.c_int(0)
        if not self._lib.cs_filter_descriptor_reach(buffer, size, ctypes.byref(reach)):
            raise FilterError("charge de filtre invalide")
        return reach.value

    def expand_rect(self, payload: bytes, doc_width: int, doc_height: int, rect) -> tuple:
        """Région du document à préparer pour calculer ``rect`` après ce filtre."""
        self._require_layers()
        buffer, size = self._payload_buffer(payload)
        out = (ctypes.c_int * 4)()
        x0, y0, x1, y1 = (int(v) for v in rect)
        if not self._lib.cs_filter_descriptor_expand_rect(buffer, size, int(doc_width),
                                                          int(doc_height), x0, y0, x1, y1, out):
            raise FilterError("région ou charge de filtre invalide")
        return tuple(out)

    def apply_filter(self, pixels, width, height, payload: bytes, *, opacity=1.0,
                     origin=(0, 0), mask=None, stride=None, mask_stride=None):
        """Applique un filtre décrit par ``payload`` (aperçu, filtre de menu...)."""
        self._require_layers()
        pbuf, psize = self._payload_buffer(payload)
        self._call("cs_filter_descriptor_apply", pixels, width, height, stride, mask,
                   mask_stride,
                   lambda fn, a, s, m, ms: fn(a, width, height, s, int(origin[0]),
                                              int(origin[1]), pbuf, psize, float(opacity),
                                              m, ms))

    def add_filter_layer(self, document_handle, name: str, payload: bytes) -> int:
        """Ajoute au sommet du document natif un calque de filtre ; retourne son index."""
        self._require_layers()
        buffer, size = self._payload_buffer(payload)
        index = ctypes.c_int(-1)
        if not self._lib.cs_document_add_filter_layer(document_handle, name.encode("utf-8"),
                                                      buffer, size, ctypes.byref(index)):
            raise FilterError("calque de filtre refusé (nom vide ou charge invalide)")
        return index.value

    def set_filter_payload(self, document_handle, index: int, payload: bytes) -> None:
        self._require_layers()
        buffer, size = self._payload_buffer(payload)
        if not self._lib.cs_document_set_filter_payload(document_handle, int(index), buffer,
                                                        size):
            raise FilterError("ce calque n'est pas un calque de filtre, ou la charge est invalide")

    def layer_kind(self, document_handle, index: int) -> int:
        """``LAYER_KIND_RASTER``, ``LAYER_KIND_FILTER``, ou -1 si l'index est invalide."""
        self._require_layers()
        return self._lib.cs_document_layer_kind(document_handle, int(index))

    def filter_payload(self, document_handle, index: int) -> bytes:
        self._require_layers()
        out = (ctypes.c_uint8 * DESCRIPTOR_BYTES)()
        size = ctypes.c_int(0)
        if not self._lib.cs_document_copy_filter_payload(document_handle, int(index), out,
                                                         DESCRIPTOR_BYTES, ctypes.byref(size)):
            raise FilterError("pas de charge de filtre à cet index")
        return bytes(out[:size.value])

    def evaluate_stack(self, entries, doc_width, doc_height, region, compose,
                       coverage=None) -> bytearray:
        """Évalue une pile de calques raster/filtre pour ``region`` = (x0, y0, x1, y1).

        ``entries`` : liste (bas -> haut) de :func:`raster_entry` / :func:`filter_entry`.
        ``compose(raster_ids, backdrop, rect, out) -> bool`` compose les rasters
        sur ``backdrop`` (``memoryview`` RGBA8 droit ou ``None``) pour ``rect`` et
        écrit dans ``out`` (``memoryview`` inscriptible) ; ``coverage(entry_index,
        rect, out) -> bool`` écrit le masque du filtre et retourne ``True``
        (``False``/``None`` = pas de masque).  Le résultat d'une région est
        identique à celui du document entier : évaluez tuile par tuile.
        """
        self._require_layers()
        x0, y0, x1, y1 = (int(v) for v in region)
        width, height = x1 - x0, y1 - y0
        if width <= 0 or height <= 0:
            raise ValueError("région vide")
        native = (_StackEntry * len(entries))()
        keep = []
        for i, entry in enumerate(entries):
            if entry[0] == "raster":
                native[i].is_filter, native[i].raster_id, native[i].visible = 0, entry[1], int(entry[2])
                native[i].opacity = 1.0
            elif entry[0] == "filter":
                buffer, size = self._payload_buffer(entry[1])
                keep.append(buffer)
                native[i].is_filter, native[i].visible = 1, int(entry[3])
                native[i].opacity = entry[2]
                native[i].payload = ctypes.cast(buffer, _BytePtr)
                native[i].payload_size = size
            else:
                raise ValueError(f"entrée de pile inconnue : {entry[0]!r}")
        errors = []

        def _compose(_user, ids, count, backdrop, x, y, w, h, out):
            try:
                rect = (x, y, x + w, y + h)
                length = w * h * 4
                back = _view(backdrop, length, readonly=True) if backdrop else None
                result = compose([ids[k] for k in range(count)], back, rect, _view(out, length))
                return 1 if result else 0
            except Exception as error:  # ne jamais laisser remonter dans le code natif
                errors.append(error)
                return 0

        def _coverage(_user, entry_index, x, y, w, h, out):
            try:
                if coverage is None:
                    return 0
                return 1 if coverage(entry_index, (x, y, x + w, y + h), _view(out, w * h)) else 0
            except Exception as error:
                errors.append(error)
                return -1

        compose_c, coverage_c = _ComposeFn(_compose), _CoverageFn(_coverage)
        result = bytearray(width * height * 4)
        array = (ctypes.c_uint8 * len(result)).from_buffer(result)
        ok = self._lib.cs_filter_stack_evaluate(native, len(entries), int(doc_width),
                                                int(doc_height), x0, y0, width, height,
                                                compose_c, coverage_c, None, array, len(result))
        del array
        if errors:
            raise errors[0]
        if not ok:
            raise FilterError("évaluation de la pile refusée (région, descripteur ou source invalide)")
        return result


def _declare_layers(library) -> None:
    i, d, u8, f = ctypes.c_int, ctypes.c_double, _BytePtr, ctypes.c_float
    handle = ctypes.c_void_p
    signatures = {
        "cs_filter_descriptor_encode": [i, i, i, ctypes.POINTER(d), u8, i, ctypes.POINTER(i)],
        "cs_filter_descriptor_decode": [u8, i, ctypes.POINTER(i), ctypes.POINTER(i),
                                        ctypes.POINTER(i), ctypes.POINTER(d)],
        "cs_filter_descriptor_reach": [u8, i, ctypes.POINTER(i)],
        "cs_filter_descriptor_expand_rect": [u8, i, i, i, i, i, i, i, ctypes.POINTER(i)],
        "cs_filter_descriptor_apply": [u8, i, i, i, i, i, u8, i, f, u8, i],
        "cs_document_add_filter_layer": [handle, ctypes.c_char_p, u8, i, ctypes.POINTER(i)],
        "cs_document_set_filter_payload": [handle, i, u8, i],
        "cs_document_layer_kind": [handle, i],
        "cs_document_copy_filter_payload": [handle, i, u8, i, ctypes.POINTER(i)],
        "cs_filter_stack_evaluate": [ctypes.POINTER(_StackEntry), i, i, i, i, i, i, i,
                                     _ComposeFn, _CoverageFn, ctypes.c_void_p, u8, i],
    }
    for name, argtypes in signatures.items():
        function = getattr(library, name)
        function.argtypes = argtypes
        function.restype = i


def _declare(library) -> None:
    i, d, u8 = ctypes.c_int, ctypes.c_double, _BytePtr
    common = [u8, i, i, i]
    tail = [u8, i]  # mask, mask_stride
    signatures = {
        "cs_filter_gaussian_blur": common + [d, d, i] + tail,
        "cs_filter_box_blur": common + [i, i, i] + tail,
        "cs_filter_motion_blur": common + [d, d, i] + tail,
        "cs_filter_unsharp_mask": common + [d, d, i, i] + tail,
        "cs_filter_median": common + [i] + tail,
        "cs_filter_pixelate": common + [i, i] + tail,
        "cs_filter_edge_detect": common + [d] + tail,
        "cs_filter_emboss": common + [d, d] + tail,
        "cs_filter_invert": common + tail,
        "cs_filter_desaturate": common + [i] + tail,
        "cs_filter_hsv_adjust": common + [d, d, d] + tail,
        "cs_filter_selective_color": common + [ctypes.POINTER(d), i] + tail,
        "cs_filter_hue_saturation": common + [d, d, d] + tail,
        "cs_filter_vibrance": common + [d, d] + tail,
        "cs_filter_color_balance": common + [ctypes.POINTER(d)] + tail,
        "cs_filter_luminosity_blend": common + [u8, i, i, d, d, i],
        "cs_filter_drop_shadow": common + [i, i, i, i, i, i, i],
        "cs_filter_stroke": common + [i, i, i, i, i],
        "cs_filter_blend_by_alpha": common + [u8, i, u8, i],
        "cs_filter_selection_feather": common + [i],
        "cs_filter_selection_morph": common + [i, i],
        "cs_filter_select_color_range": common + [u8, i, i, i, i, i],
        "cs_filter_posterize": common + [i] + tail,
        "cs_filter_threshold": common + [i] + tail,
        "cs_filter_add_noise": common + [d, ctypes.c_uint64, i, i, i] + tail,
        "cs_filter_color_to_alpha": common + [i, i, i, d] + tail,
        "cs_filter_build_levels_lut": [i, i, d, i, i, u8],
        "cs_filter_build_brightness_contrast_lut": [d, d, u8],
        "cs_filter_build_curve_lut": [ctypes.POINTER(d), ctypes.POINTER(d), i, u8],
        "cs_filter_apply_lut": common + [u8, u8, u8] + tail,
    }
    for name, argtypes in signatures.items():
        function = getattr(library, name)
        function.argtypes = argtypes
        function.restype = i
    library.cs_filter_abi_version.argtypes = []
    library.cs_filter_abi_version.restype = i
    try:
        abi = library.cs_filter_abi_version()
    except Exception:  # noqa: BLE001
        abi = 0
    if abi >= 5:
        optional = {
            "cs_filter_gradient_map": common + [u8] + tail,
            "cs_filter_lut3d": common + [ctypes.POINTER(ctypes.c_float), i] + tail,
            "cs_filter_set_alpha": common + [i],
            "cs_filter_copy_alpha": common + [u8, i],
        }
        for name, argtypes in optional.items():
            function = getattr(library, name)
            function.argtypes = argtypes
            function.restype = i


def load_filters() -> Optional[NativeFilters]:
    """Filtres du bridge CreativeCore, ou ``None`` s'il est absent ou trop ancien.

    Un bridge compilé avant l'ajout des filtres n'exporte pas ``cs_filter_*`` :
    ce n'est pas une erreur, la fonctionnalité est simplement indisponible.
    """
    from .native_bridge import load_creative_core

    global _CACHED_FILTERS
    library = load_creative_core()
    if library is None or not hasattr(library, "cs_filter_abi_version"):
        return None
    cached = _CACHED_FILTERS
    if cached is not None and cached._lib is library:
        return cached          # declaring every ctypes signature per call was costly
    try:
        _CACHED_FILTERS = NativeFilters(library)
        return _CACHED_FILTERS
    except (AttributeError, OSError):
        return None


_CACHED_FILTERS = None
