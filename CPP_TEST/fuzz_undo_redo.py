"""Seeded editing stress test: every undo/redo is checked against saved pixels.

Run: python CPP_TEST/fuzz_undo_redo.py --seeds 24 --steps 80 --branch
Small canvases make complete pixel/mask comparisons feasible; 8K latency is
measured separately by benchmark_editor_actions.py.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint,QRect,QSize
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from CANVAS.tile_history import TileHistory
from CORE.native_bridge import fill_image_rect_native
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.selection import SelectionOperation
from TOOLS.selection_tools import SelectionTools


def digest(image,mask=False):
    if image is None:return None
    import numpy as np
    image=image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    raw=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())
    pixels=raw[:,3:image.width()*4:4] if mask else raw[:,:image.width()*4]
    return hashlib.sha256(pixels.tobytes()).hexdigest()


def state(document):
    return {'layers':[(l.id,l.name,l.visible,l.opacity,l.blend_mode,l.locked,l.lock_alpha,l.clipping,
                       digest(l.image),digest(l.alpha_mask_coverage(),True)) for l in document.layers],
            'groups':[(g.id,g.name,tuple(g.layer_ids),g.parent_id,g.visible,g.opacity,
                       g.blend_mode,g.mask_disabled,digest(g.alpha_mask_coverage(),True)) for g in document.layer_groups],
            'selection':digest(document.selection.image,True),
            'size':(document.width,document.height)}


def run(seed,steps=80,branch=False):
    app=QApplication.instance() or QApplication([])
    rng=random.Random(seed);c=Canvas();c.set_document(Document(128,96,72,None));c.use_gpu=False
    c.tile_history=TileHistory(max_steps=steps+10,max_snapshot_bytes=256*1024*1024)
    manager=LayerManager(c.document);states=[state(c.document)];names=[];index=0;trace=[]

    def check(label):
        actual=state(c.document)
        if actual!=states[index]:
            mismatched=[key for key in actual if actual[key]!=states[index][key]]
            print('EXPECTED',states[index], 'ACTUAL',actual,flush=True)
            raise AssertionError(f'seed={seed} {label} index={index}: {mismatched}; trace={trace}')

    try:
        for number in range(steps):
            draw=rng.random()
            if branch and draw<.22 and index:
                c.undo();index-=1;trace.append('undo');check('mid-sequence undo');continue
            if branch and draw<.30 and index<len(states)-1:
                c.redo();index+=1;trace.append('redo');check('mid-sequence redo');continue
            doc=c.document;sel=doc.selection
            choice=rng.choice(['paint','rect','lasso','wand','invert','feather','clear','add','duplicate',
                               'remove','merge','move','mask','group','ungroup','group_mask','opacity'])
            trace.append(choice)
            active=rng.randrange(len(doc.layers));doc.set_active_layer(active);layer=doc.layers[active]
            if choice in ('rect','lasso','wand','invert','feather','clear'):
                c.begin_selection_history_action()
                if choice in ('rect','lasso'):
                    points=[QPoint(rng.randrange(-10,65),rng.randrange(-10,50)),QPoint(rng.randrange(65,140),rng.randrange(50,105))]
                    if choice=='lasso':points.append(QPoint(20,rng.randrange(30,96)))
                    mask,origin=SelectionTools.shape_region('lasso' if choice=='lasso' else 'select_rectangle',QSize(128,96),points)
                    sel.combine_region(mask,origin,rng.choice(list(SelectionOperation)))
                elif choice=='wand':sel.combine(SelectionTools.magic_wand(layer.image,QPoint(32,32),anti_alias=True),SelectionOperation.REPLACE)
                elif choice=='invert':sel.invert()
                elif choice=='feather':sel.feather(rng.randrange(1,5))
                else:sel.clear()
            elif choice=='paint':
                c.begin_history_action(dirty_only=True)
                rect=QRect(rng.randrange(100),rng.randrange(65),24,26)
                c.tile_history.capture_before(layer,rect)
                fill_image_rect_native(layer.image,rect,QColor(rng.randrange(256),rng.randrange(256),rng.randrange(256),rng.randrange(1,256)))
                layer.commit_image_cache(rect)
            else:
                c.begin_history_action(structure_only=True)
                if choice=='add' and len(doc.layers)<9:manager.add_layer('new'+str(number))
                elif choice=='duplicate' and len(doc.layers)<9:manager.duplicate_layer(active)
                elif choice=='remove' and len(doc.layers)>1:
                    c.tile_history.capture_layer_before(layer);manager.remove_layer(active)
                elif choice=='merge' and active>0:
                    pair=doc.layers[active-1:active+1]
                    keys=pair[0].tile_store.occupied_keys | pair[1].tile_store.occupied_keys
                    for item in pair:c.tile_history.capture_layer_before(item,keys)
                    manager.merge_down(active)
                elif choice=='move':
                    (manager.move_layer_up if rng.randrange(2) else manager.move_layer_down)(active)
                elif choice=='mask':
                    layer.ensure_alpha_mask()
                    c.tile_history.capture_layer_before(layer,keys=layer.tile_store.keys_for_rect(QRect(0,0,64,64)))
                    image=QImage(64,64,QImage.Format.Format_ARGB32);image.fill(QColor(rng.randrange(256),rng.randrange(256),rng.randrange(256),255))
                    layer.alpha_mask_store.write_image_at(image,0,0)
                elif choice=='group':
                    roots=[g for g in doc.layer_groups if not g.parent_id]
                    if roots and rng.randrange(2):
                        target=rng.choice(roots);doc.group_layers([i for i,l in enumerate(doc.layers) if l.id in target.layer_ids],'parent')
                    else:doc.group_layers([active],'folder') if not doc.groups_containing(layer.id) else None
                elif choice=='ungroup' and doc.layer_groups:doc.ungroup_layers(rng.choice(doc.layer_groups).id)
                elif choice=='group_mask' and doc.layer_groups:
                    group=rng.choice(doc.layer_groups);store=group.ensure_alpha_mask(128,96)
                    c.tile_history.capture_group_mask_before(group,whole_grid=True)
                    image=QImage(64,64,QImage.Format.Format_ARGB32);image.fill(QColor(rng.randrange(256),50,80,255))
                    store.write_image_at(image,0,0);group.invalidate()
                elif choice=='opacity':layer.opacity=rng.choice([.2,.6,1]);doc.sync_native_state()
            changed=c.commit_history_action()
            if changed:
                states=states[:index+1]+[state(doc)];names=names[:index]+[choice];index+=1
            else:check('no-op '+choice)
        recorded=len(states)-1
        while index:
            c.undo();index-=1;check('undo '+names[index])
        while index<recorded:
            c.redo();index+=1;check('redo '+names[index-1])
        return {'seed':seed,'branch':branch,'actions':steps,'retained_steps':recorded,'status':'OK'}
    finally:c.close();c.deleteLater();app.processEvents()


def main():
    p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=12);p.add_argument('--start',type=int,default=1)
    p.add_argument('--steps',type=int,default=80);p.add_argument('--branch',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();results=[]
    for seed in range(args.start,args.start+args.seeds):
        result=run(seed,args.steps,args.branch);results.append(result);print(json.dumps(result),flush=True)
    if args.output:args.output.write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
