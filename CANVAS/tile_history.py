from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from collections.abc import Mapping
import base64
import json
from pathlib import Path
import zipfile

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRect
from PySide6.QtGui import QColor, QFont, QImage

from DOCUMENTS.layer import Layer
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.tile_store import TILE_SIZE
from CORE.native_bridge import (create_native_history_cursor,
                                create_native_history_payload,
                                copy_image_rect_native,
                                crop_image_native,
                                fill_image_native,
                                native_tile_range_for_rect,
                                validate_history_layer_state)


SELECTION_TILE_ID = "__selection_mask__"
ALPHA_MASK_TILE_PREFIX = "__alpha_mask__:"


@dataclass
class UndoStep:
    before: dict
    after: dict
    tiles: Mapping
    swap_path: str | None = None
    native_state_bytes: int = 0

    def __post_init__(self):
        if not isinstance(self.tiles, NativeTileDeltaMap):
            self.tiles = NativeTileDeltaMap(self.tiles)


class NativeTileDeltaMap(Mapping):
    """Mapping-compatible keys with before/after QImages owned by CreativeCore."""

    def __init__(self, source=()):
        values = dict(source)
        self._keys = []
        self._indices = {}
        self._payload = create_native_history_payload()
        if not self._payload:
            raise RuntimeError("CreativeCore is required to store undo pixels")
        entries = list(values.items())
        indices = self._payload.append_many([pair for _key, pair in entries])
        if indices is None:
            self._payload.close()
            self._payload = None
            raise OSError("CreativeCore could not store the undo tile batch")
        for (key, _pair), index in zip(entries, indices):
            if index >= 0:
                self._indices[key] = index
                self._keys.append(key)

    def __getitem__(self, key):
        try:
            index = self._indices[key]
        except KeyError as error:
            raise KeyError(key) from error
        return self._payload.tile(index, 0), self._payload.tile(index, 1)

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    @property
    def native_storage_bytes(self) -> int:
        return self._payload.allocated_bytes if self._payload else 0

    @property
    def is_native(self) -> bool:
        return bool(self._payload)

    def clear(self) -> None:
        if self._payload:
            self._payload.close()
        self._payload = None
        self._keys.clear()
        self._indices.clear()

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.items()) == dict(other.items())

    def apply_layers(self, layers, side: int) -> bool:
        """Restore every layer delta in one cross-store native transaction."""
        if not self.is_native:
            return False
        writes = []
        for key, index in self._indices.items():
            layer_id = key[0]
            if layer_id.startswith(ALPHA_MASK_TILE_PREFIX):
                layer = layers.get(layer_id[len(ALPHA_MASK_TILE_PREFIX):])
                store = layer.ensure_alpha_mask()._native_handle if layer else None
            else:
                layer = layers.get(layer_id)
                store = layer.tile_store._native_handle if layer else None
            if layer is None:
                continue
            if not store:
                return False
            writes.append((store, index, key[1], key[2]))
        return self._payload.apply_to_stores(writes, side)


