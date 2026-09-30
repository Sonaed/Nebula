"""Versioned native Nebula document serialization (not a ZIP container).

The file is a small binary header, a UTF-8 metadata section, then independently
compressed and checksummed RGBA tile records. Keeping records tile-sized avoids
building a second full-canvas byte buffer while saving or loading.
"""
from __future__ import annotations

import json
import math
import logging
import struct
import zlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QFont, QImage

from CORE.native_bridge import (clone_image_native, copy_image_rect_native,
                                create_nebula_writer, crop_image_native,
                                fill_image_native,
                                open_nebula_reader, nebula_store_tiles_io,
                                validate_document_geometry,
                                validate_nebula_manifest)
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.layer_group import LayerGroup

logger = logging.getLogger(__name__)


MAGIC = b"NEBL"
VERSION = 1
FORMAT_ID = "nebula"
SUPPORTED_VERSIONS = frozenset({1})
MAX_METADATA_BYTES = 128 * 1024 * 1024
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
    def migrate(source: str | Path, destination: str | Path | None = None) -> Path:
        """Convert a legacy document into a new native `.nebula` file.

        Migration is intentionally copy-only: it never overwrites the source
        or an existing destination.  Callers that deliberately want to
        replace a file can do so after opening and validating the result.
        """
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination is None:
            destination = source.with_suffix(".nebula")
        destination = Path(destination)
        if destination.suffix.lower() not in (".nebula", ".nbl"):
            destination = destination.with_suffix(".nebula")
        if destination.exists():
            raise FileExistsError(destination)
        try:
            same_file = source.resolve() == destination.resolve()
        except OSError:
            same_file = source == destination
        if same_file:
            raise ValueError("La migration doit écrire un nouveau fichier Nebula")
        document = load_document(source)
        if document is None:
            raise ValueError(f"Document source illisible : {source}")
        if not NebulaFormat.save(document, destination):
            raise OSError(f"Échec de migration vers {destination}")
        return destination

    @staticmethod
    def _tile_offsets(path: Path, metadata_size: int, chunk_count: int) -> dict[int, tuple[int, int, int, int]]:
        """Index tile payloads without inflating them (id -> payload/size/crc)."""
        result = {}
        with path.open("rb") as stream:
            stream.seek(16 + metadata_size)
            for _ in range(chunk_count):
                header = stream.read(28)
                if len(header) != 28:
                    raise ValueError("Index de tuiles Nebula tronqué")
                kind, chunk_id, raw_size, packed_size, checksum = struct.unpack("<4sIQQI", header)
                if (kind != b"TILE" or not chunk_id or chunk_id in result
                        or raw_size <= 0 or raw_size > MAX_CHUNK_BYTES
                        or packed_size < 4 or packed_size > 64 * 1024):
                    raise ValueError("Index de tuile Nebula invalide")
                offset = stream.tell()
                result[chunk_id] = (offset, int(packed_size), int(raw_size), int(checksum))
                stream.seek(packed_size, 1)
        if len(result) != chunk_count:
            raise ValueError("Index de tuiles Nebula incomplet")
        return result

    @staticmethod
    def warm_tiles(document: Document, visible_rect: QRect | None = None,
                   maximum: int | None = None) -> int:
        """Load deferred native tiles, prioritizing a document-space rectangle."""
        pending = list(getattr(document, "_nebula_deferred_tiles", ()))
        if not pending:
            return 0
        bounds = QRect(0, 0, document.width, document.height)
        rect = bounds if visible_rect is None else QRect(visible_rect).intersected(bounds)
        selected, retained = [], []
        for entry in pending:
            record = entry["record"]
            tile_rect = QRect(int(record["x"]) * 64, int(record["y"]) * 64,
                              int(record["width"]), int(record["height"]))
            if rect.intersects(tile_rect) and (maximum is None or len(selected) < maximum):
                selected.append(entry)
            else:
                retained.append(entry)
        if not selected:
            return 0
        path = Path(document._nebula_source_path)
        loaded = 0
        with path.open("rb") as stream:
            for entry in selected:
                record = entry["record"]
                offset, packed_size, raw_size, checksum = entry["offset"]
                stream.seek(offset)
                packed = stream.read(packed_size)
                if len(packed) != packed_size or len(packed) < 4:
                    raise ValueError("Tuile Nebula tronquée")
                announced = int.from_bytes(packed[:4], "big")
                raw = zlib.decompress(packed[4:])
                if (announced != raw_size or len(raw) != raw_size
                        or (zlib.crc32(raw) & 0xffffffff) != checksum):
                    raise ValueError("Somme de contrôle de tuile Nebula invalide")
                tile = clone_image_native(QImage(raw, int(record["width"]), int(record["height"]),
                                                 int(record["width"]) * 4,
                                                 QImage.Format.Format_RGBA8888))
                if tile is None:
                    raise ValueError("CreativeCore ne peut pas charger une tuile Nebula")
                layer = document.layers[int(record["owner"])]
                store = layer.tile_store if record["role"] == "layer" else layer.ensure_alpha_mask()
                if not store.set_tile(int(record["x"]), int(record["y"]), tile):
                    raise ValueError("CreativeCore a refusé une tuile Nebula")
                loaded += 1
        document._nebula_deferred_tiles = retained
        return loaded

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
                "label_color": getattr(layer, "label_color", None),
                "locked": layer.locked, "lock_alpha": layer.lock_alpha,
                "clipping": layer.clipping, "tiles": tile_ids,
                "mask_tiles": mask_tile_ids,
                "layer_kind": str(getattr(layer, "layer_kind", "raster")),
                "adjustment": _json_value(getattr(layer, "adjustment", None)),
                "layer_effects": _json_value(getattr(layer, "layer_effects", [])),
                "psd_effects": _json_value(getattr(layer, "psd_effects", [])),
                "retouch_operations": _json_value(getattr(layer, "retouch_operations", [])),
                "transform_state": _json_value(getattr(layer, "transform_state", None)),
            })

        selection = None
        if not document.selection.is_empty():
            selection_store = document.selection.tile_store
            selected_tiles = set(selection_store.occupied_keys)

            def selection_tile(tx, ty, target=selection_store, keys=selected_tiles):
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
            selection = add_image_tiles(
                "selection", 0, document.width, document.height,
                selection_tile,
                selected_tiles,
            )

        # Named selections are document assets, not UI state.  Persist them
        # through the same sparse/tiled stream as the working selection so a
        # large canvas never needs a second dense payload in the file.
        saved_selections = []
        for selection_index, (name, image) in enumerate(
                sorted(getattr(document, "saved_selections", {}).items())):
            if not isinstance(name, str) or not name.strip() or not isinstance(image, QImage):
                continue
            if image.size() != document.selection.image.size():
                raise ValueError("Une sélection enregistrée a une taille incohérente")
            # Reuse the native bounds query through a temporary semantic mask
            # only when there is content; fully empty saved selections still
            # retain their name and round-trip as an empty mask.
            alpha_bounds = image.rect()
            from CORE.native_bridge import native_selection_bounds
            values = native_selection_bounds(image)
            if values is not None:
                alpha_bounds = QRect(*values)
            occupied = ({(tx, ty)
                         for ty in range(alpha_bounds.top() // 64, alpha_bounds.bottom() // 64 + 1)
                         for tx in range(alpha_bounds.left() // 64, alpha_bounds.right() // 64 + 1)}
                        if not alpha_bounds.isEmpty() else set())
            tile_ids = add_image_tiles(
                "saved_selection", selection_index, document.width, document.height,
                lambda tx, ty, source=image: (lambda tx=tx, ty=ty, source=source: _image_tile(
                    source, QRect(tx * 64, ty * 64, min(64, document.width - tx * 64),
                                  min(64, document.height - ty * 64)))),
                occupied,
            )
            saved_selections.append({"name": name.strip(), "tiles": tile_ids})

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

        groups = []
        for group_index, group in enumerate(document.layer_groups):
            mask_tiles = []
            mask_store = getattr(group, "alpha_mask_store", None)
            if mask_store is not None:
                keys = set(mask_store.occupied_keys)

                def group_mask_tile(tx, ty, target=mask_store, occupied=keys):
                    if (tx, ty) not in occupied:
                        return None
                    def produce(target=target, tx=tx, ty=ty):
                        image = target.tile(tx, ty)
                        return _image_tile(image, image.rect())
                    return produce
                mask_tiles = add_image_tiles("group_mask", group_index,
                                             document.width, document.height,
                                             group_mask_tile, keys)
            groups.append({
                "id": group.id, "name": group.name, "layer_ids": list(group.layer_ids),
                "parent_id": group.parent_id, "visible": group.visible,
                "opacity": group.opacity, "blend_mode": group.blend_mode,
                "blend_parameters": _json_value(group.blend_parameters),
                "mask_tiles": mask_tiles,
                "mask_disabled": bool(getattr(group, "mask_disabled", False)),
            })

        background = document.background_color
        metadata = {
            "format_version": VERSION,
            "name": str(getattr(document, "name", "Sans titre")),
            "author": str(getattr(document, "author", "")),
            "width": document.width, "height": document.height, "dpi": document.dpi,
            "color_profile": _json_value(getattr(document, "color_profile", {"name": "sRGB", "icc": ""})),
            "active_layer": document.active_layer_index,
            "background": None if background is None else [
                background.red(), background.green(), background.blue(), background.alpha()],
            "layers": layers,
            "layer_groups": groups,
            "blend_presets": _json_value(document.blend_presets),
            "selection_tiles": selection,
            "saved_selections": saved_selections,
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
            direct = nebula_store_tiles_io(writer, document, metadata["chunks"], writing=True)
            if direct is False:
                raise OSError("CreativeCore a refusé les tuiles Nebula")
            for chunk_id, produce, width, height in (() if direct else sources):
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
            logger.error("Erreur sauvegarde Nebula : %s", error)
            return False

    @staticmethod
    def _validated_metadata(metadata, chunk_count):
        if not isinstance(metadata, dict):
            raise ValueError("Métadonnées Nebula invalides")
        version = int(metadata.get("format_version", VERSION))
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"Version de format Nebula non supportée: {version}; versions supportées: {sorted(SUPPORTED_VERSIONS)}")
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
        for entry in layers:
            state = entry.get("transform_state")
            if state is not None and (not isinstance(state, dict)
                                      or any(not _finite_number(value) for value in state.values())):
                raise ValueError("Transformée non destructive Nebula invalide")
            operations = entry.get("retouch_operations", [])
            if not isinstance(operations, list) or len(operations) > 100000:
                raise ValueError("Journal de retouche Nebula invalide")
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
        saved_selections = metadata.get("saved_selections", [])
        if (not isinstance(saved_selections, list) or len(saved_selections) > 256
                or any(not isinstance(item, dict)
                       or not isinstance(item.get("name"), str)
                       or not item["name"].strip()
                       or len(item["name"]) > 128
                       for item in saved_selections)):
            raise ValueError("Sélections enregistrées Nebula invalides")
        if "active_layer" in metadata:
            int(metadata["active_layer"])
        return width, height, dpi

    @staticmethod
    def _validated_chunk_records(metadata, chunk_count):
        """Return the native-validated tile index for Qt reconstruction."""
        return {int(record["id"]): record for record in metadata["chunks"]}

    @staticmethod
    def load(file_path: str | Path, *, visible_rect: QRect | None = None,
             lazy_tiles: bool = False) -> Document | None:
        reader = None
        try:
            file_path = Path(file_path)
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
            lazy = bool(lazy_tiles or visible_rect is not None)
            offsets = NebulaFormat._tile_offsets(file_path, len(encoded_metadata), chunk_count) if lazy else {}

            document = Document(width, height, dpi,
                                QColor(*metadata["background"]) if metadata.get("background") else None)
            document.name = str(metadata.get("name", "Sans titre"))
            document.author = str(metadata.get("author", ""))
            document.color_profile = dict(metadata.get("color_profile", {"name": "sRGB", "icc": ""}))
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
                color = entry.get("label_color")
                layer.label_color = str(color) if isinstance(color, str) and len(color) <= 16 else None
                layer.layer_kind = str(entry.get("layer_kind", "raster"))
                layer.adjustment = entry.get("adjustment")
                layer.layer_effects = list(entry.get("layer_effects", []))
                layer.psd_effects = list(entry.get("psd_effects", []))
                layer.retouch_operations = list(entry.get("retouch_operations", []))
                layer.transform_state = entry.get("transform_state")
            document.active_layer_index = max(0, min(
                int(metadata.get("active_layer", 0)), len(document.layers) - 1))
            document.blend_presets = metadata.get("blend_presets", {})

            # Groups must exist before tile decoding because group masks use
            # the same native tile stream as layers and selections.
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
                    group.mask_disabled = bool(entry.get("mask_disabled", False))
                    document.layer_groups.append(group)

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

            selection_image = None
            if metadata.get("selection_tiles"):
                selection_image = QImage(width, height, QImage.Format.Format_RGBA8888)
                if not fill_image_native(selection_image, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore a refusé l’initialisation de la sélection")
            saved_selection_images = []
            for entry in metadata.get("saved_selections", []):
                image = QImage(width, height, QImage.Format.Format_RGBA8888)
                if not fill_image_native(image, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore a refusé l’initialisation d’une sélection enregistrée")
                saved_selection_images.append(image)
            direct = None if lazy else nebula_store_tiles_io(reader, document, metadata["chunks"])
            if direct is False:
                raise ValueError("Tuiles Nebula tronquées ou invalides")
            seen_chunk_ids = set()
            for _ in range(0 if direct or lazy else chunk_count):
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
                elif role == "group_mask":
                    if not (0 <= owner < len(document.layer_groups)):
                        raise ValueError("Masque de groupe Nebula invalide")
                    document.layer_groups[owner].ensure_alpha_mask(width, height).set_tile(tx, ty, tile)
                elif role == "selection":
                    if not copy_image_rect_native(
                            tile, selection_image, QRect(0, 0, tw, th), tx * 64, ty * 64):
                        raise ValueError("CreativeCore ne peut pas restaurer le masque Nebula")
                elif role == "saved_selection":
                    if not (0 <= owner < len(saved_selection_images)):
                        raise ValueError("Sélection enregistrée Nebula invalide")
                    if not copy_image_rect_native(
                            tile, saved_selection_images[owner], QRect(0, 0, tw, th), tx * 64, ty * 64):
                        raise ValueError("CreativeCore ne peut pas restaurer une sélection enregistrée")
                else:
                    if not copy_image_rect_native(
                            tile, references[owner][1], QRect(0, 0, tw, th),
                            tx * 64, ty * 64):
                        raise ValueError("CreativeCore ne peut pas restaurer une référence Nebula")

            if metadata.get("selection_tiles"):
                document.selection.image = selection_image.convertToFormat(QImage.Format.Format_ARGB32)
                document.selection.invalidate()
            document.saved_selections = {
                entry["name"]: image.convertToFormat(QImage.Format.Format_ARGB32)
                for entry, image in zip(metadata.get("saved_selections", []), saved_selection_images)
            }
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
            if lazy:
                document._nebula_source_path = str(file_path)
                document._nebula_deferred_tiles = [
                    {"record": record, "offset": offsets[int(record["id"])]}
                    for record in metadata["chunks"]
                    if record["role"] in {"layer", "layer_mask"}
                ]
                if visible_rect is not None:
                    NebulaFormat.warm_tiles(document, visible_rect)
            return document
        except Exception as error:
            logger.error("Erreur ouverture Nebula : %s", error)
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
        if signature == b"8BPS":
            from DOCUMENTS.format_psd import PSDFormat
            return PSDFormat.load(file_path)
    except OSError:
        return None
    return None


__all__ = ["NebulaFormat", "load_document", "MAGIC", "VERSION", "FORMAT_ID", "SUPPORTED_VERSIONS"]
