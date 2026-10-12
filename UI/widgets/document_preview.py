from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from UI.theme.palette import COLORS


class _CanvasPreview(QWidget):
    """Size-independent visual preview; never allocates document-sized pixels."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dimensions = (800, 600)
        self.background = "white"
        self.setMinimumSize(200, 220)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.dimensions
        scale = min((self.width()-48) / w, (self.height()-54) / h)
        rect = QRectF((self.width()-w*scale)/2, (self.height()-h*scale)/2-5, w*scale, h*scale)
        p.fillRect(rect.translated(4, 6), QColor(0, 0, 0, 70))
        if self.background == "transparent":
            p.save()
            p.setClipRect(rect)
            p.fillRect(rect, QColor(COLORS["checker_light"]))
            for y in range(int(rect.top()), int(rect.bottom())+1, 10):
                for x in range(int(rect.left()), int(rect.right())+1, 10):
                    if ((x-int(rect.left()))//10 + (y-int(rect.top()))//10) % 2:
                        p.fillRect(x, y, 10, 10, QColor(COLORS["checker_dark"]))
            p.restore()
        else:
            p.fillRect(rect, QColor(self.background))
        p.setPen(QPen(QColor(COLORS["accent"]), 1))
        p.drawRect(rect)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(0, rect.bottom()+12, self.width(), 20), Qt.AlignmentFlag.AlignCenter, f"{w:,} × {h:,} px".replace(',', ' '))
        p.end()
