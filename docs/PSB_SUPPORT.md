# PSB support assessment — Nebula 26.1.0

Nebula accepts Photoshop Large Document Format (PSB, version 2) through the
same native structure reader used for PSD. It preserves raster layers, groups,
opacity, common blend modes, clipping, pixel masks, ICC profiles, and supported
adjustment metadata. It writes version-2 layer-channel lengths and is covered
by PSD/PSB sparse mask and layer-order round-trip tests.

Supported interchange scope:

- 8-bit RGB(A) raster documents, including large sparse canvases;
- PSB layer/channel length fields and composite data;
- native `.nebula` migration after import.

Known visible limitations:

- 16-bit data imports for display but exports as 8-bit;
- Curves and Levels-as-curves export as editable `curv` records; other
  adjustment types are flattened and reported;
- smart objects, unsupported layer styles, advanced typography, and unknown
  Photoshop structures retain an import/export loss report rather than being
  silently discarded.

Qualification evidence includes the 8,000 px / 50-layer sparse PSD/PSB
round-trip suite and the 512 MB / 8,000 px raw-channel decoder fixture. The
fixture matrix is maintained in `PSD_FIXTURE_MATRIX.md`.
