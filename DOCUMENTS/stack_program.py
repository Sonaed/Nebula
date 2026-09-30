"""Describe a document (or one tile of it) as a flat native stack program.

The program is evaluated by CreativeCore's ``cs_compose_stack`` in a single
call: folders, Photoshop clipping sets, adjustment layers and masks included.
This replaces the per-tile Python composition (dozens of native round trips
per tile) that made large layered documents crawl.

The builder never touches pixels: callers provide two callbacks returning the
QImage for a layer (or its mask) on the area being composed, and whether it is
still loading.  Anything the native evaluator does not cover (layer effects,
hue/saturation-style adjustments) makes :func:`build_stack_program` return
``None`` so the caller keeps its existing path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from DOCUMENTS.adjustments import stack_table

RASTER, GROUP_BEGIN, GROUP_END, ADJUST = 0, 1, 2, 3

_MODE_IDS = {"normal": 0, "darken": 1, "multiply": 2, "color_burn": 3, "lighten": 4,
             "screen": 5, "color_dodge": 6, "overlay": 7, "soft_light": 8, "hard_light": 9,
             "difference": 10, "exclusion": 11, "hue": 12, "saturation": 13, "color": 14,
             "luminosity": 15}
_PARAMETER_KEYS = ("opacity", "opposite_mix", "intensity", "gamma", "mix_normal",
                   "pivot", "clamp", "softness", "hue_shift", "saturation_boost", "offset")
_PARAMETER_DEFAULTS = (1.0, 0.0, 1.0, 1.0, 0.0, 0.5, 1.0, 0.5, 0.0, 1.0, 0.0)


@dataclass
class StackOp:
    kind: int
    image: object = None          # QImage (RASTER), None = transparent here
    mask: object = None           # QImage whose alpha is the coverage
    opacity: float = 1.0
    mode: int = 0
    visible: bool = True
    clipping: bool = False
    parameters: tuple = _PARAMETER_DEFAULTS
    adjust_kind: int = 0
    table: object = None
    table_size: int = 0
    layer: object = None          # source layer (templates only)


@dataclass
class StackProgram:
    ops: list = field(default_factory=list)
    pending: bool = False


# A layer without custom blend parameters uses the plain (Qt / W3C) blend
# formulas.  Every advanced default already matches them except soft light,
# whose "softness" must be 1.0 to give the standard curve.
_PLAIN = _PARAMETER_DEFAULTS[:7] + (1.0,) + _PARAMETER_DEFAULTS[8:]


def _parameters(raw) -> tuple | None:
    if not raw:
        return _PLAIN
    values = []
    for key, default in zip(_PARAMETER_KEYS, _PARAMETER_DEFAULTS):
        try:
            value = float((raw or {}).get(key, default))
        except (TypeError, ValueError, AttributeError):
            value = default
        values.append(value if value == value and abs(value) < 1e30 else default)
    return tuple(values)


def _mode(name) -> int | None:
    return _MODE_IDS.get(str(name or "normal").lower())


def build_stack_program(document, layer_image, layer_mask, hierarchy=None) -> StackProgram | None:
    """Flatten ``document`` into stack ops, bottom to top.

    ``layer_image(layer) -> (QImage | None, pending)`` and
    ``layer_mask(layer) -> (QImage | None, pending)`` supply the pixels of the
    composed area.  ``hierarchy`` may be ``(group_by_id, children, roots,
    positions)`` precomputed by the caller.
    """
    if hierarchy is None:
        groups = {group.id: group for group in document.layer_groups}
        children = {group_id: [] for group_id in groups}
        roots = []
        for group in document.layer_groups:
            if group.parent_id is None:
                roots.append(group)
            elif group.parent_id in children and group.parent_id != group.id:
                children[group.parent_id].append(group)
            else:
                return None
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
    else:
        groups, children, roots, positions = hierarchy
    program = StackProgram()
    ops = program.ops

    def members(group):
        result = [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]
        if not result or result != list(range(min(result), max(result) + 1)):
            raise ValueError("groupe non contigu")
        return result

    def hidden_base():
        ops.append(StackOp(RASTER, visible=False))

    def emit_layer(layer) -> bool:
        if getattr(layer, "layer_effects", None) or getattr(layer, "psd_effects", None):
            return False
        mode = _mode(getattr(layer, "blend_mode", "normal"))
        parameters = _parameters(getattr(layer, "blend_parameters", {}))
        if mode is None:
            return False
        clipping = bool(getattr(layer, "clipping", False))
        visible = bool(getattr(layer, "visible", True))
        if not visible:
            if not clipping:
                hidden_base()
            return True
        mask = None
        if getattr(layer, "alpha_mask_store", None) is not None and not getattr(layer, "mask_disabled", False):
            mask, pending = layer_mask(layer)
            program.pending |= pending
        if getattr(layer, "layer_kind", "raster") == "adjustment":
            table = stack_table(getattr(layer, "adjustment", None))
            if table is None:
                return False
            kind, data, size = table
            ops.append(StackOp(ADJUST, mask=mask, opacity=float(layer.opacity), mode=mode,
                               clipping=clipping, parameters=parameters, adjust_kind=kind,
                               table=data, table_size=size, layer=layer))
            return True
        image, pending = layer_image(layer)
        program.pending |= pending
        if image is None:
            if not clipping:
                hidden_base()        # empty here: its clipping set shows nothing
            return True
        ops.append(StackOp(RASTER, image=image, mask=mask, opacity=float(layer.opacity),
                           mode=mode, clipping=clipping, parameters=parameters, layer=layer))
        return True

    def emit_range(start, end, child_groups) -> bool:
        child_starts = {}
        for child in child_groups:
            child_starts[min(members(child))] = child
        position = start
        while position < end:
            child = child_starts.get(position)
            if child is not None:
                if not emit_group(child):
                    return False
                position = max(members(child)) + 1
                continue
            if not emit_layer(document.layers[position]):
                return False
            position += 1
        return True

    def emit_group(group) -> bool:
        group_members = members(group)
        mode = _mode(getattr(group, "blend_mode", "normal"))
        if mode is None:
            return False
        if not getattr(group, "visible", True):
            hidden_base()
            return True
        ops.append(StackOp(GROUP_BEGIN))
        kids = sorted(children.get(group.id, []), key=lambda item: min(members(item)))
        if not emit_range(min(group_members), max(group_members) + 1, kids):
            return False
        ops.append(StackOp(GROUP_END, opacity=float(group.opacity), mode=mode,
                           parameters=_parameters(getattr(group, "blend_parameters", {}))))
        return True

    try:
        roots_sorted = sorted(roots, key=lambda item: min(members(item)))
        if not emit_range(0, len(document.layers), roots_sorted):
            return None
    except ValueError:
        return None
    return program


class StackTemplate:
    """Per-document (not per-tile) part of a stack program.

    Built once for a given layer/group structure; ``instantiate`` then only
    looks up the pixels of each layer on the tile.  This keeps the per-tile
    Python work to a dictionary lookup per layer.
    """

    __slots__ = ("entries",)

    def __init__(self, entries):
        self.entries = entries

    def instantiate(self, layer_image, layer_mask) -> StackProgram:
        program = StackProgram()
        ops = program.ops
        hidden = _HIDDEN
        for entry in self.entries:
            if entry.__class__ is StackOp:
                ops.append(entry)
                continue
            layer, template, clipping, has_mask, is_adjust = entry
            mask = None
            if has_mask:
                mask, pending = layer_mask(layer)
                program.pending |= pending
            if is_adjust:
                ops.append(StackOp(ADJUST, mask=mask, opacity=template.opacity,
                                   mode=template.mode, clipping=clipping,
                                   parameters=template.parameters,
                                   adjust_kind=template.adjust_kind, table=template.table,
                                   table_size=template.table_size))
                continue
            image, pending = layer_image(layer)
            program.pending |= pending
            if image is None:
                if not clipping:
                    ops.append(hidden)
                continue
            ops.append(StackOp(RASTER, image=image, mask=mask, opacity=template.opacity,
                               mode=template.mode, clipping=clipping,
                               parameters=template.parameters))
        return program


_HIDDEN = StackOp(RASTER, visible=False)


def build_stack_template(document, hierarchy=None) -> StackTemplate | None:
    """Structure-only program (no pixels); None when the native path can't do it."""
    placeholder = object()

    def image(layer):
        return placeholder, False

    def mask(layer):
        return placeholder, False

    program = build_stack_program(document, image, mask, hierarchy)
    if program is None:
        return None
    entries = []
    for op in program.ops:
        if op.layer is None:
            entries.append(op)
        else:
            entries.append((op.layer, op, op.clipping, op.mask is placeholder, op.kind == ADJUST))
    return StackTemplate(entries)


