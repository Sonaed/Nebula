"""Tests de l'adaptateur Python des filtres natifs (CORE/native_filters.py).

Le test compile lui-même un mini-bridge sans Qt (image_filters + filter_api) afin
de valider l'ABI de bout en bout, indépendamment du reste de CreativeCore.
S'il n'y a pas de compilateur, les tests sont ignorés (jamais faussement verts).
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from CORE import native_filters  # noqa: E402


# Le vrai bridge fournit cs_document_create ; ce mini-bridge (sans Qt) n'a que
# DocumentState, on en expose donc la création via un petit adaptateur de test.
_DOCUMENT_SHIM = """
#include "document_state.h"
extern "C" {
void* shim_doc_create(int w, int h, int dpi) { return new DocumentState(w, h, dpi); }
void shim_doc_destroy(void* p) { delete static_cast<DocumentState*>(p); }
int shim_doc_add_layer(void* p, const char* n, int* i) {
    return static_cast<DocumentState*>(p)->addLayer(n, *i) ? 1 : 0; }
}
"""


def _build_library(directory: Path):
    compiler = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        return None
    output = directory / "libfilters_test.so"
    shim = directory / "document_shim.cpp"
    shim.write_text(_DOCUMENT_SHIM)
    src = ROOT / "CPP_CORE" / "src"
    result = subprocess.run(
        [compiler, "-std=c++17", "-O2", "-fPIC", "-shared", f"-I{ROOT / 'CPP_CORE' / 'include'}",
         str(src / "image_filters.cpp"), str(src / "filter_layer.cpp"),
         str(src / "filter_api.cpp"), str(src / "document_state.cpp"),
         str(src / "document_rules.cpp"), str(src / "layer_stack.cpp"), str(shim),
         "-o", str(output)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return ctypes.CDLL(str(output))


def solid(width, height, rgba):
    return bytearray(bytes(rgba) * (width * height))


def pixel(buffer, width, x, y, stride=None):
    stride = width * 4 if stride is None else stride
    offset = y * stride + x * 4
    return tuple(buffer[offset:offset + 4])


class NativeFiltersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        library.shim_doc_create.restype = ctypes.c_void_p
        library.shim_doc_create.argtypes = [ctypes.c_int] * 3
        library.shim_doc_destroy.argtypes = [ctypes.c_void_p]
        library.shim_doc_add_layer.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.POINTER(ctypes.c_int)]
        cls.library = library

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_abi_version_matches_adapter(self):
        self.assertEqual(self.filters._lib.cs_filter_abi_version(), native_filters.ABI_VERSION)

    def test_invert_and_alpha_preserved(self):
        image = solid(4, 3, (10, 20, 30, 77))
        self.filters.invert(image, 4, 3)
        self.assertEqual(pixel(image, 4, 2, 1), (245, 235, 225, 77))
        self.filters.invert(image, 4, 3)
        self.assertEqual(pixel(image, 4, 0, 0), (10, 20, 30, 77))

    def test_blur_keeps_flat_image_and_edge_modes(self):
        for edge in (native_filters.EDGE_CLAMP, native_filters.EDGE_WRAP):
            image = solid(16, 16, (200, 100, 50, 255))
            self.filters.gaussian_blur(image, 16, 16, 3.0, edge=edge)
            self.assertEqual(pixel(image, 16, 8, 8), (200, 100, 50, 255))
        with self.assertRaises(native_filters.FilterError):
            self.filters.gaussian_blur(solid(4, 4, (1, 2, 3, 255)), 4, 4, 1.0, edge=7)

    def test_mask_limits_the_filter(self):
        image = solid(4, 1, (10, 20, 30, 255))
        mask = bytes([0, 255, 0, 255])  # objet `bytes` en lecture seule
        self.filters.invert(image, 4, 1, mask=mask)
        self.assertEqual(pixel(image, 4, 0, 0), (10, 20, 30, 255))
        self.assertEqual(pixel(image, 4, 1, 0), (245, 235, 225, 255))
        self.assertEqual(pixel(image, 4, 3, 0), (245, 235, 225, 255))

    def test_stride_padding_untouched(self):
        width, height, stride = 3, 2, 3 * 4 + 8
        image = bytearray(b"\xAB" * (stride * height))
        for y in range(height):
            for x in range(width):
                image[y * stride + x * 4:y * stride + x * 4 + 4] = bytes((1, 2, 3, 255))
        self.filters.invert(image, width, height, stride=stride)
        for y in range(height):
            self.assertEqual(bytes(image[y * stride + width * 4:(y + 1) * stride]), b"\xAB" * 8)
            self.assertEqual(pixel(image, width, 1, y, stride), (254, 253, 252, 255))

    def test_memoryview_slice_as_input(self):
        backing = bytearray(b"\x00" * 8 + bytes((5, 6, 7, 255)) * 4)
        view = memoryview(backing)[8:]
        self.filters.invert(view, 2, 2)
        self.assertEqual(bytes(backing[:8]), b"\x00" * 8)
        self.assertEqual(tuple(backing[8:12]), (250, 249, 248, 255))

    def test_short_or_readonly_buffers_are_rejected_before_native_code(self):
        with self.assertRaises(ValueError):
            self.filters.invert(bytearray(10), 4, 4)  # 64 octets requis
        with self.assertRaises(ValueError):
            self.filters.invert(bytes(64), 4, 4)  # lecture seule
        with self.assertRaises(ValueError):
            self.filters.invert(solid(4, 4, (0, 0, 0, 255)), 4, 4, mask=bytes(3))
        with self.assertRaises(ValueError):
            self.filters.invert(solid(4, 4, (0, 0, 0, 255)), 0, 4)
        with self.assertRaises(ValueError):
            self.filters.invert(solid(4, 4, (0, 0, 0, 255)), 4, 4, stride=8)

    def test_native_argument_validation_surfaces_as_filter_error(self):
        image = solid(4, 4, (9, 9, 9, 255))
        with self.assertRaises(native_filters.FilterError):
            self.filters.gaussian_blur(image, 4, 4, -2.0)
        with self.assertRaises(native_filters.FilterError):
            self.filters.median(image, 4, 4, 99)
        with self.assertRaises(native_filters.FilterError):
            self.filters.desaturate(image, 4, 4, mode=9)
        with self.assertRaises(native_filters.FilterError):
            self.filters.color_to_alpha(image, 4, 4, (300, 0, 0))
        self.assertEqual(pixel(image, 4, 0, 0), (9, 9, 9, 255))  # inchangé

    def test_color_to_alpha_roundtrip(self):
        image = solid(2, 1, (255, 255, 255, 255))
        image[4:8] = bytes((0, 0, 0, 255))
        self.filters.color_to_alpha(image, 2, 1, (255, 255, 255))
        self.assertEqual(pixel(image, 2, 0, 0)[3], 0)
        self.assertEqual(pixel(image, 2, 1, 0), (0, 0, 0, 255))

    def test_hsv_rotation(self):
        image = solid(1, 1, (255, 0, 0, 255))
        self.filters.hsv_adjust(image, 1, 1, hue_degrees=120.0)
        self.assertEqual(pixel(image, 1, 0, 0), (0, 255, 0, 255))

    def test_noise_is_deterministic_and_accepts_64_bit_seeds(self):
        a, b = solid(32, 32, (128, 128, 128, 255)), solid(32, 32, (128, 128, 128, 255))
        big = 0xFFFFFFFFFFFFFFF0
        self.filters.add_noise(a, 32, 32, 0.1, seed=big)
        self.filters.add_noise(b, 32, 32, 0.1, seed=big)
        self.assertEqual(a, b)
        self.assertNotEqual(bytes(a), bytes(solid(32, 32, (128, 128, 128, 255))))

    def test_lut_builders_and_application(self):
        identity = bytes(range(256))
        self.assertEqual(self.filters.levels_lut(), identity)
        self.assertEqual(self.filters.brightness_contrast_lut(), identity)
        self.assertEqual(self.filters.curve_lut([(0, 0), (1, 1)]), identity)
        inverse = self.filters.levels_lut(out_black=255, out_white=0)
        self.assertEqual(inverse[0], 255)
        self.assertEqual(inverse[255], 0)
        with self.assertRaises(native_filters.FilterError):
            self.filters.curve_lut([(0.8, 0), (0.2, 1)])
        with self.assertRaises(native_filters.FilterError):
            self.filters.curve_lut([(0.5, 0.5)])
        image = solid(2, 2, (10, 20, 30, 40))
        self.filters.apply_lut(image, 2, 2, inverse)
        self.assertEqual(pixel(image, 2, 1, 1), (245, 235, 225, 40))
        with self.assertRaises(ValueError):
            self.filters.apply_lut(image, 2, 2, b"\x00" * 10)

    def test_pixelate_and_posterize(self):
        image = bytearray()
        for i in range(16):
            image += bytes((i * 16, i * 16, i * 16, 255))
        self.filters.pixelate(image, 4, 4, 4)
        self.assertEqual(len({bytes(image[i:i + 4]) for i in range(0, 64, 4)}), 1)
        gradient = bytearray()
        for i in range(256):
            gradient += bytes((i, i, i, 255))
        self.filters.posterize(gradient, 16, 16, 2)
        self.assertEqual({gradient[i] for i in range(0, 1024, 4)}, {0, 255})


class FilterLayerTests(unittest.TestCase):
    """Descripteurs, calques de filtre du document et évaluation de pile."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        library.shim_doc_create.restype = ctypes.c_void_p
        library.shim_doc_create.argtypes = [ctypes.c_int] * 3
        library.shim_doc_destroy.argtypes = [ctypes.c_void_p]
        library.shim_doc_add_layer.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.POINTER(ctypes.c_int)]
        cls.library = library

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_abi_v2_advertises_filter_layers(self):
        self.assertTrue(self.filters.supports_filter_layers)
        self.assertGreaterEqual(self.filters.abi_version, 2)

    def test_descriptor_roundtrip_and_validation(self):
        f = self.filters
        blur = f.encode_filter("gaussian_blur", (3.0, 4.0), edge=native_filters.EDGE_WRAP)
        self.assertEqual(len(blur), native_filters.DESCRIPTOR_BYTES)
        decoded = f.decode_filter(blur)
        self.assertEqual(decoded["kind"], native_filters.FILTER_KINDS["gaussian_blur"])
        self.assertEqual(decoded["edge"], native_filters.EDGE_WRAP)
        self.assertEqual(decoded["params"][:2], (3.0, 4.0))
        curve = f.encode_filter("curve", (0, 0, 0.5, 0.75, 1, 1), point_count=3)
        self.assertEqual(f.decode_filter(curve)["point_count"], 3)
        with self.assertRaises(native_filters.FilterError):
            f.encode_filter("gaussian_blur", (-1.0, 1.0))
        with self.assertRaises(native_filters.FilterError):
            f.encode_filter("median", (99,))
        with self.assertRaises(native_filters.FilterError):
            f.encode_filter("curve", (0.5, 0, 0.2, 1), point_count=2)
        with self.assertRaises(ValueError):
            f.encode_filter("invert", (0,) * 9)
        with self.assertRaises(KeyError):
            f.encode_filter("nonexistent")
        corrupted = bytearray(blur)
        corrupted[30] ^= 0x01
        with self.assertRaises(native_filters.FilterError):
            f.decode_filter(bytes(corrupted))
        with self.assertRaises(native_filters.FilterError):
            f.decode_filter(blur[:-1])
        with self.assertRaises(native_filters.FilterError):
            f.decode_filter(b"")

    def test_reach_and_expand_rect(self):
        f = self.filters
        blur = f.encode_filter("gaussian_blur", (2.0, 2.0))
        self.assertEqual(f.filter_reach(blur), 6)
        self.assertEqual(f.filter_reach(f.encode_filter("invert")), 0)
        self.assertEqual(f.expand_rect(blur, 100, 80, (30, 20, 50, 40)), (24, 14, 56, 46))
        wrap = f.encode_filter("gaussian_blur", (2.0, 2.0), edge=native_filters.EDGE_WRAP)
        self.assertEqual(f.expand_rect(wrap, 100, 80, (0, 20, 20, 40)), (0, 14, 100, 46))
        with self.assertRaises(native_filters.FilterError):
            f.expand_rect(blur, 100, 80, (0, 0, 101, 10))

    def test_apply_filter_matches_direct_call_and_opacity(self):
        f = self.filters
        image = solid(4, 4, (10, 20, 30, 255))
        f.apply_filter(image, 4, 4, f.encode_filter("invert"))
        self.assertEqual(pixel(image, 4, 1, 1), (245, 235, 225, 255))
        half = solid(4, 4, (0, 0, 0, 255))
        f.apply_filter(half, 4, 4, f.encode_filter("invert"), opacity=0.5)
        self.assertEqual(pixel(half, 4, 0, 0)[0], 128)
        same = solid(4, 4, (7, 8, 9, 255))
        f.apply_filter(same, 4, 4, f.encode_filter("invert"), opacity=0.0)
        self.assertEqual(pixel(same, 4, 0, 0), (7, 8, 9, 255))
        with self.assertRaises(native_filters.FilterError):
            f.apply_filter(same, 4, 4, f.encode_filter("invert"), opacity=1.5)
        with self.assertRaises(ValueError):
            f.apply_filter(bytearray(3), 4, 4, f.encode_filter("invert"))

    def test_document_filter_layers(self):
        f, lib = self.filters, self.library
        doc = lib.shim_doc_create(64, 64, 72)
        self.addCleanup(lib.shim_doc_destroy, doc)
        index = ctypes.c_int()
        self.assertTrue(lib.shim_doc_add_layer(doc, b"Fond", ctypes.byref(index)))
        self.assertEqual(f.layer_kind(doc, 0), native_filters.LAYER_KIND_RASTER)
        payload = f.encode_filter("gaussian_blur", (3.0, 3.0))
        at = f.add_filter_layer(doc, "Flou", payload)
        self.assertEqual(at, 1)
        self.assertEqual(f.layer_kind(doc, 1), native_filters.LAYER_KIND_FILTER)
        self.assertEqual(f.filter_payload(doc, 1), payload)
        newer = f.encode_filter("gaussian_blur", (8.0, 8.0))
        f.set_filter_payload(doc, 1, newer)
        self.assertEqual(f.filter_payload(doc, 1), newer)
        self.assertEqual(f.layer_kind(doc, 99), -1)
        with self.assertRaises(native_filters.FilterError):
            f.add_filter_layer(doc, "", payload)
        with self.assertRaises(native_filters.FilterError):
            f.add_filter_layer(doc, "X", payload[:-1])
        with self.assertRaises(native_filters.FilterError):
            f.set_filter_payload(doc, 0, newer)   # calque raster
        with self.assertRaises(native_filters.FilterError):
            f.filter_payload(doc, 0)
        self.assertEqual(f.layer_kind(doc, 2), -1)  # les refus n'ont rien ajouté

    def _stack_fixture(self, width=29, height=23):
        import random
        rng = random.Random(4)
        layers = [bytes(rng.randrange(256) if k % 4 != 3 else 255 for k in range(width * height * 4))
                  for _ in range(2)]

        def compose(ids, backdrop, rect, out):
            x0, y0, x1, y1 = rect
            w = x1 - x0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    o = ((y - y0) * w + (x - x0)) * 4
                    # rasters opaques : le dernier gagne ; sans raster, le fond reste
                    src = layers[ids[-1]]
                    out[o:o + 4] = src[(y * width + x) * 4:(y * width + x) * 4 + 4]
            return True

        def coverage(entry_index, rect, out):
            x0, y0, x1, y1 = rect
            w = x1 - x0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    out[(y - y0) * w + (x - x0)] = (x * 9 + y * 5) % 256
            return True

        return width, height, compose, coverage

    def test_evaluate_stack_tiles_equal_whole_document(self):
        f = self.filters
        width, height, compose, coverage = self._stack_fixture()
        entries = [
            native_filters.raster_entry(0),
            native_filters.filter_entry(f.encode_filter("gaussian_blur", (2.5, 2.5),
                                                        edge=native_filters.EDGE_WRAP), 1.0),
            native_filters.raster_entry(1),
            native_filters.filter_entry(f.encode_filter("pixelate", (5, 4)), 0.8),
            native_filters.filter_entry(f.encode_filter("emboss", (45, 1)), 1.0),
        ]
        whole = f.evaluate_stack(entries, width, height, (0, 0, width, height), compose, coverage)
        self.assertEqual(len(whole), width * height * 4)
        assembled = bytearray(len(whole))
        for y0 in range(0, height, 7):
            for x0 in range(0, width, 9):
                rect = (x0, y0, min(width, x0 + 9), min(height, y0 + 7))
                tile = f.evaluate_stack(entries, width, height, rect, compose, coverage)
                tw = rect[2] - rect[0]
                for y in range(rect[3] - rect[1]):
                    start = ((rect[1] + y) * width + rect[0]) * 4
                    assembled[start:start + tw * 4] = tile[y * tw * 4:(y + 1) * tw * 4]
        self.assertEqual(bytes(assembled), bytes(whole))
        # sans le dernier filtre, le résultat change bel et bien
        fewer = f.evaluate_stack(entries[:-1], width, height, (0, 0, width, height), compose, coverage)
        self.assertNotEqual(bytes(fewer), bytes(whole))

    def test_evaluate_stack_errors_and_callback_exceptions(self):
        f = self.filters
        width, height, compose, coverage = self._stack_fixture()
        entries = [native_filters.raster_entry(0),
                   native_filters.filter_entry(f.encode_filter("invert"))]
        with self.assertRaises(native_filters.FilterError):
            f.evaluate_stack(entries, width, height, (0, 0, width + 1, height), compose)
        with self.assertRaises(ValueError):
            f.evaluate_stack(entries, width, height, (3, 3, 3, 9), compose)
        with self.assertRaises(ValueError):
            f.evaluate_stack([("nope", 1)], width, height, (0, 0, 4, 4), compose)

        def broken(ids, backdrop, rect, out):
            raise RuntimeError("source cassée")

        with self.assertRaisesRegex(RuntimeError, "source cassée"):
            f.evaluate_stack(entries, width, height, (0, 0, 4, 4), broken)
        with self.assertRaises(native_filters.FilterError):
            f.evaluate_stack(entries, width, height, (0, 0, 4, 4), lambda *a: False)
        bad = [native_filters.raster_entry(0), ("filter", b"\x00" * 76, 1.0, True)]
        with self.assertRaises(native_filters.FilterError):
            f.evaluate_stack(bad, width, height, (0, 0, 4, 4), compose)

    def test_old_bridge_reports_filter_layers_unavailable(self):
        f = self.filters
        f.abi_version = 1   # simule un bridge antérieur
        try:
            self.assertFalse(f.supports_filter_layers)
            with self.assertRaises(native_filters.FilterError):
                f.encode_filter("invert")
        finally:
            f.abi_version = 2


