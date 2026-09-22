from PySide6.QtCore import (
    QObject,
    Signal,
    Qt,
)

from PySide6.QtWidgets import (
    QMainWindow,
    QLabel,
    QStackedWidget,
    QToolBar,
    QSpinBox,
    QComboBox,
    QMenu,
    QInputDialog,
)
from PySide6.QtCore import QSettings

from CANVAS.canvas import Canvas

from DOCUMENTS.document import Document

from UI.home.home_page import HomePage

from UI.docks.tools_dock import ToolsDock

from UI.docks.layers_dock import LayersDock
from DOCUMENTS.blend_presets import BlendPresetManager

from UI.menus.menu_manager import MenuManager

from UI.context.context_menu_manager import ContextMenuManager
from UI.docks.brush_presets_dock import BrushPresetsDock
from UI.docks.brush_panel_dock import BrushPanelDock
from UI.docks.tool_rail_dock import ToolRailDock
from UI.docks.color_dock import ColorDock
from UI.theme import ThemeManager
from UI.widgets.dock_title_bar import install_dock_title
from UI.dialogs import PreferencesDialog
from UI.models import WorkspaceManager


class CreativeSystemUI(QObject):

    home_new_requested = Signal()

    home_open_requested = Signal()

    def __init__(
        self,
        window: QMainWindow,
        canvas: Canvas
    ) -> None:

        super().__init__(
            window
        )

        self.window: QMainWindow = window

        self.canvas: Canvas = canvas
        self.canvas.history_restored.connect(self._sync_layer_controls)

        self.apply_professional_style()

        # -----------------------------------------------------
        # VUES
        # -----------------------------------------------------

        self.stack = QStackedWidget()

        self.home_page = HomePage()

        self.stack.addWidget(
            self.home_page
        )

        self.stack.addWidget(
            self.canvas
        )

        self.window.setCentralWidget(
            self.stack
        )

        self.home_page.new_document_requested.connect(
            self.home_new_requested.emit
        )

        self.home_page.open_document_requested.connect(
            self.home_open_requested.emit
        )

        # -----------------------------------------------------
        # COMPOSANTS
        # -----------------------------------------------------

        self.tools_dock: ToolsDock = ToolsDock(
            window,
            canvas
        )

        self.layers_dock: LayersDock = LayersDock(
            window
        )
        self.layers_dock.blend_mode_changed.connect(self._set_active_blend_mode)
        self.layers_dock.blend_parameter_changed.connect(self._set_active_blend_parameter)
        self.layers_dock.blend_parameter_edit_started.connect(self._begin_blend_parameter_edit)
        self.layers_dock.blend_parameter_edit_ended.connect(self._end_blend_parameter_edit)
        self.layers_dock.blend_preset_applied.connect(self._apply_active_blend_preset)

        self.brush_presets_dock: BrushPresetsDock = (
            BrushPresetsDock(
                canvas,
                window
            )
        )

        self.brush_presets_dock.preset_selected.connect(
            self.tools_dock.sync_from_canvas
        )
        canvas.tool_changed.connect(self.tools_dock.set_active_tool)

        self.brush_panel_dock = BrushPanelDock(canvas, window)
        self.brush_presets_dock.preset_selected.connect(
            self.brush_panel_dock.sync_from_canvas
        )
        canvas.brush_settings_changed.connect(
            self.brush_panel_dock.sync_from_canvas
        )
        canvas.brush_settings_changed.connect(
            self.tools_dock.sync_from_canvas
        )

        self.tool_rail_dock = ToolRailDock(canvas, window)
        self.color_dock = ColorDock(canvas, window)
        for dock, title in (
            (self.layers_dock, "Layers"),
            (self.brush_presets_dock, "Brush Presets"),
            (self.color_dock, "Color"),
        ):
            install_dock_title(dock, title)
        self.tool_rail_dock.color_button.clicked.connect(
            self.tools_dock.color_button.click
        )

        self.menu_manager: MenuManager = MenuManager(
            window
        )

        self.create_main_toolbar()
        icon_size = int(str(QSettings("CreativeSystem", "CreativeSystem").value(
            "interface/icon_size", "24 px")).split()[0])
        self.tool_rail_dock.set_icon_size(icon_size)
        from DOCUMENTS.blend_modes import set_composition_cache_limit
        cache_mb = QSettings("CreativeSystem", "CreativeSystem").value("cpu/cache_mb", 1024, int)
        set_composition_cache_limit(max(64, min(65536, int(cache_mb))) * 1024 * 1024)

        self.context_menu_manager: ContextMenuManager = (
            ContextMenuManager(
                window,
                canvas,
                self.layers_dock.layer_list,
                self.menu_manager
            )
        )

        # -----------------------------------------------------
        # INSTALLATION
        # -----------------------------------------------------

        self.install_docks()

        self.workspace_manager = WorkspaceManager(self.window)
        self.workspace_manager.set_docks(self._workspace_docks())
        self._initialize_workspaces()
        self.install_customization_menus()
        if QSettings("CreativeSystem", "CreativeSystem").value("general/restore_session", True, bool):
            self.workspace_manager.restore_session()
        self._workspace_visibility = [not dock.isHidden() for dock in self._workspace_docks()]
        self.workspace_manager.session_visibility = self._workspace_visibility
        for dock in self._workspace_docks():
            dock.visibilityChanged.connect(self._track_workspace_visibility)

        self.create_status_bar()

        # -----------------------------------------------------
        # COMPATIBILITÉ APPLICATION.PY
        # -----------------------------------------------------

        self.expose_widgets()

        self.actions = (
            self.menu_manager.actions
        )
        self._restore_custom_toolbar()

        # -----------------------------------------------------
        # DÉMARRAGE
        # -----------------------------------------------------

        self.show_home()

    def install_customization_menus(self) -> None:
        self.menu_manager.actions["preferences"].triggered.connect(self.open_preferences)
        window_menu = self.menu_manager.menus["window"]
        dockers = window_menu.addMenu("Dockers")
        for dock in (self.tool_rail_dock, self.brush_panel_dock, self.color_dock,
                     self.brush_presets_dock, self.layers_dock, self.tools_dock):
            dockers.addAction(dock.toggleViewAction())
        self.workspaces_menu = window_menu.addMenu("Workspaces")
        self.workspaces_menu.aboutToShow.connect(self._populate_workspaces_menu)
        self._populate_workspaces_menu()
        self.main_toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_toolbar.customContextMenuRequested.connect(self._show_toolbar_customizer)

    def _initialize_workspaces(self) -> None:
        """Create useful built-in layouts once, preserving user-saved layouts."""
        manager = self.workspace_manager
        existing = set(manager.names())
        if "Default" not in existing or manager.settings.value("workspaces/Default/visibility") is None:
            manager.save("Default")
        presets = {
            "Painting": (True, True, True, True, True),
            "Drawing": (True, False, False, False, True),
            "Minimal": (False, False, False, False, False),
        }
        original = [not dock.isHidden() for dock in self._workspace_docks()]
        for name, visibility in presets.items():
            if name in existing and manager.settings.value(f"workspaces/{name}/visibility") is not None:
                continue
            for dock, visible in zip(self._workspace_docks(), visibility):
                dock.setVisible(visible)
            manager.save(name)
        for dock, visible in zip(self._workspace_docks(), original):
            dock.setVisible(visible)

    def _workspace_docks(self):
        return (self.tool_rail_dock, self.brush_panel_dock, self.color_dock,
                self.brush_presets_dock, self.layers_dock)

    def _populate_workspaces_menu(self) -> None:
        menu = self.workspaces_menu
        menu.clear()
        for name in self.workspace_manager.names():
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, workspace=name: self.load_workspace(workspace))
        if menu.actions():
            menu.addSeparator()
        menu.addAction("Save current workspace…", self.save_workspace)
        menu.addAction("Reset workspace", self.reset_workspace)

    def _show_toolbar_customizer(self, position) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        excluded = {"brush", "eraser", "picker", "smudge"}
        candidates = [(key, action) for key, action in self.actions.items()
                      if key not in excluded and action.text()]
        configured = settings.value("toolbar/actions", [], list)
        menu = QMenu(self.main_toolbar)
        for key, action in candidates:
            item = menu.addAction(action.text().replace("&", ""))
            item.setCheckable(True)
            item.setChecked(key in configured)
            item.toggled.connect(lambda checked, action_key=key, source=action:
                                 self._set_toolbar_action(action_key, source, checked))
        menu.exec(self.main_toolbar.mapToGlobal(position))

    def _set_toolbar_action(self, key, action, enabled) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        configured = settings.value("toolbar/actions", [], list)
        configured = list(configured)
        if enabled and key not in configured:
            configured.append(key)
            self.main_toolbar.addAction(action)
        elif not enabled:
            configured = [item for item in configured if item != key]
            self.main_toolbar.removeAction(action)
        settings.setValue("toolbar/actions", configured)

    def _restore_custom_toolbar(self) -> None:
        settings = QSettings("CreativeSystem", "CreativeSystem")
        excluded = {"brush", "eraser", "picker", "smudge"}
        for key in settings.value("toolbar/actions", [], list):
            action = self.actions.get(key)
            if action is not None and key not in excluded:
                self.main_toolbar.addAction(action)

    def open_preferences(self) -> None:
        dialog = PreferencesDialog(self.canvas, self.actions, self.window)
        dialog.preference_changed.connect(self._apply_preference_setting)
        dialog.exec()

    def _apply_preference_setting(self, key: str, _value) -> None:
        if key in ("input/stabilization", "input/stabilization_amount"):
            settings = QSettings("CreativeSystem", "CreativeSystem")
            enabled = settings.value("input/stabilization", True, bool)
            amount = settings.value("input/stabilization_amount", 20, int) if enabled else 0
            slider = self.tools_dock.smoothing_slider
            slider.blockSignals(True)
            slider.setValue(max(0, min(100, amount)))
            slider.blockSignals(False)
            self.tools_dock.change_smoothing(slider.value())
        elif key == "canvas/background":
            self.canvas.canvas_background = str(_value)
            self.canvas.update()
        elif key == "canvas/zoom_behavior":
            self.canvas.zoom_behavior = str(_value)
        elif key == "canvas/antialias":
            self.canvas._apply_brush_settings(self.canvas.brush_settings.snapshot())
        elif key == "brush/spacing":
            self.canvas.set_brush_setting("spacing", max(1, min(500, int(_value))) / 100.0)
        elif key == "brush/show_cursor_preview":
            self.canvas.show_brush_cursor_preview = bool(_value)
            self.canvas.update()
        elif key == "interface/compact":
            ThemeManager.apply(self.window)
        elif key == "performance/use_gpu":
            self.canvas.use_gpu = bool(_value)
            self.canvas.update()
        elif key == "input/right_click_color_picker":
            self.canvas.right_click_color_picker = bool(_value)
        elif key == "performance/undo_steps":
            maximum = max(1, min(1000, int(_value)))
            history = self.canvas.tile_history
            history.set_max_steps(maximum)
            self.canvas.max_history = maximum
            self.canvas.history_index = history.index
        elif key == "performance/memory_limit_mb":
            memory_manager = getattr(self.window, "memory_manager", None)
            if memory_manager is not None:
                memory_manager.set_limit_mb(int(_value))
        elif key == "performance/scratch_directory":
            memory_manager = getattr(self.window, "memory_manager", None)
            if memory_manager is not None:
                memory_manager.set_scratch_directory(str(_value))
        elif key.startswith("tablet/"):
            if key == "tablet/pressure":
                self.canvas.tablet_pressure_enabled = bool(_value)
            elif key == "tablet/ignore_mouse_after_tablet":
                self.canvas.ignore_synthetic_mouse_after_tablet = bool(_value)
            self.canvas._apply_brush_settings(self.canvas.brush_settings.snapshot())
        elif key.startswith("autosave/"):
            configure = getattr(self.window, "_configure_autosave", None)
            if configure is not None:
                configure()
        elif key == "cpu/threads":
            configured = str(_value)
            count = 0 if configured == "Automatic" else int(configured)
            self.canvas.projection_worker.set_thread_count(count)
        elif key == "cpu/cache_mb":
            from DOCUMENTS.blend_modes import set_composition_cache_limit
            set_composition_cache_limit(max(64, min(65536, int(_value))) * 1024 * 1024)
        elif key == "interface/icon_size":
            size = int(str(_value).split()[0])
            self.tool_rail_dock.set_icon_size(size)

    def save_workspace(self) -> None:
        name, accepted = QInputDialog.getText(self.window, "Save Workspace", "Workspace name")
        if accepted and name.strip():
            self.workspace_manager.save(name)
            self._populate_workspaces_menu()

    def load_workspace(self, name: str) -> None:
        if not self.workspace_manager.load(name):
            # Built-ins initially capture the current stable layout and become
            # independently editable after their first save.
            self.workspace_manager.save(name)
        self._workspace_visibility = [not dock.isHidden() for dock in self._workspace_docks()]
        self.workspace_manager.session_visibility = self._workspace_visibility

    def reset_workspace(self) -> None:
        self.workspace_manager.reset()
        self._workspace_visibility = [not dock.isHidden() for dock in self._workspace_docks()]
        self.workspace_manager.session_visibility = self._workspace_visibility

    def _track_workspace_visibility(self, _visible: bool) -> None:
        if self.stack.currentWidget() is self.canvas:
            self._workspace_visibility = [not dock.isHidden() for dock in self._workspace_docks()]
            self.workspace_manager.session_visibility = self._workspace_visibility

    def apply_professional_style(self) -> None:
        """Apply the shared Nebula theme to the application window."""
        ThemeManager.apply(self.window)

    def create_main_toolbar(self) -> None:
        self.main_toolbar = QToolBar("Outils principaux", self.window)
        self.main_toolbar.setObjectName("MainToolbar")
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.window.addToolBar(Qt.TopToolBarArea, self.main_toolbar)

        self.toolbar_tool_actions = {}
        for name, label, callback in (
            ("brush", "Brush", self.canvas.tools.set_brush),
            ("eraser", "Eraser", self.canvas.tools.set_eraser),
            ("picker", "Picker", self.canvas.tools.set_picker),
            ("smudge", "Smudge", self.canvas.tools.set_smudge),
        ):
            action = self.main_toolbar.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(callback)
            self.toolbar_tool_actions[name] = action
        self._sync_active_tool("brush")
        self.canvas.tool_changed.connect(self._sync_active_tool)

        self.main_toolbar.addSeparator()
        self.main_toolbar.addWidget(QLabel(" Size "))
        self.toolbar_size = QSpinBox()
        self.toolbar_size.setRange(1, 1000)
        self.toolbar_size.setSuffix(" px")
        self.toolbar_size.setValue(round(self.canvas.get_cpp_brush_settings()["size"]))
        self.toolbar_size.valueChanged.connect(
            lambda value: self.canvas.set_brush_setting("size", float(value))
        )
        self.main_toolbar.addWidget(self.toolbar_size)

        self.main_toolbar.addWidget(QLabel(" Opacity "))
        self.toolbar_opacity = QSpinBox()
        self.toolbar_opacity.setRange(1, 100)
        self.toolbar_opacity.setSuffix(" %")
        self.toolbar_opacity.setValue(round(self.canvas.get_cpp_brush_settings()["opacity"] * 100))
        self.toolbar_opacity.valueChanged.connect(
            lambda value: self.canvas.set_brush_setting("opacity", value / 100.0)
        )
        self.main_toolbar.addWidget(self.toolbar_opacity)

        self.main_toolbar.addSeparator()
        self.toolbar_presets = QComboBox()
        self.toolbar_presets.addItem("Presets…")
        self.toolbar_presets.addItems(self.canvas.brush_preset_manager.list_presets())
        self.toolbar_presets.setToolTip("Preset du moteur C++")
        self.toolbar_presets.currentTextChanged.connect(
            self._load_toolbar_preset
        )
        self.main_toolbar.addWidget(self.toolbar_presets)

        spacer = QLabel("   CreativeCore C++   " if self.canvas.cpp_brush_enabled else "   CreativeCore indisponible   ")
        spacer.setObjectName("backendBadge")
        self.main_toolbar.addWidget(spacer)
        self.canvas.brush_settings_changed.connect(self._sync_toolbar)

    def _load_toolbar_preset(self, name: str) -> None:
        if name != "Presets…":
            self.canvas.load_cpp_brush_preset(name)

    def _sync_active_tool(self, tool_name: str) -> None:
        for name, action in self.toolbar_tool_actions.items():
            action.setChecked(name == tool_name)

    def _sync_toolbar(self, settings) -> None:
        for control, value in (
            (self.toolbar_size, round(float(settings["size"]))),
            (self.toolbar_opacity, round(float(settings["opacity"]) * 100)),
        ):
            blocked = control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(blocked)

    # =========================================================
    # VUES
    # =========================================================

    def show_home(
        self
    ) -> None:

        self.stack.setCurrentWidget(
            self.home_page
        )

        self.tools_dock.hide()

        self.layers_dock.hide()

        self.brush_presets_dock.hide()
        self.brush_panel_dock.hide()
        self.tool_rail_dock.hide()
        self.color_dock.hide()

    def show_workspace(
        self
    ) -> None:

        self.stack.setCurrentWidget(
            self.canvas
        )

        self.tools_dock.hide()

        for dock, visible in zip(self._workspace_docks(), self._workspace_visibility):
            dock.setVisible(visible)

        self.canvas.setFocus()

    # =========================================================
    # DOCKS
    # =========================================================

    def install_docks(
        self
    ) -> None:

        self.window.addDockWidget(
            self.tools_dock.area,
            self.tools_dock
        )

        self.window.addDockWidget(
            self.layers_dock.area,
            self.layers_dock
        )

        self.window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tool_rail_dock)
        self.window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.brush_panel_dock)
        self.window.splitDockWidget(
            self.tool_rail_dock, self.brush_panel_dock, Qt.Orientation.Horizontal
        )

        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.color_dock)
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.brush_presets_dock)
        self.window.splitDockWidget(
            self.color_dock, self.layers_dock, Qt.Orientation.Vertical
        )
        self.window.tabifyDockWidget(self.color_dock, self.brush_presets_dock)
        self.color_dock.raise_()

        self.window.tabifyDockWidget(self.brush_panel_dock, self.tools_dock)
        self.brush_panel_dock.raise_()

        self.window.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )

        self.window.setDockNestingEnabled(
            True
        )

        self.window.resizeDocks(
            [
                self.tools_dock,
                self.layers_dock,
            ],
            [
                330,
                285,
            ],
            Qt.Orientation.Horizontal
        )

    # =========================================================
    # STATUS BAR
    # =========================================================

    def create_status_bar(
        self
    ) -> None:

        self.zoom_label = QLabel(
            "100 %"
        )

        self.zoom_label.setObjectName(
            "valueLabel"
        )

        self.window.statusBar().addPermanentWidget(
            self.zoom_label
        )

    # =========================================================
    # COMPATIBILITÉ
    # =========================================================

    def expose_widgets(
        self
    ) -> None:

        # -----------------------------------------------------
        # DOCK OUTILS
        # -----------------------------------------------------

        self.left_panel = (
            self.tools_dock
        )

        self.new_button = (
            self.tools_dock.new_button
        )

        self.open_button = (
            self.tools_dock.open_button
        )

        self.save_button = (
            self.tools_dock.save_button
        )

        self.save_as_button = (
            self.tools_dock.save_as_button
        )

        self.brush_button = (
            self.tools_dock.brush_button
        )

        self.eraser_button = (
            self.tools_dock.eraser_button
        )

        self.picker_button = self.tools_dock.picker_button
        self.smudge_button = self.tools_dock.smudge_button

        self.move_button = (
            self.tools_dock.move_button
        )

        self.transform_button = (
            self.tools_dock.transform_button
        )

        self.undo_button = (
            self.tools_dock.undo_button
        )

        self.redo_button = (
            self.tools_dock.redo_button
        )

        self.color_button = (
            self.tools_dock.color_button
        )

        self.preset_combo = (
            self.tools_dock.preset_combo
        )

        self.brush_preview = (
            self.tools_dock.brush_preview
        )

        self.size_value = (
            self.tools_dock.size_value
        )

        self.size_slider = (
            self.tools_dock.size_slider
        )

        self.opacity_value = (
            self.tools_dock.opacity_value
        )

        self.opacity_slider = (
            self.tools_dock.opacity_slider
        )

        self.pressure_size_value = (
            self.tools_dock.pressure_size_value
        )

        self.pressure_size_slider = (
            self.tools_dock.pressure_size_slider
        )

        self.pressure_opacity_value = (
            self.tools_dock.pressure_opacity_value
        )

        self.pressure_opacity_slider = (
            self.tools_dock.pressure_opacity_slider
        )

        self.spacing_value = (
            self.tools_dock.spacing_value
        )

        self.spacing_slider = (
            self.tools_dock.spacing_slider
        )

        # -----------------------------------------------------
        # DOCK CALQUES
        # -----------------------------------------------------

        self.layers_panel = (
            self.layers_dock
        )

        self.layer_list = (
            self.layers_dock.layer_list
        )

        self.brush_presets_panel = (
            self.brush_presets_dock
        )

        self.add_layer_button = (
            self.layers_dock.add_layer_button
        )

        self.duplicate_layer_button = (
            self.layers_dock.duplicate_layer_button
        )

        self.rename_layer_button = (
            self.layers_dock.rename_layer_button
        )

        self.visibility_button = (
            self.layers_dock.visibility_button
        )

        self.move_up_button = (
            self.layers_dock.move_up_button
        )

        self.move_down_button = (
            self.layers_dock.move_down_button
        )

        self.remove_layer_button = (
            self.layers_dock.remove_layer_button
        )

        self.layer_opacity_value = (
            self.layers_dock.layer_opacity_value
        )

        self.layer_opacity_slider = (
            self.layers_dock.layer_opacity_slider
        )

    # =========================================================
    # CALQUES
    # =========================================================

    def refresh_layers(
        self,
        document: Document
    ) -> None:

        self.layers_dock.refresh_layers(
            document
        )

    def get_selected_layer_index(
        self
    ) -> int:

        return (
            self.layers_dock.get_selected_layer_index()
        )

    def update_layer_opacity(
        self,
        document: Document
    ) -> None:

        self.layers_dock.update_layer_opacity(
            document
        )
        self.layers_dock.update_layer_properties(document)

    def _set_active_blend_mode(self, mode: str) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is not None:
            self._begin_blend_parameter_edit()
            opposite_mix = float(layer.blend_parameters.get("opposite_mix", 0.0))
            layer.blend_mode = mode
            layer.blend_parameters = BlendPresetManager.default_parameters(mode)
            layer.blend_parameters["opposite_mix"] = opposite_mix
            self.layers_dock.update_layer_properties(self.canvas.document)
            self._end_blend_parameter_edit()

    def _apply_active_blend_preset(self, preset: dict) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        self._begin_blend_parameter_edit()
        layer.blend_mode = str(preset["mode"])
        params = dict(preset.get("parameters", {}))
        layer.opacity = max(0.0, min(1.0, float(params.pop("opacity", layer.opacity))))
        layer.blend_parameters = params
        preset_name = str(preset.get("name") or layer.blend_mode.replace("_", " ").title())
        self.canvas.document.blend_presets[preset_name] = {
            "mode": layer.blend_mode,
            "parameters": dict(preset.get("parameters", {})),
        }
        self.layers_dock.update_layer_properties(self.canvas.document)
        self.layers_dock.update_layer_opacity(self.canvas.document)
        self._end_blend_parameter_edit()

    def _set_active_blend_parameter(self, key: str, value: float) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is not None:
            if key == "opacity":
                layer.opacity = float(value)
                self.layers_dock.update_layer_opacity(self.canvas.document)
            else:
                layer.blend_parameters[key] = float(value)
            self.layers_dock.blend_preview.set_parameter(key, float(value))

    def _begin_blend_parameter_edit(self) -> None:
        history = getattr(self.canvas, "tile_history", None)
        if history is not None and history._pending is None:
            self.canvas.begin_history_action(dirty_only=True)

    def _end_blend_parameter_edit(self) -> None:
        history = getattr(self.canvas, "tile_history", None)
        if history is not None and history._pending is not None:
            self.canvas.commit_history_action()
        self.canvas.update()

    def _sync_layer_controls(self) -> None:
        self.layers_dock.refresh_layers(self.canvas.document)

    # =========================================================
    # VALEURS
    # =========================================================

    def set_brush_size_value(
        self,
        value: int
    ) -> None:

        self.tools_dock.set_brush_size_value(
            value
        )

    def set_brush_opacity_value(
        self,
        value: int
    ) -> None:

        self.tools_dock.set_brush_opacity_value(
            value
        )

    def set_pressure_size_value(
        self,
        value: int
    ) -> None:

        self.tools_dock.set_pressure_size_value(
            value
        )

    def set_pressure_opacity_value(
        self,
        value: int
    ) -> None:

        self.tools_dock.set_pressure_opacity_value(
            value
        )

    def set_spacing_value(
        self,
        value: int
    ) -> None:

        self.tools_dock.set_spacing_value(
            value
        )

    def set_layer_opacity_value(
        self,
        value: int
    ) -> None:

        self.layers_dock.set_layer_opacity_value(
            value
        )

    def set_color(
        self,
        color_name: str
    ) -> None:

        self.tools_dock.set_color(
            color_name
        )

    def set_zoom(
        self,
        zoom: float
    ) -> None:

        zoom_percent = int(
            zoom * 100
        )

        self.zoom_label.setText(
            f"{zoom_percent} %"
        )
