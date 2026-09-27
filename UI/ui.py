from PySide6.QtCore import (
    QObject,
    Signal,
    Qt,
    QSize,
    QTimer,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut

from PySide6.QtWidgets import (
    QMainWindow,
    QLabel,
    QStackedWidget,
    QToolBar,
    QSpinBox,
    QComboBox,
    QMenu,
    QInputDialog,
    QCheckBox,
    QPushButton,
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QToolButton,
    QWidget,
)
from PySide6.QtCore import QSettings

from CANVAS.canvas import Canvas

from DOCUMENTS.document import Document

from UI.home.home_page import HomePage

from UI.docks.tools_dock import ToolsDock

from UI.docks.layers_dock import LayersDock
from UI.docks.blend_creator_dock import BlendCreatorDock
from DOCUMENTS.blend_presets import BlendPresetManager

from UI.menus.menu_manager import MenuManager

from UI.context.context_menu_manager import ContextMenuManager
from UI.docks.brush_presets_dock import BrushPresetsDock
from UI.docks.brush_panel_dock import BrushPanelDock
from UI.docks.tool_rail_dock import ToolRailDock
from UI.docks.color_dock import ColorDock
from UI.docks.resource_dock import ResourceDock
from UI.docks.adjustment_settings_dock import AdjustmentSettingsDock
from UI.docks.assistants_dock import AssistantsDock
from UI.theme import ThemeManager
from UI.widgets.dock_title_bar import install_dock_title
from UI.dialogs import PreferencesDialog
from UI.models import WorkspaceManager
from UI.widgets.command_palette import CommandPalette, ShortcutSheet

# Version de l'agencement par défaut. L'incrémenter remplace une seule fois la
# session enregistrée et les espaces de travail intégrés par le nouvel agencement.
LAYOUT_VERSION = 2
BUILTIN_WORKSPACES_V1 = ("Painting", "Drawing", "Minimal")

# Outils qui utilisent le moteur de pinceau (taille / opacité / flux utiles).
PAINT_TOOLS = {"brush", "eraser", "smudge", "blur", "sharpen", "clone_stamp",
               "line", "rectangle", "ellipse", "bezier"}
TOOL_HINTS = {
    "brush": "Glisser pour peindre · la pression du stylet module le pinceau",
    "eraser": "Glisser pour effacer avec le pinceau actif",
    "smudge": "Glisser pour étirer la peinture",
    "blur": "Glisser pour flouter sous la pointe",
    "sharpen": "Glisser pour renforcer la netteté sous la pointe",
    "clone_stamp": "Maj+clic : définir la source · glisser : dupliquer",
    "fill": "Clic : remplir la zone de couleur",
    "gradient": "Glisser pour tracer un dégradé",
    "line": "Glisser pour tracer une ligne au pinceau actif",
    "rectangle": "Glisser pour tracer un rectangle au pinceau actif",
    "ellipse": "Glisser pour tracer une ellipse au pinceau actif",
    "bezier": "Glisser les deux poignées de la courbe",
    "text": "Clic : ajouter ou modifier un texte · Maj+glisser : déplacer",
    "select_rectangle": "Glisser : sélectionner · Maj : ajouter · Alt : soustraire · Maj+Alt : intersection",
    "select_ellipse": "Glisser : sélectionner · Maj : ajouter · Alt : soustraire · Maj+Alt : intersection",
    "lasso": "Dessiner le contour · Maj : ajouter · Alt : soustraire",
    "magic_wand": "Clic : sélectionner une couleur · Maj : ajouter · Alt : soustraire",
    "move": "Glisser pour déplacer le calque · flèches : décaler",
    "transform": "Coins : proportionnel (Maj = libre) · Alt : depuis le centre · hors du cadre : rotation · Entrée / Échap",
    "crop": "Glisser le cadre de recadrage",
    "reference": "Déplacer / redimensionner les images de référence · Suppr : retirer",
    "picker": "Clic : prélever la couleur composite",
    "hand": "Glisser pour se déplacer dans le document",
    "zoom_view": "Glisser pour zoomer",
    "rotate_view": "Glisser pour tourner la vue",
}


class CreativeSystemUI(QObject):

    home_new_requested = Signal()

    home_open_requested = Signal()
    home_recent_requested = Signal(str)

    def __init__(
        self,
        window: QMainWindow,
        canvas: Canvas,
        resource_manager=None,
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
        self.home_page.recent_document_requested.connect(self.home_recent_requested.emit)

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
        self.adjustment_settings_dock = AdjustmentSettingsDock(window)
        self.blend_creator_dock = BlendCreatorDock(window, resource_manager)
        self.layers_dock.blend_mode_changed.connect(self._set_active_blend_mode)
        self.blend_creator_dock.parameter_changed.connect(self._set_active_blend_parameter)
        self.blend_creator_dock.parameter_edit_started.connect(self._begin_blend_parameter_edit)
        self.blend_creator_dock.parameter_edit_ended.connect(self._end_blend_parameter_edit)
        self.blend_creator_dock.preset_applied.connect(self._apply_active_blend_preset)

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
        self.assistants_dock = AssistantsDock(window)
        self.assistants_dock.set_manager(canvas.assistants)
        self.resource_dock = ResourceDock(resource_manager, window, canvas) if resource_manager is not None else None
        if self.resource_dock is not None:
            self.resource_dock.blend_applied.connect(self._apply_active_blend_preset)
            # Bibliothèque centrale : pinceaux publiés par StarDust & co.
            self.resource_dock.brushes_synced.connect(self._on_library_brushes)
            self.brush_presets_dock.resource_manager = resource_manager
            self.blend_creator_dock.resources_changed.connect(self.resource_dock.refresh)
        for dock, title in (
            (self.layers_dock, "Calques"),
            (self.blend_creator_dock, "Fusion"),
            (self.brush_presets_dock, "Presets de pinceau"),
            (self.color_dock, "Couleur"),
            (self.adjustment_settings_dock, "Réglages"),
            (self.assistants_dock, "Assistants de dessin"),
        ):
            install_dock_title(dock, title)
            dock.setWindowTitle(title)
        if self.resource_dock is not None:
            install_dock_title(self.resource_dock, "Ressources")
            self.resource_dock.setWindowTitle("Ressources")
        for dock, title in ((self.tool_rail_dock, "Outils"), (self.brush_panel_dock, "Pinceau"),
                            (self.tools_dock, "Outils (classique)")):
            dock.setWindowTitle(title)
        self.tool_rail_dock.color_button.clicked.connect(
            self.tools_dock.color_button.click
        )

        self.menu_manager: MenuManager = MenuManager(
            window
        )

        self.create_main_toolbar()
        self.create_selection_options_bar()
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
        # restoreState() ne retrouve un panneau que par son objectName.
        from PySide6.QtWidgets import QDockWidget as _QDockWidget
        for _dock in self.window.findChildren(_QDockWidget):
            if not _dock.objectName():
                _dock.setObjectName(type(_dock).__name__)

        self.workspace_manager = WorkspaceManager(self.window)
        self.workspace_manager.set_docks(self._workspace_docks())
        migrated = self._migrate_layout()
        self._initialize_workspaces()
        self.install_customization_menus()
        crashed = self._previous_session_crashed()
        if (not migrated and not crashed
                and QSettings("CreativeSystem", "CreativeSystem").value("general/restore_session", True, bool)):
            self.workspace_manager.restore_session()
        self._workspace_visibility = self.workspace_manager._visibility()
        self.workspace_manager.session_visibility = self._workspace_visibility
        # Sauvegarde continue de l'agencement : un plantage ou un kill ne fait
        # plus perdre la disposition des panneaux.
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(1500)
        self._layout_save_timer.timeout.connect(self._autosave_layout)
        for dock in self._workspace_docks():
            dock.visibilityChanged.connect(self._track_workspace_visibility)
            dock.dockLocationChanged.connect(lambda *_: self._layout_save_timer.start())
            dock.topLevelChanged.connect(lambda *_: self._layout_save_timer.start())

        self.create_status_bar()
        self.install_productivity()

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
        dockers = window_menu.addMenu("Panneaux")
        self.dockers_menu = dockers
        for dock in (self.tool_rail_dock, self.brush_panel_dock, self.color_dock,
                     self.brush_presets_dock, self.layers_dock, self.blend_creator_dock,
                     self.adjustment_settings_dock, self.tools_dock, self.resource_dock,
                     self.assistants_dock):
            if dock is None:
                continue
            dockers.addAction(dock.toggleViewAction())
        self.workspaces_menu = window_menu.addMenu("Espaces de travail")
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
        # Un booléen par dock de _workspace_docks(), dans le même ordre :
        # rail, brush, couleur, presets, calques, blend, ressources.
        # zip() tronquait silencieusement et le dock Ressources n'était jamais
        # enregistré dans les workspaces intégrés.
        # Ordre : rail, pinceau, couleur, presets, calques, fusion, réglages, assistants, ressources
        presets = {
            "Peinture": (True, True, True, True, True, False, False, False, True),
            "Dessin": (True, False, True, False, True, False, False, True, False),
            "Retouche": (True, False, False, False, True, True, True, False, True),
            "Minimal": (True, False, False, False, False, False, False, False, False),
        }
        original = self.workspace_manager._visibility()
        for name, visibility in presets.items():
            if name in existing and manager.settings.value(f"workspaces/{name}/visibility") is not None:
                continue
            for dock, visible in zip(self._workspace_docks(), visibility):
                dock.setVisible(bool(visible))
            manager.save(name)
        for dock in self._workspace_docks():
            if dock.objectName() in original:
                dock.setVisible(bool(original[dock.objectName()]))

    def _workspace_docks(self):
        docks = (self.tool_rail_dock, self.brush_panel_dock, self.color_dock,
                 self.brush_presets_dock, self.layers_dock, self.blend_creator_dock,
                 self.adjustment_settings_dock, self.assistants_dock)
        return docks if self.resource_dock is None else docks + (self.resource_dock,)

    @staticmethod
    def _previous_session_crashed() -> bool:
        """Après un plantage, repartir de l'agencement d'origine (l'état
        enregistré peut être la cause) ; il reste récupérable via Espaces de travail."""
        import os
        from pathlib import Path
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        marker = Path(base) / "CreativeSystem" / "nebula" / "previous_session_crashed"
        if not marker.exists():
            return False
        try:
            marker.unlink()
        except OSError:
            pass
        settings = QSettings("CreativeSystem", "CreativeSystem")
        for key in ("geometry", "state", "visibility"):
            value = settings.value(f"window/{key}")
            if value is not None:
                settings.setValue(f"workspaces/Avant plantage/{key}", value)
        return True

    def _migrate_layout(self) -> bool:
        """Applique une seule fois le nouvel agencement (v2) : la session
        enregistrée et les espaces intégrés v1 décrivaient l'ancien encombrement."""
        settings = QSettings("CreativeSystem", "CreativeSystem")
        if int(settings.value("interface/layout_version", 1) or 1) >= LAYOUT_VERSION:
            return False
        for key in ("window/geometry", "window/state", "window/visibility"):
            settings.remove(key)
        for name in BUILTIN_WORKSPACES_V1 + ("Default",):
            settings.remove(f"workspaces/{name}")
        settings.setValue("interface/layout_version", LAYOUT_VERSION)
        return True

    def _populate_workspaces_menu(self) -> None:
        menu = self.workspaces_menu
        menu.clear()
        for name in self.workspace_manager.names():
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, workspace=name: self.load_workspace(workspace))
        if menu.actions():
            menu.addSeparator()
        menu.addAction("Enregistrer l'espace actuel…", self.save_workspace)
        menu.addAction("Réinitialiser l'agencement", self.reset_workspace)

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
        name, accepted = QInputDialog.getText(self.window, "Enregistrer l'espace de travail", "Nom")
        if accepted and name.strip():
            self.workspace_manager.save(name)
            self._populate_workspaces_menu()
            self._refresh_workspace_combo(name.strip())

    def load_workspace(self, name: str) -> None:
        if not self.workspace_manager.load(name):
            # Built-ins initially capture the current stable layout and become
            # independently editable after their first save.
            self.workspace_manager.save(name)
        self._workspace_visibility = self.workspace_manager._visibility()
        self.workspace_manager.session_visibility = self._workspace_visibility
        self._refresh_workspace_combo(name)

    def reset_workspace(self) -> None:
        self.workspace_manager.reset()
        self._workspace_visibility = self.workspace_manager._visibility()
        self.workspace_manager.session_visibility = self._workspace_visibility

    def _autosave_layout(self) -> None:
        if getattr(self, "_focus_restore", None) is not None or self.stack.currentWidget() is not self.canvas:
            return
        try:
            self.workspace_manager.save_session()
        except RuntimeError:
            pass

    def _track_workspace_visibility(self, _visible: bool) -> None:
        # Le mode focus masque tout temporairement : ne pas l'enregistrer comme
        # l'agencement voulu (sinon les panneaux restaient cachés au retour).
        if getattr(self, "_focus_restore", None) is not None:
            return
        if self.stack.currentWidget() is self.canvas:
            self._workspace_visibility = self.workspace_manager._visibility()
            self.workspace_manager.session_visibility = self._workspace_visibility
            self._layout_save_timer.start()

    def apply_professional_style(self) -> None:
        """Apply the shared Nebula theme to the application window."""
        ThemeManager.apply(self.window)

    def create_main_toolbar(self) -> None:
        """Barre d'options unique et contextuelle (comme Photoshop / Krita) :
        outil actif, réglages utiles à cet outil, espace de travail, recherche."""
        self.main_toolbar = QToolBar("Options de l'outil", self.window)
        self.main_toolbar.setObjectName("MainToolbar")
        self.main_toolbar.setMovable(False)
        self.main_toolbar.setIconSize(QSize(18, 18))
        self.window.addToolBar(Qt.TopToolBarArea, self.main_toolbar)
        bar = self.main_toolbar

        # Actions d'outils conservées pour compatibilité (le rail les remplace).
        self.toolbar_tool_actions = {}
        for name, label, callback in (
            ("brush", "Pinceau", self.canvas.tools.set_brush),
            ("eraser", "Gomme", self.canvas.tools.set_eraser),
            ("picker", "Pipette", self.canvas.tools.set_picker),
            ("smudge", "Estompe", self.canvas.tools.set_smudge),
        ):
            action = QAction(label, bar)
            action.setCheckable(True)
            action.triggered.connect(callback)
            self.toolbar_tool_actions[name] = action

        self.tool_header = QToolButton()
        self.tool_header.setObjectName("toolHeader")
        self.tool_header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.tool_header.setIconSize(QSize(18, 18))
        self.tool_header.setToolTip("Outil actif")
        bar.addWidget(self.tool_header)
        bar.addSeparator()

        settings = self.canvas.get_cpp_brush_settings()
        self._paint_actions = []
        self.toolbar_presets = QComboBox()
        self.toolbar_presets.setObjectName("presetCombo")
        self.toolbar_presets.addItem("Presets…")
        self.toolbar_presets.addItems(self.canvas.brush_preset_manager.list_presets())
        self.toolbar_presets.setToolTip("Preset de pinceau (moteur CreativeCore)")
        self.toolbar_presets.setMinimumWidth(150)
        self.toolbar_presets.currentTextChanged.connect(self._load_toolbar_preset)
        self._paint_actions.append(bar.addWidget(self.toolbar_presets))

        def slider_pair(label, minimum, maximum, value, suffix, apply):
            box = QWidget()
            box.setObjectName("optionPair")
            row = QHBoxLayout(box)
            row.setContentsMargins(6, 0, 2, 0)
            row.setSpacing(6)
            caption = QLabel(label)
            caption.setObjectName("optionCaption")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setFixedWidth(110)
            slider.setValue(value)
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSuffix(suffix)
            spin.setValue(value)
            spin.setFixedWidth(74)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(lambda v: (slider.blockSignals(True), slider.setValue(v), slider.blockSignals(False)))
            spin.valueChanged.connect(apply)
            row.addWidget(caption)
            row.addWidget(slider)
            row.addWidget(spin)
            self._paint_actions.append(bar.addWidget(box))
            return spin, slider

        self.toolbar_size, self.toolbar_size_slider = slider_pair(
            "Taille", 1, 1000, round(settings["size"]), " px",
            lambda value: self.canvas.set_brush_setting("size", float(value)))
        self.toolbar_opacity, self.toolbar_opacity_slider = slider_pair(
            "Opacité", 1, 100, round(settings["opacity"] * 100), " %",
            lambda value: self.canvas.set_brush_setting("opacity", value / 100.0))
        self.toolbar_flow, self.toolbar_flow_slider = slider_pair(
            "Flux", 1, 100, round(float(settings.get("flow", 1.0)) * 100), " %",
            lambda value: self.canvas.set_brush_setting("flow", value / 100.0))
        self.toolbar_flow.setToolTip("Quantité de peinture déposée par touche")

        # Lissage (stabilisateur) : 20 % par défaut faisait traîner le trait
        # derrière le stylet. Remis à 0 une seule fois ; réglable ici à tout moment.
        prefs = QSettings("CreativeSystem", "CreativeSystem")
        smoothing = self.tools_dock.smoothing_slider
        if not prefs.value("input/stabilization_default_v2", False, bool):
            prefs.setValue("input/stabilization_default_v2", True)
            smoothing.setValue(0)
        self.toolbar_smoothing, self.toolbar_smoothing_slider = slider_pair(
            "Lissage", 0, 100, smoothing.value(), " %", smoothing.setValue)
        self.toolbar_smoothing.setToolTip("Stabilisateur : lisse le trait mais le fait suivre le stylet avec du retard. "
                                          "0 % = réponse immédiate.")
        smoothing.valueChanged.connect(lambda v: (self.toolbar_smoothing.blockSignals(True),
                                                  self.toolbar_smoothing.setValue(v),
                                                  self.toolbar_smoothing_slider.setValue(v),
                                                  self.toolbar_smoothing.blockSignals(False)))

        self.tool_hint = QLabel("")
        self.tool_hint.setObjectName("toolHint")
        self._hint_action = bar.addWidget(self.tool_hint)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self._toolbar_tail = []
        self.workspace_combo = QComboBox()
        self.workspace_combo.setObjectName("workspaceCombo")
        self.workspace_combo.setToolTip("Espace de travail : change l'agencement des panneaux")
        self.workspace_combo.setMinimumWidth(120)
        self.workspace_combo.activated.connect(self._on_workspace_combo)
        self._toolbar_tail.append(bar.addWidget(self.workspace_combo))
        self.search_button = QPushButton("⌕  Rechercher   Ctrl+K")
        self.search_button.setObjectName("searchButton")
        self.search_button.setToolTip("Trouver n'importe quelle commande, outil ou panneau")
        self.search_button.clicked.connect(lambda: self.command_palette.open())
        self._toolbar_tail.append(bar.addWidget(self.search_button))

        # compat : badge du moteur, désormais affiché dans la barre d'état
        self.backend_badge = QLabel("CreativeCore C++" if self.canvas.cpp_brush_enabled else "CreativeCore indisponible")
        self.backend_badge.setObjectName("backendBadge")

        self._sync_active_tool(self.canvas.tools.current_tool)
        self.canvas.tool_changed.connect(self._sync_active_tool)
        self.canvas.brush_settings_changed.connect(self._sync_toolbar)

    # ---------------------------------------------------------------
    # Options bar for selection / transform tools (Photoshop-like)
    # ---------------------------------------------------------------

    SELECTION_TOOLS = ("select_rectangle", "select_ellipse", "lasso", "magic_wand")

    def create_selection_options_bar(self) -> None:
        from DOCUMENTS.selection import SelectionOperation
        # Les options de sélection/transformation vivent dans la même barre
        # d'options que le pinceau : une seule rangée, qui change selon l'outil.
        toolbar = self.main_toolbar
        tail = self._toolbar_tail[0]
        self.selection_options_bar = toolbar

        class _Inserter:
            """Insère avant la partie droite (espace de travail, recherche)."""
            def addWidget(self_, widget):
                return toolbar.insertWidget(tail, widget)

            def addSeparator(self_):
                return toolbar.insertSeparator(tail)
        bar = _Inserter()
        options = self.canvas.tools.selection_tools.options
        settings = QSettings("CreativeSystem", "CreativeSystem")
        options.anti_alias = settings.value("selection/anti_alias", True, bool)
        options.feather = int(settings.value("selection/feather", 0, int))
        options.tolerance = int(settings.value("selection/tolerance", 32, int))
        options.contiguous = settings.value("selection/contiguous", True, bool)
        options.sample_all_layers = settings.value("selection/sample_all_layers", False, bool)

        def save(key, value):
            QSettings("CreativeSystem", "CreativeSystem").setValue(f"selection/{key}", value)

        self._selection_widgets = {}
        # Mode buttons
        group = QButtonGroup(self.main_toolbar)
        group.setExclusive(True)
        mode_actions = []
        for label, tip, op in (
            ("Nouvelle", "Nouvelle sélection", SelectionOperation.REPLACE),
            ("+ Ajouter", "Ajouter à la sélection (Maj)", SelectionOperation.ADD),
            ("− Soustraire", "Soustraire de la sélection (Alt)", SelectionOperation.SUBTRACT),
            ("∩ Intersection", "Intersection avec la sélection (Maj+Alt)", SelectionOperation.INTERSECT),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setChecked(op == SelectionOperation.REPLACE)
            button.clicked.connect(lambda _=False, op=op: setattr(self.canvas, "selection_base_operation", op))
            group.addButton(button)
            mode_actions.append(bar.addWidget(button))
        mode_actions.append(bar.addSeparator())
        self._selection_widgets["modes"] = mode_actions

        feather_label = bar.addWidget(QLabel(" Contour progressif "))
        feather = QSpinBox()
        feather.setRange(0, 250)
        feather.setSuffix(" px")
        feather.setValue(options.feather)
        feather.valueChanged.connect(lambda v: (setattr(options, "feather", int(v)), save("feather", int(v))))
        self._selection_widgets["feather"] = [feather_label, bar.addWidget(feather)]

        anti_alias = QCheckBox("Lissage")
        anti_alias.setToolTip("Bords anticrénelés (anti-aliasing)")
        anti_alias.setChecked(options.anti_alias)
        anti_alias.toggled.connect(lambda v: (setattr(options, "anti_alias", bool(v)), save("anti_alias", bool(v))))
        self._selection_widgets["anti_alias"] = [bar.addWidget(anti_alias)]

        wand = [bar.addSeparator(), bar.addWidget(QLabel(" Tolérance "))]
        tolerance = QSpinBox()
        tolerance.setRange(0, 255)
        tolerance.setValue(options.tolerance)
        tolerance.valueChanged.connect(lambda v: (setattr(options, "tolerance", int(v)), save("tolerance", int(v))))
        wand.append(bar.addWidget(tolerance))
        contiguous = QCheckBox("Pixels contigus")
        contiguous.setChecked(options.contiguous)
        contiguous.toggled.connect(lambda v: (setattr(options, "contiguous", bool(v)), save("contiguous", bool(v))))
        wand.append(bar.addWidget(contiguous))
        sample_all = QCheckBox("Échantillonner tous les calques")
        sample_all.setChecked(options.sample_all_layers)
        sample_all.toggled.connect(lambda v: (setattr(options, "sample_all_layers", bool(v)), save("sample_all_layers", bool(v))))
        wand.append(bar.addWidget(sample_all))
        self._selection_widgets["wand"] = wand

        transform = [bar.addWidget(QLabel(
            " Coins : proportionnel (Maj = libre) · Alt : depuis le centre · hors du cadre : rotation (Maj = 15°) "))]
        commit = QPushButton("✓ Valider")
        commit.setProperty("primary", True)
        commit.setToolTip("Appliquer la transformation (Entrée)")
        commit.clicked.connect(lambda: (self.canvas.commit_free_transform(), self.canvas.setFocus()))
        cancel = QPushButton("✕ Annuler")
        cancel.setToolTip("Annuler la transformation (Échap)")
        cancel.clicked.connect(lambda: (self.canvas.cancel_free_transform(), self.canvas.setFocus()))
        transform += [bar.addWidget(commit), bar.addWidget(cancel)]
        self._selection_widgets["transform"] = transform

        self.canvas.tool_changed.connect(self._sync_selection_options_bar)
        self._sync_selection_options_bar(self.canvas.tools.current_tool)

    def _sync_selection_options_bar(self, tool_name: str) -> None:
        is_selection = tool_name in self.SELECTION_TOOLS
        is_transform = tool_name == "transform"
        visible = {
            "modes": is_selection,
            "feather": is_selection,
            "anti_alias": is_selection and tool_name != "select_rectangle",
            "wand": tool_name == "magic_wand",
            "transform": is_transform,
        }
        for key, actions in self._selection_widgets.items():
            for action in actions:
                action.setVisible(visible[key])

    def _load_toolbar_preset(self, name: str) -> None:
        if name != "Presets…":
            self.canvas.load_cpp_brush_preset(name)

    def _sync_active_tool(self, tool_name: str) -> None:
        for name, action in self.toolbar_tool_actions.items():
            action.setChecked(name == tool_name)
        rail = getattr(self, "tool_rail_dock", None)
        spec = {n: t for n, _x, t in getattr(rail, "TOOL_SPECS", ())} if rail is not None else {}
        label = spec.get(tool_name, tool_name.replace("_", " ").capitalize())
        self.tool_header.setText(label.split(" — ")[0])
        if rail is not None:
            self.tool_header.setIcon(rail.icon_for(tool_name))
        paint = tool_name in PAINT_TOOLS
        for action in self._paint_actions:
            action.setVisible(paint)
        hint = TOOL_HINTS.get(tool_name, "")
        self.tool_hint.setText(hint)
        self._hint_action.setVisible(bool(hint) and not paint and tool_name not in self.SELECTION_TOOLS
                                     and tool_name != "transform")
        if hasattr(self, "status_hint"):
            self.status_hint.setText(hint)

    def _sync_toolbar(self, settings) -> None:
        for control, value in (
            (self.toolbar_size, round(float(settings["size"]))),
            (self.toolbar_opacity, round(float(settings["opacity"]) * 100)),
            (self.toolbar_flow, round(float(settings.get("flow", 1.0)) * 100)),
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
        # L'accueil reste épuré : pas de barre d'options ni de panneaux.
        for dock in self._workspace_docks() if hasattr(self, "workspace_manager") else ():
            dock.hide()
        if hasattr(self, "main_toolbar"):
            self.main_toolbar.hide()

    def show_workspace(
        self
    ) -> None:

        self.stack.setCurrentWidget(
            self.canvas
        )

        self.tools_dock.hide()

        self._focus_restore = None
        settings = QSettings("CreativeSystem", "CreativeSystem")
        if self.resource_dock is not None and not settings.value("interface/resources_restored_v2", False, bool):
            settings.setValue("interface/resources_restored_v2", True)
            QTimer.singleShot(0, self.reveal_resources)
        if self.resource_dock is not None and not settings.value("interface/resources_restored_v1", False, bool):
            # Réparation unique : le panneau Ressources avait pu être enregistré
            # comme masqué par le mode focus.
            settings.setValue("interface/resources_restored_v1", True)
            self._workspace_visibility = dict(self._workspace_visibility)
            self._workspace_visibility[self.resource_dock.objectName()] = True
        for dock in self._workspace_docks():
            if dock.objectName() in self._workspace_visibility:
                dock.setVisible(self._workspace_visibility[dock.objectName()])
        if self.resource_dock is not None and self.window.dockWidgetArea(self.resource_dock) == Qt.DockWidgetArea.NoDockWidgetArea:
            self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.resource_dock)
            self.window.tabifyDockWidget(self.color_dock, self.resource_dock)
        self.main_toolbar.show()
        self._refresh_document_info()

        self.canvas.setFocus()

    # =========================================================
    # DOCKS
    # =========================================================

    def install_docks(
        self
    ) -> None:
        """Agencement par défaut, pensé pour peindre :

        gauche  : rail d'outils | Pinceau (onglet Outils classique)
        droite  : [Couleur · Presets · Ressources · Assistants]
                  [Calques · Réglages · Fusion]
        Deux groupes seulement, au lieu de sept onglets empilés.
        """
        window = self.window
        window.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )
        window.setDockNestingEnabled(True)
        window.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)

        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tool_rail_dock)
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.brush_panel_dock)
        window.splitDockWidget(self.tool_rail_dock, self.brush_panel_dock, Qt.Orientation.Horizontal)
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tools_dock)
        window.tabifyDockWidget(self.brush_panel_dock, self.tools_dock)
        self.brush_panel_dock.raise_()

        right = Qt.DockWidgetArea.RightDockWidgetArea
        window.addDockWidget(right, self.color_dock)
        window.addDockWidget(right, self.layers_dock)
        window.splitDockWidget(self.color_dock, self.layers_dock, Qt.Orientation.Vertical)

        top_group = [self.brush_presets_dock, self.assistants_dock]
        if self.resource_dock is not None:
            top_group.insert(1, self.resource_dock)
        for dock in top_group:
            window.addDockWidget(right, dock)
            window.tabifyDockWidget(self.color_dock, dock)
        window.addDockWidget(right, self.adjustment_settings_dock)
        window.tabifyDockWidget(self.layers_dock, self.adjustment_settings_dock)
        # Fusion est un module Existence : son panneau n'entre dans l'agencement
        # que lorsqu'il est branché (voir set_module_dock_available).
        window.addDockWidget(right, self.blend_creator_dock)
        window.tabifyDockWidget(self.layers_dock, self.blend_creator_dock)
        self.color_dock.raise_()
        self.layers_dock.raise_()

        window.resizeDocks([self.color_dock, self.layers_dock], [360, 480], Qt.Orientation.Vertical)
        window.resizeDocks([self.color_dock, self.brush_panel_dock], [320, 250], Qt.Orientation.Horizontal)

    # =========================================================
    # STATUS BAR
    # =========================================================

    def create_status_bar(
        self
    ) -> None:
        status = self.window.statusBar()
        status.setSizeGripEnabled(False)
        self.status_hint = QLabel(TOOL_HINTS.get(self.canvas.tools.current_tool, ""))
        self.status_hint.setObjectName("statusHint")
        status.addWidget(self.status_hint, 1)
        self.document_label = QLabel("")
        self.document_label.setObjectName("valueLabel")
        status.addPermanentWidget(self.document_label)
        self.backend_label = QLabel(self.backend_badge.text())
        self.backend_label.setObjectName("backendBadge")
        status.addPermanentWidget(self.backend_label)
        # Le zoom est cliquable : menu des vues courantes.
        self.zoom_label = QToolButton()
        self.zoom_label.setObjectName("zoomButton")
        self.zoom_label.setText("100 %")
        self.zoom_label.setToolTip("Zoom — clic : vues rapides")
        self.zoom_label.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        zoom_menu = QMenu(self.zoom_label)
        for key in ("zoom_100", "fit_canvas", "reset_canvas_rotation", "flip_canvas_horizontal"):
            action = self.menu_manager.actions.get(key)
            if action is not None:
                zoom_menu.addAction(action)
        self.zoom_label.setMenu(zoom_menu)
        status.addPermanentWidget(self.zoom_label)
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(800)
        self._info_timer.timeout.connect(self._refresh_document_info)
        self._info_timer.start()

    def set_module_dock_available(self, dock, available: bool) -> None:
        """Retire complètement (onglet compris) le panneau d'un module débranché.

        Masquer seulement le dock laissait son onglet cliquable ; le re-masquer
        pendant le changement d'onglet faisait planter Qt (SIGSEGV)."""
        # Jamais pendant la construction de la fenêtre ni au milieu d'un
        # événement Qt : on applique au prochain tour de boucle.
        QTimer.singleShot(0, lambda: self._apply_module_dock(dock, available))

    def _apply_module_dock(self, dock, available: bool) -> None:
        window = self.window
        try:
            in_layout = window.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea
        except RuntimeError:
            return
        if available:
            if not in_layout:
                window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                window.tabifyDockWidget(self.layers_dock, dock)
            dock.setEnabled(True)
        else:
            dock.setEnabled(False)
            if in_layout:
                window.removeDockWidget(dock)
            dock.hide()

    def _refresh_document_info(self) -> None:
        try:
            document = self.canvas.document
            layers = len(getattr(document, "layers", []) or [])
            self.document_label.setText(f"{document.width} × {document.height} px  ·  {layers} calque(s)")
            self.set_zoom(float(getattr(self.canvas, "zoom", 1.0)))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    # =========================================================
    # PRODUCTIVITÉ : recherche, aide, mode focus
    # =========================================================

    def install_productivity(self) -> None:
        actions = self.menu_manager.actions
        self.command_palette = CommandPalette(self.window)
        actions["command_palette"].triggered.connect(self.command_palette.open)
        actions["shortcuts_help"].triggered.connect(self.show_shortcuts)
        tools = self.canvas.tools
        for key, callback in (("move_tool", tools.set_move), ("transform_tool", tools.set_transform),
                              ("select_rectangle_tool", tools.set_rectangle_selection),
                              ("select_ellipse_tool", tools.set_ellipse_selection),
                              ("lasso_tool", tools.set_lasso), ("magic_wand_tool", tools.set_magic_wand)):
            actions[key].triggered.connect(callback)
        # Tab = mode focus (tous les panneaux), seulement quand le canvas a le focus
        # pour ne pas gêner la saisie dans les champs.
        self._focus_restore = None
        self._focus_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Tab), self.canvas)
        self._focus_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._focus_shortcut.activated.connect(self.toggle_focus_mode)
        self._refresh_workspace_combo()
        if self.resource_dock is not None:
            reveal = QAction("Afficher les Ressources", self.window)
            reveal.setShortcut(QKeySequence("Ctrl+Shift+R"))
            reveal.triggered.connect(self.reveal_resources)
            window_menu = self.menu_manager.menus["window"]
            first = window_menu.actions()[0] if window_menu.actions() else None
            window_menu.insertAction(first, reveal)
            actions["show_resources"] = reveal
            self.resource_dock.sync_central_library()
            self._library_timer = QTimer(self)
            self._library_timer.setInterval(3000)
            self._library_timer.timeout.connect(self._watch_library)
            self._library_timer.start()

    def reveal_resources(self) -> None:
        """Affiche le panneau Ressources quoi qu'il arrive : ré-ancré s'il flottait
        hors écran, remis dans l'agencement s'il en était sorti, onglet au premier plan."""
        dock = self.resource_dock
        if dock is None:
            return
        window = self.window
        if dock.isFloating():
            dock.setFloating(False)
        if window.dockWidgetArea(dock) == Qt.DockWidgetArea.NoDockWidgetArea:
            window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            window.tabifyDockWidget(self.color_dock, dock)
        dock.setEnabled(True)
        dock.show()
        dock.raise_()
        if hasattr(self, "_workspace_visibility"):
            self._workspace_visibility = dict(self._workspace_visibility)
            self._workspace_visibility[dock.objectName()] = True
            self.workspace_manager.session_visibility = self._workspace_visibility

    def _on_library_brushes(self, names) -> None:
        self.brush_presets_dock.refresh()
        combo = self.toolbar_presets
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Presets…")
        combo.addItems(self.canvas.brush_preset_manager.list_presets())
        combo.blockSignals(False)
        self.window.statusBar().showMessage(
            f"Bibliothèque : {len(names)} pinceau(x) disponible(s) — " + ", ".join(list(names)[:3]), 5000)

    def _watch_library(self) -> None:
        """Rafraîchit le panneau quand une autre app (StarDust…) publie."""
        manager = getattr(self.resource_dock, "manager", None) if self.resource_dock is not None else None
        library = getattr(manager, "library", None)
        if library is None:
            return
        try:
            stamp = library.index_path.stat().st_mtime
        except OSError:
            return
        if stamp != getattr(self, "_library_stamp", None):
            first = getattr(self, "_library_stamp", None) is None
            self._library_stamp = stamp
            if not first:
                self.resource_dock.sync_central_library()
                self.resource_dock.refresh()

    def toggle_focus_mode(self) -> None:
        """Masque tous les panneaux et la barre d'options, puis restaure exactement l'état précédent."""
        docks = [d for d in self._workspace_docks() if d is not None]
        if self._focus_restore is None:
            self._focus_restore = [(dock, not dock.isHidden()) for dock in docks]
            for dock in docks:
                dock.hide()
            self.main_toolbar.hide()
            self.window.statusBar().showMessage("Mode focus — Tab pour revenir", 2500)
        else:
            for dock, visible in self._focus_restore:
                dock.setVisible(visible)
            self.main_toolbar.show()
            self._focus_restore = None
        self.canvas.setFocus()

    def show_shortcuts(self) -> None:
        gestures = (
            ("Tab", "Mode focus : masquer / afficher tous les panneaux"),
            ("Ctrl+K", "Rechercher une commande, un outil, un panneau"),
            ("Espace (maintenir)", "Se déplacer dans le document"),
            ("Ctrl+0 / Ctrl+1", "Réinitialiser la rotation / zoom 100 %"),
            ("Ctrl+5 / Ctrl+6", "Miroir de vue / tourner de 15°"),
            ("Clic droit ou appui long sur le rail", "Autres outils du groupe"),
        )
        ShortcutSheet(self.window, (("Gestes", gestures),)).exec()

    def _refresh_workspace_combo(self, current: str | None = None) -> None:
        combo = getattr(self, "workspace_combo", None)
        if combo is None or not hasattr(self, "workspace_manager"):
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Espace…")
        combo.addItems(self.workspace_manager.names())
        combo.insertSeparator(combo.count())
        combo.addItem("Enregistrer l'espace actuel…")
        combo.addItem("Réinitialiser l'agencement")
        index = combo.findText(current) if current else -1
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _on_workspace_combo(self, index: int) -> None:
        text = self.workspace_combo.itemText(index)
        if text == "Enregistrer l'espace actuel…":
            self.save_workspace()
            self._refresh_workspace_combo()
        elif text == "Réinitialiser l'agencement":
            self.reset_workspace()
            self._refresh_workspace_combo()
        elif index > 0 and text:
            self.load_workspace(text)

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

        self.undo_button = (
            self.tools_dock.undo_button
        )

        self.redo_button = (
            self.tools_dock.redo_button
        )

        self.color_button = (
            self.tools_dock.color_button
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

        self.add_layer_button = (
            self.layers_dock.add_layer_button
        )

        self.duplicate_layer_button = (
            self.layers_dock.duplicate_layer_button
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
        self.blend_creator_dock.set_layer(document)
        self.adjustment_settings_dock.set_layer(document.get_active_layer())

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
        self.blend_creator_dock.set_layer(document)
        self.adjustment_settings_dock.set_layer(document.get_active_layer())

    def _set_active_blend_mode(self, mode: str) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is not None:
            self._begin_blend_parameter_edit()
            opposite_mix = float(layer.blend_parameters.get("opposite_mix", 0.0))
            layer.blend_mode = mode
            layer.blend_parameters = BlendPresetManager.default_parameters(mode)
            layer.blend_parameters["opposite_mix"] = opposite_mix
            self.layers_dock.update_layer_properties(self.canvas.document)
            self.blend_creator_dock.set_layer(self.canvas.document)
            self._end_blend_parameter_edit()

    def _apply_active_blend_preset(self, preset: dict) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is None:
            return
        self._begin_blend_parameter_edit()
        layer.blend_mode = str(preset["mode"])
        params = dict(preset.get("parameters", {}))
        if preset.get("graph") is not None:
            layer.blend_graph = dict(preset["graph"])
        layer.opacity = max(0.0, min(1.0, float(params.pop("opacity", layer.opacity))))
        layer.blend_parameters = params
        preset_name = str(preset.get("name") or layer.blend_mode.replace("_", " ").title())
        self.canvas.document.blend_presets[preset_name] = {
            "mode": layer.blend_mode,
            "parameters": dict(preset.get("parameters", {})),
            "graph": dict(preset.get("graph", {})),
        }
        self.layers_dock.update_layer_properties(self.canvas.document)
        self.layers_dock.update_layer_opacity(self.canvas.document)
        self.blend_creator_dock.set_layer(self.canvas.document)
        self._end_blend_parameter_edit()

    def _set_active_blend_parameter(self, key: str, value: float) -> None:
        layer = self.canvas.document.get_active_layer()
        if layer is not None:
            if key == "opacity":
                layer.opacity = float(value)
                self.layers_dock.update_layer_opacity(self.canvas.document)
            else:
                layer.blend_parameters[key] = float(value)
            self.blend_creator_dock.preview.set_parameter(key, float(value))

    def _begin_blend_parameter_edit(self) -> None:
        history = getattr(self.canvas, "tile_history", None)
        if history is not None and history._pending is None:
            # Blend mode and parameters are layer metadata, not raster edits.
            try:
                self.canvas.begin_history_action(structure_only=True)
            except TypeError as error:
                # Keep lightweight UI test doubles and older embedders usable;
                # the real Canvas always exposes the structural argument.
                if "structure_only" not in str(error):
                    raise
                self.canvas.begin_history_action()

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

