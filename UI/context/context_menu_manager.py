from PySide6.QtWidgets import (
    QMainWindow,
    QListWidget,
    QListWidgetItem,
    QMenu,
)

from PySide6.QtCore import (
    Qt,
    QPoint,
)

from CANVAS.canvas import Canvas

from UI.menus.menu_manager import MenuManager


class ContextMenuManager:

    def __init__(
        self,
        window: QMainWindow,
        canvas: Canvas,
        layer_list: QListWidget,
        menu_manager: MenuManager
    ) -> None:

        self.window: QMainWindow = window
        self.canvas: Canvas = canvas
        self.layer_list: QListWidget = layer_list
        self.menu_manager: MenuManager = menu_manager

        self.create_connections()

    # =========================================================
    # CONNEXIONS
    # =========================================================

    def create_connections(self) -> None:

        self.canvas.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.canvas.customContextMenuRequested.connect(
            self.show_canvas_menu
        )

        self.layer_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.layer_list.customContextMenuRequested.connect(
            self.show_layer_menu
        )

    # =========================================================
    # CANVAS
    # =========================================================

    def show_canvas_menu(
        self,
        position: QPoint
    ) -> None:

        menu = QMenu(
            self.canvas
        )

        # -----------------------------------------------------
        # OUTIL
        # -----------------------------------------------------

        tool_menu = menu.addMenu(
            "Outil"
        )

        tool_menu.addAction(
            self.menu_manager.actions["brush"]
        )

        tool_menu.addAction(
            self.menu_manager.actions["eraser"]
        )

        # -----------------------------------------------------
        # HISTORIQUE
        # -----------------------------------------------------

        menu.addSeparator()

        menu.addAction(
            self.menu_manager.actions["undo"]
        )

        menu.addAction(
            self.menu_manager.actions["redo"]
        )

        # -----------------------------------------------------
        # CALQUE
        # -----------------------------------------------------

        menu.addSeparator()

        menu.addAction(
            self.menu_manager.actions["add_layer"]
        )

        menu.addAction(
            self.menu_manager.actions["duplicate_layer"]
        )

        # -----------------------------------------------------
        # VUE
        # -----------------------------------------------------

        menu.addSeparator()

        menu.addAction(
            self.menu_manager.actions["reset_view"]
        )

        menu.exec(
            self.canvas.mapToGlobal(
                position
            )
        )

    # =========================================================
    # CALQUES
    # =========================================================

    def show_layer_menu(
        self,
        position: QPoint
    ) -> None:

        item: QListWidgetItem | None = (
            self.layer_list.itemAt(
                position
            )
        )

        if item is None:
            return

        row = self.layer_list.row(
            item
        )

        self.layer_list.setCurrentRow(
            row
        )

        menu = QMenu(
            self.layer_list
        )

        # -----------------------------------------------------
        # ACTIONS
        # -----------------------------------------------------

        menu.addAction(
            self.menu_manager.actions["add_layer"]
        )

        menu.addAction(
            self.menu_manager.actions["duplicate_layer"]
        )

        menu.addAction(
            self.menu_manager.actions["rename_layer"]
        )

        menu.addAction(
            self.menu_manager.actions["toggle_visibility"]
        )

        # -----------------------------------------------------
        # ORDRE
        # -----------------------------------------------------

        menu.addSeparator()

        order_menu = menu.addMenu(
            "Ordre"
        )

        order_menu.addAction(
            self.menu_manager.actions["move_layer_up"]
        )

        order_menu.addAction(
            self.menu_manager.actions["move_layer_down"]
        )

        # -----------------------------------------------------
        # SUPPRESSION
        # -----------------------------------------------------

        menu.addSeparator()

        menu.addAction(
            self.menu_manager.actions["remove_layer"]
        )

        menu.exec(
            self.layer_list.mapToGlobal(
                position
            )
        )