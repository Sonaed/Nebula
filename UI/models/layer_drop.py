"""Plan a drag-and-drop in the layer list (pure logic, no Qt).

A row is a tuple:
  ("layer", layer_index, owner_group_id_or_None)
  ("group", group_id, parent_group_id_or_None)
Rows are listed top of the stack first, exactly as the list widget shows them.
"""
from __future__ import annotations


def filter_rows(rows, text: str):
    """Return the set of row positions that stay visible for a search string.

    A layer matches on its name; a group matches on its name and, when it does,
    keeps all of its children visible.  A group whose child matches stays visible
    so the match keeps its context.  ``rows`` are (kind, key, owner, name).
    """
    needle = (text or "").strip().lower()
    if not needle:
        return set(range(len(rows)))
    visible = set()
    group_position = {}
    for position, row in enumerate(rows):
        if row[0] == "group":
            group_position[row[1]] = position
    parent_of = {row[1]: row[2] for row in rows if row[0] == "group"}
    matching_groups = {row[1] for row in rows
                       if row[0] == "group" and needle in str(row[3]).lower()}

    def ancestors(group_id):
        seen = set()
        while group_id is not None and group_id not in seen:
            seen.add(group_id)
            yield group_id
            group_id = parent_of.get(group_id)

    for position, row in enumerate(rows):
        if row[0] == "layer":
            owner_chain = list(ancestors(row[2]))
            inside_match = any(group in matching_groups for group in owner_chain)
            if needle in str(row[3]).lower() or inside_match:
                visible.add(position)
                for group in owner_chain:
                    visible.add(group_position[group])
        elif row[1] in matching_groups:
            visible.add(position)
            for group in ancestors(row[2]):
                visible.add(group_position[group])
    return visible


def plan_layer_drop(before, after, moved):
    """Turn a list-widget drop into ``(order, group_changes)`` or ``None``.

    ``order`` is the bottom-to-top permutation of layer indices;
    ``group_changes`` maps a moved layer index to its new group id (``None`` =
    outside every group).  ``None`` is returned when the drop did anything
    other than moving layer rows (for instance moving a folder row).
    """
    moved = set(moved)

    def rest(rows):
        return [row for row in rows if not (row[0] == "layer" and row[1] in moved)]

    if rest(before) != rest(after):
        return None
    changes = {}
    for position, row in enumerate(after):
        if row[0] != "layer" or row[1] not in moved:
            continue
        cursor = position + 1
        while cursor < len(after) and after[cursor][0] == "layer" and after[cursor][1] in moved:
            cursor += 1
        below = after[cursor] if cursor < len(after) else None
        # The row right below decides: a layer joins the group of the row it now
        # sits on top of; on top of a folder header it takes the folder's own level.
        target = None if below is None else below[2]
        previous = next((item[2] for item in before if item[0] == "layer" and item[1] == row[1]), None)
        if target != previous:
            changes[row[1]] = target
    order = [row[1] for row in reversed(after) if row[0] == "layer"]
    return order, changes
