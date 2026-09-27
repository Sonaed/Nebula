"""PSD import preserving editable raster-layer structure when possible."""
from __future__ import annotations

import logging
import os
import struct
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage

from DOCUMENTS.document import Document
from DOCUMENTS.layer_group import LayerGroup

logger = logging.getLogger(__name__)

# Four-byte Photoshop keys: do not strip the trailing spaces in ``mul `` etc.
PSD_BLEND_MODES = {
    "norm": "normal", "dark": "darken", "mul ": "multiply",
    "idiv": "color_burn", "lite": "lighten", "scrn": "screen",
    "div ": "color_dodge", "over": "overlay", "sLit": "soft_light",
    "hLit": "hard_light", "diff": "difference", "smud": "exclusion",
    "hue ": "hue", "sat ": "saturation", "colr": "color",
    "lum ": "luminosity", "lddg": "linear_dodge", "vLit": "vivid_light",
    "lLit": "linear_light", "pLit": "pin_light", "lbrn": "linear_burn",
    "hMix": "hard_mix", "dkCl": "darker_color", "lgCl": "lighter_color",
    "fsub": "subtract", "fdiv": "divide", "pass": "passthrough",
}
PSD_BLEND_FALLBACKS = {
    "linear_dodge": "screen", "vivid_light": "hard_light",
    "linear_light": "hard_light", "pin_light": "hard_light",
    "linear_burn": "multiply", "hard_mix": "hard_light",
    "darker_color": "darken", "lighter_color": "lighten",
    "subtract": "difference", "divide": "normal", "passthrough": "normal",
}


