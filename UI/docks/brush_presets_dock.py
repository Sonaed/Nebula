from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QInputDialog,
    QMessageBox,
    QLabel,
    QLineEdit,
    QComboBox,
    QFileDialog,
)

from TOOLS.brush_preset_manager import BrushPresetManager
from UI.docks.brush_settings_dialog import BrushSettingsDialog
from UI.theme.palette import COLORS


class BrushPresetsDock(QDockWidget):
    """
    Docker de sélection des presets de brush.

    Le Canvas doit fournir :
        load_cpp_brush_preset(name)
    """

    preset_selected = Signal(str)

    def __init__(
        self,
        canvas=None,
        parent=None,
    ):
        super().__init__(
            "Brush Presets",
            parent,
        )

        self.canvas = canvas

        self.manager = (
            BrushPresetManager()
        )

        self.setObjectName(
            "BrushPresetsDock"
        )

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        # A preset browser is useful beside the canvas, not instead of it.
        # All controls below have compact labels/tooltips, so this is a true
        # dock minimum rather than a cosmetic value blocked by child widgets.
        self.setMinimumWidth(176)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.build_ui()
        self.refresh()

    def resizeEvent(self, event) -> None:
        """Use the available width for a compact multi-column brush shelf."""
        if not hasattr(self, "list_widget"):
            super().resizeEvent(event)
            return
        wide = self.width() >= 285
        mode = QListWidget.ViewMode.IconMode if wide else QListWidget.ViewMode.ListMode
        self.list_widget.setViewMode(mode)
        if wide:
            self.list_widget.setGridSize(QSize(94, 76))
            self.list_widget.setIconSize(QSize(64, 44))
            self.list_widget.setFlow(QListWidget.Flow.LeftToRight)
            self.list_widget.setWrapping(True)
        else:
            self.list_widget.setGridSize(QSize())
            self.list_widget.setIconSize(QSize(48, 32))
            self.list_widget.setFlow(QListWidget.Flow.TopToBottom)
            self.list_widget.setWrapping(False)
        super().resizeEvent(event)

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):
        container = QWidget()

        root = QVBoxLayout(
            container
        )

        root.setContentsMargins(
            8,
            8,
            8,
            8
        )

        root.setSpacing(
            6
        )

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search brushes…")
        self.search.setMinimumWidth(64)
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.setMinimumWidth(72)
        self.category.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.category.setMinimumContentsLength(5)
        self.category.addItem("All")
        self.category.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        root.addLayout(filters)

        self.list_widget = QListWidget()

        self.list_widget.setViewMode(
            QListWidget.ListMode
        )

        self.list_widget.setResizeMode(
            QListWidget.Adjust
        )

        self.list_widget.setMovement(
            QListWidget.Static
        )

        self.list_widget.setSpacing(
            3
        )

        self.list_widget.setIconSize(
            QSize(48, 32)
        )
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._collapsed_categories: set[str] = set()

        self.list_widget.itemClicked.connect(
            self.on_item_clicked
        )

        root.addWidget(
            self.list_widget,
            1
        )

        buttons = QHBoxLayout()

        self.save_button = QPushButton("💾")
        self.save_button.setToolTip("Enregistrer les modifications du preset")

        self.save_button.clicked.connect(
            self.save_preset
        )

        self.new_button = QPushButton(
            "+"
        )

        self.new_button.setToolTip(
            "Créer un nouveau preset"
        )

        self.new_button.clicked.connect(
            self.new_preset
        )
        self.new_folder_button = QPushButton("📁+")
        self.new_folder_button.setToolTip("Créer une catégorie de pinceaux")
        self.new_folder_button.clicked.connect(self.new_category)

        self.delete_button = QPushButton(
            "−"
        )

        self.delete_button.setToolTip(
            "Supprimer le preset"
        )

        self.delete_button.clicked.connect(
            self.delete_preset
        )
        self.list_widget.currentItemChanged.connect(lambda *_: self._sync_edit_controls())

        self.settings_button = QPushButton("⚙")
        self.settings_button.setToolTip("Ouvrir les réglages complets du preset")
        self.settings_button.clicked.connect(self.open_settings)

        for button in (self.save_button, self.new_button, self.new_folder_button, self.delete_button):
            button.setFixedSize(28, 28)
            buttons.addWidget(button)

        self.favorite_button = QPushButton("☆")
        self.favorite_button.setToolTip("Ajouter/retirer des favoris")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.duplicate_button = QPushButton("⧉")
        self.duplicate_button.setToolTip("Dupliquer le preset")
        self.duplicate_button.clicked.connect(self.duplicate_preset)
        self.import_button = QPushButton("⇩")
        self.import_button.setToolTip("Importer un preset")
        self.import_button.clicked.connect(self.import_preset)
        self.export_button = QPushButton("⇧")
        self.export_button.setToolTip("Exporter le preset")
        self.export_button.clicked.connect(self.export_preset)
        self.move_category_button = QPushButton("↪")
        self.move_category_button.setToolTip("Déplacer vers une catégorie")
        self.move_category_button.clicked.connect(self.move_to_category)
        for button in (self.settings_button, self.favorite_button, self.duplicate_button,
                       self.move_category_button, self.import_button, self.export_button):
            button.setFixedSize(28, 28)
            buttons.addWidget(button)
        root.addLayout(buttons)

        self.setWidget(
            container
        )

    # ========================================================
    # REFRESH
    # ========================================================

    def refresh(self, *_args):
        current = (
            self.current_preset_name()
        )

        self.list_widget.clear()

        records = [self.manager.metadata(name) for name in self.manager.list_presets()]
        categories = self.manager.categories()
        selected_category = self.category.currentText()
        blocked = self.category.blockSignals(True)
        self.category.clear(); self.category.addItem("All"); self.category.addItems(categories)
        self.category.setCurrentText(selected_category if selected_category in categories else "All")
        self.category.blockSignals(blocked)
        needle = self.search.text().strip().casefold()
        for category in categories:
            filtered = [record for record in records if record["category"] == category
                        and (not needle or needle in record["name"].casefold())
                        and (self.category.currentText() == "All" or record["category"] == self.category.currentText())]
            if not filtered:
                continue
            collapsed = category in self._collapsed_categories
            header = QListWidgetItem(("▸" if collapsed else "▾") + "  📁 " + category)
            header.setData(Qt.UserRole + 1, category)
            header.setData(Qt.UserRole + 2, "category")
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(header)
            if collapsed:
                continue
            for record in filtered:
                name = record["name"]
                item = QListWidgetItem(("    ★ " if record["favorite"] else "    ") + name)
                item.setIcon(QIcon(self._thumbnail(name)))
                item.setData(Qt.UserRole, name)
                self.list_widget.addItem(item)
            separator = QListWidgetItem("")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)
            separator.setSizeHint(QSize(94, 10))
            self.list_widget.addItem(separator)

        if current:
            self.select_preset(
                current
            )

    # ========================================================
    # SELECTION
    # ========================================================

    def current_preset_name(self):
        item = (
            self.list_widget.currentItem()
        )

        if item is None:
            return None

        return item.data(
            Qt.UserRole
        )

    def select_preset(
        self,
        name: str,
    ):
        for index in range(
            self.list_widget.count()
        ):
            item = (
                self.list_widget.item(index)
            )

            if item.data(
                Qt.UserRole
            ) == name:
                self.list_widget.setCurrentItem(
                    item
                )
                self._sync_edit_controls()

                return

    def _sync_edit_controls(self) -> None:
        name = self.current_preset_name()
        read_only = bool(name and self.manager.metadata(name).get("builtIn"))
        for button in (self.save_button, self.delete_button, self.settings_button, self.favorite_button):
            button.setEnabled(bool(name) and not read_only)
        self.duplicate_button.setEnabled(bool(name))
        self.move_category_button.setEnabled(bool(name) and not read_only)

    def new_category(self):
        name, accepted = QInputDialog.getText(self, "Nouvelle catégorie", "Nom du dossier :")
        if not accepted or not name.strip():
            return
        category = name.strip()[:64]
        self.manager.add_category(category)
        preset = self.current_preset_name()
        if preset and not self.manager.metadata(preset).get("builtIn"):
            self.manager.set_metadata(preset, category=category)
        self._collapsed_categories.discard(category)
        self.category.setCurrentText(category)
        self.refresh()

    def move_to_category(self):
        name = self.current_preset_name()
        if not name:
            return
        categories = sorted({self.manager.metadata(item)["category"] for item in self.manager.list_presets()})
        category, accepted = QInputDialog.getItem(self, "Déplacer le pinceau", "Dossier :", categories, editable=True)
        if accepted and category.strip() and self.manager.set_metadata(name, category=category.strip()[:64]):
            self.refresh(); self.select_preset(name)

    # ========================================================
    # LOAD
    # ========================================================

    def on_item_clicked(
        self,
        item,
    ):
        if item.data(Qt.UserRole + 2) == "category":
            category = item.data(Qt.UserRole + 1)
            if category in self._collapsed_categories:
                self._collapsed_categories.remove(category)
            else:
                self._collapsed_categories.add(category)
            self.refresh()
            return
        name = item.data(
            Qt.UserRole
        )

        if not name:
            return

        self.load_preset(
            name
        )

    def _notify(self, message: str, warning: bool = False) -> None:
        """Retour visible par l'utilisateur, jamais un print() dans la console."""
        window = self.window()
        status = getattr(window, "statusBar", None)
        if callable(status):
            try:
                status().showMessage(message, 4000)
            except (AttributeError, RuntimeError):
                pass
        if warning:
            QMessageBox.warning(self, "Presets de brush", message)

    def load_preset(
        self,
        name: str,
    ):
        if self.canvas is None:
            self._notify(
                f"Aucun document ouvert : impossible d'appliquer « {name} ».",
                warning=True,
            )

            return False

        loader = getattr(
            self.canvas,
            "load_cpp_brush_preset",
            None,
        )

        if loader is None:
            self._notify(
                "Ce canvas ne sait pas charger les presets de brush.",
                warning=True,
            )

            return False

        success = loader(
            name
        )

        if not success:
            self._notify(
                f"CreativeCore a refusé le preset « {name} ».",
                warning=True,
            )

        if success:
            self.preset_selected.emit(
                name
            )

            self._notify(f"Brush « {name} » appliqué.")

        return bool(success)

    def _thumbnail(self, name: str) -> QPixmap:
        settings = self.manager.load(name) or {}
        pixmap = QPixmap(88, 58); pixmap.fill(QColor(COLORS["preset_thumbnail"]))
        painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(*(settings.get("color", [220, 220, 220, 255])))
        width = max(2.0, min(18.0, float(settings.get("size", 10.0)) / 6.0))
        color.setAlphaF(max(.15, min(1.0, float(settings.get("opacity", 1.0)))))
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(10, 40, 77, 18); painter.end(); return pixmap

    def toggle_favorite(self):
        name = self.current_preset_name()
        if name:
            current = self.manager.metadata(name)["favorite"]
            self.manager.set_metadata(name, favorite=not current); self.refresh(); self.select_preset(name)

    def duplicate_preset(self):
        name = self.current_preset_name()
        if not name: return
        new_name, accepted = QInputDialog.getText(self, "Duplicate Brush", "New name", text=f"{name} Copy")
        if accepted and new_name.strip(): self.manager.duplicate(name, new_name.strip()); self.refresh(); self.select_preset(new_name.strip())

    def import_preset(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un pinceau", "",
            "Pinceaux (*.csbr *.json);;Paquets Nebula / moteurs StarDust (*.csbr);;Presets JSON (*.json)")
        if not path:
            return
        name = self.manager.import_csbr(path) if Path(path).suffix.lower() == ".csbr" else self.manager.import_preset(path)
        self.refresh()
        if not name:
            reason = getattr(self.manager, "last_error", "") or "format non reconnu"
            self._notify(f"Import impossible : {reason}", warning=True)
            return
        self.select_preset(name)
        # Centralisation : le pinceau rejoint aussi la bibliothèque commune d'Existence.
        resources = getattr(self.canvas, "resource_manager", None) or getattr(self, "resource_manager", None)
        if resources is not None:
            try:
                resources.import_file(path, "brushes")
            except (OSError, ValueError):
                pass
        self._notify(f"Pinceau importé : {name}")

    def export_preset(self):
        name = self.current_preset_name()
        if not name: return
        path, selected = QFileDialog.getSaveFileName(self, "Export Brush Preset", f"{name}.csbr", "Brush package (*.csbr);;Legacy JSON preset (*.json)")
        if path:
            is_package = selected.startswith("Brush package") or Path(path).suffix.lower() == ".csbr"
            if is_package and Path(path).suffix.lower() != ".csbr":
                path += ".csbr"
            # Le dialogue a validé le nom saisi, pas le nom suffixé : on
            # revérifie pour ne jamais écraser un fichier sans le dire.
            if Path(path).exists():
                answer = QMessageBox.question(
                    self,
                    "Écraser le fichier",
                    f"« {Path(path).name} » existe déjà. L'écraser ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            if is_package:
                self.manager.export_csbr(name, path)
            else:
                self.manager.export_preset(name, path)
            self._notify(f"Preset exporté vers « {Path(path).name} ».")

    # ========================================================
    # SAVE
    # ========================================================

    def _canvas_settings(self):
        """
        Récupère le dernier état de preset connu.

        Le Canvas peut fournir :
            get_cpp_brush_settings()
        """

        getter = getattr(
            self.canvas,
            "get_cpp_brush_settings",
            None,
        )

        if getter is None:
            return None

        return getter()

    def save_preset(self):
        name = (
            self.current_preset_name()
        )

        if name and self.manager.metadata(name).get("builtIn"):
            QMessageBox.information(self, "Brush Presets", "Les brushes intégrés sont en lecture seule. Dupliquez ce preset pour le modifier.")
            return

        if not name:
            self.new_preset()

            return

        answer = QMessageBox.question(
            self,
            "Écraser le preset",
            f"Remplacer « {name} » par les réglages actuels du brush ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        settings = (
            self._canvas_settings()
        )

        if settings is None:
            QMessageBox.information(
                self,
                "Brush Presets",
                "Le Canvas ne fournit pas encore "
                "get_cpp_brush_settings().",
            )

            return

        self.manager.save(
            name,
            settings,
        )

        self.refresh()

        self.select_preset(
            name
        )

        self._notify(f"Preset « {name} » enregistré.")

    # ========================================================
    # NEW
    # ========================================================

    def new_preset(self):
        name, accepted = QInputDialog.getText(
            self,
            "New Brush Preset",
            "Nom du preset :",
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        if self.manager.load(name) is not None:
            answer = QMessageBox.question(
                self,
                "Preset existant",
                f"« {name} » existe déjà. Le remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        settings = (
            self._canvas_settings()
        )

        if settings is None:
            QMessageBox.information(
                self,
                "Brush Presets",
                "Le Canvas ne fournit pas encore "
                "get_cpp_brush_settings().",
            )

            return

        self.manager.save(
            name,
            settings,
        )

        self.refresh()

        self.select_preset(
            name
        )

        self._notify(f"Nouveau preset « {name} » créé.")

    # ========================================================
    # DELETE
    # ========================================================

    def delete_preset(self):
        name = (
            self.current_preset_name()
        )

        if not name:
            return

        answer = QMessageBox.question(
            self,
            "Supprimer le preset",
            f"Supprimer définitivement « {name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.Yes:
            return

        if self.manager.delete(
            name
        ):
            self.refresh()

            self._notify(f"Preset « {name} » supprimé.")

    def open_settings(self):
        if self.canvas is None:
            return
        dialog = BrushSettingsDialog(self.canvas, self)
        dialog.exec()


__all__ = [
    "BrushPresetsDock",
]
