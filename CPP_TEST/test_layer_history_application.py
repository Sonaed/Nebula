from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from PySide6.QtGui import QColor, QImage

from CANVAS.tile_history import TileHistory
from CORE.application import CreativeSystem
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.layer import Layer


def fake_application(document):
    history = TileHistory()
    canvas = SimpleNamespace(
        document=document,
        tile_history=history,
        commit_history_action=lambda: history.commit(document),
        cancel_history_action=history.cancel,
        prune_gpu_layers=lambda: None,
        sync_gpu_layer=lambda: None,
    )
    app = SimpleNamespace(
        canvas=canvas,
        layer_manager=LayerManager(document),
        refresh_layers=lambda: None,
    )
    app._with_layer_history = lambda operation, **kwargs: \
        CreativeSystem._with_layer_history(app, operation, **kwargs)
    return app, history


class LayerHistoryApplicationTests(unittest.TestCase):
    def test_autosave_defers_during_open_edit_transaction(self):
        history = SimpleNamespace(index=7, _pending={"stroke": True})
        saved_documents = []
        recovery = SimpleNamespace(
            save=lambda document: (saved_documents.append(document) or True),
            clear=lambda: self.fail("must retain recovery snapshot"),
        )
        document = object()
        app = SimpleNamespace(
            canvas=SimpleNamespace(tile_history=history, document=document),
            recovery_manager=recovery,
            _last_saved_history_index=7,
        )

        CreativeSystem._autosave_recovery(app)
        self.assertEqual(saved_documents, [])
        self.assertEqual(app._last_saved_history_index, 7)

        history._pending = None
        history.index = 8
        CreativeSystem._autosave_recovery(app)
        self.assertEqual(saved_documents, [document])
        self.assertEqual(app._last_saved_history_index, 8)

    def test_merge_down_stays_sparse_without_materializing_layer_images(self):
        document = Document(8192, 8192)
        lower, upper = document.layers[0], document.add_layer("Upper")
        red = QImage(64, 64, QImage.Format.Format_ARGB32)
        red.fill(QColor("red"))
        blue = QImage(64, 64, QImage.Format.Format_ARGB32)
        blue.fill(QColor(0, 0, 255, 128))
        lower.discard_image_cache()
        upper.discard_image_cache()
        lower.tile_store.set_tile(0, 0, red)
        upper.tile_store.set_tile(0, 0, blue)
        app, _history = fake_application(document)

        with patch.object(Layer, "image", new_callable=PropertyMock,
                          side_effect=AssertionError("merge materialized a full layer")):
            CreativeSystem.merge_down(app)

        self.assertEqual(lower.tile_store.tile_count, 1)
        self.assertEqual(lower.tile_store.tile(0, 0).pixelColor(4, 4).blue(), 128)

    def test_duplicate_command_uses_sparse_history_and_round_trips(self):
        document = Document(512, 384)
        layer = document.get_active_layer()
        layer.image.setPixelColor(8, 9, QColor(220, 40, 80, 190))
        layer.commit_image_cache()
        app, history = fake_application(document)

        CreativeSystem.duplicate_layer(app)

        self.assertEqual(len(history.steps[-1].tiles), 1)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layers[1].image.pixelColor(8, 9),
                         QColor(220, 40, 80, 190))

    def test_remove_command_captures_only_removed_layer_tiles(self):
        document = Document(512, 384)
        layer = document.add_layer("Sparse")
        layer.image.setPixelColor(390, 270, QColor("cyan"))
        layer.commit_image_cache()
        app, history = fake_application(document)

        CreativeSystem.remove_layer(app)

        self.assertEqual(len(history.steps[-1].tiles), 1)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[1].image.pixelColor(390, 270), QColor("cyan"))

    def test_merge_down_command_records_sparse_pixels_and_undoes(self):
        document = Document(128, 64)
        lower = document.get_active_layer()
        lower.image.setPixelColor(4, 4, QColor("red"))
        upper = document.add_layer("Upper")
        upper.image.setPixelColor(100, 4, QColor("blue"))
        app, history = fake_application(document)

        CreativeSystem.merge_down(app)

        self.assertEqual(len(history.steps[-1].tiles), 2)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[1].image.pixelColor(100, 4), QColor("blue"))
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layers[0].image.pixelColor(100, 4), QColor("blue"))

    def test_flatten_command_captures_sparse_sources_not_canvas_images(self):
        document = Document(128, 64)
        bottom = document.get_active_layer()
        bottom.image.setPixelColor(4, 4, QColor("red"))
        top = document.add_layer("Upper")
        top.image.setPixelColor(100, 4, QColor("blue"))
        bottom.commit_image_cache()
        top.commit_image_cache()
        app, history = fake_application(document)

        CreativeSystem.flatten_image(app)

        self.assertEqual(len(history.steps[-1].tiles), 4)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[0].image.pixelColor(4, 4), QColor("red"))
        self.assertEqual(document.layers[1].image.pixelColor(100, 4), QColor("blue"))

    def test_merge_visible_command_preserves_visible_pixels_around_hidden_layer(self):
        document = Document(192, 64)
        bottom = document.get_active_layer()
        bottom.image.setPixelColor(2, 2, QColor("red"))
        hidden = document.add_layer("Hidden receiver")
        hidden.visible = False
        hidden.image.setPixelColor(70, 2, QColor("green"))
        top = document.add_layer("Visible top")
        top.image.setPixelColor(150, 2, QColor("blue"))
        for layer in document.layers:
            layer.commit_image_cache()
        app, history = fake_application(document)

        CreativeSystem.merge_visible(app)

        self.assertEqual(len(history.steps[-1].tiles), 2)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 3)
        self.assertEqual(document.layers[1].image.pixelColor(70, 2), QColor("green"))
        self.assertEqual(document.layers[2].image.pixelColor(150, 2), QColor("blue"))
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.active_layer_index, 0)
        self.assertEqual(document.layers[0].image.pixelColor(150, 2), QColor("blue"))
        self.assertEqual(document.layers[1].image.pixelColor(70, 2), QColor("green"))


if __name__ == "__main__":
    unittest.main()
