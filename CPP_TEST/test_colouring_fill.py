"""Paint bucket for colouring: reference image, gap closing, grow under lines."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from CORE.native_bridge import load_creative_core
from TOOLS.fill_tool import FillTool

APP = QApplication.instance() or QApplication([])
ORANGE = QColor(230, 120, 60)


def line_art(gap_degrees: int = 0) -> QImage:
    image = QImage(300, 300, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QPen(QColor(20, 20, 20), 4))
    if gap_degrees:
        painter.drawArc(50, 50, 200, 200, gap_degrees * 16, (360 - gap_degrees) * 16)
    else:
        painter.drawEllipse(50, 50, 200, 200)
    painter.end()
    return image


def empty_layer() -> QImage:
    image = QImage(300, 300, QImage.Format.Format_ARGB32)
    image.fill(0)
    return image


@unittest.skipIf(load_creative_core() is None, "CreativeCore non compilé")
class ColouringFillTests(unittest.TestCase):
    def setUp(self):
        self.tool = FillTool()
        self.tool.options.tolerance = 24

    def alpha(self, image, x, y):
        return QColor.fromRgba(image.pixel(x, y)).alpha()

    def test_fill_on_empty_layer_follows_the_line_art_of_another_layer(self):
        flats = empty_layer()
        self.tool.options.gap, self.tool.options.grow = 0, 0
        self.tool.set_reference(line_art())
        self.tool.fill(flats, QPoint(150, 150), ORANGE)
        self.assertEqual(self.alpha(flats, 150, 150), 255)
        self.assertEqual(self.alpha(flats, 10, 10), 0)            # outside the circle untouched

    def test_gap_closing_stops_the_leak(self):
        reference = line_art(gap_degrees=3)                      # ~5 px opening
        leaky, sealed = empty_layer(), empty_layer()
        self.tool.set_reference(reference)
        self.tool.options.gap, self.tool.options.grow = 0, 0
        self.tool.fill(leaky, QPoint(150, 150), ORANGE)
        self.assertEqual(self.alpha(leaky, 10, 10), 255)          # leaks without gap closing
        self.tool.options.gap = 5
        self.tool.fill(sealed, QPoint(150, 150), ORANGE)
        self.assertEqual(self.alpha(sealed, 10, 10), 0)           # sealed
        self.assertEqual(self.alpha(sealed, 150, 60), 255)        # but reaches the line edge

    def test_grow_pushes_colour_under_the_line(self):
        reference = line_art()
        tight, grown = empty_layer(), empty_layer()
        self.tool.set_reference(reference)
        self.tool.options.gap, self.tool.options.grow = 0, 0
        self.tool.fill(tight, QPoint(150, 150), ORANGE)
        self.tool.options.grow = 3
        self.tool.fill(grown, QPoint(150, 150), ORANGE)
        self.assertEqual(self.alpha(tight, 150, 50), 0)           # on the line: not filled
        self.assertEqual(self.alpha(grown, 150, 50), 255)         # grown under it

    def test_preview_bounds_do_not_modify_pixels(self):
        flats = empty_layer()
        self.tool.set_reference(line_art())
        bounds = self.tool.preview_bounds(flats, QPoint(150, 150))
        self.assertGreater(bounds.width(), 150)
        self.assertEqual(self.alpha(flats, 150, 150), 0)


class LassoFillTests(unittest.TestCase):
    def setUp(self):
        from CANVAS.canvas import Canvas
        from DOCUMENTS.document import Document
        self.canvas = Canvas()
        self.canvas.set_document(Document(200, 200, 72, None))
        self.canvas.set_brush_setting("color", (20, 140, 220, 255))

    def tearDown(self):
        self.canvas.close()

    def test_shape_is_filled_and_undoable(self):
        from PySide6.QtCore import QPointF
        square = [QPointF(40, 40), QPointF(160, 40), QPointF(160, 160), QPointF(40, 160)]
        self.canvas.apply_lasso_fill(square)
        layer = self.canvas.get_active_layer().image
        inside = QColor.fromRgba(layer.pixel(100, 100))
        self.assertEqual((inside.blue(), inside.alpha()), (220, 255))
        self.assertEqual(QColor.fromRgba(layer.pixel(10, 10)).alpha(), 0)
        self.canvas.undo()
        self.assertEqual(QColor.fromRgba(self.canvas.get_active_layer().image.pixel(100, 100)).alpha(), 0)

    def test_fill_is_clipped_to_the_selection(self):
        from PySide6.QtCore import QPointF
        from DOCUMENTS.selection import SelectionOperation
        from TOOLS.selection_tools import SelectionTools
        selection = self.canvas.document.selection
        mask = SelectionTools.shape_mask("select_rectangle", selection.image.size(),
                                         [QPointF(0, 0), QPointF(100, 200)])
        selection.combine(mask, SelectionOperation.REPLACE)
        square = [QPointF(40, 40), QPointF(160, 40), QPointF(160, 160), QPointF(40, 160)]
        self.canvas.apply_lasso_fill(square)
        layer = self.canvas.get_active_layer().image
        self.assertEqual(QColor.fromRgba(layer.pixel(60, 100)).alpha(), 255)
        self.assertEqual(QColor.fromRgba(layer.pixel(140, 100)).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
