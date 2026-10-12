"""Bounded, temporary visibility feedback; never an authoritative pixel source.

The caller must commit pending stroke buffers before rendering. Thumbnails are
composed with the same stack evaluator as the exact projection, but filtering
sources before blending is only an approximation at reduced resolution.
"""
from collections import OrderedDict
import ctypes
import weakref
from PySide6.QtGui import QImage
from CORE.native_bridge import load_creative_core, qimage_const_pointer, qimage_pointer
from DOCUMENTS.stack_program import build_stack_program, compose_program, native_stack_function


class VisibilityPreview:
    def __init__(self, max_size=768, budget_bytes=96 * 1024 * 1024):
        self.max_size = max(1, int(max_size))
        self.budget_bytes = max(0, int(budget_bytes))
        self._cache = OrderedDict()
        self._bytes = 0
        self._document_ref = None

    def clear(self):
        self._cache.clear()
        self._bytes = 0
        self._document_ref = None

    def _select_document(self, document):
        if self._document_ref is not None and self._document_ref() is document:
            return
        self.clear()
        owner = weakref.ref(self)

        def released(reference):
            renderer = owner()
            if renderer is not None and renderer._document_ref is reference:
                renderer.clear()

        self._document_ref = weakref.ref(document, released)

    def _remove_cached(self, layer_id):
        cached = self._cache.pop(layer_id, None)
        if cached is not None:
            self._bytes -= cached[1].sizeInBytes()

    def render(self, document):
        self._select_document(document)
        present = {layer.id for layer in document.layers}
        for layer_id in self._cache.keys() - present:
            self._remove_cached(layer_id)
        # Unsupported render-time content must keep the exact projection path.
        if (document.text_objects or document.reference_images or
                any(getattr(g, 'alpha_mask_store', None) is not None for g in document.layer_groups) or
                any(getattr(l, 'transform_state', None) or getattr(l, 'layer_effects', None) or
                    getattr(l, 'psd_effects', None) or getattr(l, 'vector_mask', None) or
                    getattr(l, 'alpha_mask_store', None) is not None
                    for l in document.layers)):
            return None
        function = native_stack_function(load_creative_core())
        if function is None:
            return None
        scale = min(1.0, self.max_size / max(document.width, document.height))
        width, height = max(1, round(document.width * scale)), max(1, round(document.height * scale))

        def layer_image(layer):
            store = layer.tile_store
            # A stroke buffer may contain edits not yet committed to its store.
            # Falling back is preferable to silently displaying stale pixels;
            # the preview never commits a buffer on the caller's behalf.
            source = getattr(layer, '_image_cache', None)
            if (getattr(layer, '_cache_dirty', False) or
                    (source is not None and int(source.cacheKey()) != layer._image_cache_key) or
                    not getattr(store, '_native_handle', None) or
                    (store.width, store.height) != (document.width, document.height)):
                return None, True
            # Do not block the UI by loading a document's scratch tiles.
            if getattr(store, '_swapped', None):
                return None, True
            revisions = store.resident_revisions()
            if revisions is None:
                return None, True
            # Native history restores also advance revisions, even when they
            # bypass Python's mutation counter. Deletions change the count.
            fingerprint = (store.id, len(revisions), max(revisions.values(), default=0), width, height)
            cached = self._cache.get(layer.id)
            if cached is not None and cached[0] == fingerprint:
                self._cache.move_to_end(layer.id)
                return cached[1], False
            image = store.thumbnail(min(self.max_size, max(document.width, document.height)))
            if image is None or image.isNull() or (image.width(), image.height()) != (width, height):
                return None, True
            image = image.convertToFormat(QImage.Format.Format_ARGB32)
            self._remove_cached(layer.id)
            self._cache[layer.id] = (fingerprint, image)
            self._bytes += image.sizeInBytes()
            while self._bytes > self.budget_bytes and self._cache:
                _key, (_version, old) = self._cache.popitem(last=False)
                self._bytes -= old.sizeInBytes()
            return image, False

        program = build_stack_program(document, layer_image, lambda layer: (None, True))
        if program is None or program.pending:
            return None
        pointers = []
        def pixels_of(image):
            pointer = qimage_const_pointer(image)
            pointers.append(pointer)
            return ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine(), 0
        def new_target(w, h):
            image = QImage(w, h, QImage.Format.Format_ARGB32)
            pointer = qimage_pointer(image)
            pointers.append(pointer)
            return image, ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine()
        return compose_program(program, width, height, function, pixels_of, new_target)
