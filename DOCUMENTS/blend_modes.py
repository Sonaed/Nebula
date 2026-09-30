from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from collections import OrderedDict
from types import SimpleNamespace
from CORE.native_filters import load_filters
from CORE.native_bridge import (composite_layers_advanced, composite_layers_native,
                                apply_alpha_mask_native, clone_image_native,
                                draw_text_native,
                                fill_image_native,
                                plan_layer_composite_runs)
from DOCUMENTS.adjustments import (AdjustmentLayerSpec, CurvesAdjustment,
                                   LevelsAdjustment, HueSaturationAdjustment,
                                   ExposureAdjustment, VibranceAdjustment,
                                   ColorBalanceAdjustment, ParametricCurvesAdjustment,
                                   SelectiveColorAdjustment, LuminosityMaskAdjustment,
                                   apply_adjustment, apply_layer_effects, spec_from_dict)


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
            or str(getattr(layer, "layer_kind", "raster")) != "raster"
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
        if getattr(layer, "mask_disabled", False):
            mask_store = None
        if mask_store is None:
            effects = getattr(layer, "layer_effects", None) or getattr(layer, "psd_effects", None)
            if not effects and not getattr(layer, "transform_state", None):
                return layer
            return SimpleNamespace(
                image=apply_layer_effects(layer.render_image(), effects), visible=layer.visible,
                opacity=layer.opacity, blend_mode=layer.blend_mode,
                blend_parameters=layer.blend_parameters,
                clipping=bool(getattr(layer, "clipping", False)),
            )
        image = clone_image_native(layer.render_image())
        mask = layer.alpha_mask_coverage()
        if image is None or mask is None or mask.isNull() or not apply_alpha_mask_native(image, mask):
            raise RuntimeError("CreativeCore refused to apply the layer alpha mask")
        image = apply_layer_effects(image, getattr(layer, "layer_effects", None) or getattr(layer, "psd_effects", None))
        return SimpleNamespace(
            image=image, visible=layer.visible, opacity=layer.opacity,
            blend_mode=layer.blend_mode, blend_parameters=layer.blend_parameters,
            clipping=bool(getattr(layer, "clipping", False)),
        )
    store = layer.tile_store
    if getattr(layer, "transform_state", None):
        tile = layer.render_image().copy(rect)
        return SimpleNamespace(
            image=tile, visible=layer.visible, opacity=layer.opacity,
            blend_mode=layer.blend_mode, blend_parameters=layer.blend_parameters,
            clipping=bool(getattr(layer, "clipping", False)),
        )
    tx, ty = rect.x() // store.tile_size, rect.y() // store.tile_size
    if store.has_tile(tx, ty):
        tile = store.tile(tx, ty)
    else:
        tile = QImage(rect.size(), store.image_format)
        if not fill_image_native(tile, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear projection tiles")
    mask_store = getattr(layer, "alpha_mask_store", None)
    if mask_store is not None and not getattr(layer, "mask_disabled", False):
        if mask_store.has_tile(tx, ty):
            mask = mask_store.tile(tx, ty)
            if mask.size() != tile.size() or not apply_alpha_mask_native(tile, mask):
                raise RuntimeError("CreativeCore refused to apply the layer alpha mask")
        # An absent mask tile represents full coverage, just like an absent
        # sparse color tile represents transparent pixels.
    tile = apply_layer_effects(tile, getattr(layer, "layer_effects", None) or getattr(layer, "psd_effects", None))
    return SimpleNamespace(
        image=tile, visible=layer.visible, opacity=layer.opacity,
        blend_mode=layer.blend_mode, blend_parameters=layer.blend_parameters,
        clipping=bool(getattr(layer, "clipping", False)),
        empty=not store.has_tile(tx, ty),
    )


def apply_clipped_adjustment(base: QImage, adjusted: QImage, clip_source: QImage) -> QImage:
    """Apply an adjustment only where the nearest unclipped base has alpha."""
    filters = load_filters()
    if filters is None or not filters.supports_adjustments:
        raise RuntimeError("CreativeCore récent requis pour les réglages écrêtés "
                           "(filtres ABI >= 4).")
    result = base.convertToFormat(QImage.Format.Format_RGBA8888)
    adjusted_image = adjusted.convertToFormat(QImage.Format.Format_RGBA8888)
    clip_image = clip_source.convertToFormat(QImage.Format.Format_RGBA8888)
    if adjusted_image.size() != result.size() or clip_image.size() != result.size():
        raise ValueError("Les images d'un réglage écrêté doivent avoir la même taille")
    if hasattr(result, "detach"):
        result.detach()  # convertToFormat partage les données : ne jamais toucher à `base`
    if not result.isNull():
        filters.blend_by_alpha(result.bits(), result.width(), result.height(),
                               adjusted_image.constBits(), clip_image.constBits(),
                               stride=result.bytesPerLine(),
                               changed_stride=adjusted_image.bytesPerLine(),
                               mask_stride=clip_image.bytesPerLine())
    return result


def adjustment_coverage(opacity: float, size, mask=None, clip_image=None):
    """Coverage image (alpha = 0..255) an adjustment layer applies through.

    Combines the layer opacity, its own alpha mask tile and, for a clipped
    adjustment, the alpha of the base it is clipped onto.  Returns None when the
    adjustment covers everything fully, so callers keep the fast path.
    """
    opacity = max(0.0, min(1.0, float(opacity)))
    if opacity >= 0.999 and mask is None and clip_image is None:
        return None
    coverage = QImage(size, QImage.Format.Format_RGBA8888)
    if not fill_image_native(coverage, QColor(0, 0, 0, int(round(opacity * 255)))):
        raise RuntimeError("CreativeCore is required to build an adjustment coverage tile")
    for source in (mask, clip_image):
        if source is None:
            continue
        if source.size() != coverage.size():
            raise ValueError("Les images d'un réglage doivent avoir la même taille")
        if not apply_alpha_mask_native(coverage, source):
            raise RuntimeError("CreativeCore refused to apply the adjustment coverage")
    return coverage


def hide_clipped_over_hidden_base(entries, base_visible: list):
    """Photoshop rule: hiding a base layer or folder hides what is clipped to it.

    `base_visible` is a one-item list tracking the last non-clipped entry of the
    current stack level.  Clipped entries above a hidden base become invisible;
    any other entry becomes the new base.
    """
    result = []
    for entry in entries:
        if bool(getattr(entry, "clipping", False)):
            if not base_visible[0] and getattr(entry, "visible", True):
                entry = _with_visible(entry, False)
        else:
            base_visible[0] = bool(getattr(entry, "visible", True))
        result.append(entry)
    return result


def _with_visible(entry, visible: bool):
    import dataclasses
    if dataclasses.is_dataclass(entry):
        return dataclasses.replace(entry, visible=visible)
    return SimpleNamespace(image=entry.image, visible=visible, opacity=entry.opacity,
                           blend_mode=entry.blend_mode,
                           blend_parameters=entry.blend_parameters,
                           clipping=bool(getattr(entry, "clipping", False)))


# ---------------------------------------------------------------------------
# Photoshop stack semantics (clipping sets and adjustment layers)
# ---------------------------------------------------------------------------

class AdjustmentEntry(SimpleNamespace):
    """A pending adjustment layer inside a list of composite entries.

    It is resolved by :func:`resolve_stack` against whatever lies below it, so
    it can carry its own blend mode, opacity, mask and clipping like
    Photoshop's adjustment layers.
    """

    image = None


def adjustment_entry(layer, mask=None) -> AdjustmentEntry | None:
    spec = spec_from_dict(getattr(layer, "adjustment", None))
    if spec is None:
        return None
    return AdjustmentEntry(spec=spec, visible=bool(getattr(layer, "visible", True)),
                           opacity=float(getattr(layer, "opacity", 1.0)),
                           blend_mode=str(getattr(layer, "blend_mode", "normal")),
                           blend_parameters=dict(getattr(layer, "blend_parameters", {}) or {}),
                           clipping=bool(getattr(layer, "clipping", False)), mask=mask)


def _plain_entry(image, visible=True, opacity=1.0, blend_mode="normal", blend_parameters=None,
                 clipping=False):
    return SimpleNamespace(image=image, visible=visible, opacity=opacity, blend_mode=blend_mode,
                           blend_parameters=dict(blend_parameters or {}), clipping=clipping)


def _psd_filters():
    filters = load_filters()
    if filters is None or not getattr(filters, "supports_psd_adjustments", False):
        return None
    return filters


def _rgba_detached(image: QImage) -> QImage:
    result = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if not result.isNull():
        if hasattr(result, "detach"):
            result.detach()
    return result


def _opaque(image: QImage, filters) -> QImage:
    """RGBA copy whose alpha is forced to 255 (colour kept as is)."""
    result = _rgba_detached(image)
    if result.isNull():
        raise RuntimeError("image de composition invalide")
    filters.set_alpha(result.bits(), result.width(), result.height(), 255,
                      stride=result.bytesPerLine())
    return result


def _with_alpha_of(image: QImage, alpha_source: QImage, filters) -> QImage:
    result = _rgba_detached(image)
    source = alpha_source.convertToFormat(QImage.Format.Format_RGBA8888)
    if result.isNull() or source.isNull() or result.size() != source.size():
        raise RuntimeError("alpha de composition incohérent")
    filters.copy_alpha(result.bits(), result.width(), result.height(), source.constBits(),
                       stride=result.bytesPerLine(), source_stride=source.bytesPerLine())
    return result


def _adjust_opaque(opaque: QImage, entry: AdjustmentEntry, width: int, height: int) -> QImage:
    """Apply one adjustment layer onto an opaque backdrop (alpha stays 255)."""
    adjusted = _rgba_detached(apply_adjustment(opaque, entry.spec))
    if entry.mask is not None:
        if entry.mask.size() != adjusted.size() or not apply_alpha_mask_native(adjusted, entry.mask):
            raise RuntimeError("CreativeCore refused to apply the adjustment mask")
    return composite_layers(width, height, [
        _plain_entry(opaque),
        _plain_entry(adjusted, True, entry.opacity, entry.blend_mode, entry.blend_parameters)])


def _isolate_clipping_set(base, clipped, width: int, height: int, filters):
    """Photoshop clipping set: clipped layers act *atop* the base only.

    The base colour is made opaque, the clipped layers (and clipped
    adjustments) are blended on it, then the base's own alpha, opacity and
    blend mode are applied to the result as one layer.  This keeps soft,
    semi-transparent base edges identical to Photoshop.
    """
    working = _opaque(base.image, filters)
    pending = []

    def flush():
        nonlocal working
        if pending:
            working = composite_layers(width, height, [_plain_entry(working)] + [
                _plain_entry(item.image, True, item.opacity, item.blend_mode,
                             item.blend_parameters) for item in pending])
            pending.clear()

    for item in clipped:
        if isinstance(item, AdjustmentEntry):
            flush()
            working = _adjust_opaque(_rgba_detached(working), item, width, height)
        else:
            pending.append(item)
    flush()
    result = _with_alpha_of(working, base.image, filters)
    return _plain_entry(result, True, float(base.opacity), str(base.blend_mode),
                        getattr(base, "blend_parameters", {}) or {}, False)


def _legacy_adjustment(entries, entry, width, height):
    """Pre-ABI-5 bridge: replace the stack by its adjusted composite."""
    if entries:
        base = composite_layers(width, height, entries)
    else:
        return entries
    try:
        adjusted = apply_adjustment(base, entry.spec)
    except (RuntimeError, ValueError):
        return entries
    clip_image = None
    if entry.clipping:
        clip_source = next((item for item in reversed(entries)
                            if not bool(getattr(item, "clipping", False))), entries[-1])
        clip_image = clip_source.image
    coverage = adjustment_coverage(entry.opacity, base.size(), entry.mask, clip_image)
    if coverage is not None:
        adjusted = apply_clipped_adjustment(base, adjusted, coverage)
    return [_plain_entry(adjusted)]


def resolve_stack(entries, width: int, height: int) -> list:
    """Turn entries (possibly holding AdjustmentEntry items and clipping sets)
    into plain entries any compositor can blend.

    Photoshop rules: a hidden base hides its clipping set; a clipping set is
    evaluated in isolation on its base; an adjustment layer transforms the
    composite below it and is blended back with its own mode, opacity and
    mask without changing the stack's transparency.
    """
    entries = list(entries)
    if not entries:
        return entries
    has_clip = any(bool(getattr(item, "clipping", False)) and getattr(item, "visible", True)
                   and not getattr(item, "empty", False) for item in entries)
    has_adjustment = any(isinstance(item, AdjustmentEntry) for item in entries)
    if not has_clip and not has_adjustment:
        # Empty clipped entries are dropped too: leaving one would push the
        # whole tile through the slower clipping-aware compositor.
        return [item for item in entries if getattr(item, "visible", True)
                and not getattr(item, "empty", False)]
    filters = _psd_filters()
    if filters is None:
        # Old bridge: native clipping as before, adjustments by replacement.
        result = []
        for item in entries:
            if not getattr(item, "visible", True):
                continue
            if isinstance(item, AdjustmentEntry):
                result = _legacy_adjustment(result, item, width, height)
            else:
                result.append(item)
        return result
    result = []
    index = 0
    while index < len(entries):
        base = entries[index]
        end = index + 1
        while end < len(entries) and bool(getattr(entries[end], "clipping", False)):
            end += 1
        clipped = [item for item in entries[index + 1:end] if getattr(item, "visible", True)
                   and not getattr(item, "empty", False)]
        index = end
        if not getattr(base, "visible", True) or getattr(base, "empty", False):
            continue                       # hidden/empty base: its clipping set shows nothing
        if isinstance(base, AdjustmentEntry):
            if not result:
                continue                   # nothing below: nothing to adjust
            below = composite_layers(width, height, result)
            adjusted = _adjust_opaque(_opaque(below, filters), base, width, height)
            flattened = _plain_entry(_with_alpha_of(adjusted, below, filters))
            if clipped:
                flattened = _isolate_clipping_set(flattened, clipped, width, height, filters)
            result = [flattened]
            continue
        if base.image is None or base.image.isNull():
            continue
        if clipped:
            result.append(_isolate_clipping_set(base, clipped, width, height, filters))
        else:
            result.append(base)
    return result


def _adjustment_spec(layer):
    value = getattr(layer, "adjustment", None)
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind", ""))
    curves = value.get("curves", {})
    levels = value.get("levels", {})
    hsl = value.get("hue_saturation", {})
    exposure = value.get("exposure", {})
    vibrance = value.get("vibrance", {})
    balance = value.get("color_balance", {})
    parametric = value.get("parametric_curves", {})
    selective = value.get("selective_color", {})
    luminosity = value.get("luminosity_mask", {})
    return AdjustmentLayerSpec(
        kind=kind,
        curves=CurvesAdjustment(
            tuple(tuple(point) for point in curves.get("points", ((0, 0), (255, 255)))),
            {str(channel): tuple(tuple(point) for point in points)
             for channel, points in dict(curves.get("channels", {})).items()
             if str(channel) in {"red", "green", "blue"} and isinstance(points, (list, tuple))},
        ),
        levels=LevelsAdjustment(**{key: levels[key] for key in
                                   ("black", "white", "gamma", "output_black", "output_white")
                                   if key in levels}),
        hue_saturation=HueSaturationAdjustment(**{key: hsl[key] for key in
                                                  ("hue", "saturation", "lightness") if key in hsl}),
        exposure=ExposureAdjustment(**{key: exposure[key] for key in
                                       ("exposure", "offset", "gamma") if key in exposure}),
        vibrance=VibranceAdjustment(**{key: vibrance[key] for key in
                                       ("vibrance", "saturation") if key in vibrance}),
        color_balance=ColorBalanceAdjustment(**{
            key: tuple(balance[key]) for key in ("shadows", "midtones", "highlights")
            if key in balance and isinstance(balance[key], (list, tuple)) and len(balance[key]) == 3}),
        threshold=int(value.get("threshold", 128)),
        posterize=int(value.get("posterize", 4)),
        parametric_curves=ParametricCurvesAdjustment(**{key: parametric[key] for key in
            ("black", "shadows", "midtones", "highlights", "white") if key in parametric}),
        selective_color=SelectiveColorAdjustment(channels={str(key): tuple(values) for key, values in
            dict(selective.get("channels", {})).items() if isinstance(values, (list, tuple)) and len(values) == 4}),
        luminosity_mask=LuminosityMaskAdjustment(**{key: luminosity[key] for key in
            ("mode", "amount", "feather", "invert") if key in luminosity}),
    )


def composite_document_layers(document, rect: QRect | None = None) -> QImage:
    """Composite document layers/groups, optionally limited to one tile rect."""
    width, height = ((document.width, document.height) if rect is None
                     else (rect.width(), rect.height()))
    groups = {group.id: group for group in document.layer_groups}

    def adjustment_for(layer):
        mask = None
        mask_store = getattr(layer, "alpha_mask_store", None)
        if mask_store is not None and not getattr(layer, "mask_disabled", False):
            if rect is None:
                materialized = layer.alpha_mask_coverage()
                mask = None if materialized is None or materialized.isNull() else materialized
            else:
                tx, ty = rect.x() // mask_store.tile_size, rect.y() // mask_store.tile_size
                mask = mask_store.tile(tx, ty) if mask_store.has_tile(tx, ty) else None
        return adjustment_entry(layer, mask)

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
        base_visible = [True]
        position = min(member_positions)
        end = max(member_positions) + 1
        while position < end:
            child = child_starts.get(position)
            if child is not None:
                child_entry = group_entry(child)
                entries.extend(hide_clipped_over_hidden_base([child_entry], base_visible))
                position = max(ordered_members(child)) + 1
            elif position not in covered:
                layer = document.layers[position]
                if getattr(layer, "layer_kind", "raster") == "adjustment":
                    entry = adjustment_for(layer)
                    if entry is not None:
                        entries.extend(hide_clipped_over_hidden_base([entry], base_visible))
                else:
                    entries.extend(hide_clipped_over_hidden_base(
                        [_document_layer_entry(layer, rect)], base_visible))
                position += 1
            else:
                position += 1
        group_image = composite_layers(width, height, resolve_stack(entries, width, height))
        mask_store = getattr(group, "alpha_mask_store", None)
        if mask_store is not None and not getattr(group, "mask_disabled", False):
            if rect is None:
                mask = QImage(width, height, QImage.Format.Format_ARGB32)
                mask.fill(QColor(255, 255, 255, 255))
                painter = QPainter(mask)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                for tx, ty in mask_store.occupied_keys:
                    painter.drawImage(mask_store.tile_rect(tx, ty).topLeft(), mask_store.tile(tx, ty))
                painter.end()
            else:
                tx, ty = rect.x() // mask_store.tile_size, rect.y() // mask_store.tile_size
                mask = mask_store.tile(tx, ty) if mask_store.has_tile(tx, ty) else None
            if mask is not None and not mask.isNull():
                if not apply_alpha_mask_native(group_image, mask):
                    raise RuntimeError("CreativeCore refused to apply the group alpha mask")
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
    base_visible = [True]
    index = 0
    while index < len(document.layers):
        group = root_by_start.get(index)
        if group is not None:
            entries.extend(hide_clipped_over_hidden_base([group_entry(group)], base_visible))
            index = max(ordered_members(group)) + 1
        elif index not in covered_by_root:
            layer = document.layers[index]
            if getattr(layer, "layer_kind", "raster") == "adjustment":
                entry = adjustment_for(layer)
                if entry is not None:
                    entries.extend(hide_clipped_over_hidden_base([entry], base_visible))
            else:
                entries.extend(hide_clipped_over_hidden_base(
                    [_document_layer_entry(layer, rect)], base_visible))
            index += 1
        else:
            index += 1
    resolved = resolve_stack(entries, width, height)
    if not resolved:
        blank = QImage(width, height, QImage.Format.Format_ARGB32)
        if not fill_image_native(blank, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore is required to clear the composite")
        return blank
    return composite_layers(width, height, resolved)


def composite_document(document) -> QImage:
    def store_signature(store):
        if store is None:
            return (0, 0, 0)
        keys = store.occupied_keys
        return (len(keys), sum(store.tile_revision(*tile) for tile in keys),
                int(store.allocated_bytes()))

    layer_key = tuple(
        (
            layer.id,
            store_signature(getattr(layer, "tile_store", None)),
            int(getattr(getattr(layer, "_image_cache", None), "cacheKey", lambda: 0)()),
            bool(getattr(layer, "_cache_dirty", False)),
            bool(layer.visible),
            float(layer.opacity),
            str(getattr(layer, "blend_mode", "normal")),
            bool(getattr(layer, "clipping", False)),
            store_signature(getattr(layer, "alpha_mask_store", None)),
            str(getattr(layer, "layer_kind", "raster")),
            repr(getattr(layer, "adjustment", None)),
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
    cache_key = (str(getattr(document, "id", "__anonymous_document__")),
                 document.width, document.height, layer_key, group_key, text_key)
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


__all__ = ["resolve_stack", "AdjustmentEntry", "adjustment_entry",
           "BLEND_MODES", "composition_mode", "composite_document",
           "composite_document_layers", "composite_layers", "has_non_normal",
           "apply_clipped_adjustment"]