import ctypes


class _CsStackOp(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int), ("pixels", ctypes.c_void_p), ("stride", ctypes.c_int),
                ("format", ctypes.c_int), ("mask", ctypes.c_void_p), ("mask_stride", ctypes.c_int),
                ("opacity", ctypes.c_float), ("mode", ctypes.c_int), ("visible", ctypes.c_int),
                ("clipping", ctypes.c_int), ("parameters", ctypes.c_float * 11),
                ("adjust_kind", ctypes.c_int), ("table", ctypes.c_void_p),
                ("table_size", ctypes.c_int)]


def native_stack_function(library):
    """``cs_compose_stack`` with its signature declared, or None (old bridge)."""
    function = getattr(library, "cs_compose_stack", None) if library is not None else None
    if function is None:
        return None
    if not function.argtypes:
        function.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.POINTER(_CsStackOp), ctypes.c_int]
        function.restype = ctypes.c_int
    return function


def compose_program(program: StackProgram, width: int, height: int, function,
                    pixels_of, new_target):
    """Run ``program`` natively.

    ``pixels_of(image) -> (address, stride, format_code)`` exposes an image
    (format 0 = ARGB32, 1 = RGBA8888, None = unsupported);
    ``new_target(width, height) -> (image, address, stride)`` allocates the
    ARGB32 result.  Returns the result image or None.
    """
    keepalive = []
    records = []
    for op in program.ops:
        pixels = mask = table = None
        stride = mask_stride = fmt = 0
        if op.image is not None:
            described = pixels_of(op.image)
            if described is None:
                return None
            pixels, stride, fmt = described
            keepalive.append(op.image)
        if op.mask is not None:
            described = pixels_of(op.mask)
            if described is None:
                return None
            mask, mask_stride, _fmt = described
            keepalive.append(op.mask)
        if op.table is not None:
            if isinstance(op.table, (bytes, bytearray)):
                buffer = ctypes.create_string_buffer(bytes(op.table), len(op.table))
                keepalive.append(buffer)
                table = ctypes.addressof(buffer)
            else:
                keepalive.append(op.table)
                table = op.table.ctypes.data
        records.append(_CsStackOp(op.kind, pixels, stride, fmt, mask, mask_stride,
                                  float(op.opacity), int(op.mode), 1 if op.visible else 0,
                                  1 if op.clipping else 0,
                                  (ctypes.c_float * 11)(*op.parameters), int(op.adjust_kind),
                                  table, int(op.table_size)))
    array = (_CsStackOp * max(1, len(records)))(*records)
    image, address, stride = new_target(width, height)
    if not function(address, width, height, stride, array, len(records)):
        return None
    return image


