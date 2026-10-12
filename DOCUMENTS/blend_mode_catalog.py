"""Stable blend identifiers shared by native composition, PSD and the UI.

Append modes: existing IDs are part of the CreativeCore ABI.
"""
BLEND_MODE_LABELS = (
    ("normal", "Normal"), ("darken", "Obscurcir"), ("multiply", "Produit"),
    ("color_burn", "Densité couleur +"), ("lighten", "Éclaircir"),
    ("screen", "Superposition"), ("color_dodge", "Densité couleur −"),
    ("overlay", "Incrustation"), ("soft_light", "Lumière tamisée"),
    ("hard_light", "Lumière crue"), ("difference", "Différence"),
    ("exclusion", "Exclusion"), ("hue", "Teinte"), ("saturation", "Saturation"),
    ("color", "Couleur"), ("luminosity", "Luminosité"),
    ("linear_dodge", "Densité linéaire − (Ajout)"),
    ("linear_burn", "Densité linéaire +"), ("vivid_light", "Lumière vive"),
    ("linear_light", "Lumière linéaire"), ("pin_light", "Lumière ponctuelle"),
    ("hard_mix", "Mélange maximal"), ("darker_color", "Couleur plus foncée"),
    ("lighter_color", "Couleur plus claire"), ("subtract", "Soustraction"),
    ("divide", "Division"),
)
BLEND_MODES = tuple(mode for mode, _label in BLEND_MODE_LABELS)
BLEND_MODE_IDS = {mode: index for index, mode in enumerate(BLEND_MODES)}
NATIVE_ONLY_BLEND_MODES = frozenset(BLEND_MODES[12:])
