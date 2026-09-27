from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
import re
from PySide6.QtWidgets import QApplication, QWidget

from UI.theme.palette import COLORS


class ThemeManager:
    """Single source of truth for CreativeSystem's widget appearance."""

    @classmethod
    def stylesheet(cls) -> str:
        path = Path(__file__).with_name("dark.qss")
        stylesheet = path.read_text(encoding="utf-8").format(**COLORS)
        settings = QSettings("CreativeSystem", "CreativeSystem")
        # Refonte UX : le mode compact (10 px) rendait l'interface difficile à
        # lire. Il est désactivé une seule fois ; il reste réactivable dans les
        # Préférences.
        if not settings.value("interface/readable_migrated", False, bool):
            settings.setValue("interface/compact", False)
            settings.setValue("interface/readable_migrated", True)
        compact = settings.value("interface/compact", False, bool)
        # Le groupe capturé par la regex contient déjà « font-size: » : ne remplacer
        # que la valeur.  Répéter la propriété donnait « font-size: font-size: 10px; »
        # et Qt rejetait alors toute la feuille de style de l'application.
        replacement = f"{10 if compact else 12}px;"
        updated, count = re.subn(r"(QWidget[^\n]*font-size:)\s*11px;",
                                 lambda match: match.group(1) + " " + replacement,
                                 stylesheet, count=1)
        if count != 1:
            raise ValueError("Nebula theme is missing its base QWidget font token")
        return updated

    @classmethod
    def apply(cls, target: QApplication | QWidget) -> None:
        target.setStyleSheet(cls.stylesheet())


__all__ = ["ThemeManager"]
