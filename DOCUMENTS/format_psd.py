"""PSD import preserving editable raster-layer structure when possible."""
from __future__ import annotations

import logging
import os
import struct
import tempfile
import shutil
import zlib
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


class PSDImportCancelled(RuntimeError):
    """The caller requested that an in-progress PSD import stop safely."""


class PSDFormat:
    """Read PSDs safely; failures are reported, never silently flattened."""

    @staticmethod
    def export_report(document) -> dict:
        """Describe PSD features that this writer cannot preserve as editable.

        The report is deliberately attached to the document by ``save`` so
        callers can show it next to the exported file instead of silently
        degrading Photoshop-only structure.
        """
        warnings = []
        adjustments = sum(getattr(layer, "layer_kind", "raster") == "adjustment"
                          and not PSDFormat._exports_adjustment(layer)
                          for layer in document.layers)
        if adjustments:
            warnings.append(f"{adjustments} calque(s) de réglage exporté(s) aplati(s)")
        nested_groups = sum(getattr(group, "parent_id", None) is not None
                            for group in document.layer_groups)
        if nested_groups:
            warnings.append(f"{nested_groups} groupe(s) imbriqué(s) exporté(s) sans hiérarchie")
        effects = sum(bool(getattr(layer, "layer_effects", ()) or
                           getattr(layer, "psd_effects", ()))
                      for layer in document.layers)
        if effects:
            warnings.append(f"Effets de calque de {effects} calque(s) non exportés")
        if document.text_objects:
            warnings.append(f"{len(document.text_objects)} objet(s) texte aplati(s) dans le composite")
        return {"layers": len(document.layers), "groups": len(document.layer_groups),
                "warnings": warnings}

    @staticmethod
    def _exports_adjustment(layer) -> bool:
        spec = getattr(layer, "adjustment", None) or {}
        return str(spec.get("kind", "")) == "curves" and isinstance(spec.get("curves"), dict)

    @staticmethod
    def load(file_path: str | Path, progress=None, cancel=None, viewport=None) -> Document | None:
        # 1. Nebula's own reader (no dependency, adjustment layers included).
        try:
            PSDFormat._raise_if_cancelled(cancel)
            return PSDFormat._load_native(file_path, progress=progress, cancel=cancel, viewport=viewport)
        except PSDImportCancelled:
            # Never reinterpret a deliberate cancellation as a decoder fault
            # and fall through to a slower or flattened import path.
            raise
        except Exception as error:  # noqa: BLE001 - any failure falls back below
            logger.warning("Lecteur PSD Nebula : %s (%s)", error, file_path)
            native_error = error
        # 2. psd-tools, when installed (exotic colour modes).
        try:
            PSDFormat._raise_if_cancelled(cancel)
            document = PSDFormat._load_layered(file_path)
            document.psd_import_warning = "\n".join(filter(None, [
                f"Lecteur Nebula : {native_error}", getattr(document, "psd_import_warning", "")]))
            return document
        except PSDImportCancelled:
            raise
        except ImportError as error:
            logger.info("psd-tools unavailable; trying flattened PSD import: %s", error)
        except Exception as error:
            logger.warning("Layered PSD import failed for %s: %s", file_path, error)
        # 3. Flattened image through Qt's image plugins.
        PSDFormat._raise_if_cancelled(cancel)
        image = QImage(str(file_path))
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            logger.error("PSD import failed: no readable fallback for %s", file_path)
            return None
        document = Document(image.width(), image.height(), 300, None)
        document.name = Path(file_path).stem
        layer = document.layers[0]
        layer.name = Path(file_path).stem
        layer.image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        document.psd_import_warning = f"PSD importé aplati : {native_error}"
        return document

    # ------------------------------------------------------------------
    # Native reader -> Nebula document
    # ------------------------------------------------------------------

    @staticmethod
    def _load_native(file_path: str | Path, progress=None, cancel=None, viewport=None) -> Document:
        from DOCUMENTS.psd_reader import read_psd

        with read_psd(file_path, composite=False, lazy_layers=True) as psd:
            if psd.layers:
                return PSDFormat._import_native_document(psd, file_path, progress, cancel, viewport)
        with read_psd(file_path, composite=True) as psd:
            if psd.composite is None:
                raise ValueError("PSD sans calque ni image composite")
            return PSDFormat._import_native_document(psd, file_path, progress, cancel, viewport)

    @staticmethod
    def _import_native_document(psd, file_path, progress=None, cancel=None, viewport=None):
        PSDFormat._raise_if_cancelled(cancel)
        document = Document(int(psd.width), int(psd.height), 300, None)
        document.name = Path(file_path).stem
        document.layers.clear()
        warnings: list[str] = list(psd.warnings)
        if psd.icc_profile:
            try:
                from DOCUMENTS.color_management import ColorProfile
                document.set_color_profile(ColorProfile("Embedded PSD ICC", psd.icc_profile))
            except Exception as error:  # noqa: BLE001
                warnings.append(f"Profil ICC ignoré ({error})")
        if not psd.layers:
            layer = document.add_layer(Path(file_path).stem)
            PSDFormat._write_pixels(layer, psd.composite, 0, 0, document)
            groups = []
        else:
            groups = []
            deferred = []
            PSDFormat._import_children(document, psd.root, None, groups, warnings, progress, cancel,
                                       deferred, viewport)
            # Keep layer order stable by creating hidden-layer placeholders in
            # their original slots, then spend decode time on them only after
            # every visible layer has been transferred to Nebula tiles.
            for source, layer in deferred:
                PSDFormat._raise_if_cancelled(cancel)
                try:
                    source.decode_pixels()
                    if source.rgba is not None and source.rgba.size:
                        PSDFormat._write_pixels(layer, source.rgba, source.left, source.top, document)
                    PSDFormat._write_mask(layer, source, document, (source.left, source.top,
                                                                     source.right, source.bottom))
                    if source.effects:
                        layer.psd_effects = list(source.effects)
                except Exception as error:  # noqa: BLE001
                    warnings.append(f"{source.name} : calque masqué ignoré ({error})")
                finally:
                    source.release_pixels()
                if progress is not None:
                    progress(layer, document)
        # Children-first order: CreativeCore's structural mirror accepts a
        # folder enclosing already-created folders (see createEnclosingGroup).
        document.layer_groups.extend(groups)
        if not document.layers:
            raise ValueError("PSD sans calque importable")
        document.active_layer_index = len(document.layers) - 1
        try:
            document.sync_native_state()
        except RuntimeError as error:
            warnings.append(f"Structure des dossiers simplifiée pour CreativeCore ({error})")
            PSDFormat._flatten_group_nesting(document)
            document.sync_native_state()
        adjustments = [layer for layer in document.layers if layer.layer_kind == "adjustment"]
        if adjustments:
            try:
                from CORE.native_filters import load_filters
                filters = load_filters()
                if filters is None or not getattr(filters, "supports_psd_adjustments", False):
                    warnings.insert(0, "Recompilez CreativeCore (cmake --build) : les calques de "
                                       "réglage Photoshop ne s'afficheront pas avant.")
            except Exception:  # noqa: BLE001
                pass
        document.psd_import_warning = "\n".join(dict.fromkeys(warnings))
        document.psd_import_report = {
            "layers": len(document.layers), "groups": len(document.layer_groups),
            "adjustments": len(adjustments),
            "clipped_layers": sum(bool(layer.clipping) for layer in document.layers),
            "masks": sum(layer.alpha_mask_store is not None for layer in document.layers),
            "warnings": list(dict.fromkeys(warnings))}
        return document

    @staticmethod
    def _flatten_group_nesting(document) -> None:
        """Last resort for a structure the native mirror refuses: keep root folders."""
        by_id = {group.id: group for group in document.layer_groups}
        document.layer_groups[:] = [group for group in document.layer_groups
                                    if group.parent_id is None or group.parent_id not in by_id]
        for group in document.layer_groups:
            group.parent_id = None

    @staticmethod
    def _import_children(document, children, parent_group, groups, warnings, progress=None,
                         cancel=None, deferred=None, viewport=None) -> list[str]:
        """Create layers bottom-to-top; return the ids of the leaf layers created."""
        leaf_ids: list[str] = []
        # ``psd_reader`` normalizes sibling lists to bottom-to-top order.
        # Nebula uses the same convention (index zero is the bottom layer),
        # so do not reverse here: reversing caused backgrounds to cover the
        # artwork after import.
        for source in children:
            PSDFormat._raise_if_cancelled(cancel)
            if source.is_group:
                start = len(groups)
                members = PSDFormat._import_children(document, source.children, source, groups,
                                                     warnings, progress, cancel, deferred, viewport)
                if not members:
                    continue            # empty Photoshop folder: nothing to show
                blend = PSDFormat._blend_from_key(source.effective_blend_key, source.name, warnings,
                                                  group=True)
                group = LayerGroup(name=source.name or "Groupe", layer_ids=list(members),
                                   visible=source.visible,
                                   opacity=PSDFormat._opacity(source),
                                   blend_mode=blend)
                for child in groups[start:]:
                    if child.parent_id is None:
                        child.parent_id = group.id
                groups.append(group)
                if source.mask is not None and not source.mask.disabled and (
                        source.mask.data is not None and source.mask.data.size
                        and int(source.mask.data.min()) < 255 or source.mask.default_color < 255):
                    warnings.append(f"{source.name} : masque de dossier ignoré")
                if source.clipping:
                    warnings.append(f"{source.name} : dossier écrêté, écrêtage ignoré")
                leaf_ids.extend(members)
                continue
            try:
                if (PSDFormat._defer_raster_layer(source, viewport)
                        and source.adjustment is None and source.fill is None
                        and deferred is not None):
                    layer = document.add_layer(source.name or "Calque")
                    PSDFormat._apply_common(layer, source, warnings)
                    layer.psd_unsupported = list(source.unsupported)
                    deferred.append((source, layer))
                    leaf_ids.append(layer.id)
                    continue
                source.decode_pixels()
                PSDFormat._raise_if_cancelled(cancel)
                layer = PSDFormat._import_leaf(document, source, warnings)
            except Exception as error:  # noqa: BLE001 - keep the rest of the file
                warnings.append(f"{source.name} : calque ignoré ({error})")
                continue
            finally:
                source.release_pixels()
            if layer is not None:
                leaf_ids.append(layer.id)
                if progress is not None:
                    progress(layer, document)
        return leaf_ids

    @staticmethod
    def _raise_if_cancelled(cancel) -> None:
        if cancel is not None and cancel.is_set():
            raise PSDImportCancelled("Import PSD annulé")

    @staticmethod
    def _defer_raster_layer(source, viewport) -> bool:
        """Whether a raster source can wait without changing document order."""
        if source.hidden:
            return True
        if viewport is None:
            return False
        vx, vy, vw, vh = (int(value) for value in viewport)
        return (source.right <= vx or source.bottom <= vy
                or source.left >= vx + max(0, vw) or source.top >= vy + max(0, vh))

    @staticmethod
    def _opacity(source) -> float:
        return max(0.0, min(1.0, (source.opacity / 255.0) * (source.fill_opacity / 255.0)))

    @staticmethod
    def _import_leaf(document, source, warnings):
        name = source.name or "Calque"
        limitations = list(source.unsupported)
        for message in source.unsupported:
            warnings.append(f"{name} : {message}")
        if source.adjustment is not None:
            spec = dict(source.adjustment)
            kind = str(spec.get("kind", ""))
            layer = document.add_adjustment_layer(kind, name, spec)
            if kind == "unsupported":
                message = f"{spec.get('reason', 'réglage non pris en charge')}, conservé sans effet"
                warnings.append(f"{name} : {message}")
                limitations.append(message)
            elif spec.get("colorize"):
                message = "option « Redéfinir » de Teinte/Saturation ignorée"
                warnings.append(f"{name} : {message}")
                limitations.append(message)
            full = (0, 0, document.width, document.height)
            PSDFormat._apply_common(layer, source, warnings, limitations)
            PSDFormat._write_mask(layer, source, document, full)
            layer.psd_unsupported = list(dict.fromkeys(limitations))
            return layer
        layer = document.add_layer(name)
        rgba = source.rgba
        if source.fill is not None and source.fill.get("kind") == "solid_color" and (
                rgba is None or not rgba.size or int(rgba[..., 3].max()) == 0):
            import numpy as np
            color = source.fill.get("color", [0, 0, 0])
            rgba = np.empty((document.height, document.width, 4), dtype=np.uint8)
            rgba[..., :3] = color[:3]
            rgba[..., 3] = 255
            left, top = 0, 0
        else:
            left, top = source.left, source.top
            if source.fill is not None and source.fill.get("kind") != "solid_color":
                message = "calque de remplissage importé en pixels"
                warnings.append(f"{name} : {message}")
                limitations.append(message)
        content = (0, 0, 0, 0)
        if rgba is not None and rgba.size:
            content = PSDFormat._write_pixels(layer, rgba, left, top, document)
        PSDFormat._apply_common(layer, source, warnings, limitations)
        PSDFormat._write_mask(layer, source, document, content)
        if source.effects:
            layer.psd_effects = list(source.effects)
            limitations.append("effets de calque conservés sans garantie de rendu")
        layer.psd_unsupported = list(dict.fromkeys(limitations))
        return layer

    @staticmethod
    def _apply_common(layer, source, warnings, limitations=None) -> None:
        layer.opacity = PSDFormat._opacity(source)
        layer.visible = source.visible
        layer.clipping = bool(source.clipping)
        layer.lock_alpha = bool(source.transparency_locked) and layer.layer_kind == "raster"
        layer.label_color = source.label_color
        layer.blend_mode = PSDFormat._blend_from_key(source.blend_key, layer.name, warnings, limitations)
        layer.psd_fill_opacity = source.fill_opacity / 255.0

    @staticmethod
    def _blend_from_key(key: str, name: str, warnings: list[str], limitations=None,
                        group: bool = False) -> str:
        mode = PSD_BLEND_MODES.get(str(key))
        if mode is None:
            message = f"mode PSD inconnu {key!r}, normal utilisé"
            warnings.append(f"{name} : {message}")
            if limitations is not None:
                limitations.append(message)
            return "normal"
        if mode == "passthrough":
            # Nebula folders are isolated; for folders holding normal layers,
            # clipping sets and clipped adjustments the result is the same.
            return "normal"
        fallback = PSD_BLEND_FALLBACKS.get(mode)
        if fallback:
            message = f"{mode} affiché comme {fallback}"
            warnings.append(f"{name} : {message}")
            if limitations is not None:
                limitations.append(message)
            return fallback
        return mode

    @staticmethod
    def _tile_region(document, left, top, right, bottom, tile):
        left, top = max(0, left), max(0, top)
        right, bottom = min(document.width, right), min(document.height, bottom)
        if right <= left or bottom <= top:
            return None
        tx0, ty0 = left // tile, top // tile
        tx1, ty1 = (right - 1) // tile, (bottom - 1) // tile
        return tx0, ty0, tx1, ty1

    @staticmethod
    def _store_tiles(store, canvas, origin_x, origin_y, region, document, skip_empty=True):
        """Cut a BGRA numpy canvas (aligned on ``origin``) into exact-size tiles."""
        tile = store.tile_size
        tx0, ty0, tx1, ty1 = region
        writes, keepalive = [], []
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                x0, y0 = tx * tile, ty * tile
                w = min(tile, document.width - x0)
                h = min(tile, document.height - y0)
                block = canvas[y0 - origin_y:y0 - origin_y + h, x0 - origin_x:x0 - origin_x + w]
                if skip_empty and not block.any():
                    continue
                block = PSDFormat._contiguous(block)
                image = QImage(block.data, w, h, w * 4, QImage.Format.Format_ARGB32)
                keepalive.append(block)
                writes.append((tx, ty, image))
                if len(writes) >= 512:
                    if not store.set_tiles_batch(writes):
                        raise RuntimeError("CreativeCore a refusé l'écriture des tuiles PSD")
                    writes, keepalive = [], []
        if writes and not store.set_tiles_batch(writes):
            raise RuntimeError("CreativeCore a refusé l'écriture des tuiles PSD")

    @staticmethod
    def _contiguous(block):
        import numpy as np
        return np.ascontiguousarray(block)

    @staticmethod
    def _write_pixels(layer, rgba, left, top, document) -> tuple[int, int, int, int]:
        """Write straight-alpha RGBA pixels; returns the written document bounds."""
        import numpy as np
        height, width = rgba.shape[:2]
        if left == 0 and top == 0 and (width, height) == (document.width, document.height):
            # The native writer already splits full-canvas images into owned
            # tiles. Avoid hundreds of thousands of Python/QImage wrappers.
            pixels = np.ascontiguousarray(rgba)
            transparent = pixels[..., 3] == 0
            if transparent.any():
                if not pixels.flags.writeable:
                    pixels = pixels.copy()
                pixels[transparent] = 0
            image = QImage(pixels.data, width, height, width * 4,
                           QImage.Format.Format_RGBA8888)
            changed = layer.tile_store.write_image(image)
            expected = ((width + layer.tile_store.tile_size - 1) // layer.tile_store.tile_size
                        * ((height + layer.tile_store.tile_size - 1) // layer.tile_store.tile_size))
            if len(changed) != expected:
                raise RuntimeError("CreativeCore a refusé l'écriture du calque PSD")
            layer.discard_image_cache()
            return (0, 0, width, height)
        tile = layer.tile_store.tile_size
        region = PSDFormat._tile_region(document, left, top, left + width, top + height, tile)
        if region is None:
            return (0, 0, 0, 0)
        tx0, ty0, tx1, ty1 = region
        origin_x = tx0 * tile
        dx0, dy0 = max(left, 0), max(top, 0)
        dx1, dy1 = min(left + width, document.width), min(top + height, document.height)
        # Convert one tile row at a time. An 8K layer needs ~2 MB of staging
        # memory instead of another full 256 MB BGRA canvas.
        for ty in range(ty0, ty1 + 1):
            origin_y = ty * tile
            y0, y1 = max(dy0, origin_y), min(dy1, origin_y + tile)
            canvas = np.zeros((tile, (tx1 - tx0 + 1) * tile, 4), dtype=np.uint8)
            source = rgba[y0 - top:y1 - top, dx0 - left:dx1 - left]
            target = canvas[y0 - origin_y:y1 - origin_y, dx0 - origin_x:dx1 - origin_x]
            target[..., 0] = source[..., 2]  # ARGB32 bytes: B, G, R, A
            target[..., 1] = source[..., 1]
            target[..., 2] = source[..., 0]
            target[..., 3] = source[..., 3]
            target[source[..., 3] == 0] = 0
            PSDFormat._store_tiles(layer.tile_store, canvas, origin_x, origin_y,
                                   (tx0, ty, tx1, ty), document)
        layer.discard_image_cache()
        return (dx0, dy0, dx1, dy1)

    @staticmethod
    def _write_mask(layer, source, document, content) -> None:
        """Photoshop pixel mask -> Nebula sparse mask (absent tile = revealed).

        Mask tiles store white RGB with the coverage in alpha, so a fully
        hiding tile is never mistaken for an absent (fully revealing) one.
        """
        import numpy as np
        mask = source.mask
        if mask is None:
            return
        default = int(mask.default_color)
        data = mask.data
        if mask.invert:
            default = 255 - default
            data = None if data is None else 255 - data
        has_data = data is not None and data.size and mask.width > 0 and mask.height > 0
        if default == 255 and (not has_data or int(data.min()) == 255):
            return                                  # reveals everything: no mask needed
        if default == 255:
            bounds = (mask.left, mask.top, mask.right, mask.bottom)
        else:
            boxes = [box for box in (content, (mask.left, mask.top, mask.right, mask.bottom))
                     if box[2] > box[0] and box[3] > box[1]]
            if not boxes:
                boxes = [(0, 0, document.width, document.height)]
            bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                      max(b[2] for b in boxes), max(b[3] for b in boxes))
        store = layer.ensure_alpha_mask()
        tile = store.tile_size
        region = PSDFormat._tile_region(document, *bounds, tile)
        layer.mask_disabled = bool(mask.disabled)
        if region is None:
            return
        tx0, ty0, tx1, ty1 = region
        origin_x, origin_y = tx0 * tile, ty0 * tile
        canvas = np.empty(((ty1 - ty0 + 1) * tile, (tx1 - tx0 + 1) * tile, 4), dtype=np.uint8)
        canvas[..., :3] = 255
        canvas[..., 3] = default
        if has_data:
            dx0, dy0 = max(mask.left, origin_x), max(mask.top, origin_y)
            dx1 = min(mask.right, origin_x + canvas.shape[1], document.width)
            dy1 = min(mask.bottom, origin_y + canvas.shape[0], document.height)
            if dx1 > dx0 and dy1 > dy0:
                canvas[dy0 - origin_y:dy1 - origin_y, dx0 - origin_x:dx1 - origin_x, 3] = \
                    data[dy0 - mask.top:dy1 - mask.top, dx0 - mask.left:dx1 - mask.left]
        PSDFormat._store_tiles(store, canvas, origin_x, origin_y, region, document,
                               skip_empty=False)

    @staticmethod
    def save(document: Document, file_path: str | Path) -> bool:
        """Atomically write ZIP-compressed editable raster PSD/PSB layers."""
        document.psd_export_report = PSDFormat.export_report(document)
        width, height = int(document.width), int(document.height)
        destination = Path(file_path)
        version = 2 if destination.suffix.lower() == ".psb" else 1
        maximum = 300000 if version == 2 else 30000
        if width <= 0 or height <= 0 or width > maximum or height > maximum:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp",
                                                     dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                PSDFormat._write_header(stream, width, height, version)
                PSDFormat._write_image_resources(stream, document)
                PSDFormat._write_layer_and_mask_info(stream, document, version)
                composite = PSDFormat._export_composite(document)
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
    def _write_header(stream, width: int, height: int, version: int = 1) -> None:
        stream.write(b"8BPS")
        stream.write(struct.pack(">H", version))
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
    def _export_composite(document):
        from DOCUMENTS.blend_modes import composite_document, composite_document_layers
        if document.width * document.height * len(document.layers) <= 16_000_000:
            return composite_document(document)
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter
        from CORE.native_bridge import draw_text_native
        image = QImage(document.width, document.height, QImage.Format.Format_RGBA8888)
        if image.isNull():
            raise MemoryError("Impossible de créer le composite PSD")
        image.fill(0)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        try:
            for y in range(0, document.height, 64):
                for x in range(0, document.width, 64):
                    rect = QRect(x, y, min(64, document.width - x), min(64, document.height - y))
                    painter.drawImage(x, y, composite_document_layers(document, rect))
        finally:
            painter.end()
        for item in document.text_objects:
            if not draw_text_native(image, item.text, item.font,
                                    item.position.x(), item.position.y(), item.color):
                raise RuntimeError("CreativeCore a refusé le texte du composite PSD")
        return image

    @staticmethod
    def _write_layer_and_mask_info(stream, document: Document, version: int = 1) -> None:
        ordered = PSDFormat._export_layer_records(document, list(document.layers))
        if len(ordered) > 32767:
            raise ValueError("Trop de calques pour le format Photoshop")
        size_format = ">Q" if version == 2 else ">I"
        size_bytes = 8 if version == 2 else 4
        section_start = stream.tell()
        stream.write(b"\0" * (size_bytes * 2))
        info_start = stream.tell()
        stream.write(struct.pack(">h", len(ordered)))
        # PSD puts every record before the channel data. Spool compressed
        # channels to disk and release each materialized image before moving
        # on: an export never retains every full-size RGBA layer at once.
        with tempfile.TemporaryFile() as channels_file:
            for kind, layer in ordered:
                if kind != "layer":
                    PSDFormat._write_group_marker(stream, layer, kind == "group_start")
                    continue
                layer.commit_image_cache(release=True)
                image = layer.tile_store.materialize().convertToFormat(QImage.Format.Format_RGBA8888)
                channels = PSDFormat._layer_channel_data(image)
                channel_ids = (0, 1, 2, -1)
                if layer.alpha_mask_store is not None:
                    mask = layer.alpha_mask_coverage()
                    channels.append(PSDFormat._zip_channel(mask, 3))
                    channel_ids += (-2,)
                    del mask
                PSDFormat._write_layer_record(stream, layer, image, channel_ids, channels, version)
                for channel in channels:
                    channels_file.write(channel)
                del image, channels
            channels_file.seek(0)
            shutil.copyfileobj(channels_file, stream, 1024 * 1024)
        info_size = stream.tell() - info_start
        if info_size % 2:
            stream.write(b"\0")
            info_size += 1
        stream.write(struct.pack(">I", 0))  # empty global mask
        end = stream.tell()
        section_size = end - section_start - size_bytes
        if version == 1 and section_size > 0xFFFFFFFF:
            raise ValueError("Ce document dépasse la limite PSD : utilisez .psb")
        stream.seek(section_start)
        stream.write(struct.pack(size_format, section_size))
        stream.write(struct.pack(size_format, info_size))
        stream.seek(end)

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
            starts.setdefault(indices[0], []).append(group)  # bounding marker precedes children.
            ends.setdefault(indices[-1], []).append(group)
        result = []
        for index in range(len(document.layers)):
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
                            channels: list[bytes], version: int = 1) -> None:
        width, height = image.width(), image.height()
        stream.write(struct.pack(">iiiiH", 0, 0, height, width, len(channel_ids)))
        for channel_id, payload in zip(channel_ids, channels):
            stream.write(struct.pack(">hQ" if version == 2 else ">hI", channel_id, len(payload)))
        mode = PSDFormat._psd_blend_key(str(getattr(layer, "blend_mode", "normal")))
        stream.write(b"8BIM" + mode)
        stream.write(bytes((round(max(0.0, min(1.0, float(layer.opacity))) * 255),
                            1 if bool(getattr(layer, "clipping", False)) else 0,
                            0 if bool(getattr(layer, "visible", True)) else 0x02, 0)))
        extra = PSDFormat._layer_extra_data(str(getattr(layer, "name", "Layer")),
                                             width, height, -2 in channel_ids,
                                             adjustment=getattr(layer, "adjustment", None))
        stream.write(struct.pack(">I", len(extra)))
        stream.write(extra)

    @staticmethod
    def _layer_extra_data(name: str, width: int, height: int, has_mask: bool = False,
                          section_type: int | None = None, adjustment=None) -> bytes:
        # Mask descriptor, blending ranges, then Pascal name + Unicode luni name.
        latin = name.encode("macroman", "replace")[:255]
        pascal = bytes((len(latin),)) + latin
        pascal += b"\0" * ((4 - len(pascal) % 4) % 4)
        utf16 = name.encode("utf-16be")
        luni_payload = struct.pack(">I", len(utf16) // 2) + utf16
        luni_padding = b"\0" * ((4 - (12 + len(luni_payload)) % 4) % 4)
        # The native reader consumes the tagged-block size literally.  Keep
        # the Photoshop alignment bytes inside this writer's declared size so
        # a following adjustment tag is not mistaken for padding.
        luni = b"8BIMluni" + struct.pack(">I", len(luni_payload) + len(luni_padding))
        luni += luni_payload + luni_padding
        mask = (struct.pack(">IiiiiBBH", 20, 0, 0, height, width, 255, 0, 0)
                if has_mask else struct.pack(">I", 0))
        section = b"" if section_type is None else b"8BIMlsct" + struct.pack(">I", 4) + struct.pack(">I", section_type)
        adjustment_block = PSDFormat._curve_adjustment_block(adjustment)
        return mask + struct.pack(">I", 0) + pascal + luni + section + adjustment_block

    @staticmethod
    def _curve_adjustment_block(adjustment) -> bytes:
        """Encode Nebula Curves/Levels-as-curves as Photoshop's ``curv`` tag."""
        if not isinstance(adjustment, dict) or adjustment.get("kind") != "curves":
            return b""
        curves = adjustment.get("curves")
        if not isinstance(curves, dict):
            return b""
        entries = [(0, curves.get("points", [[0, 0], [255, 255]]))]
        entries.extend((index, curves.get("channels", {}).get(name))
                       for index, name in ((1, "red"), (2, "green"), (3, "blue"))
                       if curves.get("channels", {}).get(name))
        bitmap = sum(1 << index for index, _points in entries)
        payload = bytearray(b"\0" + struct.pack(">HI", 1, bitmap))
        for _index, points in entries:
            normalized = [(max(0, min(255, int(point[0]))), max(0, min(255, int(point[1]))))
                          for point in points if isinstance(point, (list, tuple)) and len(point) >= 2]
            normalized = normalized[:255] or [(0, 0), (255, 255)]
            payload += struct.pack(">H", len(normalized))
            for value, output in normalized:
                payload += struct.pack(">HH", output, value)
        block = b"8BIMcurv" + struct.pack(">I", len(payload)) + bytes(payload)
        return block + (b"\0" if len(payload) % 2 else b"")

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
    def _zip_channel(image: QImage, channel: int) -> bytes:
        import numpy as np
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(rgba.constBits(), np.uint8).reshape(rgba.height(), rgba.bytesPerLine())
        plane = pixels[:, channel:rgba.width() * 4:4]
        return struct.pack(">H", 2) + zlib.compress(plane.tobytes(), 1)

    @staticmethod
    def _layer_channel_data(image: QImage) -> list[bytes]:
        return [PSDFormat._zip_channel(image, channel) for channel in range(4)]

    @staticmethod
    def _write_channel_image_data(stream, image: QImage, include_alpha: bool = False) -> None:
        # Raw merged channels are universally supported, including readers
        # which cannot decode ZIP composites. No Python PackBits pixel loop.
        import numpy as np
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(rgba.constBits(), np.uint8).reshape(rgba.height(), rgba.bytesPerLine())
        stream.write(struct.pack(">H", 0))
        for channel in range(4 if include_alpha else 3):
            stream.write(pixels[:, channel:rgba.width() * 4:4].tobytes())

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
        # psd-tools descendants are already emitted in the document's storage
        # order for raster layers.  Nebula stores that same bottom-to-top order
        # at indices 0..n, so reversing here silently inverted every import.
        sources = list(psd.descendants())
        for source in sources:
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
