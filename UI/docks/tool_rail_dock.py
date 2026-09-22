from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDockWidget, QFrame, QPushButton, QVBoxLayout, QWidget, QScrollArea


class ToolRailDock(QDockWidget):
    """Rail compacte : accès immédiat aux outils pendant la peinture."""

    TOOL_SPECS = (
        ("brush", "", "Pinceau (B)"),
        ("eraser", "", "Gomme (E)"),
        ("picker", "", "Pipette composite (I)"),
        ("smudge", "", "Smudge (S)"),
        ("clone_stamp", "", "Clone Stamp — Maj+clic définit la source (K)"),
        ("reference", "", "Déplacer / redimensionner les images de référence"),
        ("text", "", "Ajouter/modifier un texte (Y) ; Maj+glisser pour déplacer"),
        ("blur", "", "Flouter sous un tip rond dont le diamètre suit la taille du brush"),
        ("sharpen", "", "Renforcer la netteté sous un tip rond"),
        ("bezier", "", "Courbe de Bézier au brush actif : glisser deux poignées (P)"),
        ("fill", "", "Pot de peinture (F)"),
        ("gradient", "", "Dégradé linéaire (G)"),
        ("line", "", "Ligne avec le brush actif (L)"),
        ("rectangle", "", "Rectangle avec le brush actif (R)"),
        ("ellipse", "", "Ellipse avec le brush actif (O)"),
        ("select_rectangle", "", "Sélection rectangulaire"),
        ("select_ellipse", "", "Sélection elliptique"),
        ("lasso", "", "Lasso"),
        ("magic_wand", "", "Baguette magique"),
        ("crop", "", "Recadrage (C)"),
        ("move", "", "Déplacer le calque (M)"),
        ("transform", "", "Transformer (T)"),
        ("hand", "", "Main (H)"),
        ("zoom_view", "", "Zoom (Z)"),
        ("rotate_view", "", "Rotation de vue (Maj+R)"),
    )

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Tools", parent)
        self.canvas = canvas
        self.setObjectName("ToolRailDock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumWidth(52)

        content = QWidget()
        content.setObjectName("toolRail")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(5)
        self.buttons = {}
        icon_dir = Path(__file__).resolve().parents[1] / "icons"

        callbacks = {
            "brush": canvas.tools.set_brush,
            "eraser": canvas.tools.set_eraser,
            "picker": canvas.tools.set_picker,
            "smudge": canvas.tools.set_smudge,
            "clone_stamp": canvas.tools.set_clone_stamp,
            "reference": canvas.tools.set_reference,
            "text": canvas.tools.set_text,
            "blur": canvas.tools.set_blur,
            "sharpen": canvas.tools.set_sharpen,
            "bezier": canvas.tools.set_bezier,
            "fill": canvas.tools.set_fill,
            "gradient": canvas.tools.set_gradient,
            "line": canvas.tools.set_line,
            "rectangle": canvas.tools.set_rectangle,
            "ellipse": canvas.tools.set_ellipse,
            "select_rectangle": canvas.tools.set_rectangle_selection,
            "select_ellipse": canvas.tools.set_ellipse_selection,
            "lasso": canvas.tools.set_lasso,
            "magic_wand": canvas.tools.set_magic_wand,
            "crop": canvas.tools.set_crop,
            "move": canvas.tools.set_move,
            "transform": canvas.tools.set_transform,
            "hand": canvas.tools.set_hand,
            "zoom_view": canvas.tools.set_zoom_view,
            "rotate_view": canvas.tools.set_rotate_view,
        }
        for name, text, tooltip in self.TOOL_SPECS:
            button = QPushButton()
            icon_path = icon_dir / f"{name}.svg"
            if icon_path.exists():
                button.setIcon(QIcon(str(icon_path)))
                button.setIconSize(QSize(24, 24))
            button.setObjectName("railTool")
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setFixedSize(38, 38)
            button.clicked.connect(callbacks[name])
            layout.addWidget(button)
            self.buttons[name] = button

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        for name, tooltip, callback in (
            ("undo", "Annuler", canvas.undo),
            ("redo", "Rétablir", canvas.redo),
        ):
            button = QPushButton()
            icon_path = icon_dir / f"{name}.svg"
            if icon_path.exists():
                button.setIcon(QIcon(str(icon_path)))
                button.setIconSize(QSize(24, 24))
            button.setObjectName("railCommand")
            button.setToolTip(tooltip)
            button.setFixedSize(38, 34)
            button.clicked.connect(callback)
            layout.addWidget(button)

        layout.addStretch()
        self.color_button = QPushButton()
        self.color_button.setObjectName("railColor")
        self.color_button.setFixedSize(38, 38)
        self.color_button.setToolTip("Couleur principale")
        layout.addWidget(self.color_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self.setWidget(scroll)

        canvas.tool_changed.connect(self.set_active_tool)
        canvas.brush_settings_changed.connect(self.sync_color)
        self.set_active_tool(canvas.tools.current_tool)
        self.sync_color(canvas.get_cpp_brush_settings())

    def set_active_tool(self, active: str) -> None:
        for name, button in self.buttons.items():
            button.setChecked(name == active)

    def set_icon_size(self, size: int) -> None:
        size = max(16, min(48, int(size)))
        for button in (*self.buttons.values(),):
            if not button.icon().isNull():
                button.setIconSize(QSize(size, size))

    def sync_color(self, settings) -> None:
        red, green, blue, _alpha = settings["color"]
        foreground = f"#{int(red):02x}{int(green):02x}{int(blue):02x}"
        self.color_button.setStyleSheet(
            f"background-color: {foreground}; border: 2px solid #d9dde3;"
        )


__all__ = ["ToolRailDock"]