class _CsStackJob(ctypes.Structure):
    _fields_ = [("target", ctypes.c_void_p), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("target_stride", ctypes.c_int), ("ops", ctypes.POINTER(_CsStackOp)),
                ("op_count", ctypes.c_int), ("result", ctypes.c_int)]


def native_batch_function(library):
    function = getattr(library, "cs_compose_stack_batch", None) if library is not None else None
    if function is None:
        return None
    if not function.argtypes:
        function.argtypes = [ctypes.POINTER(_CsStackJob), ctypes.c_int]
        function.restype = ctypes.c_int
    return function


def compose_batch(jobs, function, pixels_of, new_target):
    """Compose several (program, width, height) in parallel natively.

    Returns a list of result images (None for a job that failed).
    """
    keepalive = []
    natives = []
    targets = []
    for program, width, height in jobs:
        records = _records(program, pixels_of, keepalive)
        if records is None:
            return None
        array = (_CsStackOp * max(1, len(records)))(*records)
        keepalive.append(array)
        image, address, stride = new_target(width, height)
        targets.append(image)
        natives.append(_CsStackJob(address, width, height, stride, array, len(records), 0))
    if not natives:
        return []
    batch = (_CsStackJob * len(natives))(*natives)
    function(batch, len(natives))
    return [image if batch[index].result else None for index, image in enumerate(targets)]


def _records(program, pixels_of, keepalive):
    records = []
    for op in program.ops:
        pixels = mask = table = None
        stride = mask_stride = fmt = 0
        if op.image is not None:
            described = pixels_of(op.image)
            if described is None:
                return None
            pixels, stride, fmt = described
            keepalive.append(op.image)
        if op.mask is not None:
            described = pixels_of(op.mask)
            if described is None:
                return None
            mask, mask_stride, _fmt = described
            keepalive.append(op.mask)
        if op.table is not None:
            if isinstance(op.table, (bytes, bytearray)):
                buffer = _TABLE_BUFFERS.get(id(op.table))
                if buffer is None or buffer[0] is not op.table:
                    buffer = (op.table, ctypes.create_string_buffer(bytes(op.table), len(op.table)))
                    if len(_TABLE_BUFFERS) > 256:
                        _TABLE_BUFFERS.clear()
                    _TABLE_BUFFERS[id(op.table)] = buffer
                table = ctypes.addressof(buffer[1])
            else:
                keepalive.append(op.table)
                table = op.table.ctypes.data
        records.append(_CsStackOp(op.kind, pixels, stride, fmt, mask, mask_stride,
                                  float(op.opacity), int(op.mode), 1 if op.visible else 0,
                                  1 if op.clipping else 0,
                                  (ctypes.c_float * 11)(*op.parameters), int(op.adjust_kind),
                                  table, int(op.table_size)))
    return records


_TABLE_BUFFERS: dict = {}


__all__ = ["native_batch_function", "compose_batch", "build_stack_template", "StackTemplate",
           "native_stack_function", "compose_program", "StackOp", "StackProgram", "build_stack_program", "RASTER", "GROUP_BEGIN",
           "GROUP_END", "ADJUST"]
