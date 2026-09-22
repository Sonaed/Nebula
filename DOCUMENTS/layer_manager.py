from DOCUMENTS.document import Document
from DOCUMENTS.layer import Layer
import math
from DOCUMENTS.blend_modes import (composite_document,
                                   composite_document_layers, composite_layers)
from CORE.native_bridge import (composite_layer_in_place, move_layer_stack,
                                plan_visible_layer_merge_groups,
                                plan_layer_group_cleanup,
                                remove_layer_stack, update_layer_property)
from types import SimpleNamespace


class LayerManager:

    def __init__(
        self,
        document: Document
    ) -> None:

        self.document: Document = document

    def add_layer(
        self,
        name: str = "Nouveau calque"
    ) -> Layer:

        layer = self.document.add_layer(
            name
        )

        self.document.active_layer_index = (
            len(self.document.layers) - 1
        )

        return layer

    def remove_layer(
        self,
        index: int
    ) -> bool:

        if len(self.document.layers) <= 1:
            return False

        if index < 0:
            return False

        if index >= len(
            self.document.layers
        ):
            return False

        result = remove_layer_stack(
            len(self.document.layers), index, self.document.active_layer_index
        )
        if result is None:
            raise RuntimeError("CreativeCore is required to remove layers")
        if result is False:
            return False
        removed = self.document.layers[index]
        order, active_after = result
        layers = self.document.layers
        group_indices = {group.id: number for number, group
                         in enumerate(self.document.layer_groups)}
        memberships = []
        for layer in layers:
            owned = [group_indices[group.id] for group in self.document.layer_groups
                     if layer.id in group.layer_ids]
            if len(owned) > 1:
                return False
            memberships.append(owned[0] if owned else -1)
        cleanup = plan_layer_group_cleanup(
            memberships, [int(position != index) for position in range(len(layers))],
            len(self.document.layer_groups))
        if cleanup is None:
            raise RuntimeError("CreativeCore is required to clean layer groups")
        if cleanup is False:
            return False
        if not self.document._native_state.remove_layer(index):
            raise RuntimeError("CreativeCore a refusé la suppression du calque")
        self.document.layers[:] = [layers[position] for position in order]
        self.document.active_layer_index = active_after
        # The native cleanup plan is expressed in the original layer order;
        # restore that order for the surviving membership list before applying.
        surviving_membership = [memberships[position] for position in order]
        cleanup = (cleanup[0], surviving_membership)
        self._apply_group_cleanup(cleanup)
        self.document.sync_native_state()

        return True

    def select_layer(
        self,
        index: int
    ) -> bool:

        if index < 0:
            return False

        if index >= len(
            self.document.layers
        ):
            return False

        if not self.document._native_state.select_layer(index):
            raise RuntimeError("CreativeCore a refusé la sélection du calque")
        self.document.active_layer_index = index

        return True

    def rename_layer(
        self,
        index: int,
        name: str
    ) -> bool:

        if index < 0:
            return False

        if index >= len(
            self.document.layers
        ):
            return False

        name = name.strip()

        if not name:
            return False

        if not self.document._native_state.rename_layer(index, name):
            raise RuntimeError("CreativeCore a refusé le renommage du calque")
        self.document.layers[index].name = name

        return True

    def duplicate_layer(
        self,
        index: int
    ) -> Layer | None:

        if index < 0:
            return None

        if index >= len(
            self.document.layers
        ):
            return None

        original: Layer = (
            self.document.layers[index]
        )
        original.commit_image_cache()
        original_group = self.document.group_for_layer(original.id)

        new_layer: Layer = (
            self.document.add_layer(
                f"{original.name} copie"
            )
        )
        if not new_layer.tile_store.copy_occupied_tiles_from(original.tile_store):
            self.document.layers.pop()
            new_layer.tile_store.close()
            return None
        if original.alpha_mask_store is not None:
            new_layer.ensure_alpha_mask()
            if not new_layer.alpha_mask_store.copy_occupied_tiles_from(original.alpha_mask_store):
                self.document.layers.pop()
                new_layer.tile_store.close()
                new_layer.alpha_mask_store.close()
                return None

        new_layer.visible = (
            original.visible
        )

        new_layer.opacity = (
            original.opacity
        )
        new_layer.blend_mode = original.blend_mode
        new_layer.blend_parameters = dict(original.blend_parameters)
        new_layer.locked = original.locked
        new_layer.lock_alpha = original.lock_alpha
        new_layer.clipping = original.clipping

        new_index = (
            len(self.document.layers) - 1
        )

        if new_index != index + 1:

            layer: Layer = (
                self.document.layers.pop(
                    new_index
                )
            )

            self.document.layers.insert(
                index + 1,
                layer
            )

        if original_group is not None:
            original_group.layer_ids.append(new_layer.id)
            original_group.layer_ids = [item.id for item in self.document.layers
                                        if item.id in original_group.layer_ids]
            original_group.invalidate()

        self.document.active_layer_index = (
            index + 1
        )
        self.document.sync_native_state()

        return new_layer

    def _move_layer_native(self, index: int, direction: int):
        layers = self.document.layers
        group_numbers = {group.id: number for number, group in enumerate(self.document.layer_groups)}
        memberships = []
        for layer in layers:
            group = self.document.group_for_layer(layer.id)
            memberships.append(group_numbers[group.id] if group is not None else -1)
        result = move_layer_stack(memberships, index, direction)
        if result is None:
            raise RuntimeError("CreativeCore is required to reorder layers")
        if result is False:
            return False
        order, active_after = result
        if not self.document._native_state.reorder_layers(order, active_after):
            raise RuntimeError("CreativeCore a refusé la réorganisation des calques")
        self.document.layers[:] = [layers[position] for position in order]
        self.document.active_layer_index = active_after
        for group in self.document.layer_groups:
            members = set(group.layer_ids)
            group.layer_ids = [layer.id for layer in self.document.layers
                               if layer.id in members]
            group.invalidate()
        self.document.sync_native_state()
        return True

    def move_layer_up(self, index: int) -> bool:
        return self._move_layer_native(index, 1)

    def move_layer_down(self, index: int) -> bool:
        return self._move_layer_native(index, -1)

    def toggle_visibility(
        self,
        index: int
    ) -> bool:

        if index < 0:
            return False

        if index >= len(
            self.document.layers
        ):
            return False

        layer: Layer = (
            self.document.layers[index]
        )

        updated = self.document._native_state.set_layer_property(
            index, 0, float(layer.visible))
        if updated is None:
            raise RuntimeError("CreativeCore a refusé la visibilité du calque")
        layer.visible = bool(updated)

        return layer.visible

    def set_opacity(
        self,
        index: int,
        opacity: float
    ) -> bool:

        if index < 0:
            return False

        if index >= len(
            self.document.layers
        ):
            return False

        current = self.document.layers[index].opacity
        if not math.isfinite(float(opacity)):
            return False
        updated = self.document._native_state.set_layer_property(index, 1, opacity)
        if updated is None:
            raise RuntimeError("CreativeCore a refusé l’opacité du calque")
        opacity = float(updated)

        self.document.layers[
            index
        ].opacity = opacity

        return True

    def get_active_layer(
        self
    ) -> Layer | None:

        index = (
            self.document.active_layer_index
        )

        if index < 0:
            return None

        if index >= len(
            self.document.layers
        ):
            return None

        return self.document.layers[
            index
        ]

    def merge_down(self, index: int) -> bool:
        if index <= 0 or index >= len(self.document.layers):
            return False
        upper, lower = self.document.layers[index], self.document.layers[index - 1]
        # A clipped lower layer takes its mask from a layer outside this pair.
        # Flattening only these two layers cannot preserve that dependency.
        if lower.clipping:
            return False
        group_indices = {group.id: number for number, group
                         in enumerate(self.document.layer_groups)}
        memberships = []
        for layer in self.document.layers:
            owned = [group_indices[group.id] for group in self.document.layer_groups
                     if layer.id in group.layer_ids]
            if len(owned) > 1:
                return False
            memberships.append(owned[0] if owned else -1)
        cleanup = plan_layer_group_cleanup(
            memberships, [int(position != index) for position in range(len(self.document.layers))],
            len(self.document.layer_groups))
        if cleanup is None:
            raise RuntimeError("CreativeCore is required to clean layer groups")
        if cleanup is False:
            return False
        # Flush only existing edit caches. From here on, the sparse TileStores
        # are authoritative; merge must not ask either Layer for `.image`.
        upper.commit_image_cache(release=True)
        lower.commit_image_cache(release=True)
        if (upper.clipping or upper.blend_parameters or lower.blend_parameters
                or upper.blend_mode in {"hue", "saturation", "color", "luminosity"}
                or lower.blend_mode in {"hue", "saturation", "color", "luminosity"}):
            # Parameterized blending can change the lower layer's own pixels,
            # so compose the union of occupied tiles against transparent local
            # tiles rather than materializing a full-canvas intermediate.
            writes = []
            for tx, ty in sorted(lower.tile_store.occupied_keys | upper.tile_store.occupied_keys):
                rect = lower.tile_store.tile_rect(tx, ty)
                bottom = lower.tile_store.tile(tx, ty)
                top = upper.tile_store.tile(tx, ty)
                rendered = composite_layers(rect.width(), rect.height(), [
                    SimpleNamespace(image=bottom, visible=lower.visible,
                        opacity=lower.opacity, blend_mode=lower.blend_mode,
                        blend_parameters=lower.blend_parameters, clipping=lower.clipping),
                    SimpleNamespace(image=top, visible=upper.visible,
                        opacity=upper.opacity, blend_mode=upper.blend_mode,
                        blend_parameters=upper.blend_parameters, clipping=upper.clipping),
                ])
                writes.append((tx, ty, rendered))
            if not lower.tile_store.set_tiles_batch(writes):
                return False
            lower.discard_image_cache()
            lower.opacity = 1.0
            lower.blend_mode = "normal"
            lower.blend_parameters = {}
        else:
            # For standard modes only source-occupied tiles can change. A
            # sparse batch keeps untouched receiver tiles resident/scratch as-is.
            writes = []
            for tx, ty in sorted(upper.tile_store.occupied_keys):
                rect = lower.tile_store.tile_rect(tx, ty)
                target = lower.tile_store.tile(tx, ty)
                source = upper.tile_store.tile(tx, ty)
                composited = composite_layer_in_place(
                    target, source, upper.opacity, upper.blend_mode
                )
                if composited is None or not composited:
                    raise RuntimeError("CreativeCore is required to merge layers")
                writes.append((tx, ty, target))
            if not lower.tile_store.set_tiles_batch(writes):
                return False
            lower.discard_image_cache()
        lower.name = f"{lower.name} + {upper.name}"
        del self.document.layers[index]
        self._apply_group_cleanup(cleanup)
        self.document.active_layer_index = index - 1
        self.document.sync_native_state()
        return True

    def _apply_group_cleanup(self, cleanup) -> None:
        """Apply a native structural group plan to the Qt model."""
        keep_groups, surviving_membership = cleanup
        survivors = self.document.layers
        groups = list(self.document.layer_groups)
        if len(surviving_membership) != len(survivors):
            raise RuntimeError("CreativeCore returned an invalid group cleanup")
        next_groups = []
        for group_index, group in enumerate(groups):
            if not keep_groups[group_index]:
                group.layer_ids = []
                group.invalidate()
                continue
            group.layer_ids = [layer.id for layer, membership
                               in zip(survivors, surviving_membership)
                               if membership == group_index]
            group.invalidate()
            if group.layer_ids:
                next_groups.append(group)
            else:
                group.layer_ids = []
                group.invalidate()
        self.document.layer_groups[:] = next_groups

    def merge_visible(self) -> bool:
        document = self.document
        group_indices = {group.id: index for index, group in enumerate(document.layer_groups)}
        layer_memberships = []
        for layer in document.layers:
            memberships = [group_indices[group.id] for group in document.layer_groups
                           if layer.id in group.layer_ids]
            if len(memberships) > 1:
                return False
            layer_memberships.append(memberships[0] if memberships else -1)
        plan = plan_visible_layer_merge_groups(
            [layer.visible for layer in document.layers], layer_memberships,
            [group.visible for group in document.layer_groups],
            document.active_layer_index)
        if plan is None:
            raise RuntimeError("CreativeCore is required to merge visible layers")
        if plan is False:
            return False
        effective_visibility, keep_mask, target_index, active_after = plan
        cleanup = plan_layer_group_cleanup(
            layer_memberships, keep_mask, len(document.layer_groups))
        if cleanup is None:
            raise RuntimeError("CreativeCore is required to clean layer groups")
        if cleanup is False:
            return False
        visible = [index for index, value in enumerate(effective_visibility) if value]

        for layer in document.layers:
            layer.commit_image_cache(release=True)
        target = document.layers[target_index]
        occupied = set().union(*(document.layers[index].tile_store.occupied_keys
                                 for index in visible))
        writes = []
        for tx, ty in sorted(occupied):
            rect = target.tile_store.tile_rect(tx, ty)
            rendered = composite_document_layers(document, rect)
            writes.append((tx, ty, rendered))
        if not target.tile_store.set_tiles_batch(writes):
            return False
        target.discard_image_cache()
        target.name = "Fusion des calques visibles"
        target.visible = True
        target.opacity = 1.0
        target.blend_mode = "normal"
        target.blend_parameters = {}
        target.lock_alpha = False
        target.clipping = False

        document.layers[:] = [layer for index, layer in enumerate(document.layers)
                              if keep_mask[index]]
        self._apply_group_cleanup(cleanup)

        document.active_layer_index = active_after
        document.sync_native_state()
        return True

    def flatten(self) -> bool:
        if not self.document.layers:
            return False
        image = composite_document(self.document)
        self.document.layers.clear()
        for group in self.document.layer_groups:
            group.invalidate()
        self.document.layer_groups.clear()
        layer = self.document.add_layer("Flattened Image")
        layer.image = image
        self.document.active_layer_index = 0
        self.document.sync_native_state()
        return True

    def toggle_lock(self, index: int) -> bool:
        if not (0 <= index < len(self.document.layers)):
            return False
        layer = self.document.layers[index]
        updated = self.document._native_state.set_layer_property(
            index, 2, float(layer.locked))
        if updated is None:
            raise RuntimeError("CreativeCore a refusé le verrouillage du calque")
        layer.locked = bool(updated)
        return self.document.layers[index].locked

    def toggle_lock_alpha(self, index: int) -> bool:
        if not (0 <= index < len(self.document.layers)):
            return False
        layer = self.document.layers[index]
        updated = self.document._native_state.set_layer_property(
            index, 3, float(layer.lock_alpha))
        if updated is None:
            raise RuntimeError("CreativeCore a refusé Alpha Lock")
        layer.lock_alpha = bool(updated)
        return self.document.layers[index].lock_alpha

    def toggle_clipping(self, index: int) -> bool:
        if not (0 <= index < len(self.document.layers)):
            return False
        layer = self.document.layers[index]
        updated = self.document._native_state.set_layer_property(
            index, 4, float(layer.clipping))
        if updated is None:
            raise RuntimeError("CreativeCore a refusé l’écrêtage du calque")
        layer.clipping = bool(updated)
        return layer.clipping
