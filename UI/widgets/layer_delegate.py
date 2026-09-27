from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from UI.theme.palette import COLORS


CLIP_INDENT = 16


class LayerItemDelegate(QStyledItemDelegate):
    """Compact painted layer row independent from the platform widget style."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 46)

    @staticmethod
    def _paint_clip_arrow(painter: QPainter, left: int, rect: QRect) -> None:
        """Flèche coudée vers le bas : ce calque est écrêté sur celui du dessous."""
        painter.save()
        painter.setPen(QPen(QColor(COLORS["accent"]), 1.5))
        x = left + 3
        y = rect.center().y()
        painter.drawLine(x, y - 9, x, y + 3)
        painter.drawLine(x, y + 3, x + 8, y + 3)
        painter.drawLine(x + 8, y + 3, x + 5, y)
        painter.drawLine(x + 8, y + 3, x + 5, y + 6)
        painter.restore()

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        rect = option.rect.adjusted(2, 1, -2, -1)
        folder = index.data(Qt.ItemDataRole.UserRole + 5)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["layer_selected"]) if selected else QColor(COLORS["layer_hover"]) if hovered else QColor(COLORS["layer_surface"]))
        painter.drawRoundedRect(rect, 4, 4)
        if isinstance(folder, dict):
            depth = int(folder.get("depth", 0))
            visible = folder.get("visible", True)
            painter.setPen(QColor(COLORS["text_bright"] if visible else COLORS["text_disabled"]))
            painter.drawEllipse(rect.left() + 8, rect.center().y() - 6, 13, 13)
            painter.setPen(QColor(COLORS["text_bright"] if visible else COLORS["text_disabled"]))
            painter.drawText(QRect(rect.left() + 27 + depth * 16, rect.top(), 16, rect.height()), Qt.AlignmentFlag.AlignCenter,
                             "▸" if folder.get("collapsed") else "▾")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["folder"]) if visible else QColor(COLORS["text_disabled"]))
            painter.drawRoundedRect(QRect(rect.left() + 48 + depth * 16, rect.center().y() - 8, 18, 14), 2, 2)
            painter.setPen(QColor(COLORS["text_bright"] if visible else COLORS["text_disabled"]))
            painter.drawText(QRect(rect.left() + 74 + depth * 16, rect.top(), rect.width() - 79, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, str(index.data(Qt.ItemDataRole.DisplayRole)))
            painter.restore()
            return
        flags = index.data(Qt.ItemDataRole.UserRole + 2) or {}
        depth = int(flags.get("depth", 0))
        offset = depth * 16
        # Calque écrêté : la miniature est décalée vers la droite et une flèche pointe
        # vers le calque de base (comme Photoshop) ; l'œil reste dans sa colonne.
        clipping = bool(flags.get("clipping"))
        eye_offset = offset
        if clipping:
            offset += CLIP_INDENT
        visible = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        painter.setPen(QPen(QColor(COLORS["text_bright"] if visible else COLORS["text_disabled"]), 1.5))
        # Cible stylet : la pastille était à 7 px, sous le seuil utilisable.
        painter.drawEllipse(rect.left() + 8 + eye_offset, rect.center().y() - 6, 13, 13)
        if clipping:
            self._paint_clip_arrow(painter, rect.left() + 28 + eye_offset, rect)
        image = index.data(Qt.ItemDataRole.DecorationRole)
        thumb_rect = QRect(rect.left() + 28 + offset, rect.top() + 5, 36, 36)
        painter.fillRect(thumb_rect, QColor(COLORS["thumbnail_surface"]))
        if image is not None:
            painter.drawPixmap(thumb_rect, image)
        has_mask = bool(flags.get("has_mask"))
        text_left = rect.left() + 73 + offset
        if has_mask:
            # The mask is attached visually to its layer but remains a
            # separate target for direct editing.
            painter.setPen(QColor(COLORS["text_secondary"]))
            painter.drawText(QRect(thumb_rect.right() + 1, rect.top(), 8, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, "⛓")
            mask_rect = QRect(thumb_rect.right() + 10, rect.top() + 5, 36, 36)
            painter.fillRect(mask_rect, QColor(COLORS["text"]))
            mask = index.data(Qt.ItemDataRole.UserRole + 3)
            if mask is not None:
                painter.drawPixmap(mask_rect, mask)
            painter.setPen(QPen(QColor(COLORS["accent"]), 2) if flags.get("mask_selected")
                           else QPen(QColor(COLORS["text_secondary"]), 1))
            painter.drawRect(mask_rect)
            text_left = mask_rect.right() + 7
        painter.setPen(QColor(COLORS["text_bright"]))
        painter.drawText(QRect(text_left, rect.top() + 5, rect.right() - 45 - text_left, 22), Qt.AlignmentFlag.AlignVCenter, str(index.data(Qt.ItemDataRole.DisplayRole)))
        # Les verrous actifs sont peints à l'accent : en gris secondaire ils
        # étaient invisibles, première cause de « mon pinceau ne peint plus ».
        active_lock = bool(flags.get("lock_alpha") or flags.get("locked"))
        painter.setPen(QColor(COLORS["accent"] if active_lock else COLORS["text_secondary"]))
        indicators = ("α" if flags.get("lock_alpha") else "") + ("  ◈" if flags.get("locked") else "")
        painter.drawText(QRect(rect.right() - 42, rect.top(), 38, rect.height()), Qt.AlignmentFlag.AlignCenter, indicators)
        label_color = flags.get("label_color")
        if label_color:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(str(label_color)))
            painter.drawRoundedRect(QRect(rect.right() - 4, rect.top() + 5, 3, rect.height() - 10), 1, 1)
        painter.restore()


__all__ = ["LayerItemDelegate"]
