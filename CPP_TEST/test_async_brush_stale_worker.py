"""Regression test for: "au stylet ca reste casse" - a hard-edged block of
the wrong color stamped over a fresh stroke, plus wet/smudge sometimes not
applying at all, specifically with the stylus (never with the mouse).

Root cause: mousePressEvent/mouseMoveEvent never touch the async-brush path
at all (grep confirms _can_use_async_brush/_begin_async_brush are only
referenced from Canvas.tabletEvent) - the stylus path additionally falls
back to BrushAsyncWorker (CPP_CORE/src/brush_async_worker.cpp), which runs
each stroke's dab compositing on a background std::thread and streams
patches back to Python.

TabletRelease's cs_brush_async_finish() only *requests* that worker to wrap
up (BrushAsyncWorker::finish() just sets a flag and returns - it does not
join the thread); the worker is actually destroyed/joined later, when its
final complete=True patch reaches _apply_async_brush_patch on the UI thread.
A fast lift-then-press (very normal for real stylus painting) used to reach
_begin_async_brush() again while the previous worker's handle was still
sitting in self._async_brush_handle: it got silently overwritten, orphaning
that worker. It kept running - matched only by layer id, with no idea the
stroke that started it was abandoned - and:
  1. its late patches got pasted straight onto the pixels of the *new*
     stroke via write_image_at (a hard-edged block of stale color), and
  2. its eventual completion decremented the *new* stroke's
     _async_stroke_pending counter, occasionally driving it to 0 early and
     cancelling the new stroke outright (which is why the wet/smudge effect
     sometimes just didn't show up).

The fix: _begin_async_brush() now force-cancels any handle still sitting in
self._async_brush_handle before creating a new one (never orphans a
worker), and each worker's `receive` callback closes over the stroke
generation it was started with, dropping any patch that arrives after its
stroke has since been abandoned - belt-and-suspenders for a callback that
was already in flight before the cancel took effect.
"""
import ctypes
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load_begin_async_brush():
    src = (ROOT / "CANVAS" / "canvas.py").read_text()
    start = src.index("    def _begin_async_brush(")
    end = src.index("    def _queue_async_brush(")
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


class FakeImage:
    """Enough of a QImage stand-in to exercise the real ctypes buffer call:
    a bytearray supports the buffer protocol, same as a real QImage's bits()."""

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
    H = _load_begin_async_brush()
    h = H()
    h.symmetry_horizontal = False
    h.symmetry_vertical = False
    h.document = SimpleNamespace(width=100, height=100)
    h._async_brush_handle = None
    h._async_brush_layer_id = None
    h._async_symmetry_handles = []
    h._async_stroke_pending = 0
    h._async_stroke_generation = 0

    h.sync_calls = 0
    h._sync_cpp_brush = lambda: setattr(h, "sync_calls", h.sync_calls + 1)
    h._queue_async_brush = lambda *a, **k: True

    cancel_calls = []

    def fake_cancel():
        cancel_calls.append(True)
        # The real cs_brush_async_destroy() deletes the native worker
        # synchronously, which joins its thread - and that worker can be
        # mid-batch (already past its own "am I cancelled?" check) when this
        # runs, calling back into `receive` on its own thread *while* this
        # join blocks us. Simulate exactly that: fire the about-to-be-
        # cancelled worker's own callback from inside the cancel call.
        if h._receives:
            h._receives[-1](0, 9, 9, 4, 4, None, 16, False, b"", None)
        h._async_brush_handle = None
        h._async_symmetry_handles = []
        h._async_stroke_pending = 0
    h._cancel_async_brush = fake_cancel
    h._cancel_calls = cancel_calls

    receives = []

    class FakeLib:
        _cs_brush_async_callback_type = staticmethod(lambda f: (receives.append(f), f)[1])

        def cs_brush_begin_stroke(self, *a):
            pass

        def cs_brush_async_start(self, *a, **k):
            return SimpleNamespace(n=len(receives))

    h.cpp_brush_library = FakeLib()
    h.cpp_brush = object()
    h._receives = receives

    emitted = []
    h.async_brush_patch = SimpleNamespace(emit=lambda *a: emitted.append(a))
    h._emitted = emitted

    return h


def test_begin_async_brush_cancels_a_still_live_previous_handle_before_starting():
    h = make_harness()
    layer = SimpleNamespace(id="layer-1", image=FakeImage())

    assert h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)
    first_handle = h._async_brush_handle
    assert h._cancel_calls == []  # nothing stale yet - must not cancel needlessly

    # Simulate the race: a new press arrives while the previous worker's
    # handle is still live (TabletRelease only *requested* finish - the
    # worker hasn't completed/been cleaned up yet).
    assert h._begin_async_brush(layer, SimpleNamespace(x=lambda: 2, y=lambda: 2), 0.5)
    assert h._cancel_calls == [True]  # the stale handle was force-cancelled
    assert h._async_brush_handle is not first_handle  # never silently overwritten-while-live


def test_stale_generation_callback_is_dropped_not_misapplied():
    h = make_harness()
    layer = SimpleNamespace(id="layer-1", image=FakeImage())

    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)
    stale_receive = h._receives[0]
    generation_after_first = h._async_stroke_generation

    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 2, y=lambda: 2), 0.5)
    fresh_receive = h._receives[1]
    assert h._async_stroke_generation != generation_after_first

    # The orphaned worker's callback fires late (as if it were still running
    # in the background) - it must be silently dropped, not applied to the
    # pixels/state of the stroke that superseded it.
    stale_receive(0, 5, 5, 4, 4, None, 16, False, b"", None)
    assert h._emitted == []

    # A callback from the *current* worker must still go through normally.
    fresh_receive(0, 5, 5, 4, 4, None, 16, False, b"", None)
    assert len(h._emitted) == 1


def test_generation_is_bumped_before_the_stale_worker_is_cancelled():
    """The narrowest, realest form of the race, and the actual gap in the
    first version of this fix: cs_brush_async_destroy() joins the old
    worker's thread synchronously, and that worker can be mid-batch when
    this happens, calling back into `receive` from its own thread *while*
    the join is still blocking us (make_harness's fake_cancel simulates this
    directly). If the generation were only bumped *after* the cancel call
    returned, that straggler would still read the old, still-matching
    generation and slip through - which is exactly what kept the block/
    stripe artifact reproducing even after the first fix was built and
    installed. The generation must already be new by the time cancel runs."""
    h = make_harness()
    layer = SimpleNamespace(id="layer-1", image=FakeImage())

    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)
    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 2, y=lambda: 2), 0.5)

    assert h._cancel_calls == [True]
    # The stale worker's mid-cancel straggler callback must have been
    # dropped, not emitted onto the new stroke.
    assert h._emitted == []


def test_no_previous_handle_means_no_spurious_cancel():
    """The common case (previous stroke already fully completed and cleaned
    itself up via _apply_async_brush_patch) must not pay for a cancel call
    it doesn't need."""
    h = make_harness()
    layer = SimpleNamespace(id="layer-1", image=FakeImage())
    h._begin_async_brush(layer, SimpleNamespace(x=lambda: 1, y=lambda: 1), 0.5)
    assert h._cancel_calls == []


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
