"""Versioned native Nebula document serialization (not a ZIP container).

The file is a small binary header, a UTF-8 metadata section, then independently
compressed and checksummed RGBA tile records. Keeping records tile-sized avoids
building a second full-canvas byte buffer while saving or loading.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QFont, QImage

from CORE.native_bridge import (clone_image_native, copy_image_rect_native,
                                create_nebula_writer, crop_image_native,
                                fill_image_native,
                                open_nebula_reader,
                                validate_document_geometry,
                                validate_nebula_manifest)
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.layer_group import LayerGroup


MAGIC = b"NEBL"
VERSION = 1
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 1_000_000
MAX_CHUNK_BYTES = 64 * 64 * 4
MAX_DOCUMENT_DIMENSION = CSDFormat.MAX_DOCUMENT_DIMENSION
MAX_EAGER_IMAGE_PIXELS = 64 * 1024 * 1024
MAX_REFERENCE_IMAGES = 256
MAX_LAYERS = 100_000
MAX_TEXT_OBJECTS = 100_000
MAX_LAYER_GROUPS = 100_000


def _finite_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False
def _json_value(value):
    """Convert settings/preset values to JSON-safe finite primitive values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _image_tile(image: QImage, rect: QRect) -> bytes:
    tile = crop_image_native(image, rect, QImage.Format.Format_RGBA8888)
    if tile is None or tile.isNull():
        raise OSError("CreativeCore est requis pour lire une tuile d’image")
    return bytes(tile.constBits())


