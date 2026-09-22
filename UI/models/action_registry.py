from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence


DEFAULT_SHORTCUTS = {
    "new": "Ctrl+N", "open": "Ctrl+O", "save": "Ctrl+S",
    "save_as": "Ctrl+Shift+S", "undo": "Ctrl+Z", "redo": "Ctrl+Shift+Z",
    "brush": "B", "eraser": "E", "picker": "I", "smudge": "S",
    "fill": "F", "gradient": "G", "line": "L", "rectangle": "R",
    "ellipse": "O", "select_all": "Ctrl+A", "deselect": "Ctrl+D",
    "clone_stamp": "K",
    "text": "Y",
    "bezier": "P",
    "invert_selection": "Ctrl+I", "preferences": "Ctrl+,",
    "hand": "H", "zoom_view": "Z", "rotate_view": "Shift+R",
}


class ActionRegistry:
    """Applies persistent shortcuts and detects conflicts for all UI actions."""

    def __init__(self, actions: dict[str, QAction], settings=None) -> None:
        self.actions = actions
        self.settings = settings or QSettings("CreativeSystem", "CreativeSystem")

    def apply(self) -> None:
        for key, action in self.actions.items():
            value = self.settings.value(f"shortcuts/{key}", DEFAULT_SHORTCUTS.get(key, ""))
            action.setShortcut(QKeySequence(str(value)))

    def conflicts(self, sequence: QKeySequence, excluding: str = "") -> list[str]:
        if sequence.isEmpty():
            return []
        return [key for key, action in self.actions.items() if key != excluding and action.shortcut() == sequence]

    def reset(self) -> None:
        self.settings.remove("shortcuts")
        self.apply()


__all__ = ["ActionRegistry", "DEFAULT_SHORTCUTS"]
