import json
import math
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QSettings
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QImageReader

from DOCUMENTS.document import Document
from DOCUMENTS.layer import Layer
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.blend_modes import composite_document
from CORE.native_bridge import validate_document_geometry


class LayerData(TypedDict):
    id: str
    name: str
    visible: bool
    opacity: float
    image: str
    blend_mode: str
    locked: bool
    lock_alpha: bool
    clipping: bool


class DocumentData(TypedDict):
    format: str
    version: str
    width: int
    height: int
    dpi: int
    active_layer: int
    layers: list[LayerData]
    schema_version: int
    application_version: str
    selection: str | None
    modified_utc: str


class CSDFormat:

    VERSION: str = "0.3"
    SCHEMA_VERSION: int = 6
    MAX_DOCUMENT_DIMENSION: int = 100_000
    MAX_DOCUMENT_PIXELS: int = 64 * 1024 * 1024
    MAX_DECODED_LAYER_BYTES: int = 512 * 1024 * 1024
    MAX_IMAGE_ENTRY_BYTES: int = 256 * 1024 * 1024
    MAX_MANIFEST_BYTES: int = 64 * 1024 * 1024
    MAX_REFERENCE_IMAGES: int = 256
    MAX_REFERENCE_PIXELS: int = 64 * 1024 * 1024
    MAX_LAYER_GROUPS: int = 100_000

    @staticmethod
    def _finite_number(value) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _read_bounded_image(
        archive: zipfile.ZipFile,
        name: str,
        *,
        expected_size=None,
        max_pixels: int,
        already_allocated_pixels: int = 0,
        aggregate_pixel_limit: int | None = None,
    ) -> tuple[QImage, int]:
        """Inspect an image header before decoding its pixel allocation."""
        try:
            info = archive.getinfo(name)
        except KeyError as error:
            raise ValueError(f"Image CSD absente : {name}") from error
        if info.file_size > CSDFormat.MAX_IMAGE_ENTRY_BYTES:
            raise ValueError("Entrée image CSD trop volumineuse")
        encoded = archive.read(info)
        buffer = QBuffer()
        buffer.setData(QByteArray(encoded))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ValueError("Données image CSD illisibles")
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        size = reader.size()
        pixels = int(size.width()) * int(size.height())
        if (size.isEmpty() or pixels > max_pixels
                or (expected_size is not None and size != expected_size)
                or (aggregate_pixel_limit is not None
                    and already_allocated_pixels + pixels > aggregate_pixel_limit)):
            buffer.close()
            raise ValueError("Dimensions ou budget mémoire image CSD invalide")
        image = reader.read()
        buffer.close()
        if image.isNull() or image.size() != size:
            raise ValueError("Image CSD invalide ou tronquée")
        return image, pixels

    @staticmethod
    def _png_bytes(image: QImage) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError("Impossible d'ouvrir le buffer PNG")
        if not image.save(buffer, "PNG"):
            raise OSError("Impossible d'encoder l'image PNG")
        buffer.close()
        return bytes(data)

    @staticmethod
    def save(
        document: Document,
        file_path: str | Path,
    ) -> bool:

        try:

            file_path = Path(
                file_path
            )

            pixels = int(document.width) * int(document.height)
            geometry_valid = validate_document_geometry(
                document.width, document.height, document.dpi,
                CSDFormat.MAX_DOCUMENT_DIMENSION, CSDFormat.MAX_DOCUMENT_PIXELS)
            if geometry_valid is None:
                geometry_valid = (1 <= document.width <= CSDFormat.MAX_DOCUMENT_DIMENSION
                                  and 1 <= document.height <= CSDFormat.MAX_DOCUMENT_DIMENSION
                                  and 1 <= document.dpi <= 9600
                                  and pixels <= CSDFormat.MAX_DOCUMENT_PIXELS)
            if (not geometry_valid
                    or not document.layers or len(document.layers) > 100_000
                    or pixels * 4 * len(document.layers) > CSDFormat.MAX_DECODED_LAYER_BYTES):
                raise ValueError("Le document dépasse le budget raster CSD")
            if len(document.reference_images) > CSDFormat.MAX_REFERENCE_IMAGES:
                raise ValueError("Le document contient trop d’images de référence")
            if len(document.text_objects) > 100_000:
                raise ValueError("Le document contient trop d’objets texte")
            reference_pixels = sum(
                item.image.width() * item.image.height()
                for item in document.reference_images
            )
            if (any(item.image.isNull() for item in document.reference_images)
                    or reference_pixels > CSDFormat.MAX_REFERENCE_PIXELS):
                raise ValueError("Les images de référence dépassent le budget CSD")

            file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(prefix=f".{file_path.name}.", suffix=".tmp", dir=file_path.parent)
            os.close(fd)
            temporary_path = Path(temporary_name)
            compression = zipfile.ZIP_DEFLATED if QSettings(
                "CreativeSystem", "CreativeSystem"
            ).value("files/compress_documents", True, bool) else zipfile.ZIP_STORED
            with zipfile.ZipFile(
                temporary_path,
                "w",
                compression
            ) as archive:

                document_data: DocumentData = {
                    "format": "CreativeSystem Document",
                    "version": CSDFormat.VERSION,
                    "schema_version": CSDFormat.SCHEMA_VERSION,
                    "application_version": "0.3-dev",
                    "width": document.width,
                    "height": document.height,
                    "dpi": document.dpi,
                    "active_layer": (
                        document.active_layer_index
                    ),
                    "layers": [],
                    "blend_presets": document.blend_presets,
                    "layer_groups": [{
                        "id": group.id, "name": group.name, "parent_id": group.parent_id,
                        "layer_ids": list(group.layer_ids), "visible": group.visible,
                        "opacity": group.opacity, "blend_mode": group.blend_mode,
                        "blend_parameters": group.blend_parameters,
                    } for group in document.layer_groups],
                    "reference_images": [],
                    "text_objects": [],
                    "selection": None,
                    "modified_utc": datetime.now(timezone.utc).isoformat(),
                }

                for index, layer in enumerate(
                    document.layers
                ):

                    image_name = (
                        f"layers/layer_{index:03d}.png"
                    )

                    layer_data: LayerData = {
                        "id": layer.id,
                        "name": layer.name,
                        "visible": layer.visible,
                        "opacity": layer.opacity,
                        "image": image_name,
                        "blend_mode": layer.blend_mode,
                        "locked": layer.locked,
                        "lock_alpha": layer.lock_alpha,
                        "clipping": layer.clipping,
                        "blend_parameters": layer.blend_parameters,
                    }

                    document_data["layers"].append(
                        layer_data
                    )

                    archive.writestr(image_name, CSDFormat._png_bytes(layer.image))

                if not document.selection.is_empty():
                    selection_name = "selection/mask.png"
                    archive.writestr(
                        selection_name,
                        CSDFormat._png_bytes(document.selection.image),
                    )
                    document_data["selection"] = selection_name

                for index, reference in enumerate(document.reference_images):
                    image_name = f"references/reference_{index:03d}.png"
                    archive.writestr(image_name, CSDFormat._png_bytes(reference.image))
                    document_data["reference_images"].append({
                        "id": reference.id, "image": image_name,
                        "x": reference.position.x(), "y": reference.position.y(),
                        "scale": reference.scale, "opacity": reference.opacity,
                    })

                document_data["text_objects"] = [{
                    "id": item.id, "text": item.text,
                    "x": item.position.x(), "y": item.position.y(),
                    "color": [item.color.red(), item.color.green(), item.color.blue(), item.color.alpha()],
                    "font": item.font.toString(),
                } for item in document.text_objects]

                thumbnail = composite_document(document).scaled(
                    256, 256, aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                    mode=Qt.TransformationMode.SmoothTransformation,
                )
                archive.writestr("thumbnail.png", CSDFormat._png_bytes(thumbnail))

                json_data = json.dumps(
                    document_data,
                    indent=4,
                    ensure_ascii=False
                )
                if len(json_data.encode("utf-8")) > CSDFormat.MAX_MANIFEST_BYTES:
                    raise ValueError("Manifeste CSD trop volumineux")

                archive.writestr(
                    "document.json",
                    json_data
                )

            os.replace(temporary_path, file_path)
            return True

        except Exception as error:

            if "temporary_path" in locals():
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

            print(
                f"Erreur sauvegarde CSD : {error}"
            )

            return False

    @staticmethod
    def load(
        file_path: str | Path,
    ) -> Document | None:

        try:

            file_path = Path(
                file_path
            )

            with zipfile.ZipFile(
                file_path,
                "r"
            ) as archive:
                if len(archive.infolist()) > 1_000_000:
                    raise ValueError("Archive CSD contenant trop d’entrées")
                try:
                    manifest_info = archive.getinfo("document.json")
                except KeyError as error:
                    raise ValueError("Manifeste CSD absent") from error
                if manifest_info.file_size > CSDFormat.MAX_MANIFEST_BYTES:
                    raise ValueError("Manifeste CSD trop volumineux")
                json_data = archive.read(manifest_info)

                document_data = json.loads(
                    json_data.decode("utf-8")
                )
                if not isinstance(document_data, dict):
                    raise ValueError("Manifest CSD invalide")

                width: int = int(
                    document_data["width"]
                )

                height: int = int(
                    document_data["height"]
                )

                dpi: int = int(
                    document_data.get(
                        "dpi",
                        300
                    )
                )

                geometry_valid = validate_document_geometry(
                    width, height, dpi, CSDFormat.MAX_DOCUMENT_DIMENSION,
                    CSDFormat.MAX_DOCUMENT_PIXELS)
                if geometry_valid is None:
                    geometry_valid = (1 <= width <= CSDFormat.MAX_DOCUMENT_DIMENSION
                                      and 1 <= height <= CSDFormat.MAX_DOCUMENT_DIMENSION
                                      and 1 <= dpi <= 9600
                                      and width * height <= CSDFormat.MAX_DOCUMENT_PIXELS)
                if not geometry_valid:
                    raise ValueError("Dimensions ou DPI CSD invalides")

                active_layer: int = int(
                    document_data[
                        "active_layer"
                    ]
                )

                layer_entries = document_data.get("layers")
                if not isinstance(layer_entries, list) or not layer_entries:
                    raise ValueError("Le document CSD doit contenir au moins un calque")
                if (len(layer_entries) * width * height * 4
                        > CSDFormat.MAX_DECODED_LAYER_BYTES):
                    raise ValueError("Les pixels des calques dépassent le budget mémoire CSD")
                for layer_data in layer_entries:
                    if not isinstance(layer_data, dict) or not isinstance(layer_data.get("image"), str):
                        raise ValueError("Entrée de calque CSD invalide")
                    try:
                        image_info = archive.getinfo(layer_data["image"])
                    except KeyError as error:
                        raise ValueError("Image de calque CSD absente") from error
                    if image_info.file_size > min(
                            CSDFormat.MAX_IMAGE_ENTRY_BYTES,
                            width * height * 4 + 1024 * 1024):
                        raise ValueError("Image de calque CSD trop volumineuse")
                reference_entries = document_data.get("reference_images", [])
                if (not isinstance(reference_entries, list)
                        or len(reference_entries) > CSDFormat.MAX_REFERENCE_IMAGES):
                    raise ValueError("Liste d’images de référence CSD invalide")
                for entry in reference_entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("image"), str):
                        raise ValueError("Entrée d’image de référence CSD invalide")
                    if any(not CSDFormat._finite_number(entry.get(key, default))
                           for key, default in (("x", 0), ("y", 0),
                                                ("scale", 1), ("opacity", 0.8))):
                        raise ValueError("Transformée d’image de référence CSD invalide")
                    try:
                        reference_info = archive.getinfo(entry["image"])
                    except KeyError as error:
                        raise ValueError("Image de référence CSD absente") from error
                    if reference_info.file_size > CSDFormat.MAX_IMAGE_ENTRY_BYTES:
                        raise ValueError("Image de référence CSD trop volumineuse")
                text_entries = document_data.get("text_objects", [])
                if not isinstance(text_entries, list) or len(text_entries) > 100_000:
                    raise ValueError("Liste d’objets texte CSD invalide")
                for entry in text_entries:
                    color = entry.get("color", [0, 0, 0, 255]) if isinstance(entry, dict) else None
                    if (not isinstance(entry, dict)
                            or not CSDFormat._finite_number(entry.get("x", 0))
                            or not CSDFormat._finite_number(entry.get("y", 0))
                            or not isinstance(color, (list, tuple))
                            or len(color) not in (3, 4)):
                        raise ValueError("Objet texte CSD invalide")
                    if any(not CSDFormat._finite_number(value) for value in color):
                        raise ValueError("Couleur de texte CSD invalide")
                    try:
                        for value in color:
                            int(value)
                    except (TypeError, ValueError, OverflowError) as error:
                        raise ValueError("Couleur de texte CSD invalide") from error
                groups = document_data.get("layer_groups", [])
                if not isinstance(groups, list) or len(groups) > CSDFormat.MAX_LAYER_GROUPS:
                    raise ValueError("Liste de groupes CSD invalide")
                for entry in groups:
                    if (not isinstance(entry, dict)
                            or not isinstance(entry.get("layer_ids", []), list)
                            or not CSDFormat._finite_number(entry.get("opacity", 1.0))
                            or not isinstance(entry.get("blend_parameters", {}), dict)):
                        raise ValueError("Métadonnées de groupe CSD invalides")
                selection_name = document_data.get("selection")
                if selection_name:
                    if not isinstance(selection_name, str):
                        raise ValueError("Nom du masque de sélection CSD invalide")
                    try:
                        selection_info = archive.getinfo(selection_name)
                    except KeyError as error:
                        raise ValueError("Masque de sélection CSD absent") from error
                    if selection_info.file_size > min(
                            CSDFormat.MAX_IMAGE_ENTRY_BYTES,
                            width * height * 4 + 1024 * 1024):
                        raise ValueError("Masque de sélection CSD trop volumineux")
                document = Document(
                    width,
                    height,
                    dpi
                )

                document.layers.clear()

                for layer_data in layer_entries:

                    if not isinstance(layer_data, dict):
                        raise ValueError("Entrée de calque CSD invalide")

                    image, _pixels = CSDFormat._read_bounded_image(
                        archive, layer_data["image"],
                        expected_size=QSize(width, height),
                        max_pixels=CSDFormat.MAX_DOCUMENT_PIXELS,
                    )

                    layer: Layer = (
                        document.add_layer(
                            str(
                                layer_data["name"]
                            )
                        )
                    )

                    layer.image = image

                    layer.id = str(layer_data.get("id", layer.id))

                    layer.visible = layer_data.get("visible") is not False

                    try:
                        opacity = float(layer_data.get("opacity", 1.0))
                    except (TypeError, ValueError):
                        opacity = 1.0
                    layer.opacity = max(0.0, min(1.0, opacity)) if math.isfinite(opacity) else 1.0

                    layer.blend_mode = str(layer_data.get("blend_mode", "normal"))
                    layer.locked = bool(layer_data.get("locked", False))
                    layer.lock_alpha = bool(layer_data.get("lock_alpha", False))
                    layer.clipping = bool(layer_data.get("clipping", False))
                    parameters = layer_data.get("blend_parameters", {})
                    if isinstance(parameters, dict):
                        layer.blend_parameters = {
                            str(key): float(value)
                            for key, value in parameters.items()
                            if isinstance(value, (int, float)) and math.isfinite(float(value))
                        }

                document.active_layer_index = (
                    max(0, min(active_layer, len(document.layers) - 1))
                )
                from DOCUMENTS.layer_group import LayerGroup
                layer_ids = {layer.id for layer in document.layers}
                for entry in document_data.get("layer_groups", []):
                    if not isinstance(entry, dict):
                        continue
                    members = [str(layer_id) for layer_id in entry.get("layer_ids", [])
                               if str(layer_id) in layer_ids]
                    indices = [next(i for i, layer in enumerate(document.layers)
                                    if layer.id == layer_id) for layer_id in members]
                    if not members or indices != list(range(min(indices), max(indices) + 1)):
                        continue
                    group = LayerGroup(
                        name=str(entry.get("name", "Groupe")),
                        id=str(entry.get("id") or LayerGroup().id),
                        layer_ids=members,
                        visible=entry.get("visible") is not False,
                        opacity=max(0.0, min(1.0, float(entry.get("opacity", 1.0)))),
                        blend_mode=str(entry.get("blend_mode", "normal")),
                    )
                    parent_id = entry.get("parent_id")
                    group.parent_id = str(parent_id) if parent_id else None
                    params = entry.get("blend_parameters", {})
                    if isinstance(params, dict):
                        group.blend_parameters = {
                            str(key): float(value) for key, value in params.items()
                            if isinstance(value, (int, float)) and math.isfinite(float(value))
                        }
                    document.layer_groups.append(group)
                groups_by_id = {group.id: group for group in document.layer_groups}
                if len(groups_by_id) != len(document.layer_groups):
                    raise ValueError("Identifiants de groupes CSD dupliqués")
                for group in document.layer_groups:
                    if group.parent_id is not None:
                        parent = groups_by_id.get(group.parent_id)
                        if parent is None or not set(group.layer_ids).issubset(parent.layer_ids):
                            raise ValueError("Hiérarchie de groupes CSD invalide")
                    elif any(group is not other and other.parent_id is None
                             and set(group.layer_ids).intersection(other.layer_ids)
                             for other in document.layer_groups):
                        raise ValueError("Groupes racine CSD chevauchants")
                presets = document_data.get("blend_presets", {})
                if isinstance(presets, dict):
                    document.blend_presets = presets

                selection_name = document_data.get("selection")
                if selection_name and selection_name in archive.namelist():
                    selection, _pixels = CSDFormat._read_bounded_image(
                        archive, selection_name,
                        expected_size=QSize(width, height),
                        max_pixels=CSDFormat.MAX_DOCUMENT_PIXELS,
                    )
                    document.selection.image = selection.convertToFormat(
                        QImage.Format.Format_ARGB32
                    )
                    document.selection.invalidate()

                reference_pixels = 0
                for item in reference_entries:
                    if not isinstance(item, dict) or not isinstance(item.get("image"), str):
                        raise ValueError("Entrée d’image de référence CSD invalide")
                    image_name = item.get("image")
                    if image_name not in archive.namelist():
                        raise ValueError("Image de référence CSD absente")
                    reference_image, pixels = CSDFormat._read_bounded_image(
                        archive, image_name,
                        max_pixels=CSDFormat.MAX_REFERENCE_PIXELS,
                        already_allocated_pixels=reference_pixels,
                        aggregate_pixel_limit=CSDFormat.MAX_REFERENCE_PIXELS,
                    )
                    reference_pixels += pixels
                    document.reference_images.append(ReferenceImage(
                        reference_image, QPointF(float(item.get("x", 0)), float(item.get("y", 0))),
                        max(0.01, min(100.0, float(item.get("scale", 1.0)))),
                        max(0.0, min(1.0, float(item.get("opacity", 0.8)))),
                        str(item.get("id") or ReferenceImage(reference_image).id),
                    ))

                for item in document_data.get("text_objects", []):
                    color = item.get("color", [0, 0, 0, 255])
                    font = QFont()
                    font.fromString(str(item.get("font", "")))
                    if font.pointSizeF() <= 0:
                        font = QFont("Sans Serif", 24)
                    document.text_objects.append(EditableText(
                        str(item.get("text", "")),
                        QPointF(float(item.get("x", 0)), float(item.get("y", 0))),
                        QColor(*[max(0, min(255, int(value))) for value in color[:4]]),
                        font,
                        str(item.get("id") or EditableText("", QPointF()).id),
                    ))

                document.sync_native_state()
                return document

        except Exception as error:

            print(
                f"Erreur ouverture CSD : {error}"
            )

            return None
