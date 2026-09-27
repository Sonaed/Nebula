from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
import json
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFileDialog, QListWidget, QListWidgetItem,
                               QToolButton, QVBoxLayout, QWidget, QDockWidget, QLabel,
                               QHBoxLayout, QInputDialog, QMessageBox, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QPushButton)
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap

from TOOLS.resource_manager import APP_ID, ResourceManager
from PySide6.QtWidgets import QMenu

APP_NAMES = {"nebula": "Nebula", "stardust": "StarDust", "atlas": "Atlas", "cosmos": "Cosmos",
             "singularity": "Singularity"}
from existence.module_adapter import ExistenceModuleAdapter


class ResourceDock(QDockWidget):
    """Unified browser for Nebula brushes, textures, palettes, styles and ICC."""

    blend_applied = Signal(object)
    brushes_synced = Signal(list)   # pinceaux installés depuis la bibliothèque centrale

    def __init__(self, manager: ResourceManager, parent=None, canvas=None) -> None:
        super().__init__("RESSOURCES", parent)
        self.manager = manager
        self.canvas = canvas
        self.setObjectName("ResourceDock")
        self.existence_module = ExistenceModuleAdapter("resource_center")
        self.setProperty("existenceModuleId", self.existence_module.module_id)
        body = QWidget(self)
        layout = QVBoxLayout(body)
        self.kind = QComboBox(body)
        self.kind.addItem("Toutes", "")
        for value in manager.KINDS:
            self.kind.addItem(value.replace("_", " ").title(), value)
        layout.addWidget(self.kind)
        self.scope = QComboBox(body)
        self.scope.addItem("Utilisables dans Nebula", APP_ID)
        self.scope.addItem("Toute la bibliothèque (toutes les apps)", None)
        self.scope.setToolTip("Bibliothèque centrale d'Existence : chaque ressource est étiquetée\n"
                              "avec les applications qui peuvent l'utiliser.")
        layout.addWidget(self.scope)
        self.search = QLineEdit(body)
        self.search.setPlaceholderText("Rechercher dans la bibliothèque…")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.items = QListWidget(body)
        self.items.itemDoubleClicked.connect(self.apply_selected)
        layout.addWidget(self.items, 1)
        self.palette_tree = QTreeWidget(body)
        self.palette_tree.setHeaderHidden(True)
        self.palette_tree.setIndentation(18)
        self.palette_tree.setRootIsDecorated(True)
        self.palette_tree.itemClicked.connect(self._palette_item_clicked)
        self.palette_tree.hide()
        layout.addWidget(self.palette_tree, 1)
        self.status = QLabel("Double-cliquez pour appliquer une ressource.", body)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.import_button = QToolButton(body)
        self.import_button.setText("⇩")
        self.import_button.setToolTip("Importer une ressource")
        self.import_button.clicked.connect(self.import_resource)
        self.apply_button = QToolButton(body)
        self.apply_button.setText("✓")
        self.apply_button.setToolTip("Appliquer la ressource sélectionnée")
        self.apply_button.clicked.connect(self.apply_selected)
        actions = QHBoxLayout()
        self.rename_button = QToolButton(body)
        self.rename_button.setText("✎")
        self.rename_button.setToolTip("Renommer la ressource")
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button = QToolButton(body)
        self.delete_button.setText("⌫")
        self.delete_button.setToolTip("Supprimer la ressource")
        self.delete_button.clicked.connect(self.delete_selected)
        self.apps_button = QToolButton(body)
        self.apps_button.setText("⌘")
        self.apps_button.setToolTip("Applications qui peuvent utiliser cette ressource")
        self.apps_button.clicked.connect(self.edit_apps)
        for button in (self.import_button, self.apply_button, self.apps_button, self.rename_button, self.delete_button):
            button.setFixedSize(30, 30)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.setWidget(body)
        # Branché seulement maintenant : remplir le combo ci-dessus émet
        # currentIndexChanged, et refresh() touche des widgets créés après lui.
        self.kind.currentIndexChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def sync_central_library(self) -> None:
        """Installe les pinceaux publiés ailleurs (StarDust…) dans les presets Nebula."""
        presets = getattr(self.canvas, "brush_preset_manager", None) if self.canvas is not None else None
        sync = getattr(self.manager, "sync_brush_presets", None)
        if presets is None or sync is None:
            return
        try:
            installed = sync(presets)
        except (OSError, ValueError):
            return
        if installed:
            self.status.setText(f"{len(installed)} pinceau(x) ajouté(s) depuis la bibliothèque : " + ", ".join(installed[:4]))
            self.brushes_synced.emit(installed)

    @staticmethod
    def _apps_label(record) -> str:
        apps = getattr(record, "apps", ()) or ()
        return " · ".join(APP_NAMES.get(a, a) for a in apps)

    def edit_apps(self) -> None:
        record = self._selected_record()
        if record is None or getattr(self.manager, "library", None) is None:
            self.status.setText("Sélectionnez une ressource (bibliothèque centrale requise).")
            return
        current = set(getattr(record, "apps", ()) or ())
        menu = QMenu(self)
        menu.addSection(f"« {record.name} » utilisable dans")
        actions = {}
        for app_id, label in APP_NAMES.items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(app_id in current)
            actions[action] = app_id
        chosen = menu.exec(self.apps_button.mapToGlobal(self.apps_button.rect().bottomLeft()))
        if chosen is None:
            return
        app_id = actions[chosen]
        current.symmetric_difference_update({app_id})
        self.manager.set_apps(record, sorted(current))
        self.refresh()
        self.status.setText(f"« {record.name} » : " + (", ".join(APP_NAMES.get(a, a) for a in sorted(current)) or "aucune application"))

    def refresh(self) -> None:
        self.items.clear()
        self.palette_tree.clear()
        if not getattr(self, "_synced_once", False):
            self._synced_once = True
            self.sync_central_library()
        selected = self.kind.currentData()
        query = self.search.text().strip().casefold()
        scope = self.scope.currentData() if hasattr(self, "scope") else APP_ID
        try:
            catalog = self.manager.catalog(selected or None, app=scope)
        except TypeError:   # gestionnaire sans étiquettes
            catalog = self.manager.catalog(selected or None)
        records = [record for record in catalog
                   if not query or query in record.name.casefold() or query in record.kind.casefold()]
        palette_mode = selected in {"palettes", "gradients"}
        all_mode = not selected
        tree_mode = palette_mode or all_mode
        self.items.setVisible(not palette_mode)
        self.palette_tree.setVisible(tree_mode)
        if tree_mode:
            for record in records:
                record_kind = selected or record.kind
                if record_kind not in {"palettes", "gradients"}:
                    self.items.addItem(f"{record.kind.replace('_', ' ')} · {record.name}")
                    self.items.item(self.items.count() - 1).setData(Qt.ItemDataRole.UserRole, record)
                    self.items.item(self.items.count() - 1).setToolTip(self._apps_label(record) or "Toutes les applications")
                    continue
                values = (self._palette_colors(record.path)
                          if record_kind == "palettes" else self._gradient_stops(record.path))
                folder = QTreeWidgetItem([record.name])
                folder.setData(0, Qt.ItemDataRole.UserRole, record)
                label = "couleurs" if record_kind == "palettes" else "dégradé"
                folder.setToolTip(0, f"{len(values)} {label} · cliquer pour ouvrir/fermer\n"
                                     f"Applications : {self._apps_label(record) or 'toutes'}")
                self.palette_tree.addTopLevelItem(folder)
                if record_kind == "palettes":
                    child = QTreeWidgetItem(folder)
                    swatches = QWidget(self.palette_tree)
                    swatch_layout = QHBoxLayout(swatches)
                    swatch_layout.setContentsMargins(2, 3, 2, 3)
                    swatch_layout.setSpacing(4)
                    for index, color in enumerate(values):
                        rgba = self._rgba(color)
                        if rgba is None:
                            continue
                        button = QPushButton(swatches)
                        button.setFixedSize(32, 32)
                        button.setToolTip(f"{color} · appliquer")
                        button.setStyleSheet(f"background: {color}; border: 1px solid rgba(255,255,255,90); border-radius: 4px;")
                        button.clicked.connect(lambda _checked=False, value=rgba: self._apply_color(value))
                        swatch_layout.addWidget(button)
                    swatch_layout.addStretch(1)
                    child.setSizeHint(0, QSize(0, 40))
                    self.palette_tree.setItemWidget(child, 0, swatches)
                else:
                    child = QTreeWidgetItem(folder)
                    preview = self._gradient_preview(values, width=260, height=42)
                    child.setSizeHint(0, QSize(0, 48))
                    child.setData(0, Qt.ItemDataRole.UserRole, {"gradient": record.path})
                    preview_button = QPushButton(self.palette_tree)
                    preview_button.setIcon(QIcon(preview))
                    preview_button.setIconSize(QSize(260, 42))
                    preview_button.setFixedSize(268, 46)
                    preview_button.setFlat(True)
                    preview_button.setToolTip("Cliquer pour appliquer ce dégradé")
                    preview_button.clicked.connect(lambda _checked=False, path=record.path: self._apply_gradient(path))
                    self.palette_tree.setItemWidget(child, 0, preview_button)
            if all_mode and self.items.count() == 0:
                self.items.hide()
                folder.setExpanded(False)
        else:
            for record in records:
                self.items.addItem(f"{record.kind.replace('_', ' ')} · {record.name}")
                self.items.item(self.items.count() - 1).setData(Qt.ItemDataRole.UserRole, record)
                self.items.item(self.items.count() - 1).setToolTip(self._apps_label(record) or "Toutes les applications")
        if not records and not tree_mode:
            # Une liste vide sans explication fait croire à une perte de données.
            label = self.kind.currentText() if selected else "la bibliothèque"
            empty = QListWidgetItem(f"Aucune ressource dans {label}.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.items.addItem(empty)
        self._sync_import_button()
        self.rename_button.setEnabled(bool(records))
        self.delete_button.setEnabled(bool(records))

    def _palette_item_clicked(self, item, _column=0) -> None:
        rgba = item.data(0, Qt.ItemDataRole.UserRole)
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())
            return
        if isinstance(rgba, list) and self.canvas is not None:
            self.canvas.set_brush_setting("color", rgba)
            self.status.setText(f"Couleur appliquée : {self._color_hex(rgba)}")
        elif isinstance(rgba, dict) and "gradient" in rgba and self.canvas is not None:
            self._apply_gradient(rgba["gradient"])

    def _apply_color(self, rgba) -> None:
        if self.canvas is not None:
            self.canvas.set_brush_setting("color", rgba)
            self.status.setText(f"Couleur appliquée : {self._color_hex(rgba)}")

    def _apply_gradient(self, path: Path) -> None:
        if self.canvas is None:
            return
        stops = self._gradient_stops(path)
        if stops:
            color = self._rgba(stops[-1].get("color") if isinstance(stops[-1], dict) else stops[-1])
            if color is not None:
                self.canvas.set_brush_setting("gradientColor", color)
                self.status.setText(f"Dégradé appliqué : {Path(path).stem}")

    @staticmethod
    def _color_hex(rgba) -> str:
        return "#" + "".join(f"{int(channel):02X}" for channel in rgba[:3])

    def _palette_colors(self, path: Path):
        if path.suffix.lower() == ".gpl":
            values = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                fields = line.split()
                if len(fields) >= 3 and all(field.isdigit() for field in fields[:3]):
                    values.append(self._color_hex([int(field) for field in fields[:3]]))
            return values
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data.get("colors", data) if isinstance(data, dict) else data
        return values if isinstance(values, list) else []

    def _gradient_stops(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        stops = data.get("stops", data.get("colors", [])) if isinstance(data, dict) else data
        return stops if isinstance(stops, list) else []

    def _gradient_preview(self, stops, width=96, height=24) -> QPixmap:
        preview = QPixmap(width, height)
        preview.fill(Qt.GlobalColor.transparent)
        gradient = QLinearGradient(0, 0, width, 0)
        for index, stop in enumerate(stops):
            value = stop.get("color") if isinstance(stop, dict) else stop
            color = self._rgba(value)
            if color is not None:
                position = float(stop.get("position", index / max(1, len(stops) - 1))) if isinstance(stop, dict) else index / max(1, len(stops) - 1)
                gradient.setColorAt(max(0.0, min(1.0, position)), QColor(*color))
        painter = QPainter(preview)
        painter.fillRect(preview.rect(), gradient)
        painter.end()
        return preview

    def _sync_import_button(self) -> None:
        if not hasattr(self, "import_button"):
            return
        kind = self.kind.currentData()
        self.import_button.setEnabled(bool(kind))
        self.import_button.setToolTip(
            f"Importer un fichier dans « {self.kind.currentText()} »."
            if kind
            else "Choisissez d'abord un type de ressource à importer."
        )

    def import_resource(self) -> None:
        kind = self.kind.currentData()
        if not kind:
            return
        suffixes = " ".join(f"*{suffix}" for suffix in self.manager.KINDS[kind])
        path, _ = QFileDialog.getOpenFileName(self, "Importer une ressource", "", f"Ressources ({suffixes})")
        if path:
            try:
                imported = self.manager.import_file(path, kind)
            except (OSError, ValueError) as error:
                self.status.setText(f"Import impossible : {error}")
                return
            if kind in {"brushes", "brush_engines"} and self.canvas is not None:
                presets = getattr(self.canvas, "brush_preset_manager", None)
                if presets is not None:
                    name = (presets.import_csbr(imported) if Path(imported).suffix.lower() == ".csbr"
                            else presets.import_preset(imported))
                    if name:
                        self.brushes_synced.emit([name])
                    else:
                        self.status.setText(f"Fichier ajouté, mais pas utilisable comme pinceau : "
                                            f"{getattr(presets, 'last_error', '') or 'format inconnu'}")
                        self.refresh()
                        return
            self.refresh()
            self.status.setText(f"« {Path(imported).name} » importé.")

    def apply_selected(self, _item=None) -> None:
        if self.kind.currentData() in {"palettes", "gradients"} or self.palette_tree.hasFocus():
            item = self.palette_tree.currentItem()
            if item is not None:
                self._palette_item_clicked(item)
            return
        item = self.items.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if self.canvas is None:
            self.status.setText("Ouvrez un document pour appliquer une ressource.")
            return
        if record is None:
            self.status.setText("Sélectionnez une ressource dans la liste.")
            return
        try:
            if record.kind == "blends":
                from DOCUMENTS.blend_presets import BlendPresetManager
                preset_manager = BlendPresetManager(self.manager.root / "blends")
                name = record.path.stem
                preset = preset_manager.load(name)
                if preset is None and record.path.suffix.lower() == ".csbl":
                    name = preset_manager.import_csbl(record.path)
                    preset = preset_manager.load(name) if name else None
                if preset is not None:
                    self.blend_applied.emit(preset)
                    self.status.setText(f"Fusion appliquée : {name}")
                    return
            elif record.kind in {"brushes", "brush_engines"} and record.path.suffix.lower() in {".csbr", ".json"}:
                presets = self.canvas.brush_preset_manager
                name = (presets.import_csbr(record.path) if record.path.suffix.lower() == ".csbr"
                        else presets.import_preset(record.path))
                if name and self.canvas.load_cpp_brush_preset(name):
                    self.brushes_synced.emit([name])
                    self.status.setText(f"Pinceau appliqué : {name}")
                    return
                if not name:
                    self.status.setText(f"Pinceau illisible : {getattr(presets, 'last_error', '') or 'format inconnu'}")
                    return
            elif record.kind in {"textures", "patterns"}:
                if self.canvas.load_brush_texture(str(record.path)):
                    self.status.setText(f"Texture de pinceau appliquée : {record.name}")
                    return
            elif record.kind == "palettes":
                color = self._first_palette_color(record.path)
                if color is not None:
                    self.canvas.set_brush_setting("color", color)
                    self.status.setText(f"Couleur appliquée depuis : {record.name}")
                    return
            elif record.kind == "gradients":
                color = self._gradient_end_color(record.path)
                if color is not None:
                    self.canvas.set_brush_setting("gradientColor", color)
                    self.status.setText(f"Dégradé chargé : {record.name}")
                    return
            self.status.setText("Ressource importée et prête ; ce format ne peut pas encore être appliqué automatiquement.")
        except (OSError, ValueError, json.JSONDecodeError):
            self.status.setText("Impossible de lire cette ressource.")

    def _selected_record(self):
        tree_active = self.kind.currentData() in {"palettes", "gradients"} or self.palette_tree.hasFocus()
        item = self.palette_tree.currentItem() if tree_active else self.items.currentItem()
        if item is not None and tree_active and item.parent() is not None:
            item = item.parent()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def rename_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        name, accepted = QInputDialog.getText(self, "Renommer la ressource", "Nom", text=record.name)
        if accepted and name.strip():
            try:
                self.manager.rename(record, name)
                self.refresh()
                self.status.setText("Ressource renommée.")
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Ressources", str(error))

    def delete_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        answer = QMessageBox.question(self, "Supprimer la ressource",
                                       f"Supprimer « {record.name} » ?")
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.manager.delete(record)
                self.refresh()
                self.status.setText("Ressource supprimée.")
            except OSError as error:
                QMessageBox.warning(self, "Ressources", str(error))

    @staticmethod
    def _rgba(value):
        if isinstance(value, str) and value.startswith("#") and len(value) in {7, 9}:
            raw = value[1:]
            return [int(raw[offset:offset + 2], 16) for offset in (0, 2, 4)] + ([int(raw[6:8], 16)] if len(raw) == 8 else [255])
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [max(0, min(255, int(channel))) for channel in list(value[:4]) + [255]][:4]
        return None

    def _first_palette_color(self, path: Path):
        if path.suffix.lower() == ".gpl":
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                fields = line.split()
                if len(fields) >= 3 and all(field.isdigit() for field in fields[:3]):
                    return self._rgba(fields[:3])
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data.get("colors", data) if isinstance(data, dict) else data
        return self._rgba(values[0]) if isinstance(values, list) and values else None

    def _gradient_end_color(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        stops = data.get("stops", data.get("colors", [])) if isinstance(data, dict) else data
        if isinstance(stops, list) and stops:
            value = stops[-1].get("color") if isinstance(stops[-1], dict) else stops[-1]
            return self._rgba(value)
        return None
    blend_applied = Signal(object)
