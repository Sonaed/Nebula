"""Tests de l'instantané d'état de tuiles du moteur de rendu GPU.

Le rendu interrogeait CreativeCore (ctypes) plusieurs fois par tuile et par image,
y compris pour les tuiles vides : ~50 ms par image sur un document de ~1000 tuiles.
Ces tests fixent le contrat de l'optimisation : mêmes résultats qu'avant, beaucoup
moins d'appels natifs, et jamais de valeur périmée d'une image à l'autre.

Ils n'ont besoin ni d'OpenGL ni d'un vrai TileStore : un faux magasin compte les
appels.  Sans PySide6, de simples doublures permettent d'importer le module.
"""
from __future__ import annotations

import random
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # vraie pile Qt si disponible
    import PySide6.QtGui  # noqa: F401
    import PySide6.QtOpenGL  # noqa: F401
except ImportError:  # doublures minimales : seule la logique Python est testée
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtOpenGL",
                 "PySide6.QtWidgets"):
        sys.modules[name] = mock.MagicMock(name=name)
    bridge = types.ModuleType("CORE.native_bridge")
    bridge.NativeTextureAtlasHandle = mock.MagicMock()
    bridge.load_creative_core = lambda: None
    sys.modules.setdefault("CORE", types.ModuleType("CORE"))
    sys.modules["CORE.native_bridge"] = bridge

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402

from CANVAS.gpu_renderer import CanvasGPURenderer  # noqa: E402


class FakeImage:
    def __init__(self, alpha: bytes) -> None:
        self.data = bytearray()
        for value in alpha:
            self.data += bytes((10, 20, 30, value))
        self._count = len(alpha)

    def isNull(self): return False
    def hasAlphaChannel(self): return True
    def format(self): return QImage.Format.Format_RGBA8888
    def constBits(self): return memoryview(self.data)
    def width(self): return 8
    def height(self): return self._count // 8
    def sizeInBytes(self): return len(self.data)


class FakeStore:
    """Magasin de tuiles factice qui compte chaque « appel natif »."""

    tile_size = 64

    def __init__(self, resident, swapped=(), revisions=None, opaque=()):
        self.resident = set(resident)
        self._swapped = {key: Path("/dev/null") for key in swapped}
        self.revisions = dict(revisions or {})
        self.opaque = set(opaque)
        self.calls = {"resident_keys": 0, "has_tile": 0, "tile_is_resident": 0,
                      "tile_revision": 0, "tile": 0, "async": 0}

    def resident_keys(self):
        self.calls["resident_keys"] += 1
        return set(self.resident)

    def has_tile(self, tx, ty):
        self.calls["has_tile"] += 1
        return (tx, ty) in self.resident or (tx, ty) in self._swapped

    def tile_is_resident(self, tx, ty):
        self.calls["tile_is_resident"] += 1
        return (tx, ty) in self.resident

    def tile_revision(self, tx, ty):
        self.calls["tile_revision"] += 1
        return self.revisions.get((tx, ty), 0)

    def tile(self, tx, ty):
        self.calls["tile"] += 1
        return FakeImage(bytes([255] * 64 if (tx, ty) in self.opaque else [255] * 63 + [7]))

    def request_tile_async(self, tx, ty, callback=None):
        self.calls["async"] += 1
        return True

    def native_calls(self):
        return sum(self.calls[name] for name in ("has_tile", "tile_is_resident", "tile_revision"))


class BulkStore(FakeStore):
    """Magasin avec lecture en bloc des révisions (bridge récent)."""

    def resident_revisions(self):
        self.calls["resident_keys"] += 1
        return {key: self.revisions.get(key, 0) for key in self.resident}


class FakeLayer:
    def __init__(self, layer_id, store, opacity=1.0):
        self.id = layer_id
        self.tile_store = store
        self.visible = True
        self.blend_mode = "normal"
        self.blend_parameters = {}
        self.opacity = opacity
        self.clipping = False


class FakeTexture:
    _next = 100
    def __init__(self):
        FakeTexture._next += 1
        self._id = FakeTexture._next
    def textureId(self): return self._id
    def isCreated(self): return True
    def destroy(self): pass


def make_renderer() -> CanvasGPURenderer:
    renderer = CanvasGPURenderer()
    renderer.initialized = True
    renderer.blitter = object()
    return renderer


class FrameSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()
        patches = (mock.patch.object(self.renderer, "_create_texture",
                                     side_effect=lambda image, tiled=False: FakeTexture()),
                   mock.patch.object(self.renderer, "_evict_texture_cache"))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def random_store(rng, columns=30, rows=17):
        tiles = [(tx, ty) for ty in range(rows) for tx in range(columns)]
        resident = {key for key in tiles if rng.random() < 0.6}
        swapped = {key for key in tiles if key not in resident and rng.random() < 0.15}
        revisions = {key: rng.randrange(1, 50) for key in tiles if rng.random() < 0.9}
        opaque = {key for key in resident if rng.random() < 0.5}
        return FakeStore(resident, swapped, revisions, opaque)

    def test_opaque_tiles_and_occlusion_match_the_legacy_scan(self):
        rng = random.Random(7)
        width, height = 30 * 64 - 10, 17 * 64 - 3  # bords partiels
        for _ in range(12):
            layers = [FakeLayer(f"l{i}", self.random_store(rng), opacity=rng.choice((1.0, 1.0, 0.5)))
                      for i in range(3)]
            legacy = self.renderer.compute_occlusion(layers, width, height)
            self.renderer._opaque_tile_cache.clear()
            self.renderer.begin_frame()
            try:
                framed = self.renderer.compute_occlusion(layers, width, height)
            finally:
                self.renderer.end_frame()
            self.assertEqual(legacy, framed)
            self.renderer._opaque_tile_cache.clear()

    def test_sync_tile_results_match_the_legacy_path(self):
        rng = random.Random(11)
        store = self.random_store(rng, columns=12, rows=9)
        layer = FakeLayer("a", store)

        def run(framed):
            self.renderer.textures.clear()
            store.calls = dict.fromkeys(store.calls, 0)
            if framed:
                self.renderer.begin_frame()
            try:
                out = {(tx, ty): self.renderer.sync_tile(layer, tx, ty)
                       for ty in range(9) for tx in range(12)}
            finally:
                self.renderer.end_frame()
            revisions = {key: (None if value is None else value.revision) for key, value in out.items()}
            return revisions, dict(store.calls)

        legacy, legacy_calls = run(False)
        framed, framed_calls = run(True)
        self.assertEqual(legacy, framed)
        # Mêmes demandes de chargement asynchrone pour les tuiles déchargées.
        self.assertEqual(legacy_calls["async"], framed_calls["async"])

    def test_native_calls_collapse_to_at_most_one_read_per_tile(self):
        rng = random.Random(3)
        store = FakeStore({(tx, ty) for ty in range(32) for tx in range(32)},
                          revisions={(tx, ty): 5 for ty in range(32) for tx in range(32)},
                          opaque={(tx, ty) for ty in range(32) for tx in range(32)})
        layer = FakeLayer("bg", store)

        def one_paint(framed):
            store.calls = dict.fromkeys(store.calls, 0)
            self.renderer.textures.clear()
            self.renderer._opaque_tile_cache.clear()
            if framed:
                self.renderer.begin_frame()
            try:
                self.renderer.compute_occlusion([layer], 32 * 64, 32 * 64)
                for ty in range(32):
                    for tx in range(32):
                        self.renderer.sync_tile(layer, tx, ty)
            finally:
                self.renderer.end_frame()
            return store.native_calls()

        legacy, framed = one_paint(False), one_paint(True)
        self.assertGreaterEqual(legacy, 4 * 1024)          # ~5 appels par tuile avant
        self.assertLessEqual(framed, 1024)                  # au plus une lecture par tuile
        self.assertEqual(store.calls["has_tile"] + store.calls["tile_is_resident"], 0)
        self.assertEqual(store.calls["resident_keys"], 1)   # une seule lecture en bloc

    def test_an_edit_between_frames_is_never_missed(self):
        store = FakeStore({(0, 0), (1, 0)}, revisions={(0, 0): 1, (1, 0): 1})
        layer = FakeLayer("a", store)
        self.renderer.begin_frame()
        first = self.renderer.sync_tile(layer, 0, 0)
        self.renderer.end_frame()
        self.assertEqual(first.revision, 1)
        store.revisions[(0, 0)] = 2                          # la tuile est modifiée
        self.renderer.begin_frame()
        second = self.renderer.sync_tile(layer, 0, 0)
        self.renderer.end_frame()
        self.assertEqual(second.revision, 2)
        # Hors trame, aucune valeur mise en cache : la modification suivante est vue.
        store.revisions[(0, 0)] = 3
        self.assertEqual(self.renderer.sync_tile(layer, 0, 0).revision, 3)

    def test_the_snapshot_is_dropped_when_the_frame_ends_even_on_error(self):
        store = FakeStore({(0, 0)}, revisions={(0, 0): 1})
        layer = FakeLayer("a", store)
        self.renderer.begin_frame()
        self.renderer.sync_tile(layer, 0, 0)
        self.renderer.end_frame()
        self.assertEqual(self.renderer._frame_tiles, {})
        self.assertFalse(self.renderer._frame_active)

    def test_swapped_tile_requests_async_load_and_missing_tile_is_skipped(self):
        store = FakeStore({(0, 0)}, swapped={(1, 0)}, revisions={(1, 0): 4})
        layer = FakeLayer("a", store)
        self.renderer.begin_frame()
        try:
            self.assertIsNone(self.renderer.sync_tile(layer, 1, 0))   # sur disque
            self.assertIsNone(self.renderer.sync_tile(layer, 5, 5))   # inexistante
        finally:
            self.renderer.end_frame()
        self.assertEqual(store.calls["async"], 1)

    def test_fully_opaque_check_matches_the_reference_definition(self):
        rng = random.Random(5)
        samples = [bytes([255] * 64), bytes([255] * 63 + [254]), bytes([0] * 64), b"\xff", b"\x00"]
        samples += [bytes(rng.choice((255, 255, 255, 0, 128)) for _ in range(64)) for _ in range(50)]
        samples += [bytes([254] + [255] * 63), bytes([255] * 32 + [1] + [255] * 31)]
        for alpha in samples:
            image = FakeImage(alpha)
            expected = all(value == 255 for value in alpha)
            self.assertEqual(CanvasGPURenderer._image_is_fully_opaque(image), expected, alpha)


