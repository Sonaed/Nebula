"""Small, pixel-free descriptions retained beside the native undo payload."""
from __future__ import annotations


TOOL_HISTORY_LABELS = {
    "brush": "Coup de pinceau", "eraser": "Gomme", "smudge": "Estompe",
    "blur": "Flou local", "sharpen": "Netteté locale", "clone_stamp": "Tampon de duplication",
    "fill": "Remplissage", "gradient": "Dégradé", "line": "Ligne",
    "rectangle": "Rectangle", "ellipse": "Ellipse", "bezier": "Courbe de Bézier",
}


def _object_signature(item):
    image = getattr(item, "image", None)
    return (item.id, item.position, getattr(item, "text", None),
            getattr(item, "color", None), getattr(item, "font", None),
            getattr(item, "scale", None), getattr(item, "opacity", None),
            image.cacheKey() if image is not None else None)


def describe_step(before: dict, after: dict, tile_keys) -> tuple[str, str]:
    """Describe metadata before CreativeCore takes ownership of that metadata.

    Only metadata and tile *keys* are inspected. Pixel payloads must never be
    decoded or copied merely to populate the History panel.
    """
    if (before.get("width"), before.get("height")) != (after.get("width"), after.get("height")):
        return "Dimensions du document", f"{after.get('width', 0)} × {after.get('height', 0)} px"
    if before.get("history_mode") == "selection":
        return "Sélection", "Zone de sélection"

    for key, added, removed, edited in (
        ("text_objects", "Ajouter un texte", "Supprimer un texte", "Modifier un texte"),
        ("reference_images", "Ajouter une référence", "Supprimer une référence", "Modifier une référence"),
    ):
        old, new = before.get(key, ()), after.get(key, ())
        if len(old) != len(new):
            return (added if len(new) > len(old) else removed), ""
        if [_object_signature(item) for item in old] != [_object_signature(item) for item in new]:
            return edited, ""

    old_layers, new_layers = before.get("layers", ()), after.get("layers", ())
    old_by_id = {layer["id"]: layer for layer in old_layers}
    new_by_id = {layer["id"]: layer for layer in new_layers}
    added = [layer for layer in new_layers if layer["id"] not in old_by_id]
    removed = [layer for layer in old_layers if layer["id"] not in new_by_id]
    if added and not removed:
        return "Ajouter un calque" if len(added) == 1 else "Ajouter des calques", ", ".join(layer["name"] for layer in added)
    if removed and not added:
        return "Supprimer un calque" if len(removed) == 1 else "Supprimer des calques", ", ".join(layer["name"] for layer in removed)
    if [layer["id"] for layer in old_layers] != [layer["id"] for layer in new_layers]:
        return "Réorganiser les calques", ""
    changes = (
        ("name", "Renommer le calque"), ("visible", "Visibilité du calque"),
        ("opacity", "Opacité du calque"), ("blend_mode", "Mode de fusion"),
        ("blend_parameters", "Paramètres de fusion"), ("locked", "Verrouillage du calque"),
        ("lock_alpha", "Verrouillage alpha"), ("clipping", "Écrêtage du calque"),
        ("alpha_mask_present", "Masque de calque"),
    )
    for layer in new_layers:
        old = old_by_id[layer["id"]]
        for key, label in changes:
            if old.get(key) != layer.get(key):
                return label, str(layer.get("name", ""))
    if before.get("layer_groups") != after.get("layer_groups"):
        return "Groupe de calques", ""
    if before.get("blend_presets") != after.get("blend_presets"):
        return "Réglage de fusion", ""

    layer_ids = {key[0] for key in tile_keys}
    if layer_ids == {"__selection_mask__"}:
        return "Sélection", "Zone de sélection"
    if any(key.startswith("__alpha_mask__:") for key in layer_ids):
        return "Peindre le masque", "Masque de calque"
    names = [layer["name"] for layer in new_layers if layer["id"] in layer_ids]
    if layer_ids:
        return "Modification des pixels", ", ".join(names)
    return "Modification du document", ""


__all__ = ["TOOL_HISTORY_LABELS", "describe_step"]
