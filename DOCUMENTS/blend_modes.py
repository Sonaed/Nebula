from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from collections import OrderedDict
from types import SimpleNamespace
from CORE.native_bridge import (composite_layers_advanced, composite_layers_native,
                                apply_alpha_mask_native, clone_image_native,
                                draw_text_native,
                                fill_image_native,
                                plan_layer_composite_runs)


BLEND_MODES = (
    "normal", "darken", "multiply", "color_burn", "lighten", "screen",
    "color_dodge", "overlay", "soft_light", "hard_light", "difference",
    "exclusion", "hue", "saturation", "color", "luminosity",
)

def composition_mode(name: str):
    """Compatibility export for callers that still import the old symbol."""
    from UI.qt_blend_modes import composition_mode as _composition_mode
    return _composition_mode(name)


def has_non_normal(document) -> bool:
    return any(
        layer.visible and (
            str(getattr(layer, "blend_mode", "normal")).lower() != "normal"
            or bool(getattr(layer, "clipping", False))
            or bool(getattr(layer, "blend_parameters", {}))
        )
        for layer in document.layers
    )


_COMPOSITE_CACHE: OrderedDict[tuple, QImage] = OrderedDict()
# Full-frame composites are retained only for explicit export/compatibility
# calls. Canvas display uses the per-tile projection cache instead.
_COMPOSITE_CACHE_LIMIT = 1
_COMPOSITE_CACHE_MEMORY_LIMIT = 64 * 1024 * 1024


def set_composition_cache_limit(limit_bytes: int) -> None:
    """Set the compatibility composite cache budget and evict oldest entries."""
    global _COMPOSITE_CACHE_MEMORY_LIMIT
    _COMPOSITE_CACHE_MEMORY_LIMIT = max(1, int(limit_bytes))
    while _COMPOSITE_CACHE and composition_cache_size_bytes() > _COMPOSITE_CACHE_MEMORY_LIMIT:
        _COMPOSITE_CACHE.popitem(last=False)


def composition_cache_size_bytes() -> int:
    return sum(int(image.sizeInBytes()) for image in _COMPOSITE_CACHE.values())


def clear_composition_cache() -> int:
    """Drop cached full-canvas composites and return the estimated bytes freed."""
    global _COMPOSITE_CACHE
    freed = composition_cache_size_bytes()
    _COMPOSITE_CACHE.clear()
    return freed


def composite_layers(width: int, height: int, layers) -> QImage:
    layers = list(layers)
    if any(bool(getattr(layer, "clipping", False))
           or bool(getattr(layer, "blend_parameters", {}))
           or str(getattr(layer, "blend_mode", "normal")).lower() in {"hue", "saturation", "color", "luminosity"}
           for layer in layers):
        native = composite_layers_advanced(width, height, layers)
        if native is None:
            raise RuntimeError("CreativeCore is required for advanced layer compositing")
        return native
    image = composite_layers_native(width, height, layers)
    if image is None:
        raise RuntimeError("CreativeCore is required for standard layer compositing")
    return image


