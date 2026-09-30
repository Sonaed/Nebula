from __future__ import annotations

"""Advanced blend controls kept separate from the everyday Layers dock."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from DOCUMENTS.blend_presets import BlendPresetManager
from DOCUMENTS.blend_graph import NODE_TYPES, default_graph, validate_graph
from existence.module_adapter import ExistenceModuleAdapter
from UI.widgets.blend_preview import BlendPreviewWidget
from UI.widgets.numeric_slider import NumericSlider
from UI.theme.palette import COLORS


class BlendCreatorDock(QDockWidget):
    """Preset and parameter editor for the blend mode of the active layer."""

    parameter_changed = Signal(str, float)
    parameter_edit_started = Signal()
    parameter_edit_ended = Signal()
    preset_applied = Signal(object)
    resources_changed = Signal()
    graph_changed = Signal(object)

    def __init__(self, parent=None, resource_manager=None) -> None:
        super().__init__("CRÉATEUR DE FUSION", parent)
        self.setObjectName("BlendCreatorDock")
        self.existence_module = ExistenceModuleAdapter("fusion_creator")
        self.setProperty("existenceModuleId", self.existence_module.module_id)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(250)
        self.setMaximumWidth(360)
        self._document = None
        self._editing = False
        self.graph = default_graph()
        blend_root = getattr(resource_manager, "root", None)
        self.blend_preset_manager = BlendPresetManager(Path(blend_root) / "blends" if blend_root else None)
        self._build()
        self._refresh_presets()
        self._refresh_graph()

    def _build(self) -> None:
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        self.setWidget(content)

        title = QLabel("RÉGLAGES AVANCÉS")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self.layer_name = QLabel("Sélectionnez un calque")
        self.layer_name.setObjectName("blendCreatorLayer")
        layout.addWidget(self.layer_name)

        self.parameters_widget = QWidget()
        self.parameters_layout = QVBoxLayout(self.parameters_widget)
        self.parameters_layout.setContentsMargins(0, 2, 0, 2)
        self.parameters_layout.setSpacing(0)
        self.parameter_scroll = QScrollArea()
        self.parameter_scroll.setWidgetResizable(True)
        self.parameter_scroll.setMinimumHeight(190)
        self.parameter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.parameter_scroll.setWidget(self.parameters_widget)
        layout.addWidget(self.parameter_scroll)
        self.parameter_controls: dict[str, NumericSlider] = {}

        self.preview = BlendPreviewWidget(self)
        self.preview.setFixedSize(160, 160)
        self.preview.setToolTip("Aperçu du mode et des réglages de fusion")
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        graph_title = QLabel("GRAPHE DE TRAITEMENT")
        graph_title.setObjectName("panelTitle")
        layout.addWidget(graph_title)
        self.graph_list = QListWidget()
        self.graph_list.setMinimumHeight(110)
        self.graph_list.setToolTip("Entrées, analyses, transformations, opérations et sortie")
        layout.addWidget(self.graph_list)
        graph_actions = QHBoxLayout()
        self.graph_node_combo = QComboBox()
        self.graph_node_combo.addItems(NODE_TYPES)
        graph_actions.addWidget(self.graph_node_combo, 1)
        add_node = QPushButton("+")
        add_node.setToolTip("Ajouter un nœud")
        add_node.clicked.connect(self.add_graph_node)
        graph_actions.addWidget(add_node)
        remove_node = QPushButton("−")
        remove_node.setToolTip("Supprimer le nœud sélectionné")
        remove_node.clicked.connect(self.remove_graph_node)
        graph_actions.addWidget(remove_node)
        layout.addLayout(graph_actions)
        self.graph_status = QLabel()
        self.graph_status.setWordWrap(True)
        layout.addWidget(self.graph_status)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("separator")
        layout.addWidget(separator)
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.setIconSize(QSize(48, 24))
        preset_row.addWidget(self.preset_combo, 1)
        apply_button = QPushButton("Appliquer")
        apply_button.clicked.connect(self.apply_preset)
        preset_row.addWidget(apply_button)
        layout.addLayout(preset_row)
        actions = QHBoxLayout()
        copy_button = QPushButton("Copier")
        copy_button.clicked.connect(self.duplicate_preset)
        self.save_button = QPushButton("Enregistrer")
        self.save_button.clicked.connect(self.save_preset)
        import_button = QPushButton("Importer")
        import_button.clicked.connect(self.import_preset)
        export_button = QPushButton("Exporter")
        export_button.clicked.connect(self.export_preset)
        for button in (copy_button, self.save_button, import_button, export_button):
            actions.addWidget(button)
        layout.addLayout(actions)

    @property
    def _active_layer(self):
        return self._document.get_active_layer() if self._document is not None else None

    def set_layer(self, document) -> None:
        self._document = document
        layer = self._active_layer
        if layer is None:
            self.layer_name.setText("Sélectionnez un calque")
            return
        self.layer_name.setText(f"Calque actif : {layer.name}")
        values = dict(layer.blend_parameters)
        # Opacity remains a direct layer property in the Layers dock.
        values.pop("opacity", None)
        self._rebuild_parameters(layer.blend_mode, values)
        self.graph = getattr(layer, "blend_graph", None) or default_graph(layer.blend_mode)
        self._refresh_graph()
        self.preview.set_mode(layer.blend_mode)
        self.preview.set_parameters(layer.blend_mode, values)
        # The preview images are only needed while the dock is shown; building
        # them materialized every layer below the active one at full size
        # (seconds on large documents) on every layer-panel refresh.
        self._preview_dirty = True
        if self.isVisible():
            self._update_preview_images()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if getattr(self, "_preview_dirty", False):
            self._update_preview_images()

    @staticmethod
    def _draw_store(painter, store, size: int) -> None:
        """Draw a sparse tile store scaled into a size×size square (no full image)."""
        width, height = max(1, store.width), max(1, store.height)
        scale_x, scale_y = size / width, size / height
        for tx, ty in store.occupied_keys:
            rect = store.tile_rect(tx, ty)
            try:
                tile = store.tile(tx, ty)
            except OSError:
                continue
            painter.drawImage(QRectF(rect.x() * scale_x, rect.y() * scale_y,
                                     rect.width() * scale_x, rect.height() * scale_y), tile)

    def _update_preview_images(self) -> None:
        document = self._document
        layer = self._active_layer
        if document is None or layer is None:
            return
        self._preview_dirty = False
        backdrop = QImage(QSize(256, 256), QImage.Format.Format_ARGB32_Premultiplied)
        backdrop.fill(QColor(48, 48, 48))
        painter = QPainter(backdrop)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for y in range(0, 256, 16):
            for x in range(0, 256, 16):
                if (x // 16 + y // 16) % 2:
                    painter.fillRect(x, y, 16, 16, QColor(64, 64, 64))
        for below in document.layers[:document.active_layer_index]:
            if below.visible and getattr(below, "layer_kind", "raster") == "raster":
                painter.setOpacity(max(0.0, min(1.0, float(below.opacity))))
                self._draw_store(painter, below.tile_store, 256)
        painter.end()
        top = QImage(QSize(256, 256), QImage.Format.Format_ARGB32_Premultiplied)
        top.fill(QColor(0, 0, 0, 0))
        painter = QPainter(top)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw_store(painter, layer.tile_store, 256)
        painter.end()
        self.preview.set_images(backdrop, top)

    def _rebuild_parameters(self, mode: str, values: dict) -> None:
        specs = [spec for spec in BlendPresetManager.parameter_specs(mode) if spec[0] != "opacity"]
        keys = [spec[0] for spec in specs]
        if (getattr(self, "_parameter_mode", None) == mode
                and list(self.parameter_controls) == keys):
            # Same mode (the usual case on a layer-panel refresh): update the
            # values in place instead of destroying and recreating widgets.
            for key, _label, _minimum, _maximum, _step, default in specs:
                control = self.parameter_controls[key]
                control.blockSignals(True)
                try:
                    control.setValue(float(values.get(key, default)))
                finally:
                    control.blockSignals(False)
            return
        self._parameter_mode = mode
        while self.parameters_layout.count():
            item = self.parameters_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach synchronously: deleteLater() on these Python-owned
                # sliders crashed shiboken (free(): invalid size) when a
                # refresh rebuilt them repeatedly.
                widget.hide()
                widget.setParent(None)
        self.parameter_controls.clear()
        for key, label, minimum, maximum, step, default in BlendPresetManager.parameter_specs(mode):
            if key == "opacity":
                continue
            control = NumericSlider(label, minimum, maximum, float(values.get(key, default)), step, default=default)
            control.setFixedHeight(48)
            control.valueChanged.connect(lambda value, parameter=key: self._emit_parameter(parameter, value))
            control.slider.sliderPressed.connect(self._begin_edit)
            control.slider.sliderReleased.connect(self._finish_edit)
            control.spin.editingFinished.connect(self._finish_edit)
            self.parameters_layout.addWidget(control)
            self.parameter_controls[key] = control

    def _emit_parameter(self, key: str, value: float) -> None:
        self._begin_edit()
        self.parameter_changed.emit(key, value)
        self.preview.set_parameter(key, value)

    def _begin_edit(self) -> None:
        if not self._editing:
            self._editing = True
            self.parameter_edit_started.emit()

    def _finish_edit(self) -> None:
        if self._editing:
            self._editing = False
            self.parameter_edit_ended.emit()

    def _refresh_presets(self, selected: str | None = None) -> None:
        current = selected or self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for name in self.blend_preset_manager.list_presets():
            pixmap = QPixmap()
            preview = self.blend_preset_manager.preview_png(name)
            if preview:
                pixmap.loadFromData(preview, "PNG")
            self.preset_combo.addItem(QIcon(pixmap), name)
        if current:
            self.preset_combo.setCurrentText(current)
        self.preset_combo.blockSignals(False)
        self.save_button.setEnabled(not self.blend_preset_manager.is_builtin(self.preset_combo.currentText()))

    def _refresh_graph(self) -> None:
        self.graph_list.blockSignals(True)
        self.graph_list.clear()
        for node in self.graph.get("nodes", []):
            label = f"{node.get('type', '?')} · {node.get('id', '?')}"
            if node.get("type") == "Blend":
                label += f" · {node.get('mode', 'normal')} · {node.get('channel', 'RGB')}"
            self.graph_list.addItem(label)
        self.graph_list.blockSignals(False)
        errors = validate_graph(self.graph)
        self.graph_status.setText(
            "Graphe valide · modes CreativeCore" if not errors
            else "Graphe invalide : " + "; ".join(errors[:2])
        )
        self.graph_status.setStyleSheet(
            f"color: {COLORS['label_green']};" if not errors
            else f"color: {COLORS['label_orange']};"
        )

    def add_graph_node(self) -> None:
        node_type = self.graph_node_combo.currentText()
        base = node_type.lower()
        existing = {node.get("id") for node in self.graph.get("nodes", [])}
        node_id, index = base, 2
        while node_id in existing:
            node_id, index = f"{base}_{index}", index + 1
        node = {"id": node_id, "type": node_type}
        if node_type == "Blend":
            node.update({"mode": "normal", "channel": "RGB",
                         "contribution": {"type": "constant", "value": 1.0}})
        nodes = self.graph.setdefault("nodes", [])
        output = next((item for item in nodes if item.get("type") == "Output"), None)
        if output is not None:
            output_index = nodes.index(output)
            predecessor = nodes[output_index - 1] if output_index else None
            nodes.insert(output_index, node)
            if predecessor:
                for edge in self.graph["edges"]:
                    if edge.get("to") == output["id"] and edge.get("from") == predecessor["id"]:
                        edge["to"] = node_id
                        break
                self.graph["edges"].append({"from": node_id, "to": output["id"]})
        else:
            nodes.append(node)
        self._refresh_graph()
        self.graph_changed.emit(self.graph)

    def remove_graph_node(self) -> None:
        item = self.graph_list.currentItem()
        if item is None:
            return
        node_id = item.text().split(" · ", 1)[-1].split(" · ", 1)[0]
        node = next((node for node in self.graph.get("nodes", []) if node.get("id") == node_id), None)
        if node is None or node.get("type") in {"Input", "Output"}:
            return
        self.graph["nodes"] = [node for node in self.graph["nodes"] if node.get("id") != node_id]
        self.graph["edges"] = [edge for edge in self.graph.get("edges", [])
                                if edge.get("from") != node_id and edge.get("to") != node_id]
        self._refresh_graph()
        self.graph_changed.emit(self.graph)

    def apply_preset(self) -> None:
        preset = self.blend_preset_manager.load(self.preset_combo.currentText())
        if preset is not None:
            self.graph = preset.get("graph") or default_graph(preset.get("mode", "normal"))
            self._refresh_graph()
            self.preset_applied.emit(preset)

    def duplicate_preset(self) -> None:
        source = self.preset_combo.currentText()
        name, accepted = QInputDialog.getText(self, "Copier le preset", "Nom", text=f"{source} Copy")
        if accepted and name.strip() and self.blend_preset_manager.duplicate(source, name.strip()):
            self._refresh_presets(name.strip())
            self.resources_changed.emit()

    def save_preset(self) -> None:
        layer = self._active_layer
        name = self.preset_combo.currentText()
        if layer is None or self.blend_preset_manager.is_builtin(name):
            return
        params = dict(layer.blend_parameters)
        params["opacity"] = float(layer.opacity)
        if self.blend_preset_manager.save(name, {"mode": layer.blend_mode,
                                                 "parameters": params,
                                                 "graph": self.graph}):
            self._refresh_presets(name)
            self.resources_changed.emit()

    def import_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un preset", "", "CreativeSystem Blend (*.csbl)")
        if path:
            name = self.blend_preset_manager.import_csbl(path)
            if name:
                self._refresh_presets(name)
                self.resources_changed.emit()
            else:
                QMessageBox.warning(self, "Preset de fusion", "Le fichier .csbl est invalide ou non pris en charge.")

    def export_preset(self) -> None:
        name = self.preset_combo.currentText()
        path, _ = QFileDialog.getSaveFileName(self, "Exporter un preset", f"{name}.csbl", "CreativeSystem Blend (*.csbl)")
        if path:
            if not path.lower().endswith(".csbl"):
                path += ".csbl"
            if not self.blend_preset_manager.export_csbl(name, path):
                QMessageBox.warning(self, "Preset de fusion", "Export impossible.")
