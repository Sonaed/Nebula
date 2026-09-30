# Nebula 26.1.0 release qualification

This is the reproducible qualification record for the production-beta release.
It intentionally uses generated fixtures so no private artwork is required.

| Gate | Evidence | Result |
| --- | --- | --- |
| PSD structure, masks, groups, supported adjustments, and unsupported-feature reporting | `CPP_TEST.test_psd_reader`, `CPP_TEST.test_psd_parity`, `CPP_TEST.test_large_document_io` | Pass; optional `psd-tools` parity cases are explicitly skipped when that dependency is absent. |
| Corrupt/interrupted native files | `CPP_TEST.test_nebula_format` | Pass; expected rejection messages are exercised by negative cases. |
| Selection/masking and adjustment persistence | `CPP_TEST.test_selection`, `CPP_TEST.test_selection_native`, `CPP_TEST.test_adjustments_native`, `CPP_TEST.test_tile_history` | Pass. |
| CPU projection and large native save/reopen | `docs/benchmarks/8k-50-sparse.json`, `docs/benchmarks/8k-50-dense.json`, `CPP_TEST/benchmark_8k_document.py` | **Required release gate.** Sparse fixture reopened in 0.118 s; dense 8,000 px/50 layer fixture reopened in 24.0355 s with a measured 14,097.1 MiB peak. |
| 512 MB / 8,000 px PSD preview path | `docs/benchmarks/500mb-8k-headless.json`, `CPP_TEST/benchmark_500mb_psd.py` | Pass: metadata 0.001 s, preview 0.590 s, first visible tiles 0.054 s, peak RSS 1117.5 MiB. |
| GPU-safe presentation and CPU fallback | `CPP_TEST.test_gpu_frame_snapshot`, `CPP_TEST.test_gpu_dirty_tracking`, `CPP_TEST.test_projection_presentation` | Pass: 59 checks. The application retains native CPU projection when the safe GPU presenter is unavailable. |
| UI/interactions | `CPP_TEST.test_ui_design_system`, `CPP_TEST.test_projection_presentation` | Pass: non-modal PSD import/proxy state, layer search/thumbnails, focus and shortcut behavior. |

## Expected skips

The only PSD parity skips are dependency-gated `psd-tools` interoperability
checks. Nebula's built-in reader/writer and the corresponding non-optional
tests still run. They are not silent failures and do not hide production code.

## Release scope

The build is a production beta. Editable Photoshop export is deliberately
limited to Curves and Levels-as-curves; other adjustment types are flattened
and shown in the export-loss report. GPU support is safe tile presentation,
with CPU projection as the correct fallback for unsupported driver/context
capabilities.

## Memory limit

The dense fixture is intentionally a stress case: it has 50 fully populated
8,000 px layers and peaks at about **14.1 GiB RSS** during import/save/reopen.
It is a required qualification run, not a recommended working-document size.
Nebula's default working-memory budget is 60% of physical RAM (bounded to
512 MiB–48 GiB), configurable in Preferences. When exceeded, the status bar
warns the user and Nebula evicts non-visible tiles and eligible undo payloads
to its disk-backed scratch cache. The working UI remains available through the
PSD composite preview while editable layers continue decoding in background.

Run the mandatory dense gate with:

`QT_QPA_PLATFORM=offscreen python CPP_TEST/benchmark_8k_document.py --release-gate --output docs/benchmarks/8k-50-dense.json`

The exporter spools compressed PSD channel data to a temporary file and
releases each layer image before proceeding to the next one. It therefore
never retains all full-size RGBA layers at once during export.
