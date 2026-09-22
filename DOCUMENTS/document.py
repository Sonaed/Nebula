from PySide6.QtGui import QColor

from DOCUMENTS.layer import Layer
from DOCUMENTS.selection import SelectionMask
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.layer_group import LayerGroup
from CORE.native_bridge import (create_native_document_state,
                                fill_image_native,
                                normalize_layer_group,
                                validate_document_geometry)


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
        self.name: str = "Sans titre"
        self.author: str = ""
        self.background_color: QColor | None = (
            background_color
        )

        self.layers: list[Layer] = []
        self.layer_groups: list[LayerGroup] = []
        self.active_layer_index: int = -1
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

            else:

                if not fill_image_native(background.image, background_color):
                    raise RuntimeError("CreativeCore a refusé le remplissage du document")

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
