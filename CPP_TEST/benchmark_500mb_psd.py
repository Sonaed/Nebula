"""Generate and measure an 8,000 px PSD near the 500 MB Priority-1 gate."""
from __future__ import annotations

import json
import os
import resource
import struct
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.psd_import import build_overview, decode_composite_tiles
from DOCUMENTS.psd_reader import read_psd


SIZE = 8000


def _random_channel(stream, bytes_count: int) -> None:
    remaining = bytes_count
    while remaining:
        chunk = os.urandom(min(4 * 1024 * 1024, remaining))
        stream.write(chunk)
        remaining -= len(chunk)


def fixture(path: Path) -> None:
    """One full RGBA layer + one RGBA composite: about 512 MB uncompressed."""
    plane = SIZE * SIZE
    name = b"\x05Large" + b"\0\0"
    extra = b"\0" * 8 + name
    channel_length = 2 + plane
    record = struct.pack(">4iH", 0, 0, SIZE, SIZE, 4)
    record += b"".join(struct.pack(">hI", channel, channel_length)
                       for channel in (0, 1, 2, -1))
    record += b"8BIMnorm" + bytes((255, 0, 0, 0)) + struct.pack(">I", len(extra)) + extra
    info_size = 2 + len(record) + 4 * channel_length
    if info_size % 2:
        info_size += 1
    with path.open("wb") as stream:
        stream.write(b"8BPS" + struct.pack(">H", 1) + b"\0" * 6)
        stream.write(struct.pack(">HIIHH", 4, SIZE, SIZE, 8, 3))
        stream.write(b"\0" * 8)  # colour data and image resources
        stream.write(struct.pack(">I", info_size + 8) + struct.pack(">Ih", info_size, 1))
        stream.write(record)
        for _channel in range(4):
            stream.write(struct.pack(">H", 0))
            _random_channel(stream, plane)
        if (2 + len(record) + 4 * channel_length) % 2:
            stream.write(b"\0")
        stream.write(b"\0" * 4)  # global mask
        stream.write(struct.pack(">H", 0))
        for _channel in range(4):
            _random_channel(stream, plane)


def main() -> None:
    result = {"size": SIZE, "scope": "headless decoder qualification; UI event-loop timing excluded"}
    with tempfile.TemporaryDirectory(prefix="nebula-500mb-") as directory:
        source = Path(directory) / "large.psd"
        started = time.perf_counter()
        fixture(source)
        result["fixture_bytes"] = source.stat().st_size
        result["fixture_seconds"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        with read_psd(source, composite=False, lazy_layers=True) as psd:
            result["metadata_seconds"] = round(time.perf_counter() - started, 3)
            result["metadata_layers"] = len(psd.layers)
        started = time.perf_counter()
        preview, preview_size = build_overview(source)
        result["preview_seconds"] = round(time.perf_counter() - started, 3)
        result["preview_bytes"] = len(preview)
        result["preview_source_size"] = preview_size
        started = time.perf_counter()
        _size, tiles = decode_composite_tiles(source, (0, 0, 512, 512), 64)
        result["visible_tiles_seconds"] = round(time.perf_counter() - started, 3)
        result["visible_tiles"] = len(tiles)
        started = time.perf_counter()
        _size, panned_tiles = decode_composite_tiles(source, (7000, 7000, 512, 512), 64)
        result["panned_tiles_seconds"] = round(time.perf_counter() - started, 3)
        result["panned_tiles"] = len(panned_tiles)
        started = time.perf_counter()
        document = PSDFormat._load_native(source)
        result["editable_import_seconds"] = round(time.perf_counter() - started, 3)
        result["resident_tile_bytes"] = sum(layer.tile_store.allocated_bytes() for layer in document.layers)
        for layer in document.layers:
            layer.tile_store.close()
    result["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
