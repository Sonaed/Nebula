"""Palette de commandes Nebula (Ctrl+K) et aide-mémoire des raccourcis (F1).

La palette parcourt la barre de menus au moment de l'ouverture : toute action
ajoutée plus tard (modules Existence, panneaux, espaces de travail) y apparaît
sans enregistrement supplémentaire.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout,
)


def collect_actions(window):
    """(chemin, action) de chaque action visible des menus, récursivement."""
    out = []

    def walk(menu, path):
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            text = action.text().replace("&", "").strip()
            if action.menu() is not None:
                walk(action.menu(), path + [text])
            elif text:
                out.append((path, text, action))
    for top in window.menuBar().actions():
        if top.menu() is not None and top.isVisible():
            walk(top.menu(), [top.text().replace("&", "")])
    return out


def _score(query: str, text: str) -> int:
    """Correspondance floue simple : sous-chaîne > initiales > lettres dans l'ordre."""
    q, t = query.casefold(), text.casefold()
    if not q:
        return 1
    if t.startswith(q):
        return 100
    if q in t:
        return 80 - t.index(q)
    words = [w for w in t.replace("/", " ").replace("›", " ").split() if w]
    if "".join(w[0] for w in words).startswith(q):
        return 60
    pos = 0
    for ch in q:
        pos = t.find(ch, pos)
        if pos < 0:
            return 0
        pos += 1
    return 20


class CommandPalette(QDialog):
    RECENT_KEY = "interface/recent_commands"

    def __init__(self, window):
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.window_ = window
        self.setObjectName("commandPalette")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("commandPaletteInput")
        self.edit.setPlaceholderText("Tape une commande, un outil, un panneau…  (Échap pour fermer)")
        self.list = QListWidget()
        self.list.setObjectName("commandPaletteList")
        self.list.setMinimumHeight(360)
        self.hint = QLabel("Entrée : exécuter · ↑↓ : naviguer · les commandes récentes apparaissent en premier")
        self.hint.setObjectName("mutedLabel")
        layout.addWidget(self.edit)
        layout.addWidget(self.list)
        layout.addWidget(self.hint)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _i: self._run_current())
        self.edit.installEventFilter(self)
        self.entries = []

    def open(self):
        self.entries = collect_actions(self.window_)
        self.edit.clear()
        self._filter("")
        geo = self.window_.geometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2, geo.top() + 90)
        self.show()
        self.raise_()
        self.edit.setFocus()

    def _recent(self):
        return list(QSettings("CreativeSystem", "CreativeSystem").value(self.RECENT_KEY, [], list) or [])

    def _remember(self, key):
        recent = [key] + [k for k in self._recent() if k != key]
        QSettings("CreativeSystem", "CreativeSystem").setValue(self.RECENT_KEY, recent[:8])

    def _filter(self, text):
        self.list.clear()
        recent = self._recent()
        scored = []
        for path, label, action in self.entries:
            full = " › ".join(path + [label])
            score = max(_score(text, label), _score(text, full) - 5)
            if score <= 0:
                continue
            if full in recent:
                score += 30 - recent.index(full) * 2
            scored.append((score, full, path, label, action))
        scored.sort(key=lambda s: (-s[0], s[1]))
        for _score_, full, path, label, action in scored[:60]:
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            state = "  ✓" if action.isCheckable() and action.isChecked() else ""
            text = f"{label}{state}      {' › '.join(path)}" + (f"   ·   {shortcut}" if shortcut else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setData(Qt.ItemDataRole.UserRole + 1, action)
            if not action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8, Qt.Key.Key_PageUp: -8}[key]
                row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
                self.list.setCurrentRow(row)
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _run_current(self):
        item = self.list.currentItem()
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        action = item.data(Qt.ItemDataRole.UserRole + 1)
        self._remember(item.data(Qt.ItemDataRole.UserRole))
        self.close()
        action.trigger()


class ShortcutSheet(QDialog):
    """Aide-mémoire généré depuis les vraies actions (toujours à jour)."""

    def __init__(self, window, extra_sections=()):
        super().__init__(window)
        self.setWindowTitle("Raccourcis et gestes")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        layout.addWidget(browser)
        groups = {}
        for path, label, action in collect_actions(window):
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if shortcut:
                groups.setdefault(path[0], []).append((label, shortcut))
        html = ["<style>td{padding:3px 14px 3px 0;} h3{margin:14px 0 4px;} kbd{font-weight:700;}</style>"]
        for title, rows in extra_sections:
            html.append(f"<h3>{title}</h3><table>")
            html += [f"<tr><td><kbd>{k}</kbd></td><td>{v}</td></tr>" for k, v in rows]
            html.append("</table>")
        for menu, rows in groups.items():
            html.append(f"<h3>{menu}</h3><table>")
            html += [f"<tr><td><kbd>{s}</kbd></td><td>{l}</td></tr>" for l, s in rows]
            html.append("</table>")
        browser.setHtml("".join(html))


class Separator(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.VLine)
        self.setObjectName("optionsSeparator")


__all__ = ["CommandPalette", "ShortcutSheet", "collect_actions"]
