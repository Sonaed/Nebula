from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle


class LayerItemDelegate(QStyledItemDelegate):
    """Compact painted layer row independent from the platform widget style."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 46)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        rect = option.rect.adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#354552") if selected else QColor("#28292D") if hovered else QColor("#222326"))
        painter.drawRoundedRect(rect, 4, 4)
        visible = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        painter.setPen(QPen(QColor("#E4E4E4") if visible else QColor("#686868"), 1.5))
        painter.drawEllipse(rect.left() + 10, rect.center().y() - 3, 7, 7)
        image = index.data(Qt.ItemDataRole.DecorationRole)
        thumb_rect = QRect(rect.left() + 28, rect.top() + 5, 36, 36)
        painter.fillRect(thumb_rect, QColor("#18191B"))
        if image is not None:
            painter.drawImage(thumb_rect, image)
        painter.setPen(QColor("#E4E4E4"))
        painter.drawText(QRect(rect.left() + 73, rect.top() + 5, rect.width() - 112, 22), Qt.AlignmentFlag.AlignVCenter, str(index.data(Qt.ItemDataRole.DisplayRole)))
        flags = index.data(Qt.ItemDataRole.UserRole + 2) or {}
        painter.setPen(QColor("#A5A5A5"))
        indicators = ("α" if flags.get("lock_alpha") else "") + ("  ◈" if flags.get("locked") else "") + ("  ↳" if flags.get("clipping") else "")
        painter.drawText(QRect(rect.right() - 42, rect.top(), 38, rect.height()), Qt.AlignmentFlag.AlignCenter, indicators)
        painter.restore()


__all__ = ["LayerItemDelegate"]
