from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QAction
from UI.models.action_registry import ActionRegistry


class MenuManager:

    def __init__(
        self,
        window: QMainWindow
    ) -> None:

        self.window: QMainWindow = window
        self.actions: dict[str, QAction] = {}
        self.menus = {}

        self.create_menus()
        self.registry = ActionRegistry(self.actions)
        self.registry.apply()

    def create_menus(self) -> None:

        menu_bar = self.window.menuBar()

        # FICHIER
        file_menu = menu_bar.addMenu("Fichier")
        self.menus["file"] = file_menu

        self.actions["new"] = file_menu.addAction("Nouveau…")
        self.actions["open"] = file_menu.addAction("Ouvrir…")
        self.actions["import_reference"] = file_menu.addAction("Importer une image de référence…")

        file_menu.addSeparator()

        self.actions["save"] = file_menu.addAction("Enregistrer")
        self.actions["save_as"] = file_menu.addAction("Enregistrer sous…")
        # Exporting is a file operation: it used to be the only real entry of
        # a near-empty Image menu.
        self.actions["export"] = file_menu.addAction("Exporter l'image…")
        self.actions["singularize"] = file_menu.addAction("Singulariser…")

        file_menu.addSeparator()

        self.actions["close"] = file_menu.addAction("Fermer le document")

        file_menu.addSeparator()

        self.actions["exit"] = file_menu.addAction("Quitter")

        # ÉDITION
        edit_menu = menu_bar.addMenu("Édition")
        self.menus["edit"] = edit_menu

        self.actions["undo"] = edit_menu.addAction("Annuler")
        self.actions["redo"] = edit_menu.addAction("Rétablir")
        edit_menu.addSeparator()
        self.actions["pressure_curve"] = edit_menu.addAction("Courbe de pression du stylet…")
        self.actions["preferences"] = edit_menu.addAction("Préférences…")

        # CALQUE
        layer_menu = menu_bar.addMenu("Calque")
        self.menus["layer"] = layer_menu

        self.actions["add_layer"] = layer_menu.addAction("Nouveau calque")
        self.actions["duplicate_layer"] = layer_menu.addAction("Dupliquer le calque")
        self.actions["rename_layer"] = layer_menu.addAction("Renommer…")
        self.actions["remove_layer"] = layer_menu.addAction("Supprimer le calque")
        layer_menu.addSeparator()
        self.actions["toggle_visibility"] = layer_menu.addAction("Afficher / masquer")
        self.actions["lock_layer"] = layer_menu.addAction("Verrouiller le calque")
        self.actions["lock_alpha"] = layer_menu.addAction("Verrouiller l'alpha")
        layer_menu.addSeparator()
        self.actions["move_layer_up"] = layer_menu.addAction("Monter")
        self.actions["move_layer_down"] = layer_menu.addAction("Descendre")
        layer_menu.addSeparator()
        transform_menu = layer_menu.addMenu("Transformer le calque")
        self.actions["rotate_90"] = transform_menu.addAction("Rotation 90°")
        self.actions["flip_horizontal"] = transform_menu.addAction("Miroir horizontal")
        self.actions["flip_vertical"] = transform_menu.addAction("Miroir vertical")
        layer_menu.addSeparator()
        self.actions["merge_down"] = layer_menu.addAction("Fusionner vers le bas")
        self.actions["merge_visible"] = layer_menu.addAction("Fusionner les calques visibles")
        self.actions["flatten"] = layer_menu.addAction("Aplatir l'image")

        # SÉLECTION
        select_menu = menu_bar.addMenu("Sélection")
        self.menus["select"] = select_menu
        self.actions["select_all"] = select_menu.addAction("Tout sélectionner")
        self.actions["deselect"] = select_menu.addAction("Désélectionner")
        self.actions["invert_selection"] = select_menu.addAction("Inverser la sélection")
        select_menu.addSeparator()
        self.actions["feather_selection"] = select_menu.addAction("Contour progressif…")
        self.actions["expand_selection"] = select_menu.addAction("Dilater…")
        self.actions["contract_selection"] = select_menu.addAction("Contracter…")
        select_menu.addSeparator()
        self.actions["select_color_range"] = select_menu.addAction("Plage de couleurs…")
        self.actions["select_alpha"] = select_menu.addAction("Depuis la transparence du calque")
        select_menu.addSeparator()
        self.actions["quick_mask"] = select_menu.addAction("Masque rapide (peindre la sélection)")
        self.actions["quick_mask"].setCheckable(True)

        # OUTILS — same groups and order as the tool rail.
        tools_menu = menu_bar.addMenu("Outils")
        self.menus["tools"] = tools_menu
        self.actions["brush"] = tools_menu.addAction("Pinceau")
        self.actions["smudge"] = tools_menu.addAction("Estompe")
        self.actions["blur"] = tools_menu.addAction("Flou")
        self.actions["sharpen"] = tools_menu.addAction("Netteté")
        self.actions["clone_stamp"] = tools_menu.addAction("Tampon de duplication")
        self.actions["clone_stamp"].setStatusTip("Maj+clic : définir la source")
        self.actions["eraser"] = tools_menu.addAction("Gomme")
        tools_menu.addSeparator()
        self.actions["fill"] = tools_menu.addAction("Pot de peinture")
        self.actions["gradient"] = tools_menu.addAction("Dégradé")
        self.actions["line"] = tools_menu.addAction("Ligne")
        self.actions["rectangle"] = tools_menu.addAction("Rectangle")
        self.actions["ellipse"] = tools_menu.addAction("Ellipse")
        self.actions["bezier"] = tools_menu.addAction("Courbe de Bézier")
        self.actions["text"] = tools_menu.addAction("Texte")
        tools_menu.addSeparator()
        self.actions["select_rectangle_tool"] = tools_menu.addAction("Sélection rectangulaire")
        self.actions["select_ellipse_tool"] = tools_menu.addAction("Sélection elliptique")
        self.actions["lasso_tool"] = tools_menu.addAction("Lasso")
        self.actions["magic_wand_tool"] = tools_menu.addAction("Baguette magique")
        tools_menu.addSeparator()
        self.actions["move_tool"] = tools_menu.addAction("Déplacer le calque")
        self.actions["transform_tool"] = tools_menu.addAction("Transformer")
        self.actions["crop"] = tools_menu.addAction("Recadrer")
        self.actions["reference"] = tools_menu.addAction("Images de référence")
        self.actions["picker"] = tools_menu.addAction("Pipette")
        tools_menu.addSeparator()
        self.actions["hand"] = tools_menu.addAction("Main")
        self.actions["zoom_view"] = tools_menu.addAction("Zoom")
        self.actions["rotate_view"] = tools_menu.addAction("Rotation de la vue")

        # AFFICHAGE
        view_menu = menu_bar.addMenu("Affichage")
        self.menus["view"] = view_menu

        self.actions["zoom_100"] = view_menu.addAction("Zoom 100 %")
        self.actions["fit_canvas"] = view_menu.addAction("Adapter à la fenêtre")
        self.actions["reset_view"] = view_menu.addAction("Réinitialiser la vue")
        view_menu.addSeparator()
        self.actions["rotate_canvas"] = view_menu.addAction("Tourner la vue de 15°")
        self.actions["reset_canvas_rotation"] = view_menu.addAction("Réinitialiser la rotation")
        self.actions["flip_canvas_horizontal"] = view_menu.addAction("Miroir de la vue (horizontal)")
        self.actions["flip_canvas_vertical"] = view_menu.addAction("Miroir de la vue (vertical)")
        view_menu.addSeparator()
        self.actions["symmetry_horizontal"] = view_menu.addAction("Symétrie horizontale")
        self.actions["symmetry_vertical"] = view_menu.addAction("Symétrie verticale")
        radial_menu = view_menu.addMenu("Symétrie radiale")
        for copies in (1, 2, 4, 6, 8, 12):
            label = "Désactivée" if copies == 1 else f"{copies} copies"
            action = radial_menu.addAction(label)
            action.setCheckable(True)
            self.actions[f"symmetry_radial_{copies}"] = action
        self.actions["place_radial_center"] = radial_menu.addAction("Placer le centre sur la toile")
        self.actions["place_radial_center"].setCheckable(True)
        self.actions["place_radial_center"].setStatusTip("Le prochain clic sur la toile place le centre de symétrie")
        self.actions["wrap_around"] = view_menu.addAction("Mode tuile (motif sans raccord)")
        self.actions["wrap_around"].setCheckable(True)
        assistant_menu = view_menu.addMenu("Assistants de dessin")
        self.actions["assistant_ruler"] = assistant_menu.addAction("Règle")
        self.actions["assistant_ellipse"] = assistant_menu.addAction("Ellipse")
        self.actions["assistant_perspective"] = assistant_menu.addAction("Perspective à un point")
        self.actions["assistant_perspective"].setStatusTip(
            "Maj+clic pour placer le point de fuite"
        )
        view_menu.addSeparator()
        # "\t" puts the key in the menu's shortcut column instead of the label
        # (Tab itself is handled by the canvas).
        self.actions["canvas_only"] = view_menu.addAction("Mode focus\tTab")
        for key in ("canvas_only", "flip_canvas_horizontal", "flip_canvas_vertical"):
            self.actions[key].setCheckable(True)
        for key in ("assistant_ruler", "assistant_ellipse", "assistant_perspective",
                    "symmetry_horizontal", "symmetry_vertical"):
            self.actions[key].setCheckable(True)

        # FENÊTRE
        window_menu = menu_bar.addMenu("Fenêtre")
        self.menus["window"] = window_menu

        # Historical entries duplicated Fenêtre ▸ Panneaux.  They stay
        # available as actions (compatibility) but live in no menu, so they
        # can no longer leave a dangling separator behind.
        for key, text in (
            ("show_tools", "Afficher le panneau Outils"),
            ("show_layers", "Afficher le panneau Calques"),
            ("show_brush", "Afficher le panneau Pinceau"),
            ("show_tools_window", "Panneau Outils"),
            ("show_layers_window", "Panneau Calques"),
        ):
            action = QAction(text, self.window)
            action.setCheckable(True)
            action.setChecked(True)
            action.setVisible(False)
            self.actions[key] = action

        # AIDE
        help_menu = menu_bar.addMenu("Aide")
        self.menus["help"] = help_menu
        self.actions["command_palette"] = help_menu.addAction("Rechercher une commande…")
        self.actions["shortcuts_help"] = help_menu.addAction("Raccourcis et gestes")
