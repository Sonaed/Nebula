# Nebula 26.1.0 release roadmap

Status reflects implementation in the current tree. A checked item has code
and focused automated coverage where practical; it does **not** by itself mean
the 500 MB / 8,000 px release acceptance target has been met.

## Priority 1 — Large PSD performance

- [x] Parse PSD/PSB metadata and layer hierarchy without decoding all layer pixels.
- [x] Read the embedded composite preview independently of editable layers.
- [x] Display the composite preview while import work remains in the background.
- [x] Plan visible viewport tiles before nearby halo tiles.
- [x] Put decoded visible composite tiles into the Canvas proxy tile store.
- [x] Decode the one-tile viewport halo with the first composite-tile pass.
- [x] Reprioritize uncached visible/nearby composite tiles when the user pans during a still-running import.
- [x] Defer hidden and distant raster-layer decoding until opening-viewport raster layers have transferred, while preserving original layer order.
- [x] Cancel PSD import cooperatively between layer decodes and on window close.
- [x] Keep PSD work off the Qt event thread and publish progress through the UI timer.
- [x] Avoid whole-composite decode for raw, PackBits, ZIP, and ZIP-with-prediction composites when extracting viewport regions.
- [x] Reuse decoded regions through a bounded LRU keyed by source, owner/layer, channel set, and tile rectangle; the importer decodes each editable-layer channel only once before sparse tile transfer.
- [x] Show preview/import/tile progress in the status area.
- [x] Show live process, document, cache, and GPU memory accounting.
- [x] Record memory peak and timing for a 512,000,132-byte / 8,000 px PSD qualification fixture.
- [x] Verify decoder readiness ≤2 s (0.001 s metadata), preview ≤3 s (0.590 s), and first visible region ≤1 s after preview (0.054 s).
- [x] Verify panned visible-region decoding is bounded (0.080 s for a distant viewport; no full-document compose).

Qualification evidence is in `docs/benchmarks/500mb-8k-headless.json`. The
fixture is generated with incompressible full-size channels, so the 512 MB
file-size and 8,000 px conditions are exercised without depending on private
artwork. A separate 50-layer sparse smoke benchmark imported in 0.280 s;
native save was 0.255 s; native reopen was 0.168 s; peak RSS was 436.1 MiB.

## Priority 2 — Native `.nebula` format

- [x] Store native documents as independently compressed, checksummed tile records.
- [x] Validate file metadata and tile manifests before rebuilding a document.
- [x] Atomically save native files and preserve the last valid recovery snapshot on failure.
- [x] Load document structure before native pixel data through the indexed lazy-open path.
- [x] Load visible native tiles before distant tiles through document-space tile warming.
- [x] Expose bounded native tile-cache warming for background workers.
- [x] Add a copy-only native-format migration API and command-line tool.
- [x] Add interrupted-save recovery coverage for a sparse 8,000 px native document.
- [x] Benchmark large `.nebula` reopen against equivalent PSD input (the 8,000 px / 50-layer sparse benchmark records 0.280 s PSD import and 0.168 s native reopen).

## Priority 3 — Photoshop interchange

- [x] Import raster layers, groups, opacity, common blend modes, masks, clipping, ICC profiles, and supported adjustment metadata.
- [x] Read PSD and PSB structure; write layered PSD and PSB documents.
- [x] Preserve import limitations in an import report and display them after opening.
- [x] Generate and display a PSD/PSB export-loss report for flattened adjustments/text and unsupported hierarchy/effects.
- [x] Cover PSD/PSB round trips and sparse large-document I/O with focused tests.
- [x] Add per-layer unsupported-feature indicators and explanatory tooltips in the Layers UI.
- [x] Export Curves and Levels-as-curves as editable Photoshop `curv` adjustment records; flatten and report unsupported adjustment types.
- [x] Add 8-bit and 16-bit fixture matrix with expected results and a deterministic 16-bit import fixture.
- [x] Complete PSB support assessment and large-file qualification with documented supported scope and limitations.

## Priority 4 — Adjustments and filters

- [x] Release-qualify Levels, Curves, Brightness/Contrast, Hue/Saturation, Color Balance, Exposure, Gradient Map, Color Lookup, blur/sharpen, and noise reduction.
- [x] Confirm non-destructive storage, undo/redo, serialization, preview, native execution, CPU/GPU parity, and PSD behavior for every supported adjustment.

Brightness/Contrast is now an editable native-LUT adjustment with live preview,
tile-stack LUT support, history, and `.nebula` round-trip coverage. Curves and
Levels export as editable PSD records; other adjustment/filter types are
flattened deliberately and named in the PSD export-loss report. Blur/sharpen
and deterministic noise use the native filter ABI and its filter-layer
descriptor coverage. CPU and GPU projection share the same cached adjustment
tables; settings that need per-pixel execution retain the native CPU fallback.

## Priority 5 — Selection and masking

- [x] Release-qualify rectangular, elliptical, and lasso selections; selection combination modes; invert/expand/contract/feather; alpha-to-selection; persistence; and mask workflow controls.

Shape masks honor configured edge smoothing and feathering, and alpha-to-
selection is available as **Selection → Layer Transparency**. Selection and
mask edits use selection-only tile history and persist in native documents.

## Priority 6 — Interaction and polish

- [x] Surface PSD preview/tile/import state in the status area.
- [x] Surface application memory usage in the status area.
- [x] Add a visible, non-blocking Cancel control to the PSD import UI.
- [x] Add proxy/editable-import state and clear flattened-content warnings to the import UI.
- [x] Add layer search/filtering and improved thumbnails.
- [x] Audit shortcuts, large-canvas zoom/pan stability, and non-modal long-operation UI.

## Release gates still open

- [x] Full release fixture matrix: small/layered/masked/grouped/adjusted/unsupported PSDs, 8,000 px, supported 16-bit, corrupt/interrupted files, CPU-only, and GPU-enabled environments.
- [x] Document peak memory for the large PSD benchmark.
- [x] No unexplained validation skips.
- [x] Native save/reopen reliability run for the release fixture set.

Qualification commands, expected dependency-gated skips, benchmark results,
and release scope are recorded in `docs/RELEASE_QUALIFICATION_26.1.0.md`.
The dense 8,000 px / 50 full-layer benchmark is a required gate, with its
memory limit documented there; it must not be replaced by the sparse run.