def _legacy_selective_color(data, channels):
    """Ancienne implémentation NumPy de DOCUMENTS/adjustments.apply_selective_color,
    reproduite telle quelle : c'est la référence de non-régression du noyau natif."""
    import numpy as np
    rgb = data[..., :3].astype(np.float32) / 255.0
    flat = rgb.reshape((-1, 3))
    mx, mn = flat.max(1), flat.min(1)
    delta = mx - mn
    hue = np.zeros_like(mx)
    chromatic = delta > 1e-8
    hue = np.where(chromatic & (mx == flat[:, 0]), ((flat[:, 1] - flat[:, 2]) / np.maximum(delta, 1e-8)) % 6, hue)
    hue = np.where(chromatic & (mx == flat[:, 1]), (flat[:, 2] - flat[:, 0]) / np.maximum(delta, 1e-8) + 2, hue)
    hue = np.where(chromatic & (mx == flat[:, 2]), (flat[:, 0] - flat[:, 1]) / np.maximum(delta, 1e-8) + 4, hue) * 60.0
    saturation = np.divide(delta, np.maximum(mx, 1e-8))
    luminance = 0.2126 * flat[:, 0] + 0.7152 * flat[:, 1] + 0.0722 * flat[:, 2]
    centers = {"reds": 0.0, "yellows": 60.0, "greens": 120.0, "cyans": 180.0,
               "blues": 240.0, "magentas": 300.0}
    result = flat.copy()
    for name, center in centers.items():
        values = channels.get(name)
        if values is None:
            continue
        distance = np.abs(((hue - center + 180.0) % 360.0) - 180.0)
        weight = np.clip(1.0 - distance / 45.0, 0.0, 1.0) * saturation
        c, m, y, k = np.asarray(values, dtype=np.float32) / 100.0
        result[:, 0] += weight * (-c * (1.0 - result[:, 0]))
        result[:, 1] += weight * (-m * (1.0 - result[:, 1]))
        result[:, 2] += weight * (-y * (1.0 - result[:, 2]))
        result *= np.clip(1.0 - weight[:, None] * k, 0.0, 1.0)
    for name, mask in (("whites", luminance >= 0.75), ("neutrals", saturation <= 0.25), ("blacks", luminance <= 0.25)):
        values = channels.get(name)
        if values is None:
            continue
        c, m, y, k = np.asarray(values, dtype=np.float32) / 100.0
        weight = mask.astype(np.float32) * (1.0 - saturation if name != "neutrals" else 1.0)
        result[:, 0] += weight * (-c * (1.0 - result[:, 0]))
        result[:, 1] += weight * (-m * (1.0 - result[:, 1]))
        result[:, 2] += weight * (-y * (1.0 - result[:, 2]))
        result *= np.clip(1.0 - weight[:, None] * k, 0.0, 1.0)
    out = data.copy()
    out[..., :3] = np.rint(np.clip(result.reshape(rgb.shape), 0.0, 1.0) * 255.0).astype(np.uint8)
    return out


