from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPolygonF
from PySide6.QtWidgets import QDockWidget, QFrame, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget


class _SlotButton(QPushButton):
    """Case du rail : un groupe d'outils. Clic = outil courant du groupe ;
    clic droit ou appui long = choisir une variante (comme Photoshop)."""

    def __init__(self, rail, group_id, tools):
        super().__init__()
        self.rail, self.group_id, self.tools = rail, group_id, tools
        self.current = tools[0]
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(380)
        self._hold.timeout.connect(self.show_flyout)
        self._flyout_shown = False
        self.setObjectName("railTool")
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _p: self.show_flyout())

    def mousePressEvent(self, event):
        self._flyout_shown = False
        if event.button() == Qt.MouseButton.LeftButton and len(self.tools) > 1:
            self._hold.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._hold.stop()
        if self._flyout_shown:
            self.setDown(False)
            return
        super().mouseReleaseEvent(event)

    def show_flyout(self):
        if len(self.tools) < 2:
            return
        self._flyout_shown = True
        self.setDown(False)
        menu = QMenu(self)
        for name in self.tools:
            spec = self.rail.SPEC_BY_NAME[name]
            action = menu.addAction(self.rail.icon_for(name), spec[1])
            action.setCheckable(True)
            action.setChecked(name == self.rail.active_tool)
            action.triggered.connect(lambda _c=False, n=name: self.rail.activate(n))
        menu.exec(self.mapToGlobal(self.rect().topRight()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self.tools) > 1:   # petit coin : le groupe contient d'autres outils
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(166, 180, 206, 170))
            w, h = self.width(), self.height()
            painter.drawPolygon(QPolygonF([QPointF(w - 4, h - 10), QPointF(w - 4, h - 4), QPointF(w - 10, h - 4)]))
            painter.end()