class TileHistory:
    """Bounded undo history that retains pixel data only for changed tiles."""

    def __init__(self, tile_size: int = TILE_SIZE, max_steps: int = 30) -> None:
        self.tile_size = TILE_SIZE
        self.max_steps = max(1, int(max_steps))
        self.steps: list[UndoStep] = []
        self._native_cursor = create_native_history_cursor(self.max_steps)
        if not self._native_cursor:
            raise RuntimeError("CreativeCore is required to manage undo history")
        self._pending: dict | None = None
        self._assert_cursor_consistency()

    def _assert_cursor_consistency(self) -> None:
        """Keep Qt-owned step metadata aligned with CreativeCore's timeline."""
        transaction_open = self._native_cursor.transaction_open
        if (self._native_cursor.count != len(self.steps) or
                not 0 <= self._native_cursor.index <= self._native_cursor.count or
                transaction_open != (self._pending is not None) or
                (transaction_open and self._native_cursor.transaction_mode not in
                 {"general", "dirty", "selection", "structure"})):
            raise RuntimeError("CreativeCore history cursor and step metadata diverged")

    @property
    def index(self) -> int:
        return self._native_cursor.index

    @index.setter
    def index(self, value: int) -> None:
        self._native_cursor.synchronize(len(self.steps), int(value))
        self._assert_cursor_consistency()

    def reset(self) -> None:
        self._remove_swap_files(self.steps)
        self.steps.clear()
        self._native_cursor.reset()
        self._pending = None
        self._assert_cursor_consistency()

    def cancel(self) -> None:
        self._pending = None
        if self._native_cursor.transaction_open:
            self._native_cursor.cancel_transaction()
        self._assert_cursor_consistency()

    @staticmethod
    def _encode_image(image: QImage | None) -> bytes | None:
        if image is None:
            return None
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            buffer.close()
            raise OSError("Could not encode undo tile for disk swap")
        buffer.close()
        return bytes(data)

    @classmethod
    def write_step_swap(cls, step: UndoStep, path: str | Path) -> int:
        """Serialize immutable undo tile deltas; safe to call from a worker."""
        path = Path(path)
        manifest = []
        payload_bytes = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, ((layer_id, tx, ty), pair) in enumerate(step.tiles.items()):
                row = {"layer": layer_id, "x": tx, "y": ty,
                       "before": None, "after": None}
                for side, image in zip(("before", "after"), pair):
                    encoded = cls._encode_image(image)
                    if encoded is not None:
                        name = f"tile-{index}-{side}.png"
                        row[side] = name
                        archive.writestr(name, encoded)
                        payload_bytes += len(encoded)
                manifest.append(row)
            archive.writestr("manifest.json",
                             json.dumps(manifest, separators=(",", ":")))
        return payload_bytes

    @staticmethod
    def _remove_swap_files(steps) -> None:
        for step in steps:
            if step.swap_path:
                try:
                    Path(step.swap_path).unlink(missing_ok=True)
                except OSError:
                    pass
            if hasattr(step.tiles, "clear"):
                step.tiles.clear()

    @staticmethod
    def load_step_swap(step: UndoStep) -> dict[tuple[str, int, int], tuple[QImage | None, QImage | None]]:
        if not step.swap_path:
            return step.tiles
        tiles = {}
        with zipfile.ZipFile(step.swap_path, "r") as archive:
            for row in json.loads(archive.read("manifest.json")):
                images = []
                for side in ("before", "after"):
                    name = row[side]
                    if name is None:
                        images.append(None)
                        continue
                    image = QImage()
                    if not image.loadFromData(archive.read(name), "PNG"):
                        raise OSError(f"Could not decode undo tile {name}")
                    images.append(image)
                tiles[(row["layer"], int(row["x"]), int(row["y"]))] = tuple(images)
        return tiles

    def attach_step_swap(self, step: UndoStep, path: str) -> None:
        step.swap_path = path
        step.tiles.clear()

    def discard_oldest(self, count: int) -> None:
        removed = self._native_cursor.discard_oldest(int(count))
        self._discard_oldest_python(removed)
        self._assert_cursor_consistency()

    def _discard_oldest_python(self, count: int) -> None:
        count = int(count)
        if count < 0 or count > len(self.steps):
            raise RuntimeError("CreativeCore returned an invalid history retention plan")
        removed = self.steps[:count]
        self._remove_swap_files(removed)
        del self.steps[:count]

    def set_max_steps(self, maximum: int) -> None:
        removed = self._native_cursor.set_maximum(int(maximum))
        self.max_steps = self._native_cursor.maximum
        self._discard_oldest_python(removed)
        self._assert_cursor_consistency()

    def _append_step(self, step: UndoStep) -> None:
        self._assert_cursor_consistency()
        if self._native_cursor.transaction_open:
            raise RuntimeError("Cannot append history while an edit transaction is open")
        append_state = getattr(self._native_cursor, "append_state", None)
        native_state_ready = all(
            key in step.before and key in step.after
            for key in ("history_mode", "width", "height", "selection_width",
                        "selection_height", "selection_format", "active_layer_index",
                        "layers", "layer_groups")
        )
        if append_state is not None and native_state_ready:
            before_payload = self._native_state_payload(step.before)
            after_payload = self._native_state_payload(step.after)
            result = append_state(before_payload, after_payload)
            if result is None:
                raise RuntimeError("CreativeCore rejected native history state")
            truncated, discarded = result
            step.native_state_bytes = len(before_payload) + len(after_payload)
            step.before = {}
            step.after = {}
        else:
            truncated, discarded = self._native_cursor.append()
        if truncated:
            branch_start = len(self.steps) - truncated
            if branch_start < 0:
                raise RuntimeError("CreativeCore requested an invalid history branch trim")
            self._remove_swap_files(self.steps[branch_start:])
            del self.steps[branch_start:]
        self.steps.append(step)
        self._discard_oldest_python(discarded)
        self._assert_cursor_consistency()

    @staticmethod
    def _layer_meta(layer) -> dict:
        return {
            "id": layer.id,
            "name": layer.name,
            "visible": layer.visible,
            "opacity": layer.opacity,
            "blend_mode": layer.blend_mode,
            "blend_parameters": dict(getattr(layer, "blend_parameters", {})),
            "locked": layer.locked,
            "lock_alpha": layer.lock_alpha,
            "clipping": layer.clipping,
            "width": layer.tile_store.width,
            "height": layer.tile_store.height,
            "format": layer.tile_store.image_format,
            "alpha_mask_present": layer.alpha_mask_store is not None,
        }

    @staticmethod
    def _encode_reference_image(item: ReferenceImage) -> dict:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not item.image.save(buffer, "PNG"):
            buffer.close()
            raise OSError("Could not encode reference image for native history")
        buffer.close()
        return {
            "id": item.id,
            "x": item.position.x(),
            "y": item.position.y(),
            "scale": float(item.scale),
            "opacity": float(item.opacity),
            "png": base64.b64encode(bytes(data)).decode("ascii"),
        }

    @classmethod
    def _native_state_payload(cls, state: dict) -> bytes:
        encoded = {
            "history_mode": state["history_mode"],
            "width": int(state["width"]),
            "height": int(state["height"]),
            "selection_width": int(state["selection_width"]),
            "selection_height": int(state["selection_height"]),
            "selection_format": getattr(state["selection_format"], "value", state["selection_format"]),
            "active_layer_index": int(state["active_layer_index"]),
            "layers": [{**item, "format": getattr(item["format"], "value", item["format"])}
                       for item in state["layers"]],
            "layer_groups": state["layer_groups"],
            "blend_presets": state.get("blend_presets", {}),
            "text_objects": [{
                "id": item.id,
                "text": item.text,
                "x": item.position.x(),
                "y": item.position.y(),
                "color": item.color.rgba(),
                "font": item.font.toString(),
            } for item in state.get("text_objects", ())],
        }
        if "reference_images" in state:
            encoded["reference_images"] = [
                cls._encode_reference_image(item)
                for item in state["reference_images"]
            ]
        return json.dumps(encoded, separators=(",", ":"), allow_nan=False).encode("utf-8")

    @classmethod
    def _validate_native_state(cls, state: dict) -> None:
        payload = cls._native_state_payload(state)
        valid = validate_history_layer_state(payload, state["width"], state["height"])
        if valid is None:
            raise RuntimeError("CreativeCore is required to validate history metadata")
        if not valid:
            raise ValueError("CreativeCore rejected an invalid history layer state")

    def _capture(self, document, include_images: bool = True,
                 include_objects: bool = True,
                 mode: str = "general") -> tuple[dict, dict[str, QImage]]:
        layers = list(document.layers)
        state = {
            "history_mode": mode,
            "width": document.width,
            "height": document.height,
            "selection_width": document.selection.image.width(),
            "selection_height": document.selection.image.height(),
            "selection_format": document.selection.image.format(),
        }
        if mode in {"general", "structure"}:
            state.update({
                "layers": [self._layer_meta(layer) for layer in layers],
                "active_layer_index": document.active_layer_index,
                "blend_presets": deepcopy(getattr(document, "blend_presets", {})),
                "layer_groups": [{
                    "id": group.id, "name": group.name,
                    "layer_ids": list(group.layer_ids), "visible": group.visible,
                    "opacity": group.opacity, "blend_mode": group.blend_mode,
                    "blend_parameters": dict(group.blend_parameters),
                } for group in getattr(document, "layer_groups", ())],
            })
        if mode == "general" and include_objects:
            state["reference_images"] = [item.copy() for item in document.reference_images]
            state["text_objects"] = [item.copy() for item in document.text_objects]
        if mode in {"general", "structure"}:
            self._validate_native_state(state)
        images = (
            {layer.id: QImage(layer.image) for layer in layers}
            if include_images else {}
        )
        if include_images:
            images[SELECTION_TILE_ID] = QImage(document.selection.image)
        return state, images

    def begin(
        self,
        document,
        dirty_only: bool = False,
        selection_only: bool = False,
        structure_only: bool = False,
    ) -> None:
        if self._pending is not None or self._native_cursor.transaction_open:
            return
        if not self._native_cursor.begin_transaction(
                dirty_only, selection_only, structure_only):
            return
        try:
            mode = self._native_cursor.transaction_mode
            if mode is None:
                raise RuntimeError("CreativeCore returned an invalid transaction mode")
            if mode == "general":
                for layer in document.layers:
                    layer.commit_image_cache()
            state, _images = self._capture(
                document, include_images=False, include_objects=mode == "general",
                mode=mode,
            )
            before_tiles = {}
            if mode == "selection":
                before_tiles.update(self._capture_selection_tiles(document))
            elif mode == "general":
                before_tiles.update(self._capture_document_tiles(document))
            self._pending = {
                "state": state,
                "mode": mode,
                "before_tiles": before_tiles,
            }
            self._assert_cursor_consistency()
        except Exception:
            self._native_cursor.cancel_transaction()
            self._pending = None
            raise

    def capture_before(self, layer, rect: QRect) -> None:
        """Save touched stroke tiles once, before the first write to each tile."""
        if self._pending is None or self._pending["mode"] != "dirty" or rect.isEmpty():
            return
        before_tiles = self._pending["before_tiles"]
        for tx, ty in self._tile_keys(layer.tile_store.width, layer.tile_store.height, rect):
            key = (layer.id, tx, ty)
            if key not in before_tiles:
                before_tiles[key] = layer.tile_store.tile(tx, ty)

    def captured_before_tile(self, layer_id: str, tx: int, ty: int):
        """Return (captured, image); a captured None represents a transparent sparse tile."""
        if self._pending is None:
            return False, None
        key = (layer_id, int(tx), int(ty))
        tiles = self._pending["before_tiles"]
        if key not in tiles:
            return False, None
        return True, tiles[key]

    def capture_layer_before(self, layer, keys=None) -> None:
        """Capture sparse tile payloads for a known structural edit target."""
        if self._pending is None or self._pending["mode"] != "structure":
            return
        layer.commit_image_cache()
        selected = layer.tile_store.occupied_keys if keys is None else set(keys)
        for tx, ty in selected:
            key = (layer.id, int(tx), int(ty))
            if key in self._pending["before_tiles"]:
                continue
            image = (layer.tile_store.tile(*key[1:])
                     if key[1:] in layer.tile_store.occupied_keys else None)
            self._pending["before_tiles"][key] = image
        mask_store = layer.alpha_mask_store
        if mask_store is not None:
            for tx, ty in (mask_store.occupied_keys if keys is None else set(keys)):
                key = (ALPHA_MASK_TILE_PREFIX + layer.id, int(tx), int(ty))
                if key not in self._pending["before_tiles"]:
                    self._pending["before_tiles"][key] = mask_store.tile(tx, ty)

    def capture_mask_before(self, layer, rect: QRect) -> None:
        """Capture alpha-mask tiles before a mask edit begins."""
        if self._pending is None or rect.isEmpty():
            return
        if self._pending["mode"] not in {"dirty", "structure"}:
            return
        store = layer.ensure_alpha_mask()
        for tx, ty in self._tile_keys(store.width, store.height, rect):
            key = (ALPHA_MASK_TILE_PREFIX + layer.id, tx, ty)
            if key not in self._pending["before_tiles"]:
                self._pending["before_tiles"][key] = (
                    store.tile(tx, ty) if (tx, ty) in store.occupied_keys else None)

    def mark_dirty(self, layer, rect: QRect | None) -> None:
        """Keep the transaction API explicit; tile capture is the source of truth."""
        # The native history payload records the actual changed tiles.  A
        # second dirty-rectangle map used to be accumulated here but was never
        # consumed during commit or replay.
        return

    def _tile_keys(self, width: int, height: int, rect: QRect | None = None):
        if width <= 0 or height <= 0:
            return
        region = QRect(0, 0, width, height) if rect is None else rect
        tile_range = native_tile_range_for_rect(
            width, height, self.tile_size, region.x(), region.y(),
            region.width(), region.height(),
        )
        if tile_range is None:
            raise RuntimeError("CreativeCore is required to plan history tile capture")
        first_x, first_y, end_x, end_y = tile_range
        for ty in range(first_y, end_y):
            for tx in range(first_x, end_x):
                yield tx, ty

    def _tile(self, image: QImage, tx: int, ty: int) -> QImage | None:
        if image.isNull():
            return None
        rect = QRect(tx * self.tile_size, ty * self.tile_size, self.tile_size, self.tile_size)
        rect = rect.intersected(image.rect())
        if rect.isEmpty():
            return None
        tile = crop_image_native(image, rect)
        if tile is None:
            raise RuntimeError("CreativeCore is required to capture history pixels")
        return tile

    def _capture_selection_tiles(self, document) -> dict:
        selection = document.selection
        bounds = selection.bounds()
        captured = {}
        for tx, ty in self._tile_keys(selection.width, selection.height, bounds):
            tile = self._tile(selection.image, tx, ty)
            if tile is not None:
                captured[(SELECTION_TILE_ID, tx, ty)] = tile
        return captured

    def _capture_document_tiles(self, document) -> dict:
        captured = {}
        for layer in document.layers:
            layer.commit_image_cache()
            for tx, ty in layer.tile_store.occupied_keys:
                captured[(layer.id, tx, ty)] = layer.tile_store.tile(tx, ty)
            mask_store = layer.alpha_mask_store
            if mask_store is not None:
                for tx, ty in mask_store.occupied_keys:
                    captured[(ALPHA_MASK_TILE_PREFIX + layer.id, tx, ty)] = mask_store.tile(tx, ty)
        captured.update(self._capture_selection_tiles(document))
        return captured

    @staticmethod
    def _make_diffs(before_tiles, after_tiles):
        diffs = {}
        for key in before_tiles.keys() | after_tiles.keys():
            old_tile = before_tiles.get(key)
            new_tile = after_tiles.get(key)
            if old_tile is not None or new_tile is not None:
                diffs[key] = (old_tile, new_tile)
        return diffs

    def _append_if_changed(self, before, after, diffs) -> bool:
        step = UndoStep(before, after, diffs)
        if before == after and not step.tiles:
            return False
        self._append_step(step)
        return True

    def commit(self, document) -> bool:
        if self._pending is None:
            return False
        if not self._native_cursor.transaction_open:
            raise RuntimeError("CreativeCore has no open history transaction to commit")
        for layer in document.layers:
            layer.commit_image_cache()
        pending = self._pending
        if not self._native_cursor.commit_transaction():
            raise RuntimeError("CreativeCore rejected an open history transaction")
        self._pending = None
        self._assert_cursor_consistency()
        after, _after_images = self._capture(
            document, include_images=False,
            include_objects=pending["mode"] == "general",
            mode=pending["mode"],
        )
        before = pending["state"]
        before_layers = ({item["id"]: item for item in before["layers"]}
                         if pending["mode"] == "structure" else {})
        diffs: dict[tuple[str, int, int], tuple[QImage | None, QImage | None]] = {}

        if pending["mode"] == "selection":
            diffs = self._make_diffs(
                pending["before_tiles"], self._capture_selection_tiles(document))
            return self._append_if_changed(before, after, diffs)

        if pending["mode"] == "dirty":
            current_layers = {layer.id: layer for layer in document.layers}
            for key, old_tile in pending["before_tiles"].items():
                layer_id, tx, ty = key
                is_mask = layer_id.startswith(ALPHA_MASK_TILE_PREFIX)
                real_id = layer_id[len(ALPHA_MASK_TILE_PREFIX):] if is_mask else layer_id
                layer = current_layers.get(real_id)
                store = (layer.alpha_mask_store if is_mask else layer.tile_store) if layer else None
                current_keys = store.occupied_keys if store is not None else set()
                new_tile = (store.tile(tx, ty)
                            if (tx, ty) in current_keys else None)
                if old_tile is not None or new_tile is not None:
                    diffs[key] = (old_tile, new_tile)
            return self._append_if_changed(before, after, diffs)

        if pending["mode"] == "structure":
            current_layers = {layer.id: layer for layer in document.layers}
            for key, old_tile in pending["before_tiles"].items():
                layer_id, tx, ty = key
                is_mask = layer_id.startswith(ALPHA_MASK_TILE_PREFIX)
                real_id = layer_id[len(ALPHA_MASK_TILE_PREFIX):] if is_mask else layer_id
                layer = current_layers.get(real_id)
                store = (layer.alpha_mask_store if is_mask else layer.tile_store) if layer else None
                current_keys = store.occupied_keys if store is not None else set()
                new_tile = (store.tile(tx, ty)
                            if (tx, ty) in current_keys else None)
                if old_tile is not None or new_tile is not None:
                    diffs[key] = (old_tile, new_tile)
            for layer_id, layer in current_layers.items():
                if layer_id in before_layers:
                    continue
                for tx, ty in layer.tile_store.occupied_keys:
                    diffs[(layer_id, tx, ty)] = (None, layer.tile_store.tile(tx, ty))
                if layer.alpha_mask_store is not None:
                    for tx, ty in layer.alpha_mask_store.occupied_keys:
                        diffs[(ALPHA_MASK_TILE_PREFIX + layer_id, tx, ty)] = (
                            None, layer.alpha_mask_store.tile(tx, ty))
            return self._append_if_changed(before, after, diffs)

        diffs = self._make_diffs(
            pending["before_tiles"], self._capture_document_tiles(document))

        return self._append_if_changed(before, after, diffs)

    @staticmethod
    def _copy_tile(target: QImage, tile: QImage, tx: int, ty: int, tile_size: int) -> None:
        x, y = tx * tile_size, ty * tile_size
        rect = QRect(0, 0, tile.width(), tile.height())
        if not copy_image_rect_native(tile, target, rect, x, y):
            raise RuntimeError("CreativeCore is required to restore selection history pixels")

    def _apply(self, document, step: UndoStep, after: bool,
               history_index: int | None = None) -> None:
        for current_layer in document.layers:
            current_layer.commit_image_cache(release=True)
        state = step.after if after else step.before
        if history_index is not None:
            native_state = self._native_cursor.state(history_index, 1 if after else 0)
            if native_state:
                merged = dict(state)
                merged.update(json.loads(native_state.decode("utf-8")))
                if isinstance(merged.get("selection_format"), int):
                    merged["selection_format"] = QImage.Format(merged["selection_format"])
                for meta in merged.get("layers", ()):
                    if isinstance(meta.get("format"), int):
                        meta["format"] = QImage.Format(meta["format"])
                if "text_objects" in merged:
                    text_objects = []
                    for item in merged["text_objects"]:
                        font = QFont()
                        font.fromString(item["font"])
                        text_objects.append(EditableText(
                            item["text"], QPointF(float(item["x"]), float(item["y"])),
                            QColor.fromRgba(int(item["color"])), font, item["id"],
                        ))
                    merged["text_objects"] = text_objects
                if "reference_images" in merged:
                    references = []
                    for item in merged["reference_images"]:
                        image = QImage()
                        raw = base64.b64decode(item["png"], validate=True)
                        if not image.loadFromData(raw, "PNG"):
                            raise ValueError("Native history reference image is invalid")
                        references.append(ReferenceImage(
                            image, QPointF(float(item["x"]), float(item["y"])),
                            float(item["scale"]), float(item["opacity"]), item["id"],
                        ))
                    merged["reference_images"] = references
                state = merged
        mode = state.get("history_mode", "general")
        if mode in {"general", "structure"}:
            self._validate_native_state(state)
        fast_scope = mode in {"dirty", "selection"}
        if fast_scope:
            if (document.width != state["width"] or document.height != state["height"]):
                raise RuntimeError("Cannot replay a local history step on different document geometry")
            layers = list(document.layers)
        else:
            existing = {layer.id: layer for layer in document.layers}
            layers = []
            for meta in state["layers"]:
                layer = existing.get(meta["id"])
                if (
                    layer is None
                    or layer.tile_store.width != meta["width"]
                    or layer.tile_store.height != meta["height"]
                    or layer.tile_store.image_format != meta["format"]
                ):
                    layer = Layer(meta["name"], meta["width"], meta["height"])
                    layer.id = meta["id"]
                layer.name = meta["name"]
                layer.visible = meta["visible"]
                layer.opacity = meta["opacity"]
                layer.blend_mode = meta["blend_mode"]
                layer.blend_parameters = dict(meta.get("blend_parameters", {}))
                layer.locked = meta["locked"]
                layer.lock_alpha = meta["lock_alpha"]
                layer.clipping = meta["clipping"]
                if meta.get("alpha_mask_present", False):
                    layer.ensure_alpha_mask()
                else:
                    layer.set_alpha_mask(None)
                layers.append(layer)

        by_id = {layer.id: layer for layer in layers}
        tiles = self.load_step_swap(step) if step.swap_path and not step.tiles else step.tiles
        native_tiles = (tiles if isinstance(tiles, NativeTileDeltaMap) and tiles.is_native
                        and all(layer.tile_store._native_handle for layer in layers) else None)
        native_side = 1 if after else 0
        if mode == "dirty" and any(
                (layer_id[len(ALPHA_MASK_TILE_PREFIX):] if layer_id.startswith(ALPHA_MASK_TILE_PREFIX)
                 else layer_id) not in by_id
                for layer_id, _x, _y in tiles):
            raise RuntimeError("Raster history references a layer outside the current stack")
        if mode == "selection" and any(layer_id != SELECTION_TILE_ID
                                        for layer_id, _x, _y in tiles):
            raise RuntimeError("Selection history contains a non-selection tile")
        if native_tiles is not None:
            if not native_tiles.apply_layers(by_id, native_side):
                raise OSError("Could not restore native history tiles atomically")
            for layer in layers:
                layer.discard_image_cache()
        layer_writes: dict[str, list[tuple[int, int, QImage]]] = {}
        for layer_id, tx, ty in tiles:
            if layer_id == SELECTION_TILE_ID:
                continue
            if native_tiles is not None:
                continue
            values = tiles[(layer_id, tx, ty)]
            tile = values[1] if after else values[0]
            is_mask = layer_id.startswith(ALPHA_MASK_TILE_PREFIX)
            real_id = layer_id[len(ALPHA_MASK_TILE_PREFIX):] if is_mask else layer_id
            layer = by_id.get(real_id)
            if layer is not None:
                store = layer.ensure_alpha_mask() if is_mask else layer.tile_store
                rect = store.tile_rect(tx, ty)
                if tile is None:
                    # A missing side means the sparse tile did not exist in
                    # that history state. Explicitly clear it; skipping here
                    # leaves stale pixels when replaying structural deltas.
                    tile = QImage(rect.size(), store.image_format)
                    if not fill_image_native(tile, QColor(0, 0, 0, 0)):
                        raise RuntimeError("CreativeCore is required to clear history tiles")
                layer_writes.setdefault(layer_id, []).append((tx, ty, tile))
        for layer_id, writes in layer_writes.items():
            is_mask = layer_id.startswith(ALPHA_MASK_TILE_PREFIX)
            real_id = layer_id[len(ALPHA_MASK_TILE_PREFIX):] if is_mask else layer_id
            layer = by_id[real_id]
            store = layer.ensure_alpha_mask() if is_mask else layer.tile_store
            if not store.set_tiles_batch(writes):
                raise OSError(f"Could not restore history tiles for layer {layer_id}")
            if not is_mask:
                layer.discard_image_cache()

        selection = document.selection.image
        if (
            selection.width() != state["selection_width"]
            or selection.height() != state["selection_height"]
            or selection.format() != state["selection_format"]
        ):
            selection = QImage(
                state["selection_width"], state["selection_height"], state["selection_format"]
            )
            if not fill_image_native(selection, QColor(0, 0, 0, 0)):
                raise RuntimeError("CreativeCore is required to clear the selection history")
        for (layer_id, tx, ty), values in tiles.items():
            if layer_id != SELECTION_TILE_ID:
                continue
            tile = values[1] if after else values[0]
            rect = QRect(tx * self.tile_size, ty * self.tile_size,
                         self.tile_size, self.tile_size).intersected(selection.rect())
            if rect.isEmpty():
                continue
            if tile is None:
                tile = QImage(rect.size(), selection.format())
                if not fill_image_native(tile, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore is required to clear history tiles")
            self._copy_tile(selection, tile, tx, ty, self.tile_size)

        if not fast_scope:
            document.layers = layers
            from DOCUMENTS.layer_group import LayerGroup
            document.layer_groups = [LayerGroup(
                name=item["name"], id=item["id"], layer_ids=list(item["layer_ids"]),
                visible=item["visible"], opacity=item["opacity"],
                blend_mode=item["blend_mode"],
                blend_parameters=dict(item.get("blend_parameters", {})),
            ) for item in state.get("layer_groups", [])]
            document.width = state["width"]
            document.height = state["height"]
            document.active_layer_index = min(
                state["active_layer_index"], max(0, len(layers) - 1)
            )
            document.selection.image = selection
            document.selection.invalidate()
            if "reference_images" in state:
                document.reference_images = [item.copy() for item in state["reference_images"]]
            if "text_objects" in state:
                document.text_objects = [item.copy() for item in state["text_objects"]]
            document.blend_presets = deepcopy(state.get("blend_presets", {}))
            document.sync_native_state()
        elif mode == "selection":
            document.selection.image = selection
            document.selection.invalidate()

    def undo(self, document) -> bool:
        self._assert_cursor_consistency()
        if self._native_cursor.transaction_open:
            return False
        if self.index <= 0:
            return False
        target_index = self.index - 1
        self._apply(document, self.steps[target_index], after=False,
                    history_index=target_index)
        # Move the native cursor only after a successful document apply.
        if not self._native_cursor.undo():
            raise RuntimeError("CreativeCore rejected a validated history undo")
        self._assert_cursor_consistency()
        return True

    def redo(self, document) -> bool:
        self._assert_cursor_consistency()
        if self._native_cursor.transaction_open:
            return False
        if self.index >= len(self.steps):
            return False
        self._apply(document, self.steps[self.index], after=True,
                    history_index=self.index)
        if not self._native_cursor.redo():
            raise RuntimeError("CreativeCore rejected a validated history redo")
        self._assert_cursor_consistency()
        return True
