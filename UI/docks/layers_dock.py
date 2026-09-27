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
    QAbstractItemView,
    QToolButton,
    QMenu,
    QLineEdit,
)

from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtGui import QPixmap

from DOCUMENTS.document import Document
from UI.widgets.layer_delegate import LayerItemDelegate, CLIP_INDENT
from UI.models.layer_drop import filter_rows, plan_layer_drop
from UI.theme.palette import COLORS


class LayerListWidget(QListWidget):
    """Layer list with a dedicated, small visibility target at the row start."""

    # callable(layer_index, group_id) -> bool, assigned by the dock
    folder_clip_target = None

    visibility_requested = Signal(int)
    folder_toggle_requested = Signal(str)
    clipping_requested = Signal(int)
    isolate_requested = Signal(int)
    lock_indicator_clicked = Signal(int, bool)
    rename_requested = Signal(int)
    mask_selected = Signal(int)
    group_visibility_requested_at = Signal(str)
    layer_order_dropped = Signal(list)
    # object et non dict : les clés sont des entiers, Qt ne sait pas convertir ce dict en QVariantMap.
    layer_group_drop = Signal(list, object)
    invalid_layer_drop = Signal()

    def dropEvent(self, event) -> None:
        """Convertit le nouvel ordre visuel en permutation + changements de groupe.

        Les lignes de dossiers sont virtuelles : seules les lignes de calques
        peuvent être déplacées.  Un calque lâché entre les enfants d'un dossier y
        entre, lâché en dehors il en sort (voir ``plan_layer_drop``).
        """
        def rows():
            result = []
            for row in range(self.count()):
                item = self.item(row)
                layer_index = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(layer_index, int):
                    flags = item.data(Qt.ItemDataRole.UserRole + 2) or {}
                    result.append(("layer", layer_index, flags.get("group_id")))
                else:
                    info = item.data(Qt.ItemDataRole.UserRole + 5) or {}
                    result.append(("group", item.data(Qt.ItemDataRole.UserRole + 4),
                                   info.get("parent_id")))
            return result

        moved = {item.data(Qt.ItemDataRole.UserRole) for item in self.selectedItems()
                 if isinstance(item.data(Qt.ItemDataRole.UserRole), int)}
        before = rows()
        before_layers = [row[1] for row in before if row[0] == "layer"]
        super().dropEvent(event)
        after = rows()
        after_layers = [row[1] for row in after if row[0] == "layer"]
        if len(before_layers) != len(after_layers) or sorted(before_layers) != sorted(after_layers):
            self.invalid_layer_drop.emit()
            return
        plan = plan_layer_drop(before, after, moved)
        if plan is None:
            self.invalid_layer_drop.emit()
            return
        order, changes = plan
        if changes:
            self.layer_group_drop.emit(order, changes)
        elif before_layers != after_layers:
            self.layer_order_dropped.emit(order)
        elif before != after:
            self.invalid_layer_drop.emit()

    def mouseReleaseEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        # Photoshop-style gesture: Alt-click precisely between two leaf rows
        # toggles clipping for the upper layer onto the lower layer.
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            point = event.position().toPoint()
            above = self.indexAt(point - QPoint(0, 6))
            below = self.indexAt(point + QPoint(0, 6))
            upper_index = above.data(Qt.ItemDataRole.UserRole) if above.isValid() else None
            lower_index = below.data(Qt.ItemDataRole.UserRole) if below.isValid() else None
            if isinstance(upper_index, int) and isinstance(lower_index, int) and upper_index == lower_index + 1:
                self.clipping_requested.emit(upper_index)
                event.accept()
                return
            # Layer above a folder header: clip onto the folder's whole content.
            lower_group = below.data(Qt.ItemDataRole.UserRole + 4) if below.isValid() else None
            if (isinstance(upper_index, int) and isinstance(lower_group, str)
                    and self.folder_clip_target is not None
                    and self.folder_clip_target(upper_index, lower_group)):
                self.clipping_requested.emit(upper_index)
                event.accept()
                return
        group_id = index.data(Qt.ItemDataRole.UserRole + 4) if index.isValid() else None
        if isinstance(group_id, str) and event.button() == Qt.MouseButton.LeftButton:
            depth_data = index.data(Qt.ItemDataRole.UserRole + 5) or {}
            arrow_right = 56 + int(depth_data.get("depth", 0)) * 16
            if event.position().x() < 28:
                self.group_visibility_requested_at.emit(group_id)
                event.accept()
                return
            if event.position().x() < arrow_right:
                self.folder_toggle_requested.emit(group_id)
                event.accept()
                return
        # Les indicateurs α / ◈ peints à droite sont désormais cliquables :
        # viser le petit bouton du bas n'est plus le seul moyen.
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            layer_index = index.data(Qt.ItemDataRole.UserRole)
            row_rect = self.visualRect(index)
            flags = index.data(Qt.ItemDataRole.UserRole + 2) or {}
            depth = int(flags.get("depth", 0))
            # Mirrors LayerItemDelegate.paint()'s exact geometry rather than
            # an independently-guessed offset: rect = option.rect.adjusted(
            # 2, 1, -2, -1), thumb_rect starts at rect.left() + 28 + offset
            # and is 36px wide, and mask_rect starts 10px past the
            # thumbnail's right edge - that's rect.left() + 73 + offset,
            # i.e. row_rect.left() + 75 + offset once the delegate's own +2
            # inset is folded in. `offset` itself gains CLIP_INDENT when the
            # row is a clipped layer, exactly like the delegate shifts the
            # thumbnail right to make room for the clip arrow.
            #
            # This hit zone used to be a bare `+68+depth*16` - no +2 inset,
            # and no clipping term at all. For an unclipped layer that left
            # ~7px of dead space just left of the real box (mostly
            # harmless), but for a CLIPPED layer with a mask the real box
            # sits a further CLIP_INDENT px to the right of where clicks
            # were being tested: well over half the visible mask thumbnail
            # didn't respond to a click at all, which is exactly what "je
            # n'arrive pas a editer le masque" looks like from the user's
            # side - clicking the thumbnail mostly just re-selected the
            # layer row instead of entering mask-edit mode.
            offset = depth * 16 + (CLIP_INDENT if flags.get("clipping") else 0)
            mask_left = row_rect.left() + 75 + offset
            if (isinstance(layer_index, int) and flags.get("has_mask")
                    and mask_left <= event.position().x() < mask_left + 38):
                self.mask_selected.emit(layer_index)
                event.accept()
                return
            if isinstance(layer_index, int) and event.position().x() >= row_rect.right() - 42:
                self.lock_indicator_clicked.emit(layer_index, bool(flags.get("lock_alpha")))
                event.accept()
                return
        # The delegate draws the visibility dot in the first 28 pixels.
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton and event.position().x() < 28:
            layer_index = index.data(Qt.ItemDataRole.UserRole)
            if isinstance(layer_index, int):
                # Alt+clic sur l'œil isole le calque, comme Photoshop et Krita.
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    self.isolate_requested.emit(layer_index)
                else:
                    self.visibility_requested.emit(layer_index)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class LayersDock(QDockWidget):

    blend_mode_changed = Signal(str)
    lock_requested = Signal()
    lock_alpha_requested = Signal()
    group_selected_requested = Signal()
    ungroup_selected_requested = Signal()
    group_visibility_requested = Signal()
    add_mask_requested = Signal()
    remove_mask_requested = Signal()
    apply_mask_requested = Signal()
    disable_mask_requested = Signal()
    invert_mask_requested = Signal()
    add_adjustment_requested = Signal(str)
    edit_adjustment_requested = Signal()
    visibility_requested = Signal(int)
    layer_order_changed = Signal(list)
    layer_group_drop_changed = Signal(list, object)
    merge_selected_requested = Signal()
    label_color_requested = Signal(object)
    clipping_requested = Signal(int)
    isolate_requested = Signal(int)
    lock_indicator_clicked = Signal(int, bool)
    mask_selected = Signal(int)
    rename_requested = Signal(int)
    group_visibility_requested_at = Signal(str)
    # ── Nouveaux signaux ──────────────────────────────────────────────────────
    duplicate_layer_requested = Signal()

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
        self._collapsed_groups: set[str] = set()
        self._mask_editing_layer_id: str | None = None
        # ── Cache miniatures : {layer_id: (cache_key, QPixmap)} ──────────────
        # cache_key = (tile_store generation hash, has_mask, mask_disabled)
        # Évite de matérialiser les TileStore à chaque refresh_layers()
        self._thumb_cache: dict[str, tuple] = {}

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

        # Recherche : indispensable dès que la pile dépasse une vingtaine de calques.
        self.layer_search = QLineEdit()
        self.layer_search.setPlaceholderText("Rechercher un calque…")
        self.layer_search.setClearButtonEnabled(True)
        self.layer_search.setObjectName("layerSearch")
        self.layer_search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.layer_search)

        # =====================================================
        # LISTE
        # =====================================================

        self.layer_list = LayerListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layer_list.setItemDelegate(LayerItemDelegate(self.layer_list))
        self.layer_list.setMouseTracking(True)
        self.layer_list.setSpacing(1)
        self.layer_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.layer_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.layer_list.setDropIndicatorShown(True)
        self.layer_list.visibility_requested.connect(self.visibility_requested)
        self.layer_list.folder_toggle_requested.connect(self._toggle_folder)
        self.layer_list.group_visibility_requested_at.connect(self.group_visibility_requested_at)
        self.layer_list.clipping_requested.connect(self.clipping_requested)
        self.layer_list.folder_clip_target = self._can_clip_onto_folder
        self.layer_list.isolate_requested.connect(self.isolate_requested)
        self.layer_list.lock_indicator_clicked.connect(self.lock_indicator_clicked)
        self.layer_list.setToolTip("Alt + clic entre deux calques : créer ou retirer un masque d'écrêtage")
        self.layer_list.itemDoubleClicked.connect(self._open_adjustment_on_double_click)
        self.layer_list.layer_order_dropped.connect(self.layer_order_changed)
        self.layer_list.layer_group_drop.connect(self.layer_group_drop_changed)
        self.layer_list.invalid_layer_drop.connect(self._restore_after_invalid_drop)
        # Clic droit → menu contextuel
        self.layer_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self._show_layer_context_menu)

        layout.addWidget(
            self.layer_list,
            1
        )

        # =====================================================
        # ACTIONS
        # =====================================================

        # Actions courantes : une seule barre, toujours à portée de main.
        primary_actions = QHBoxLayout()
        primary_actions.setSpacing(4)
        def action_button(text: str, tooltip: str) -> QToolButton:
            button = QToolButton(content)
            button.setText(text)
            button.setToolTip(tooltip)
            button.setObjectName("layerAction")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setFixedSize(28, 28)
            primary_actions.addWidget(button)
            return button

        self.add_layer_button = action_button("＋", "Nouveau calque")
        self.duplicate_layer_button = action_button("⧉", "Dupliquer le calque")
        # Le masque est une action principale, pas une option dissimulée.
        self.add_mask_button = action_button("◐", "Ajouter un masque de calque")
        self.remove_mask_button = action_button("◌", "Supprimer le masque de calque")
        self.remove_layer_button = action_button("⌫", "Supprimer le calque")
        self.remove_layer_button.setObjectName("layerActionDanger")

        # Organisation : les flèches et les options de groupe restent proches,
        # sans prendre la hauteur de cinq grands boutons.
        def organize_button(text: str, tooltip: str) -> QToolButton:
            button = QToolButton(content)
            button.setText(text); button.setToolTip(tooltip)
            button.setObjectName("layerAction")
            button.setFixedSize(28, 28)
            primary_actions.addWidget(button)
            return button

        self.group_layers_button = organize_button("G", "Grouper la sélection")
        self.ungroup_layers_button = organize_button("↗", "Dégrouper")
        self.lock_button = organize_button("▣", "Verrouiller le calque")
        self.lock_alpha_button = organize_button("α", "Verrou alpha")
        self.group_layers_button.clicked.connect(self.group_selected_requested)
        self.ungroup_layers_button.clicked.connect(self.ungroup_selected_requested)
        layout.addLayout(primary_actions)

        # Options moins fréquentes dans un menu explicite, au lieu de lignes
        # permanentes qui repoussent la liste de calques hors de la vue.
        self.layer_more_button = QToolButton(content)
        self.layer_more_button.setText("⋯")
        self.layer_more_button.setToolTip("Options de calque")
        self.layer_more_button.setFixedSize(28, 28)
        self.layer_more_button.setObjectName("layerMore")
        self.layer_more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self.layer_more_button)
        adjustment_menu = more_menu.addMenu("Ajouter un calque de réglage")
        clipping_action = more_menu.addAction("Activer / désactiver l'écrêtage du calque")
        curves_action = adjustment_menu.addAction("Courbes")
        levels_action = adjustment_menu.addAction("Niveaux")
        hue_action = adjustment_menu.addAction("Teinte / Saturation")
        exposure_action = adjustment_menu.addAction("Exposition")
        vibrance_action = adjustment_menu.addAction("Vibrance")
        balance_action = adjustment_menu.addAction("Balance des couleurs")
        invert_action = adjustment_menu.addAction("Inverser")
        threshold_action = adjustment_menu.addAction("Seuil")
        posterize_action = adjustment_menu.addAction("Postérisation")
        parametric_action = adjustment_menu.addAction("Courbes paramétriques")
        selective_action = adjustment_menu.addAction("Couleur sélective")
        luminosity_action = adjustment_menu.addAction("Masque de luminosité")
        edit_adjustment_action = adjustment_menu.addAction("Modifier le réglage actif…")
        more_menu.addSeparator()
        mask_menu = more_menu.addMenu("Masque de calque")
        apply_mask_action = mask_menu.addAction("Appliquer le masque")
        disable_mask_action = mask_menu.addAction("Activer / désactiver le masque")
        invert_mask_action = mask_menu.addAction("Inverser le masque")
        more_menu.addSeparator()
        self.group_visibility_action = more_menu.addAction("Afficher / masquer le groupe")
        self.layer_more_button.setMenu(more_menu)
        curves_action.triggered.connect(lambda: self.add_adjustment_requested.emit("curves"))
        levels_action.triggered.connect(lambda: self.add_adjustment_requested.emit("levels"))
        hue_action.triggered.connect(lambda: self.add_adjustment_requested.emit("hue_saturation"))
        exposure_action.triggered.connect(lambda: self.add_adjustment_requested.emit("exposure"))
        vibrance_action.triggered.connect(lambda: self.add_adjustment_requested.emit("vibrance"))
        balance_action.triggered.connect(lambda: self.add_adjustment_requested.emit("color_balance"))
        invert_action.triggered.connect(lambda: self.add_adjustment_requested.emit("invert"))
        threshold_action.triggered.connect(lambda: self.add_adjustment_requested.emit("threshold"))
        posterize_action.triggered.connect(lambda: self.add_adjustment_requested.emit("posterize"))
        parametric_action.triggered.connect(lambda: self.add_adjustment_requested.emit("parametric_curves"))
        selective_action.triggered.connect(lambda: self.add_adjustment_requested.emit("selective_color"))
        luminosity_action.triggered.connect(lambda: self.add_adjustment_requested.emit("luminosity_mask"))
        edit_adjustment_action.triggered.connect(self.edit_adjustment_requested)
        clipping_action.triggered.connect(lambda: self.clipping_requested.emit(self.get_selected_layer_index()))
        apply_mask_action.triggered.connect(self.apply_mask_requested)
        disable_mask_action.triggered.connect(self.disable_mask_requested)
        invert_mask_action.triggered.connect(self.invert_mask_requested)
        label_menu = more_menu.addMenu("Couleur du calque")
        for label, color in (("Aucune", None), ("Rouge", COLORS["label_red"]), ("Orange", COLORS["label_orange"]),
                             ("Jaune", COLORS["label_yellow"]), ("Vert", COLORS["label_green"]), ("Bleu", COLORS["label_blue"]),
                             ("Violet", COLORS["label_violet"]), ("Rose", COLORS["label_pink"])):
            action = label_menu.addAction(label)
            action.triggered.connect(lambda _checked=False, value=color: self.label_color_requested.emit(value))
        self.group_visibility_action.triggered.connect(self.group_visibility_requested)
        self.group_visibility_button = self.layer_more_button
        primary_actions.addWidget(self.layer_more_button)

        self.group_opacity_label = QLabel("Opacité du groupe")
        self.group_opacity_slider = QSlider(Qt.Orientation.Horizontal, content)
        self.group_opacity_slider.setRange(0, 100)
        self.group_opacity_slider.setValue(100)
        self.group_opacity_label.hide()
        self.group_opacity_slider.hide()

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

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("OPACITÉ"))
        opacity_row.addStretch()
        opacity_row.addWidget(self.layer_opacity_value)
        layout.addLayout(opacity_row)
        layout.addWidget(self.layer_opacity_slider)

        blend_header = QHBoxLayout()
        blend_header.addWidget(QLabel("MODE DE FUSION"))
        self.blend_mode_combo = QComboBox()
        self.blend_mode_combo.addItems([
            "Normal", "Darken", "Multiply", "Color Burn", "Lighten", "Screen",
            "Color Dodge", "Overlay", "Soft Light", "Hard Light", "Difference",
            "Exclusion", "Hue", "Saturation", "Color", "Luminosity",
        ])
        self.blend_mode_combo.currentIndexChanged.connect(lambda index: self.blend_mode_changed.emit(self.blend_mode_combo.itemText(index).lower().replace(" ", "_")))
        blend_header.addWidget(self.blend_mode_combo, 1)
        layout.addLayout(blend_header)
        self._document: Document | None = None
        self.lock_button.clicked.connect(self.lock_requested)
        self.lock_alpha_button.clicked.connect(self.lock_alpha_requested)
        self.add_mask_button.clicked.connect(self.add_mask_requested)
        self.remove_mask_button.clicked.connect(self.remove_mask_requested)
        self.layer_list.mask_selected.connect(self.mask_selected)

        # ── Connexion du bouton Dupliquer ─────────────────────────────────────
        self.duplicate_layer_button.clicked.connect(self.duplicate_layer_requested)

    # =========================================================
    # STYLE
    # =========================================================

    def create_style(self) -> None:
        """Use the application-wide Nebula stylesheet."""
        return

    # =========================================================
    # MENU CONTEXTUEL (clic droit)
    # =========================================================

    def _show_layer_context_menu(self, pos: QPoint) -> None:
        """Menu contextuel Krita/Photoshop sur le clic droit d'un calque."""
        item = self.layer_list.itemAt(pos)
        if item is None:
            return
        layer_index = item.data(Qt.ItemDataRole.UserRole)
        group_id = item.data(Qt.ItemDataRole.UserRole + 4)

        menu = QMenu(self)

        if isinstance(layer_index, int):
            # ── Calque raster ou d'ajustement ──────────────────────────────
            menu.addAction("Renommer…").triggered.connect(
                lambda: self.rename_requested.emit(layer_index))
            menu.addAction("Dupliquer").triggered.connect(self.duplicate_layer_requested)
            menu.addSeparator()

            flags = item.data(Qt.ItemDataRole.UserRole + 2) or {}
            vis_label = "Masquer" if item.data(Qt.ItemDataRole.UserRole + 1) else "Afficher"
            menu.addAction(vis_label).triggered.connect(
                lambda: self.visibility_requested.emit(layer_index))
            menu.addAction("Solo (Alt+clic œil)").triggered.connect(
                lambda: self.isolate_requested.emit(layer_index))

            lock_label = "Déverrouiller" if flags.get("locked") else "Verrouiller"
            menu.addAction(lock_label).triggered.connect(self.lock_requested)
            alpha_label = "Retirer verrou alpha" if flags.get("lock_alpha") else "Verrou alpha"
            menu.addAction(alpha_label).triggered.connect(self.lock_alpha_requested)

            base_word = "dossier" if self._clip_base_is_folder(layer_index) else "calque"
            clip_label = ("Retirer l'écrêtage" if flags.get("clipping")
                          else f"Écrêter sur le {base_word} en dessous")
            menu.addAction(clip_label).triggered.connect(
                lambda: self.clipping_requested.emit(layer_index))

            menu.addSeparator()

            # ── Masque ─────────────────────────────────────────────────────
            mask_sub = menu.addMenu("Masque de calque")
            mask_sub.addAction("Ajouter un masque").triggered.connect(self.add_mask_requested)
            mask_sub.addAction("Supprimer le masque").triggered.connect(self.remove_mask_requested)
            mask_sub.addAction("Appliquer le masque").triggered.connect(self.apply_mask_requested)
            mask_sub.addAction("Activer / désactiver").triggered.connect(self.disable_mask_requested)
            mask_sub.addAction("Inverser le masque").triggered.connect(self.invert_mask_requested)

            # ── Calques de réglage ─────────────────────────────────────────
            adj_sub = menu.addMenu("Calque de réglage")
            for kind, label in (
                ("curves", "Courbes"),
                ("levels", "Niveaux"),
                ("hue_saturation", "Teinte / Saturation"),
                ("exposure", "Exposition"),
                ("vibrance", "Vibrance"),
                ("color_balance", "Balance des couleurs"),
                ("invert", "Inverser"),
                ("threshold", "Seuil"),
                ("posterize", "Postérisation"),
                ("parametric_curves", "Courbes paramétriques"),
                ("selective_color", "Couleur sélective"),
                ("luminosity_mask", "Masque de luminosité"),
            ):
                adj_sub.addAction(label).triggered.connect(
                    lambda _c=False, k=kind: self.add_adjustment_requested.emit(k))

            menu.addSeparator()

            # ── Groupe ─────────────────────────────────────────────────────
            menu.addAction("Grouper la sélection").triggered.connect(self.group_selected_requested)
            menu.addAction("Dégrouper").triggered.connect(self.ungroup_selected_requested)

            menu.addSeparator()

            # ── Étiquette couleur ──────────────────────────────────────────
            label_sub = menu.addMenu("Étiquette couleur")
            for lbl, color in (
                ("Aucune", None),
                ("Rouge", COLORS["label_red"]),
                ("Orange", COLORS["label_orange"]),
                ("Jaune", COLORS["label_yellow"]),
                ("Vert", COLORS["label_green"]),
                ("Bleu", COLORS["label_blue"]),
                ("Violet", COLORS["label_violet"]),
                ("Rose", COLORS["label_pink"]),
            ):
                label_sub.addAction(lbl).triggered.connect(
                    lambda _c=False, v=color: self.label_color_requested.emit(v))

            selected = self.get_selected_layer_indices()
            if len(selected) > 1:
                menu.addSeparator()
                menu.addAction(f"Fusionner les {len(selected)} calques sélectionnés").triggered.connect(
                    self.merge_selected_requested)
            menu.addSeparator()
            menu.addAction("Supprimer").triggered.connect(
                lambda: self.layer_list.parent().parent()  # dock → app via signal chain
            )
            # Supprimer est géré via le bouton Supprimer existant (remove_layer_button)
            # Le signal est passé par le bouton; ici on l'émet directement.
            del menu.actions()[-1]  # retirer l'action vide précédente
            delete_action = menu.addAction(f"⌫  Supprimer les {len(selected)} calques" if len(selected) > 1 else "⌫  Supprimer le calque")
            delete_action.setObjectName("dangerAction")
            # Connect to remove_layer_button click which is already wired in application.py
            delete_action.triggered.connect(self.remove_layer_button.click)

        elif isinstance(group_id, str):
            # ── Groupe ─────────────────────────────────────────────────────
            menu.addAction("Afficher / masquer le groupe").triggered.connect(
                self.group_visibility_requested)
            menu.addAction("Dégrouper").triggered.connect(self.ungroup_selected_requested)

        if not menu.isEmpty():
            menu.exec(self.layer_list.mapToGlobal(pos))

    # =========================================================
    # CALQUES
    # =========================================================

    def _thumb_key(self, layer) -> tuple:
        """Clé de cache miniature : version de génération du TileStore + état masque."""
        try:
            gen = layer.tile_store._generation if hasattr(layer.tile_store, "_generation") else id(layer)
        except Exception:
            gen = id(layer)
        return (gen, layer.alpha_mask_store is not None, getattr(layer, "mask_disabled", False))

    def _get_thumb(self, layer) -> QPixmap:
        """Retourne la miniature mise en cache (36×36) du calque.

        Évite de matérialiser le TileStore complet à chaque appel de
        refresh_layers() — la miniature n'est recalculée que lorsque le
        contenu du calque a réellement changé.
        """
        key = self._thumb_key(layer)
        cached = self._thumb_cache.get(layer.id)
        if cached is not None and cached[0] == key:
            return cached[1]
        # Cache miss : matérialisation nécessaire
        img = layer.image.scaled(
            36, 36,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        px = QPixmap.fromImage(img)
        self._thumb_cache[layer.id] = (key, px)
        return px

    def _get_mask_thumb(self, layer) -> QPixmap | None:
        """Miniature du masque alpha, aussi mise en cache."""
        if layer.alpha_mask_store is None:
            return None
        cache_key = ("mask", self._thumb_key(layer))
        cached = self._thumb_cache.get(layer.id + "_mask")
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        materialized = layer.alpha_mask_grayscale()
        img = materialized.scaled(
            36, 36,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        px = QPixmap.fromImage(img)
        self._thumb_cache[layer.id + "_mask"] = (cache_key, px)
        return px

    def invalidate_thumb_cache(self, layer_id: str | None = None) -> None:
        """Force le recalcul de la miniature au prochain refresh.

        Appelé par le canvas après un coup de pinceau sur le calque actif.
        Sans ça, les miniatures restent figées même quand on peint.
        """
        if layer_id is None:
            self._thumb_cache.clear()
        else:
            self._thumb_cache.pop(layer_id, None)
            self._thumb_cache.pop(layer_id + "_mask", None)

    def _can_clip_onto_folder(self, layer_index: int, group_id: str) -> bool:
        """True when the layer sits directly above the folder in the same stack level."""
        document = self._document
        if document is None or not (0 < layer_index < len(document.layers)):
            return False
        group = next((g for g in document.layer_groups if g.id == group_id), None)
        if group is None:
            return False
        positions = {layer.id: i for i, layer in enumerate(document.layers)}
        members = [positions[i] for i in group.layer_ids if i in positions]
        if not members or max(members) != layer_index - 1 or layer_index in members:
            return False
        layer_id = document.layers[layer_index].id
        # Same level: the layer must live in the folder's parent (or at root).
        owners = [g for g in document.layer_groups if layer_id in g.layer_ids]
        owner_ids = {g.id for g in owners}
        parent = group.parent_id
        if parent is None:
            return not any(g.parent_id is None for g in owners)
        return parent in owner_ids and not any(
            g.parent_id == parent for g in owners if g.id != parent)

    def _clip_base_is_folder(self, layer_index: int) -> bool:
        document = self._document
        if document is None or not (0 < layer_index < len(document.layers)):
            return False
        below_id = document.layers[layer_index - 1].id
        own_id = document.layers[layer_index].id
        return any(below_id in g.layer_ids and own_id not in g.layer_ids
                   for g in document.layer_groups)

    def refresh_layers(
        self,
        document: Document
    ) -> None:

        self._document = document
        # Rebuilding QListWidget invalidates its viewport and normally resets
        # the vertical bar to zero.  A layer refresh happens during painting,
        # opacity changes and thumbnail updates, so losing the user's place in
        # a long stack is particularly disruptive.
        scroll_bar = self.layer_list.verticalScrollBar()
        previous_scroll = scroll_bar.value()
        # Les dossiers sont des lignes virtuelles ; dropEvent ne transmet que
        # les feuilles. Le geste reste donc disponible même avec des groupes.
        self._sync_drag_mode()
        # Une sélection multiple survit aux simples changements de propriété
        # (visibilité, verrou…) ; dès que la pile change, les indices ne sont
        # plus fiables et on repart de zéro.
        layer_ids = tuple(layer.id for layer in document.layers)
        kept_selection = (set(self.get_selected_layer_indices())
                          if layer_ids == getattr(self, "_last_layer_ids", None) else set())
        self._last_layer_ids = layer_ids

        self.layer_list.blockSignals(
            True
        )

        self.layer_list.clear()

        self._collapsed_groups.intersection_update({group.id for group in document.layer_groups})
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
        groups = {group.id: group for group in document.layer_groups}
        children = {group.id: [] for group in document.layer_groups}
        roots = []
        for group in document.layer_groups:
            (children[group.parent_id].append(group) if group.parent_id in groups else roots.append(group))

        def members(group):
            return [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]

        def add_leaf(index, depth=0, group_id=None):
            layer = document.layers[index]
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setData(Qt.ItemDataRole.UserRole + 1, layer.visible)
            item.setData(Qt.ItemDataRole.UserRole + 2, {"locked": layer.locked, "lock_alpha": layer.lock_alpha,
                                                        "clipping": layer.clipping, "depth": depth, "group_id": group_id,
                                                        "label_color": layer.label_color,
                                                        "has_mask": layer.alpha_mask_store is not None,
                                                        "mask_selected": layer.id == self._mask_editing_layer_id})
            # ── Miniature mise en cache — ne matérialise pas le TileStore si rien n'a changé ──
            item.setData(Qt.ItemDataRole.DecorationRole, self._get_thumb(layer))
            mask_px = self._get_mask_thumb(layer)
            if mask_px is not None:
                item.setData(Qt.ItemDataRole.UserRole + 3, mask_px)
            self.layer_list.addItem(item)

        def add_folder(group, depth=0):
            positions_in_group = members(group)
            if not positions_in_group:
                return
            collapsed = group.id in self._collapsed_groups
            item = QListWidgetItem(group.name)
            item.setData(Qt.ItemDataRole.UserRole + 4, group.id)
            item.setData(Qt.ItemDataRole.UserRole + 5, {"collapsed": collapsed, "visible": group.visible, "depth": depth,
                                                        "parent_id": group.parent_id if group.parent_id in groups else None})
            self.layer_list.addItem(item)
            if collapsed:
                return
            child_starts = {max(members(child)): child for child in children[group.id] if members(child)}
            covered = {position for child in children[group.id] for position in members(child)}
            for position in range(max(positions_in_group), min(positions_in_group) - 1, -1):
                child = child_starts.get(position)
                if child is not None:
                    add_folder(child, depth + 1)
                elif position not in covered:
                    add_leaf(position, depth + 1, group.id)

        root_starts = {max(members(group)): group for group in roots if members(group)}
        covered = {position for group in roots for position in members(group)}
        for index in range(len(document.layers) - 1, -1, -1):
            if index in root_starts:
                add_folder(root_starts[index])
            elif index not in covered:
                add_leaf(index)

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

        if len(kept_selection) > 1:
            for row in range(self.layer_list.count()):
                item = self.layer_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) in kept_selection:
                    item.setSelected(True)

        self.layer_list.blockSignals(
            False
        )

        self.update_layer_opacity(
            document
        )
        self.update_layer_properties(document)
        self._apply_filter()
        # Qt may clamp the value once the new item geometry exists, hence the
        # queued restore rather than assigning it before the event loop has
        # laid out the rebuilt rows.
        QTimer.singleShot(0, lambda value=previous_scroll: scroll_bar.setValue(value))

    # ── Recherche ─────────────────────────────────────────────────────────
    def _sync_drag_mode(self) -> None:
        # Réorganiser une liste filtrée donnerait une permutation partielle.
        filtering = bool(self.layer_search.text().strip()) if hasattr(self, "layer_search") else False
        self.layer_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop if filtering
                                        else QAbstractItemView.DragDropMode.InternalMove)

    def _on_search_changed(self, _text: str) -> None:
        self._sync_drag_mode()
        self._apply_filter()

    def _apply_filter(self) -> None:
        if not hasattr(self, "layer_search"):
            return
        text = self.layer_search.text()
        rows = []
        for row in range(self.layer_list.count()):
            item = self.layer_list.item(row)
            layer_index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(layer_index, int):
                flags = item.data(Qt.ItemDataRole.UserRole + 2) or {}
                rows.append(("layer", layer_index, flags.get("group_id"), item.text()))
            else:
                info = item.data(Qt.ItemDataRole.UserRole + 5) or {}
                rows.append(("group", item.data(Qt.ItemDataRole.UserRole + 4),
                             info.get("parent_id"), item.text()))
        visible = filter_rows(rows, text)
        for row in range(self.layer_list.count()):
            self.layer_list.item(row).setHidden(row not in visible)
        if text.strip() and self._document is not None:
            shown = sum(1 for position, row in enumerate(rows) if row[0] == "layer" and position in visible)
            self.layer_count.setText(f"{shown}/{len(self._document.layers)}")
        elif self._document is not None:
            self.layer_count.setText(str(len(self._document.layers)))

    def _toggle_folder(self, group_id: str) -> None:
        if group_id in self._collapsed_groups:
            self._collapsed_groups.remove(group_id)
        else:
            self._collapsed_groups.add(group_id)
        if self._document is not None:
            self.refresh_layers(self._document)

    def set_mask_editing_layer_id(self, layer_id: str | None) -> None:
        self._mask_editing_layer_id = layer_id
        if self._document is not None:
            self.refresh_layers(self._document)

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

    def _open_adjustment_on_double_click(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self.layer_list.setCurrentItem(item)
            if self._document is not None and 0 <= index < len(self._document.layers):
                if getattr(self._document.layers[index], "layer_kind", "raster") == "adjustment":
                    self.edit_adjustment_requested.emit()
                else:
                    self.rename_requested.emit(index)

    def _restore_after_invalid_drop(self) -> None:
        if self._document is not None:
            self.refresh_layers(self._document)

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

    def set_layer_opacity_value(
        self,
        value: int
    ) -> None:

        self.layer_opacity_value.setText(
            f"{value} %"
        )

    def update_layer_properties(self, document: Document) -> None:
        layer = document.get_active_layer()
        if layer is None:
            return
        group = document.group_for_layer(layer.id)
        self.group_opacity_label.setEnabled(group is not None)
        self.group_opacity_slider.setEnabled(group is not None)
        self.group_visibility_action.setEnabled(group is not None)
        self.group_visibility_action.setText(
            "Masquer le groupe" if group is not None and group.visible else "Afficher le groupe"
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
        self.lock_button.setText("▣" if layer.locked else "▢")
        self.lock_button.setToolTip("Déverrouiller le calque" if layer.locked else "Verrouiller le calque")
        self.lock_alpha_button.setText("α✓" if layer.lock_alpha else "α")
        self.lock_alpha_button.setToolTip("Retirer le verrou alpha" if layer.lock_alpha else "Verrou alpha")
