"""Read-only real-PSD import, thumbnail and CPU viewport qualification.

No save/export is performed. --fingerprints verifies every imported tile, which
adds a separate full pixel traversal excluded from the import timing.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from DOCUMENTS.format_psd import PSDFormat
from CANVAS.canvas import Canvas
from UI.docks.layers_dock import LayersDock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fingerprints', action='store_true')
    parser.add_argument('--visibility', action='store_true', help='Measure immediate feedback separately from exact recomposition')
    parser.add_argument('--profile-visibility', type=Path)
    parser.add_argument('--layer-name', help='Exact name of a visible layer to toggle')
    parser.add_argument('--visibility-cycles', type=int, default=2)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    result = {'source': str(args.source.resolve()), 'scope': 'CPU offscreen; no GPU frame-rate claim'}
    def timed(name, operation):
        start = time.perf_counter(); value = operation()
        result[name] = round(time.perf_counter()-start, 4)
        print(name, result[name], flush=True)
        return value
    document = timed('import_seconds', lambda: PSDFormat._load_native(args.source))
    result['report'] = document.psd_import_report
    if args.fingerprints:
        def fingerprints():
            records = []
            for layer in document.layers:
                digest = hashlib.sha256()
                for tx, ty in sorted(layer.tile_store.occupied_keys):
                    image = layer.tile_store.tile(tx, ty)
                    digest.update(struct.pack('>II', tx, ty)); digest.update(image.constBits())
                records.append({'name': layer.name, 'visible': layer.visible,
                                'opacity': layer.opacity, 'blend': layer.blend_mode,
                                'hash': digest.hexdigest()})
            return records
        result['layers'] = timed('fingerprint_seconds', fingerprints)
    timed('thumbnail_seconds', lambda: [LayersDock._tile_thumbnail(l.tile_store) for l in document.layers])
    canvas = Canvas(); canvas.resize(1200, 800); canvas.use_gpu = False
    try:
        timed('set_document_seconds', lambda: canvas.set_document(document))
        def wait_for_view():
            start = time.perf_counter()
            canvas._ensure_projection()
            while time.perf_counter()-start < 30:
                app.processEvents()
                # A hidden headless Canvas gets no paint events: explicitly
                # continue its time-budgeted scan, just as paintEvent does.
                canvas._ensure_projection()
                if canvas._projection_display_ready and not canvas._projection_waiting_visible:
                    return True
                time.sleep(.005)
            return False
        result['fit_ready'] = timed('fit_seconds', wait_for_view)
        if args.visibility:
            candidates = (layer for layer in reversed(document.layers)
                          if layer.visible and layer.opacity > 0 and layer.tile_store.occupied_keys)
            layer = next(layer for layer in candidates
                         if args.layer_name is None or layer.name == args.layer_name)
            result['visibility_layer'] = layer.name
            result['visibility'] = []
            preview_hashes = []
            for shown in (False, True) * max(1, args.visibility_cycles):
                start = time.perf_counter()
                layer.visible = shown
                document.sync_native_state()
                canvas.invalidate_projection_for_layers([layer])
                dispatch = time.perf_counter() - start
                preview = getattr(document, '_display_preview', None)
                has_preview = preview is not None and not preview.isNull()
                preview_hash = hashlib.sha256(preview.constBits()).hexdigest() if has_preview else None
                preview_hashes.append(preview_hash)
                profile = None
                if args.profile_visibility and not result['visibility']:
                    import cProfile
                    profile = cProfile.Profile(); profile.enable()
                start = time.perf_counter()
                canvas._ensure_projection()
                first_slice = time.perf_counter() - start
                ready = wait_for_view()
                exact = time.perf_counter() - start
                if profile is not None:
                    import pstats
                    profile.disable()
                    args.profile_visibility.parent.mkdir(parents=True, exist_ok=True)
                    with args.profile_visibility.open('w') as stream:
                        pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(55)
                item = {'visible': shown, 'dispatch_seconds': round(dispatch, 4),
                        'preview_available': has_preview, 'preview_hash': preview_hash,
                        'first_projection_slice_seconds': round(first_slice, 4),
                        'profiled': profile is not None,
                        'exact_seconds': round(exact, 4), 'exact_ready': ready,
                        'preview_retired': not hasattr(document, '_display_preview')}
                result['visibility'].append(item)
                print('visibility', item, flush=True)
            result['visibility_feedback_changes'] = (all(preview_hashes)
                and preview_hashes[0] != preview_hashes[1]
                and all(value == preview_hashes[index % 2] for index, value in enumerate(preview_hashes)))
        canvas.zoom = 1.0; canvas.offset = QPointF(-document.width/3, -document.height/3)
        result['zoom_ready'] = timed('zoom_seconds', wait_for_view)
        canvas.offset += QPointF(-300, -180)
        result['pan_ready'] = timed('pan_seconds', wait_for_view)
        timed('idle_seconds', canvas._ensure_projection)
        result['performance'] = canvas.performance_stats_snapshot()
    finally:
        canvas.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    if args.visibility and not all(item['exact_ready'] and item['preview_retired']
                                   for item in result['visibility']):
        raise SystemExit('Visibility projection did not finish cleanly; see report')
    if args.visibility and not result['visibility_feedback_changes']:
        raise SystemExit('No visible pixel change; choose a non-occluded layer for this PSD')
    if not all(result[name] for name in ('fit_ready', 'zoom_ready', 'pan_ready')):
        raise SystemExit('Projection timeout; see report')


if __name__ == '__main__':
    main()