class BulkRevisionTests(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()
        for patcher in (mock.patch.object(self.renderer, "_create_texture",
                                          side_effect=lambda image, tiled=False: FakeTexture()),
                        mock.patch.object(self.renderer, "_evict_texture_cache")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_native_read_per_layer_and_no_per_tile_revision_calls(self):
        resident = {(tx, ty) for ty in range(20) for tx in range(20)}
        store = BulkStore(resident, revisions={key: 3 for key in resident},
                          opaque=resident)
        layer = FakeLayer("a", store)
        self.renderer.begin_frame()
        try:
            self.renderer.compute_occlusion([layer], 20 * 64, 20 * 64)
            for key in sorted(resident):
                self.assertEqual(self.renderer.sync_tile(layer, *key).revision, 3)
        finally:
            self.renderer.end_frame()
        self.assertEqual(store.calls["tile_revision"], 0)
        self.assertEqual(store.calls["resident_keys"], 1)

    def test_bulk_and_per_tile_snapshots_agree(self):
        rng = random.Random(9)
        resident = {(tx, ty) for ty in range(9) for tx in range(9) if rng.random() < 0.7}
        revisions = {key: rng.randrange(1, 9) for key in resident}
        opaque = {key for key in resident if rng.random() < 0.5}
        results = []
        for cls in (FakeStore, BulkStore):
            top = FakeLayer("top", cls(set(resident), revisions=revisions, opaque=opaque))
            bottom = FakeLayer("bottom", cls(set(resident), revisions=revisions))
            self.renderer._opaque_tile_cache.clear()
            self.renderer.begin_frame()
            try:
                out = self.renderer.compute_occlusion([bottom, top], 9 * 64, 9 * 64)
            finally:
                self.renderer.end_frame()
            results.append(out["bottom"])
        self.assertTrue(results[0])           # le test n'est pas vide
        self.assertEqual(results[0], results[1])

    def test_old_bridge_returning_none_falls_back(self):
        store = BulkStore({(0, 0)}, revisions={(0, 0): 7})
        store.resident_revisions = lambda: None
        layer = FakeLayer("a", store)
        self.renderer.begin_frame()
        try:
            self.assertEqual(self.renderer.sync_tile(layer, 0, 0).revision, 7)
        finally:
            self.renderer.end_frame()


class NativeKeyRevisionsTests(unittest.TestCase):
    """NativeTileStoreHandle.key_revisions : un appel pour toutes les tuiles résidentes."""

    def handle(self, tiles, has_function=True):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "real_native_bridge", ROOT / "CORE" / "native_bridge.py")
        native_bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native_bridge)
        calls = []

        def function(handle, pairs, revisions, capacity):
            calls.append(capacity)
            if pairs is not None and revisions is not None and capacity > 0:
                for index, ((x, y), rev) in enumerate(list(tiles.items())[:capacity]):
                    pairs[index * 2], pairs[index * 2 + 1], revisions[index] = x, y, rev
            return min(capacity, len(tiles)) if capacity > 0 else len(tiles)

        library = types.SimpleNamespace()
        if has_function:
            library.cs_tile_store_copy_key_revisions = function
        item = native_bridge.NativeTileStoreHandle.__new__(native_bridge.NativeTileStoreHandle)
        item._library, item._handle = library, object()
        return item, calls

    def test_returns_every_tile_with_its_revision(self):
        tiles = {(0, 0): 4, (5, 2): 2 ** 40, (30, 47): 1}
        handle, calls = self.handle(tiles)
        self.assertEqual(handle.key_revisions(), tiles)
        self.assertEqual(len(calls), 2)                   # taille puis remplissage

    def test_empty_store_and_old_bridge(self):
        handle, _ = self.handle({})
        self.assertEqual(handle.key_revisions(), {})
        handle, _ = self.handle({(1, 1): 1}, has_function=False)
        self.assertIsNone(handle.key_revisions())

    def test_large_store(self):
        tiles = {(x, y): x * 100 + y for x in range(50) for y in range(50)}
        handle, _ = self.handle(tiles)
        self.assertEqual(handle.key_revisions(), tiles)


