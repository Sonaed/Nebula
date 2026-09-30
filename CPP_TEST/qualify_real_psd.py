"""Bounded, read-only qualification of a real PSD supplied by a user."""
from __future__ import annotations
import argparse, gc, json, os, sys, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.psd_import import build_overview, decode_composite_tiles
from DOCUMENTS.psd_reader import read_psd

def rss_mib():
    return round(int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)

def timed(result, key, func):
    start = time.perf_counter(); value = func(); result[key + "_seconds"] = round(time.perf_counter() - start, 3); return value

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("source", type=Path); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    source = args.source.resolve(); result = {"source": str(source), "source_bytes": source.stat().st_size, "rss_before_mib": rss_mib()}
    with read_psd(source, composite=False, lazy_layers=True) as metadata:
        result.update({"width": metadata.width, "height": metadata.height, "metadata_layers": len(metadata.layers)})
    preview, size = timed(result, "preview", lambda: build_overview(source)); result["preview_source_size"] = size; result["preview_bytes"] = len(preview)
    size, tiles = timed(result, "first_visible_tiles", lambda: decode_composite_tiles(source, (0, 0, 900, 600), 64)); result["first_visible_tile_count"] = len(tiles)
    _size, cold = timed(result, "cold_tiles", lambda: decode_composite_tiles(source, (max(0, size[0]-900), max(0, size[1]-600), 900, 600), 64)); result["cold_tile_count"] = len(cold)
    document = timed(result, "editable_import", lambda: PSDFormat._load_native(source))
    report = getattr(document, "psd_import_report", {}); result.update({"import_report": report, "import_warning": getattr(document, "psd_import_warning", ""), "resident_tile_bytes": sum(layer.tile_store.allocated_bytes() for layer in document.layers), "resident_tiles": sum(len(layer.tile_store.resident_keys()) for layer in document.layers), "rss_after_import_mib": rss_mib()})
    for layer in document.layers:
        layer.tile_store.close()
        if layer.alpha_mask_store: layer.alpha_mask_store.close()
    del document; gc.collect(); result["rss_after_close_pretrim_mib"] = rss_mib()
    from CORE.memory_manager import MemoryManager
    MemoryManager.trim_allocator()
    result["rss_after_close_mib"] = rss_mib(); result["result"] = "pass" if not result["import_warning"] else "pass_with_warnings"
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result, indent=2))

if __name__ == "__main__": main()
