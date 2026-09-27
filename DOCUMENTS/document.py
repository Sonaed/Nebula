from PySide6.QtGui import QColor

from DOCUMENTS.layer import Layer
from DOCUMENTS.selection import SelectionMask
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.layer_group import LayerGroup
from CORE.native_bridge import (create_native_document_state,
                                fill_image_native,
                                normalize_layer_group,
                                validate_document_geometry)
from DOCUMENTS.color_management import ColorProfile, SRGB
from uuid import uuid4


class Document:

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        dpi: int = 300,
        background_color: QColor | None = None,
    ):

        valid_geometry = validate_document_geometry(width, height, dpi)
        if valid_geometry is None:
            raise RuntimeError("CreativeCore is required to create documents")
        if not valid_geometry:
            raise ValueError("Dimensions ou résolution du document invalides")

        self._native_state = create_native_document_state(width, height, dpi)
        if self._native_state is None:
            raise RuntimeError("CreativeCore est requis pour le modèle document")

        self.width: int = width
        self.height: int = height
        self.dpi: int = dpi
        self.id: str = str(uuid4())
        self.name: str = "Sans titre"
        self.author: str = ""
        self.background_color: QColor | None = (
            background_color
        )
        self.color_profile: dict = {"name": "sRGB", "icc": ""}

        self.layers: list[Layer] = []
        self.layer_groups: list[LayerGroup] = []
        self.active_layer_index: int = -1
        # repair_layer_groups() is called once per frame from
        # Canvas._ensure_projection() for any document with groups. Its
        # O(groups^2 x depth) chain-walk plus per-group gap scan is cheap for
        # a handful of groups, but on a document with many folders it was
        # redone every frame even when nothing about the layer/group
        # structure had changed since the last call (the common case: the
        # user is painting or panning, not reordering folders). It's a pure
        # function of layer order + each group's (id, layer_ids, parent_id),
        # so memoizing on that signature is exact - any structural change
        # changes the signature and forces a real recompute.
        self._group_repair_cache: tuple | None = None
        self.selection = SelectionMask(width, height)
        self.reference_images: list[ReferenceImage] = []
        self.text_objects: list[EditableText] = []
        self.blend_presets: dict[str, dict] = {}

        self.add_layer(
            "Arrière-plan"
        )

        background: Layer | None = (
            self.get_active_layer()
        )

        if background is not None:

            if background_color is None:

                if not fill_image_native(background.image, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore a refusé le remplissage du document")
                background.mark_image_cache_dirty()

            else:

                if not fill_image_native(background.image, background_color):
                    raise RuntimeError("CreativeCore a refusé le remplissage du document")
                background.mark_image_cache_dirty()

    def add_layer(
        self,
        name: str = "Nouveau calque",
    ) -> Layer:

        layer_name = str(name).strip() or "Nouveau calque"
        native_index = self._native_state.add_layer(layer_name)
        if native_index is None:
            raise RuntimeError("CreativeCore a refusé la création du calque")
        layer = Layer(
            layer_name,
            self.width,
            self.height,
        )

        self.layers.append(
            layer
        )

        self.active_layer_index = (
            len(self.layers) - 1
        )

        return layer

    def add_adjustment_layer(self, kind: str, name: str | None = None, spec=None) -> Layer:
        """Create a serializable non-destructive adjustment layer."""
        layer = self.add_layer(name or str(kind).replace("_", " ").title())
        layer.layer_kind = "adjustment"
        layer.adjustment = spec if spec is not None else {"kind": str(kind)}
        layer.visible = True
        return layer

    def set_color_profile(self, profile: ColorProfile = SRGB) -> None:
        """Set the document's embedded ICC profile metadata."""
        self.color_profile = {"name": str(profile.name),
                              "icc": bytes(profile.icc_bytes).hex()}

    def group_layers(self, indices, name: str = "Groupe") -> LayerGroup | None:
        requested = [int(index) for index in indices]
        requested_members = [self.layers[index].id for index in sorted(set(requested))
                             if 0 <= index < len(self.layers)]
        wrapping = next((candidate for candidate in self.layer_groups
                         if candidate.parent_id is None
                         and candidate.layer_ids == requested_members), None)
        grouped = [any(layer.id in group.layer_ids for group in self.layer_groups
                       if group.parent_id is None)
                   for layer in self.layers]
        selected = (sorted(set(requested)) if wrapping is not None
                    else normalize_layer_group(requested, grouped))
        if selected is None:
            raise RuntimeError("CreativeCore is required to validate layer groups")
        if selected is False:
            return None
        group_name = str(name).strip() or "Groupe"
        if self._native_state.create_group(selected, group_name) is None:
            raise RuntimeError("CreativeCore a refusé la création du groupe")
        members = [self.layers[index].id for index in selected]
        # CreativeCore accepts an exact root-group selection as a wrapping
        # operation.  Keep the Qt mirror hierarchical as well.
        child = wrapping
        group = LayerGroup(name=group_name, layer_ids=members)
        self.layer_groups.append(group)
        if child is not None:
            child.parent_id = group.id
            child.invalidate()
        return group

    def ungroup_layers(self, group_id: str) -> bool:
        for index, group in enumerate(self.layer_groups):
            if group.id == group_id:
                if not self._native_state.remove_group(index):
                    raise RuntimeError("CreativeCore a refusé la suppression du groupe")
                group.invalidate()
                del self.layer_groups[index]
                for child in self.layer_groups:
                    if child.parent_id == group_id:
                        child.parent_id = None
                        child.invalidate()
                return True
        return False

    def groups_containing(self, layer_id: str) -> list[LayerGroup]:
        """Every group listing the layer: its direct group and all ancestors."""
        return [group for group in self.layer_groups if layer_id in group.layer_ids]

    def _group_structure_signature(self) -> tuple:
        return (
            tuple(layer.id for layer in self.layers),
            tuple((group.id, tuple(group.layer_ids), group.parent_id)
                 for group in self.layer_groups),
        )

    def repair_layer_groups(self) -> bool:
        """Restore the invariants the compositor relies on; return True if anything changed.

        Each group must list existing layers that form one contiguous run of the
        stack.  A gap is filled when the layers inside it belong to no unrelated
        group (a layer inserted in the middle of a group belongs to it); otherwise
        the group keeps its longest contiguous run.  Empty groups are dropped and a
        dangling parent reference is cleared.
        """
        signature = self._group_structure_signature()
        if self._group_repair_cache is not None and self._group_repair_cache[0] == signature:
            return self._group_repair_cache[1]
        changed = False
        by_id = {group.id: group for group in self.layer_groups}
        for group in self.layer_groups:
            if group.parent_id is not None and (group.parent_id not in by_id
                                                or group.parent_id == group.id):
                group.parent_id = None
                changed = True

        def chain(group):
            seen, cursor = set(), group
            while cursor is not None and cursor.id not in seen:
                seen.add(cursor.id)
                cursor = by_id.get(cursor.parent_id)
            return seen

        related = {group.id: chain(group) for group in self.layer_groups}
        for group in self.layer_groups:
            related[group.id] |= {other.id for other in self.layer_groups
                                  if group.id in chain(other)}
        positions = {layer.id: index for index, layer in enumerate(self.layers)}
        for group in sorted(self.layer_groups, key=lambda item: len(item.layer_ids)):
            known = [layer_id for layer_id in group.layer_ids if layer_id in positions]
            if len(known) != len(group.layer_ids):
                changed = True
            indices = sorted({positions[layer_id] for layer_id in known})
            if not indices:
                group.layer_ids = []
                continue
            if indices == list(range(indices[0], indices[-1] + 1)):
                ordered = [self.layers[index].id for index in indices]
                if ordered != group.layer_ids:
                    group.layer_ids = ordered
                    changed = True
                continue
            gap = [self.layers[index].id for index in range(indices[0], indices[-1] + 1)
                   if index not in indices]
            foreign = any(other.id not in related[group.id]
                          for layer_id in gap
                          for other in self.layer_groups
                          if layer_id in other.layer_ids)
            if not foreign:
                group.layer_ids = [self.layers[index].id
                                   for index in range(indices[0], indices[-1] + 1)]
            else:
                runs, current = [], [indices[0]]
                for index in indices[1:]:
                    if index == current[-1] + 1:
                        current.append(index)
                    else:
                        runs.append(current)
                        current = [index]
                runs.append(current)
                best = max(runs, key=len)
                group.layer_ids = [self.layers[index].id for index in best]
            group.invalidate()
            changed = True
        for index in range(len(self.layer_groups) - 1, -1, -1):
            if not self.layer_groups[index].layer_ids:
                removed = self.layer_groups[index]
                try:
                    self._native_state.remove_group(index)
                except Exception:
                    pass
                for child in self.layer_groups:
                    if child.parent_id == removed.id:
                        child.parent_id = removed.parent_id
                del self.layer_groups[index]
                changed = True
        self._group_repair_cache = (self._group_structure_signature(), changed)
        return changed

    def move_layer_to_group(self, layer_id: str, group_id: str | None) -> bool:
        """Move one layer into ``group_id`` (or out of every group with ``None``).

        A nested group also lists its leaves, so the layer joins the target group
        and all of its ancestors, and leaves every other group.  Groups left
        empty are removed.  The caller must already have placed the layer inside
        the target group's block of the stack (reorder first).
        """
        by_id = {group.id: group for group in self.layer_groups}
        if group_id is not None and group_id not in by_id:
            return False
        keep: set[str] = set()
        cursor = group_id
        while cursor is not None and cursor in by_id and cursor not in keep:
            keep.add(cursor)
            cursor = by_id[cursor].parent_id
        changed = False
        for group in self.layer_groups:
            member = layer_id in group.layer_ids
            if group.id in keep and not member:
                group.layer_ids.append(layer_id)
                changed = True
            elif group.id not in keep and member:
                group.layer_ids.remove(layer_id)
                changed = True
            else:
                continue
            group.layer_ids = [layer.id for layer in self.layers if layer.id in group.layer_ids]
            group.invalidate()
        for index in range(len(self.layer_groups) - 1, -1, -1):
            if not self.layer_groups[index].layer_ids:
                removed = self.layer_groups[index]
                # Le miroir natif des groupes n'est qu'indicatif : un refus n'est pas fatal.
                try:
                    self._native_state.remove_group(index)
                except Exception:
                    pass
                for child in self.layer_groups:
                    if child.parent_id == removed.id:
                        child.parent_id = removed.parent_id
                del self.layer_groups[index]
                changed = True
        return changed

    def set_group_visibility(self, group_id: str, visible: bool) -> bool:
        for index, group in enumerate(self.layer_groups):
            if group.id == group_id:
                result = self._native_state.set_group_property(
                    index, 0, float(bool(visible)))
                if result is None:
                    raise RuntimeError("CreativeCore a refusé la visibilité du groupe")
                group.visible = bool(result)
                group.invalidate()
                return True
        return False

    def set_group_opacity(self, group_id: str, opacity: float) -> bool:
        for index, group in enumerate(self.layer_groups):
            if group.id == group_id:
                result = self._native_state.set_group_property(index, 1, float(opacity))
                if result is None:
                    raise RuntimeError("CreativeCore a refusé l’opacité du groupe")
                group.opacity = float(result)
                group.invalidate()
                return True
        return False

    def group_for_layer(self, layer_id: str) -> LayerGroup | None:
        return next((group for group in self.layer_groups if layer_id in group.layer_ids), None)

    def has_layer_groups(self) -> bool:
        return bool(self.layer_groups)

    def get_active_layer(
        self
    ) -> Layer | None:

        if self.active_layer_index < 0:
            return None

        if self.active_layer_index >= len(
            self.layers
        ):
            return None

        return self.layers[
            self.active_layer_index
        ]

    def set_active_layer(
        self,
        index: int,
    ) -> None:

        if 0 <= index < len(
            self.layers
        ):
            if not self._native_state.select_layer(index):
                raise RuntimeError("CreativeCore a refusé la sélection du calque")
            self.active_layer_index = index

    def sync_native_state(self) -> None:
        """Rebuild the native structural mirror after a full state restore."""
        self._native_state.reset_layers()
        for layer in self.layers:
            index = self._native_state.add_layer(layer.name)
            if index is None:
                raise RuntimeError("CreativeCore a refusé la restauration des calques")
            for property_id, value in (
                (0, float(bool(layer.visible))), (1, float(layer.opacity)),
                (2, float(bool(layer.locked))), (3, float(bool(layer.lock_alpha))),
                (4, float(bool(layer.clipping))),
            ):
                if property_id == 0 and not layer.visible:
                    result = self._native_state.set_layer_property(index, property_id, value)
                elif property_id == 1 and value != 1.0:
                    result = self._native_state.set_layer_property(index, property_id, value)
                elif property_id in (2, 3, 4) and value:
                    result = self._native_state.set_layer_property(index, property_id, value)
                else:
                    continue
                if result is None:
                    raise RuntimeError("CreativeCore a refusé la restauration d’une propriété")
        if self.layers:
            if not self._native_state.select_layer(
                    min(self.active_layer_index, len(self.layers) - 1)):
                raise RuntimeError("CreativeCore a refusé la restauration du calque actif")
        self._native_state.reset_groups()
        for group in self.layer_groups:
            indices = [index for index, layer in enumerate(self.layers)
                       if layer.id in group.layer_ids]
            native_index = self._native_state.create_group(indices, group.name)
            if native_index is None:
                raise RuntimeError("CreativeCore a refusé la restauration des groupes")
            if not group.visible:
                if self._native_state.set_group_property(native_index, 0, 0.0) is None:
                    raise RuntimeError("CreativeCore a refusé la visibilité du groupe")
            if group.opacity != 1.0:
                if self._native_state.set_group_property(native_index, 1, group.opacity) is None:
                    raise RuntimeError("CreativeCore a refusé l’opacité du groupe")

    def __del__(self):
        try:
            native_state = getattr(self, "_native_state", None)
            if native_state is not None:
                native_state.close()
        except Exception:
            pass
