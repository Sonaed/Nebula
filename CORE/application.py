from CORE.version import DISPLAY as NEBULA_DISPLAY
from pathlib import Path
import os
import sys
import json
import subprocess
import tempfile

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QColorDialog,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QProgressDialog,
)

from PySide6.QtGui import (
    QImage,
    QColor,
)
from PySide6.QtCore import Qt, QSettings, QTimer

from CANVAS.canvas import Canvas

from UI.ui import CreativeSystemUI
from UI.dialogs.adjustment_layer_dialog import AdjustmentLayerDialog

from DOCUMENTS.layer_manager import LayerManager

from DOCUMENTS.document_manager import DocumentManager

from DOCUMENTS.format_nebula import NebulaFormat, load_document
from DOCUMENTS.format_psd import PSDFormat

from DOCUMENTS.document_dialog import DocumentDialog

from DOCUMENTS.document import Document
from DOCUMENTS.tile_store import (TILE_SIZE, initialize_scratch_dispatcher,
                                  shutdown_scratch_executor)
from TOOLS.resource_manager import ResourceManager
from DOCUMENTS.blend_modes import composite_document
from DOCUMENTS.color_management import ColorProfile, convert_to_profile
from DOCUMENTS.recovery import RecoveryManager
from DOCUMENTS.psd_import import (
    PSDImportScheduler, ImportPriority, build_overview, decode_composite_tiles,
    estimate_import_budget,
)
from DOCUMENTS.format_psd import PSDImportCancelled
from CORE.memory_manager import MemoryManager
from CORE.native_bridge import fill_image_native, plan_visible_layer_merge