class ToolRailDock(QDockWidget):
    """Rail d'outils groupés : 9 cases au lieu de 25 boutons.

    Chaque case garde en mémoire la dernière variante utilisée (ex. Lasso dans
    le groupe Sélection). Les boutons individuels restent disponibles dans
    ``self.buttons`` (compatibilité) sans encombrer le rail."""

    # (outil, libellé + raccourci)
    TOOL_SPECS = (
        ("brush", "", "Pinceau (B)"),
        ("smudge", "", "Estompe (S)"),
        ("blur", "", "Flou"),
        ("sharpen", "", "Netteté"),
        ("clone_stamp", "", "Tampon de duplication (K) — Maj+clic : source"),
        ("eraser", "", "Gomme (E)"),
        ("fill", "", "Pot de peinture (F)"),
        ("gradient", "", "Dégradé (G)"),
        ("line", "", "Ligne (L)"),
        ("rectangle", "", "Rectangle (R)"),
        ("ellipse", "", "Ellipse (O)"),
        ("bezier", "", "Courbe de Bézier (P)"),
        ("text", "", "Texte (Y) — Maj+glisser : déplacer"),
        ("select_rectangle", "", "Sélection rectangulaire"),
        ("select_ellipse", "", "Sélection elliptique"),
        ("lasso", "", "Lasso"),
        ("magic_wand", "", "Baguette magique"),
        ("move", "", "Déplacer le calque (M)"),
        ("transform", "", "Transformer (T)"),
        ("crop", "", "Recadrer (C)"),
        ("reference", "", "Images de référence"),
        ("picker", "", "Pipette (I)"),
        ("hand", "", "Main (H)"),
        ("zoom_view", "", "Zoom (Z)"),
        ("rotate_view", "", "Rotation de vue (Maj+R)"),
    )
    SPEC_BY_NAME = {name: (name, label) for name, _text, label in TOOL_SPECS}
    GROUPS = (
        ("paint", "Peinture", ("brush", "smudge", "blur", "sharpen", "clone_stamp")),
        ("erase", "Gomme", ("eraser",)),
        ("fill", "Remplissage", ("fill", "gradient")),
        ("shape", "Formes", ("line", "rectangle", "ellipse", "bezier")),
        ("text", "Texte", ("text",)),
        ("select", "Sélection", ("select_rectangle", "select_ellipse", "lasso", "magic_wand")),
        ("move", "Déplacer / transformer", ("move", "transform", "crop", "reference")),
        ("picker", "Pipette", ("picker",)),
        ("view", "Vue", ("hand", "zoom_view", "rotate_view")),
    )

    def __init__(self, canvas, parent=None) -> None:
        super().__init__("Outils", parent)
        self.canvas = canvas
        self.setObjectName("ToolRailDock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumWidth(54)
        self.icon_dir = Path(__file__).resolve().parents[1] / "icons"
        self.icon_size = 22
        self.active_tool = ""

        tools = canvas.tools
        self.callbacks = {
            "brush": tools.set_brush, "eraser": tools.set_eraser, "picker": tools.set_picker,
            "smudge": tools.set_smudge, "clone_stamp": tools.set_clone_stamp, "reference": tools.set_reference,
            "text": tools.set_text, "blur": tools.set_blur, "sharpen": tools.set_sharpen, "bezier": tools.set_bezier,
            "fill": tools.set_fill, "gradient": tools.set_gradient, "line": tools.set_line,
            "rectangle": tools.set_rectangle, "ellipse": tools.set_ellipse,
            "select_rectangle": tools.set_rectangle_selection, "select_ellipse": tools.set_ellipse_selection,
            "lasso": tools.set_lasso, "magic_wand": tools.set_magic_wand, "crop": tools.set_crop,
            "move": tools.set_move, "transform": tools.set_transform, "hand": tools.set_hand,
            "zoom_view": tools.set_zoom_view, "rotate_view": tools.set_rotate_view,
        }

        content = QWidget()
        content.setObjectName("toolRail")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(4)

        # Boutons individuels (compatibilité : tests et appels existants).
        self.buttons = {}
        for name, _text, label in self.TOOL_SPECS:
            button = QPushButton(content)
            button.setObjectName("railTool")
            button.setCheckable(True)
            button.setToolTip(label)
            button.setIcon(self.icon_for(name))
            button.clicked.connect(lambda _c=False, n=name: self.activate(n))
            button.hide()
            self.buttons[name] = button

        self.slots = {}
        for group_id, title, members in self.GROUPS:
            slot = _SlotButton(self, group_id, members)
            slot.clicked.connect(lambda _c=False, s=slot: self.activate(s.current))
            layout.addWidget(slot, 0, Qt.AlignmentFlag.AlignHCenter)
            self.slots[group_id] = slot
            self._refresh_slot(slot)
            if group_id in ("erase", "text", "move"):
                layout.addWidget(self._separator())

        layout.addWidget(self._separator())
        for name, tooltip, callback in (("undo", "Annuler (Ctrl+Z)", canvas.undo), ("redo", "Rétablir (Ctrl+Maj+Z)", canvas.redo)):
            button = QPushButton()
            button.setIcon(self.icon_for(name))
            button.setIconSize(QSize(self.icon_size, self.icon_size))
            button.setObjectName("railCommand")
            button.setToolTip(tooltip)
            button.setFixedSize(40, 34)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(callback)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()
        self.color_button = QPushButton()
        self.color_button.setObjectName("railColor")
        self.color_button.setFixedSize(40, 40)
        self.color_button.setToolTip("Couleur principale — clic : choisir")
        layout.addWidget(self.color_button, 0, Qt.AlignmentFlag.AlignHCenter)

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

    @staticmethod
    def _separator():
        line = QFrame()
        line.setObjectName("railSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def icon_for(self, name: str) -> QIcon:
        path = self.icon_dir / f"{name}.svg"
        return QIcon(str(path)) if path.exists() else QIcon()

    def group_of(self, tool: str):
        for group_id, _title, members in self.GROUPS:
            if tool in members:
                return group_id
        return None

    def _refresh_slot(self, slot: _SlotButton) -> None:
        slot.setIcon(self.icon_for(slot.current))
        slot.setIconSize(QSize(self.icon_size, self.icon_size))
        title = next(t for g, t, _m in self.GROUPS if g == slot.group_id)
        label = self.SPEC_BY_NAME[slot.current][1]
        extra = "\nClic droit ou appui long : autres outils du groupe" if len(slot.tools) > 1 else ""
        slot.setToolTip(f"{label}\n— {title}{extra}")
        if slot.icon().isNull():
            slot.setText(label[:2])

    def activate(self, name: str) -> None:
        callback = self.callbacks.get(name)
        if callback is not None:
            callback()
        self.set_active_tool(name)

    def set_active_tool(self, active: str) -> None:
        self.active_tool = active
        for name, button in self.buttons.items():
            button.setChecked(name == active)
        group = self.group_of(active)
        for group_id, slot in self.slots.items():
            if group_id == group and slot.current != active:
                slot.current = active
                self._refresh_slot(slot)
            slot.setChecked(group_id == group)

    def set_icon_size(self, size: int) -> None:
        self.icon_size = max(16, min(40, int(size)))
        for slot in self.slots.values():
            slot.setFixedSize(self.icon_size + 18, self.icon_size + 18)
            slot.setIconSize(QSize(self.icon_size, self.icon_size))
        for button in self.buttons.values():
            button.setIconSize(QSize(self.icon_size, self.icon_size))

    def sync_color(self, settings) -> None:
        red, green, blue, _alpha = settings["color"]
        foreground = f"#{int(red):02x}{int(green):02x}{int(blue):02x}"
        palette = self.color_button.palette()
        palette.setColor(QPalette.ColorRole.Button, QColor(foreground))
        self.color_button.setAutoFillBackground(True)
        self.color_button.setPalette(palette)
        self.color_button.setStyleSheet(f"QPushButton#railColor {{ background: {foreground}; }}")


__all__ = ["ToolRailDock"]
