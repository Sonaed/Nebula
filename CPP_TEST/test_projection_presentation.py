"""Projection results become visible as a coherent viewport, not scattered tiles."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from DOCUMENTS.tile_store import TileStore
from DOCUMENTS.document import Document


class PresentationHarness:
    _publish_projection_frame = Canvas._publish_projection_frame
    _on_projected_tile = Canvas._on_projected_tile
    _invalidate_projection_cache = Canvas._invalidate_projection_cache

    def __init__(self):
        self.projection_store = TileStore(128, 64)
        self._projection_scan_pending = False
        self._projection_tile_generation = {(0, 0): 1, (1, 0): 1}
        self._projection_tile_signatures = {(0, 0): ('new',), (1, 0): ('new',)}
        self._projection_ready_tiles = set()
        self._projection_pending_images = {}
        self._projection_publish_keys = {(0, 0), (1, 0)}
        self._projection_waiting_visible = {(0, 0), (1, 0)}
        self._projection_display_ready = True
        self.updates = 0
        for key in self._projection_tile_generation:
            self.projection_store.set_tile(*key, tile('red'))

    def visible_document_tile_keys(self):
        return {(0, 0), (1, 0)}

    def update(self):
        self.updates += 1


def tile(color):
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


class ProjectionPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_partial_results_leave_previous_view_untouched(self):
        canvas = PresentationHarness()
        canvas._on_projected_tile(1, 0, 0, tile('blue'))
        self.assertEqual(canvas.updates, 0)
        self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('red'))
        canvas._on_projected_tile(1, 1, 0, tile('green'))
        self.assertEqual(canvas.updates, 1)
        self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('blue'))
        self.assertEqual(canvas.projection_store.tile(1, 0).pixelColor(0, 0), QColor('green'))
        self.assertFalse(canvas._projection_pending_images)

    def test_scan_must_finish_before_publication(self):
        canvas = PresentationHarness()
        canvas._projection_scan_pending = True
        for x in (0, 1):
            canvas._on_projected_tile(1, x, 0, tile('blue'))
        self.assertEqual(canvas.updates, 0)
        canvas._projection_scan_pending = False
        self.assertTrue(canvas._publish_projection_frame())
        self.assertEqual(canvas.updates, 1)

    def test_stale_results_and_undo_cannot_publish_pending_pixels(self):
        canvas = PresentationHarness()
        canvas._on_projected_tile(0, 0, 0, tile('blue'))
        self.assertFalse(canvas._projection_pending_images)
        canvas._on_projected_tile(1, 0, 0, tile('blue'))
        canvas._invalidate_projection_cache()
        canvas._on_projected_tile(1, 1, 0, tile('green'))
        self.assertFalse(canvas._projection_pending_images)
        self.assertFalse(canvas._projection_ready_tiles)
        self.assertEqual(canvas.updates, 0)

    def test_native_worker_publishes_complete_viewport(self):
        from PySide6.QtCore import QEventLoop, QTimer
        canvas = Canvas()
        try:
            document = Document(128, 64)
            document.layers[0].tile_store.set_tile(0, 0, tile('red'))
            document.layers[0].tile_store.set_tile(1, 0, tile('blue'))
            canvas.set_document(document)
            canvas.visible_document_tile_keys = lambda *args: {(0, 0), (1, 0)}
            canvas._ensure_projection()
            loop = QEventLoop()
            timer = QTimer()
            timer.timeout.connect(lambda: loop.quit() if canvas._projection_display_ready else None)
            timer.start(5)
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            deadline.start(3000)
            loop.exec()
            timer.stop()
            deadline.stop()
            self.assertTrue(canvas._projection_display_ready)
            self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('red'))
            self.assertEqual(canvas.projection_store.tile(1, 0).pixelColor(0, 0), QColor('blue'))
        finally:
            canvas.close()

    def test_psd_proxy_keeps_canvas_geometry_and_one_preview(self):
        from PySide6.QtCore import QBuffer, QIODevice
        from CORE.application import CreativeSystem
        image = tile('blue')
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        documents = SimpleNamespace(documents=[], active_document=None)
        target = SimpleNamespace(document=None)
        target.set_document = lambda document: setattr(target, 'document', document)
        import_states = []
        fake = SimpleNamespace(canvas=target, document_manager=documents,
            refresh_layers=lambda: None,
            ui=SimpleNamespace(show_workspace=lambda: None,
                               set_import_state=lambda text="", warning=False: import_states.append((text, warning))),
            statusBar=lambda: SimpleNamespace(showMessage=lambda *args: None))
        CreativeSystem._show_psd_proxy(fake, bytes(buffer.data()), 400, 300)
        proxy = target.document
        self.assertEqual((proxy.layers[0].tile_store.width, proxy.layers[0].tile_store.height), (400, 300))
        self.assertTrue(proxy._loading_preview)
        self.assertEqual(proxy._display_preview.size(), image.size())
        self.assertEqual(import_states[-1], ("Aperçu PSD · import éditable en cours", False))
        CreativeSystem._apply_psd_proxy_tiles(fake, {(0, 0): bytes(buffer.data())})
        self.assertIn((0, 0), proxy.layers[0].tile_store.occupied_keys)

    def test_native_batch_idle_and_edit_refresh(self):
        from unittest.mock import patch
        canvas = Canvas()
        try:
            document = Document(64, 64)
            store = document.layers[0].tile_store
            store.set_tile(0, 0, tile('red'))
            canvas.set_document(document)
            canvas.visible_document_tile_keys = lambda *args: {(0, 0)}
            with patch.object(canvas.projection_worker, 'request',
                              side_effect=AssertionError('redundant composition')):
                canvas._ensure_projection()
                self.assertTrue(canvas._projection_display_ready)
                with patch.object(canvas, 'visible_document_tile_keys',
                                  side_effect=AssertionError('idle tile scan')):
                    canvas._ensure_projection()
                store.set_tile(0, 0, tile('blue'))
                canvas._ensure_projection()
                self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('blue'))
                document.layers[0].opacity = 0.5
                canvas._ensure_projection()
                self.assertAlmostEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0).alpha(), 128, delta=1)
                document.layers[0].opacity = 1.0
                with patch.object(canvas, '_compose_native_batch',
                                  side_effect=AssertionError('cached state recomposited')):
                    canvas._ensure_projection()
                self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('blue'))
                store.set_tile(0, 0, tile('green'))
                canvas._ensure_projection()
                self.assertEqual(canvas.projection_store.tile(0, 0).pixelColor(0, 0), QColor('green'))
                canvas._invalidate_projection_cache()
                canvas._ensure_projection()
                self.assertIn((0, 0), canvas._projection_ready_tiles)
        finally:
            canvas.close()

    def test_switching_same_size_documents_clears_old_projection(self):
        canvas = Canvas()
        try:
            canvas.projection_store.set_tile(0, 0, tile('red'))
            canvas._projection_tile_generation[(0, 0)] = 7
            canvas._projection_tile_signatures[(0, 0)] = ('old',)
            canvas._projection_ready_tiles.add((0, 0))
            canvas._projection_pending_images[(0, 0)] = tile('blue')
            canvas.set_document(Document(800, 600))
            canvas._on_projected_tile(7, 0, 0, tile('green'))
            self.assertFalse(canvas.projection_store.occupied_keys)
            self.assertFalse(canvas._projection_pending_images)
            self.assertFalse(canvas._projection_ready_tiles)
            self.assertFalse(canvas._projection_display_ready)
        finally:
            canvas.close()


if __name__ == '__main__':
    unittest.main()