class CreativeSystem(QMainWindow):

    def closeEvent(
        self,
        event
    ) -> None:

        if getattr(self, "_psd_import_scheduler", None) is not None:
            self._psd_import_scheduler.cancel()
            self._psd_import_scheduler.shutdown(wait=False)
            self._psd_import_scheduler = None
            self._psd_overview_future = None
            self._psd_tile_future = None

        canvas = getattr(
            self,
            "canvas",
            None
        )

        wormholes = getattr(self, "wormholes", None)
        if wormholes is not None:
            wormholes.shutdown()

        ui = getattr(self, "ui", None)
        if ui is not None and hasattr(ui, "workspace_manager"):
            ui.workspace_manager.save_session()

        if canvas is not None:
            canvas.cleanup_gl_resources()
            canvas._destroy_cpp_brush()
        memory_manager = getattr(self, "memory_manager", None)
        if memory_manager is not None:
            memory_manager.shutdown()
        shutdown_scratch_executor()

        super().closeEvent(
            event
        )


    def __init__(
        self
    ) -> None:

        super().__init__()
        initialize_scratch_dispatcher()

        # CreativeSystem is an opaque desktop window. Explicitly disabling
        # translucency prevents the compositor from exposing applications
        # below it if an OpenGL child momentarily carries fractional alpha.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)

        # =====================================================
        # FENÊTRE
        # =====================================================

        self.setWindowTitle(
            f"CreativeSystem {NEBULA_DISPLAY} — Nouveau dessin"
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
        self.resource_manager = ResourceManager()

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
            self.canvas,
            self.resource_manager,
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
        self._psd_import_scheduler: PSDImportScheduler | None = None
        self._psd_import_future = None
        self._psd_proxy_tiles: set[tuple[int, int]] = set()
        self._psd_last_viewport = None
        self._psd_overview_future = None
        self._psd_tile_future = None
        self._psd_import_timer = None
        self._psd_import_progress = None
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
        if os.environ.get("EXISTENCE_EMBEDDED_VIEW") == "1":
            return
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

        self.canvas.performance_warning.connect(
            lambda message: self.statusBar().showMessage(message, 5000)
        )
        self.canvas.history_operation_deferred.connect(
            lambda message: self.statusBar().showMessage(message, 1800)
        )

        # LayersDock.invalidate_thumb_cache() already existed for exactly
        # this ("called by the canvas after a brush stroke on the active
        # layer. Without this, thumbnails stay frozen even when painting.")
        # but nothing ever called it - no layer thumbnail, including a mask
        # thumbnail, ever refreshed after painting on it.
        self.canvas.layer_thumbnail_dirty.connect(
            self._on_layer_thumbnail_dirty
        )

        # -----------------------------------------------------
        # HOME PAGE
        # -----------------------------------------------------

        self.ui.home_new_requested.connect(
            self.new_file
        )

        self.ui.home_open_requested.connect(
            self.open_file
        )
        self.ui.home_recent_requested.connect(self.open_file)
        self._refresh_recent_documents()

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
        self.ui.actions["feather_selection"].triggered.connect(lambda: self.edit_selection("feather"))
        self.ui.actions["expand_selection"].triggered.connect(lambda: self.edit_selection("expand"))
        self.ui.actions["contract_selection"].triggered.connect(lambda: self.edit_selection("contract"))
        self.ui.actions["select_color_range"].triggered.connect(self.select_color_range)
        self.ui.actions["select_alpha"].triggered.connect(self.select_alpha)

        self.ui.actions["show_brush"].triggered.connect(
            self.ui.brush_panel_dock.setVisible
        )

        # -----------------------------------------------------
        # IMAGE
        # -----------------------------------------------------

        self.ui.actions["export"].triggered.connect(
            self.export_image
        )
        self.ui.actions["singularize"].triggered.connect(
            self.singularize_export
        )
        self.ui.blend_creator_dock.visibilityChanged.connect(
            self._enforce_blend_module_visibility
        )
        # Module Pixel Art (Existence) : panneau visible seulement s'il est branché.
        from PIXEL.pixel_art import install as install_pixel_art
        self.pixel_art = install_pixel_art(self)
        if self.pixel_art is not None:
            self.ui.actions["pixel_art_panel"] = self.pixel_art.dock.toggleViewAction()
            if getattr(self.ui, "dockers_menu", None) is not None:
                self.ui.dockers_menu.addAction(self.pixel_art.dock.toggleViewAction())
        # Hôte générique Existence : tout autre module compatible branché sur
        # Nebula arrive dans le menu « Modules » et, s'il a une interface, en
        # panneau (listé aussi dans Fenêtre ▸ Panneaux).
        self.module_host = None
        try:
            import os as _os
            import sys as _sys
            _root = _os.environ.get("EXISTENCE_ROOT", "/home/deanos/Documents/Existence")
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            from modules.host_sdk import install_module_host
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice

            def _composite_png() -> bytes:
                data = QByteArray()
                buffer = QBuffer(data)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                self.create_composite_image().save(buffer, "PNG")
                return bytes(data)

            dockers = getattr(self.ui, "dockers_menu", None)
            self.module_host = install_module_host(
                self, "nebula",
                register_dock=(lambda dock: dockers.addAction(dock.toggleViewAction())) if dockers else None,
                handled={"fusion_creator", "pixel_art", "resource_center"},
                image_provider=_composite_png,
            )
        except ImportError as exc:
            print(f"[Nebula] SDK de modules Existence introuvable : {exc}")
        self._install_test_probe()
        self.refresh_existence_modules()
        # Existence peut (dé)brancher un module pendant que Nebula tourne.
        self._existence_config_mtime = self._existence_config_stamp()
        self._existence_watch = QTimer(self)
        self._existence_watch.timeout.connect(self._watch_existence_config)
        self._existence_watch.start(2000)
        # Wormholes d'Existence : envoi entre apps et calques liés en direct.
        from EXISTENCE.wormhole_client import install as install_wormholes
        self.wormholes = install_wormholes(self)

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
        self.ui.adjustment_settings_dock.spec_changed.connect(self._apply_adjustment_live)
        self.ui.adjustment_settings_dock.editing_started.connect(self._begin_adjustment_edit)
        self.ui.adjustment_settings_dock.editing_finished.connect(self._end_adjustment_edit)

        self.ui.add_layer_button.clicked.connect(
            self.add_layer
        )

        self.ui.duplicate_layer_button.clicked.connect(
            self.duplicate_layer
        )

        self.ui.remove_layer_button.clicked.connect(
            self.remove_layer
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
        self.ui.layers_dock.apply_mask_requested.connect(self.apply_active_layer_mask)
        self.ui.layers_dock.disable_mask_requested.connect(self.toggle_active_layer_mask_disabled)
        self.ui.layers_dock.invert_mask_requested.connect(self.invert_active_layer_mask)
        self.ui.layers_dock.mask_selected.connect(self.edit_layer_mask_at)
        self.ui.layers_dock.add_adjustment_requested.connect(self.add_adjustment_layer)
        self.ui.layers_dock.edit_adjustment_requested.connect(self.edit_adjustment_layer)
        self.ui.layers_dock.visibility_requested.connect(self.toggle_layer_visibility_at)
        self.ui.layers_dock.layer_order_changed.connect(self.reorder_layers)
        self.ui.layers_dock.layer_group_drop_changed.connect(self.reorder_layers_into_groups)
        self.ui.layers_dock.merge_selected_requested.connect(self.merge_selected_layers)
        self.ui.layers_dock.label_color_requested.connect(self.set_active_layer_label_color)
        self.ui.layers_dock.clipping_requested.connect(self.toggle_layer_clipping_at)
        self.ui.layers_dock.rename_requested.connect(self.rename_layer_at)
        self.ui.layers_dock.isolate_requested.connect(self.isolate_layer_at)
        self.ui.layers_dock.lock_indicator_clicked.connect(self.toggle_lock_from_indicator)
        self.ui.layers_dock.group_selected_requested.connect(self.group_selected_layers)
        self.ui.layers_dock.ungroup_selected_requested.connect(self.ungroup_selected_layers)
        self.ui.layers_dock.group_visibility_requested.connect(self.toggle_active_group_visibility)
        self.ui.layers_dock.group_visibility_requested_at.connect(self.toggle_group_visibility_at)
        self.ui.layers_dock.group_opacity_slider.valueChanged.connect(self.change_active_group_opacity)
        self.ui.layers_dock.group_opacity_slider.sliderPressed.connect(self._begin_group_opacity_history)
        self.ui.layers_dock.group_opacity_slider.sliderReleased.connect(self._commit_group_opacity_history)
        self.ui.layers_dock.group_opacity_slider.actionTriggered.connect(self._group_opacity_action)
        # ── Dupliquer (bouton dock + menu contextuel clic droit) ──────────────
        self.ui.layers_dock.duplicate_layer_requested.connect(self.duplicate_layer)

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

        # Vue menu mirrors — same handlers so both menu items stay in sync.
        self.ui.actions[
            "show_tools"
        ].triggered.connect(
            self.toggle_tools_panel
        )

        self.ui.actions[
            "show_layers"
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

        visible_count = sum(1 for layer in document.layers if layer.visible)
        if visible_count > 1 and isinstance(self, QWidget):
            if QMessageBox.question(
                self,
                "Fusionner les calques visibles",
                f"Fusionner les {visible_count} calques visibles en un seul ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return

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

        count = len(document.layers)
        if count > 1 and isinstance(self, QWidget):
            if QMessageBox.question(
                self,
                "Aplatir l'image",
                f"Fusionner les {count} calques en un seul ? "
                "La structure de calques sera perdue.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return

        def prepare(history):
            for layer in document.layers:
                history.capture_layer_before(layer)

        changed = self._with_layer_history(self.layer_manager.flatten,
                                           structure_only=True, prepare=prepare)
        if changed:
            self.refresh_layers(); self.canvas.prune_gpu_layers(); self.canvas.sync_gpu_layer()

    def toggle_layer_lock(self) -> None:
        targets = self._selected_layer_targets()
        document = self.canvas.document
        # toggle_lock returns the *new locked state*: False is a successful
        # unlock, not a failed operation.  Refresh on both transitions.
        if targets:
            active = document.active_layer_index
            reference = active if active in targets else targets[0]
            wanted = not document.layers[reference].locked

            def lock_all():
                for index in targets:
                    if document.layers[index].locked != wanted:
                        self.layer_manager.toggle_lock(index)
                return True

            self._with_layer_history(lock_all, changed=True, dirty_only=True)
            self.refresh_layers()

    def set_active_layer_label_color(self, color: str | None) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        from UI.theme.palette import COLORS
        normalized = color if color in {None, *(COLORS[key] for key in ("label_red", "label_orange", "label_yellow", "label_green", "label_blue", "label_violet", "label_pink"))} else None
        if layer.label_color == normalized:
            return
        self.canvas.begin_history_action(structure_only=True)
        layer.label_color = normalized
        self.canvas.commit_history_action()
        self.refresh_layers()

    def toggle_layer_alpha_lock(self) -> None:
        index = self.canvas.document.active_layer_index
        valid = 0 <= index < len(self.canvas.document.layers)
        if valid:
            self._with_layer_history(lambda: self.layer_manager.toggle_lock_alpha(index),
                                     changed=True, dirty_only=True)
            self.refresh_layers()

    def toggle_layer_clipping_at(self, index: int) -> None:
        """Toggle the upper layer's clipping mask via Alt-click in the stack."""
        if not (0 < index < len(self.canvas.document.layers)):
            return
        self._with_layer_history(lambda: self.layer_manager.toggle_clipping(index),
                                 changed=True, structure_only=True)
        self.canvas._invalidate_projection_cache()
        self.refresh_layers()
        self.canvas.update()

    def isolate_layer_at(self, index: int) -> None:
        """Alt+clic sur l'œil : n'afficher que ce calque, ou tout réafficher."""
        document = self.canvas.document
        if not (0 <= index < len(document.layers)):
            return
        others = [i for i in range(len(document.layers)) if i != index]
        already_isolated = (document.layers[index].visible
                            and all(not document.layers[i].visible for i in others))

        def apply() -> bool:
            for i, layer in enumerate(document.layers):
                layer.visible = True if already_isolated else (i == index)
            return True

        self._with_layer_history(apply, changed=True, dirty_only=True)
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.statusBar().showMessage(
            "Tous les calques réaffichés." if already_isolated
            else f"Calque « {document.layers[index].name} » isolé (Alt+clic pour revenir).",
            4000,
        )

    def toggle_lock_from_indicator(self, index: int, alpha_locked: bool) -> None:
        """Clic direct sur les indicateurs α / ◈ peints dans la liste."""
        document = self.canvas.document
        if not (0 <= index < len(document.layers)):
            return
        action = (self.layer_manager.toggle_lock_alpha if alpha_locked
                  else self.layer_manager.toggle_lock)
        self._with_layer_history(lambda: action(index), changed=True, dirty_only=True)
        self.refresh_layers()

    def deselect(self) -> None:
        self._with_selection_history(self.canvas.document.selection.clear)
        self.canvas.update()

    def invert_selection(self) -> None:
        self._with_selection_history(self.canvas.document.selection.invert)
        self.canvas.update()

    def edit_selection(self, operation: str) -> None:
        radius, accepted = QInputDialog.getInt(self, "Sélection", "Rayon (px)", 4, 1, 256)
        if not accepted:
            return
        selection = self.canvas.document.selection
        self._with_selection_history(lambda: getattr(selection, operation)(radius))
        self.canvas.update()

    def select_color_range(self) -> None:
        values = self.canvas.brush_settings.snapshot().get("color", [255, 255, 255, 255])
        color = QColor(*[int(value) for value in values[:4]])
        tolerance, accepted = QInputDialog.getInt(self, "Plage de couleurs", "Tolérance", 24, 1, 255)
        if not accepted:
            return
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        self._with_selection_history(lambda: self.canvas.document.selection.select_color_range(
            layer.image, color, tolerance))
        self.canvas.update()

    def select_alpha(self) -> None:
        """Load the active layer transparency as an undoable selection."""
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        self._with_selection_history(lambda: self.canvas.document.selection.select_alpha(layer.image))
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

        pixel_art = getattr(self, "pixel_art", None)
        dialog = DocumentDialog(
            self,
            pixel_art=bool(pixel_art is not None and pixel_art.enabled),
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
        preset = dialog.get_pixel_preset()
        if preset is not None and pixel_art is not None:
            QTimer.singleShot(0, lambda: pixel_art.apply_canvas_preset(preset))

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

    def _start_psd_import(self, file_path: str) -> None:
        """Decode PSD away from the Qt event thread; cancellation is cooperative."""
        if self._psd_import_scheduler is not None:
            self._psd_import_scheduler.cancel()
            self._psd_import_scheduler.shutdown(wait=False)
        scheduler = self._psd_import_scheduler = PSDImportScheduler(workers=2)
        try:
            budget = estimate_import_budget(file_path)
            limit = getattr(getattr(self, "memory_manager", None), "limit_mb", 0)
            budget_text = (f"Budget d’import estimé : {budget.estimated_mib:.0f} MiB"
                           f" · calque plein : {budget.per_full_layer_mib:.0f} MiB"
                           + (f" · limite Nebula : {limit} MiB" if limit else ""))
            self._psd_import_budget = budget
        except (OSError, ValueError) as error:
            budget_text = f"Budget d’import indisponible : {error}"
            self._psd_import_budget = None
        progress = QProgressDialog(f"Lecture des métadonnées Photoshop…\n{budget_text}", "Annuler", 0, 0, self)
        progress.setWindowTitle("Import Photoshop")
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.canceled.connect(self._cancel_psd_import)
        progress.show()
        self._psd_import_progress = progress
        self.ui.set_import_state(budget_text, warning=bool(getattr(self._psd_import_budget, "estimated_mib", 0) > (getattr(getattr(self, "memory_manager", None), "limit_mb", 0) or float("inf"))))
        self.statusBar().showMessage(f"Import PSD en arrière-plan… {budget_text}")
        self._psd_overview_future = scheduler.submit(
            "overview", ImportPriority.OVERVIEW,
            lambda cancel: None if cancel.is_set() else build_overview(file_path))
        self._psd_import_future = None
        self._psd_import_timer = QTimer(self)
        self._psd_import_timer.setInterval(30)
        self._psd_import_timer.timeout.connect(lambda: self._poll_psd_import(file_path))
        self._psd_import_timer.start()

    def _cancel_psd_import(self) -> None:
        """Stop accepting PSD work without blocking the event loop."""
        scheduler, self._psd_import_scheduler = self._psd_import_scheduler, None
        if scheduler is not None:
            scheduler.cancel()
            scheduler.shutdown(wait=False)
        if self._psd_import_timer is not None:
            self._psd_import_timer.stop()
        self._psd_overview_future = None
        self._psd_tile_future = None
        self._psd_import_future = None
        progress, self._psd_import_progress = self._psd_import_progress, None
        if progress is not None:
            progress.blockSignals(True)
            progress.close()
            progress.deleteLater()
        self.statusBar().showMessage("Import PSD annulé")
        self.ui.set_import_state()

    def _poll_psd_import(self, file_path: str) -> None:
        overview = self._psd_overview_future
        if overview is not None and overview.done():
            self._psd_overview_future = None
            try:
                payload, (width, height) = overview.result()
                progress = getattr(self, "_psd_import_progress", None)
                if progress is not None:
                    progress.setLabelText("Aperçu prêt — préparation des zones visibles…\n" + self.ui.import_state_label.text())
                self._show_psd_proxy(payload, width, height)
                # The embedded preview is available immediately.  Decode the
                # document-space tiles beneath the current viewport next and
                # put them in the proxy's sparse store as they arrive.  This
                # keeps the import bounded and, unlike the former status-only
                # callback, gives Canvas real pixels to render and retain.
                self._queue_psd_viewport_tiles(file_path, width, height)
                # Keep the complete preview stable while editable layers load.
                editable_viewport = self._psd_import_viewport(width, height)
                self._psd_import_future = self._psd_import_scheduler.submit(
                    "document", ImportPriority.REST,
                    lambda cancel: PSDFormat.load(file_path, cancel=cancel,
                                                   viewport=editable_viewport))
            except Exception as error:  # noqa: BLE001
                self.statusBar().showMessage(f"Aperçu PSD indisponible : {error}")
                # The preview is optional; never let it prevent the editable
                # native import from starting.
                self._psd_import_future = self._psd_import_scheduler.submit(
                    "document", ImportPriority.REST,
                    lambda cancel: PSDFormat.load(file_path, cancel=cancel))
        tile_future = getattr(self, "_psd_tile_future", None)
        if tile_future is not None and tile_future.done():
            self._psd_tile_future = None
            try:
                _size, tiles = tile_future.result()
                self._apply_psd_proxy_tiles(tiles)
                self._psd_proxy_tiles.update(tiles)
                progress = getattr(self, "_psd_import_progress", None)
                if progress is not None:
                    progress.setLabelText("Zones visibles prêtes — import des calques…")
                self.statusBar().showMessage(f"PSD — {len(tiles)} tuiles visibles prêtes")
            except Exception as error:  # noqa: BLE001
                self.statusBar().showMessage(f"Tuiles PSD indisponibles : {error}")
        proxy = getattr(self.canvas, "document", None)
        if (self._psd_import_scheduler is not None and proxy is not None
                and getattr(proxy, "_loading_preview", False)
                and self._psd_tile_future is None):
            self._queue_psd_viewport_tiles(file_path, proxy.width, proxy.height)
        future = self._psd_import_future
        if future is None or not future.done():
            return
        if self._psd_import_timer is not None:
            self._psd_import_timer.stop()
        progress, self._psd_import_progress = self._psd_import_progress, None
        if progress is not None:
            progress.blockSignals(True)
            progress.close()
            progress.deleteLater()
        scheduler, self._psd_import_scheduler = self._psd_import_scheduler, None
        self._psd_import_future = None
        try:
            document = future.result()
        except PSDImportCancelled:
            self.statusBar().showMessage("Import PSD annulé")
            self.ui.set_import_state()
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            return
        except Exception as error:  # noqa: BLE001
            self.statusBar().showMessage(f"Import PSD échoué : {error}")
            self.ui.set_import_state("Import PSD interrompu", warning=True)
            if scheduler is not None: scheduler.shutdown(wait=False)
            QMessageBox.warning(self, "Ouverture PSD", f"Impossible d’ouvrir le fichier PSD :\n{error}")
            return
        if scheduler is not None:
            self.statusBar().showMessage(
                f"PSD importé — premier résultat {scheduler.metrics.first_result_ms or 0:.0f} ms")
            scheduler.shutdown(wait=False)
        if document is None:
            self.ui.set_import_state("Import PSD indisponible", warning=True)
            QMessageBox.warning(self, "Import PSD", "Impossible d’ouvrir ce fichier PSD.")
            return
        self._report_psd_import(document)
        warnings = list(getattr(document, "psd_import_report", {}).get("warnings", ()) or ())
        self.ui.set_import_state(
            "PSD éditable" if not warnings else f"PSD éditable · {len(warnings)} limite(s)",
            warning=bool(warnings),
        )
        preview = getattr(self.canvas.document, "_display_preview", None)
        if preview is not None:
            document._display_preview = QImage(preview)
        self.canvas.set_document(document)
        self.layer_manager = LayerManager(document)
        self.document_manager.documents.append(document)
        self.document_manager.active_document = document
        self.current_file = file_path
        self._remember_recent_document(file_path)
        self._last_saved_history_index = self.canvas.tile_history.index
        self.refresh_layers()
        self.update_window_title()
        self.ui.show_workspace()

    def _show_psd_proxy(self, payload: bytes, width: int, height: int) -> None:
        """Display the embedded composite while editable layers decode."""
        image = QImage.fromData(payload, "PNG")
        if image.isNull():
            return
        proxy = Document(width, height, 300, None)
        proxy.name = "Aperçu PSD (décodage en cours)"
        layer = proxy.get_active_layer()
        if layer is None:
            return
        layer.name = "Aperçu composite"
        proxy._display_preview = image
        proxy._loading_preview = True
        self.ui.set_import_state("Aperçu PSD · import éditable en cours")
        self.canvas.set_document(proxy)
        self.layer_manager = LayerManager(proxy)
        self.document_manager.documents.append(proxy)
        self.document_manager.active_document = proxy
        self.refresh_layers()
        self.ui.show_workspace()
        self.statusBar().showMessage("Aperçu PSD visible — calques en cours de décodage…")

    def _psd_import_viewport(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Document-space viewport used for the first progressive PSD pass."""
        canvas = self.canvas
        zoom = max(float(getattr(canvas, "zoom", 1.0) or 1.0), 0.001)
        offset = getattr(canvas, "offset", None)
        ox = float(offset.x()) if offset is not None else 0.0
        oy = float(offset.y()) if offset is not None else 0.0
        visible_width = max(TILE_SIZE, int(canvas.width() / zoom))
        visible_height = max(TILE_SIZE, int(canvas.height() / zoom))
        x = max(0, min(width - 1, int(-ox / zoom)))
        y = max(0, min(height - 1, int(-oy / zoom)))
        return x, y, min(visible_width, width - x), min(visible_height, height - y)

    def _queue_psd_viewport_tiles(self, file_path: str, width: int, height: int) -> None:
        """Prioritize the current viewport again whenever the user pans."""
        viewport = self._psd_import_viewport(width, height)
        if viewport == self._psd_last_viewport:
            return
        self._psd_last_viewport = viewport
        scheduler = self._psd_import_scheduler
        if scheduler is None:
            return
        self._psd_tile_future = scheduler.submit(
            "visible composite tiles", ImportPriority.VISIBLE,
            lambda cancel: None if cancel.is_set() else decode_composite_tiles(
                file_path, viewport, TILE_SIZE, self._psd_proxy_tiles))

    def _apply_psd_proxy_tiles(self, tiles: dict[tuple[int, int], bytes]) -> None:
        """Publish decoded composite regions into the loading proxy's tiles.

        ``decode_composite_tiles`` returns document origins rather than tile
        keys.  Splitting each decoded image at Nebula's native tile boundary
        handles edge tiles and keeps the proxy compatible with normal Canvas
        composition.
        """
        proxy = getattr(self.canvas, "document", None)
        if proxy is None or not getattr(proxy, "_loading_preview", False):
            return
        layer = proxy.get_active_layer()
        store = getattr(layer, "tile_store", None) if layer is not None else None
        if store is None:
            return
        writes = []
        for (origin_x, origin_y), payload in tiles.items():
            image = QImage.fromData(payload, "PNG").convertToFormat(QImage.Format.Format_ARGB32)
            if image.isNull():
                continue
            for y in range(0, image.height(), TILE_SIZE):
                for x in range(0, image.width(), TILE_SIZE):
                    tx, ty = (origin_x + x) // TILE_SIZE, (origin_y + y) // TILE_SIZE
                    target = store.tile_rect(tx, ty)
                    if target.isEmpty():
                        continue
                    part = image.copy(x, y, target.width(), target.height())
                    if not part.isNull():
                        writes.append((tx, ty, part))
        if writes:
            store.set_tiles_batch(writes)
            update = getattr(self.canvas, "update", None)
            if callable(update):
                update()

    def _report_psd_import(self, document) -> None:
        """Tell the user what a PSD import could not keep editable (if anything)."""
        report = getattr(document, "psd_import_report", None)
        warning = str(getattr(document, "psd_import_warning", "") or "").strip()
        if isinstance(report, dict):
            try:
                self.statusBar().showMessage(
                    f"PSD importé : {report.get('layers', 0)} calques, "
                    f"{report.get('groups', 0)} dossiers, "
                    f"{report.get('adjustments', 0)} calques de réglage", 8000)
            except RuntimeError:
                pass
        if not warning:
            return
        lines = warning.splitlines()
        shown = "\n".join(f"• {line}" for line in lines[:14])
        if len(lines) > 14:
            shown += f"\n… et {len(lines) - 14} autre(s)"
        print("Import PSD :\n" + warning)
        QMessageBox.information(self, "Import PSD", "Le fichier est ouvert. Remarques :\n\n" + shown)

    def _report_psd_export(self, document) -> None:
        """Make Photoshop export losses visible after a successful write."""
        report = getattr(document, "psd_export_report", {})
        warnings = list(report.get("warnings", ())) if isinstance(report, dict) else []
        if not warnings:
            self.statusBar().showMessage("PSD exporté sans perte connue", 6000)
            return
        shown = "\n".join(f"• {warning}" for warning in warnings)
        self.statusBar().showMessage("PSD exporté avec limitations signalées", 8000)
        QMessageBox.information(
            self, "Export Photoshop", "Le fichier a été exporté. Limites connues :\n\n" + shown)

    def open_file(self, file_path: str | None = None) -> None:

        preferences = QSettings("CreativeSystem", "CreativeSystem")
        start_directory = preferences.value("files/last_directory", "", str)

        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Ouvrir un document",
                start_directory,
                "Nebula document (*.nebula *.nbl);;"
                "Legacy projects (*.csd *.atlas *.psd *.psb);;"
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

        if extension in (".nebula", ".nbl", ".csd", ".atlas", ".psd", ".psb"):

            if extension in (".psd", ".psb"):
                self._start_psd_import(file_path)
                return

            document = load_document(file_path)

            if document is None:

                QMessageBox.warning(
                    self,
                    "Erreur",
                    "Impossible d’ouvrir ce document Nebula, CSD, Atlas ou PSD."
                )

                return

            self._report_psd_import(document)

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
            self._remember_recent_document(file_path)
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
            self._remember_recent_document(file_path)
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

        self._dispose_current_document()

    def _dispose_current_document(self) -> None:
        """Release sparse/native pixels before returning from a discarded document.

        Merely hiding the workspace left the active Canvas and document manager
        holding every native TileStore. For dense PSDs this looked exactly like
        a persistent RAM leak after closing a file.
        """
        old = self.canvas.document
        replacement = Document(800, 600)
        self.canvas.set_document(replacement)
        for layer in old.layers:
            layer.tile_store.close()
            if layer.alpha_mask_store is not None:
                layer.alpha_mask_store.close()
        selection_store = getattr(getattr(old, "selection", None), "tile_store", None)
        if selection_store is not None:
            selection_store.close()
        for group in getattr(old, "layer_groups", ()):
            group.invalidate()
            if getattr(group, "alpha_mask_store", None) is not None:
                group.alpha_mask_store.close()
        self.document_manager.close_document(old)
        if replacement not in self.document_manager.documents:
            self.document_manager.documents.append(replacement)
        self.document_manager.active_document = replacement
        self.layer_manager = LayerManager(replacement)
        self.current_file = None
        self.ui.show_home()
        self.update_window_title()
        manager = getattr(self, "memory_manager", None)
        if manager is not None:
            manager.trim_allocator()
            manager.refresh()

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

        image = composite_document(document)
        profile = getattr(document, "color_profile", {}) or {}
        icc = profile.get("icc", "") if isinstance(profile, dict) else ""
        if icc:
            try:
                image = convert_to_profile(image, ColorProfile(str(profile.get("name", "embedded ICC")),
                                                               bytes.fromhex(str(icc))))
            except (ValueError, TypeError):
                # A malformed optional profile must not make a valid raster
                # export unusable; Nebula validation still rejects bad files.
                pass
        return image

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

    def _existence_module_connected(self, module_id: str, parent_id: str = "nebula") -> bool:
        """True only while Existence keeps the module on its Nebula orbit."""
        config_path = Path.home() / ".config" / "existence" / "apps.json"
        if not config_path.exists():
            return True
        try:
            apps = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        item = next((app for app in apps if app.get("id") == module_id), None)
        if not item:
            return False
        # Un module peut être branché sur plusieurs univers à la fois.
        hosts = list(item.get("orbits") or [])
        if item.get("orbit_of"):
            hosts.append(item["orbit_of"])
        return parent_id in hosts

    def _install_test_probe(self) -> None:
        """Sonde du banc de test GUI (inactive hors test)."""
        import os as _os
        if not _os.environ.get("EXISTENCE_TEST_PROBE"):
            return
        import hashlib
        from modules.test_probe import install_probe
        from DOCUMENTS.document import Document

        def layer_hash(layer) -> str:
            image = layer.image
            return hashlib.md5(bytes(image.constBits())[: image.sizeInBytes()]).hexdigest()[:12]

        def state() -> dict:
            on_home = self.ui.stack.currentWidget() is getattr(self.ui, "home_page", None)
            document = None if on_home else getattr(self.canvas, "document", None)
            layers = []
            if document is not None:
                layers = [{"id": l.id, "name": l.name, "hash": layer_hash(l)} for l in document.layers]
            holes = getattr(self, "wormholes", None)
            return {"document": bool(document), "layers": layers,
                    "live_links": dict(getattr(holes, "layer_links", {}) or {}),
                    "fusion_available": self._existence_module_connected("fusion_creator"),
                    "pixel_art_enabled": bool(getattr(getattr(self, "pixel_art", None), "enabled", False))}

        def new_document(width=64, height=64):
            document = Document(int(width), int(height), 72, QColor(255, 255, 255))
            self.canvas.set_document(document)
            self.layer_manager = LayerManager(document)
            self.document_manager.documents.append(document)
            self.document_manager.active_document = document
            self.current_file = None
            self._last_saved_history_index = self.canvas.tile_history.index
            self.refresh_layers()
            self.ui.show_workspace()
            return True

        def fill_active(red, green, blue):
            layer = self.canvas.get_active_layer()
            image = QImage(layer.image.width(), layer.image.height(), QImage.Format.Format_ARGB32)
            image.fill(QColor(int(red), int(green), int(blue)))
            self._with_layer_history(lambda: setattr(layer, "image", image) or True)
            self.canvas._invalidate_gpu_after_history()
            return layer.id

        def send_layer(target, live=True):
            self.wormholes.send_layer(target, live=bool(live))
            return list(self.wormholes.layer_links)

        self._test_probe = install_probe(self, "nebula", state=state, commands={
            "new_document": new_document, "fill_active": fill_active, "send_layer": send_layer,
            "poll_wormholes": lambda: self.wormholes.poll() or True,
        })

    @staticmethod
    def _existence_config_stamp() -> float:
        try:
            return (Path.home() / ".config" / "existence" / "apps.json").stat().st_mtime
        except OSError:
            return 0.0

    def _watch_existence_config(self) -> None:
        stamp = self._existence_config_stamp()
        if stamp != self._existence_config_mtime:
            self._existence_config_mtime = stamp
            self.refresh_existence_modules()

    def refresh_existence_modules(self) -> None:
        """Synchronise Nebula's visible surface with Existence's orbit map."""
        blend_connected = self._existence_module_connected("fusion_creator")
        singularity_connected = self._existence_module_connected("singularity")
        self.ui.blend_creator_dock.toggleViewAction().setVisible(blend_connected)
        self.ui.blend_creator_dock.toggleViewAction().setEnabled(blend_connected)
        setter = getattr(self.ui, "set_module_dock_available", None)
        if setter is not None:
            setter(self.ui.blend_creator_dock, blend_connected)
        else:
            self.ui.blend_creator_dock.setEnabled(blend_connected)
            self.ui.blend_creator_dock.setVisible(blend_connected)
        self.ui.actions["singularize"].setVisible(singularity_connected)
        self.ui.actions["singularize"].setEnabled(singularity_connected)
        pixel_art = getattr(self, "pixel_art", None)
        if pixel_art is not None:
            pixel_connected = self._existence_module_connected("pixel_art")
            pixel_art.set_available(pixel_connected)
            pixel_art.dock.toggleViewAction().setVisible(pixel_connected)
            if setter is not None:
                setter(pixel_art.dock, pixel_connected)
            else:
                pixel_art.dock.setVisible(pixel_connected)

    def _enforce_blend_module_visibility(self, visible: bool) -> None:
        """Empêche un workspace restauré de montrer un module débranché."""
        if visible and not self._existence_module_connected("fusion_creator"):
            # Différé : ne jamais masquer un dock pendant que Qt change d'onglet.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.ui.set_module_dock_available(self.ui.blend_creator_dock, False)
                              if hasattr(self.ui, "set_module_dock_available") else self.ui.blend_creator_dock.hide())

    def singularize_export(self) -> None:
        """Export the current composite through Singularity without its GUI."""
        if not self._existence_module_connected("singularity"):
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Singulariser en WebP", "", "WebP (*.webp)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".webp"):
            file_path += ".webp"
        singularity = Path("/home/deanos/Documents/Singularity/webready.py")
        if not singularity.exists():
            QMessageBox.warning(self, "Singularity", "Le moteur Singularity est introuvable.")
            return
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                temp_path = Path(handle.name)
            if not self.create_composite_image().save(str(temp_path), "PNG"):
                raise RuntimeError("Nebula n'a pas pu préparer le dessin courant.")
            result = subprocess.run(
                [sys.executable, str(singularity), "--headless", str(temp_path), file_path],
                cwd=str(singularity.parent), capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Singularity a refusé l'export.")
            self.statusBar().showMessage(f"Singularisé : {file_path}", 5000)
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            QMessageBox.warning(self, "Singularity", f"Export impossible : {exc}")
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

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

        elif extension in (".psd", ".psb"):
            from DOCUMENTS.format_psd import PSDFormat
            success = PSDFormat.save(self.canvas.document, self.current_file)

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
        elif extension in (".psd", ".psb"):
            report_export = getattr(self, "_report_psd_export", None)
            if callable(report_export):
                report_export(self.canvas.document)
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
            ".psd": "Photoshop document (*.psd)",
            ".psb": "Photoshop large document (*.psb)",
            ".png": "PNG (*.png)", ".tif": "TIFF (*.tif *.tiff)",
        }
        selected_filter = filter_for_format.get(default_format, native_filter)

        file_path, selected = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le document",
            start_directory,
            "Nebula document (*.nebula *.nbl);;"
            "Photoshop document (*.psd);;"
            "Photoshop large document (*.psb);;"
            "PNG (*.png);;"
            "JPEG (*.jpg *.jpeg);;"
            "TIFF (*.tif *.tiff);;"
            "BMP (*.bmp)",
            selected_filter,
        )

        if not file_path:
            return

        extension_by_filter = {
            native_filter: ".nebula", "Photoshop document (*.psd)": ".psd",
            "Photoshop large document (*.psb)": ".psb",
            "PNG (*.png)": ".png",
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

        elif extension in (".psd", ".psb"):
            success = PSDFormat.save(self.canvas.document, file_path)

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

        if extension in (".psd", ".psb"):
            report_export = getattr(self, "_report_psd_export", None)
            if callable(report_export):
                report_export(self.canvas.document)

        self.current_file = file_path
        self._remember_recent_document(file_path)
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

    def _recent_document_paths(self) -> list[str]:
        value = QSettings("CreativeSystem", "CreativeSystem").value("files/recent_documents", [], list)
        paths = value if isinstance(value, list) else []
        return [str(Path(path)) for path in paths if isinstance(path, str) and Path(path).is_file()]

    def _refresh_recent_documents(self) -> None:
        self.ui.home_page.set_recent_documents(self._recent_document_paths())

    def _remember_recent_document(self, file_path: str) -> None:
        path = str(Path(file_path).resolve())
        settings = QSettings("CreativeSystem", "CreativeSystem")
        paths = [item for item in self._recent_document_paths() if item != path]
        paths.insert(0, path)
        settings.setValue("files/recent_documents", paths[:8])
        self._refresh_recent_documents()

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

    def _on_layer_thumbnail_dirty(self, layer_id: str) -> None:
        """A stroke just finished on `layer_id` - its cached thumbnail (and,
        if a mask is being edited, its mask thumbnail) is stale."""
        self.ui.layers_dock.invalidate_thumb_cache(layer_id)
        self.refresh_layers()

    def refresh_layers(
        self
    ) -> None:
        # Debounce: coalesce multiple rapid calls into a single UI update
        # (e.g. brush stroke end + layer property change in the same frame).
        if not getattr(self, "_refresh_layers_pending", False):
            self._refresh_layers_pending = True
            QTimer.singleShot(0, self._do_refresh_layers)

    def _do_refresh_layers(self) -> None:
        self._refresh_layers_pending = False
        self.ui.refresh_layers(self.canvas.document)
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

            self.canvas.edit_layer_pixels()
            self.ui.layers_dock.set_mask_editing_layer_id(None)

            self.ui.update_layer_opacity(
                self.canvas.document
            )

            self.canvas.update()

    def edit_layer_mask_at(self, index: int) -> None:
        """Make the clicked mask thumbnail the active painting target."""
        if self.canvas.edit_layer_alpha_mask(index):
            layer = self.canvas.document.layers[index]
            self.ui.layers_dock.set_mask_editing_layer_id(layer.id)
            self.statusBar().showMessage(
                "Masque actif — noir masque, blanc révèle.", 4000
            )

    def add_layer(
        self
    ) -> None:

        self._with_layer_history(lambda: self.layer_manager.add_layer("Nouveau calque"),
                                 structure_only=True)

        self.refresh_layers()

    def duplicate_layer(
        self
    ) -> None:

        targets = self._selected_layer_targets()
        if not targets:
            return

        def duplicate_all():
            copies = []
            # Du haut vers le bas : une copie s'insère au-dessus de son original,
            # ce qui ne décale jamais les indices restant à traiter.
            for index in sorted(targets, reverse=True):
                layer = self.layer_manager.duplicate_layer(index)
                if layer is not None:
                    copies.append(layer)
            return copies

        copies = self._with_layer_history(duplicate_all, structure_only=True)

        if copies:

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

    def rename_layer_at(self, index: int) -> None:
        if not (0 <= index < len(self.canvas.document.layers)):
            return
        self.canvas.document.active_layer_index = index
        self.rename_layer()

    def _selected_layer_targets(self) -> list[int]:
        """Calques visés par une commande : la sélection multiple, sinon le calque actif."""
        document = self.canvas.document
        selected = [index for index in self.ui.layers_dock.get_selected_layer_indices()
                    if 0 <= index < len(document.layers)]
        if len(selected) > 1:
            return selected
        active = document.active_layer_index
        return [active] if 0 <= active < len(document.layers) else []

    def remove_layer(
        self
    ) -> None:

        targets = self._selected_layer_targets()
        document = self.canvas.document
        # Jamais tous les calques : un document garde au moins un calque.
        if len(targets) >= len(document.layers):
            targets = targets[:len(document.layers) - 1]
        before_layers = [document.layers[index] for index in targets]

        def prepare(history):
            for layer in before_layers:
                history.capture_layer_before(layer)

        def remove_all():
            removed = 0
            for index in sorted(targets, reverse=True):
                if self.layer_manager.remove_layer(index):
                    removed += 1
            return removed

        removed = self._with_layer_history(remove_all, structure_only=True, prepare=prepare)
        if removed:

            self.refresh_layers()
            self.canvas.prune_gpu_layers()
            # Sans ce message, l'utilisateur croit la suppression définitive.
            status_bar = getattr(self, "statusBar", None)
            if callable(status_bar):
                status_bar().showMessage(
                    ("Calque supprimé" if removed == 1 else f"{removed} calques supprimés")
                    + " — Ctrl+Z pour annuler.", 5000
                )

    def merge_selected_layers(self) -> None:
        """Fusionne une sélection de calques contigus en un seul (un pas d'annulation)."""
        document = self.canvas.document
        indices = sorted(index for index in self.ui.layers_dock.get_selected_layer_indices()
                         if 0 <= index < len(document.layers))
        if len(indices) < 2:
            return
        if indices != list(range(indices[0], indices[-1] + 1)):
            status_bar = getattr(self, "statusBar", None)
            if callable(status_bar):
                status_bar().showMessage(
                    "Sélectionnez des calques qui se suivent pour les fusionner.", 5000)
            return
        low, high = indices[0], indices[-1]

        def prepare(history):
            layers = document.layers[low:high + 1]
            keys = set()
            for layer in layers:
                layer.commit_image_cache()
                keys |= layer.tile_store.occupied_keys
            for layer in layers:
                history.capture_layer_before(layer, keys)

        def merge_all():
            merged = 0
            for index in range(high, low, -1):
                if not self.layer_manager.merge_down(index):
                    break
                merged += 1
            return merged

        if self._with_layer_history(merge_all, structure_only=True, prepare=prepare):
            self.refresh_layers()
            self.canvas.prune_gpu_layers()
            self.canvas.sync_gpu_layer()

    def reorder_layers_into_groups(self, order: list[int], targets: dict) -> None:
        """Glisser-déposer qui change aussi l'appartenance à un groupe (un pas d'annulation)."""
        document = self.canvas.document
        count = len(document.layers)
        if sorted(order) != list(range(count)):
            self.refresh_layers()      # dossiers repliés : permutation partielle, on restaure
            return
        moves = {document.layers[int(index)].id: group_id for index, group_id in targets.items()
                 if 0 <= int(index) < count}

        def operation():
            # Ordre + appartenance aux groupes en un seul passage : le miroir natif
            # n'est reconstruit qu'une fois, quand les groupes sont de nouveau contigus.
            self.layer_manager.reorder_layers(list(order), moves)
            return True

        if self._with_layer_history(operation, structure_only=True):
            self.canvas._projection_tile_signatures.clear()
            self.refresh_layers()
            self.canvas.update()

    def group_selected_layers(self) -> None:
        indices = self.ui.layers_dock.get_selected_layer_indices()
        if len(indices) < 2:
            return
        name, accepted = QInputDialog.getText(self, "Grouper les calques", "Nom du groupe :")
        if not accepted:
            return
        self.canvas.begin_history_action(structure_only=True)
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
            self.canvas.begin_history_action(structure_only=True)
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
        self.canvas.begin_history_action(structure_only=True)
        if not self.canvas.document.set_group_visibility(group.id, not group.visible):
            self.canvas.cancel_history_action()
            return
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def toggle_group_visibility_at(self, group_id: str) -> None:
        group = next((item for item in self.canvas.document.layer_groups if item.id == group_id), None)
        if group is None:
            return
        self.canvas.begin_history_action(structure_only=True)
        if not self.canvas.document.set_group_visibility(group_id, not group.visible):
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
        self.canvas.begin_history_action(structure_only=True)
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
        history = self.canvas.tile_history
        history.begin(self.canvas.document, structure_only=True)
        history.capture_layer_before(self.canvas.document.layers[index])
        if not self.layer_manager.remove_alpha_mask(index):
            self.canvas.cancel_history_action()
            return
        self.canvas.edit_layer_pixels()
        self.ui.layers_dock.set_mask_editing_layer_id(None)
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def apply_active_layer_mask(self) -> None:
        """Merge the mask into the layer pixels and remove it (destructive, undoable)."""
        index = self.canvas.document.active_layer_index
        if index < 0:
            return
        layer = self.canvas.document.layers[index]
        if layer.alpha_mask_store is None:
            return
        history = self.canvas.tile_history
        history.begin(self.canvas.document)
        history.capture_layer_before(layer)
        if not self.layer_manager.apply_alpha_mask(index):
            self.canvas.cancel_history_action()
            return
        self.ui.layers_dock.set_mask_editing_layer_id(None)
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def toggle_active_layer_mask_disabled(self) -> None:
        """Enable or disable the active layer mask without removing it."""
        index = self.canvas.document.active_layer_index
        if index < 0:
            return
        if not self.layer_manager.toggle_alpha_mask_disabled(index):
            return
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def invert_active_layer_mask(self) -> None:
        """Invert all pixels in the active layer mask (destructive, undoable)."""
        index = self.canvas.document.active_layer_index
        if index < 0:
            return
        layer = self.canvas.document.layers[index]
        if layer.alpha_mask_store is None:
            return
        history = self.canvas.tile_history
        history.begin(self.canvas.document)
        history.capture_layer_before(layer)
        if not self.layer_manager.invert_alpha_mask(index):
            self.canvas.cancel_history_action()
            return
        self.canvas.commit_history_action()
        self.canvas.reload_alpha_mask_edit_buffer()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()

    def add_adjustment_layer(self, kind: str) -> None:
        def _identity_lut():
            import numpy as np
            from DOCUMENTS.psd_reader import encode_lut
            axis = np.linspace(0.0, 1.0, 17, dtype=np.float32)
            blue, green, red = np.meshgrid(axis, axis, axis, indexing="ij")
            return encode_lut(17, np.stack((red, green, blue), axis=-1), name="Identité")

        """Insert a non-destructive adjustment layer with editable defaults."""
        defaults = {
            "curves": {"kind": "curves", "curves": {"points": [[0, 0], [128, 128], [255, 255]]}},
            "levels": {"kind": "levels", "levels": {"black": 0, "white": 255, "gamma": 1.0,
                                                           "output_black": 0, "output_white": 255}},
            "hue_saturation": {"kind": "hue_saturation", "hue_saturation": {
                "hue": 0.0, "saturation": 0.0, "lightness": 0.0}},
            "exposure": {"kind": "exposure", "exposure": {"exposure": 0.0, "offset": 0.0, "gamma": 1.0}},
            "brightness_contrast": {"kind": "brightness_contrast", "brightness_contrast": {
                "brightness": 0.0, "contrast": 0.0}},
            "vibrance": {"kind": "vibrance", "vibrance": {"vibrance": 0.0, "saturation": 0.0}},
            "invert": {"kind": "invert"},
            "threshold": {"kind": "threshold", "threshold": 128},
            "posterize": {"kind": "posterize", "posterize": 4},
            "color_balance": {"kind": "color_balance", "color_balance": {
                "shadows": [0.0, 0.0, 0.0], "midtones": [0.0, 0.0, 0.0], "highlights": [0.0, 0.0, 0.0]}},
            "parametric_curves": {"kind": "parametric_curves", "parametric_curves": {
                "black": 0.0, "shadows": 0.0, "midtones": 0.0, "highlights": 0.0, "white": 0.0}},
            "selective_color": {"kind": "selective_color", "selective_color": {"channels": {}}},
            "luminosity_mask": {"kind": "luminosity_mask", "luminosity_mask": {
                "mode": "lights", "amount": 1.0, "feather": 0.15, "invert": False}},
            "gradient_map": {"kind": "gradient_map", "gradient_map": {
                "reverse": False, "method": "Lnr ", "stops": [
                    {"location": 0.0, "midpoint": 0.5, "color": [0, 0, 0]},
                    {"location": 1.0, "midpoint": 0.5, "color": [255, 255, 255]}]}},
            "color_lookup": {"kind": "color_lookup", "color_lookup": _identity_lut()},
        }
        spec = defaults.get(str(kind))
        if spec is None:
            return
        self.canvas.begin_history_action(structure_only=True)
        names = {"gradient_map": "Courbe de transfert de dégradé",
                 "color_lookup": "Correspondance de couleur"}
        self.canvas.document.add_adjustment_layer(kind, names.get(str(kind)), spec=spec)
        self.canvas.commit_history_action()
        self.canvas._projection_tile_signatures.clear()
        self.refresh_layers()
        self.canvas.update()
        if kind in names:
            self.edit_adjustment_layer()

    def edit_adjustment_layer(self) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None or getattr(layer, "layer_kind", "raster") != "adjustment":
            return
        self.ui.adjustment_settings_dock.set_layer(layer)
        self.ui.adjustment_settings_dock.show()
        self.ui.adjustment_settings_dock.raise_()
        self.ui.adjustment_settings_dock.activateWindow()

    def _begin_adjustment_edit(self) -> None:
        if not getattr(self, "_adjustment_edit_active", False):
            self._adjustment_edit_active = True
            self.canvas.begin_history_action(structure_only=True)

    def _end_adjustment_edit(self) -> None:
        # Do not leave the last slider value waiting for the frame coalescer:
        # closing a drag must commit exactly what the user sees.
        self._flush_adjustment_preview()
        if getattr(self, "_adjustment_edit_active", False):
            self._adjustment_edit_active = False
            self.canvas.commit_history_action()

    def _apply_adjustment_live(self, spec: dict) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None or getattr(layer, "layer_kind", "raster") != "adjustment":
            return
        self._begin_adjustment_edit()
        # Spinboxes can emit dozens of values per second.  Recomposition is
        # expensive on dense documents, so publish at most once per rendered
        # frame while retaining the most recent value.
        self._pending_adjustment_spec = dict(spec)
        self._pending_adjustment_layer_id = layer.id
        timer = getattr(self, "_adjustment_preview_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(16)
            timer.timeout.connect(self._flush_adjustment_preview)
            self._adjustment_preview_timer = timer
        if not timer.isActive():
            timer.start()

    def _flush_adjustment_preview(self) -> None:
        spec = getattr(self, "_pending_adjustment_spec", None)
        layer_id = getattr(self, "_pending_adjustment_layer_id", None)
        self._pending_adjustment_spec = None
        self._pending_adjustment_layer_id = None
        if spec is None or layer_id is None:
            return
        layer = next((item for item in self.canvas.document.layers if item.id == layer_id), None)
        if layer is None or getattr(layer, "layer_kind", "raster") != "adjustment":
            return
        layer.adjustment = spec
        self.canvas._invalidate_projection_cache()
        self.canvas.update()

    def _begin_group_opacity_history(self) -> None:
        if not getattr(self, "_group_opacity_edit_active", False):
            self._group_opacity_edit_active = True
            self.canvas.begin_history_action(structure_only=True)

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
        # The per-tile projection signature already includes each group's
        # opacity (see Canvas._groups_static_signature), so the normal
        # signature diff on the next frame already detects and recomposites
        # exactly the tiles under this group - a full clear here forced every
        # visible+prefetch tile of the whole document to be rebuilt on every
        # single pixel of slider movement, the same "invalidate way more than
        # what changed" bug already fixed for mask painting. The equivalent
        # per-layer opacity slider (change_layer_opacity) never needed this
        # clear either.
        self.canvas.update()

    def move_layer_up(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if self._with_layer_history(lambda: self.layer_manager.move_layer_up(index),
                                    structure_only=True):

            self.refresh_layers()

    def move_layer_down(
        self
    ) -> None:

        index = (
            self.canvas.document.active_layer_index
        )

        if self._with_layer_history(lambda: self.layer_manager.move_layer_down(index),
                                    structure_only=True):

            self.refresh_layers()

    def reorder_layers(self, order: list[int]) -> None:
        """Commit a drag-and-drop layer stack change as a single undo step."""
        current = list(range(len(self.canvas.document.layers)))
        if order == current:
            return
        if self._with_layer_history(
            lambda: self.layer_manager.reorder_layers(order), structure_only=True
        ):
            self.canvas._projection_tile_signatures.clear()
            self.refresh_layers()
            self.canvas.update()

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

    def toggle_layer_visibility_at(self, index: int) -> None:
        """Toggle from the visibility dot without changing the active layer."""
        document = self.canvas.document
        if not (0 <= index < len(document.layers)):
            return
        selected = [item for item in self.ui.layers_dock.get_selected_layer_indices()
                    if 0 <= item < len(document.layers)]
        if index in selected and len(selected) > 1:
            # Clic sur l'œil d'un calque de la sélection : tous prennent le même état.
            wanted = not document.layers[index].visible

            def toggle_all():
                for item in selected:
                    if document.layers[item].visible != wanted:
                        self.layer_manager.toggle_visibility(item)
                return True

            self._with_layer_history(toggle_all, changed=True, dirty_only=True)
        else:
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
            self.canvas.begin_history_action(structure_only=True)

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

        # Keep both View-menu and Window-menu checkmarks in sync.
        self.ui.actions["show_tools"].setChecked(checked)
        self.ui.actions["show_tools_window"].setChecked(checked)

    def toggle_layers_panel(
        self,
        checked: bool = True
    ) -> None:

        self.ui.layers_panel.setVisible(
            checked
        )

        self.ui.actions["show_layers"].setChecked(checked)
        self.ui.actions["show_layers_window"].setChecked(checked)

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
                f"CreativeSystem {NEBULA_DISPLAY} — {filename}"
            )

        else:

            self.setWindowTitle(
                f"CreativeSystem {NEBULA_DISPLAY} — Nouveau dessin"
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
