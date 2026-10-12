from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QKeySequenceEdit,
    QFileDialog,
)


class PreferencesDialog(QDialog):
    preference_changed = Signal(str, object)
    # Seven pages instead of twelve, and only settings that are actually
    # applied somewhere: placebo options (language, tooltips, colour
    # management, CPU fallback, recovery copies…) were removed — a release
    # must not offer switches that do nothing.
    CATEGORIES = (
        "Général", "Interface", "Toile", "Stylet et pinceau",
        "Performances", "Fichiers", "Raccourcis",
    )

    # Each setting is stored immediately, so closing the dialog never loses edits.
    OPTIONS = {
        "Général": [
            ("check", "general/restore_session", "Restaurer l'agencement des panneaux au démarrage", True),
        ],
        "Interface": [
            ("check", "interface/compact", "Densité compacte (texte plus petit)", False),
            ("choice", "interface/icon_size", "Taille des icônes d'outils", ["20 px", "24 px", "28 px"], "24 px"),
            ("check", "interface/show_diagnostics", "Afficher les diagnostics mémoire dans la barre d'état", False),
        ],
        "Toile": [
            ("choice", "canvas/zoom_behavior", "Zoom", ["At cursor", "At canvas center"], "At cursor",
             {"At cursor": "Sous le curseur", "At canvas center": "Au centre de la toile"}),
            ("choice", "canvas/background", "Fond autour du document", ["Checkerboard", "Dark", "Light"], "Checkerboard",
             {"Checkerboard": "Damier", "Dark": "Sombre", "Light": "Clair"}),
            ("check", "canvas/antialias", "Lisser le rendu de la toile", True),
        ],
        "Stylet et pinceau": [
            ("check", "tablet/pressure", "Utiliser la pression du stylet", True),
            ("check", "tablet/pressure_size", "La pression contrôle la taille", True),
            ("check", "tablet/pressure_opacity", "La pression contrôle l'opacité", True),
            ("check", "tablet/ignore_mouse_after_tablet", "Ignorer les clics souris générés par le stylet", True),
            ("check", "input/stabilization", "Activer le stabilisateur de trait", True),
            ("number", "input/stabilization_amount", "Force du stabilisateur (%)", 0, 100, 20),
            ("check", "input/right_click_palette", "Clic droit : palette rapide (sinon pipette ; Alt+clic reste la pipette)", True),
            ("number", "brush/spacing", "Espacement par défaut (%)", 1, 500, 10),
            ("check", "brush/remember_per_tool", "Mémoriser les réglages par outil", True),
            ("check", "brush/show_cursor_preview", "Afficher le contour du pinceau", True),
        ],
        "Performances": [
            ("choice", "performance/memory_profile", "Profil mémoire", ["Prudent", "Équilibré", "Performance", "Manuel"], "Équilibré"),
            ("number", "performance/memory_limit_mb", "Limite mémoire de Nebula (Mo)", 256, 65536, 2048),
            ("number", "performance/undo_steps", "Nombre d'annulations", 1, 1000, 100),
            ("number", "performance/undo_memory_limit_mb", "Mémoire de l'historique (Mo)", 8, 8192, 512),
            ("path", "performance/scratch_directory", "Dossier d'échange des tuiles", ""),
            ("check", "performance/use_gpu", "Utiliser la toile GPU si disponible", True),
            ("choice", "cpu/threads", "Threads de calcul", ["Automatic", "1", "2", "4", "8"], "Automatic",
             {"Automatic": "Automatique"}),
            ("number", "cpu/cache_mb", "Cache d'image (Mo)", 64, 65536, 1024),
        ],
        "Fichiers": [
            ("choice", "files/default_format", "Format de document par défaut",
             [".nebula", ".nbl", ".psd", ".psb", ".png", ".tif"], ".nebula"),
            ("check", "files/remember_directory", "Se souvenir du dernier dossier", True),
            ("check", "files/compress_documents", "Compresser les documents", True),
            ("check", "autosave/enabled", "Sauvegarde automatique", True),
            ("number", "autosave/interval_minutes", "Intervalle de sauvegarde (minutes)", 1, 120, 5),
        ],
    }

    def __init__(self, canvas, actions: dict, parent=None) -> None:
        super().__init__(parent)
        self.canvas, self.actions = canvas, actions
        self.settings = QSettings("CreativeSystem", "CreativeSystem")
        self.setWindowTitle("Préférences — Nebula")
        self.resize(780, 560)
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(165)
        self.navigation.addItems(self.CATEGORIES)
        self.pages = QStackedWidget()
        root.addWidget(self.navigation)
        root.addWidget(self.pages, 1)
        for name in self.CATEGORIES:
            self.pages.addWidget(self._shortcuts_page() if name == "Raccourcis" else self._standard_page(name))
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

    def _standard_page(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(name.upper())
        title.setObjectName("dockTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        for option in self.OPTIONS.get(name, []):
            kind, key, label, *args = option
            if kind == "check":
                default = args[0]
                control = QCheckBox(label)
                control.setChecked(self.settings.value(key, default, bool))
                control.toggled.connect(lambda value, setting=key: self._store(setting, value))
                form.addRow(control)
            elif kind == "choice":
                choices, default = args[0], args[1]
                # Stored values stay stable (existing settings keep working);
                # only what the user reads is translated.
                display = args[2] if len(args) > 2 else {}
                control = QComboBox()
                for choice in choices:
                    control.addItem(display.get(choice, choice), choice)
                value = str(self.settings.value(key, default))
                control.setCurrentIndex(max(0, choices.index(value if value in choices else default)))
                control.currentIndexChanged.connect(
                    lambda index, setting=key, box=control: self._store(setting, box.itemData(index)))
                form.addRow(label, control)
            elif kind == "path":
                default = args[0]
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                control = QLineEdit(str(self.settings.value(key, default)))
                browse = QPushButton("Parcourir…")
                browse.clicked.connect(lambda _=False, edit=control, setting=key: self._choose_directory(setting, edit))
                control.editingFinished.connect(lambda edit=control, setting=key: self._store(setting, edit.text()))
                row_layout.addWidget(control, 1)
                row_layout.addWidget(browse)
                form.addRow(label, row)
            else:
                minimum, maximum, default = args
                control = QSpinBox()
                control.setRange(minimum, maximum)
                control.setValue(self.settings.value(key, default, int))
                control.valueChanged.connect(lambda value, setting=key: self._store(setting, value))
                form.addRow(label, control)
        layout.addLayout(form)
        if name == "Performances":
            fixed_tiles = QLabel("Prudent : 35 % de la RAM · Équilibré : 60 % · Performance : 75 % · "
                                 "Manuel conserve la limite indiquée.")
            fixed_tiles.setObjectName("mutedLabel")
            layout.addWidget(fixed_tiles)
        layout.addStretch()
        return page

    def _store(self, key: str, value) -> None:
        self.settings.setValue(key, value)
        self.preference_changed.emit(key, value)

    def _choose_directory(self, key: str, control: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Dossier d'échange des tuiles", control.text())
        if selected:
            control.setText(selected)
            self._store(key, selected)

    def _shortcuts_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        title = QLabel("RACCOURCIS CLAVIER"); title.setObjectName("dockTitle"); layout.addWidget(title)
        search = QLineEdit(); search.setPlaceholderText("Rechercher une commande…"); layout.addWidget(search)
        self.shortcut_status = QLabel(" "); layout.addWidget(self.shortcut_status)
        table = QTableWidget(0, 2); table.setHorizontalHeaderLabels(["Commande", "Raccourci"])
        table.horizontalHeader().setStretchLastSection(True)
        defaults = {}
        for action_id, action in sorted(self.actions.items()):
            if not action.text(): continue
            row = table.rowCount(); table.insertRow(row)
            item = QTableWidgetItem(action.text().replace("&", "")); item.setData(Qt.ItemDataRole.UserRole, action_id); table.setItem(row, 0, item)
            editor = QKeySequenceEdit(action.shortcut()); table.setCellWidget(row, 1, editor)
            defaults[action_id] = QKeySequence(action.shortcut())
            editor.keySequenceChanged.connect(lambda seq, a=action, key=action_id, edit=editor: self._set_shortcut(key, a, seq, edit))
        search.textChanged.connect(lambda text: self._filter(table, text))
        layout.addWidget(table, 1)
        reset = QPushButton("Rétablir les raccourcis par défaut")
        reset.clicked.connect(lambda: self._restore_defaults(table, defaults))
        layout.addWidget(reset); return page

    def _set_shortcut(self, key, action, sequence, editor) -> None:
        for other_key, other in self.actions.items():
            if other_key != key and not sequence.isEmpty() and other.shortcut() == sequence:
                blocked = editor.blockSignals(True)
                editor.setKeySequence(action.shortcut())
                editor.blockSignals(blocked)
                self.shortcut_status.setText(f"{sequence.toString()} est déjà attribué à {other.text().replace('&', '')}.")
                return
        self.shortcut_status.setText(" ")
        action.setShortcut(sequence); self.settings.setValue(f"shortcuts/{key}", sequence.toString())

    @staticmethod
    def _filter(table, text: str) -> None:
        needle = text.casefold()
        for row in range(table.rowCount()): table.setRowHidden(row, needle not in table.item(row, 0).text().casefold())

    def _restore_defaults(self, table, defaults) -> None:
        for row in range(table.rowCount()):
            key = table.item(row, 0).data(Qt.ItemDataRole.UserRole); action = self.actions[key]
            action.setShortcut(defaults[key]); table.cellWidget(row, 1).setKeySequence(defaults[key]); self.settings.remove(f"shortcuts/{key}")
