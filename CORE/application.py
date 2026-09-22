from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QColorDialog,
    QFileDialog,
    QMessageBox,
    QInputDialog,
)

from PySide6.QtGui import (
    QImage,
    QColor,
)
from PySide6.QtCore import Qt, QSettings, QTimer

from CANVAS.canvas import Canvas

from UI.ui import CreativeSystemUI

from DOCUMENTS.layer_manager import LayerManager

from DOCUMENTS.document_manager import DocumentManager

from DOCUMENTS.format_nebula import NebulaFormat, load_document

from DOCUMENTS.document_dialog import DocumentDialog

from DOCUMENTS.document import Document
from DOCUMENTS.blend_modes import composite_document
from UI.qt_blend_modes import composition_mode
from DOCUMENTS.recovery import RecoveryManager
from CORE.memory_manager import MemoryManager
from CORE.native_bridge import fill_image_native, plan_visible_layer_merge


class CreativeSystem(QMainWindow):

    def closeEvent(
        self,
        event
    ) -> None:

        canvas = getattr(
            self,
            "canvas",
            None
        )

        ui = getattr(self, "ui", None)
        if ui is not None and hasattr(ui, "workspace_manager"):
            ui.workspace_manager.save_session()

        if canvas is not None:
            canvas.cleanup_gl_resources()
            canvas._destroy_cpp_brush()
        memory_manager = getattr(self, "memory_manager", None)
        if memory_manager is not None:
            memory_manager.shutdown()

        super().closeEvent(
            event
        )


    def __init__(
        self
    ) -> None:

        super().__init__()

        # CreativeSystem is an opaque desktop window. Explicitly disabling
        # translucency prevents the compositor from exposing applications
        # below it if an OpenGL child momentarily carries fractional alpha.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)

        # =====================================================
        # FENÊTRE
        # =====================================================

        self.setWindowTitle(
            "CreativeSystem Nebula — Nouveau dessin"
        )

        self.resize(
            1400,
            850
        )

        # =====================================================
        # DOCUMENTS
        # =====================================================

        self.document_manager = (
            DocumentManager()
        )

        # =====================================================
        # CANVAS
        # =====================================================

        self.canvas = Canvas()

        self.document_manager.documents.append(
            self.canvas.document
        )

        self.document_manager.active_document = (
            self.canvas.document
        )

        # =====================================================
        # CALQUES
        # =====================================================

        self.layer_manager = LayerManager(
            self.canvas.document
        )

        # =====================================================
        # FICHIER COURANT
        # =====================================================

        self.current_file = None
        self._last_saved_history_index = self.canvas.tile_history.index

        # =====================================================
        # UI
        # =====================================================

        self.ui = CreativeSystemUI(
            self,
            self.canvas
        )

        self.memory_manager = MemoryManager(
            self.canvas,
            self.statusBar(),
            self,
        )

        self.connect_ui()

        self.refresh_layers()

        self.update_window_title()

        self.recovery_manager = RecoveryManager()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_recovery)
        self._configure_autosave()
        self._offer_recovery()

    def _configure_autosave(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        if not settings.value("autosave/enabled", True, bool):
            self._autosave_timer.stop()
            return
        interval = max(1, min(120, settings.value("autosave/interval_minutes", 5, int)))
        self._autosave_timer.start(interval * 60 * 1000)

    def _autosave_recovery(self) -> None:
        if self.canvas is None:
            return
        history = self.canvas.tile_history
        # Do not clear a previous recovery snapshot or serialize a half-finished
        # stroke/transform while the transaction is still open. The next timer
        # tick will save the committed state once its history index advances.
        if history._pending is not None:
            return
        current_index = history.index
        if current_index == self._last_saved_history_index:
            self.recovery_manager.clear()
            return
        if current_index <= 0 and self.current_file is None:
            self.recovery_manager.clear()
            return
        if self.recovery_manager.save(self.canvas.document):
            self._last_saved_history_index = current_index

    def _offer_recovery(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        if not settings.value("autosave/enabled", True, bool) or not self.recovery_manager.path.is_file():
            return
        answer = QMessageBox.question(
            self, "Session recovery",
            "A recovered document is available. Restore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            document = self.recovery_manager.load()
            if document is not None:
                self.canvas.set_document(document)
                self.layer_manager = LayerManager(document)
                self.document_manager.documents.append(document)
                self.document_manager.active_document = document
                self.current_file = None
                self._last_saved_history_index = -1
                self.refresh_layers()
                self.update_window_title()
                self.ui.show_workspace()
                return
        self.recovery_manager.clear()

    # =========================================================
    # CONNEXIONS UI
    # =========================================================

    def connect_ui(
        self
    ) -> None:

        # -----------------------------------------------------
        # HOME PAGE
        # -----------------------------------------------------

        self.ui.home_new_requested.connect(
            self.new_file
        )

        self.ui.home_open_requested.connect(
            self.open_file
        )

        # -----------------------------------------------------
        # FICHIER
        # -----------------------------------------------------

        self.ui.new_button.clicked.connect(
            self.new_file
        )

        self.ui.open_button.clicked.connect(
            self.open_file
        )

        self.ui.save_button.clicked.connect(
            self.save_file
        )

        self.ui.save_as_button.clicked.connect(
            self.save_file_as
        )

        self.ui.actions["new"].triggered.connect(
            self.new_file
        )

        self.ui.actions["open"].triggered.connect(
            self.open_file
        )

        self.ui.actions["import_reference"].triggered.connect(
            self.import_reference_image
        )

        self.ui.actions["save"].triggered.connect(
            self.save_file
        )

        self.ui.actions["save_as"].triggered.connect(
            self.save_file_as
        )

        self.ui.actions["close"].triggered.connect(
            self.close_document
        )

        self.ui.actions["exit"].triggered.connect(
            self.close
        )

        # -----------------------------------------------------
        # OUTILS
        # -----------------------------------------------------

        self.ui.brush_button.clicked.connect(
            self.canvas.tools.set_brush
        )

        self.ui.eraser_button.clicked.connect(
            self.canvas.tools.set_eraser
        )

        self.ui.picker_button.clicked.connect(
            self.canvas.tools.set_picker
        )

        self.ui.smudge_button.clicked.connect(
            self.canvas.tools.set_smudge
        )

        self.ui.undo_button.clicked.connect(
            self.canvas.undo
        )

        self.ui.redo_button.clicked.connect(
            self.canvas.redo
        )

        self.ui.actions["undo"].triggered.connect(
            self.canvas.undo
        )

        self.ui.actions["redo"].triggered.connect(
            self.canvas.redo
        )

        self.ui.actions["brush"].triggered.connect(
            self.canvas.tools.set_brush
        )

        self.ui.actions["eraser"].triggered.connect(
            self.canvas.tools.set_eraser
        )

        self.ui.actions["picker"].triggered.connect(
            self.canvas.tools.set_picker
        )

        self.ui.actions["smudge"].triggered.connect(
            self.canvas.tools.set_smudge
        )
        self.ui.actions["clone_stamp"].triggered.connect(
            self.canvas.tools.set_clone_stamp
        )
        self.ui.actions["reference"].triggered.connect(self.canvas.tools.set_reference)
        self.ui.actions["text"].triggered.connect(self.canvas.tools.set_text)
        self.ui.actions["blur"].triggered.connect(self.canvas.tools.set_blur)
        self.ui.actions["sharpen"].triggered.connect(self.canvas.tools.set_sharpen)
        self.ui.actions["bezier"].triggered.connect(self.canvas.tools.set_bezier)

        for action_name, callback in (
            ("fill", self.canvas.tools.set_fill),
            ("gradient", self.canvas.tools.set_gradient),
            ("line", self.canvas.tools.set_line),
            ("rectangle", self.canvas.tools.set_rectangle),
            ("ellipse", self.canvas.tools.set_ellipse),
            ("crop", self.canvas.tools.set_crop),
        ):
            self.ui.actions[action_name].triggered.connect(callback)

        self.ui.actions["select_all"].triggered.connect(self.select_all)
        self.ui.actions["deselect"].triggered.connect(self.deselect)
        self.ui.actions["invert_selection"].triggered.connect(self.invert_selection)

        self.ui.actions["show_brush"].triggered.connect(
            self.ui.brush_panel_dock.setVisible
        )

        # -----------------------------------------------------
        # IMAGE
        # -----------------------------------------------------

        self.ui.actions["export"].triggered.connect(
            self.export_image
        )

        # -----------------------------------------------------
        # COULEUR
        # -----------------------------------------------------

        self.ui.color_button.clicked.connect(
            self.choose_color
        )

        self.canvas.color_sampled.connect(
            lambda color: self.ui.set_color(color.name())
        )

        # -----------------------------------------------------
        # BROSSE
        # -----------------------------------------------------

        self.ui.size_slider.valueChanged.connect(
            self.change_brush_size
        )

        self.ui.opacity_slider.valueChanged.connect(
            self.change_brush_opacity
        )

        self.ui.pressure_size_slider.valueChanged.connect(
            self.change_pressure_size
        )

        self.ui.pressure_opacity_slider.valueChanged.connect(
            self.change_pressure_opacity
        )

        self.ui.spacing_slider.valueChanged.connect(
            self.change_spacing
        )

        # -----------------------------------------------------
        # CALQUES
        # -----------------------------------------------------

        self.ui.layer_list.currentRowChanged.connect(
            self.select_layer
        )

        self.ui.visibility_button.clicked.connect(
            self.toggle_layer_visibility
        )

        self.ui.add_layer_button.clicked.connect(
            self.add_layer
        )

        self.ui.duplicate_layer_button.clicked.connect(
            self.duplicate_layer
        )

        self.ui.rename_layer_button.clicked.connect(
            self.rename_layer
        )

        self.ui.remove_layer_button.clicked.connect(
            self.remove_layer
        )

        self.ui.move_up_button.clicked.connect(
            self.move_layer_up
        )

        self.ui.move_down_button.clicked.connect(
            self.move_layer_down
        )

        self.ui.layer_opacity_slider.valueChanged.connect(
            self.change_layer_opacity
        )
        self.ui.layer_opacity_slider.sliderPressed.connect(self._begin_layer_property_history)
        self.ui.layer_opacity_slider.sliderReleased.connect(self._commit_layer_property_history)
        self.ui.layer_opacity_slider.actionTriggered.connect(self._layer_opacity_action)
        self.ui.layers_dock.lock_requested.connect(self.toggle_layer_lock)
        self.ui.layers_dock.lock_alpha_requested.connect(self.toggle_layer_alpha_lock)
        self.ui.layers_dock.add_mask_requested.connect(self.add_active_layer_mask)
        self.ui.layers_dock.remove_mask_requested.connect(self.remove_active_layer_mask)
        self.ui.layers_dock.group_selected_requested.connect(self.group_selected_layers)
        self.ui.layers_dock.ungroup_selected_requested.connect(self.ungroup_selected_layers)
        self.ui.layers_dock.group_visibility_requested.connect(self.toggle_active_group_visibility)
        self.ui.layers_dock.group_opacity_slider.valueChanged.connect(self.change_active_group_opacity)
        self.ui.layers_dock.group_opacity_slider.sliderPressed.connect(self._begin_group_opacity_history)
        self.ui.layers_dock.group_opacity_slider.sliderReleased.connect(self._commit_group_opacity_history)
        self.ui.layers_dock.group_opacity_slider.actionTriggered.connect(self._group_opacity_action)

        # -----------------------------------------------------
        # MENUS CALQUES
        # -----------------------------------------------------

        self.ui.actions["add_layer"].triggered.connect(
            self.add_layer
        )

        self.ui.actions["duplicate_layer"].triggered.connect(
            self.duplicate_layer
        )

        self.ui.actions["rename_layer"].triggered.connect(
            self.rename_layer
        )

        self.ui.actions["toggle_visibility"].triggered.connect(
            self.toggle_layer_visibility
        )

        self.ui.actions["move_layer_up"].triggered.connect(
            self.move_layer_up
        )

        self.ui.actions["move_layer_down"].triggered.connect(
            self.move_layer_down
        )

        self.ui.actions["remove_layer"].triggered.connect(
            self.remove_layer
        )
        self.ui.actions["rotate_90"].triggered.connect(lambda: self.canvas.rotate_active(90.0))
        self.ui.actions["flip_horizontal"].triggered.connect(self.canvas.flip_active_horizontal)
        self.ui.actions["flip_vertical"].triggered.connect(self.canvas.flip_active_vertical)
        self.ui.actions["zoom_100"].triggered.connect(self.canvas.zoom_100)
        self.ui.actions["fit_canvas"].triggered.connect(self.reset_view)
        self.ui.actions["rotate_canvas"].triggered.connect(lambda: self.canvas.rotate_canvas(15.0))
        self.ui.actions["reset_canvas_rotation"].triggered.connect(self.canvas.reset_canvas_rotation)
        self.ui.actions["flip_canvas_horizontal"].triggered.connect(self.canvas.flip_canvas_view_horizontal)
        self.ui.actions["flip_canvas_vertical"].triggered.connect(self.canvas.flip_canvas_view_vertical)
        self.ui.actions["canvas_only"].triggered.connect(self.toggle_canvas_only)
        self.ui.actions["symmetry_horizontal"].triggered.connect(self.canvas.toggle_horizontal_symmetry)
        self.ui.actions["symmetry_vertical"].triggered.connect(self.canvas.toggle_vertical_symmetry)
        self.ui.actions["hand"].triggered.connect(self.canvas.tools.set_hand)
        self.ui.actions["zoom_view"].triggered.connect(self.canvas.tools.set_zoom_view)
        self.ui.actions["rotate_view"].triggered.connect(self.canvas.tools.set_rotate_view)
        self.ui.actions["assistant_ruler"].triggered.connect(
            lambda checked: self.set_drawing_assistant("ruler", checked)
        )
        self.ui.actions["assistant_ellipse"].triggered.connect(
            lambda checked: self.set_drawing_assistant("ellipse", checked)
        )
        self.ui.actions["assistant_perspective"].triggered.connect(
            lambda checked: self.set_drawing_assistant("perspective", checked)
        )
        self.canvas.canvas_only_changed.connect(
            lambda checked: self._sync_checkable_action("canvas_only", checked)
        )
        self.canvas.view_flip_changed.connect(self._sync_view_flip_actions)
        self.canvas.symmetry_changed.connect(self._sync_symmetry_actions)
        self.ui.actions["merge_down"].triggered.connect(self.merge_down)
        self.ui.actions["merge_visible"].triggered.connect(self.merge_visible)
        self.ui.actions["flatten"].triggered.connect(self.flatten_image)
        self.ui.actions["lock_layer"].triggered.connect(self.toggle_layer_lock)
        self.ui.actions["lock_alpha"].triggered.connect(self.toggle_layer_alpha_lock)

        # -----------------------------------------------------
        # AFFICHAGE
        # -----------------------------------------------------

        self.ui.actions["reset_view"].triggered.connect(
            self.reset_view
        )

        # -----------------------------------------------------
        # FENÊTRE
        # -----------------------------------------------------

        self.ui.actions[
            "show_tools_window"
        ].triggered.connect(
            self.toggle_tools_panel
        )

        self.ui.actions[
            "show_layers_window"
        ].triggered.connect(
            self.toggle_layers_panel
        )


    def select_all(self) -> None:
        self._with_selection_history(self.canvas.document.selection.select_all)
        self.canvas.update()

    def merge_down(self) -> None:
        index = self.canvas.document.active_layer_index
        document = self.canvas.document

        def prepare(history):
            if not (0 < index < len(document.layers)):
                return
            upper, lower = document.layers[index], document.layers[index - 1]
            upper.commit_image_cache()
            lower.commit_image_cache()
            upper_keys = upper.tile_store.occupied_keys
            history.capture_layer_before(upper, upper_keys)
            history.capture_layer_before(lower, lower.tile_store.occupied_keys | upper_keys)

        changed = self._with_layer_history(
            lambda: self.layer_manager.merge_down(index),
            structure_only=True, prepare=prepare,
        )
        if changed:
            self.refresh_layers(); self.canvas.prune_gpu_layers(); self.canvas.sync_gpu_layer()

    def merge_visible(self) -> None:
        document = self.canvas.document

        def prepare(history):
            working = list(document.layers)
            for layer in working:
                layer.commit_image_cache()
            membership = {layer_id: group for group in document.layer_groups
                          for layer_id in group.layer_ids}
            effective_visibility = [
                bool(layer.visible and (membership.get(layer.id) is None
                                        or membership[layer.id].visible))
                for layer in working
            ]
            plan = plan_visible_layer_merge(effective_visibility,
                                            document.active_layer_index)
            if plan is False:
                return
            visible = [layer for layer, is_visible
                       in zip(working, effective_visibility) if is_visible]
            merged_keys = set().union(*(layer.tile_store.occupied_keys for layer in visible))
            target = visible[0]
            history.capture_layer_before(target, merged_keys | target.tile_store.occupied_keys)
            for layer in visible[1:]:
                history.capture_layer_before(layer, layer.tile_store.occupied_keys)

        changed = self._with_layer_history(self.layer_manager.merge_visible,
                                           structure_only=True, prepare=prepare)
        if changed:
            self.refresh_layers(); self.canvas.prune_gpu_layers(); self.canvas.sync_gpu_layer()

    def flatten_image(self) -> None:
        document = self.canvas.document

        def prepare(history):
            for layer in document.layers:
                history.capture_layer_before(layer)

        changed = self._with_layer_history(self.layer_manager.flatten,
                                           structure_only=True, prepare=prepare)
        if changed:
            self.refresh_layers(); self.canvas.prune_gpu_layers(); self.canvas.sync_gpu_layer()

    def toggle_layer_lock(self) -> None:
        index = self.canvas.document.active_layer_index
        valid = 0 <= index < len(self.canvas.document.layers)
        if self._with_layer_history(lambda: self.layer_manager.toggle_lock(index),
                                    changed=valid, dirty_only=True):
            self.refresh_layers()

    def toggle_layer_alpha_lock(self) -> None:
        index = self.canvas.document.active_layer_index
        valid = 0 <= index < len(self.canvas.document.layers)
        if self._with_layer_history(lambda: self.layer_manager.toggle_lock_alpha(index),
                                    changed=valid, dirty_only=True):
            self.refresh_layers()

    def deselect(self) -> None:
        self._with_selection_history(self.canvas.document.selection.clear)
        self.canvas.update()

    def invert_selection(self) -> None:
        self._with_selection_history(self.canvas.document.selection.invert)
        self.canvas.update()

    def _with_selection_history(self, operation) -> None:
        """Record selection-only edits without snapshotting every paint layer."""
        history = self.canvas.tile_history
        owns_transaction = history._pending is None
        if owns_transaction:
            self.canvas.begin_selection_history_action()
        try:
            operation()
        except Exception:
            if owns_transaction:
                self.canvas.cancel_history_action()
            raise
        if owns_transaction:
            self.canvas.commit_history_action()

    # =========================================================
    # NOUVEAU DOCUMENT
    # =========================================================

    def new_file(
        self
    ) -> None:

        dialog = DocumentDialog(
            self
        )

        if not dialog.exec():
            return

        width, height = (
            dialog.get_dimensions()
        )

        dpi = (
            dialog.get_dpi()
        )

        background = (
            dialog.get_background()
        )

        background_color: QColor | None = None

        if background == "white":

            background_color = QColor(
                255,
                255,
                255
            )

        elif background == "black":

            background_color = QColor(
                0,
                0,
                0
            )

        document = Document(
            width,
            height,
            dpi,
            background_color
        )

        self.canvas.set_document(
            document
        )

        self.layer_manager = LayerManager(
            document
        )

        self.document_manager.documents.append(
            document
        )

        self.document_manager.active_document = (
            document
        )

        self.current_file = None
        self._last_saved_history_index = self.canvas.tile_history.index

        self.refresh_layers()

        self.update_window_title()

        # -----------------------------------------------------
        # PASSAGE HOME → WORKSPACE
        # -----------------------------------------------------

        self.ui.show_workspace()

    # =========================================================
    # OUVERTURE
    # =========================================================

    def import_reference_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Importer une image de référence", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
        )
        if file_path:
            self.canvas.add_reference_image(file_path)

    def open_file(
        self
    ) -> None:

        preferences = QSettings("CreativeSystem", "CreativeSystem")
        start_directory = preferences.value("files/last_directory", "", str)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir un document",
            start_directory,
            "Nebula document (*.nebula *.nbl);;"
            "Legacy projects (*.csd *.atlas);;"
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )

        if not file_path:
            return

        self._remember_file_directory(file_path)

        extension = (
            Path(file_path)
            .suffix
            .lower()
        )

        # -----------------------------------------------------
        # CSD
        # -----------------------------------------------------

        if extension in (".nebula", ".nbl", ".csd", ".atlas"):

            document = load_document(file_path)

            if document is None:

                QMessageBox.warning(
                    self,
                    "Erreur",
                    "Impossible d’ouvrir ce document Nebula, CSD ou Atlas."
                )

                return

            self.canvas.set_document(
                document
            )

            self.layer_manager = LayerManager(
                document
            )

            self.document_manager.documents.append(
                document
            )

            self.document_manager.active_document = (
                document
            )

            self.current_file = file_path
            self._last_saved_history_index = self.canvas.tile_history.index

            self.refresh_layers()

            self.update_window_title()

            # -------------------------------------------------
            # PASSAGE HOME → WORKSPACE
            # -------------------------------------------------

            self.ui.show_workspace()

            return

        # -----------------------------------------------------
        # IMAGE
        # -----------------------------------------------------

        if self.canvas.load_image(
            file_path
        ):

            self.current_file = file_path
            self._last_saved_history_index = self.canvas.tile_history.index

            self.layer_manager = LayerManager(
                self.canvas.document
            )

            self.document_manager.documents.append(
                self.canvas.document
            )

            self.document_manager.active_document = (
                self.canvas.document
            )

            self.refresh_layers()

            self.update_window_title()

            # -------------------------------------------------
            # PASSAGE HOME → WORKSPACE
            # -------------------------------------------------

            self.ui.show_workspace()

            return

        QMessageBox.warning(
            self,
            "Erreur",
            "Impossible d'ouvrir cette image."
        )

    # =========================================================
    # FERMER LE DOCUMENT
    # =========================================================

    def close_document(
        self
    ) -> None:

        result = QMessageBox.question(
            self,
            "Fermer le document",
            "Voulez-vous enregistrer le document avant de le fermer ?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save
        )

        if result == QMessageBox.StandardButton.Cancel:
            return

        if result == QMessageBox.StandardButton.Save:
            self.save_file()
            return

        self.current_file = None
        self.ui.show_home()
        self.update_window_title()

    # =========================================================
    # IMAGE COMPOSITE
    # =========================================================

    def create_composite_image(
        self
    ) -> QImage:

        document = self.canvas.document

        image = QImage(
            document.width,
            document.height,
            QImage.Format.Format_ARGB32
        )

        if not fill_image_native(image, QColor(0, 0, 0, 0)):
            raise RuntimeError("CreativeCore a refusé la préparation de l’export")

        return composite_document(document)

    # =========================================================
    # EXPORT IMAGE
    # =========================================================

    def export_image(
        self
    ) -> None:

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter l'image",
            "",
            "PNG (*.png);;"
            "JPEG (*.jpg *.jpeg);;"
            "BMP (*.bmp)"
        )

        if not file_path:
            return

        image = (
            self.create_composite_image()
        )

        if not image.save(
            file_path
        ):

            QMessageBox.warning(
                self,
                "Erreur",
                "Impossible d'exporter l'image."
            )

    # =========================================================
    # SAUVEGARDE
    # =========================================================

    def save_file(
        self
    ) -> None:

        if self.current_file is None:

            self.save_file_as()

            return

        extension = (
            Path(self.current_file)
            .suffix
            .lower()
        )

        if extension in (".nebula", ".nbl"):

            success = NebulaFormat.save(
                self.canvas.document,
                self.current_file
            )

        elif extension in (".csd", ".atlas"):
            # Legacy sources are read-only: Save must never overwrite their format.
            self.save_file_as()
            return

        else:

            image = (
                self.create_composite_image()
            )

            success = image.save(
                self.current_file
            )

        if not success:

            QMessageBox.warning(
                self,
                "Erreur",
                "Impossible d'enregistrer le fichier."
            )
        elif extension in (".nebula", ".nbl"):
            self.recovery_manager.clear()
            self._last_saved_history_index = self.canvas.tile_history.index

    def save_file_as(
        self
    ) -> None:

        preferences = QSettings("CreativeSystem", "CreativeSystem")
        start_directory = preferences.value("files/last_directory", "", str)
        default_format = preferences.value("files/default_format", ".nebula", str)
        native_filter = "Nebula document (*.nebula *.nbl)"
        filter_for_format = {
            ".nebula": native_filter, ".nbl": native_filter,
            ".png": "PNG (*.png)", ".tif": "TIFF (*.tif *.tiff)",
        }
        selected_filter = filter_for_format.get(default_format, native_filter)

        file_path, selected = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le document",
            start_directory,
            "Nebula document (*.nebula *.nbl);;"
            "PNG (*.png);;"
            "JPEG (*.jpg *.jpeg);;"
            "TIFF (*.tif *.tiff);;"
            "BMP (*.bmp)",
            selected_filter,
        )

        if not file_path:
            return

        extension_by_filter = {
            native_filter: ".nebula", "PNG (*.png)": ".png",
            "JPEG (*.jpg *.jpeg)": ".jpg", "TIFF (*.tif *.tiff)": ".tif",
            "BMP (*.bmp)": ".bmp",
        }
        if not Path(file_path).suffix:
            native_default = default_format if default_format in (".nebula", ".nbl") else ".nebula"
            file_path += native_default if selected == native_filter else extension_by_filter.get(selected, ".nebula")
        self._remember_file_directory(file_path)

        extension = (
            Path(file_path)
            .suffix
            .lower()
        )

        if extension in (".nebula", ".nbl"):

            success = NebulaFormat.save(
                self.canvas.document,
                file_path
            )

        elif extension in (".csd", ".atlas"):
            QMessageBox.warning(
                self, "Format ancien",
                "Les fichiers CSD/Atlas sont conservés en lecture seule. "
                "Enregistre en .nebula ou .nbl.",
            )
            return

        else:

            image = (
                self.create_composite_image()
            )

            success = image.save(
                file_path
            )

        if not success:

            QMessageBox.warning(
                self,
                "Erreur",
                "Impossible d'enregistrer le fichier."
            )

            return

        self.current_file = file_path
        if extension in (".nebula", ".nbl"):
            self._last_saved_history_index = self.canvas.tile_history.index

        if extension in (".nebula", ".nbl"):
            self.recovery_manager.clear()

        self.update_window_title()

    @staticmethod
    def _remember_file_directory(file_path: str) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        if settings.value("files/remember_directory", True, bool):
            settings.setValue("files/last_directory", str(Path(file_path).parent))

    # =========================================================
    # CALQUES
    # =========================================================

    def _with_layer_history(self, operation, changed=None, dirty_only=False,
                            structure_only=False, prepare=None):
        """Wrap one layer command in a single undo step, respecting open sliders."""
        history = self.canvas.tile_history
        owns_transaction = history._pending is None
        if owns_transaction:
            history.begin(self.canvas.document, dirty_only=dirty_only,
                          structure_only=structure_only or dirty_only)
        try:
            if owns_transaction and prepare is not None:
                prepare(history)
            result = operation()
        except Exception:
            if owns_transaction:
                self.canvas.cancel_history_action()
            raise
        did_change = (bool(result) if changed is None else
                      bool(changed(result) if callable(changed) else changed))
        if owns_transaction:
            if did_change:
                self.canvas.commit_history_action()
            else:
                self.canvas.cancel_history_action()
        return result

    def refresh_layers(
        self
    ) -> None:

        self.ui.refresh_layers(
            self.canvas.document
        )

        self.canvas.update()

    def select_layer(
        self,
        row: int
    ) -> None:

        layer_index = (
            self.ui.get_selected_layer_index()
        )

        if layer_index < 0:
            return

        if self.layer_manager.select_layer(
            layer_index
        ):

            self.ui.update_layer_opacity(
                self.canvas.document
            )

            self.canvas.update()

    def add_layer(
        self
    ) -> None:

        self._with_layer_history(lambda: self.layer_manager.add_layer("Nouveau calque"),
                                 structure_only=True)

        self.refresh_layers()

    def duplicate_layer(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        layer = self._with_layer_history(
            lambda: self.layer_manager.duplicate_layer(index), structure_only=True
        )

        if layer is not None:

            self.refresh_layers()

    def rename_layer(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if index < 0:
            return

        layer = self.canvas.document.layers[
            index
        ]

        name, accepted = QInputDialog.getText(
            self,
            "Renommer le calque",
            "Nom du calque :",
            text=layer.name
        )

        if not accepted:
            return

        if self._with_layer_history(lambda: self.layer_manager.rename_layer(index, name),
                                    dirty_only=True):

            self.refresh_layers()

    def remove_layer(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        before_layers = ([self.canvas.document.layers[index]]
                         if 0 <= index < len(self.canvas.document.layers) else [])

        def prepare(history):
            for layer in before_layers:
                history.capture_layer_before(layer)

        if self._with_layer_history(lambda: self.layer_manager.remove_layer(index),
                                    structure_only=True, prepare=prepare):

            self.refresh_layers()
            self.canvas.prune_gpu_layers()

    def group_selected_layers(self) -> None:
        indices = self.ui.layers_dock.get_selected_layer_indices()
        if len(indices) < 2:
            return
        name, accepted = QInputDialog.getText(self, "Grouper les calques", "Nom du groupe :")
        if not accepted:
            return
        self.canvas.begin_history_action(dirty_only=True)
        group = self.canvas.document.group_layers(indices, name)
        if group is not None:
            self.canvas.commit_history_action()
            self.canvas._projection_tile_signatures.clear()
            self.refresh_layers()
            self.canvas.update()
        else:
            self.canvas.cancel_history_action()

    def ungroup_selected_layers(self) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        group = self.canvas.document.group_for_layer(layer.id)
        if group is not None:
            self.canvas.begin_history_action(dirty_only=True)
        if group is not None and self.canvas.document.ungroup_layers(group.id):
            self.canvas.commit_history_action()
            self.canvas._projection_tile_signatures.clear()
            self.refresh_layers()
            self.canvas.update()

    def toggle_active_group_visibility(self) -> None:
        layer = self.canvas.document.get_active_layer()
        group = self.canvas.document.group_for_layer(layer.id) if layer is not None else None
        if group is None:
            return
        self.canvas.begin_history_action(dirty_only=True)
        if not self.canvas.document.set_group_visibility(group.id, not group.visible):
            self.canvas.cancel_history_action()
            return
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def add_active_layer_mask(self) -> None:
        """Attach a sparse, fully opaque editable mask to the active layer."""
        index = self.canvas.document.active_layer_index
        if index < 0:
            return
        self.canvas.begin_history_action(dirty_only=True)
        if not self.layer_manager.add_alpha_mask(index):
            self.canvas.cancel_history_action()
            return
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def remove_active_layer_mask(self) -> None:
        """Remove the active layer mask as one structural undoable action."""
        index = self.canvas.document.active_layer_index
        if index < 0:
            return
        self.canvas.begin_history_action(dirty_only=True)
        if not self.layer_manager.remove_alpha_mask(index):
            self.canvas.cancel_history_action()
            return
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def _begin_group_opacity_history(self) -> None:
        if not getattr(self, "_group_opacity_edit_active", False):
            self._group_opacity_edit_active = True
            self.canvas.begin_history_action(dirty_only=True)

    def _commit_group_opacity_history(self) -> None:
        if getattr(self, "_group_opacity_edit_active", False):
            self._group_opacity_edit_active = False
            self.canvas.commit_history_action()

    def _group_opacity_action(self, _action) -> None:
        self._begin_group_opacity_history()
        QTimer.singleShot(0, self._commit_group_opacity_history_if_idle)

    def _commit_group_opacity_history_if_idle(self) -> None:
        if not self.ui.layers_dock.group_opacity_slider.isSliderDown():
            self._commit_group_opacity_history()

    def change_active_group_opacity(self, value: int) -> None:
        layer = self.canvas.document.get_active_layer()
        group = self.canvas.document.group_for_layer(layer.id) if layer is not None else None
        if group is None:
            return
        self._begin_group_opacity_history()
        self.canvas.document.set_group_opacity(
            group.id, max(0.0, min(1.0, int(value) / 100.0)))
        self.canvas._projection_tile_signatures.clear()
        self.canvas.update()

    def move_layer_up(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if self._with_layer_history(lambda: self.layer_manager.move_layer_up(index),
                                    dirty_only=True):

            self.refresh_layers()

    def move_layer_down(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if self._with_layer_history(lambda: self.layer_manager.move_layer_down(index),
                                    dirty_only=True):

            self.refresh_layers()

    def toggle_layer_visibility(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if not (0 <= index < len(self.canvas.document.layers)):
            return
        self._with_layer_history(
            lambda: self.layer_manager.toggle_visibility(index), changed=True,
            dirty_only=True,
        )

        self.refresh_layers()

    # =========================================================
    # OPACITÉ CALQUE
    # =========================================================

    def change_layer_opacity(
        self,
        value: int
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if index < 0:
            return

        self._with_layer_history(
            lambda: self.layer_manager.set_opacity(index, value / 100),
            changed=0 <= index < len(self.canvas.document.layers),
            dirty_only=True,
        )

        self.ui.set_layer_opacity_value(
            value
        )

        self.canvas.update()

    def _begin_layer_property_history(self) -> None:
        if self.canvas.tile_history._pending is None:
            self.canvas.begin_history_action(dirty_only=True)

    def _commit_layer_property_history(self) -> None:
        if self.canvas.tile_history._pending is not None:
            self.canvas.commit_history_action()

    def _layer_opacity_action(self, _action) -> None:
        self._begin_layer_property_history()
        QTimer.singleShot(0, self._commit_layer_property_history_if_idle)

    def _commit_layer_property_history_if_idle(self) -> None:
        if not self.ui.layer_opacity_slider.isSliderDown():
            self._commit_layer_property_history()

    # =========================================================
    # PANNEAUX
    # =========================================================

    def toggle_tools_panel(
        self,
        checked: bool = True
    ) -> None:

        self.ui.left_panel.setVisible(
            checked
        )

        self.ui.actions[
            "show_tools"
        ].setChecked(
            checked
        )

    def toggle_layers_panel(
        self,
        checked: bool = True
    ) -> None:

        self.ui.layers_panel.setVisible(
            checked
        )

        self.ui.actions[
            "show_layers"
        ].setChecked(
            checked
        )

    # =========================================================
    # COULEUR
    # =========================================================

    def choose_color(
        self
    ) -> None:

        color = QColorDialog.getColor(
            self.canvas.tools.brush.color,
            self,
            "Choisir une couleur"
        )

        if not color.isValid():
            return

        self.canvas.set_brush_setting(
            "color",
            [color.red(), color.green(), color.blue(), color.alpha()]
        )

        self.ui.set_color(
            color.name()
        )

    # =========================================================
    # BROSSE
    # =========================================================

    def change_brush_size(
        self,
        value: int
    ) -> None:

        self.canvas.set_brush_setting("size", float(value))

        self.ui.set_brush_size_value(
            value
        )

    def change_brush_opacity(
        self,
        value: int
    ) -> None:

        self.canvas.set_brush_setting("opacity", value / 100)

        self.ui.set_brush_opacity_value(
            value
        )

    def change_pressure_size(
        self,
        value: int
    ) -> None:

        self.canvas.set_brush_setting(
            "pressureSize", value > 0
        )

        self.ui.set_pressure_size_value(
            value
        )

    def change_pressure_opacity(
        self,
        value: int
    ) -> None:

        self.canvas.set_brush_setting(
            "pressureOpacity", value > 0
        )

        self.ui.set_pressure_opacity_value(
            value
        )

    def change_spacing(
        self,
        value: int
    ) -> None:

        self.canvas.set_brush_setting("spacing", value / 100)

        self.ui.set_spacing_value(
            value
        )

    # =========================================================
    # VUE
    # =========================================================

    def reset_view(
        self
    ) -> None:

        self.canvas.fit_document()

        self.ui.set_zoom(
            self.canvas.zoom
        )

        self.canvas.update()

    def toggle_canvas_only(self) -> None:
        self.canvas.toggle_canvas_only()
        visible = not self.canvas.canvas_only
        for dock in (
            self.ui.tool_rail_dock,
            self.ui.brush_panel_dock,
            self.ui.color_dock,
            self.ui.brush_presets_dock,
            self.ui.layers_dock,
        ):
            dock.setVisible(visible)
        self.ui.main_toolbar.setVisible(visible)

    def set_drawing_assistant(self, mode: str, enabled: bool) -> None:
        self.canvas.set_assistant_mode(mode if enabled else "none")
        actions = self.ui.actions
        for key, candidate in (
            ("assistant_ruler", "ruler"),
            ("assistant_ellipse", "ellipse"),
            ("assistant_perspective", "perspective"),
        ):
            action = actions[key]
            action.blockSignals(True)
            action.setChecked(enabled and candidate == mode)
            action.blockSignals(False)

    def _sync_checkable_action(self, key: str, checked: bool) -> None:
        action = self.ui.actions[key]
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _sync_view_flip_actions(self, horizontal: bool, vertical: bool) -> None:
        self._sync_checkable_action("flip_canvas_horizontal", horizontal)
        self._sync_checkable_action("flip_canvas_vertical", vertical)

    def _sync_symmetry_actions(self, horizontal: bool, vertical: bool) -> None:
        self._sync_checkable_action("symmetry_horizontal", horizontal)
        self._sync_checkable_action("symmetry_vertical", vertical)

    # =========================================================
    # TITRE
    # =========================================================

    def update_window_title(
        self
    ) -> None:

        if self.current_file:

            filename = Path(
                self.current_file
            ).name

            self.setWindowTitle(
                f"CreativeSystem Nebula — {filename}"
            )

        else:

            self.setWindowTitle(
                "CreativeSystem Nebula — Nouveau dessin"
            )

        self.ui.set_zoom(
            self.canvas.zoom
        )

    # =========================================================
    # RUN
    # =========================================================

    def run(
        self
    ) -> None:

        self.show()
