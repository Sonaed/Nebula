# Nebula `.nebula` format v1 policy

Version 1 is frozen for the production-beta boundary. Readers must preserve
layers, groups, masks, selections, adjustments, text, references, color
metadata, and tile checksums. A future version is rejected explicitly rather
than loaded with silent loss. Migration to a future format must produce a new
file and retain the original.

PSD remains an interchange format with a loss report; `.nebula` is the only
format with a preservation guarantee.
