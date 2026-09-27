"""Regression test for the real root cause behind every "stylet + oil flat /
smudge" artifact this round: a use-after-free on the pixel buffer the async
brush worker(s) read and write for the whole duration of a stroke.

_begin_async_brush() builds:

    image = layer.image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = (ctypes.c_uint8 * image.sizeInBytes()).from_buffer(image.bits())
    handle = lib.cs_brush_async_start(self.cpp_brush, raw, ...)

cs_brush_async_start (creative_core_api.cpp) wraps `raw` in a QImage
constructed over that *external* pointer:

    QImage borrowed(rgba, width, height, stride, QImage::Format_RGBA8888);
    ... BrushAsyncWorker(*engine, borrowed, strokeId, ...)

and BrushAsyncWorker stores a `SourceProvider` lambda that captures that
QImage by value. For a QImage built over external memory this way, a "copy"
still shares the exact same buffer (Qt does not deep-copy it), and the
worker's run() does `m_image = m_sourceProvider();` and then draws directly
into that shared buffer on its own background thread for as long as the
stroke lasts - potentially seconds, across many segments.

Both `image` and `raw` in _begin_async_brush were plain local variables:
nothing on `self` referenced either one, and the C ABI call only receives
the raw pointer, not a reference to the Python objects behind it. The
instant _begin_async_brush() returned, both became eligible for garbage
collection - while the worker thread(s) were still actively reading from and
writing to that exact memory. Whenever CPython's allocator actually reused
that freed block before the stroke finished (timing-dependent, which is why
this reproduced differently every time - a solid block, then stripes, then a
clean stroke in a color that was never selected), the worker ended up
compositing into memory that belonged to something else entirely. A leaked
or reused buffer landing on a plausible-looking flat color explains the
symptom far better than a torn/raced patch would: the strokes in the
screenshots were cleanly shaped, just wrongly colored.

Mouse painting never touches this code path at all (only Canvas.tabletEvent
calls _begin_async_brush), which is why this was stylus-only from the start,
independent of the two race-condition fixes already made to this method.

The fix: pin both `image` and `raw` on `self` (`_async_brush_source_image` /
`_async_brush_source_raw`) for the async stroke's entire lifetime, cleared
only in _cancel_async_brush() once every worker that could still be touching
that memory (the primary handle and every symmetry clone) has been
destroyed, which joins its thread first.
"""
import ctypes
import gc
import weakref
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load_async_brush_methods():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _begin_async_brush(")
    end = src.index("    def _apply_async_brush_patch(")
    body = "class H:\n" + src[start:end]

    class FakeQImage:
        Format = SimpleNamespace(Format_RGBA8888=1)

        def __init__(self, *a, **k):
            pass

        def copy(self):
            return self

    ns = {"QImage": FakeQImage,
          "QPoint": lambda x, y: SimpleNamespace(x=lambda: x, y=lambda: y),
          "ctypes": ctypes, "time": __import__("time")}
    exec(body, ns)
    return ns["H"]


class TrackedImage:
    """Stands in for the QImage returned by layer.image.convertToFormat():
    supports weak references (like any normal Python object/QImage would),
    so the test can observe whether it's actually kept alive."""

    def __init__(self, w=8, h=8, bpl=32):
        self._buf = bytearray(bpl * h)
        self._w, self._h, self._bpl = w, h, bpl

    def convertToFormat(self, fmt):
        return self

    def bits(self):
        return self._buf

    def sizeInBytes(self):
        return len(self._buf)

    def width(self):
        return self._w

    def height(self):
        return self._h

    def bytesPerLine(self):
        return self._bpl


def make_harness():
    H = _load_async_brush_methods()
    h = H()
    h.symmetry_horizontal = False
    h.symmetry_vertical = False
    h.document = SimpleNamespace(width=100, height=100)
    h._async_brush_handle = None
    h._async_brush_layer_id = None
    h._async_symmetry_handles = []
    h._async_stroke_pending = 0
    h._async_stroke_generation = 0
    h._async_brush_source_image = None
    h._async_brush_source_raw = None

    h._sync_cpp_brush = lambda: None
    h._queue_async_brush = lambda *a, **k: True

    def fake_cancel():
        h._async_brush_handle = None
        h._async_symmetry_handles = []
        h._async_stroke_pending = 0
        h._async_brush_source_image = None
        h._async_brush_source_raw = None
    h._cancel_async_brush = fake_cancel

    class FakeLib:
        _cs_brush_async_callback_type = staticmethod(lambda f: f)

        def cs_brush_begin_stroke(self, *a):
            pass

        def cs_brush_async_start(self, *a, **k):
            return SimpleNamespace()

    h.cpp_brush_library = FakeLib()
    h.cpp_brush = object()
    h.async_brush_patch = SimpleNamespace(emit=lambda *a: None)
    return h


def test_source_image_survives_gc_after_begin_async_brush_returns():
    """The core of the bug: once _begin_async_brush() returns, its local
    `image`/`raw` variables must not be the only thing keeping the pixel
    buffer alive. If nothing on `self` holds a reference, a real GC pass can
    reclaim it while the (real, threaded) worker is still using it."""
    h = make_harness()
    tracked = TrackedImage()
    watch = weakref.ref(tracked)
    layer = SimpleNamespace(id="layer-1", image=tracked)

    assert h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)

    # Drop every reference this test itself holds, exactly as a real
    # TabletPress handler would once _begin_async_brush() returns.
    del tracked, layer
    gc.collect()

    assert watch() is not None, (
        "the async stroke's source image was garbage-collected while the "
        "stroke was still active - this is the use-after-free: a real "
        "background worker would now be reading/writing freed memory"
    )
    # And it must be reachable specifically via the pinning attribute, not
    # by accident through some other path.
    assert h._async_brush_source_image is watch()


def test_source_image_is_released_once_the_stroke_is_cancelled_or_completed():
    """The other half: pinning the buffer forever would just trade a
    use-after-free for a leak that grows with every stroke. Once
    _cancel_async_brush() has actually destroyed every worker that could
    still touch the memory, the pin must be dropped."""
    h = make_harness()
    tracked = TrackedImage()
    watch = weakref.ref(tracked)
    layer = SimpleNamespace(id="layer-1", image=tracked)

    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)
    assert h._async_brush_source_image is not None

    h._cancel_async_brush()
    assert h._async_brush_source_image is None
    assert h._async_brush_source_raw is None

    del tracked, layer
    gc.collect()
    assert watch() is None, "the source image leaked past the stroke's end"


def test_symmetry_clones_share_the_same_pinned_buffer():
    """Symmetry clones are started with the *same* `raw` buffer
    (cs_brush_async_start(clone, raw, ...)) - confirm the pin covers that
    shared buffer too, not just the primary handle's own copy of the
    reference."""
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _begin_async_brush(")
    end = src.index("    def _queue_async_brush(")
    body = src[start:end]
    pin_index = body.index("self._async_brush_source_raw = raw")
    symmetry_loop_index = body.index("for idx, (mx, my, tsx, tsy) in enumerate(sym_axes):")
    assert pin_index < symmetry_loop_index, (
        "the buffer must be pinned before the symmetry clones (which reuse "
        "the same `raw`) are started, not after"
    )


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