class PSDFormat:
    """Read PSDs safely; failures are reported, never silently flattened."""

    @staticmethod
    def load(file_path: str | Path) -> Document | None:
        try:
            return PSDFormat._load_layered(file_path)
        except ImportError as error:
            logger.info("psd-tools unavailable; trying flattened PSD import: %s", error)
        except Exception as error:
            logger.warning("Layered PSD import failed for %s: %s", file_path, error)
        image = QImage(str(file_path))
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            logger.error("PSD import failed: no readable fallback for %s", file_path)
            return None
        document = Document(image.width(), image.height(), 300, None)
        document.name = Path(file_path).stem
        document.layers.clear()
        layer = document.add_layer(Path(file_path).stem)
        layer.image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        document.psd_import_warning = "PSD importé aplati : psd-tools n'a pas pu lire les calques"
        return document

    @staticmethod
    def save(document: Document, file_path: str | Path) -> bool:
        """Write a valid 8-bit RGB PSD with editable raster layers.

        This first writer intentionally uses Photoshop's uncompressed channel
        form.  It is universally readable and, importantly, can be written
        atomically; PackBits compression can be added without changing the
        document model or the file structure.
        """
        width, height = int(document.width), int(document.height)
        if width <= 0 or height <= 0 or width > 30000 or height > 30000:
            return False
        destination = Path(file_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp",
                                                     dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                PSDFormat._write_header(stream, width, height)
                PSDFormat._write_image_resources(stream, document)
                PSDFormat._write_layer_and_mask_info(stream, document)
                from DOCUMENTS.blend_modes import composite_document
                composite = composite_document(document)
                PSDFormat._write_channel_image_data(stream, composite)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
            return True
        except Exception as error:
            logger.exception("PSD export failed for %s: %s", destination, error)
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            return False

    @staticmethod
    def _write_header(stream, width: int, height: int) -> None:
        stream.write(b"8BPS")
        stream.write(struct.pack(">H", 1))
        stream.write(b"\0" * 6)
        stream.write(struct.pack(">HIIHH", 3, height, width, 8, 3))
        stream.write(struct.pack(">I", 0))  # colour-mode data

    @staticmethod
    def _write_image_resources(stream, document: Document) -> None:
        """Persist an embedded ICC profile in Photoshop resource 1039."""
        profile = getattr(document, "color_profile", {}) or {}
        try:
            icc = bytes.fromhex(str(profile.get("icc", "")))
        except ValueError:
            icc = b""
        if not icc:
            stream.write(struct.pack(">I", 0))
            return
        resource = b"8BIM" + struct.pack(">H", 1039) + b"\0"
        resource += b"\0" * (len(resource) % 2)
        resource += struct.pack(">I", len(icc)) + icc + (b"\0" if len(icc) % 2 else b"")
        stream.write(struct.pack(">I", len(resource)))
        stream.write(resource)

    @staticmethod
    def _write_layer_and_mask_info(stream, document: Document) -> None:
        from io import BytesIO
        body = BytesIO()
        layers = list(reversed(document.layers))  # PSD is top-to-bottom.
        ordered = PSDFormat._export_layer_records(document, layers)
        body.write(struct.pack(">h", len(ordered)))
        records: list[tuple[object, QImage, tuple[int, ...], list[bytes]]] = []
        for kind, layer in ordered:
            if kind != "layer":
                PSDFormat._write_group_marker(body, layer, kind == "group_start")
                continue
            image = layer.tile_store.materialize().convertToFormat(QImage.Format.Format_RGBA8888)
            channels = PSDFormat._layer_channel_data(image)
            channel_ids = (0, 1, 2, -1)
            mask_store = getattr(layer, "alpha_mask_store", None)
            if mask_store is not None:
                mask = mask_store.materialize().convertToFormat(QImage.Format.Format_RGBA8888)
                channels.append(PSDFormat._layer_channel_data(mask)[3])
                channel_ids += (-2,)
            records.append((layer, image, channel_ids, channels))
            PSDFormat._write_layer_record(body, layer, image, channel_ids, channels)
        for _layer, _image, _channel_ids, channels in records:
            for channel in channels:
                body.write(channel)
        layer_info = body.getvalue()
        # PSD layer-and-mask section: layer-info length, layer-info payload,
        # global mask length.  Photoshop accepts an empty global mask.
        payload = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)
        stream.write(struct.pack(">I", len(payload)))
        stream.write(payload)

    @staticmethod
    def _export_layer_records(document, layers):
        """Expand Nebula root folders into Photoshop lsct start/end records."""
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
        starts: dict[int, list[object]] = {}
        ends: dict[int, list[object]] = {}
        for group in document.layer_groups:
            # A root group writes a complete PSD section. Nested groups are
            # preserved on import; exporting their marker nesting requires
            # the parent/child marker order Photoshop enforces, so keep the
            # parent section valid rather than emitting a corrupt PSD.
            if group.parent_id is not None or not group.layer_ids:
                continue
            indices = sorted(positions[item] for item in group.layer_ids if item in positions)
            if not indices or indices != list(range(indices[0], indices[-1] + 1)):
                continue
            starts.setdefault(indices[-1], []).append(group)  # end marker comes first in PSD order.
            ends.setdefault(indices[0], []).append(group)
        result = []
        for index in range(len(document.layers) - 1, -1, -1):
            for group in starts.get(index, ()):
                result.append(("group_end", group))
            result.append(("layer", document.layers[index]))
            for group in ends.get(index, ()):
                result.append(("group_start", group))
        return result

    @staticmethod
    def _write_group_marker(stream, group, opening: bool) -> None:
        name = str(getattr(group, "name", "Groupe") if opening else "</Layer group>")
        stream.write(struct.pack(">iiiiH", 0, 0, 0, 0, 0))
        mode = PSDFormat._psd_blend_key(str(getattr(group, "blend_mode", "normal"))) if opening else b"norm"
        stream.write(b"8BIM" + mode)
        opacity = round(max(0.0, min(1.0, float(getattr(group, "opacity", 1.0)))) * 255) if opening else 255
        visible = bool(getattr(group, "visible", True)) if opening else True
        stream.write(bytes((opacity, 0, 0 if visible else 0x02, 0)))
        extra = PSDFormat._layer_extra_data(name, 0, 0, False, 1 if opening else 3)
        stream.write(struct.pack(">I", len(extra)))
        stream.write(extra)

    @staticmethod
    def _write_layer_record(stream, layer, image: QImage, channel_ids: tuple[int, ...],
                            channels: list[bytes]) -> None:
        width, height = image.width(), image.height()
        stream.write(struct.pack(">iiiiH", 0, 0, height, width, len(channel_ids)))
        for channel_id, payload in zip(channel_ids, channels):
            stream.write(struct.pack(">hI", channel_id, len(payload)))
        mode = PSDFormat._psd_blend_key(str(getattr(layer, "blend_mode", "normal")))
        stream.write(b"8BIM" + mode)
        stream.write(bytes((round(max(0.0, min(1.0, float(layer.opacity))) * 255),
                            1 if bool(getattr(layer, "clipping", False)) else 0,
                            0 if bool(getattr(layer, "visible", True)) else 0x02, 0)))
        extra = PSDFormat._layer_extra_data(str(getattr(layer, "name", "Layer")),
                                             width, height, -2 in channel_ids)
        stream.write(struct.pack(">I", len(extra)))
        stream.write(extra)

    @staticmethod
    def _layer_extra_data(name: str, width: int, height: int, has_mask: bool = False,
                          section_type: int | None = None) -> bytes:
        # Mask descriptor, blending ranges, then Pascal name + Unicode luni name.
        latin = name.encode("macroman", "replace")[:255]
        pascal = bytes((len(latin),)) + latin
        pascal += b"\0" * ((4 - len(pascal) % 4) % 4)
        utf16 = name.encode("utf-16be")
        luni = b"8BIMluni" + struct.pack(">I", 4 + len(utf16)) + struct.pack(">I", len(name)) + utf16
        luni += b"\0" * ((4 - len(luni) % 4) % 4)
        mask = (struct.pack(">IiiiiBBH", 20, 0, 0, height, width, 255, 0, 0)
                if has_mask else struct.pack(">I", 0))
        section = b"" if section_type is None else b"8BIMlsct" + struct.pack(">I", 4) + struct.pack(">I", section_type)
        return mask + struct.pack(">I", 0) + pascal + luni + section

    @staticmethod
    def _channel_rows(image: QImage, include_alpha: bool = False) -> list[list[bytes]]:
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(rgba.constBits())
        channels = (0, 1, 2, 3) if include_alpha else (0, 1, 2)
        stride, width = rgba.bytesPerLine(), rgba.width()
        return [[raw[row * stride + channel:row * stride + channel + width * 4:4]
                 for row in range(rgba.height())] for channel in channels]

    @staticmethod
    def _packbits(row: bytes) -> bytes:
        """Encode one Photoshop PackBits scanline."""
        result = bytearray()
        index = 0
        while index < len(row):
            run = 1
            while index + run < len(row) and row[index + run] == row[index] and run < 128:
                run += 1
            if run >= 3:
                result.append((257 - run) & 0xFF)
                result.append(row[index])
                index += run
                continue
            start = index
            index += run
            while index < len(row):
                repeat = 1
                while index + repeat < len(row) and row[index + repeat] == row[index] and repeat < 128:
                    repeat += 1
                if repeat >= 3 or index - start >= 128:
                    break
                index += repeat
            literal = row[start:index]
            result.append(len(literal) - 1)
            result.extend(literal)
        return bytes(result)

    @staticmethod
    def _layer_channel_data(image: QImage) -> list[bytes]:
        payloads = []
        for rows in PSDFormat._channel_rows(image, include_alpha=True):
            packed = [PSDFormat._packbits(row) for row in rows]
            if any(len(row) > 0xFFFF for row in packed):
                raise ValueError("PSD RLE scanline exceeds v1 limit")
            payloads.append(struct.pack(">H", 1) + b"".join(struct.pack(">H", len(row)) for row in packed)
                            + b"".join(packed))
        return payloads

    @staticmethod
    def _write_channel_image_data(stream, image: QImage, include_alpha: bool = False) -> None:
        all_rows = PSDFormat._channel_rows(image, include_alpha)
        packed_rows = [[PSDFormat._packbits(row) for row in rows] for rows in all_rows]
        if any(len(row) > 0xFFFF for rows in packed_rows for row in rows):
            raise ValueError("PSD RLE scanline exceeds v1 limit")
        stream.write(struct.pack(">H", 1))
        for rows in packed_rows:
            for row in rows:
                stream.write(struct.pack(">H", len(row)))
        for rows in packed_rows:
            for row in rows:
                stream.write(row)

    @staticmethod
    def _psd_blend_key(mode: str) -> bytes:
        inverse = {value: key.encode("ascii") for key, value in PSD_BLEND_MODES.items()
                   if len(key) == 4 and value not in PSD_BLEND_FALLBACKS}
        return inverse.get(mode.lower(), b"norm")

    @staticmethod
    def _load_layered(file_path: str | Path) -> Document:
        from psd_tools import PSDImage

        psd = PSDImage.open(str(file_path))
        document = Document(int(psd.width), int(psd.height), 300, None)
        document.name = Path(file_path).stem
        document.layers.clear()
        warnings: list[str] = []
        PSDFormat._import_color_profile(document, psd, warnings)
        imported: dict[int, object] = {}
        # psd-tools order is top-to-bottom; Nebula stores the bottom layer at 0.
        sources = list(psd.descendants())
        for source in reversed(sources):
            if PSDFormat._is_group(source):
                continue
            try:
                PSDFormat._report_special_layer(source, warnings)
                # Preserve embedded ICC metadata separately.  Applying a bad
                # profile here must not make every raster layer disappear.
                pil = source.composite(apply_icc=False)
                if pil is None:
                    warnings.append(f"{PSDFormat._name(source)} : pixels indisponibles")
                    continue
                image = PSDFormat._pil_to_qimage(pil)
                left, top = PSDFormat._bounds(source)
                layer = document.add_layer(PSDFormat._name(source))
                # Direct RGBA -> sparse tiles: no transient PNG/zlib copy.
                layer.tile_store.write_image_at(image, left, top)
                layer.discard_image_cache()
                layer.opacity = max(0.0, min(1.0, float(getattr(source, "opacity", 255)) / 255.0))
                layer.visible = bool(getattr(source, "visible", True))
                layer.clipping = PSDFormat._clipping(source)
                layer.blend_mode = PSDFormat._blend_mode(source, warnings, layer.name)
                layer.psd_effects = PSDFormat._effects(source)
                PSDFormat._import_mask(layer, source, warnings)
                imported[id(source)] = layer
            except Exception as error:
                warnings.append(f"{PSDFormat._name(source)} : calque ignoré ({error})")
        PSDFormat._import_groups(document, sources, imported, warnings)
        if not document.layers:
            raise ValueError("PSD contains no raster layers")
        document.psd_import_warning = "\n".join(warnings)
        document.psd_import_report = {"layers": len(document.layers),
                                      "groups": len(document.layer_groups),
                                      "clipped_layers": sum(layer.clipping for layer in document.layers),
                                      "warnings": warnings}
        return document

    @staticmethod
    def _report_special_layer(source, warnings: list[str]) -> None:
        """Make Photoshop-only structures visible in the import report."""
        kind = type(source).__name__
        name = PSDFormat._name(source)
        if kind == "AdjustmentLayer":
            warnings.append(f"{name} : calque de réglage rasterisé (édition PSD non disponible)")
        elif kind == "SmartObjectLayer":
            warnings.append(f"{name} : objet dynamique rasterisé")
        elif kind in {"TypeLayer", "ShapeLayer", "FillLayer"}:
            warnings.append(f"{name} : {kind} rasterisé")

    @staticmethod
    def _import_color_profile(document, psd, warnings: list[str]) -> None:
        """Read Photoshop image resource 1039 without assuming psd-tools enums."""
        try:
            resources = getattr(psd, "image_resources", None)
            entry = resources.get(1039) if resources is not None else None
            data = bytes(getattr(entry, "data", b"")) if entry is not None else b""
            if data:
                from DOCUMENTS.color_management import ColorProfile
                document.set_color_profile(ColorProfile("Embedded PSD ICC", data))
        except Exception as error:
            warnings.append(f"Profil ICC ignoré ({error})")

    @staticmethod
    def _pil_to_qimage(pil) -> QImage:
        import numpy as np
        array = np.asarray(pil.convert("RGBA"), dtype=np.uint8)
        if array.ndim != 3 or array.shape[2] != 4:
            raise ValueError("pixels PSD non RGBA")
        # copy() transfers ownership before PIL/numpy are released.
        result = QImage(array.data, array.shape[1], array.shape[0], array.strides[0],
                        QImage.Format.Format_RGBA8888).copy()
        if result.isNull():
            raise ValueError("conversion pixels PSD impossible")
        return result

    @staticmethod
    def _is_group(source) -> bool:
        value = getattr(source, "is_group", False)
        return bool(value() if callable(value) else value)

    @staticmethod
    def _name(source) -> str:
        return str(getattr(source, "name", "PSD Layer") or "PSD Layer")

    @staticmethod
    def _bounds(source) -> tuple[int, int]:
        bbox = getattr(source, "bbox", None)
        try:
            return int(bbox[0]), int(bbox[1])
        except (TypeError, ValueError, IndexError):
            return int(getattr(source, "left", 0) or 0), int(getattr(source, "top", 0) or 0)

    @staticmethod
    def _clipping(source) -> bool:
        value = getattr(source, "clipping", getattr(source, "clip", False))
        return bool(value and value not in (0, "0", False))

    @staticmethod
    def _import_mask(layer, source, warnings: list[str]) -> None:
        """Import a raster layer mask at its own PSD bounds when available."""
        mask = getattr(source, "mask", None)
        if mask is None:
            return
        try:
            reader = getattr(mask, "topil", None)
            if not callable(reader):
                reader = getattr(mask, "composite", None)
            pil = reader() if callable(reader) else None
            if pil is None:
                warnings.append(f"{layer.name} : masque raster indisponible")
                return
            import numpy as np
            coverage = np.asarray(pil.convert("L"), dtype=np.uint8)
            rgba = np.zeros((coverage.shape[0], coverage.shape[1], 4), dtype=np.uint8)
            rgba[:, :, 3] = coverage
            image = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
                           QImage.Format.Format_RGBA8888).copy()
            left, top = PSDFormat._bounds(mask)
            layer.ensure_alpha_mask().write_image_at(image, left, top)
        except Exception as error:
            warnings.append(f"{layer.name} : masque ignoré ({error})")

    @staticmethod
    def _blend_mode(source, warnings: list[str], name: str) -> str:
        raw = getattr(source, "blend_mode", "norm")
        key = getattr(raw, "value", raw)
        if isinstance(key, bytes):
            key = key.decode("ascii", "replace")
        else:
            key = str(key)
        mode = PSD_BLEND_MODES.get(key)
        if mode is None:
            warnings.append(f"{name} : mode PSD inconnu {key!r}, normal utilisé")
            return "normal"
        fallback = PSD_BLEND_FALLBACKS.get(mode)
        if fallback:
            warnings.append(f"{name} : {mode} affiché comme {fallback}")
            return fallback
        return mode

    @staticmethod
    def _import_groups(document, sources, imported, warnings: list[str]) -> None:
        positions = {layer.id: index for index, layer in enumerate(document.layers)}
        groups_by_source: dict[int, LayerGroup] = {}
        for source in sources:
            if not PSDFormat._is_group(source):
                continue
            descendants = getattr(source, "descendants", None)
            leaves = list(descendants()) if callable(descendants) else []
            members = sorted({imported[id(item)].id for item in leaves if id(item) in imported},
                             key=positions.__getitem__)
            if not members:
                continue
            indices = [positions[item] for item in members]
            if indices != list(range(indices[0], indices[-1] + 1)):
                warnings.append(f"{PSDFormat._name(source)} : groupe non contigu ignoré")
                continue
            group = LayerGroup(
                name=PSDFormat._name(source), layer_ids=members,
                visible=bool(getattr(source, "visible", True)),
                opacity=max(0.0, min(1.0, float(getattr(source, "opacity", 255)) / 255.0)),
                blend_mode=PSDFormat._blend_mode(source, warnings, PSDFormat._name(source)))
            groups_by_source[id(source)] = group
            document.layer_groups.append(group)
        # psd-tools keeps a parent reference for nested LayerGroup objects.
        # Preserve it instead of flattening the hierarchy in the dock.
        for source in sources:
            group = groups_by_source.get(id(source))
            parent = groups_by_source.get(id(getattr(source, "parent", None)))
            if group is not None and parent is not None:
                group.parent_id = parent.id

    @staticmethod
    def _effects(layer) -> list[dict]:
        effects = getattr(layer, "effects", None)
        return [] if effects is None else [{"type": type(item).__name__, "enabled": True} for item in effects]


__all__ = ["PSDFormat", "PSD_BLEND_MODES"]
