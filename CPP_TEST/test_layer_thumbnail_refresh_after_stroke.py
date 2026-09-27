"""Regression test for: "J'arrive toujours pas a utiliser le masque comme un
masque" / "peindre ne change rien sur la miniature du masque" - reported
even after the mask paint-target bug (#7) and mask-edit performance bug (#8)
were both fixed and rebuilt.

Root cause, found by tracing the layers panel's thumbnail pipeline rather
than the brush/mask code again (both of which had already checked out clean
twice): UI/docks/layers_dock.py's LayerListWidget.refresh_layers() rebuilds
every row from scratch each time it runs, and each row's thumbnail comes
from `_get_thumb`/`_get_mask_thumb`, which cache the rendered QPixmap keyed
off a "thumb key" and only re-render on a cache MISS. There is a dedicated
method for forcing that miss, `invalidate_thumb_cache(layer_id)`, whose own
docstring says: "Appele par le canvas apres un coup de pinceau sur le
calque actif. Sans ca, les miniatures restent figees meme quand on peint."
(Called by the canvas after a brush stroke on the active layer. Without
this, thumbnails stay frozen even when painting.)

`grep -rn "invalidate_thumb_cache"` across the whole codebase turned up
exactly ONE hit: its own definition. Nothing ever called it. And nothing
in the paint-stroke-completion code path (Canvas.canvas_brush_end_stroke,
called at TabletRelease/mouseReleaseEvent, plus a couple of other stroke
end sites) ever called Application.refresh_layers() either. So no layer's
thumbnail - the mask thumbnail included - EVER updated after painting, no
matter how correct the underlying pixel/mask data was: the layers panel
only ever rebuilds (and only then re-renders a thumbnail, and only for a
layer whose cache was separately invalidated) in response to layer
STRUCTURE changes (add/delete/duplicate/reorder/select/...), never in
response to a paint stroke. This is exactly why the user could paint on a
mask correctly (after #7/#8) and its thumbnail would still never visibly
change: the mechanism meant to catch that was wired up as a docstring, not
as a connection.

The fix: Canvas gained a new Signal, `layer_thumbnail_dirty(str)`, emitted
with the active layer's id at the end of `canvas_brush_end_stroke()` (the
one stroke-completion method every mouse/tablet path already funnels
through). Application.connect_ui() connects it to a new
`_on_layer_thumbnail_dirty(layer_id)` handler that calls
`self.ui.layers_dock.invalidate_thumb_cache(layer_id)` (clears both that
layer's normal AND mask cache entries - see its own implementation) and
then `self.refresh_layers()` (already debounced via QTimer.singleShot(0,
...), so this costs nothing extra even on rapid strokes).
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CANVAS_PATH = ROOT / "CANVAS" / "canvas.py"
APP_PATH = ROOT / "CORE" / "application.py"


def _extract_canvas_brush_end_stroke() -> str:
    src = CANVAS_PATH.read_text()
    start = src.index("    def canvas_brush_end_stroke(")
    end = src.index("    def _restore_alpha_from(", start)
    return src[start:end]


def _extract_connect_ui_snippet() -> str:
    src = APP_PATH.read_text()
    start = src.index("    def connect_ui(")
    end = src.index(
        "# -----------------------------------------------------\n        # HOME PAGE",
        start,
    )
    return src[start:end]


def _extract_on_layer_thumbnail_dirty() -> str:
    src = APP_PATH.read_text()
    start = src.index("    def _on_layer_thumbnail_dirty(")
    end = src.index("    def refresh_layers(", start)
    return src[start:end]


def _as_callable(method_body: str, signature: str, func_name: str, params: str = "self"):
    """Turns an extracted `def name(self, ...) -> ReturnType:` method body
    into a standalone callable, keeping the body's own indentation (it
    doesn't need to match a fresh 4-space convention, only be internally
    consistent, which it already is as extracted)."""
    sig_end = method_body.index(signature) + len(signature)
    rest = method_body[sig_end:]
    src = f"def {func_name}({params}):\n" + rest
    namespace: dict = {}
    exec(compile(src, f"<{func_name}>", "exec"), namespace)  # noqa: S102 - real source under test
    return namespace[func_name]


def test_source_stroke_end_emits_thumbnail_dirty_with_active_layer_id():
    body = _extract_canvas_brush_end_stroke()
    assert "active_layer = self.get_active_layer()" in body
    assert "self.layer_thumbnail_dirty.emit(active_layer.id)" in body
    emit_index = body.index("self.layer_thumbnail_dirty.emit(active_layer.id)")
    guard_index = body.index("if active_layer is not None:")
    assert guard_index < emit_index


def test_source_signal_declared_on_canvas():
    src = CANVAS_PATH.read_text()
    assert "layer_thumbnail_dirty = Signal(str)" in src


def test_source_application_connects_the_signal():
    body = _extract_connect_ui_snippet()
    assert "self.canvas.layer_thumbnail_dirty.connect(" in body
    assert "self._on_layer_thumbnail_dirty" in body


def test_source_handler_invalidates_cache_then_refreshes():
    body = _extract_on_layer_thumbnail_dirty()
    invalidate_index = body.index("self.ui.layers_dock.invalidate_thumb_cache(layer_id)")
    refresh_index = body.index("self.refresh_layers()")
    assert invalidate_index < refresh_index, (
        "the cache must be invalidated BEFORE refresh_layers() rebuilds the "
        "panel, otherwise the rebuild re-reads the still-stale cached pixmap"
    )


def test_behavior_end_stroke_emits_for_the_active_layer():
    """Executes the real extracted canvas_brush_end_stroke() body against a
    controlled fake `self`, confirming the emit actually fires with the
    active layer's id - not just that the right substrings exist somewhere
    in the file."""
    body = _extract_canvas_brush_end_stroke()
    fn = _as_callable(body, "def canvas_brush_end_stroke(\n        self\n    ) -> None:", "canvas_brush_end_stroke")

    emitted = []
    fake_self = SimpleNamespace(
        tools=SimpleNamespace(brush=SimpleNamespace()),
        _alpha_lock_snapshot=None,
        clone_source=object(),
        clone_offset=object(),
        get_active_layer=lambda: SimpleNamespace(id="layer-active-1"),
        layer_thumbnail_dirty=SimpleNamespace(emit=lambda layer_id: emitted.append(layer_id)),
        _brush_segment_ms=[],
        performance_warning=SimpleNamespace(emit=lambda msg: None),
    )
    fn(fake_self)
    assert emitted == ["layer-active-1"]
    # Confirms the rest of the method still ran normally around the new code.
    assert fake_self._alpha_lock_snapshot is None
    assert fake_self.clone_source is None
    assert fake_self.clone_offset is None


def test_behavior_end_stroke_does_not_emit_with_no_active_layer():
    body = _extract_canvas_brush_end_stroke()
    fn = _as_callable(body, "def canvas_brush_end_stroke(\n        self\n    ) -> None:", "canvas_brush_end_stroke")

    emitted = []
    fake_self = SimpleNamespace(
        tools=SimpleNamespace(brush=SimpleNamespace()),
        _alpha_lock_snapshot=None,
        clone_source=None,
        clone_offset=None,
        get_active_layer=lambda: None,
        layer_thumbnail_dirty=SimpleNamespace(emit=lambda layer_id: emitted.append(layer_id)),
        _brush_segment_ms=[],
        performance_warning=SimpleNamespace(emit=lambda msg: None),
    )
    fn(fake_self)
    assert emitted == []


def test_behavior_handler_invalidates_then_refreshes_in_order():
    """Executes the real extracted _on_layer_thumbnail_dirty() body,
    confirming the two calls happen, in order, with the right layer id."""
    body = _extract_on_layer_thumbnail_dirty()
    fn = _as_callable(body, "def _on_layer_thumbnail_dirty(self, layer_id: str) -> None:",
                       "_on_layer_thumbnail_dirty", params="self, layer_id")

    calls = []
    fake_self = SimpleNamespace(
        ui=SimpleNamespace(layers_dock=SimpleNamespace(
            invalidate_thumb_cache=lambda layer_id: calls.append(("invalidate", layer_id)))),
        refresh_layers=lambda: calls.append(("refresh", None)),
    )
    fn(fake_self, "layer-active-1")
    assert calls == [("invalidate", "layer-active-1"), ("refresh", None)]


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
