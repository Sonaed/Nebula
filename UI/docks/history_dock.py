"""An inspectable undo timeline backed by the canvas' existing transactions."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QDockWidget, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QStyledItemDelegate, QStyle, QVBoxLayout, QWidget,
)

from UI.theme.palette import COLORS


DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
STATE_ROLE = Qt.ItemDataRole.UserRole + 2


class HistoryDelegate(QStyledItemDelegate):
    """Two-line timeline rows without allocating a QWidget for every step."""

    def sizeHint(self, option, index):
        return QSize(200, 47)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(3, 1, -3, -1)
        state = index.data(STATE_ROLE)
        current = state == "current"
        future = state == "future"
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if current or selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["accent_soft"] if current else COLORS["control"]))
            painter.drawRoundedRect(rect, 5, 5)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(COLORS["control_hover"]))
        x = rect.left() + 15
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        painter.setPen(QPen(QColor(COLORS["accent"] if current else COLORS["text_muted"]), 1.5))
        painter.setBrush(QColor(COLORS["accent"] if current else COLORS["panel"]))
        painter.drawEllipse(QRectF(x - 3.5, rect.center().y() - 3.5, 7, 7))

        number_width = max(29, painter.fontMetrics().horizontalAdvance(str(index.row())) + 14)
        text_rect = rect.adjusted(31, 5, -number_width, -5)
        font = QFont(option.font)
        font.setBold(current)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text_disabled"] if future else COLORS["text"]))
        label = painter.fontMetrics().elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, label)
        font.setBold(False)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text_disabled"] if future else COLORS["text_muted"]))
        detail = index.data(DETAIL_ROLE) or ("État actuel" if current else "Rétablir cette étape" if future else "Étape appliquée")
        detail = painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, detail)
        painter.drawText(rect.adjusted(0, 0, -8, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(index.row()).zfill(2))
        painter.restore()


class HistoryDock(QDockWidget):
    """A visible-only, pixel-free view of the bounded native undo history.

    A jump advances one existing canvas undo/redo per event-loop turn. Every
    turn checks document and branch identity, and a strict budget prevents
    retries if a restore cannot advance. Canvas editing is suspended during
    the jump, so an intermediate state cannot accidentally become a branch.
    """

    def __init__(self, canvas, parent=None):
        super().__init__("Historique", parent)
        self.setObjectName("history_dock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.canvas = canvas
        self._signature = None
        self._target = None
        self._seek_identity = None
        self._seek_budget = 0
        self._canvas_was_enabled = True

        root = QWidget()
        root.setObjectName("dockContent")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(7)
        self.summary = QLabel("Aucune modification")
        self.summary.setObjectName("mutedLabel")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setObjectName("historyTimeline")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setMinimumHeight(100)
        self.list.setItemDelegate(HistoryDelegate(self.list))
        self.list.setAccessibleName("Étapes de l’historique")
        self.list.setToolTip("Cliquer une étape restaure cet état. Les flèches puis Entrée permettent aussi de naviguer.")
        self.list.itemClicked.connect(self._activate_item)
        self.list.itemActivated.connect(self._activate_item)
        layout.addWidget(self.list, 1)
        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.undo_button = QPushButton("↶  Annuler")
        self.redo_button = QPushButton("↷  Rétablir")
        self.undo_button.setToolTip("Annuler la dernière modification · Ctrl+Z")
        self.redo_button.setToolTip("Rétablir la modification suivante · Ctrl+Maj+Z")
        self.undo_button.clicked.connect(lambda: self.seek(self.canvas.tile_history.index - 1))
        self.redo_button.clicked.connect(lambda: self.seek(self.canvas.tile_history.index + 1))
        controls.addWidget(self.undo_button)
        controls.addWidget(self.redo_button)
        layout.addLayout(controls)
        # Snapshots: saved states you can come back to at any time.
        snapshot_row = QHBoxLayout()
        snapshot_title = QLabel("Instantanés")
        snapshot_title.setObjectName("fieldCaption")
        self.snapshot_button = QPushButton("+  Instantané")
        self.snapshot_button.setToolTip("Mémoriser l'état actuel de tous les calques")
        self.snapshot_button.clicked.connect(self._create_snapshot)
        snapshot_row.addWidget(snapshot_title)
        snapshot_row.addStretch()
        snapshot_row.addWidget(self.snapshot_button)
        layout.addLayout(snapshot_row)
        self.snapshot_list = QListWidget()
        self.snapshot_list.setObjectName("historyTimeline")
        self.snapshot_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.snapshot_list.setMaximumHeight(110)
        self.snapshot_list.setToolTip("Double-clic : revenir à cet instantané (annulable) · clic droit : supprimer")
        self.snapshot_list.itemDoubleClicked.connect(self._restore_snapshot)
        self.snapshot_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.snapshot_list.customContextMenuRequested.connect(self._snapshot_menu)
        layout.addWidget(self.snapshot_list)
        self.hint = QLabel("Cliquez une étape pour retrouver cet état.")
        self.hint.setObjectName("mutedLabel")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.setWidget(root)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._seek_tick)
        # The memory manager may discard or swap steps outside canvas signals.
        # This reads metadata only, runs only while visible, and never repaints
        # unchanged rows or accesses native tile payloads.
        self._retention_timer = QTimer(self)
        self._retention_timer.setInterval(1000)
        self._retention_timer.timeout.connect(self.refresh)
        self.visibilityChanged.connect(self._visibility_changed)
        signal = getattr(canvas, "history_changed", None)
        if signal is not None:
            signal.connect(self.schedule_refresh)
        else:
            canvas.history_restored.connect(self.schedule_refresh)
        self.refresh()

    def _refresh_snapshots(self) -> None:
        snapshots = self.canvas.document_snapshots() if hasattr(self.canvas, "document_snapshots") else []
        self.snapshot_list.clear()
        for snapshot in snapshots:
            item = QListWidgetItem(f"{snapshot['name']}   ·   {snapshot['time']}")
            item.setData(Qt.ItemDataRole.UserRole, id(snapshot))
            self.snapshot_list.addItem(item)
        self.snapshot_list.setVisible(bool(snapshots))
        self.snapshot_button.setEnabled(getattr(self.canvas, "document", None) is not None)

    def _snapshot_for(self, item):
        key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return next((s for s in self.canvas.document_snapshots() if id(s) == key), None)

    def _create_snapshot(self) -> None:
        if self.canvas.create_snapshot() is not None:
            self._refresh_snapshots()

    def _restore_snapshot(self, item) -> None:
        snapshot = self._snapshot_for(item)
        if snapshot is not None:
            self.canvas.restore_snapshot(snapshot)

    def _snapshot_menu(self, position) -> None:
        item = self.snapshot_list.itemAt(position)
        snapshot = self._snapshot_for(item)
        if snapshot is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Revenir à cet instantané", lambda: self.canvas.restore_snapshot(snapshot))
        menu.addAction("Supprimer", lambda: (self.canvas.delete_snapshot(snapshot), self._refresh_snapshots()))
        menu.exec(self.snapshot_list.mapToGlobal(position))

    def _visibility_changed(self, visible):
        if visible:
            self._retention_timer.start()
            self.refresh()
        else:
            self._retention_timer.stop()

    def schedule_refresh(self):
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    def _identity(self):
        history = self.canvas.tile_history
        return id(self.canvas.document), id(history), tuple(id(step) for step in history.steps)

    def _editing(self):
        return (self.canvas.tile_history._pending is not None
                or getattr(self.canvas, "free_transform", None) is not None
                or bool(getattr(self.canvas, "_deferred_undo_count", 0)))

    def refresh(self):
        if hasattr(self, "snapshot_list"):
            self._refresh_snapshots()
        history = self.canvas.tile_history
        index = history.index
        identity = self._identity()
        signature = (identity, index)
        if signature != self._signature:
            changed_branch = self._signature is None or identity != self._signature[0]
            if changed_branch:
                self.list.clear()
                start = QListWidgetItem("État initial conservé")
                start.setData(DETAIL_ROLE, "Début de l’historique disponible")
                start.setToolTip("Le premier état encore disponible dans la limite d’annulation configurée.")
                self.list.addItem(start)
                for step in history.steps:
                    label = getattr(step, "label", "") or "Modification du document"
                    detail = getattr(step, "detail", "")
                    item = QListWidgetItem(label)
                    item.setData(DETAIL_ROLE, detail)
                    item.setToolTip(label + ("\n" + detail if detail else ""))
                    self.list.addItem(item)
            for row in range(self.list.count()):
                self.list.item(row).setData(STATE_ROLE, "current" if row == index else "future" if row > index else "past")
            self.list.setCurrentRow(index)
            self.list.scrollToItem(self.list.currentItem(), QAbstractItemView.ScrollHint.EnsureVisible)
            self._signature = signature
        count = len(history.steps)
        self.summary.setText(f"{index} / {count} étapes appliquées" if count else "Votre prochaine modification apparaîtra ici")
        seeking = self._target is not None
        editing = self._editing()
        self.list.setEnabled(not (editing or seeking))
        self.undo_button.setEnabled(not (editing or seeking) and index > 0)
        self.redo_button.setEnabled(not (editing or seeking) and index < count)
        if seeking:
            self.hint.setText(f"Restauration de l’étape {self._target}…")
        elif editing:
            self.hint.setText("Terminez le geste en cours pour parcourir l’historique.")
        elif index < count:
            self.hint.setText("Une nouvelle modification remplacera les étapes suivantes.")
        else:
            self.hint.setText("Cliquez une étape pour retrouver cet état.")

    def _activate_item(self, item):
        self.seek(self.list.row(item))

    def seek(self, target: int) -> bool:
        history = self.canvas.tile_history
        if self._target is not None or self._editing() or not 0 <= target <= len(history.steps):
            self.refresh()
            return False
        if target == history.index:
            return True
        self._target = target
        self._seek_identity = self._identity()
        self._seek_budget = abs(target - history.index)
        self._canvas_was_enabled = self.canvas.isEnabled()
        self.canvas.setEnabled(False)
        self.refresh()
        self._seek_timer.start(0)
        return True

    def _seek_tick(self):
        if self._target is None:
            return
        history = self.canvas.tile_history
        if self._identity() != self._seek_identity or self._editing():
            self._finish_seek()
            return
        previous = history.index
        if previous == self._target or self._seek_budget <= 0:
            self._finish_seek()
            return
        direction = -1 if self._target < previous else 1
        self._seek_budget -= 1
        try:
            (self.canvas.undo if direction < 0 else self.canvas.redo)()
        except Exception as error:
            self._finish_seek()
            self.hint.setText("Cette étape n’a pas pu être restaurée.")
            self.hint.setToolTip(str(error))
            return
        if history.index != previous + direction or history.index == self._target:
            self._finish_seek()
        else:
            self.refresh()
            self._seek_timer.start(0)

    def _finish_seek(self):
        self._seek_timer.stop()
        self._target = None
        self._seek_identity = None
        self.canvas.setEnabled(self._canvas_was_enabled)
        self.refresh()


__all__ = ["HistoryDock"]
