"""Reproducible CPU editor latency; no GPU/FPS or hardware stylus claims."""
from __future__ import annotations
import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.selection import SelectionOperation
from TOOLS.selection_tools import SelectionTools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--width', type=int, default=8000)
    parser.add_argument('--height', type=int, default=6000)
    parser.add_argument('--layers', type=int, default=12)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    c = Canvas(); c.resize(1600, 1000)
    c.set_document(Document(args.width, args.height, 72, None))
    c.use_gpu = False; c.zoom = .2; c.offset = QPointF()
    c.tools.set_brush(); c.brush_settings.update({'size': 48, 'stabilization': 0, 'pressureSize': False})
    manager = LayerManager(c.document)
    for i in range(args.layers-1): manager.add_layer(f'Layer {i}')
    for i, layer in enumerate(c.document.layers):
        patch = QImage(min(3000,args.width), min(4600,args.height), QImage.Format.Format_ARGB32)
        patch.fill(QColor((20*i)%256,90,max(0,200-10*i),255))
        layer.tile_store.write_image_at(patch,(i*400)%max(1,args.width-3000),min(300,args.height//10))
        layer.discard_image_cache()
    del patch
    c._reset_history()
    results = {}

    def timed(fn):
        start=time.perf_counter(); fn(); return (time.perf_counter()-start)*1000

    def event(kind,x,y):
        e=QMouseEvent(kind,QPointF(x,y),QPointF(x,y),
            Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress:c.mousePressEvent,QEvent.Type.MouseMove:c.mouseMoveEvent,
         QEvent.Type.MouseButtonRelease:c.mouseReleaseEvent}[kind](e)

    def stroke():
        event(QEvent.Type.MouseButtonPress,100,100)
        moves=[timed(lambda k=k:event(QEvent.Type.MouseMove,100+k*9,100+(k%20)*6)) for k in range(1,120)]
        release=timed(lambda:event(QEvent.Type.MouseButtonRelease,1171,160))
        undo=timed(c.undo); redo=timed(c.redo)
        return [statistics.median(moves),sorted(moves)[int(len(moves)*.95)],release,undo,redo]
    stroke()  # warm-up
    for label, values in zip(('move_median','move_p95','stroke_release','stroke_undo','stroke_redo'),zip(*(stroke() for _ in range(args.repeats)))):
        results[label]=round(statistics.median(values),3)
    c._reset_history()
    sel=c.document.selection; size=QSize(args.width,args.height)

    def action(label,operation):
        samples=[]
        for _ in range(args.repeats):
            elapsed=timed(operation)
            undo=timed(c.undo); redo=timed(c.redo)
            samples.append((elapsed,undo,redo))
            c.undo()  # each repetition starts from the same state
        c.redo()
        results[label]={k:round(statistics.median(v),3) for k,v in zip(('edit','undo','redo'),zip(*samples))}
        print(label,results[label],flush=True)

    def shape(tool,points,operation):
        def edit():
            # Exercise the public fast path when available, same semantic operation.
            if hasattr(SelectionTools,'shape_region') and hasattr(sel,'combine_region'):
                mask,origin=SelectionTools.shape_region(tool,size,points)
                sel.combine_region(mask,origin,operation)
            else:sel.combine(SelectionTools.shape_mask(tool,size,points),operation)
        return lambda:c.apply_selection_edit(edit)
    action('rectangle',shape('select_rectangle',[QPoint(500,500),QPoint(3500,2500)],SelectionOperation.REPLACE))
    action('lasso',shape('lasso',[QPoint(1000,1000),QPoint(4000,1200),QPoint(3000,4000),QPoint(800,3000)],SelectionOperation.ADD))
    action('feather_20',lambda:c.apply_selection_edit(lambda:sel.feather(20)))
    action('invert',lambda:c.apply_selection_edit(sel.invert))
    action('select_all',lambda:c.apply_selection_edit(sel.select_all))
    action('deselect',lambda:c.apply_selection_edit(sel.clear))
    c.tools.selection_tools.options.sample_all_layers=False
    action('magic_wand',lambda:c.select_magic_wand_at(QPointF(500,400),Qt.KeyboardModifier.NoModifier))
    c.tools.selection_tools.options.sample_all_layers=True
    action('magic_wand_merged',lambda:c.select_magic_wand_at(QPointF(500,400),Qt.KeyboardModifier.NoModifier))
    results['outline']=round(timed(sel.outline_segments),3)
    sel.clear(); c._reset_history()
    def structure(op,capture=()):
        c.begin_history_action(structure_only=True)
        keys=set().union(*(layer.tile_store.occupied_keys for layer in capture))
        for layer in capture:c.tile_history.capture_layer_before(layer,keys)
        op(); c.commit_history_action()
    action('add_layer',lambda:structure(lambda:manager.add_layer('new')))
    action('duplicate_layer',lambda:structure(lambda:manager.duplicate_layer(3)))
    action('move_layer',lambda:structure(lambda:manager.move_layer_up(3)))
    action('merge_down',lambda:structure(lambda:manager.merge_down(3),c.document.layers[2:4]))
    report={'fixture':vars(args)|{'output':str(args.output)},'platform':platform.platform(),
            'python':platform.python_version(),'backend':'CPU Qt offscreen; timings in ms',
            'results_ms':results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    c.close()


if __name__=='__main__':main()
