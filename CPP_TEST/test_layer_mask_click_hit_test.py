"""Regression test for: "j'arrive pas a utiliser les masques de calque...
j'arrive pas a editer le masque, a le faire fonctionner etc... je peux que
le creer" - adding a layer mask worked (LayersDock.add_mask_requested is a
simple button click, always wired correctly), but getting INTO mask-edit
mode by clicking the mask thumbnail in the layers panel was unreliable.

Root cause: LayerListWidget.mouseReleaseEvent (UI/docks/layers_dock.py) hit-
tests clicks against a `mask_left` it computed independently from where
LayerItemDelegate.paint() (UI/widgets/layer_delegate.py) actually PAINTS the
mask thumbnail:

  delegate (what's drawn):
    rect        = option.rect.adjusted(2, 1, -2, -1)
    offset      = depth*16 (+ CLIP_INDENT if the row is a clipped layer)
    thumb_rect  = QRect(rect.left() + 28 + offset, ..., 36, 36)
    mask_rect   = QRect(thumb_rect.right() + 10, ..., 36, 36)
              == QRect(rect.left() + 73 + offset, ..., 36, 36)
              == QRect(row_rect.left() + 75 + offset, ..., 36, 36)   [+2 inset]

  dock (what used to be clickable):
    mask_left = row_rect.left() + 68 + depth*16          # no +2 inset,
                                                           # no clip term at all

For an ordinary (unclipped) layer this was only off by ~7px - mostly
harmless overlap. For a CLIPPED layer with a mask, the real box sat a
further CLIP_INDENT (16px) to the right of where clicks were being tested:
well under half of the visible 36px-wide mask thumbnail actually responded
to a click, and clicking anywhere near its centre or right side just
re-selected the layer row instead of entering mask-edit mode - which is
exactly what "je n'arrive pas a l'editer" looks like day to day.

The fix: the dock's hit zone now mirrors the delegate's real geometry
exactly, including the clipping term, instead of an independently-guessed
offset that could silently drift out of sync with what's actually painted.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCK_PATH = ROOT / "UI" / "docks" / "layers_dock.py"
DELEGATE_PATH = ROOT / "UI" / "widgets" / "layer_delegate.py"

CLIP_INDENT = 16  # UI/widgets/layer_delegate.py's own constant


def painted_mask_box_left(depth: int, clipping: bool) -> int:
    """Transcription of LayerItemDelegate.paint()'s mask_rect geometry,
    expressed relative to row_rect.left() (i.e. option.rect.left() /
    visualRect(index).left(), the same origin the dock's click handler
    uses)."""
    offset = depth * 16 + (CLIP_INDENT if clipping else 0)
    inset = 2  # rect = option.rect.adjusted(2, 1, -2, -1)
    thumb_left = inset + 28 + offset
    thumb_right = thumb_left + 36 - 1  # QRect.right() == left() + width() - 1
    mask_left = thumb_right + 10
    return mask_left


def click_zone(depth: int, clipping: bool) -> tuple[int, int]:
    """Transcription of the (fixed) LayerListWidget.mouseReleaseEvent hit
    zone, same coordinate origin as painted_mask_box_left()."""
    offset = depth * 16 + (CLIP_INDENT if clipping else 0)
    mask_left = 75 + offset
    return mask_left, mask_left + 38


def test_click_zone_fully_covers_the_painted_box_unclipped():
    for depth in (0, 1, 2, 3):
        box_left = painted_mask_box_left(depth, clipping=False)
        box_right = box_left + 36
        zone_left, zone_right = click_zone(depth, clipping=False)
        assert zone_left <= box_left and zone_right >= box_right, (
            f"depth={depth}: painted box [{box_left},{box_right}) not fully "
            f"covered by click zone [{zone_left},{zone_right})"
        )


def test_click_zone_fully_covers_the_painted_box_clipped():
    """The case that was badly broken before the fix: clipped layers add
    CLIP_INDENT to the painted position, which the old click zone never
    accounted for at all."""
    for depth in (0, 1, 2, 3):
        box_left = painted_mask_box_left(depth, clipping=True)
        box_right = box_left + 36
        zone_left, zone_right = click_zone(depth, clipping=True)
        assert zone_left <= box_left and zone_right >= box_right, (
            f"depth={depth} clipped: painted box [{box_left},{box_right}) "
            f"not fully covered by click zone [{zone_left},{zone_right})"
        )


def test_click_zone_does_not_bleed_into_the_next_row_element():
    """A sanity bound: the fix shouldn't overshoot so far that the mask hit
    zone starts eating into space meant for other controls (the old zone
    started 7px early; the fix should land right at the box, not drift the
    other direction by a large margin)."""
    box_left = painted_mask_box_left(0, clipping=False)
    zone_left, _ = click_zone(0, clipping=False)
    assert 0 <= zone_left - 0 < box_left + 5, "click zone start drifted unexpectedly far"
    assert zone_left <= box_left


def test_source_dock_hit_test_accounts_for_clip_indent():
    src = DOCK_PATH.read_text()
    assert "CLIP_INDENT" in src, "expected the dock to import/use the delegate's own CLIP_INDENT constant"
    assert "from UI.widgets.layer_delegate import LayerItemDelegate, CLIP_INDENT" in src
    assert 'offset = depth * 16 + (CLIP_INDENT if flags.get("clipping") else 0)' in src
    assert "mask_left = row_rect.left() + 75 + offset" in src, (
        "expected the hit zone to mirror the delegate's real geometry "
        "(row_rect.left() + 75 + offset), not an independently-guessed offset"
    )


def test_source_delegate_geometry_unchanged_reference():
    """Guards the assumption this test (and the fix) is built on: if the
    delegate's own paint geometry ever changes, this test - and the dock's
    click zone - need to change with it."""
    src = DELEGATE_PATH.read_text()
    assert "thumb_rect = QRect(rect.left() + 28 + offset, rect.top() + 5, 36, 36)" in src
    assert "mask_rect = QRect(thumb_rect.right() + 10, rect.top() + 5, 36, 36)" in src
    assert "CLIP_INDENT = 16" in src


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
