from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
import base64
import math
import random

from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
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
    QMenu,
    QToolButton,
)

from TOOLS.brush_preset_manager import BrushPresetManager
from UI.docks.brush_settings_dialog import BrushSettingsDialog
from UI.theme.palette import COLORS

_ACTION_ICONS = Path(__file__).resolve().parents[1] / "icons" / "actions"


def _action_icon(name: str) -> QIcon:
    path = _ACTION_ICONS / f"{name}.svg"
    return QIcon(str(path)) if path.is_file() else QIcon()

THUMB_W, THUMB_H = 132, 30


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
            "Presets de pinceau",
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
        # The list (34 rendered previews) is filled the first time the panel
        # is shown, not while the application starts with it hidden.
        self._populated = False

    def showEvent(self, event) -> None:
        if not self._populated:
            self.refresh()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        # One readable list at every width: the old icon grid wrapped the
        # category headers into the grid and truncated every name.
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
        self.search.setPlaceholderText("Rechercher un pinceau…")
        self.search.setMinimumWidth(64)
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.setMinimumWidth(72)
        self.category.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.category.setMinimumContentsLength(5)
        self.category.addItem("Toutes", "")
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

        self.list_widget.setSpacing(0)
        self.list_widget.setObjectName("brushPresetList")
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.setIconSize(QSize(THUMB_W, THUMB_H))
        self._thumb_cache: dict[tuple, QPixmap] = {}
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._collapsed_categories: set[str] = set()

        self.list_widget.itemClicked.connect(
            self.on_item_clicked
        )
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_preset_context_menu)

        root.addWidget(
            self.list_widget,
            1
        )

        buttons = QHBoxLayout()
        buttons.setSpacing(2)

        def push(text: str, tooltip: str, slot) -> QPushButton:
            # Kept as attributes for scripts/tests; reachable from the "…" menu.
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            button.setVisible(False)
            return button

        self.save_button = push("", "Enregistrer les modifications du preset", self.save_preset)
        self.new_button = push("", "Nouveau preset", self.new_preset)
        self.new_folder_button = push("", "Nouvelle catégorie", self.new_category)
        self.delete_button = push("", "Supprimer le preset", self.delete_preset)
        self.settings_button = push("", "Réglages du pinceau", self.open_settings)
        self.favorite_button = push("", "Favori", self.toggle_favorite)
        self.duplicate_button = push("", "Dupliquer le preset", self.duplicate_preset)
        self.import_button = push("", "Importer un preset", self.import_preset)
        self.export_button = push("", "Exporter le preset", self.export_preset)
        self.move_category_button = push("", "Déplacer vers une catégorie", self.move_to_category)
        self.list_widget.currentItemChanged.connect(lambda *_: self._sync_edit_controls())

        def tool(icon: str, tooltip: str, slot=None) -> QToolButton:
            button = QToolButton()
            button.setIcon(_action_icon(icon))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setObjectName("layerAction")
            button.setFixedSize(28, 28)
            if slot is not None:
                button.clicked.connect(slot)
            return button

        self.new_tool = tool("plus", "Nouveau preset à partir du pinceau actuel", self.new_preset)
        self.settings_tool = tool("sliders-horizontal", "Réglages du pinceau", self.open_settings)
        self.more_tool = tool("dots-three", "Plus d'actions")
        self.more_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_tool.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        more = QMenu(self.more_tool)
        more.addAction("Enregistrer les modifications", self.save_preset)
        more.addAction("Dupliquer…", self.duplicate_preset)
        more.addAction("Ajouter / retirer des favoris", self.toggle_favorite)
        more.addAction("Déplacer vers une catégorie…", self.move_to_category)
        more.addSeparator()
        more.addAction("Nouvelle catégorie…", self.new_category)
        more.addAction("Importer…", self.import_preset)
        more.addAction("Exporter…", self.export_preset)
        more.addSeparator()
        more.addAction("Supprimer…", self.delete_preset)
        self.more_tool.setMenu(more)
        buttons.addWidget(self.new_tool)
        buttons.addWidget(self.settings_tool)
        buttons.addStretch(1)
        buttons.addWidget(self.more_tool)
        root.addLayout(buttons)

        self.setWidget(
            container
        )

    # ========================================================
    # REFRESH
    # ========================================================

    CATEGORY_LABELS = {
        "01_Sketching": "Esquisse", "02_Inking": "Encrage", "03_Painting": "Peinture",
        "04_Airbrush": "Aérographe", "05_Texture": "Texture", "06_Erasers": "Gommes",
        "07_Utility": "Utilitaires",
    }

    @classmethod
    def category_label(cls, category: str) -> str:
        """Readable name for a category folder ("01_Sketching" → "Esquisse")."""
        if category in cls.CATEGORY_LABELS:
            return cls.CATEGORY_LABELS[category]
        head, _, tail = category.partition("_")
        return tail if head.isdigit() and tail else category

    def refresh(self, *_args):
        self._populated = True
        current = (
            self.current_preset_name()
        )

        self.list_widget.clear()

        records = [self.manager.metadata(name) for name in self.manager.list_presets()]
        categories = self.manager.categories()
        selected_category = self.category.currentData() or ""
        blocked = self.category.blockSignals(True)
        self.category.clear(); self.category.addItem("Toutes", "")
        for category in categories:
            self.category.addItem(self.category_label(category), category)
        index = self.category.findData(selected_category) if selected_category in categories else 0
        self.category.setCurrentIndex(max(0, index))
        self.category.blockSignals(blocked)
        needle = self.search.text().strip().casefold()
        chosen = self.category.currentData() or ""
        for category in categories:
            filtered = [record for record in records if record["category"] == category
                        and (not needle or needle in record["name"].casefold())
                        and (not chosen or record["category"] == chosen)]
            if not filtered:
                continue
            collapsed = category in self._collapsed_categories
            header = QListWidgetItem(("▸  " if collapsed else "▾  ") + self.category_label(category).upper())
            header.setSizeHint(QSize(0, 30))
            header.setForeground(QColor(COLORS["text_muted"]))
            font = header.font(); font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5)); font.setBold(True)
            font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 0.8); header.setFont(font)
            header.setData(Qt.UserRole + 1, category)
            header.setData(Qt.UserRole + 2, "category")
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(header)
            if collapsed:
                continue
            for record in filtered:
                name = record["name"]
                item = QListWidgetItem(name + ("  ★" if record["favorite"] else ""))
                item.setIcon(QIcon(self._thumbnail(name)))
                item.setSizeHint(QSize(0, THUMB_H + 10))
                item.setToolTip(name)
                item.setData(Qt.UserRole, name)
                self.list_widget.addItem(item)


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

    def _show_preset_context_menu(self, pos) -> None:
        """Keep every preset action available from the item under the cursor."""
        item = self.list_widget.itemAt(pos)
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not name:
            return
        self.list_widget.setCurrentItem(item)
        read_only = bool(self.manager.metadata(name).get("builtIn"))
        menu = QMenu(self)
        menu.addAction("Appliquer", lambda: self.load_preset(name))
        if not read_only:
            menu.addAction("Renommer…", self.rename_preset)
        menu.addAction("Dupliquer…", self.duplicate_preset)
        if not read_only:
            menu.addAction("Supprimer…", self.delete_preset)
        menu.addSeparator()
        menu.addAction("Exporter…", self.export_preset)
        menu.addAction("Importer…", self.import_preset)
        menu.addSeparator()
        menu.addAction("Restaurer le preset standard", self.restore_default_preset)
        menu.exec(self.list_widget.mapToGlobal(pos))

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
            QMessageBox.warning(self, "Presets de pinceau", message)

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

            self._notify(f"Pinceau « {name} » appliqué.")

        return bool(success)

    def _thumbnail(self, name: str) -> QPixmap:
        """Stamp the preset's real tip along a pressure-tapered stroke."""
        path = self.manager.preset_path(name)
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        key = (name, stamp)
        cached = self._thumb_cache.get(key) if hasattr(self, "_thumb_cache") else None
        if cached is not None:
            return cached
        pixmap = QPixmap.fromImage(self._render_thumbnail(self.manager.load(name) or {}, name))
        if hasattr(self, "_thumb_cache"):
            self._thumb_cache[key] = pixmap
        return pixmap

    @staticmethod
    def _render_thumbnail(settings: dict, name: str = "") -> QImage:
        scale = 2  # rendered at 2x for crisp HiDPI icons
        width, height = THUMB_W * scale, THUMB_H * scale
        ink = QColor(232, 233, 238)
        result = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)

        def number(key, default):
            try:
                return float(settings.get(key, default))
            except (TypeError, ValueError):
                return float(default)

        eraser = bool(settings.get("eraser"))
        smudge = bool(settings.get("smudgeTool"))
        if eraser or smudge:
            band = QPainter(result)
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0.0, QColor(84, 120, 186)); gradient.setColorAt(0.49, QColor(84, 120, 186))
            gradient.setColorAt(0.51, QColor(214, 164, 70)); gradient.setColorAt(1.0, QColor(214, 164, 70))
            band.fillRect(6 * scale, 7 * scale, width - 12 * scale, height - 14 * scale, gradient)
            band.end()

        tip = QImage()
        encoded = settings.get("_csbr_bitmap_tip_png")
        if encoded:
            try:
                tip = QImage.fromData(base64.b64decode(encoded, validate=True))
            except (ValueError, TypeError):
                tip = QImage()

        max_d = max(3.0, min(22.0, number("size", 10.0) / 2.6)) * scale
        hardness = max(0.0, min(1.0, number("hardness", 0.8)))
        roundness = max(0.15, min(1.0, number("roundness", 1.0)))
        spacing = max(0.03, min(2.0, number("spacing", 0.1)))
        flow = max(0.02, min(1.0, number("flow", 1.0)))
        opacity = max(0.05, min(1.0, number("opacity", 1.0)))
        scatter = max(0.0, min(2.0, number("scatter", 0.0)))
        size_jitter = max(0.0, min(1.0, number("sizeJitter", 0.0)))
        minimum = max(0.0, min(1.0, number("minimumSize", 0.01)))
        follow = number("directionFollow", 0.0) > 0.5
        rng = random.Random(name)

        stroke = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        stroke.fill(Qt.GlobalColor.transparent)
        painter = QPainter(stroke)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        left, right = 10 * scale, width - 10 * scale
        amplitude = (height / 2 - max_d / 2 - 2 * scale) * 0.8
        t = 0.0
        while t <= 1.0:
            pressure = math.sin(math.pi * t) ** 0.7
            x = left + (right - left) * t
            y = height / 2 + amplitude * math.sin(t * 2 * math.pi)
            d = max_d * (minimum + (1 - minimum) * pressure) if settings.get("pressureSize") else max_d
            d *= 1.0 - size_jitter * rng.random()
            d = max(1.2 * scale, d)
            alpha = flow * (pressure if settings.get("pressureFlow") else 1.0)
            if settings.get("pressureOpacity"):
                alpha *= 0.35 + 0.65 * pressure
            ox = (rng.random() - .5) * scatter * max_d
            oy = (rng.random() - .5) * scatter * max_d
            painter.save()
            painter.translate(x + ox, y + oy)
            angle = math.degrees(math.atan(amplitude * 2 * math.pi * math.cos(t * 2 * math.pi) / (right - left)))
            painter.rotate((angle + 90.0) if follow else number("angle", 0.0))
            painter.scale(1.0, roundness)
            painter.setOpacity(max(0.02, min(1.0, alpha)))
            if not tip.isNull():
                dab = QImage(int(d) + 2, int(d) + 2, QImage.Format.Format_ARGB32_Premultiplied)
                dab.fill(ink)
                mask = QPainter(dab)
                mask.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                mask.drawImage(dab.rect(), tip)
                mask.end()
                painter.drawImage(int(-d / 2), int(-d / 2), dab)
            else:
                radius = d / 2
                gradient = QRadialGradient(0, 0, radius)
                solid = QColor(ink); clear = QColor(ink); clear.setAlpha(0)
                gradient.setColorAt(0.0, solid)
                gradient.setColorAt(max(0.0, min(0.98, hardness * 0.97)), solid)
                gradient.setColorAt(1.0, clear)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawEllipse(QRectF(-radius, -radius, d, d))
            painter.restore()
            step = max(0.6 * scale, d * spacing) / (right - left)
            t += step
        painter.end()

        out = QPainter(result)
        if eraser:
            out.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        elif smudge:
            out.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        out.setOpacity(opacity * (0.55 if smudge else 1.0))
        out.drawImage(0, 0, stroke)
        out.end()
        result.setDevicePixelRatio(scale)
        return result

    def toggle_favorite(self):
        name = self.current_preset_name()
        if name:
            current = self.manager.metadata(name)["favorite"]
            self.manager.set_metadata(name, favorite=not current); self.refresh(); self.select_preset(name)

    def duplicate_preset(self):
        name = self.current_preset_name()
        if not name: return
        new_name, accepted = QInputDialog.getText(self, "Dupliquer le preset", "Nom du nouveau preset :", text=f"{name} (copie)")
        if accepted and new_name.strip(): self.manager.duplicate(name, new_name.strip()); self.refresh(); self.select_preset(new_name.strip())

    def rename_preset(self):
        name = self.current_preset_name()
        if not name or self.manager.metadata(name).get("builtIn"):
            return
        new_name, accepted = QInputDialog.getText(self, "Renommer le preset", "Nouveau nom :", text=name)
        new_name = new_name.strip()
        if not accepted or not new_name or new_name == name:
            return
        if self.manager.load(new_name) is not None:
            self._notify(f"Le preset « {new_name} » existe déjà.", warning=True)
            return
        if self.manager.duplicate(name, new_name) is not None and self.manager.delete(name):
            self.refresh()
            self.select_preset(new_name)
            self._notify(f"Preset renommé en « {new_name} ».")

    def restore_default_preset(self):
        """Apply a known bundled brush; personal presets are never overwritten."""
        for name in ("Round Soft", "Pencil HB", "Ink Pen"):
            if self.manager.load(name) is not None:
                self.select_preset(name)
                self.load_preset(name)
                return
        self._notify("Aucun preset standard n'est disponible.", warning=True)

    def import_preset(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un pinceau", "",
            "Pinceaux (*.csbr *.json *.abr);;Pinceaux Photoshop (*.abr);;"
            "Paquets Nebula / moteurs StarDust (*.csbr);;Presets JSON (*.json)")
        if not path:
            return
        if Path(path).suffix.lower() == ".abr":
            self.import_abr_file(path)
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

    def import_abr_file(self, path: str) -> list[str]:
        """Import every brush of a Photoshop .abr into its own category."""
        from PySide6.QtWidgets import QApplication
        from TOOLS.abr_import import AbrError, import_abr
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            names, report = import_abr(path, self.manager)
        except (AbrError, OSError) as error:
            QApplication.restoreOverrideCursor()
            self._notify(f"Import impossible : {error}", warning=True)
            return []
        QApplication.restoreOverrideCursor()
        self.refresh()
        if names:
            self.select_preset(names[0])
        resources = getattr(self.canvas, "resource_manager", None) or getattr(self, "resource_manager", None)
        if resources is not None:
            try:
                resources.import_file(path, "brushes")
            except (OSError, ValueError):
                pass
        summary = f"{len(names)} pinceau(x) importé(s) depuis « {Path(path).name} »."
        if report:
            details = "\n".join(report[:12]) + ("\n…" if len(report) > 12 else "")
            QMessageBox.information(self, "Import Photoshop", f"{summary}\n\nÀ noter :\n{details}")
        self._notify(summary)
        return names

    def export_preset(self):
        name = self.current_preset_name()
        if not name: return
        path, selected = QFileDialog.getSaveFileName(self, "Exporter le pinceau", f"{name}.csbr", "Paquet de pinceau (*.csbr);;Preset JSON (ancien format) (*.json)")
        if path:
            is_package = selected.startswith("Paquet de pinceau") or Path(path).suffix.lower() == ".csbr"
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
            QMessageBox.information(self, "Presets de pinceau", "Les pinceaux intégrés sont en lecture seule. Dupliquez ce preset pour le modifier.")
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
                "Presets de pinceau",
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
            "Nouveau preset",
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
                "Presets de pinceau",
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
