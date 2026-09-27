from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QKeySequenceEdit,
    QFileDialog,
)


class PreferencesDialog(QDialog):
    preference_changed = Signal(str, object)
    CATEGORIES = (
        "General", "Interface", "Canvas", "Input", "Tablet", "Brush",
        "Performance", "CPU", "Files", "Autosave", "Color Management",
        "Shortcuts",
    )

    # Each setting is stored immediately, so closing the dialog never loses edits.
    OPTIONS = {
        "General": [
            ("check", "general/restore_session", "Restore the last workspace on launch", True),
            ("check", "general/confirm_exit", "Confirm before closing with unsaved changes", True),
            ("choice", "general/language", "Language", ["System", "English", "Français"], "System"),
        ],
        "Interface": [
            ("check", "interface/compact", "Compact professional density", True),
            ("check", "interface/tooltips", "Show tooltips", True),
            ("choice", "interface/icon_size", "Toolbar icon size", ["20 px", "24 px", "28 px"], "24 px"),
        ],
        "Canvas": [
            ("choice", "canvas/zoom_behavior", "Zoom behavior", ["At cursor", "At canvas center"], "At cursor"),
            ("choice", "canvas/background", "Canvas background", ["Checkerboard", "Dark", "Light"], "Checkerboard"),
            ("check", "canvas/antialias", "Enable canvas antialiasing", True),
        ],
        "Input": [
            ("check", "input/stabilization", "Enable brush stroke stabilization", True),
            ("number", "input/stabilization_amount", "Stabilization amount", 0, 100, 20),
            ("check", "input/right_click_color_picker", "Right click temporarily picks color", True),
        ],
        "Tablet": [
            ("check", "tablet/pressure", "Enable tablet pressure", True),
            ("check", "tablet/pressure_size", "Pressure controls brush size", True),
            ("check", "tablet/pressure_opacity", "Pressure controls opacity", True),
            ("check", "tablet/ignore_mouse_after_tablet", "Ignore synthetic mouse events", True),
        ],
        "Brush": [
            ("number", "brush/spacing", "Default brush spacing (%)", 1, 500, 10),
            ("check", "brush/remember_per_tool", "Remember settings per tool", True),
            ("check", "brush/show_cursor_preview", "Show brush cursor preview", True),
        ],
        "Performance": [
            ("number", "performance/memory_limit_mb", "Application RAM limit (MB)", 256, 65536, 2048),
            ("number", "performance/undo_steps", "Undo history steps", 1, 1000, 100),
            ("path", "performance/scratch_directory", "Tile scratch directory", ""),
            ("check", "performance/use_gpu", "Use GPU canvas when available", True),
        ],
        "CPU": [
            ("choice", "cpu/threads", "Worker threads", ["Automatic", "1", "2", "4", "8"], "Automatic"),
            ("number", "cpu/cache_mb", "Image cache limit (MB)", 64, 65536, 1024),
            ("check", "cpu/allow_fallback", "Allow CPU rendering fallback", True),
        ],
        "Files": [
            ("choice", "files/default_format", "Default document format", [".nebula", ".nbl", ".png", ".tif"], ".nebula"),
            ("check", "files/remember_directory", "Remember last open/save directory", True),
            ("check", "files/compress_documents", "Compress document archives", True),
        ],
        "Autosave": [
            ("check", "autosave/enabled", "Enable autosave", True),
            ("number", "autosave/interval_minutes", "Autosave interval (minutes)", 1, 120, 5),
            ("number", "autosave/keep_copies", "Recovery copies to keep", 1, 100, 10),
        ],
        "Color Management": [
            ("choice", "color/working_space", "Working color space", ["sRGB", "Display P3", "Adobe RGB"], "sRGB"),
            ("choice", "color/rendering_intent", "Rendering intent", ["Perceptual", "Relative colorimetric", "Saturation", "Absolute colorimetric"], "Perceptual"),
            ("check", "color/embed_profile", "Embed profile in exported images", True),
        ],
    }

    def __init__(self, canvas, actions: dict, parent=None) -> None:
        super().__init__(parent)
        self.canvas, self.actions = canvas, actions
        self.settings = QSettings("CreativeSystem", "CreativeSystem")
        self.setWindowTitle("CreativeSystem Preferences")
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
            self.pages.addWidget(self._shortcuts_page() if name == "Shortcuts" else self._standard_page(name))
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
                choices, default = args
                control = QComboBox()
                control.addItems(choices)
                value = str(self.settings.value(key, default))
                control.setCurrentText(value if value in choices else default)
                control.currentTextChanged.connect(lambda value, setting=key: self._store(setting, value))
                form.addRow(label, control)
            elif kind == "path":
                default = args[0]
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                control = QLineEdit(str(self.settings.value(key, default)))
                browse = QPushButton("Browse…")
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
        if name == "Performance":
            fixed_tiles = QLabel("Tile size: 64 × 64 px (fixed for document and undo compatibility)")
            fixed_tiles.setObjectName("mutedLabel")
            layout.addWidget(fixed_tiles)
        layout.addStretch()
        return page

    def _store(self, key: str, value) -> None:
        self.settings.setValue(key, value)
        self.preference_changed.emit(key, value)

    def _choose_directory(self, key: str, control: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose tile scratch directory", control.text())
        if selected:
            control.setText(selected)
            self._store(key, selected)

    def _shortcuts_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        title = QLabel("KEYBOARD SHORTCUTS"); title.setObjectName("dockTitle"); layout.addWidget(title)
        search = QLineEdit(); search.setPlaceholderText("Search actions…"); layout.addWidget(search)
        self.shortcut_status = QLabel(" "); layout.addWidget(self.shortcut_status)
        table = QTableWidget(0, 2); table.setHorizontalHeaderLabels(["Action", "Shortcut"])
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
        reset = QPushButton("Restore default shortcuts")
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