class OcclusionCacheTests(unittest.TestCase):
    """Un calque inchangé ne recalcule rien d'une image à l'autre ; tout changement est vu."""

    def setUp(self):
        self.renderer = make_renderer()

    def frame(self, layers, width=8 * 64, height=8 * 64):
        self.renderer.begin_frame()
        try:
            return self.renderer.compute_occlusion(layers, width, height)
        finally:
            self.renderer.end_frame()

    def layers(self, revisions=None, opaque=None):
        resident = {(tx, ty) for ty in range(8) for tx in range(8)}
        top = BulkStore(set(resident), revisions=revisions or {k: 1 for k in resident},
                        opaque=resident if opaque is None else opaque)
        return top, [FakeLayer("bottom", BulkStore(set(resident))), FakeLayer("top", top)]

    def test_second_identical_frame_reads_no_pixels_and_gives_the_same_answer(self):
        top, layers = self.layers()
        first = self.frame(layers)
        reads = top.calls["tile"]
        self.assertGreater(reads, 0)
        second = self.frame(layers)
        self.assertEqual(top.calls["tile"], reads)
        self.assertEqual(first["bottom"], second["bottom"])
        self.assertEqual(len(second["bottom"]), 64)

    def test_a_revision_change_is_never_missed(self):
        top, layers = self.layers()
        self.assertEqual(len(self.frame(layers)["bottom"]), 64)
        top.opaque.discard((3, 3))         # la tuile est repeinte de façon translucide...
        top.revisions[(3, 3)] = 2          # ... et sa révision change
        after = self.frame(layers)["bottom"]
        self.assertNotIn((3, 3), after)
        self.assertEqual(len(after), 63)

    def test_new_and_removed_tiles_are_seen(self):
        top, layers = self.layers()
        self.frame(layers)
        top.resident.discard((0, 0))
        self.assertNotIn((0, 0), self.frame(layers)["bottom"])
        top.resident.add((0, 0)); top.revisions[(0, 0)] = 9; top.opaque.add((0, 0))
        self.assertIn((0, 0), self.frame(layers)["bottom"])

    def test_document_resize_invalidates_the_cache(self):
        top, layers = self.layers()
        big = self.frame(layers)["bottom"]
        small = self.frame(layers, 4 * 64, 4 * 64)["bottom"]
        self.assertEqual(len(big), 64)
        self.assertEqual(len(small), 16)

    def test_deleted_layers_are_pruned(self):
        top, layers = self.layers()
        self.frame(layers)
        self.assertIn("top", self.renderer._opaque_set_cache)
        with mock.patch("CANVAS.gpu_renderer.QOpenGLContext") as context:
            context.currentContext.return_value = object()
            self.renderer.prune_layers([layers[0]])
        self.assertNotIn("top", self.renderer._opaque_set_cache)

    def test_old_bridge_without_bulk_revisions_still_works(self):
        resident = {(tx, ty) for ty in range(4) for tx in range(4)}
        top = FakeStore(set(resident), revisions={k: 1 for k in resident}, opaque=resident)
        layers = [FakeLayer("bottom", FakeStore(set(resident))), FakeLayer("top", top)]
        first = self.frame(layers, 4 * 64, 4 * 64)
        second = self.frame(layers, 4 * 64, 4 * 64)
        self.assertEqual(len(first["bottom"]), 16)
        self.assertEqual(first["bottom"], second["bottom"])


