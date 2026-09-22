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

        self.actions["new"] = file_menu.addAction("Nouveau")
        self.actions["open"] = file_menu.addAction("Ouvrir...")
        self.actions["import_reference"] = file_menu.addAction("Importer une image de référence...")

        file_menu.addSeparator()

        self.actions["save"] = file_menu.addAction("Enregistrer")
        self.actions["save_as"] = file_menu.addAction("Enregistrer sous...")

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
        self.actions["preferences"] = edit_menu.addAction("Preferences…")

        # IMAGE
        image_menu = menu_bar.addMenu("Image")

        self.actions["export"] = image_menu.addAction(
            "Exporter l'image..."
        )

        # CALQUE
        layer_menu = menu_bar.addMenu("Calque")

        self.actions["add_layer"] = layer_menu.addAction(
            "Nouveau calque"
        )

        self.actions["duplicate_layer"] = layer_menu.addAction(
            "Dupliquer"
        )

        self.actions["rename_layer"] = layer_menu.addAction(
            "Renommer"
        )

        self.actions["toggle_visibility"] = layer_menu.addAction(
            "Afficher / Masquer"
        )

        layer_menu.addSeparator()

        self.actions["move_layer_up"] = layer_menu.addAction(
            "Monter"
        )

        self.actions["move_layer_down"] = layer_menu.addAction(
            "Descendre"
        )

        self.actions["remove_layer"] = layer_menu.addAction(
            "Supprimer"
        )
        layer_menu.addSeparator()
        self.actions["rotate_90"] = layer_menu.addAction("Rotation 90°")
        self.actions["flip_horizontal"] = layer_menu.addAction("Miroir horizontal")
        self.actions["flip_vertical"] = layer_menu.addAction("Miroir vertical")
        self.actions["merge_down"] = layer_menu.addAction("Fusionner vers le bas")
        self.actions["merge_visible"] = layer_menu.addAction("Fusionner les visibles")
        self.actions["flatten"] = layer_menu.addAction("Aplatir l'image")
        self.actions["lock_layer"] = layer_menu.addAction("Verrouiller le calque")
        self.actions["lock_alpha"] = layer_menu.addAction("Verrouiller l'alpha")

        # OUTILS
        tools_menu = menu_bar.addMenu("Outils")

        self.actions["brush"] = tools_menu.addAction("Pinceau")
        self.actions["eraser"] = tools_menu.addAction("Gomme")
        self.actions["picker"] = tools_menu.addAction("Pipette")
        self.actions["smudge"] = tools_menu.addAction("Smudge")
        self.actions["clone_stamp"] = tools_menu.addAction("Clone Stamp — Maj+clic pour définir la source")
        self.actions["reference"] = tools_menu.addAction("Sélectionner une référence")
        self.actions["text"] = tools_menu.addAction("Texte éditable")
        self.actions["blur"] = tools_menu.addAction("Blur")
        self.actions["sharpen"] = tools_menu.addAction("Sharpen")
        self.actions["bezier"] = tools_menu.addAction("Courbe de Bézier")
        self.actions["fill"] = tools_menu.addAction("Pot de peinture")
        self.actions["gradient"] = tools_menu.addAction("Dégradé")
        self.actions["line"] = tools_menu.addAction("Ligne")
        self.actions["rectangle"] = tools_menu.addAction("Rectangle")
        self.actions["ellipse"] = tools_menu.addAction("Ellipse")
        self.actions["crop"] = tools_menu.addAction("Crop")
        tools_menu.addSeparator()
        self.actions["hand"] = tools_menu.addAction("Main")
        self.actions["zoom_view"] = tools_menu.addAction("Zoom")
        self.actions["rotate_view"] = tools_menu.addAction("Rotation de vue")

        select_menu = menu_bar.addMenu("Sélection")
        self.menus["select"] = select_menu
        self.actions["select_all"] = select_menu.addAction("Tout sélectionner")
        self.actions["deselect"] = select_menu.addAction("Désélectionner")
        self.actions["invert_selection"] = select_menu.addAction("Inverser la sélection")

        # AFFICHAGE
        view_menu = menu_bar.addMenu("Affichage")

        self.actions["reset_view"] = view_menu.addAction(
            "Réinitialiser la vue"
        )
        self.actions["zoom_100"] = view_menu.addAction("Zoom 100 %")
        self.actions["fit_canvas"] = view_menu.addAction("Adapter au canvas")
        self.actions["rotate_canvas"] = view_menu.addAction("Tourner le canvas (+15°)")
        self.actions["reset_canvas_rotation"] = view_menu.addAction("Réinitialiser la rotation")
        self.actions["flip_canvas_horizontal"] = view_menu.addAction("Miroir de vue horizontal")
        self.actions["flip_canvas_vertical"] = view_menu.addAction("Miroir de vue vertical")
        self.actions["canvas_only"] = view_menu.addAction("Mode canvas uniquement")
        self.actions["symmetry_horizontal"] = view_menu.addAction("Symétrie horizontale")
        self.actions["symmetry_vertical"] = view_menu.addAction("Symétrie verticale")
        for key in ("canvas_only", "flip_canvas_horizontal", "flip_canvas_vertical"):
            self.actions[key].setCheckable(True)
        view_menu.addSeparator()
        assistant_menu = view_menu.addMenu("Assistants de dessin")
        self.actions["assistant_ruler"] = assistant_menu.addAction("Règle")
        self.actions["assistant_ellipse"] = assistant_menu.addAction("Ellipse")
        self.actions["assistant_perspective"] = assistant_menu.addAction("Perspective à un point")
        self.actions["assistant_perspective"].setStatusTip(
            "Maj+clic pour placer le point de fuite"
        )
        for key in ("assistant_ruler", "assistant_ellipse", "assistant_perspective",
                    "symmetry_horizontal", "symmetry_vertical"):
            self.actions[key].setCheckable(True)

        view_menu.addSeparator()

        self.actions["show_tools"] = view_menu.addAction(
            "Afficher le panneau Outils"
        )

        self.actions["show_layers"] = view_menu.addAction(
            "Afficher le panneau Calques"
        )

        self.actions["show_brush"] = view_menu.addAction(
            "Afficher le panneau Brush Engine"
        )

        self.actions["show_tools"].setCheckable(True)
        self.actions["show_layers"].setCheckable(True)
        self.actions["show_brush"].setCheckable(True)

        self.actions["show_tools"].setChecked(True)
        self.actions["show_layers"].setChecked(True)
        self.actions["show_brush"].setChecked(True)

        # FENÊTRE
        window_menu = menu_bar.addMenu("Fenêtre")
        self.menus["window"] = window_menu

        self.actions["show_tools_window"] = window_menu.addAction(
            "Panneau Outils"
        )

        self.actions["show_layers_window"] = window_menu.addAction(
            "Panneau Calques"
        )

        self.actions["show_tools_window"].setCheckable(True)
        self.actions["show_layers_window"].setCheckable(True)

        self.actions["show_tools_window"].setChecked(True)
        self.actions["show_layers_window"].setChecked(True)
