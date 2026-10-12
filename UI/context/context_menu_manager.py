from PySide6.QtWidgets import QMainWindow, QListWidget, QMenu

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

        # Layer list context menu is handled by LayersDock._show_layer_context_menu.
        # Do NOT connect here — a double connection would fire both menus.

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