_ALL_BANDS = {
    "reds": (-40, 10, 5, 0), "yellows": (20, -30, 0, 10), "greens": (0, 25, -25, 0),
    "cyans": (50, 0, 0, -10), "blues": (-15, -15, 40, 5), "magentas": (30, 30, -30, 0),
    "whites": (0, 0, 20, -20), "neutrals": (10, -10, 10, 10), "blacks": (-20, 0, 0, 30),
}


class SelectiveColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, data, channels, **kwargs):
        height, width = data.shape[:2]
        buffer = bytearray(data.tobytes())
        self.filters.selective_color(buffer, width, height, channels, **kwargs)
        return buffer

    def test_matches_the_legacy_numpy_implementation(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy absent : pas de référence de non-régression")
        rng = np.random.default_rng(1234)
        data = rng.integers(0, 256, size=(96, 80, 4), dtype=np.uint8)
        # Cas limites que l'aléatoire ne couvre pas : gris, primaires, égalités de
        # canaux, extrêmes, pixels pile sur les seuils de saturation/luminance.
        specials = [(0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 0, 0), (0, 255, 0),
                    (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (200, 200, 50),
                    (50, 200, 200), (200, 50, 200), (200, 150, 150), (138, 172, 129),
                    (35, 40, 30), (1, 0, 0), (0, 1, 0), (0, 0, 1), (254, 255, 255)]
        for i, rgb in enumerate(specials):
            data[0, i, :3] = rgb
        for channels in (_ALL_BANDS, {"reds": (-100, 100, 100, 100)}, {"neutrals": (0, 0, 0, 100)},
                         {"whites": (30, 30, 30, 30), "blacks": (-50, 50, 0, 10)}, {}):
            expected = _legacy_selective_color(data, channels)
            actual = np.frombuffer(self._run(data, channels), dtype=np.uint8).reshape(data.shape)
            difference = np.abs(actual.astype(int) - expected.astype(int))
            self.assertEqual(int(difference[..., 3].max()), 0, "alpha modifié")
            # float32 dans le même ordre que NumPy : on attend l'égalité exacte ;
            # ±1 est toléré seulement si un compilateur contracte en FMA.
            self.assertLessEqual(int(difference.max()), 1, channels)
            self.assertLess(int((difference > 0).sum()), max(1, difference.size // 500), channels)

    def test_no_band_is_identity_and_unknown_names_are_ignored(self):
        image = bytearray(range(64))
        original = bytes(image)
        self.filters.selective_color(image, 4, 4, {})
        self.assertEqual(bytes(image), original)
        self.filters.selective_color(image, 4, 4, {"oranges": (100, 100, 100, 100)})
        self.assertEqual(bytes(image), original)

    def test_mask_and_stride(self):
        width, height, stride = 3, 2, 3 * 4 + 8
        image = bytearray([0xAB]) * (stride * height)
        for y in range(height):
            for x in range(width):
                image[y * stride + x * 4:y * stride + x * 4 + 4] = bytes((200, 60, 60, 255))
        mask = bytes([255, 0, 128, 255, 0, 255])
        self.filters.selective_color(image, width, height, {"reds": (100, 0, 0, 0)},
                                     mask=mask, stride=stride)
        self.assertEqual(pixel(image, width, 1, 0, stride), (200, 60, 60, 255))  # masque 0
        self.assertLess(pixel(image, width, 0, 0, stride)[0], 200)                # masque 255
        for y in range(height):  # le remplissage entre lignes est intact
            self.assertEqual(bytes(image[y * stride + 12:(y + 1) * stride]), bytes([0xAB]) * 8)

    def test_invalid_input_is_rejected(self):
        image = bytearray(16)
        with self.assertRaises(ValueError):
            self.filters.selective_color(image, 2, 2, {"reds": (1, 2, 3)})
        with self.assertRaises(native_filters.FilterError):
            self.filters.selective_color(image, 2, 2, {"reds": (float("nan"), 0, 0, 0)})
        with self.assertRaises(ValueError):
            self.filters.selective_color(bytearray(8), 2, 2, {"reds": (1, 2, 3, 4)})

    def test_old_bridge_reports_selective_color_unavailable(self):
        old = mock.MagicMock()
        old.cs_filter_abi_version.return_value = 2
        with mock.patch.object(native_filters, "_declare"), \
                mock.patch.object(native_filters, "_declare_layers"):
            filters = native_filters.NativeFilters(old)
        self.assertFalse(filters.supports_selective_color)
        with self.assertRaises(native_filters.FilterError):
            filters.selective_color(bytearray(16), 2, 2, {"reds": (1, 2, 3, 4)})


# ---------------------------------------------------------------- réglages ----
# Copies textuelles des anciennes implémentations NumPy (DOCUMENTS/adjustments.py
# avant la réécriture native) : elles servent uniquement de référence.

def _legacy_choices_to_rgb(np, hsv, shape):
    h6 = hsv[:, 0] * 6.0
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p = hsv[:, 2] * (1 - hsv[:, 1])
    q = hsv[:, 2] * (1 - f * hsv[:, 1])
    t = hsv[:, 2] * (1 - (1 - f) * hsv[:, 1])
    choices = np.stack((np.stack((hsv[:, 2], t, p), 1), np.stack((q, hsv[:, 2], p), 1),
                        np.stack((p, hsv[:, 2], t), 1), np.stack((p, q, hsv[:, 2]), 1),
                        np.stack((t, p, hsv[:, 2]), 1), np.stack((hsv[:, 2], p, q), 1)), 1)
    return np.rint(choices[np.arange(len(i)), i].reshape(shape) * 255).astype(np.uint8)


def _legacy_hue_saturation(np, data, hue, saturation, lightness):
    data = data.copy()
    np.seterr(invalid="ignore", divide="ignore")  # 0/0 sur les gris : masqué par np.where
    rgb = data[..., :3].astype(np.float32) / 255.0
    flat = rgb.reshape((-1, 3))
    hsv = np.empty_like(flat)
    mx, mn = flat.max(1), flat.min(1)
    delta = mx - mn
    hsv[:, 2] = mx
    hsv[:, 1] = np.where(mx == 0, 0, delta / np.maximum(mx, 1e-8))
    hsv[:, 0] = 0
    mask = delta != 0
    hsv[:, 0] = np.where(mask & (mx == flat[:, 0]), ((flat[:, 1] - flat[:, 2]) / delta) % 6, hsv[:, 0])
    hsv[:, 0] = np.where(mask & (mx == flat[:, 1]), (flat[:, 2] - flat[:, 0]) / delta + 2, hsv[:, 0])
    hsv[:, 0] = np.where(mask & (mx == flat[:, 2]), (flat[:, 0] - flat[:, 1]) / delta + 4, hsv[:, 0]) / 6.0
    hsv[:, 0] = (hsv[:, 0] + float(hue) / 360.0) % 1.0
    hsv[:, 1] = np.clip(hsv[:, 1] * (1.0 + float(saturation) / 100.0), 0, 1)
    hsv[:, 2] = np.clip(hsv[:, 2] + float(lightness) / 100.0, 0, 1)
    data[..., :3] = _legacy_choices_to_rgb(np, hsv, data[..., :3].shape)
    return data


def _legacy_vibrance(np, data, vibrance, saturation_shift):
    data = data.copy()
    rgb = data[..., :3].astype(np.float32) / 255.0
    flat = rgb.reshape((-1, 3))
    mx = flat.max(1)
    mn = flat.min(1)
    saturation = np.divide(mx - mn, np.maximum(mx, 1e-8))
    vib = float(vibrance) / 100.0
    sat_delta = vib * (1.0 - saturation) + float(saturation_shift) / 100.0
    hsv = np.empty_like(flat)
    hsv[:, 2] = mx
    hsv[:, 1] = np.clip(saturation * (1.0 + sat_delta), 0.0, 1.0)
    delta = mx - mn
    hsv[:, 0] = 0.0
    mask = delta > 1e-8
    hsv[:, 0] = np.where(mask & (mx == flat[:, 0]), ((flat[:, 1] - flat[:, 2]) / np.maximum(delta, 1e-8)) % 6, hsv[:, 0])
    hsv[:, 0] = np.where(mask & (mx == flat[:, 1]), (flat[:, 2] - flat[:, 0]) / np.maximum(delta, 1e-8) + 2, hsv[:, 0])
    hsv[:, 0] = np.where(mask & (mx == flat[:, 2]), (flat[:, 0] - flat[:, 1]) / np.maximum(delta, 1e-8) + 4, hsv[:, 0]) / 6.0
    data[..., :3] = _legacy_choices_to_rgb(np, hsv, data[..., :3].shape)
    return data


def _legacy_color_balance(np, data, shadows, midtones, highlights):
    data = data.copy()
    rgb = data[..., :3].astype(np.float32) / 255.0
    luminance = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    sh = np.clip(1.0 - luminance * 2.0, 0.0, 1.0)[..., None]
    hi = np.clip((luminance - 0.5) * 2.0, 0.0, 1.0)[..., None]
    mi = np.clip(1.0 - sh - hi, 0.0, 1.0)
    shadow_shift = np.asarray(shadows, dtype=np.float32).reshape(1, 1, 3)
    midtone_shift = np.asarray(midtones, dtype=np.float32).reshape(1, 1, 3)
    highlight_shift = np.asarray(highlights, dtype=np.float32).reshape(1, 1, 3)
    correction = (sh * shadow_shift + mi * midtone_shift + hi * highlight_shift) / 100.0
    rgb = np.clip(rgb + correction, 0.0, 1.0)
    data[..., :3] = np.rint(rgb * 255.0).astype(np.uint8)
    return data


def _legacy_luminosity_mask(np, source, mode, amount, feather, invert):
    rgb = source[..., :3].astype(np.float32) / 255.0
    luminance = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    mode = str(mode).lower()
    if mode in {"lights", "highlights", "lumières"}:
        mask = np.clip((luminance - 0.35) / 0.65, 0.0, 1.0)
    elif mode in {"shadows", "ombres"}:
        mask = np.clip((0.65 - luminance) / 0.65, 0.0, 1.0)
    elif mode in {"midtones", "midtone", "tons_moyens"}:
        mask = np.clip(1.0 - np.abs(luminance - 0.5) / 0.5, 0.0, 1.0)
    else:
        mask = np.ones_like(luminance)
    feather = max(0.01, float(feather))
    mask = np.power(mask, 1.0 / feather)
    if invert:
        mask = 1.0 - mask
    return np.clip(mask * float(amount), 0.0, 1.0)


def _legacy_luminosity_blend(np, source, adjusted, mode, amount, feather, invert):
    mask = _legacy_luminosity_mask(np, source, mode, amount, feather, invert)
    changed = adjusted.copy()
    alpha = source[..., 3:4]
    changed[..., :3] = np.rint(source[..., :3] * (1.0 - mask[..., None]) +
                               changed[..., :3] * mask[..., None]).astype(np.uint8)
    changed[..., 3:4] = alpha
    return changed


def _adjustment_test_image(np):
    rng = np.random.default_rng(99)
    data = rng.integers(0, 256, size=(90, 110, 4), dtype=np.uint8)
    specials = [(0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 0, 0), (0, 255, 0),
                (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (200, 200, 50),
                (1, 0, 0), (0, 1, 0), (0, 0, 1), (254, 255, 255), (255, 254, 254),
                (10, 10, 11), (127, 128, 127), (128, 127, 128)]
    for i, rgb in enumerate(specials):
        data[0, i, :3] = rgb
    # Toutes les valeurs de gris et un balayage de teintes saturées.
    for v in range(256):
        data[1 + v // 110, v % 110, :3] = (v, v, v)
    return data


class AdjustmentKernelParityTests(unittest.TestCase):
    """Les noyaux natifs reproduisent l'ancien NumPy (float32, même ordre)."""

    @classmethod
    def setUpClass(cls):
        try:
            import numpy as np
        except ImportError:
            raise unittest.SkipTest("NumPy absent : pas de référence de non-régression")
        cls.np = np
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        cls.data = _adjustment_test_image(np)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def native(self, method, *args, **kwargs):
        np = self.np
        height, width = self.data.shape[:2]
        buffer = bytearray(self.data.tobytes())
        getattr(self.filters, method)(buffer, width, height, *args, **kwargs)
        return np.frombuffer(buffer, dtype=np.uint8).reshape(self.data.shape)

    def assert_close(self, actual, expected, tolerance=0, label=""):
        np = self.np
        diff = np.abs(actual.astype(int) - expected.astype(int))
        self.assertEqual(int(diff[..., 3].max()), 0, f"{label}: alpha modifié")
        worst = int(diff.max())
        self.assertLessEqual(worst, tolerance,
                             f"{label}: écart max {worst}, {int((diff > tolerance).sum())} valeurs")

    def test_hue_saturation_is_bit_exact(self):
        for hue, sat, light in ((0, 0, 0), (30, 0, 0), (-120, 40, 0), (359, -100, 10),
                                (180, 100, -25), (720, 250, 100), (-45.5, -33.3, -100)):
            expected = _legacy_hue_saturation(self.np, self.data, hue, sat, light)
            self.assert_close(self.native("hue_saturation", hue, sat, light), expected, 0,
                              f"hsl {hue},{sat},{light}")

    def test_vibrance_is_bit_exact(self):
        for vib, sat in ((0, 0), (50, 0), (-80, 20), (100, 100), (-100, -100), (33.3, -12.5)):
            expected = _legacy_vibrance(self.np, self.data, vib, sat)
            self.assert_close(self.native("vibrance", vib, sat), expected, 0, f"vib {vib},{sat}")

    def test_color_balance_is_bit_exact(self):
        cases = (((0, 0, 0),) * 3,
                 ((20, -10, 5), (0, 0, 0), (0, 0, 0)),
                 ((0, 0, 0), (15, 15, -30), (0, 0, 0)),
                 ((10, 20, 30), (-40, 25, 5), (60, -60, 100)),
                 ((100, 100, 100), (100, 100, 100), (100, 100, 100)),
                 ((-100, -100, -100), (-100, -100, -100), (-100, -100, -100)))
        for shadows, midtones, highlights in cases:
            expected = _legacy_color_balance(self.np, self.data, shadows, midtones, highlights)
            self.assert_close(self.native("color_balance", shadows, midtones, highlights),
                              expected, 0, f"cb {shadows} {midtones} {highlights}")

    def test_luminosity_blend_matches_within_one_step(self):
        # powf (libm) et np.power peuvent différer d'un ulp : ±1 en 8 bits tolérés.
        np = self.np
        adjusted = _legacy_hue_saturation(np, self.data, 90, 60, -10)
        exact = 0
        total = 0
        for mode in ("lights", "shadows", "midtones", "none", "ombres"):
            for amount, feather, invert in ((1.0, 0.15, False), (0.6, 1.0, False),
                                            (1.0, 0.5, True), (1.0, 0.0, False), (2.0, 3.0, True)):
                expected = _legacy_luminosity_blend(np, self.data, adjusted, mode, amount, feather, invert)
                buffer = bytearray(adjusted.tobytes())
                self.filters.luminosity_blend(buffer, 110, 90, bytes(self.data.tobytes()), mode,
                                              amount, feather, invert)
                actual = np.frombuffer(buffer, dtype=np.uint8).reshape(self.data.shape)
                self.assert_close(actual, expected, 1, f"lum {mode} {amount} {feather} {invert}")
                exact += int((actual == expected).sum())
                total += actual.size
        self.assertGreater(exact / total, 0.999)

    def test_selection_mask_limits_the_adjustment(self):
        np = self.np
        mask = bytearray(110 * 90)
        for x in range(55):
            for y in range(90):
                mask[y * 110 + x] = 255
        result = self.native("hue_saturation", 120, 50, 0, mask=bytes(mask))
        expected = _legacy_hue_saturation(np, self.data, 120, 50, 0)
        self.assert_close(result[:, :55], expected[:, :55], 0, "zone masquée")
        self.assert_close(result[:, 55:], self.data[:, 55:], 0, "hors masque")

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(Exception):
            self.filters.hue_saturation(bytearray(16), 2, 2, float("nan"), 0, 0)
        with self.assertRaises(ValueError):
            self.filters.color_balance(bytearray(16), 2, 2, (1, 2), (0, 0, 0), (0, 0, 0))


def _legacy_shadow_alpha(np, alpha, dx, dy, radius, color_alpha):
    """Alpha de l'ombre exactement comme l'ancien NumPy (avant composition)."""
    shadow = np.zeros_like(alpha)
    y0, y1 = max(0, dy), min(alpha.shape[0], alpha.shape[0] + dy)
    x0, x1 = max(0, dx), min(alpha.shape[1], alpha.shape[1] + dx)
    sy0, sy1 = max(0, -dy), max(0, -dy) + (y1 - y0)
    sx0, sx1 = max(0, -dx), max(0, -dx) + (x1 - x0)
    if y1 > y0 and x1 > x0:
        shadow[y0:y1, x0:x1] = alpha[sy0:sy1, sx0:sx1]
    for axis in (0, 1):
        shadow = np.apply_along_axis(lambda row: np.convolve(
            np.pad(row.astype(np.float32), (radius, radius), mode="edge"),
            np.ones(2 * radius + 1) / (2 * radius + 1), mode="valid"), axis, shadow)
    return (shadow.astype(np.float32) * (color_alpha / 255.0)).astype(np.uint8)


def _legacy_stroke(np, data, width, color):
    data = data.copy()
    alpha = data[..., 3]
    padded = np.pad(alpha, width, mode="constant")
    views = [padded[y:y + alpha.shape[0], x:x + alpha.shape[1]]
             for y in range(2 * width + 1) for x in range(2 * width + 1)]
    outline = np.maximum.reduce(views)
    mask = np.maximum(0, outline.astype(np.int16) - alpha.astype(np.int16)).astype(np.uint8)
    data[..., :3] = np.where(mask[..., None] > 0, np.array(color[:3], dtype=np.uint8), data[..., :3])
    data[..., 3] = np.maximum(alpha, (mask.astype(np.uint16) * int(color[3]) // 255).astype(np.uint8))
    return data


class LayerEffectKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy as np
        except ImportError:
            raise unittest.SkipTest("NumPy absent")
        cls.np = np
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        rng = np.random.default_rng(5)
        data = np.zeros((70, 90, 4), dtype=np.uint8)
        data[15:40, 20:50] = (200, 30, 60, 255)
        data[30:55, 40:75, :3] = (20, 180, 90)
        data[30:55, 40:75, 3] = rng.integers(0, 256, size=(25, 35), dtype=np.uint8)
        data[2, 2] = (255, 255, 255, 255)          # pixel isolé près du bord
        data[69, 89] = (10, 10, 10, 128)           # coin
        cls.data = data

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_native(self, method, *args, **kwargs):
        np = self.np
        buffer = bytearray(self.data.tobytes())
        getattr(self.filters, method)(buffer, 90, 70, *args, **kwargs)
        return np.frombuffer(buffer, dtype=np.uint8).reshape(self.data.shape)

    def test_stroke_is_bit_exact(self):
        np = self.np
        for width, color in ((1, (255, 255, 255, 255)), (3, (255, 0, 0, 128)), (7, (1, 2, 3, 1)),
                             (32, (9, 9, 9, 255))):
            expected = _legacy_stroke(np, self.data, width, color)
            actual = self.run_native("stroke", width, color)
            self.assertTrue(np.array_equal(actual, expected), f"stroke {width} {color}")

    def test_drop_shadow_alpha_matches_the_legacy_blur(self):
        np = self.np
        alpha = self.data[..., 3]
        for dx, dy, radius, color in ((4, 4, 6, (0, 0, 0, 160)), (-9, 5, 3, (40, 50, 60, 255)),
                                      (0, 0, 1, (255, 0, 0, 90)), (200, -3, 4, (0, 0, 0, 200)),
                                      (-6, -8, 20, (0, 0, 0, 255))):
            shadow_alpha = _legacy_shadow_alpha(np, alpha, dx, dy, radius, color[3])
            actual = self.run_native("drop_shadow", dx, dy, radius, color)
            empty = alpha == 0
            diff = np.abs(actual[..., 3].astype(int) - shadow_alpha.astype(int))[empty]
            self.assertLessEqual(int(diff.max()), 1, f"ombre {dx},{dy},{radius}")
            self.assertGreater(float((diff == 0).mean()), 0.999)
            shown = empty & (shadow_alpha > 0)
            self.assertTrue(np.array_equal(actual[shown][:, :3],
                                           np.tile(np.array(color[:3], dtype=np.uint8), (int(shown.sum()), 1))))

    def test_drop_shadow_goes_under_the_layer(self):
        np = self.np
        actual = self.run_native("drop_shadow", 6, 6, 4, (0, 0, 0, 255))
        opaque = self.data[..., 3] == 255
        self.assertTrue(np.array_equal(actual[opaque], self.data[opaque]))
        self.assertTrue(np.array_equal(actual[..., 3][opaque], self.data[..., 3][opaque]))
        # Un pixel partiellement transparent est éclairci/assombri par l'ombre, jamais l'inverse.
        self.assertTrue((actual[..., 3] >= self.data[..., 3]).all())

    def test_out_of_range_arguments_are_rejected(self):
        buffer = bytearray(16)
        for call in (lambda: self.filters.stroke(buffer, 2, 2, 0),
                     lambda: self.filters.stroke(buffer, 2, 2, 33),
                     lambda: self.filters.drop_shadow(buffer, 2, 2, 1, 1, 0),
                     lambda: self.filters.drop_shadow(buffer, 2, 2, 1, 1, 40)):
            with self.assertRaises(native_filters.FilterError):
                call()
        with self.assertRaises(ValueError):
            self.filters.stroke(buffer, 2, 2, 1, (1, 2))


def _legacy_feather(np, data, radius):
    data = data.copy()
    alpha = data[..., 3].astype(np.float32)
    for axis in (0, 1):
        alpha = np.apply_along_axis(lambda row: np.convolve(
            np.pad(row, (radius, radius), mode="edge"),
            np.ones(2 * radius + 1) / (2 * radius + 1), mode="valid"), axis, alpha)
    data[..., :3] = data[..., 3:4] = np.rint(alpha)[..., None].astype(np.uint8)
    return data


def _legacy_morph(np, data, radius, grow):
    data = data.copy()
    height, width = data.shape[:2]
    alpha = data[..., 3]
    padded = np.pad(alpha, radius, mode="constant", constant_values=0)
    views = [padded[y:y + height, x:x + width]
             for y in range(2 * radius + 1) for x in range(2 * radius + 1)]
    reduced = np.maximum.reduce(views) if grow else np.minimum.reduce(views)
    data[..., :3] = data[..., 3:4] = reduced[..., None]
    return data


def _legacy_clipped(np, base, changed, clip):
    original = base.copy()
    mask = clip[..., 3:4].astype(np.float32) / 255.0
    original[..., :3] = np.rint(original[..., :3] * (1.0 - mask) +
                                changed[..., :3] * mask).astype(np.uint8)
    return original


class SelectionKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy as np
        except ImportError:
            raise unittest.SkipTest("NumPy absent")
        cls.np = np
        cls._tmp = tempfile.TemporaryDirectory()
        library = _build_library(Path(cls._tmp.name))
        if library is None:
            raise unittest.SkipTest("aucun compilateur C++ disponible")
        cls.filters = native_filters.NativeFilters(library)
        rng = np.random.default_rng(17)
        cls.data = rng.integers(0, 256, size=(37, 53, 4), dtype=np.uint8)
        cls.data[..., 3][rng.random((37, 53)) < 0.5] = 0          # sélection très irrégulière
        cls.data[10:25, 12:40, 3] = 255
        cls.data[0, :, 3] = 255                                   # touche le bord

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def native(self, method, *args):
        np = self.np
        buffer = bytearray(self.data.tobytes())
        getattr(self.filters, method)(buffer, 53, 37, *args)
        return np.frombuffer(buffer, dtype=np.uint8).reshape(self.data.shape)

    def test_feather_is_bit_exact(self):
        for radius in (1, 2, 5, 17, 40, 90):
            expected = _legacy_feather(self.np, self.data, radius)
            self.assertTrue(self.np.array_equal(self.native("selection_feather", radius), expected),
                            f"rayon {radius}")

    def test_expand_and_contract_are_bit_exact(self):
        for radius in (1, 2, 3, 8, 20, 60):
            for grow in (True, False):
                expected = _legacy_morph(self.np, self.data, radius, grow)
                self.assertTrue(self.np.array_equal(
                    self.native("selection_morph", radius, grow), expected),
                    f"rayon {radius} grow={grow}")

    def test_contract_also_erodes_the_image_border(self):
        full = self.np.full((6, 6, 4), 255, dtype=self.np.uint8)
        buffer = bytearray(full.tobytes())
        self.filters.selection_morph(buffer, 6, 6, 1, False)
        out = self.np.frombuffer(buffer, dtype=self.np.uint8).reshape(6, 6, 4)
        self.assertEqual(int(out[0, 3, 3]), 0)
        self.assertEqual(int(out[3, 3, 3]), 255)

    def test_color_range_is_a_true_euclidean_distance(self):
        np = self.np
        rgb = np.array([[[0, 0, 0, 255], [255, 255, 255, 255], [100, 100, 100, 255],
                         [200, 30, 30, 255], [10, 250, 10, 255]]], dtype=np.uint8)
        mask = bytearray(5 * 4)
        self.filters.select_color_range(mask, 5, 1, bytes(rgb.tobytes()), (0, 0, 0), 16)
        out = np.frombuffer(mask, dtype=np.uint8).reshape(1, 5, 4)
        distance = np.sqrt(((rgb[..., :3].astype(np.int32)) ** 2).sum(axis=2))
        expected = np.clip(255 - distance * 255 / max(1, 16 * 1.732), 0, 255).astype(np.uint8)
        self.assertTrue(np.array_equal(out[..., 3], expected))
        self.assertTrue(all(np.array_equal(out[..., k], out[..., 3]) for k in range(3)))
        self.assertEqual(int(out[0, 0, 3]), 255)   # même couleur : sélection pleine
        self.assertEqual(int(out[0, 1, 3]), 0)     # blanc, très loin : hors sélection

    def test_color_range_random_matches_int32_reference(self):
        np = self.np
        for tolerance in (0, 1, 16, 64, 255):
            source = self.data.copy()
            buffer = bytearray(53 * 37 * 4)
            self.filters.select_color_range(buffer, 53, 37, bytes(source.tobytes()),
                                            (120, 60, 200), tolerance)
            out = np.frombuffer(buffer, dtype=np.uint8).reshape(37, 53, 4)
            target = np.array([120, 60, 200], dtype=np.int32)
            distance = np.sqrt(((source[..., :3].astype(np.int32) - target) ** 2).sum(axis=2))
            expected = np.clip(255 - distance * 255 / max(1, tolerance * 1.732), 0, 255).astype(np.uint8)
            self.assertTrue(np.array_equal(out[..., 3], expected), f"tolérance {tolerance}")

    def test_clipped_blend_is_bit_exact(self):
        np = self.np
        rng = np.random.default_rng(2)
        base = rng.integers(0, 256, size=(37, 53, 4), dtype=np.uint8)
        changed = rng.integers(0, 256, size=(37, 53, 4), dtype=np.uint8)
        clip = self.data
        buffer = bytearray(base.tobytes())
        self.filters.blend_by_alpha(buffer, 53, 37, bytes(changed.tobytes()), bytes(clip.tobytes()))
        out = np.frombuffer(buffer, dtype=np.uint8).reshape(base.shape)
        self.assertTrue(np.array_equal(out, _legacy_clipped(np, base, changed, clip)))

    def test_invalid_arguments_are_rejected(self):
        buffer = bytearray(16)
        for call in (lambda: self.filters.selection_feather(buffer, 2, 2, 0),
                     lambda: self.filters.selection_morph(buffer, 2, 2, -1, True),
                     lambda: self.filters.select_color_range(buffer, 2, 2, bytes(16), (300, 0, 0)),
                     lambda: self.filters.blend_by_alpha(buffer, 2, 2, bytes(16), bytes(16), stride=4)):
            with self.assertRaises((native_filters.FilterError, ValueError)):
                call()
        with self.assertRaises(Exception):
            self.filters.blend_by_alpha(buffer, 2, 2, bytes(4), bytes(16))   # source trop courte


class LoaderTests(unittest.TestCase):
    def test_missing_symbols_mean_unavailable_not_broken(self):
        class OldBridge:  # bridge compilé avant les filtres
            pass

        with mock.patch("CORE.native_bridge.load_creative_core", return_value=OldBridge()):
            self.assertIsNone(native_filters.load_filters())
        with mock.patch("CORE.native_bridge.load_creative_core", return_value=None):
            self.assertIsNone(native_filters.load_filters())


if __name__ == "__main__":
    unittest.main()
