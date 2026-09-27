"""Regression test for: "AttributeError: 'NoneType' object has no attribute
'x'" crashing Canvas.tabletEvent mid-stroke, in
_cpp_draw_segment's `if stabilize:` branch (CANVAS/canvas.py):

    File "CANVAS/canvas.py", line ..., in _cpp_draw_segment
    start = QPoint(round(previous.x()), round(previous.y()))
    AttributeError: 'NoneType' object has no attribute 'x'

Root cause: `previous = getattr(self, "_cpp_smoothed_point", QPointF(start))`
only falls back to the QPointF(start) default when the attribute is
MISSING. But _cpp_end_stroke() deliberately sets
`self._cpp_smoothed_point = None` when a stroke ends - so once a single
stroke has happened, the attribute always EXISTS, and getattr happily hands
back that stored None instead of ever using the default.

tabletEvent's TabletMove handler can call _cpp_draw_segment(..., stabilize=
True) again while self.drawing is still True but no TabletRelease has fired
in between - specifically, if the previous move's _cpp_draw_segment returned
None (a bad QImage ctypes buffer, cpp_brush_enabled toggled off mid-stroke,
etc.) it falls into `else: self._cpp_end_stroke()` right there in the event
handler (CANVAS/canvas.py, TabletMove branch), which zeroes
_cpp_smoothed_point - and the very next TabletMove crashes the tablet event
override outright (PySide6 swallows the exception at the C++/Python
boundary and just prints the traceback, but the stroke silently stops
using the smoothed/stabilized point handling from then on, if it doesn't
kill the event loop's error reporting entirely).

The fix: check `previous is None` explicitly after the getattr, covering
both "attribute missing" and "attribute present but None" the same way -
falling back to QPointF(start) in both cases, exactly as the original
default was always meant to.
"""
import ctypes
import textwrap
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "CANVAS" / "canvas.py"


class FakeQPointF:
    def __init__(self, *args):
        if len(args) == 1 and hasattr(args[0], "x"):
            self._x, self._y = float(args[0].x()), float(args[0].y())
        else:
            self._x, self._y = float(args[0]), float(args[1])

    def x(self):
        return self._x

    def y(self):
        return self._y


class FakeQPoint:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


def _extract_stabilize_block() -> str:
    """Pulls the exact `if stabilize:` block out of _cpp_draw_segment, byte
    for byte - this test runs the REAL source, not a transcription, so it
    can't drift from what actually ships."""
    src = SRC_PATH.read_text()
    method_start = src.index("    def _cpp_draw_segment(")
    block_start = src.index("        if stabilize:", method_start)
    block_end = src.index("\n        layer = self.get_active_layer()", block_start)
    return src[block_start:block_end]


def _fake_smooth_point(handle, ex, ey, out_x_ref, out_y_ref):
    """Stand-in for cs_brush_smooth_point: always succeeds, and writes
    through the ctypes.byref() pointers exactly like the real C function
    would, so the exec'd source's `ctypes.byref(out_x)` plumbing is
    exercised for real rather than mocked away."""
    ctypes.cast(out_x_ref, ctypes.POINTER(ctypes.c_float))[0] = ex + 1.0
    ctypes.cast(out_y_ref, ctypes.POINTER(ctypes.c_float))[0] = ey + 1.0
    return True


def _run_stabilize_block(smoothed_point_attr_present: bool, smoothed_point_value=None):
    block = _extract_stabilize_block()

    fake_self = SimpleNamespace(
        cpp_brush_library=SimpleNamespace(cs_brush_smooth_point=_fake_smooth_point),
        cpp_brush=object(),
    )
    if smoothed_point_attr_present:
        fake_self._cpp_smoothed_point = smoothed_point_value

    namespace = {
        "self": fake_self,
        "stabilize": True,
        "start": FakeQPoint(10, 20),
        "end": FakeQPoint(30, 40),
        "ctypes": ctypes,
        "QPointF": FakeQPointF,
        "QPoint": FakeQPoint,
        "round": round,
    }
    exec(textwrap.dedent(block), namespace)  # noqa: S102 - deliberately executing the real source under test
    return namespace["start"], namespace["end"]


def test_missing_attribute_falls_back_to_start_without_crashing():
    """Baseline: attribute never set at all (e.g. very first stroke ever) -
    this already worked before the fix, must keep working."""
    start, end = _run_stabilize_block(smoothed_point_attr_present=False)
    assert (start.x(), start.y()) == (10, 20)


def test_none_valued_attribute_falls_back_to_start_instead_of_crashing():
    """The actual regression: _cpp_smoothed_point IS set, but to None (the
    exact state _cpp_end_stroke() leaves it in). Before the fix this raised
    AttributeError: 'NoneType' object has no attribute 'x'."""
    start, end = _run_stabilize_block(
        smoothed_point_attr_present=True, smoothed_point_value=None
    )
    assert (start.x(), start.y()) == (10, 20)


def test_real_stored_point_is_still_used_when_present():
    """Make sure the fix didn't turn the fallback into the only path - a
    genuinely stored smoothed point from earlier in the stroke must still
    be used, not silently discarded in favour of `start`."""
    stored = FakeQPointF(5.0, 7.0)
    start, end = _run_stabilize_block(
        smoothed_point_attr_present=True, smoothed_point_value=stored
    )
    assert (start.x(), start.y()) == (5, 7)


def test_source_checks_previous_is_none_after_the_getattr():
    """Pins the fix in canvas.py: the getattr's result must be explicitly
    None-checked before `.x()`/`.y()` are ever called on it, so a stored
    None (not just a missing attribute) can never reach `previous.x()`."""
    src = SRC_PATH.read_text()
    anchor = 'previous = getattr(self, "_cpp_smoothed_point", None)'
    assert anchor in src, (
        "expected the getattr's default to be None (an explicit is-None "
        "check must follow), not QPointF(start) used directly as the "
        "getattr default"
    )
    after = src[src.index(anchor):src.index(anchor) + 400]
    assert "if previous is None:" in after
    assert "previous = QPointF(start)" in after


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
