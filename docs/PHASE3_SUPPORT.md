# Nebula Phase 3 support boundary

Nebula's production interchange format is `.nebula`/`.nbl`, with PSD import
and export supported for raster layers, groups, opacity, blending, masks,
clipping, editable text metadata, and embedded ICC profiles. Unsupported PSD
features must be reported as losses; they are not silently advertised as
editable.

Rendering authority remains the native CPU document/brush/compositor path.
OpenGL is a presentation and preview accelerator with explicit replay fallback,
so GPU availability cannot change the saved result. Production parity tests
must compare the committed CPU image, not screenshots of the viewport.

Color workflows use embedded ICC metadata, explicit linear-sRGB tagging, and
`SoftProofSettings` for output intent. HDR/16-bit float storage is not claimed
until a native document surface and export fixture exist; current documents
remain bounded RGBA with explicit conversion at interchange boundaries.

Automation uses `nebula.script.v1`, a narrow document facade that can add
adjustment layers and save without depending on private Qt widgets.
