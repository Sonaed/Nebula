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

        self.setMinimumWidth(
            230
        )

        self.build_ui()
        self.refresh()

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
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.addItem("All")
        self.category.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        root.addLayout(filters)

        self.list_widget = QListWidget()

        self.list_widget.setViewMode(
            QListWidget.IconMode
        )

        self.list_widget.setResizeMode(
            QListWidget.Adjust
        )

        self.list_widget.setMovement(
            QListWidget.Static
        )

        self.list_widget.setSpacing(
            8
        )

        self.list_widget.setIconSize(
            QSize(72, 50)
        )

        self.list_widget.itemClicked.connect(
            self.on_item_clicked
        )

        root.addWidget(
            self.list_widget,
            1
        )

        buttons = QHBoxLayout()

        self.save_button = QPushButton(
            "Save"
        )

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

        self.settings_button = QPushButton("Réglages…")
        self.settings_button.clicked.connect(self.open_settings)

        buttons.addWidget(
            self.save_button
        )

        buttons.addWidget(
            self.new_button
        )

        buttons.addWidget(
            self.delete_button
        )

        root.addLayout(
            buttons
        )

        root.addWidget(self.settings_button)

        extra = QHBoxLayout()
        self.favorite_button = QPushButton("☆")
        self.favorite_button.setToolTip("Ajouter/retirer des favoris")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_preset)
        self.import_button = QPushButton("Import")
        self.import_button.clicked.connect(self.import_preset)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_preset)
        for button in (self.favorite_button, self.duplicate_button, self.import_button, self.export_button):
            extra.addWidget(button)
        root.addLayout(extra)

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
        categories = sorted({record["category"] for record in records})
        selected_category = self.category.currentText()
        blocked = self.category.blockSignals(True)
        self.category.clear(); self.category.addItem("All"); self.category.addItems(categories)
        self.category.setCurrentText(selected_category if selected_category in categories else "All")
        self.category.blockSignals(blocked)
        needle = self.search.text().strip().casefold()
        for record in records:
            name = record["name"]
            if needle and needle not in name.casefold():
                continue
            if self.category.currentText() != "All" and record["category"] != self.category.currentText():
                continue
            item = QListWidgetItem(
                ("★ " if record["favorite"] else "") + name
            )
            item.setIcon(QIcon(self._thumbnail(name)))

            item.setTextAlignment(
                Qt.AlignHCenter
                | Qt.AlignBottom
            )

            item.setData(
                Qt.UserRole,
                name
            )

            self.list_widget.addItem(
                item
            )

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

    # ========================================================
    # LOAD
    # ========================================================

    def on_item_clicked(
        self,
        item,
    ):
        name = item.data(
            Qt.UserRole
        )

        if not name:
            return

        self.load_preset(
            name
        )

    def load_preset(
        self,
        name: str,
    ):
        if self.canvas is None:
            print(
                f"⚠ Aucun Canvas associé au preset {name}"
            )

            return False

        loader = getattr(
            self.canvas,
            "load_cpp_brush_preset",
            None,
        )

        if loader is None:
            print(
                "⚠ Canvas sans load_cpp_brush_preset()."
            )

            return False

        success = loader(
            name
        )

        if success:
            self.preset_selected.emit(
                name
            )

            print(
                f"✓ Preset sélectionné : {name}"
            )

        return bool(success)

    def _thumbnail(self, name: str) -> QPixmap:
        settings = self.manager.load(name) or {}
        pixmap = QPixmap(88, 58); pixmap.fill(QColor("#191A1C"))
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
        path, _ = QFileDialog.getOpenFileName(self, "Import Brush Preset", "", "Brush packages (*.csbr);;Legacy JSON presets (*.json)")
        if path:
            name = self.manager.import_csbr(path) if Path(path).suffix.lower() == ".csbr" else self.manager.import_preset(path)
            self.refresh()
            if name: self.select_preset(name)

    def export_preset(self):
        name = self.current_preset_name()
        if not name: return
        path, selected = QFileDialog.getSaveFileName(self, "Export Brush Preset", f"{name}.csbr", "Brush package (*.csbr);;Legacy JSON preset (*.json)")
        if path:
            if selected.startswith("Brush package") or Path(path).suffix.lower() == ".csbr":
                if Path(path).suffix.lower() != ".csbr": path += ".csbr"
                self.manager.export_csbr(name, path)
            else:
                self.manager.export_preset(name, path)

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

        print(
            f"✓ Preset sauvegardé : {name}"
        )

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

        print(
            f"✓ Nouveau preset créé : {name}"
        )

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
            "Delete Brush Preset",
            f"Supprimer « {name} » ?",
        )

        if answer != QMessageBox.Yes:
            return

        if self.manager.delete(
            name
        ):
            self.refresh()

            print(
                f"✓ Preset supprimé : {name}"
            )

    def open_settings(self):
        if self.canvas is None:
            return
        dialog = BrushSettingsDialog(self.canvas, self)
        dialog.exec()


__all__ = [
    "BrushPresetsDock",
]
