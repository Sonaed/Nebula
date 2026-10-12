"""Pixel oracles for the recovered large-canvas editor optimisations."""
import os
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtCore import QPoint,QPointF,QRect,QSize,Qt,QEvent
from PySide6.QtGui import QColor,QImage,QMouseEvent,QKeyEvent
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from CANVAS.tile_history import TileHistory,NativeTileDeltaMap
from CORE.native_bridge import native_selection_bounds,crop_image_native,fill_image_rect_native
from DOCUMENTS.document import Document
from DOCUMENTS.selection import SelectionMask,SelectionOperation,_native_filters
from TOOLS.selection_tools import SelectionTools,antialias_mask


def alpha(image):
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(rgba.constBits(),np.uint8).reshape(rgba.height(),rgba.bytesPerLine())[:,3:rgba.width()*4:4].copy()


class EditorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_region_shapes_equal_full_canvas_for_every_operation(self):
        size=QSize(151,117)
        for tool in SelectionTools.SHAPE_TOOLS:
            for radius in (0,3):
                for op in SelectionOperation:
                    with self.subTest(tool=tool,radius=radius,operation=op):
                        a,b=SelectionMask(151,117),SelectionMask(151,117)
                        a.select_all();b.select_all()
                        points=[QPointF(-7,13),QPointF(98,90)] if tool!='lasso' else [QPointF(-7,13),QPointF(98,20),QPointF(40,90)]
                        a.combine(SelectionTools.shape_mask(tool,size,points,feather=radius),op)
                        region,origin=SelectionTools.shape_region(tool,size,points,feather=radius)
                        b.combine_region(region,origin,op)
                        np.testing.assert_array_equal(alpha(a.image),alpha(b.image))

    def test_region_filters_equal_full_native_filters_at_edges(self):
        for origin in (QPoint(0,0),QPoint(31,29),QPoint(90,70)):
            for operation in ('feather','expand','contract'):
                with self.subTest(origin=origin,operation=operation):
                    mask=SelectionMask(128,96)
                    image=QImage(128,96,QImage.Format.Format_ARGB32);image.fill(0)
                    fill_image_rect_native(image,QRect(origin,QSize(30,25)),QColor(255,255,255,190))
                    mask.combine(image,SelectionOperation.REPLACE)
                    expected=mask.image.copy()
                    if operation=='feather':_native_filters().selection_feather(expected.bits(),128,96,7,stride=expected.bytesPerLine())
                    else:_native_filters().selection_morph(expected.bits(),128,96,7,operation=='expand',stride=expected.bytesPerLine())
                    getattr(mask,operation)(7)
                    np.testing.assert_array_equal(alpha(mask.image),alpha(expected))

    def test_antialias_retains_original_rounding(self):
        rng=np.random.default_rng(27)
        image=QImage(71,59,QImage.Format.Format_ARGB32);image.fill(0)
        for y in range(59):
            for x in range(71):image.setPixelColor(x,y,QColor(255,255,255,int(rng.integers(0,256))))
        hard=(alpha(image)>=128).astype(np.float32);padded=np.pad(hard,1,mode='edge')
        box=sum(padded[y:y+59,x:x+71] for y in range(3) for x in range(3))/9.0
        expected=np.clip(np.rint((.5*hard+.5*box)*255),0,255).astype(np.uint8)
        antialias_mask(image)
        np.testing.assert_array_equal(alpha(image),expected)

    def test_read_only_native_queries_do_not_detach_layer_pixels(self):
        image=QImage(64,64,QImage.Format.Format_ARGB32);image.fill(QColor('white'))
        shared=QImage(image);key=image.cacheKey()
        self.assertEqual(native_selection_bounds(image),(0,0,64,64))
        self.assertFalse(crop_image_native(image,QRect(4,4,16,16)).isNull())
        self.assertEqual(image.cacheKey(),key)
        self.assertEqual(shared.cacheKey(),key)

    def test_paint_undo_does_not_decode_payload_or_allocate_selection(self):
        doc=Document(128,96,72,None);history=TileHistory();layer=doc.layers[0]
        history.begin(doc,dirty_only=True)
        history.capture_before(layer,QRect(0,0,16,16))
        fill_image_rect_native(layer.image,QRect(0,0,16,16),QColor('red'))
        layer.commit_image_cache(QRect(0,0,16,16));history.commit(doc)
        with patch.object(NativeTileDeltaMap,'__getitem__',side_effect=AssertionError('Paint payload decoded in Python')):
            self.assertTrue(history.undo(doc));self.assertTrue(history.redo(doc))
        self.assertIsNone(doc.selection._image)

    def test_selection_clipping_interpolates_eraser_and_transparent_paint(self):
        c=Canvas();c.create_new_image(16,16)
        try:
            for coverage in (0,64,128,255):
                for after_alpha in (0,70,255):
                    mask=QImage(16,16,QImage.Format.Format_ARGB32);mask.fill(QColor(255,255,255,coverage))
                    # Keep the selection globally non-empty even for the zero sample.
                    mask.setPixelColor(0,0,QColor('white'))
                    c.document.selection.combine(mask,SelectionOperation.REPLACE)
                    before=QImage(16,16,QImage.Format.Format_ARGB32_Premultiplied);before.fill(QColor(20,60,90,180))
                    after=QImage(16,16,QImage.Format.Format_ARGB32_Premultiplied);after.fill(QColor(230,40,60,after_alpha))
                    c._restore_selection_after_edit(after,before,QRect(0,0,16,16))
                    expected=round(180*(1-coverage/255)+after_alpha*coverage/255)
                    self.assertLessEqual(abs(after.pixelColor(8,8).alpha()-expected),1)
        finally:c.close()

    def test_gradient_coalesces_and_cancel_discards_pending_preview(self):
        c=Canvas();c.create_new_image(64,48);c.tools.set_gradient();c.use_gpu=False
        try:
            before=c.get_active_layer().image.copy()
            c._begin_gradient(QPoint(2,2))
            with patch.object(c.tools,'gradient',wraps=c.tools.gradient) as gradient:
                c._queue_gradient(QPoint(20,20))
                for x in range(21,45):c._queue_gradient(QPoint(x,20))
                self.assertEqual(gradient.call_count,1)
                c._finish_gradient(QPoint(50,25))
                self.assertEqual(gradient.call_count,2)
                self.assertEqual(gradient.call_args.args[2],QPoint(50,25))
            result=c.get_active_layer().image.copy();c.undo()
            self.assertEqual(c.get_active_layer().image,before)
            c.redo();self.assertEqual(c.get_active_layer().image,result)
            c._begin_gradient(QPoint(4,4));c._queue_gradient(QPoint(30,10));c._queue_gradient(QPoint(40,10))
            c._cancel_gradient();self.app.processEvents()
            self.assertEqual(c.get_active_layer().image,result)
            self.assertFalse(c._gradient_timer.isActive())
        finally:c.close()


if __name__=='__main__':unittest.main()
