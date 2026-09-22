from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QImage


@dataclass
class ReferenceImage:
    image: QImage
    position: QPointF = field(default_factory=QPointF)
    scale: float = 1.0
    opacity: float = 0.8
    id: str = field(default_factory=lambda: str(uuid4()))

    def copy(self) -> "ReferenceImage":
        return ReferenceImage(QImage(self.image), QPointF(self.position),
                              self.scale, self.opacity, self.id)


@dataclass
class EditableText:
    text: str
    position: QPointF
    color: QColor = field(default_factory=lambda: QColor(0, 0, 0, 255))
    font: QFont = field(default_factory=lambda: QFont("Sans Serif", 24))
    id: str = field(default_factory=lambda: str(uuid4()))

    def copy(self) -> "EditableText":
        return EditableText(self.text, QPointF(self.position), QColor(self.color),
                            QFont(self.font), self.id)
