"""Regression tests for the general performance-overhaul pass.

Covers two independent fixes found by auditing for the same "recompute/rewrite
the whole document on every dab" bug class as the mask-painting fix:

1. Canvas._apply_filter_segment (blur/sharpen tools) used to commit through
   `layer.image = image`, which writes every tile of the document via the
   native bridge, and every call site then repeated that same full write a
   second time by re-assigning the return value back to `.image`/`.image`.
   That's two full-document native writes per mouse-move event while
   blurring/sharpening. It should now write only the segment's dirty rect,
   once.

2. GPURenderer.prune_layers() used to do four full scans over its caches
   (which can hold tens of thousands of cached-tile entries) on every single
   frame, even when the document's set of layers hadn't changed since the
   last frame (the overwhelming majority of frames: painting, panning,
   idling). It should now short-circuit when the live layer-id set is
   unchanged.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. _apply_filter_segment
# ---------------------------------------------------------------------------

def test_filter_segment_source_no_longer_double_writes_full_document():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    # The four blur/sharpen call sites must no longer re-assign the result
    # back onto `.image` (that used to be call #2 of a full-document write;
    # _apply_filter_segment now commits its own dirty rect internally).
    assert "layer.image = self._apply_filter_segment(" not in src
    assert "active_layer.image = self._apply_filter_segment(" not in src
    assert src.count("self._apply_filter_segment(") == 4

    start = src.index("    def _apply_filter_segment(")
    end = src.index("\n    def ", start + 10)
    body = src[start:end]
    # The old blanket commit (a bare assignment statement, not the comment
    # that now explains why it was removed) and full-widget repaint must be
    # gone...
    assert "layer.image = image\n            self.tile_history.mark_dirty" not in body
    assert "\n        self.update()\n" not in body
    # ...replaced by a dirty-rect-scoped write and a dirty-rect-scoped repaint.
    assert "layer.tile_store.write_image(image, dirty)" in body
    assert "layer.discard_image_cache()" in body
    assert "self._repaint_brush_dirty_rect(dirty)" in body


def test_filter_segment_commits_only_the_dirty_rect():
    """Exercise the real method body against a fake layer/tile_store."""
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _apply_filter_segment(")
    end = src.index("\n    def ", start + 10)
    body = "class H:\n" + src[start:end] + "\n"

    calls = {"filter_brush_segment": 0}

    def fake_filter_brush_segment(image, *a, **k):
        calls["filter_brush_segment"] += 1
        return image  # non-None => native filter path succeeded

    class FakeFormat:
        Format_RGBA8888 = "rgba8888"

    class FakeImage:
        Format = FakeFormat

        def __init__(self, fmt="rgba8888"):
            self._fmt = fmt

        def format(self):
            return self._fmt

        def convertToFormat(self, fmt):
            return FakeImage(fmt)

    class FakeQImage:
        Format = FakeFormat

    class FakePoint:
        def __init__(self, x, y):
            self._x, self._y = x, y

        def x(self):
            return self._x

        def y(self):
            return self._y

    ns = {
        "QImage": FakeQImage,
        "QPoint": FakePoint,
        "filter_brush_segment": fake_filter_brush_segment,
    }
    exec(body, ns)
    H = ns["H"]

    tile_writes = []

    class FakeTileStore:
        def write_image(self, image, rect):
            tile_writes.append(rect)

    class FakeLayer:
        def __init__(self):
            self.tile_store = FakeTileStore()
            self.discarded = False

        def discard_image_cache(self):
            self.discarded = True

    class FakeHistory:
        def __init__(self):
            self.before = []
            self.dirty = []

        def capture_before(self, layer, rect):
            self.before.append(rect)

        def mark_dirty(self, layer, rect):
            self.dirty.append(rect)

    class FakeGpuRenderer:
        def __init__(self):
            self.dirtied = []

        def mark_layer_dirty(self, layer, rect):
            self.dirtied.append(rect)

    h = H()
    layer = FakeLayer()
    h.tile_history = FakeHistory()
    h.gpu_ready = True
    h.gpu_renderer = FakeGpuRenderer()
    h.brush_settings = SimpleNamespace(snapshot=lambda: {"size": 10.0, "spacing": 0.15,
                                                          "opacity": 1.0, "flow": 1.0})
    h.document = SimpleNamespace(width=2500, height=3000)
    h.symmetry_horizontal = False
    h.symmetry_vertical = False
    h.get_active_layer = lambda: layer
    the_dirty_rect = "dirty-rect-42x42"
    h._brush_dirty_rect = lambda start, end: the_dirty_rect
    h._restore_locked_alpha = lambda image, rect: None
    repainted = []
    h._repaint_brush_dirty_rect = lambda rect: repainted.append(rect)

    image = FakeImage()
    start_point = ns["QPoint"](0, 0)
    end_point = ns["QPoint"](1, 1)
    result = h._apply_filter_segment(image, start_point, end_point, 1.0, 1.0, False)

    assert calls["filter_brush_segment"] == 1
    # Exactly one write, scoped to the dirty rect - never the whole document.
    assert tile_writes == [the_dirty_rect]
    assert layer.discarded is True
    assert h.tile_history.dirty == [the_dirty_rect]
    assert h.gpu_renderer.dirtied == [the_dirty_rect]
    assert repainted == [the_dirty_rect]
    assert result is image


# ---------------------------------------------------------------------------
# 2. GPURenderer.prune_layers
# ---------------------------------------------------------------------------

def _load_prune_layers():
    src = (ROOT / "CANVAS" / "gpu_renderer.py").read_text()
    start = src.index("    def prune_layers(")
    end = src.index("    def _evict_texture_cache(")
    body = "class H:\n" + src[start:end]

    class FakeContext:
        @staticmethod
        def currentContext():
            return object()  # non-None: pretend a GL context is current

    ns = {"QOpenGLContext": FakeContext, "QRect": object}
    exec(body, ns)
    return ns["H"]


def make_renderer(H, texture_keys):
    class FakeTexture:
        def __init__(self):
            self.width = 64
            self.height = 64

            class T:
                @staticmethod
                def isCreated():
                    return False
            self.texture = T()

    h = H()
    h.textures = {key: FakeTexture() for key in texture_keys}
    h._opaque_set_cache = {key[0]: object() for key in texture_keys}
    h._draw_cache = {key[0]: object() for key in texture_keys}
    h._opaque_tile_cache = {key: object() for key in texture_keys}
    h.dirty_layers = {key[0] for key in texture_keys}
    h.dirty_rects = {key[0]: object() for key in texture_keys}
    h._texture_generation = 0
    h._cached_texture_bytes = sum(64 * 64 * 4 for _ in texture_keys)
    h._prune_last_live_keys = None
    return h


def test_prune_layers_short_circuits_when_layer_set_is_unchanged():
    H = _load_prune_layers()
    keys = [("layer-a", 0, 0), ("layer-b", 0, 0), ("layer-b", 1, 0)]
    h = make_renderer(H, keys)
    layers = [SimpleNamespace(id="layer-a"), SimpleNamespace(id="layer-b")]

    h.prune_layers(layers)
    # First call with a fresh cache still has to record the live set, but
    # nothing was stale, so nothing should have been evicted.
    assert set(h.textures) == set(keys)

    # Sabotage the caches the way a bug would (leftover entry for a layer
    # that's no longer live) - if prune_layers actually re-scanned, this
    # would get cleaned. Since the live set hasn't changed since last call,
    # it must be left alone: proves the early-return path was taken, not
    # just "there happened to be nothing stale".
    h.textures[("ghost", 0, 0)] = h.textures[("layer-a", 0, 0)]
    h.prune_layers(layers)
    assert ("ghost", 0, 0) in h.textures


def test_prune_layers_still_evicts_when_layer_set_changes():
    H = _load_prune_layers()
    keys = [("layer-a", 0, 0), ("layer-b", 0, 0)]
    h = make_renderer(H, keys)
    h.prune_layers([SimpleNamespace(id="layer-a"), SimpleNamespace(id="layer-b")])

    # Remove layer-b from the document: its cache entries must be pruned.
    h.prune_layers([SimpleNamespace(id="layer-a")])
    assert ("layer-b", 0, 0) not in h.textures
    assert ("layer-a", 0, 0) in h.textures
    assert "layer-b" not in h._draw_cache
    assert "layer-b" not in h._opaque_set_cache