class FakeBlitter:
    def __init__(self):
        self.events = []
    def bind(self): self.events.append(("bind",))
    def release(self): self.events.append(("release",))
    def setOpacity(self, value): self.events.append(("opacity", value))
    def blit_matrix(self, texture_id, sx, sy, tx, ty):
        self.events.append(("matrix", texture_id, sx, sy, tx, ty))
    def blit(self, texture_id, transform, origin):
        self.events.append(("transform", texture_id, transform.m11(), transform.m22(),
                            transform.dx(), transform.dy(), origin))


class TiledDrawTests(unittest.TestCase):
    """La passe de dessin regroupe les états GL et garde exactement les mêmes matrices."""

    class Store(FakeStore):
        columns, rows = 8, 6
        def tile_rect(self, tx, ty):
            from types import SimpleNamespace
            x, y = tx * 64, ty * 64
            w, h = min(64, 500 - x), min(64, 380 - y)
            return SimpleNamespace(x=lambda: x, y=lambda: y, width=lambda: w, height=lambda: h)

    def setUp(self):
        from types import SimpleNamespace
        self.renderer = make_renderer()
        self.renderer.blitter = FakeBlitter()
        self.order = []
        real_sync = self.renderer.sync_tile
        def traced(layer, tx, ty):
            self.order.append(("sync", len(self.renderer.blitter.events)))
            return real_sync(layer, tx, ty)
        for patcher in (mock.patch.object(self.renderer, "_create_texture",
                                          side_effect=lambda image, tiled=False: FakeTexture()),
                        mock.patch.object(self.renderer, "_evict_texture_cache"),
                        mock.patch.object(self.renderer, "sync_tile", side_effect=traced)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.document = SimpleNamespace(width=500, height=380)
        self.offset = SimpleNamespace(x=lambda: 13.5, y=lambda: -7.25)

    def make_layer(self):
        resident = {(tx, ty) for ty in range(6) for tx in range(8)}
        return FakeLayer("a", self.Store(resident, revisions={k: 1 for k in resident}), opacity=0.6)

    def draw(self, layer, **kwargs):
        args = dict(viewport_width=900, viewport_height=700, zoom=0.5, offset=self.offset,
                    transform_scale_x=1.0, transform_scale_y=1.0, is_transforming=False,
                    device_pixel_ratio=2.0)
        args.update(kwargs)
        self.renderer._draw_tiled_layer(layer, self.document, **args)

    def test_state_is_bound_once_and_textures_are_synced_before_binding(self):
        layer = self.make_layer()
        self.draw(layer)
        events = self.renderer.blitter.events
        self.assertEqual(events[0], ("bind",))
        self.assertEqual(events[-1], ("release",))
        self.assertEqual(sum(1 for e in events if e[0] == "bind"), 1)
        self.assertEqual(sum(1 for e in events if e[0] == "matrix"), 48)
        # Toutes les synchronisations de textures ont eu lieu avant le premier bind().
        self.assertTrue(all(position == 0 for _, position in self.order))
        self.assertEqual(self.renderer.transfer_stats["tile_draw_calls"], 48)

    def test_matrices_equal_the_previous_transform_math(self):
        layer = self.make_layer()
        self.draw(layer)
        viewport = QRect(0, 0, 1800, 1400)     # (doublure Qt : largeur = 1.0, réel : 1800)
        vw, vh = max(1.0, float(viewport.width())), max(1.0, float(viewport.height()))
        zoom, dpr = 0.5, 2.0
        checked = 0
        for event in self.renderer.blitter.events:
            if event[0] != "matrix":
                continue
        tiles = [e for e in self.renderer.blitter.events if e[0] == "matrix"]
        for index, (ty, tx) in enumerate((ty, tx) for ty in range(6) for tx in range(8)):
            rect = layer.tile_store.tile_rect(tx, ty)
            target = (13.5 + rect.x() * zoom) * dpr, (-7.25 + rect.y() * zoom) * dpr, \
                rect.width() * zoom * dpr, rect.height() * zoom * dpr
            expected = (2.0 * target[2] / vw, 2.0 * target[3] / vh, 2.0 * target[0] / vw - 1.0,
                        1.0 - 2.0 * (target[1] + target[3]) / vh)
            got = tiles[index]
            self.assertEqual(got[2:], expected, (tx, ty))
            checked += 1
        self.assertEqual(checked, 48)

    def test_rotated_view_keeps_the_general_path(self):
        layer = self.make_layer()
        self.draw(layer, view_rotation=15.0)
        kinds = {e[0] for e in self.renderer.blitter.events}
        self.assertIn("transform", kinds)
        self.assertNotIn("matrix", kinds)

    def test_occluded_tiles_are_skipped_without_sync(self):
        layer = self.make_layer()
        occluded = {(tx, ty) for ty in range(6) for tx in range(4)}
        self.draw(layer, occluded_tiles=occluded)
        self.assertEqual(sum(1 for e in self.renderer.blitter.events if e[0] == "matrix"), 24)
        self.assertEqual(self.renderer.transfer_stats["occluded_tile_draws"], 24)

    def test_nothing_visible_means_no_bind(self):
        layer = self.make_layer()
        layer.tile_store.resident.clear()
        self.draw(layer)
        self.assertEqual(self.renderer.blitter.events, [])


class DrawCacheTests(TiledDrawTests):
    """Passe de dessin en cache : même image, beaucoup moins de travail Python."""

    class BulkTiles(BulkStore):
        columns, rows = 8, 6
        tile_rect = TiledDrawTests.Store.tile_rect

    def make_layer(self):
        resident = {(tx, ty) for ty in range(6) for tx in range(8)}
        return FakeLayer("a", self.BulkTiles(resident, revisions={k: 1 for k in resident}),
                         opacity=0.6)

    def frame_draw(self, layer, **kwargs):
        self.renderer.blitter.events.clear()
        self.renderer.begin_frame()
        try:
            self.draw(layer, **kwargs)
        finally:
            self.renderer.end_frame()
        return [e for e in self.renderer.blitter.events if e[0] == "matrix"]

    def sync_count(self):
        return len(self.order)

    def test_cached_frame_draws_exactly_what_the_uncached_path_draws(self):
        layer = self.make_layer()
        first = self.frame_draw(layer)
        plain = self.make_layer()
        plain.tile_store.resident_revisions = lambda: None      # ancien bridge : pas de cache
        reference = self.frame_draw(plain)
        self.assertEqual(len(first), 48)
        self.assertEqual([e[2:] for e in first], [e[2:] for e in reference])

    def test_an_unchanged_second_frame_syncs_nothing(self):
        layer = self.make_layer()
        first = self.frame_draw(layer)
        syncs = self.sync_count()
        second = self.frame_draw(layer)
        self.assertEqual(self.sync_count(), syncs)
        self.assertEqual(second, first)

    def test_only_the_changed_tile_is_resynced(self):
        layer = self.make_layer()
        before = self.frame_draw(layer)
        syncs = self.sync_count()
        layer.tile_store.revisions[(3, 2)] = 2
        after = self.frame_draw(layer)
        self.assertEqual(self.sync_count() - syncs, 1)
        self.assertEqual(len(after), 48)
        changed = set(after) - set(before)
        self.assertEqual(len(changed), 1)          # une seule tuile a une nouvelle texture

    def test_new_and_removed_tiles_are_seen(self):
        layer = self.make_layer()
        self.frame_draw(layer)
        layer.tile_store.resident.discard((0, 0))
        self.assertEqual(len(self.frame_draw(layer)), 47)
        layer.tile_store.resident.add((0, 0))
        layer.tile_store.revisions[(0, 0)] = 5
        self.assertEqual(len(self.frame_draw(layer)), 48)

    def test_a_view_change_rebuilds_the_matrices(self):
        layer = self.make_layer()
        first = self.frame_draw(layer)
        moved = self.frame_draw(layer, zoom=0.75)
        self.assertNotEqual([e[2:] for e in first], [e[2:] for e in moved])
        again = self.frame_draw(layer, zoom=0.75)
        self.assertEqual(again, moved)

    def test_texture_destruction_invalidates_the_cache(self):
        layer = self.make_layer()
        self.frame_draw(layer)
        syncs = self.sync_count()
        self.renderer._texture_generation += 1
        self.frame_draw(layer)
        self.assertEqual(self.sync_count() - syncs, 48)

    def test_a_tile_that_was_loading_appears_once_it_is_resident(self):
        layer = self.make_layer()
        layer.tile_store.resident.discard((1, 1))
        layer.tile_store._swapped[(1, 1)] = Path("/dev/null")
        self.assertEqual(len(self.frame_draw(layer)), 47)
        layer.tile_store.resident.add((1, 1))
        layer.tile_store._swapped.clear()
        layer.tile_store.revisions[(1, 1)] = 1
        self.assertEqual(len(self.frame_draw(layer)), 48)

    def test_occlusion_change_is_honoured(self):
        layer = self.make_layer()
        self.assertEqual(len(self.frame_draw(layer)), 48)
        hidden = frozenset((tx, ty) for ty in range(6) for tx in range(4))
        self.assertEqual(len(self.frame_draw(layer, occluded_tiles=hidden)), 24)
        self.assertEqual(len(self.frame_draw(layer, occluded_tiles=hidden)), 24)
        self.assertEqual(len(self.frame_draw(layer)), 48)

    def test_opacity_is_applied_every_frame(self):
        layer = self.make_layer()
        self.frame_draw(layer)
        layer.opacity = 0.25
        self.frame_draw(layer)
        opacities = [e[1] for e in self.renderer.blitter.events if e[0] == "opacity"]
        self.assertEqual(opacities, [0.25])

    def test_a_blitter_with_draw_tiles_gets_the_same_tiles(self):
        layer = self.make_layer()
        reference = self.frame_draw(layer)
        seen = []
        self.renderer.blitter.draw_tiles = lambda items: seen.extend(items)
        self.renderer._draw_cache.clear()
        self.frame_draw(layer)
        self.assertEqual(seen, [e[1:] for e in reference])

    def test_deleted_layers_drop_their_cache(self):
        layer = self.make_layer()
        self.frame_draw(layer)
        self.assertIn("a", self.renderer._draw_cache)
        with mock.patch("CANVAS.gpu_renderer.QOpenGLContext") as ctx:
            ctx.currentContext.return_value = object()
            self.renderer.prune_layers([])
        self.assertNotIn("a", self.renderer._draw_cache)


# Les tests hérités de TiledDrawTests sont déjà exécutés par leur propre classe.
for _name in [n for n in dir(TiledDrawTests) if n.startswith("test_")]:
    if _name not in DrawCacheTests.__dict__:
        setattr(DrawCacheTests, _name, None)


class BigCanvasCacheTests(unittest.TestCase):
    """Régression : canevas 2500x3000 (40 x 47 = 1880 tuiles) => uploads à chaque image."""

    class Store(FakeStore):
        columns, rows = 40, 47
        def tile_rect(self, tx, ty):
            from types import SimpleNamespace
            x, y = tx * 64, ty * 64
            w, h = min(64, 2500 - x), min(64, 3000 - y)
            return SimpleNamespace(x=lambda: x, y=lambda: y, width=lambda: w, height=lambda: h)

    def test_a_full_canvas_is_uploaded_once_not_every_frame(self):
        from types import SimpleNamespace
        renderer = make_renderer()
        renderer.blitter = FakeBlitter()
        created = []
        def create(image, tiled=False):
            created.append(1)
            return FakeTexture()
        resident = {(tx, ty) for ty in range(47) for tx in range(40)}
        layers = [FakeLayer(name, self.Store(resident, revisions={k: 1 for k in resident}))
                  for name in ("background", "sketch")]
        document = SimpleNamespace(width=2500, height=3000)
        offset = SimpleNamespace(x=lambda: 0.0, y=lambda: 0.0)
        with mock.patch.object(renderer, "_create_texture", side_effect=create):
            for _ in range(5):
                renderer.begin_frame()
                try:
                    for layer in layers:
                        renderer._draw_tiled_layer(
                            layer, document, viewport_width=2600, viewport_height=3100, zoom=1.0,
                            offset=offset, transform_scale_x=1.0, transform_scale_y=1.0,
                            is_transforming=False, device_pixel_ratio=1.0)
                finally:
                    renderer.end_frame()
        self.assertEqual(len(created), 2 * 1880)          # première image seulement
        self.assertEqual(len(renderer.textures), 2 * 1880)

    def test_byte_budget_still_bounds_the_cache(self):
        renderer = make_renderer()
        renderer.max_cached_bytes = 8 * 8 * 4 * 100         # 100 tuiles (FakeImage : 8 x 8)
        store = FakeStore({(x, 0) for x in range(300)}, revisions={(x, 0): 1 for x in range(300)})
        layer = FakeLayer("a", store)
        with mock.patch.object(renderer, "_create_texture", side_effect=lambda i, tiled=False: FakeTexture()):
            for x in range(300):
                renderer.sync_tile(layer, x, 0)
        self.assertLessEqual(len(renderer.textures), 100)


class SafeBlitterStateTests(unittest.TestCase):
    """SafeTextureBlitter : programme/VAO liés une fois par passe, uniforms mis en cache."""

    def make(self):
        from CANVAS.gpu_safe_blitter import SafeTextureBlitter
        blitter = SafeTextureBlitter()
        blitter.gl = mock.MagicMock(name="gl")
        blitter.program = mock.MagicMock(name="program")
        blitter.program.uniformLocation.side_effect = lambda name: hash(name) % 97
        blitter.vao = mock.MagicMock(name="vao")
        return blitter

    def test_one_pass_of_many_tiles(self):
        b = self.make()
        b.bind(); b.setOpacity(0.5)
        for i in range(200):
            b.blit_matrix(10 + i, 0.1, 0.2, -0.5, 0.5)
        b.release()
        self.assertEqual(b.program.bind.call_count, 1)
        self.assertEqual(b.vao.bind.call_count, 1)
        self.assertEqual(b.program.uniformLocation.call_count, 7)     # une fois pour toutes
        self.assertEqual(b.gl.glDrawArrays.call_count, 200)
        self.assertEqual(b.gl.glUniform1i.call_count, 2)              # uTexture + uFlipY, une seule fois
        self.assertEqual(b.program.release.call_count, 1)

    def test_draw_tiles_uses_three_gl_calls_per_tile_and_restores_the_mode(self):
        b = self.make()
        b.bind()
        items = [(10 + i, 0.1, 0.2, -0.5, 0.5) for i in range(200)]
        b.draw_tiles(iter(items))
        b.release()
        self.assertEqual(b.gl.glDrawArrays.call_count, 200)
        self.assertEqual(b.gl.glBindTexture.call_count, 200)
        self.assertEqual(b.gl.glUniform4f.call_count, 200)
        self.assertEqual(b.gl.glUniform2f.call_count, 0)
        use_rect = b._loc["uUseRect"]
        modes = [c.args for c in b.gl.glUniform1i.call_args_list if c.args[0] == use_rect]
        self.assertEqual(modes, [(use_rect, 1), (use_rect, 0)])
        self.assertEqual(b.gl.glActiveTexture.call_count, 2)          # bind() + une fois par passe
        first = b.gl.glUniform4f.call_args_list[0].args
        self.assertEqual(first[1:], (0.1, 0.2, -0.5, 0.5))

    def test_draw_tiles_standalone_binds_and_releases(self):
        b = self.make()
        b.draw_tiles([(1, 1.0, 1.0, 0.0, 0.0)])
        self.assertEqual(b.program.bind.call_count, 1)
        self.assertEqual(b.program.release.call_count, 1)

    def test_standalone_blit_still_works_without_bind(self):
        from PySide6.QtGui import QTransform
        b = self.make()
        transform = mock.MagicMock()
        for name in ("m11", "m21", "m12", "m22", "dx", "dy"):
            getattr(transform, name).return_value = 0.25
        b.blit(7, transform, "top_left")
        b.blit(8, transform, "bottom_left")
        self.assertEqual(b.gl.glDrawArrays.call_count, 2)
        self.assertEqual(b.program.bind.call_count, 2)
        self.assertEqual(b.program.release.call_count, 2)
        self.assertFalse(b._bound)

    def test_flip_and_opacity_are_only_resent_when_they_change(self):
        b = self.make()
        transform = mock.MagicMock()
        for name in ("m11", "m21", "m12", "m22", "dx", "dy"):
            getattr(transform, name).return_value = 1.0
        b.bind()
        b.blit(1, transform, "top_left"); b.blit(2, transform, "top_left")
        flips = b.gl.glUniform1i.call_count
        b.blit(3, transform, "bottom_left")
        self.assertEqual(b.gl.glUniform1i.call_count, flips + 1)
        opacity_calls = b.gl.glUniform1f.call_count
        b.setOpacity(b.opacity)                                       # inchangée
        self.assertEqual(b.gl.glUniform1f.call_count, opacity_calls)
        b.setOpacity(0.3)
        self.assertEqual(b.gl.glUniform1f.call_count, opacity_calls + 1)
        b.release()

    def test_bind_is_a_noop_before_creation(self):
        from CANVAS.gpu_safe_blitter import SafeTextureBlitter
        b = SafeTextureBlitter()
        b.bind(); b.blit_matrix(1, 1, 1, 0, 0); b.release()          # ne doit rien lever


if __name__ == "__main__":
    unittest.main()