class NebulaFormat:
    """Read/write the native `.nebula` / `.nbl` versioned binary format."""

    @staticmethod
    def _metadata(document: Document):
        if not document.layers:
            raise ValueError("Un document Nebula doit contenir au moins un calque")
        geometry_valid = validate_document_geometry(
            document.width, document.height, document.dpi,
            MAX_DOCUMENT_DIMENSION, MAX_EAGER_IMAGE_PIXELS)
        if geometry_valid is None:
            geometry_valid = (1 <= document.width <= MAX_DOCUMENT_DIMENSION
                              and 1 <= document.height <= MAX_DOCUMENT_DIMENSION
                              and 1 <= document.dpi <= 9600
                              and document.width * document.height <= MAX_EAGER_IMAGE_PIXELS)
        if not geometry_valid:
            raise ValueError("La sélection dense dépasserait la limite mémoire Nebula")
        if len(document.layers) > MAX_LAYERS:
            raise ValueError("Le document contient trop de calques")
        if len(document.reference_images) > MAX_REFERENCE_IMAGES:
            raise ValueError("Le document contient trop d’images de référence")
        reference_pixels = sum(
            max(0, item.image.width()) * max(0, item.image.height())
            for item in document.reference_images
        )
        if any(item.image.isNull() for item in document.reference_images):
            raise ValueError("Une image de référence Nebula est vide")
        if reference_pixels > MAX_EAGER_IMAGE_PIXELS:
            raise ValueError("Les images de référence dépassent la limite mémoire Nebula")
        if len(document.text_objects) > MAX_TEXT_OBJECTS:
            raise ValueError("Le document contient trop d’objets texte")
        if len(document.layer_groups) > MAX_LAYER_GROUPS:
            raise ValueError("Le document contient trop de groupes")
        sources = []
        chunks = []
        next_id = 1

        def add_image_tiles(role: str, owner: int, width: int, height: int, get_tile,
                            occupied=None):
            nonlocal next_id
            columns = (width + 63) // 64
            rows = (height + 63) // 64
            records = []
            for ty in range(rows):
                for tx in range(columns):
                    if occupied is not None and (tx, ty) not in occupied:
                        continue
                    if next_id > MAX_CHUNKS:
                        raise ValueError("Le document contient trop de tuiles")
                    tile = get_tile(tx, ty)
                    if tile is None:
                        continue
                    tw, th = min(64, width - tx * 64), min(64, height - ty * 64)
                    record = {"id": next_id, "role": role, "owner": owner,
                              "x": tx, "y": ty, "width": tw, "height": th}
                    chunks.append(record)
                    sources.append((next_id, tile, tw, th))
                    records.append(next_id)
                    next_id += 1
            return records

        layers = []
        for index, layer in enumerate(document.layers):
            if (layer.tile_store.width != document.width
                    or layer.tile_store.height != document.height
                    or layer.tile_store.tile_size != 64):
                raise ValueError("La grille d’un calque est incohérente avec le document")
            layer.commit_image_cache()
            store = layer.tile_store
            occupied = set(store.occupied_keys)

            def layer_tile(tx, ty, target=store, keys=occupied):
                if (tx, ty) not in keys:
                    return None
                was_swapped = not target.tile_is_resident(tx, ty)

                def produce(target=target, tx=tx, ty=ty, swapped=was_swapped):
                    image = target.tile(tx, ty)
                    try:
                        return _image_tile(image, image.rect())
                    finally:
                        # Saving must not silently undo an existing disk eviction.
                        if swapped:
                            target.evict_tile_to_scratch(tx, ty)
                return produce

            tile_ids = add_image_tiles("layer", index, document.width, document.height, layer_tile)
            mask_store = getattr(layer, "alpha_mask_store", None)
            mask_tile_ids = []
            if mask_store is not None:
                if (mask_store.width != document.width or mask_store.height != document.height
                        or mask_store.tile_size != 64):
                    raise ValueError("La grille du masque alpha est incohérente avec le document")
                mask_occupied = set(mask_store.occupied_keys)

                def mask_tile(tx, ty, target=mask_store, keys=mask_occupied):
                    if (tx, ty) not in keys:
                        return None
                    was_swapped = not target.tile_is_resident(tx, ty)

                    def produce(target=target, tx=tx, ty=ty, swapped=was_swapped):
                        image = target.tile(tx, ty)
                        try:
                            return _image_tile(image, image.rect())
                        finally:
                            if swapped:
                                target.evict_tile_to_scratch(tx, ty)
                    return produce

                mask_tile_ids = add_image_tiles(
                    "layer_mask", index, document.width, document.height, mask_tile)
            layers.append({
                "id": layer.id, "name": layer.name, "visible": layer.visible,
                "opacity": layer.opacity, "blend_mode": layer.blend_mode,
                "blend_parameters": _json_value(layer.blend_parameters),
                "locked": layer.locked, "lock_alpha": layer.lock_alpha,
                "clipping": layer.clipping, "tiles": tile_ids,
                "mask_tiles": mask_tile_ids,
            })

        selection = None
        if not document.selection.is_empty():
            bounds = document.selection.bounds()
            selected_tiles = {
                (tx, ty)
                for ty in range(bounds.top() // 64, bounds.bottom() // 64 + 1)
                for tx in range(bounds.left() // 64, bounds.right() // 64 + 1)
            }
            selection = add_image_tiles(
                "selection", 0, document.width, document.height,
                lambda tx, ty: (lambda tx=tx, ty=ty: _image_tile(
                    document.selection.image,
                    QRect(tx * 64, ty * 64, min(64, document.width - tx * 64),
                          min(64, document.height - ty * 64)))),
                selected_tiles,
            )

        references = []
        for index, reference in enumerate(document.reference_images):
            image = reference.image
            if (image.isNull() or image.width() > MAX_DOCUMENT_DIMENSION
                    or image.height() > MAX_DOCUMENT_DIMENSION):
                raise ValueError("Dimensions d’image de référence Nebula invalides")
            tile_ids = add_image_tiles(
                "reference", index, image.width(), image.height(),
                lambda tx, ty, img=image: (lambda tx=tx, ty=ty, img=img: _image_tile(
                    img, QRect(tx * 64, ty * 64, min(64, img.width() - tx * 64),
                               min(64, img.height() - ty * 64))))
            )
            references.append({
                "id": reference.id, "width": image.width(), "height": image.height(),
                "x": reference.position.x(), "y": reference.position.y(),
                "scale": reference.scale, "opacity": reference.opacity,
                "tiles": tile_ids,
            })

        background = document.background_color
        metadata = {
            "name": str(getattr(document, "name", "Sans titre")),
            "author": str(getattr(document, "author", "")),
            "width": document.width, "height": document.height, "dpi": document.dpi,
            "active_layer": document.active_layer_index,
            "background": None if background is None else [
                background.red(), background.green(), background.blue(), background.alpha()],
            "layers": layers,
            "layer_groups": [{
                "id": group.id, "name": group.name, "layer_ids": list(group.layer_ids),
                "parent_id": group.parent_id,
                "visible": group.visible, "opacity": group.opacity,
                "blend_mode": group.blend_mode,
                "blend_parameters": _json_value(group.blend_parameters),
            } for group in document.layer_groups],
            "blend_presets": _json_value(document.blend_presets),
            "selection_tiles": selection,
            "references": references,
            "texts": [{
                "id": item.id, "text": item.text, "x": item.position.x(),
                "y": item.position.y(),
                "color": [item.color.red(), item.color.green(), item.color.blue(), item.color.alpha()],
                "font": item.font.toString(),
            } for item in document.text_objects],
            "chunks": chunks,
        }
        return metadata, sources

    @staticmethod
    def save(document: Document, file_path: str | Path) -> bool:
        writer = None
        try:
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            metadata, sources = NebulaFormat._metadata(document)
            if len(sources) > MAX_CHUNKS:
                raise ValueError("Le document contient trop de tuiles")
            encoded_metadata = json.dumps(
                metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(encoded_metadata) > MAX_METADATA_BYTES:
                raise ValueError("Métadonnées Nebula trop volumineuses")
            writer = create_nebula_writer(file_path, encoded_metadata, len(sources))
            if not writer:
                raise OSError("Le moteur C++ n’a pas pu ouvrir le fichier Nebula")
            for chunk_id, produce, width, height in sources:
                raw = produce()
                if len(raw) != width * height * 4 or len(raw) > MAX_CHUNK_BYTES:
                    raise ValueError("Taille de tuile Nebula invalide")
                if not writer.add_tile(chunk_id, raw):
                    raise OSError(f"Le moteur C++ a refusé la tuile {chunk_id}")
            finished = writer.finish()
            writer = None  # finish always releases the native writer handle
            if not finished:
                raise OSError("Échec de validation ou de publication atomique du fichier")
            return True
        except Exception as error:
            if writer:
                try:
                    writer.cancel()
                except Exception:
                    pass
            print(f"Erreur sauvegarde Nebula : {error}")
            return False

    @staticmethod
    def _validated_metadata(metadata, chunk_count):
        if not isinstance(metadata, dict):
            raise ValueError("Métadonnées Nebula invalides")
        width, height = int(metadata["width"]), int(metadata["height"])
        dpi = int(metadata.get("dpi", 300))
        layers = metadata.get("layers")
        chunks = metadata.get("chunks")
        geometry_valid = validate_document_geometry(
            width, height, dpi, MAX_DOCUMENT_DIMENSION, MAX_EAGER_IMAGE_PIXELS)
        if geometry_valid is None:
            geometry_valid = (1 <= width <= MAX_DOCUMENT_DIMENSION
                              and 1 <= height <= MAX_DOCUMENT_DIMENSION
                              and 1 <= dpi <= 9600
                              and width * height <= MAX_EAGER_IMAGE_PIXELS)
        if not geometry_valid:
            raise ValueError("Dimensions ou DPI Nebula invalides")
        if not isinstance(layers, list) or not layers or len(layers) > MAX_LAYERS:
            raise ValueError("Liste de calques Nebula invalide")
        if any(not isinstance(entry, dict) for entry in layers):
            raise ValueError("Entrée de calque Nebula invalide")
        layer_ids = [str(entry["id"]) for entry in layers if entry.get("id")]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Identifiants de calques Nebula dupliqués")
        if any(not isinstance(entry.get("blend_parameters", {}), dict)
               or any(not _finite_number(value)
                      for value in entry.get("blend_parameters", {}).values())
               for entry in layers):
            raise ValueError("Paramètres de fusion de calque Nebula invalides")
        if any(not _finite_number(entry.get("opacity", 1.0)) for entry in layers):
            raise ValueError("Opacité de calque Nebula invalide")
        if not isinstance(chunks, list) or len(chunks) != chunk_count or chunk_count > MAX_CHUNKS:
            raise ValueError("Table de tuiles Nebula invalide")
        references = metadata.get("references", [])
        if not isinstance(references, list) or len(references) > MAX_REFERENCE_IMAGES:
            raise ValueError("Liste d’images de référence Nebula invalide")
        reference_pixels = 0
        for entry in references:
            if not isinstance(entry, dict):
                raise ValueError("Entrée d’image de référence Nebula invalide")
            image_width, image_height = int(entry["width"]), int(entry["height"])
            if not (1 <= image_width <= MAX_DOCUMENT_DIMENSION
                    and 1 <= image_height <= MAX_DOCUMENT_DIMENSION):
                raise ValueError("Dimensions d’image de référence invalides")
            if any(not _finite_number(entry.get(key, default))
                   for key, default in (("x", 0), ("y", 0), ("scale", 1), ("opacity", 0.8))):
                raise ValueError("Transformée d’image de référence non finie")
            reference_pixels += image_width * image_height
            if reference_pixels > MAX_EAGER_IMAGE_PIXELS:
                raise ValueError("Les images de référence dépassent la limite mémoire Nebula")
        texts = metadata.get("texts", [])
        if not isinstance(texts, list) or len(texts) > MAX_TEXT_OBJECTS:
            raise ValueError("Liste d’objets texte Nebula invalide")
        for entry in texts:
            if (not isinstance(entry, dict)
                    or not _finite_number(entry.get("x", 0))
                    or not _finite_number(entry.get("y", 0))):
                raise ValueError("Position d’objet texte Nebula invalide")
            color = entry.get("color", [0, 0, 0, 255])
            if (not isinstance(color, list) or len(color) not in (3, 4)
                    or any(not _finite_number(value) for value in color)):
                raise ValueError("Couleur d’objet texte Nebula invalide")
        groups = metadata.get("layer_groups", [])
        if not isinstance(groups, list) or len(groups) > MAX_LAYER_GROUPS:
            raise ValueError("Liste de groupes Nebula invalide")
        for group in groups:
            if (not isinstance(group, dict)
                    or not isinstance(group.get("layer_ids", []), list)
                    or not isinstance(group.get("blend_parameters", {}), dict)
                    or any(not _finite_number(value) for value in
                           group.get("blend_parameters", {}).values())
                    or not _finite_number(group.get("opacity", 1.0))):
                raise ValueError("Métadonnées de groupe Nebula invalides")
        background = metadata.get("background")
        if background is not None and (
            not isinstance(background, list) or len(background) != 4
            or any(not _finite_number(value) for value in background)
        ):
            raise ValueError("Couleur de fond Nebula invalide")
        if not isinstance(metadata.get("blend_presets", {}), dict):
            raise ValueError("Presets de fusion Nebula invalides")
        if "active_layer" in metadata:
            int(metadata["active_layer"])
        return width, height, dpi

    @staticmethod
    def _validated_chunk_records(metadata, chunk_count):
        """Return the native-validated tile index for Qt reconstruction."""
        return {int(record["id"]): record for record in metadata["chunks"]}

    @staticmethod
    def load(file_path: str | Path) -> Document | None:
        reader = None
        try:
            reader = open_nebula_reader(file_path)
            if not reader:
                raise ValueError("Signature, version ou structure binaire Nebula invalide")
            encoded_metadata = reader.metadata(MAX_METADATA_BYTES)
            if encoded_metadata is None:
                raise ValueError("Impossible de lire les métadonnées Nebula")
            metadata = json.loads(encoded_metadata.decode("utf-8"))
            chunk_count = reader.chunk_count()
            native_geometry = validate_nebula_manifest(encoded_metadata, chunk_count)
            if native_geometry is None:
                raise RuntimeError("CreativeCore est requis pour valider le manifeste Nebula")
            if native_geometry is False:
                raise ValueError("Manifeste Nebula invalide")
            width, height, dpi = native_geometry
            python_geometry = NebulaFormat._validated_metadata(metadata, chunk_count)
            if python_geometry != native_geometry:
                raise ValueError("Géométrie Nebula divergente entre les validateurs")
            chunk_records = NebulaFormat._validated_chunk_records(metadata, chunk_count)

            document = Document(width, height, dpi,
                                QColor(*metadata["background"]) if metadata.get("background") else None)
            document.name = str(metadata.get("name", "Sans titre"))
            document.author = str(metadata.get("author", ""))
            document.layers.clear()
            for entry in metadata["layers"]:
                if not isinstance(entry, dict):
                    raise ValueError("Entrée de calque Nebula invalide")
                layer = document.add_layer(str(entry.get("name", "Calque")))
                layer.id = str(entry.get("id") or layer.id)
                layer.visible = entry.get("visible") is not False
                layer.opacity = max(0.0, min(1.0, float(entry.get("opacity", 1.0))))
                layer.blend_mode = str(entry.get("blend_mode", "normal"))
                layer.blend_parameters = dict(entry.get("blend_parameters", {}))
                layer.locked = bool(entry.get("locked", False))
                layer.lock_alpha = bool(entry.get("lock_alpha", False))
                layer.clipping = bool(entry.get("clipping", False))
            document.active_layer_index = max(0, min(
                int(metadata.get("active_layer", 0)), len(document.layers) - 1))
            document.blend_presets = metadata.get("blend_presets", {})

            references = []
            for entry in metadata.get("references", []):
                image_width, image_height = int(entry["width"]), int(entry["height"])
                image = QImage(image_width, image_height, QImage.Format.Format_RGBA8888)
                if not fill_image_native(image, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore a refusé l’initialisation d’une référence")
                references.append((entry, image))
            document.reference_images = [ReferenceImage(
                image, QPointF(float(entry.get("x", 0)), float(entry.get("y", 0))),
                max(0.01, min(100.0, float(entry.get("scale", 1.0)))),
                max(0.0, min(1.0, float(entry.get("opacity", 0.8)))),
                str(entry.get("id") or ReferenceImage(image).id),
            ) for entry, image in references]

            selection_image = QImage(width, height, QImage.Format.Format_RGBA8888)
            if not fill_image_native(selection_image, QColor(0, 0, 0, 0)):
                raise RuntimeError("CreativeCore a refusé l’initialisation de la sélection")
            seen_chunk_ids = set()
            for _ in range(chunk_count):
                decoded_tile = reader.next_tile(MAX_CHUNK_BYTES)
                if decoded_tile is None:
                    raise ValueError("Tuile Nebula tronquée ou invalide")
                chunk_id, raw = decoded_tile
                raw_size = len(raw)
                record = chunk_records.get(chunk_id)
                if (record is None or chunk_id in seen_chunk_ids
                        or raw_size != int(record["width"]) * int(record["height"]) * 4):
                    raise ValueError("Enregistrement de tuile invalide")
                seen_chunk_ids.add(chunk_id)
                role, owner = record["role"], int(record["owner"])
                tx, ty = int(record["x"]), int(record["y"])
                tw, th = int(record["width"]), int(record["height"])
                tile = clone_image_native(
                    QImage(raw, tw, th, tw * 4, QImage.Format.Format_RGBA8888))
                if tile is None:
                    raise ValueError("CreativeCore ne peut pas cloner une tuile Nebula")
                if role == "layer":
                    document.layers[owner].tile_store.set_tile(tx, ty, tile)
                elif role == "layer_mask":
                    mask_store = document.layers[owner].ensure_alpha_mask()
                    mask_store.set_tile(tx, ty, tile)
                elif role == "selection":
                    if not copy_image_rect_native(
                            tile, selection_image, QRect(0, 0, tw, th), tx * 64, ty * 64):
                        raise ValueError("CreativeCore ne peut pas restaurer le masque Nebula")
                else:
                    if not copy_image_rect_native(
                            tile, references[owner][1], QRect(0, 0, tw, th),
                            tx * 64, ty * 64):
                        raise ValueError("CreativeCore ne peut pas restaurer une référence Nebula")

            if metadata.get("selection_tiles"):
                document.selection.image = selection_image.convertToFormat(QImage.Format.Format_ARGB32)
                document.selection.invalidate()
            for item in metadata.get("texts", []):
                color = item.get("color", [0, 0, 0, 255])
                font = QFont()
                font.fromString(str(item.get("font", "")))
                if font.pointSizeF() <= 0:
                    font = QFont("Sans Serif", 24)
                document.text_objects.append(EditableText(
                    str(item.get("text", "")), QPointF(float(item.get("x", 0)), float(item.get("y", 0))),
                    QColor(*[max(0, min(255, int(value))) for value in color[:4]]), font,
                    str(item.get("id") or EditableText("", QPointF()).id)))
            layer_ids = {layer.id for layer in document.layers}
            for entry in metadata.get("layer_groups", []):
                members = [str(value) for value in entry.get("layer_ids", [])
                           if str(value) in layer_ids]
                indices = [next(i for i, layer in enumerate(document.layers) if layer.id == value)
                           for value in members]
                if members and indices == list(range(min(indices), max(indices) + 1)):
                    group = LayerGroup(
                        name=str(entry.get("name", "Groupe")), id=str(entry.get("id") or LayerGroup().id),
                        layer_ids=members, visible=entry.get("visible") is not False,
                        opacity=max(0.0, min(1.0, float(entry.get("opacity", 1.0)))),
                        blend_mode=str(entry.get("blend_mode", "normal")))
                    parent_id = entry.get("parent_id")
                    group.parent_id = str(parent_id) if parent_id else None
                    group.blend_parameters = dict(entry.get("blend_parameters", {}))
                    document.layer_groups.append(group)
            groups_by_id = {group.id: group for group in document.layer_groups}
            if len(groups_by_id) != len(document.layer_groups):
                raise ValueError("Identifiants de groupes Nebula dupliqués")
            for group in document.layer_groups:
                if group.parent_id is not None:
                    parent = groups_by_id.get(group.parent_id)
                    if parent is None or not set(group.layer_ids).issubset(parent.layer_ids):
                        raise ValueError("Hiérarchie de groupes Nebula invalide")
                elif any(group is not other and other.parent_id is None
                         and set(group.layer_ids).intersection(other.layer_ids)
                         for other in document.layer_groups):
                    raise ValueError("Groupes racine Nebula chevauchants")
            document.sync_native_state()
            return document
        except Exception as error:
            print(f"Erreur ouverture Nebula : {error}")
            return None
        finally:
            if reader:
                reader.close()


def load_document(file_path: str | Path) -> Document | None:
    """Load Nebula, or import legacy CSD/Atlas projects read-only."""
    try:
        with Path(file_path).open("rb") as source:
            signature = source.read(4)
        if signature == MAGIC:
            return NebulaFormat.load(file_path)
        if signature[:2] == b"PK":
            return CSDFormat.load(file_path)
        if signature == b"ATLS":
            from DOCUMENTS.format_atlas import AtlasFormat
            return AtlasFormat.load(file_path)
    except OSError:
        return None
    return None


__all__ = ["NebulaFormat", "load_document", "MAGIC", "VERSION"]
