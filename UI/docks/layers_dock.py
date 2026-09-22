from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLayout,
    QPushButton,
    QLabel,
    QSlider,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QScrollArea,
    QAbstractItemView,
)

from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage, QPainter

from DOCUMENTS.document import Document
from DOCUMENTS.blend_presets import BlendPresetManager
from UI.widgets.layer_delegate import LayerItemDelegate
from UI.widgets.numeric_slider import NumericSlider
from UI.widgets.blend_preview import BlendPreviewWidget


class LayersDock(QDockWidget):

    blend_mode_changed = Signal(str)
    blend_parameter_changed = Signal(str, float)
    blend_parameter_edit_started = Signal()
    blend_parameter_edit_ended = Signal()
    blend_preset_applied = Signal(object)
    lock_requested = Signal()
    lock_alpha_requested = Signal()
    group_selected_requested = Signal()
    ungroup_selected_requested = Signal()
    group_visibility_requested = Signal()
    add_mask_requested = Signal()
    remove_mask_requested = Signal()

    def __init__(
        self,
        window
    ) -> None:

        super().__init__(
            "CALQUES",
            window
        )

        self.area = (
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._blend_parameter_edit_active = False

        self.setObjectName(
            "LayersDock"
        )

        self.setMinimumWidth(
            250
        )

        self.setMaximumWidth(
            360
        )

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.create_content()
        self.create_style()

    def create_content(self) -> None:

        content = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            10,
            10,
            10,
            10
        )

        layout.setSpacing(
            7
        )

        content.setLayout(
            layout
        )

        self.setWidget(
            content
        )

        # =====================================================
        # EN-TÊTE
        # =====================================================

        header = QHBoxLayout()

        title = QLabel(
            "CALQUES"
        )

        title.setObjectName(
            "panelTitle"
        )

        header.addWidget(
            title
        )

        header.addStretch()

        self.layer_count = QLabel(
            "1"
        )

        self.layer_count.setObjectName(
            "layerCount"
        )

        header.addWidget(
            self.layer_count
        )

        layout.addLayout(
            header
        )

        # =====================================================
        # LISTE
        # =====================================================

        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layer_list.setItemDelegate(LayerItemDelegate(self.layer_list))
        self.layer_list.setMouseTracking(True)
        self.layer_list.setSpacing(1)

        layout.addWidget(
            self.layer_list,
            1
        )

        # =====================================================
        # ACTIONS
        # =====================================================

        actions_row = QHBoxLayout()

        self.add_layer_button = QPushButton(
            "+"
        )

        self.add_layer_button.setToolTip(
            "Nouveau calque"
        )

        self.duplicate_layer_button = QPushButton(
            "Dupliquer"
        )

        actions_row.addWidget(
            self.add_layer_button
        )

        actions_row.addWidget(
            self.duplicate_layer_button
        )

        layout.addLayout(
            actions_row
        )

        self.rename_layer_button = QPushButton(
            "Renommer"
        )

        self.visibility_button = QPushButton(
            "Afficher / Masquer"
        )

        layout.addWidget(
            self.rename_layer_button
        )

        layout.addWidget(
            self.visibility_button
        )

        # =====================================================
        # ORDRE
        # =====================================================

        order_row = QHBoxLayout()

        self.move_up_button = QPushButton(
            "↑"
        )

        self.move_up_button.setToolTip(
            "Monter"
        )

        self.move_down_button = QPushButton(
            "↓"
        )

        self.move_down_button.setToolTip(
            "Descendre"
        )

        order_row.addWidget(
            self.move_up_button
        )

        order_row.addWidget(
            self.move_down_button
        )

        layout.addLayout(
            order_row
        )

        group_row = QHBoxLayout()
        self.group_layers_button = QPushButton("Grouper")
        self.ungroup_layers_button = QPushButton("Dégrouper")
        self.group_visibility_button = QPushButton("Visibilité groupe")
        self.group_layers_button.clicked.connect(self.group_selected_requested)
        self.ungroup_layers_button.clicked.connect(self.ungroup_selected_requested)
        group_row.addWidget(self.group_layers_button)
        group_row.addWidget(self.ungroup_layers_button)
        group_row.addWidget(self.group_visibility_button)
        self.group_visibility_button.clicked.connect(self.group_visibility_requested)
        layout.addLayout(group_row)

        group_opacity_row = QHBoxLayout()
        self.group_opacity_label = QLabel("Opacité groupe")
        self.group_opacity_slider = QSlider(Qt.Orientation.Horizontal, content)
        self.group_opacity_slider.setRange(0, 100)
        self.group_opacity_slider.setValue(100)
        group_opacity_row.addWidget(self.group_opacity_label)
        group_opacity_row.addWidget(self.group_opacity_slider, 1)
        layout.addLayout(group_opacity_row)

        mask_row = QHBoxLayout()
        self.add_mask_button = QPushButton("+ Masque")
        self.remove_mask_button = QPushButton("− Masque")
        self.add_mask_button.setToolTip("Ajouter un masque alpha éditable au calque actif")
        self.remove_mask_button.setToolTip("Supprimer le masque alpha du calque actif")
        self.add_mask_button.clicked.connect(self.add_mask_requested)
        self.remove_mask_button.clicked.connect(self.remove_mask_requested)
        mask_row.addWidget(self.add_mask_button)
        mask_row.addWidget(self.remove_mask_button)
        layout.addLayout(mask_row)

        self.remove_layer_button = QPushButton(
            "Supprimer"
        )

        layout.addWidget(
            self.remove_layer_button
        )

        # =====================================================
        # OPACITÉ
        # =====================================================

        separator = QFrame()

        separator.setFrameShape(
            QFrame.Shape.HLine
        )

        separator.setObjectName(
            "separator"
        )

        layout.addWidget(
            separator
        )

        self.layer_opacity_value = QLabel("100 %", content)
        self.layer_opacity_slider = QSlider(
            Qt.Orientation.Horizontal, content
        )

        self.layer_opacity_slider.setRange(
            0,
            100
        )

        self.layer_opacity_slider.setValue(
            100
        )

        # Kept hidden for compatibility with the legacy application bridge;
        # the visible opacity control now lives with the blend parameters.
        self.layer_opacity_value.hide()
        self.layer_opacity_slider.hide()

        blend_header = QHBoxLayout()
        blend_header.addWidget(QLabel("MODE DE FUSION"))
        self.blend_mode_combo = QComboBox()
        self.blend_mode_combo.addItems([
            "Normal", "Darken", "Multiply", "Color Burn", "Lighten", "Screen",
            "Color Dodge", "Overlay", "Soft Light", "Hard Light", "Difference",
            "Exclusion", "Hue", "Saturation", "Color", "Luminosity",
        ])
        self.blend_mode_combo.currentIndexChanged.connect(
            lambda index: self.blend_mode_changed.emit(self.blend_mode_combo.itemText(index).lower().replace(" ", "_"))
        )
        blend_header.addWidget(self.blend_mode_combo, 1)
        layout.addLayout(blend_header)
        self.blend_preset_manager = BlendPresetManager()
        self._document: Document | None = None
        self.blend_parameters_widget = QWidget()
        self.blend_parameters_layout = QVBoxLayout(self.blend_parameters_widget)
        self.blend_parameters_layout.setContentsMargins(0, 2, 0, 2)
        self.blend_parameters_layout.setSpacing(0)
        self.blend_parameter_scroll = QScrollArea()
        self.blend_parameter_scroll.setWidgetResizable(True)
        self.blend_parameter_scroll.setMinimumHeight(260)
        self.blend_parameter_scroll.setMaximumHeight(272)
        self.blend_parameter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.blend_parameter_scroll.setWidget(self.blend_parameters_widget)
        layout.addWidget(self.blend_parameter_scroll)
        self.blend_parameter_controls: dict[str, NumericSlider] = {}
        self.blend_preview = BlendPreviewWidget(self)
        # Keep the panel compact; the offscreen render target remains 256².
        self.blend_preview.setFixedSize(160, 160)
        self.blend_preview.setToolTip("Aperçu OpenGL du mode de fusion sélectionné")
        layout.addWidget(self.blend_preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preset_row = QHBoxLayout()
        self.blend_preset_combo = QComboBox()
        self.blend_preset_combo.setIconSize(QSize(48, 24))
        preset_row.addWidget(self.blend_preset_combo, 1)
        self.blend_preset_apply = QPushButton("Apply")
        self.blend_preset_apply.clicked.connect(self.apply_blend_preset)
        preset_row.addWidget(self.blend_preset_apply)
        layout.addLayout(preset_row)
        preset_actions = QHBoxLayout()
        self.blend_preset_copy = QPushButton("New Copy")
        self.blend_preset_copy.clicked.connect(self.duplicate_blend_preset)
        self.blend_preset_save = QPushButton("Save")
        self.blend_preset_save.clicked.connect(self.save_blend_preset)
        self.blend_preset_import = QPushButton("Import")
        self.blend_preset_import.clicked.connect(self.import_blend_preset)
        self.blend_preset_export = QPushButton("Export")
        self.blend_preset_export.clicked.connect(self.export_blend_preset)
        for button in (self.blend_preset_copy, self.blend_preset_save,
                       self.blend_preset_import, self.blend_preset_export):
            preset_actions.addWidget(button)
        layout.addLayout(preset_actions)
        self._refresh_blend_presets()
        locks = QHBoxLayout()
        self.lock_button = QPushButton("Lock")
        self.lock_alpha_button = QPushButton("Alpha")
        self.lock_button.clicked.connect(self.lock_requested)
        self.lock_alpha_button.clicked.connect(self.lock_alpha_requested)
        locks.addWidget(self.lock_button); locks.addWidget(self.lock_alpha_button)
        layout.addLayout(locks)

    # =========================================================
    # STYLE
    # =========================================================

    def create_style(self) -> None:

        self.setStyleSheet(
            """
            QDockWidget {
                color: #e8edf7;
            }

            QDockWidget::title {
                background-color: #101727;
                color: #a0adc3;
                padding: 8px 11px;
                border: 1px solid #26344d;
                border-bottom: 0;
                font-size: 10px;
                font-weight: 700;
            }

            QDockWidget > QWidget {
                background-color: #101727;
                border: 1px solid #26344d;
            }

            QWidget {
                color: #e8edf7;
                font-size: 12px;
            }

            QLabel#panelTitle {
                color: #8997b0;
                font-size: 9px;
                font-weight: 700;
            }

            QLabel#valueLabel {
                color: #a0adc3;
                font-size: 10px;
            }

            QLabel#layerCount {
                color: #68758c;
                font-size: 10px;
            }

            QPushButton {
                background-color: #1c2940;
                color: #e8edf7;
                border: 1px solid #26344d;
                border-radius: 5px;
                padding: 7px 9px;
                min-height: 18px;
            }

            QPushButton:hover {
                background-color: #253550;
                border-color: #7868d8;
            }

            QPushButton:pressed {
                background-color: #151f32;
            }

            QListWidget {
                background-color: #0c1321;
                color: #d8e0ef;
                border: 1px solid #202e46;
                border-radius: 6px;
                outline: none;
                padding: 4px;
            }

            QListWidget::item {
                padding: 10px 8px;
                margin: 1px 0;
                border-radius: 4px;
            }

            QListWidget::item:hover {
                background-color: #1c2940;
            }

            QListWidget::item:selected {
                background-color: #332f59;
                color: #ffffff;
            }

            QSlider::groove:horizontal {
                height: 4px;
                background: #1c2940;
                border-radius: 2px;
            }

            QSlider::handle:horizontal {
                width: 11px;
                height: 11px;
                margin: -4px 0;
                background: #c5cce0;
                border-radius: 6px;
            }

            QSlider::handle:horizontal:hover {
                background: #62c5d7;
            }

            QFrame#separator {
                background-color: #26344d;
                max-height: 1px;
            }
            """
        )

    # =========================================================
    # UTILITAIRE
    # =========================================================

    def add_separator(
        self,
        layout: QLayout
    ) -> None:

        separator = QFrame()

        separator.setObjectName(
            "separator"
        )

        separator.setFrameShape(
            QFrame.Shape.HLine
        )

        separator.setFixedHeight(
            1
        )

        layout.addWidget(
            separator
        )

    # =========================================================
    # CALQUES
    # =========================================================

    def refresh_layers(
        self,
        document: Document
    ) -> None:

        self._document = document

        self.layer_list.blockSignals(
            True
        )

        self.layer_list.clear()

        for index in range(
            len(document.layers) - 1,
            -1,
            -1
        ):

            layer = document.layers[
                index
            ]

            group = document.group_for_layer(layer.id)
            if group is None:
                display_name = layer.name
            elif group.layer_ids and layer.id == group.layer_ids[-1]:
                display_name = f"▾ {group.name}  ·  {layer.name}"
            else:
                display_name = f"    {layer.name}"
            item = QListWidgetItem(display_name)

            item.setData(
                Qt.ItemDataRole.UserRole,
                index
            )
            item.setData(Qt.ItemDataRole.UserRole + 1, layer.visible)
            item.setData(Qt.ItemDataRole.UserRole + 2, {
                "locked": layer.locked,
                "lock_alpha": layer.lock_alpha,
                "clipping": layer.clipping,
            })
            item.setData(
                Qt.ItemDataRole.DecorationRole,
                layer.image.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation),
            )

            self.layer_list.addItem(
                item
            )

        self.layer_count.setText(
            str(
                len(document.layers)
            )
        )

        active_index = (
            document.active_layer_index
        )

        for row in range(
            self.layer_list.count()
        ):

            item = self.layer_list.item(
                row
            )

            if item.data(
                Qt.ItemDataRole.UserRole
            ) == active_index:

                self.layer_list.setCurrentRow(
                    row
                )

                break

        self.layer_list.blockSignals(
            False
        )

        self.update_layer_opacity(
            document
        )
        self.update_layer_properties(document)

    def get_selected_layer_index(
        self
    ) -> int:

        row = self.layer_list.currentRow()

        if row < 0:
            return -1

        item = self.layer_list.item(
            row
        )

        index = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not isinstance(
            index,
            int
        ):

            return -1

        return index

    def get_selected_layer_indices(self) -> list[int]:
        return sorted({int(item.data(Qt.ItemDataRole.UserRole))
                       for item in self.layer_list.selectedItems()
                       if isinstance(item.data(Qt.ItemDataRole.UserRole), int)})

    def update_layer_opacity(
        self,
        document: Document
    ) -> None:

        index = (
            document.active_layer_index
        )

        if index < 0:
            return

        if index >= len(
            document.layers
        ):

            return

        opacity = int(
            document.layers[index].opacity * 100
        )

        self.layer_opacity_slider.blockSignals(
            True
        )

        self.layer_opacity_slider.setValue(
            opacity
        )

        self.layer_opacity_slider.blockSignals(
            False
        )

        self.layer_opacity_value.setText(
            f"{opacity} %"
        )
        opacity_control = self.blend_parameter_controls.get("opacity")
        if opacity_control is not None:
            opacity_control.setValue(opacity / 100.0)

    def set_layer_opacity_value(
        self,
        value: int
    ) -> None:

        self.layer_opacity_value.setText(
            f"{value} %"
        )
        opacity_control = self.blend_parameter_controls.get("opacity")
        if opacity_control is not None:
            opacity_control.setValue(value / 100.0)
        self.blend_preview.set_parameter("opacity", value / 100.0)

    def update_layer_properties(self, document: Document) -> None:
        layer = document.get_active_layer()
        if layer is None:
            return
        group = document.group_for_layer(layer.id)
        self.group_opacity_label.setEnabled(group is not None)
        self.group_opacity_slider.setEnabled(group is not None)
        self.group_visibility_button.setEnabled(group is not None)
        self.group_visibility_button.setText(
            "Masquer groupe" if group is not None and group.visible else "Afficher groupe"
        )
        blocked_group = self.group_opacity_slider.blockSignals(True)
        self.group_opacity_slider.setValue(round(group.opacity * 100) if group is not None else 100)
        self.group_opacity_slider.blockSignals(blocked_group)
        blocked = self.blend_mode_combo.blockSignals(True)
        index = {
            "normal": 0, "darken": 1, "multiply": 2, "color_burn": 3,
            "lighten": 4, "screen": 5, "color_dodge": 6, "overlay": 7,
            "soft_light": 8, "hard_light": 9, "difference": 10,
            "exclusion": 11, "hue": 12, "saturation": 13, "color": 14,
            "luminosity": 15,
        }.get(layer.blend_mode, 0)
        self.blend_mode_combo.setCurrentIndex(index)
        self.blend_mode_combo.blockSignals(blocked)
        slider_values = dict(layer.blend_parameters)
        slider_values["opacity"] = layer.opacity
        self._rebuild_blend_parameters(layer.blend_mode, slider_values)
        self.blend_preview.set_mode(layer.blend_mode)
        preview_size = QSize(256, 256)
        backdrop = QImage(preview_size, QImage.Format.Format_ARGB32_Premultiplied)
        backdrop.fill(QColor(48, 48, 48))
        painter = QPainter(backdrop)
        target = QRectF(0, 0, 256, 256)
        for y in range(0, 256, 16):
            for x in range(0, 256, 16):
                if (x // 16 + y // 16) % 2:
                    painter.fillRect(x, y, 16, 16, QColor(64, 64, 64))
        for below in document.layers[:document.active_layer_index]:
            if below.visible:
                painter.setOpacity(max(0.0, min(1.0, float(below.opacity))))
                painter.drawImage(target, below.image)
        painter.end()
        self.blend_preview.set_images(backdrop, layer.image)
        self.blend_preview.set_parameters(layer.blend_mode, slider_values)
        self.lock_button.setText("Unlock" if layer.locked else "Lock")
        self.lock_alpha_button.setText("Alpha ✓" if layer.lock_alpha else "Alpha")

    def _rebuild_blend_parameters(self, mode: str, values: dict) -> None:
        while self.blend_parameters_layout.count():
            item = self.blend_parameters_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.blend_parameter_controls.clear()
        self.blend_preset_save.setEnabled(
            not self.blend_preset_manager.is_builtin(self.blend_preset_combo.currentText())
        )
        for key, label, minimum, maximum, step, default in BlendPresetManager.parameter_specs(mode):
            control = NumericSlider(
                label, minimum, maximum,
                float(values.get(key, default)), step,
                default=default,
            )
            control.setFixedHeight(48)
            control.valueChanged.connect(
                lambda value, parameter=key: self._emit_blend_parameter_change(parameter, value)
            )
            control.slider.sliderPressed.connect(self._begin_blend_parameter_edit)
            control.slider.sliderReleased.connect(self._finish_blend_parameter_edit)
            control.spin.editingFinished.connect(self._finish_blend_parameter_edit)
            self.blend_parameters_layout.addWidget(control)
            self.blend_parameter_controls[key] = control

    def _emit_blend_parameter_change(self, key: str, value: float) -> None:
        self._begin_blend_parameter_edit()
        self.blend_parameter_changed.emit(key, value)

    def _begin_blend_parameter_edit(self) -> None:
        if not self._blend_parameter_edit_active:
            self._blend_parameter_edit_active = True
            self.blend_parameter_edit_started.emit()

    def _finish_blend_parameter_edit(self) -> None:
        if self._blend_parameter_edit_active:
            self._blend_parameter_edit_active = False
            self.blend_parameter_edit_ended.emit()

    def set_blend_parameter_values(self, values: dict) -> None:
        for key, control in self.blend_parameter_controls.items():
            if key in values:
                control.setValue(float(values[key]))

    def apply_blend_preset(self) -> None:
        preset = self.blend_preset_manager.load(self.blend_preset_combo.currentText())
        if preset is not None:
            self.blend_preset_applied.emit(preset)

    def duplicate_blend_preset(self) -> None:
        source = self.blend_preset_combo.currentText()
        name, accepted = QInputDialog.getText(self, "New blend preset", "Name", text=f"{source} Copy")
        if not accepted or not name.strip():
            return
        if self.blend_preset_manager.duplicate(source, name.strip()):
            self._refresh_blend_presets(name.strip())

    def save_blend_preset(self) -> None:
        name = self.blend_preset_combo.currentText()
        layer = self._active_layer
        if layer is None or self.blend_preset_manager.is_builtin(name):
            return
        params = BlendPresetManager.default_parameters(layer.blend_mode)
        params["opacity"] = layer.opacity
        params.update({key: value for key, value in layer.blend_parameters.items() if key in params})
        params["opacity"] = float(layer.opacity)
        if self.blend_preset_manager.save(name, {"mode": layer.blend_mode, "parameters": params}):
            self._refresh_blend_presets(name)

    @property
    def _active_layer(self):
        return self._document.get_active_layer() if self._document is not None else None

    def _refresh_blend_presets(self, selected: str | None = None) -> None:
        current = selected or self.blend_preset_combo.currentText()
        self.blend_preset_combo.blockSignals(True)
        self.blend_preset_combo.clear()
        for preset_name in self.blend_preset_manager.list_presets():
            pixmap = QPixmap()
            preview = self.blend_preset_manager.preview_png(preset_name)
            if preview:
                pixmap.loadFromData(preview, "PNG")
            self.blend_preset_combo.addItem(QIcon(pixmap), preset_name)
        if current:
            self.blend_preset_combo.setCurrentText(current)
        self.blend_preset_combo.blockSignals(False)
        self.blend_preset_save.setEnabled(not self.blend_preset_manager.is_builtin(current))

    def import_blend_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Blend Preset", "", "CreativeSystem Blend (*.csbl)")
        if path:
            name = self.blend_preset_manager.import_csbl(path)
            if name:
                self._refresh_blend_presets(name)
            else:
                QMessageBox.warning(self, "Blend Preset", "The .csbl file is invalid or unsupported.")

    def export_blend_preset(self) -> None:
        name = self.blend_preset_combo.currentText()
        path, _ = QFileDialog.getSaveFileName(self, "Export Blend Preset", f"{name}.csbl", "CreativeSystem Blend (*.csbl)")
        if path:
            if not path.lower().endswith(".csbl"):
                path += ".csbl"
            if not self.blend_preset_manager.export_csbl(name, path):
                QMessageBox.warning(self, "Blend Preset", "Could not export this preset.")