def _document_layer_entry(layer, rect: QRect | None):
    if rect is None:
        mask_store = getattr(layer, "alpha_mask_store", None)
        if mask_store is None:
            return layer
        image = clone_image_native(layer.image)
        mask = mask_store.materialize()
        if image is None or mask.isNull() or not apply_alpha_mask_native(image, mask):
            raise RuntimeError("CreativeCore refused to apply the layer alpha mask")
        return SimpleNamespace(
            image=image, visible=layer.visible, opacity=layer.opacity,
            blend_mode=layer.blend_mode, blend_parameters=layer.blend_parameters,
            clipping=bool(getattr(layer, "clipping", False)),
        )
    store = layer.tile_store
    tx, ty = rect.x() // store.tile_size, rect.y() // store.tile_size
    if store.has_tile(tx, ty):
        tile = store.tile(tx, ty)
    else:
        tile = QImage(rect.size(), store.image_format)
        if not fill_image_native(tile, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear projection tiles")
    mask_store = getattr(layer, "alpha_mask_store", None)
    if mask_store is not None:
        if mask_store.has_tile(tx, ty):
            mask = mask_store.tile(tx, ty)
            if mask.size() != tile.size() or not apply_alpha_mask_native(tile, mask):
                raise RuntimeError("CreativeCore refused to apply the layer alpha mask")
        # An absent mask tile represents full coverage, just like an absent
        # sparse color tile represents transparent pixels.
    return SimpleNamespace(
        image=tile, visible=layer.visible, opacity=layer.opacity,
        blend_mode=layer.blend_mode, blend_parameters=layer.blend_parameters,
        clipping=bool(getattr(layer, "clipping", False)),
    )


def composite_document_layers(document, rect: QRect | None = None) -> QImage:
    """Composite document layers/groups, optionally limited to one tile rect."""
    width, height = ((document.width, document.height) if rect is None
                     else (rect.width(), rect.height()))
    groups = {group.id: group for group in document.layer_groups}
    children = {group_id: [] for group_id in groups}
    roots = []
    for group in document.layer_groups:
        if group.parent_id is None:
            roots.append(group)
        elif group.parent_id in groups and group.parent_id != group.id:
            children[group.parent_id].append(group)
        else:
            raise ValueError("Layer group parent is invalid")
    positions = {layer.id: index for index, layer in enumerate(document.layers)}

    def ordered_members(group):
        member_positions = [positions[layer_id] for layer_id in group.layer_ids
                            if layer_id in positions]
        if not member_positions or member_positions != list(range(min(member_positions), max(member_positions) + 1)):
            raise ValueError("Layer groups must be contiguous and unambiguous")
        return member_positions

    def group_entry(group):
        member_positions = ordered_members(group)
        child_groups = sorted(children[group.id], key=lambda item: min(ordered_members(item)))
        child_starts = {}
        covered = set()
        for child in child_groups:
            child_positions = ordered_members(child)
            if not set(child_positions).issubset(member_positions) or covered.intersection(child_positions):
                raise ValueError("Nested layer groups must be disjoint children")
            covered.update(child_positions)
            child_starts[min(child_positions)] = child
        entries = []
        position = min(member_positions)
        end = max(member_positions) + 1
        while position < end:
            child = child_starts.get(position)
            if child is not None:
                entries.append(group_entry(child))
                position = max(ordered_members(child)) + 1
            elif position not in covered:
                entries.append(_document_layer_entry(document.layers[position], rect))
                position += 1
            else:
                position += 1
        group_image = composite_layers(width, height, entries)
        return SimpleNamespace(
            image=group_image, visible=bool(group.visible), opacity=float(group.opacity),
            blend_mode=str(group.blend_mode),
            blend_parameters=dict(getattr(group, "blend_parameters", {}) or {}),
            clipping=False,
        )

    root_by_start = {}
    covered_by_root = set()
    for group in roots:
        member_positions = ordered_members(group)
        if covered_by_root.intersection(member_positions):
            raise ValueError("Layer belongs to multiple root groups")
        covered_by_root.update(member_positions)
        root_by_start[min(member_positions)] = group
    entries = []
    index = 0
    while index < len(document.layers):
        group = root_by_start.get(index)
        if group is not None:
            entries.append(group_entry(group))
            index = max(ordered_members(group)) + 1
        elif index not in covered_by_root:
            entries.append(_document_layer_entry(document.layers[index], rect))
            index += 1
        else:
            index += 1
    return composite_layers(width, height, entries)


def composite_document(document) -> QImage:
    layer_key = tuple(
        (
            layer.id,
            int(layer.image.cacheKey()),
            bool(layer.visible),
            float(layer.opacity),
            str(getattr(layer, "blend_mode", "normal")),
            bool(getattr(layer, "clipping", False)),
            tuple(sorted((key, int(value)) for key, value in (
                ("mask", getattr(getattr(layer, "alpha_mask_store", None), "_native_handle", None)
                 and sum(layer.alpha_mask_store.tile_revision(*tile)
                         for tile in layer.alpha_mask_store.occupied_keys)
                 or 0),))),
            tuple(sorted((str(key), repr(value)) for key, value in getattr(layer, "blend_parameters", {}).items())),
        )
        for layer in document.layers
    )
    text_key = tuple(
        (item.id, item.text, item.position.x(), item.position.y(), item.color.rgba(), item.font.toString())
        for item in document.text_objects
    )
    group_key = tuple(
        (group.id, tuple(group.layer_ids), bool(group.visible), float(group.opacity),
         str(group.blend_mode),
         tuple(sorted((str(key), repr(value))
                      for key, value in getattr(group, "blend_parameters", {}).items())))
        for group in document.layer_groups
    )
    cache_key = (id(document), document.width, document.height, layer_key, group_key, text_key)
    cached = _COMPOSITE_CACHE.get(cache_key)
    if cached is not None:
        _COMPOSITE_CACHE.move_to_end(cache_key)
        # QImage copies share storage until modified; a deep copy here used
        # to copy a full canvas on every repaint of non-normal blend layers.
        return QImage(cached)

    image = composite_document_layers(document)
    for item in document.text_objects:
        if not draw_text_native(image, item.text, item.font,
                                item.position.x(), item.position.y(), item.color):
            raise RuntimeError("CreativeCore is required to render document text")
    image_bytes = int(image.sizeInBytes())
    if image_bytes <= _COMPOSITE_CACHE_MEMORY_LIMIT:
        _COMPOSITE_CACHE[cache_key] = QImage(image)
        _COMPOSITE_CACHE.move_to_end(cache_key)
        while (len(_COMPOSITE_CACHE) > _COMPOSITE_CACHE_LIMIT
               or composition_cache_size_bytes() > _COMPOSITE_CACHE_MEMORY_LIMIT):
            _COMPOSITE_CACHE.popitem(last=False)
    return image


__all__ = ["BLEND_MODES", "composition_mode", "composite_document",
           "composite_document_layers", "composite_layers", "has_non_normal"]
