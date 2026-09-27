"""Assistants de dessin — panneau latéral.

Permet d'ajouter / supprimer / activer des assistants (règle, ellipse,
perspective 1pt/2pt, règle parallèle, cercles concentriques) et active
le mode "construction de handle" sur le canvas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QCheckBox, QComboBox, QToolButton,
)
from PySide6.QtGui import QIcon, QColor

from CANVAS.canvas_assistants import AssistantManager

_KINDS = [
    ("ruler",           "Règle droite"),
    ("parallel_ruler",  "Règle parallèle"),
    ("ellipse",         "Ellipse"),
    ("perspective_1pt", "Perspective 1 point"),
    ("perspective_2pt", "Perspective 2 points"),
    ("concentric",      "Cercles concentriques"),
]


class AssistantsDock(QDockWidget):
    """Dock for managing drawing assistants."""

    # Emitted when the user wants to begin placing a new assistant
    begin_build_requested = Signal(str)   # kind string
    # Emitted when snap toggle changes
    snap_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Assistants de dessin", parent)
        self.setObjectName("assistants_dock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._manager: AssistantManager | None = None

        root = QWidget()
        self.setWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # ── Kind selector + Add button ──────────────────────────────────────
        kind_row = QHBoxLayout()
        self._kind_box = QComboBox()
        for k, label in _KINDS:
            self._kind_box.addItem(label, k)
        kind_row.addWidget(self._kind_box, 1)

        self._add_btn = QPushButton("＋ Ajouter")
        self._add_btn.setFixedWidth(90)
        self._add_btn.clicked.connect(self._on_add)
        kind_row.addWidget(self._add_btn)
        lay.addLayout(kind_row)

        # ── Snap toggle ──────────────────────────────────────────────────────
        self._snap_check = QCheckBox("Magnétisme activé")
        self._snap_check.setChecked(True)
        self._snap_check.toggled.connect(self._on_snap_toggled)
        lay.addWidget(self._snap_check)

        # ── Assistant list ───────────────────────────────────────────────────
        lay.addWidget(QLabel("Assistants actifs :"))
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        lay.addWidget(self._list, 1)

        # ── Remove / toggle row ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._toggle_btn = QPushButton("Activer / Désactiver")
        self._toggle_btn.clicked.connect(self._on_toggle_selected)
        self._remove_btn = QPushButton("🗑 Supprimer")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        self._clear_btn = QPushButton("Tout effacer")
        self._clear_btn.clicked.connect(self._on_clear_all)
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addWidget(self._clear_btn)
        lay.addLayout(btn_row)

        # ── Build-mode hint ─────────────────────────────────────────────────
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #aaa; font-size: 11px;")
        lay.addWidget(self._hint)

    # ── public API ────────────────────────────────────────────────────────────

    def set_manager(self, manager: AssistantManager) -> None:
        self._manager = manager
        self._refresh_list()

    def refresh(self) -> None:
        self._refresh_list()

    def set_building_hint(self, kind: str, handles_placed: int, handles_needed: int) -> None:
        if handles_placed >= handles_needed:
            self._hint.setText("✅ Assistant placé — cliquer pour peindre.")
        else:
            remaining = handles_needed - handles_placed
            self._hint.setText(
                f"Cliquer pour placer le point {handles_placed + 1}/{handles_needed}…"
                f" ({remaining} restant{'s' if remaining > 1 else ''})"
            )

    # ── internals ─────────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._list.clear()
        if self._manager is None:
            return
        kind_labels = {k: lbl for k, lbl in _KINDS}
        for a in self._manager.assistants():
            label = kind_labels.get(a.LABEL, a.LABEL)
            status = "✓" if a.active else "✗"
            item = QListWidgetItem(f"{status}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, a.id)
            if not a.active:
                item.setForeground(QColor(120, 120, 120))
            self._list.addItem(item)

    def _on_add(self) -> None:
        kind = self._kind_box.currentData()
        if kind:
            self.begin_build_requested.emit(kind)

    def _on_toggle_selected(self) -> None:
        item = self._list.currentItem()
        if item is None or self._manager is None:
            return
        aid = item.data(Qt.ItemDataRole.UserRole)
        for a in self._manager.assistants():
            if a.id == aid:
                a.active = not a.active
                break
        self._refresh_list()

    def _on_remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None or self._manager is None:
            return
        aid = item.data(Qt.ItemDataRole.UserRole)
        self._manager.remove(aid)
        self._refresh_list()

    def _on_clear_all(self) -> None:
        if self._manager is None:
            return
        self._manager.clear()
        self._refresh_list()

    def _on_snap_toggled(self, checked: bool) -> None:
        if self._manager is not None:
            self._manager.snap_enabled = checked
        self.snap_toggled.emit(checked)
