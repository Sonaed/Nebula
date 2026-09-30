"""8K/50-layer PSD -> editable Nebula -> reopen benchmark.

Defaults to full-canvas, translucent raster layers (all contribute). Use
--patch-size 512 for a sparse illustration workload. Timings exclude fixture
creation. CPU tile composition is measured separately from GUI/GPU latency.
"""
import argparse
import gc
import faulthandler
import json
import os
from pathlib import Path
import resource
import statistics
import struct
import sys
import tempfile
import time
import zlib
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.format_nebula import NebulaFormat
from DOCUMENTS.blend_modes import composite_document_layers


def current_rss_mib():
    try:
        return round(int(Path("/proc/self/statm").read_text().split()[1])
                     * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024, 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def fixture(path, size, count, patch):
    payloads = [b'\0\2' + zlib.compress(bytes([value]) * (patch * patch), 1)
                for value in (128, 31, 97, 211)]
    records = []
    for index in range(count):
        name = ('Layer %02d' % index).encode()
        name = bytes([len(name)]) + name
        name += b'\0' * (-len(name) % 4)
        extra = b'\0' * 8 + name
        record = struct.pack('>4iH', 0, 0, patch, patch, 4)
        record += b''.join(struct.pack('>hI', cid, len(payload))
                           for cid, payload in zip((-1, 0, 1, 2), payloads))
        record += b'8BIMnorm' + bytes((255, 0, 0, 0))
        record += struct.pack('>I', len(extra)) + extra
        records.append(record)
    info_size = 2 + sum(map(len, records)) + count * sum(map(len, payloads))
    padding = info_size % 2
    info_size += padding
    with path.open('wb') as stream:
        stream.write(b'8BPS' + struct.pack('>H', 1) + b'\0' * 6
                     + struct.pack('>HIIHH', 3, size, size, 8, 3) + b'\0' * 8)
        stream.write(struct.pack('>IIh', info_size + 8, info_size, count))
        for record in records:
            stream.write(record)
        for _ in records:
            for payload in payloads:
                stream.write(payload)
        stream.write(b'\0' * padding + b'\0' * 4)
        stream.write(b'\0\2' + zlib.compress(b"".join(bytes([v]) * (size * size) for v in (31, 97, 211)), 1))


def release(document):
    for layer in document.layers:
        layer.tile_store.close()
        if layer.alpha_mask_store:
            layer.alpha_mask_store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', type=int, default=8000)
    parser.add_argument('--layers', type=int, default=50)
    parser.add_argument('--patch-size', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--psd-export', action='store_true')
    parser.add_argument('--release-gate', action='store_true',
                        help='require the dense 8K/50-layer qualification fixture')
    args = parser.parse_args()
    faulthandler.dump_traceback_later(60, repeat=True)
    app = QApplication.instance() or QApplication([])
    patch = args.patch_size or args.size
    if args.release_gate and (args.size != 8000 or args.layers != 50 or patch != args.size):
        parser.error('--release-gate requires the dense default: 8000 px, 50 full layers')
    results = dict(size=args.size, layers=args.layers, painted_size=patch,
                   scope='PSD import, Nebula save/reopen, CPU 64px tile composition; excludes GUI/GPU')
    results['rss_before_mib'] = current_rss_mib()
    if args.release_gate:
        results['release_gate'] = 'dense_8k_50'
    def measure(name, operation):
        print("starting", name, flush=True)
        started = time.perf_counter()
        result = operation()
        results[name + '_seconds'] = round(time.perf_counter() - started, 4)
        print(name, results[name + '_seconds'], flush=True)
        return result
    with tempfile.TemporaryDirectory(prefix='nebula-8k-') as directory:
        psd = Path(directory) / 'input.psd'
        native = Path(directory) / 'output.nebula'
        fixture(psd, args.size, args.layers, patch)
        document = measure('psd_import', lambda: PSDFormat._load_native(psd))
        assert len(document.layers) == args.layers
        assert not document.psd_import_warning, document.psd_import_warning
        expected = QColor(31, 97, 211, 128)
        for layer in document.layers:
            assert layer.tile_store.tile(0, 0).pixelColor(0, 0) == expected
            assert layer._image_cache is None
        print('checking resident bytes', flush=True)
        results['resident_tile_bytes'] = sum(l.tile_store.allocated_bytes() for l in document.layers)
        results['resident_tiles'] = sum(len(l.tile_store.resident_keys()) for l in document.layers)
        results['scratch_tiles_before_release'] = sum(len(l.tile_store._swapped) for l in document.layers)
        print('compositing tiles', flush=True)
        durations = []
        for _ in range(21):
            start = time.perf_counter()
            image = composite_document_layers(document, QRect(0, 0, 64, 64))
            durations.append((time.perf_counter() - start) * 1000)
            assert not image.isNull()
        results['cpu_64px_tile_median_ms'] = round(statistics.median(durations[1:]), 3)
        if args.psd_export:
            exported = Path(directory) / 'exported.psd'
            assert measure('psd_export', lambda: PSDFormat.save(document, exported))
            from DOCUMENTS.psd_reader import read_psd
            with read_psd(exported, composite=False, lazy_layers=True) as check:
                assert len(check.layers) == args.layers
                for item in (check.layers[0], check.layers[-1]):
                    item.decode_pixels()
                    assert tuple(item.rgba[0, 0]) == (31, 97, 211, 128)
                    item.release_pixels()
            results['psd_file_bytes'] = exported.stat().st_size
        assert measure('nebula_save' , lambda: NebulaFormat.save(document, native))
        results['nebula_file_bytes'] = native.stat().st_size
        release(document)
        del document
        gc.collect()
        results['rss_after_close_mib'] = current_rss_mib()
        restored = measure('nebula_reopen', lambda: NebulaFormat.load(native))
        assert restored is not None and len(restored.layers) == args.layers
        for layer in restored.layers:
            assert layer.tile_store.tile(0, 0).pixelColor(0, 0) == expected
            edge = (patch - 1) // 64
            assert layer.tile_store.tile(edge, edge).pixelColor((patch-1) % 64, (patch-1) % 64) == expected
        release(restored)
        del restored
        gc.collect()
        results['rss_after_reopen_close_mib'] = current_rss_mib()
    results['peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    output = json.dumps(results, indent=2)
    print(output)
    if args.output:
        args.output.write_text(output + '\n')


if __name__ == '__main__':
    main()
