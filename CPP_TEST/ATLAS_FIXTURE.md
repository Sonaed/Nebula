# Atlas v3 interoperability fixture

`atlas_v3_serializer_sample.atlas` was written by the original Atlas v3
`AtlasSerializer::save` implementation from
`CreativeSystemAtlas_alpha0.1/engine/serialization/atlas_project.cpp`, then
opened through Nebula's native Atlas reader and Python document adapter. It is
not a hand-authored byte stream. The small fixture contains one 3×2 RGBA layer,
144 DPI metadata, and a mask that reduces the final pixel alpha from 64 to 32.

`test_atlas_serializer_interop.py` keeps this cross-project compatibility check
in the routine suite; it does not require the Atlas source tree at test time.
