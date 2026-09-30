# PSD/PSB interchange fixture matrix

| Fixture | Coverage | Expected result |
| --- | --- | --- |
| Native 8-bit PSD | Raster layers, groups, masks, clipping, blend modes | Editable import and PSD round trip |
| Native 16-bit RGB PSD | 16-bit composite channels | Deterministic 8-bit display conversion (high byte) |
| Native PSD/PSB | Sparse raster layers and masks | Layer order, pixels, masks, groups preserved |
| 8,000 px / 50-layer sparse PSD | Large document interchange | PSD import and native reopen benchmarked |
| 512 MB / 8,000 px PSD | Large raw RGBA channels | Metadata, preview, viewport tile, panning, and editable-import qualification |

The current writer emits 8-bit RGB(A) PSD/PSB pixel data. It imports supported
8-bit and 16-bit data; 16-bit export is intentionally reported as an
interchange limitation rather than silently advertised as lossless.
