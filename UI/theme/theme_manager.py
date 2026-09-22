from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from UI.theme.palette import COLORS


class ThemeManager:
    """Single source of truth for CreativeSystem's widget appearance."""

    @classmethod
    def stylesheet(cls) -> str:
        path = Path(__file__).with_name("dark.qss")
        stylesheet = path.read_text(encoding="utf-8").format(**COLORS)
        compact = QSettings("CreativeSystem", "CreativeSystem").value("interface/compact", True, bool)
        return stylesheet.replace("font-size: 11px;", f"font-size: {10 if compact else 12}px;", 1)

    @classmethod
    def apply(cls, target: QApplication | QWidget) -> None:
        target.setStyleSheet(cls.stylesheet())


__all__ = ["ThemeManager"]
