# 8000 × 8000 / 50-layer validation — 2026-09-28

The updated engine successfully imported, saved and reopened an 8000 × 8000
8-bit RGBA document with 50 fully populated, translucent raster layers. PSD
export also completed and its layer pixels were checked on reopening. This
validates the document-size target, not Photoshop-equivalent interactive speed.

## Measured results

Machine: AMD Ryzen 7 3700X, approximately 40 GiB system RAM, Linux, release
CreativeCore build. These are single-run wall-clock measurements on a shared
machine, not isolated benchmark medians.

| Operation | Full 8000 × 8000 pixels on every layer | 512 × 512 painted area on every layer |
| --- | ---: | ---: |
| PSD import | 29.48 s | 0.22 s |
| PSD export | 68.28 s | Not measured |
| Nebula save | 31.35 s | 0.21 s |
| Nebula reopen | 24.04 s | 0.12 s |
| Process peak resident memory | 14,097 MiB | 437 MiB |
| Resident layer pixels | 12.8 GB | 52.4 MB |
| Median composition of one 64 × 64 tile | 1.92 ms | 1.94 ms |

Both documents have 50 editable layers and an 8000 × 8000 canvas. The full
fixture uses a uniform colour with alpha 128 on every layer, so all layers
contribute, but the image data is highly compressible. These timings do not
predict noisy artwork, complex masks, effects, adjustment stacks or arbitrary
Photoshop files. Tile-composition time is not a frame-rate measurement.

Raw results: [dense](benchmarks/8k-50-dense.json),
[sparse](benchmarks/8k-50-sparse.json).

## Changes

- PSD input files are memory-mapped. Editable layers decode one at a time and
  release their temporary pixels after transfer to native tiles.
- PSD previews read the merged image without decoding the full layer stack.
- Full-canvas raster imports transfer directly to the native tile writer;
  offset layers convert in bounded strips.
- PSD/PSB export uses native zlib compression and a temporary channel spool,
  retaining one decoded layer at a time. Large merged previews composite from
  tiles instead of materializing every layer together.
- Photoshop export preserves bottom-to-top raster order and white defaults
  outside sparse masks. Save As now dispatches to the layered writer. PSB is
  available in the open/save dialogs.
- Nebula saves/loads resident raster and mask tiles directly in the native
  engine. Scratch-backed tiles, references and selections retain their
  existing validated adapter path. CRC validation remains enabled and uses
  zlib's compatible IEEE CRC. The metadata cap is now 128 MiB.
- Native tile batches stage only changed keys, preserving atomic validation
  without copying every existing tile index on each batch.
- Empty documents no longer allocate an unnecessary full raster background.
  Nebula reopening no longer allocates a second empty selection image.
- Large normal stacks use cached projection when no GPU stroke is active.
  Viewports larger than the shader compositor's 256-tile cache use budgeted
  projection, and shader cache hits refresh eviction order.
- Thumbnail fingerprints use the tile store mutation counter. Dirty-image
  history edits publish their changed regions before undo captures pixels.

## Validation

- Production native library rebuilt successfully.
- 92 focused Python test cases: successful run, 4 optional cases skipped
  (psd-tools and an external real-world PSD fixture were unavailable).
- 24 existing performance/thumbnail function tests passed. Stale source-string
  expectations and test doubles were updated to the current projection paths.
- Native tile-store test compiled separately against the rebuilt static
  library with assertions enabled and passed, including invalid-batch
  atomicity, duplicate writes, deletion and preservation of unrelated tiles.
- Small PSD and PSB round trips verified layer order, pixels, groups and sparse
  mask defaults. Direct Nebula I/O verified the v1 checksum against Python
  zlib and rejected a deliberately corrupted checksum.
- Headless application startup/shutdown passed with native brush/projection
  enabled. Desktop OpenGL smoke execution did not complete successfully in
  this environment; interactive GPU frame rate remains unverified.
- Python compilation and whitespace checks passed.

## Remaining limits

A dense 50-layer document still needs about 12.8 GB for uncompressed 8-bit
pixels alone. Import/export remains a substantial operation, and the above
results are not a claim of Photoshop-speed painting, panning or launch with
this dense document. No comparison against Photoshop was performed.

PSD export is an 8-bit raster writer, not a lossless export of every Photoshop
feature. Nested group export, editable adjustment metadata, vector objects,
smart objects and all Photoshop effects are not covered by this work. Use
Nebula for its native editable state; use PSB when Photoshop section lengths
outgrow PSD's 32-bit fields. Documents with many full-canvas masks can still
reach Nebula's existing one-million-chunk limit.

The binary layout follows the
[Adobe Photoshop file-format specification](https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/).
Compatibility was verified with Nebula's reader; direct Photoshop validation
and the optional psd-tools parity suite remain outstanding.

## Reproduce

From the Nebula directory:

```sh
cmake --build build_cpp_native -j2
QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_8k_document.py --psd-export --output /tmp/nebula-dense.json
QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_8k_document.py --patch-size 512 --output /tmp/nebula-sparse.json
QT_QPA_PLATFORM=offscreen python -m unittest CPP_TEST.test_large_document_io CPP_TEST.test_nebula_format CPP_TEST.test_psd_reader CPP_TEST.test_psd_parity CPP_TEST.test_tile_store CPP_TEST.test_tile_history CPP_TEST.test_native_projection CPP_TEST.test_application_smoke -q
```

Fixture creation is excluded from timings. The dense run requires substantial
available memory; the benchmark intentionally retains all editable tiles.
The application entry point remains `python main.py`.
