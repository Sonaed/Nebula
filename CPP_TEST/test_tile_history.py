from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage

from CANVAS.tile_history import (ALPHA_MASK_TILE_PREFIX, SELECTION_TILE_ID,
                                 NativeTileDeltaMap,
                                 TileHistory, UndoStep)
from DOCUMENTS.document import Document
from DOCUMENTS.format_nebula import NebulaFormat
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage


class TileHistoryTests(unittest.TestCase):
    def test_alpha_mask_tiles_replay_through_native_undo_redo(self) -> None:
        document = Document(8, 8)
        layer = document.get_active_layer()
        history = TileHistory()
        rect = QRect(0, 0, 8, 8)
        history.begin(document, dirty_only=True)
        history.capture_mask_before(layer, rect)
        mask = layer.ensure_alpha_mask()
        tile = QImage(8, 8, QImage.Format.Format_ARGB32)
        tile.fill(QColor(255, 255, 255, 128))
        mask.set_tile(0, 0, tile)
        self.assertTrue(history.commit(document))
        self.assertIn((ALPHA_MASK_TILE_PREFIX + layer.id, 0, 0), history.steps[-1].tiles)

        self.assertTrue(history.undo(document))
        self.assertFalse(layer.alpha_mask_store.occupied_keys)
        self.assertTrue(history.redo(document))
        self.assertEqual(layer.alpha_mask_store.tile(0, 0).pixelColor(0, 0).alpha(), 128)

    def test_structural_history_requires_native_metadata_validation(self) -> None:
        document = Document(32, 32)
        history = TileHistory()
        with patch("CANVAS.tile_history.validate_history_layer_state",
                   return_value=None):
            with self.assertRaisesRegex(RuntimeError, "required to validate"):
                history.begin(document, structure_only=True)
        self.assertIsNone(history._pending)
        self.assertFalse(history._native_cursor.transaction_open)

    def test_raster_history_does_not_snapshot_unrelated_canvas_objects(self) -> None:
        document = Document(32, 32)
        reference_image = QImage(12, 10, QImage.Format.Format_ARGB32)
        reference_image.fill(QColor("orange"))
        reference = ReferenceImage(reference_image)
        text = EditableText("Keep me", QPoint(4, 8))
        document.reference_images.append(reference)
        document.text_objects.append(text)
        history = TileHistory()
        layer = document.get_active_layer()

        with patch.object(reference, "copy", wraps=reference.copy) as copy_reference, \
             patch.object(text, "copy", wraps=text.copy) as copy_text:
            history.begin(document, dirty_only=True)
            copy_reference.assert_not_called()
            copy_text.assert_not_called()
            self.assertNotIn("reference_images", history._pending["state"])
            self.assertNotIn("text_objects", history._pending["state"])
            self.assertNotIn("layers", history._pending["state"])
            self.assertNotIn("layer_groups", history._pending["state"])
            self.assertNotIn("blend_presets", history._pending["state"])
            rect = QRect(2, 3, 1, 1)
            history.capture_before(layer, rect)
            layer.image.setPixelColor(2, 3, QColor("cyan"))
            history.mark_dirty(layer, rect)
            self.assertTrue(history.commit(document))

        self.assertTrue(history.undo(document))
        self.assertIs(document.layers[0], layer)
        self.assertIs(document.reference_images[0], reference)
        self.assertIs(document.text_objects[0], text)
        self.assertEqual(document.reference_images[0].image.pixelColor(1, 1),
                         QColor("orange"))

    def test_general_history_reference_pixels_are_owned_by_native_state(self) -> None:
        document = Document(24, 24)
        reference = ReferenceImage(QImage(8, 6, QImage.Format.Format_ARGB32),
                                   QPoint(3, 4), 1.25, 0.65)
        reference.image.fill(QColor("orange"))
        document.reference_images.append(reference)
        history = TileHistory()
        history.begin(document)
        reference.image.fill(QColor("cyan"))
        self.assertTrue(history.commit(document))
        step = history.steps[-1]
        self.assertEqual(step.before, {})
        self.assertEqual(step.after, {})
        self.assertGreater(step.native_state_bytes, 0)
        self.assertTrue(history.undo(document))
        self.assertEqual(document.reference_images[0].image.pixelColor(1, 1),
                         QColor("orange"))
        self.assertEqual(document.reference_images[0].id, reference.id)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.reference_images[0].image.pixelColor(1, 1),
                         QColor("cyan"))

    def test_selection_history_replays_mask_without_rebuilding_document_model(self) -> None:
        document = Document(40, 24)
        first = document.get_active_layer()
        second = document.add_layer("Top")
        group = document.group_layers([0, 1], "Pair")
        history = TileHistory()

        history.begin(document, selection_only=True)
        self.assertNotIn("layers", history._pending["state"])
        self.assertNotIn("layer_groups", history._pending["state"])
        document.selection.image.setPixelColor(8, 9, QColor("white"))
        document.selection.invalidate()
        self.assertTrue(history.commit(document))

        self.assertTrue(history.undo(document))
        self.assertIs(document.layers[0], first)
        self.assertIs(document.layers[1], second)
        self.assertIs(document.layer_groups[0], group)
        self.assertFalse(document.selection.contains(8, 9))
        self.assertTrue(history.redo(document))
        self.assertTrue(document.selection.contains(8, 9))

    def test_native_transaction_lifecycle_is_single_open_and_closes_cleanly(self) -> None:
        document = Document(32, 32)
        history = TileHistory()
        history.begin(document, dirty_only=True)
        self.assertTrue(history._native_cursor.transaction_open)
        first_pending = history._pending
        history.begin(document, selection_only=True)
        self.assertIs(history._pending, first_pending)
        self.assertTrue(history._native_cursor.transaction_open)
        self.assertFalse(history.undo(document))
        self.assertFalse(history.redo(document))
        with self.assertRaisesRegex(RuntimeError, "while an edit transaction is open"):
            history._append_step(UndoStep({}, {}, {}))
        history.cancel()
        self.assertIsNone(history._pending)
        self.assertFalse(history._native_cursor.transaction_open)
        history.begin(document, dirty_only=True)
        self.assertFalse(history.commit(document))
        self.assertFalse(history._native_cursor.transaction_open)

    def test_native_metadata_replaces_python_structural_copies(self) -> None:
        document = Document(32, 32)
        history = TileHistory()
        history.begin(document, structure_only=True)
        document.add_layer("Ink")
        self.assertTrue(history.commit(document))
        step = history.steps[-1]
        self.assertGreater(step.native_state_bytes, 0)
        self.assertEqual(step.before, {})
        self.assertEqual(step.after, {})
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 2)

    def test_native_transaction_is_cancelled_if_begin_capture_fails(self) -> None:
        history = TileHistory()
        with patch.object(history, "_capture", side_effect=OSError("capture failed")):
            with self.assertRaisesRegex(OSError, "capture failed"):
                history.begin(Document(32, 32), dirty_only=True)
        self.assertIsNone(history._pending)
        self.assertFalse(history._native_cursor.transaction_open)

    def test_cpp_cursor_authoritatively_truncates_branches_and_retention(self) -> None:
        history = TileHistory(max_steps=2)
        for label in ("a", "b"):
            history._append_step(UndoStep({"label": label}, {"label": label}, {}))
        history.index = 1
        history._append_step(UndoStep({"label": "branch"}, {"label": "branch"}, {}))
        self.assertEqual(len(history.steps), 2)
        self.assertEqual(history.index, 2)
        history._append_step(UndoStep({"label": "capacity"}, {"label": "capacity"}, {}))
        self.assertEqual(len(history.steps), 2)
        self.assertEqual(history._native_cursor.count, 2)
        self.assertEqual(history.index, 2)

    def test_history_rejects_cursor_step_metadata_divergence(self) -> None:
        history = TileHistory()
        history.steps.append(UndoStep({}, {}, {}))
        with self.assertRaisesRegex(RuntimeError, "cursor and step metadata diverged"):
            history._append_step(UndoStep({}, {}, {}))

    def test_tile_capture_range_uses_native_clipped_geometry(self) -> None:
        history = TileHistory(tile_size=64)
        self.assertEqual(
            list(history._tile_keys(130, 130, QRect(-4, 63, 70, 2))),
            [(0, 0), (1, 0), (0, 1), (1, 1)],
        )
        self.assertEqual(list(history._tile_keys(130, 130, QRect(140, 0, 2, 2))), [])

    def test_tile_capture_requires_native_geometry(self) -> None:
        history = TileHistory()
        with patch("CANVAS.tile_history.native_tile_range_for_rect", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                list(history._tile_keys(128, 128, QRect(0, 0, 64, 64)))

    def test_generic_transaction_snapshots_only_sparse_tiles(self) -> None:
        document = Document(2048, 1024)
        history = TileHistory()
        layer = document.get_active_layer()
        layer.discard_image_cache()
        history.begin(document)
        self.assertEqual(history._pending["before_tiles"], {})
        self.assertNotIn("images", history._pending)
        self.assertNotIn("dirty_rects", history._pending)

        new_tile = QImage(64, 64, QImage.Format.Format_ARGB32)
        new_tile.fill(0)
        new_tile.setPixelColor(5, 6, QColor("cyan"))
        layer.tile_store.set_tile(12, 7, new_tile)
        layer.discard_image_cache()
        self.assertTrue(history.commit(document))
        step = history.steps[-1]
        self.assertEqual(set(step.tiles), {(layer.id, 12, 7)})
        self.assertIsNone(step.tiles[(layer.id, 12, 7)][0])
        self.assertTrue(history.undo(document))
        self.assertFalse(layer.tile_store.has_tile(12, 7))
        self.assertTrue(history.redo(document))
        self.assertEqual(layer.tile_store.tile(12, 7).pixelColor(5, 6), QColor("cyan"))

    def test_undo_step_pixels_are_owned_by_creative_core(self) -> None:
        document = Document(64, 64)
        history = TileHistory()
        layer = document.get_active_layer()
        rect = QRect(3, 4, 1, 1)
        history.begin(document, dirty_only=True)
        history.capture_before(layer, rect)
        layer.image.setPixelColor(3, 4, QColor("magenta"))
        history.mark_dirty(layer, rect)
        self.assertTrue(history.commit(document))

        step = history.steps[-1]
        key = (layer.id, 0, 0)
        self.assertTrue(step.tiles.is_native)
        self.assertGreater(step.tiles.native_storage_bytes, 0)
        before, after = step.tiles[key]
        self.assertEqual(before.pixelColor(3, 4).alpha(), 0)
        self.assertEqual(after.pixelColor(3, 4), QColor("magenta"))
        after.fill(QColor("lime"))
        self.assertEqual(step.tiles[key][1].pixelColor(3, 4), QColor("magenta"))

    def test_native_history_batch_skips_unchanged_tiles_and_keeps_indices(self) -> None:
        before = QImage(8, 8, QImage.Format.Format_ARGB32)
        before.fill(QColor("red"))
        changed = QImage(8, 8, QImage.Format.Format_ARGB32)
        changed.fill(QColor("blue"))
        added = QImage(8, 8, QImage.Format.Format_ARGB32)
        added.fill(QColor("lime"))
        deltas = NativeTileDeltaMap([
            (("layer", 0, 0), (before, changed)),
            (("layer", 1, 0), (before, before.copy())),
            (("layer", 2, 0), (None, added)),
        ])
        self.assertTrue(deltas.is_native)
        self.assertEqual(set(deltas), {("layer", 0, 0), ("layer", 2, 0)})
        self.assertEqual(deltas[("layer", 0, 0)][1].pixelColor(0, 0), QColor("blue"))
        self.assertEqual(deltas[("layer", 2, 0)][0], None)
        self.assertEqual(deltas[("layer", 2, 0)][1].pixelColor(0, 0), QColor("lime"))

    def test_history_requires_native_payload_and_cursor(self) -> None:
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("orange"))
        with patch("CANVAS.tile_history.create_native_history_payload", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                NativeTileDeltaMap({("layer", 0, 0): (None, image)})
        with patch("CANVAS.tile_history.create_native_history_cursor", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                TileHistory()

    def test_edit_undo_redo_save_close_reopen_cycle(self) -> None:
        document = Document(96, 72, 144)
        history = TileHistory()
        layer = document.get_active_layer()
        area = QRect(20, 18, 12, 9)
        history.begin(document, dirty_only=True)
        history.capture_before(layer, area)
        layer.image.fill(QColor(0, 0, 0, 0))
        for y in range(area.top(), area.bottom() + 1):
            for x in range(area.left(), area.right() + 1):
                layer.image.setPixelColor(x, y, QColor(225, 64, 118, 210))
        history.mark_dirty(layer, area)
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(layer.image.pixelColor(24, 21).alpha(), 0)
        self.assertTrue(history.redo(document))
        self.assertEqual(layer.image.pixelColor(24, 21), QColor(225, 64, 118, 210))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.nebula"
            self.assertTrue(NebulaFormat.save(document, path))
            restored = NebulaFormat.load(path)
        self.assertIsNotNone(restored)
        self.assertEqual((restored.width, restored.height, restored.dpi), (96, 72, 144))
        self.assertEqual(restored.get_active_layer().image.pixelColor(24, 21),
                         QColor(225, 64, 118, 210))

    def test_extended_edit_undo_redo_branch_save_reopen_workflow(self) -> None:
        document = Document(128, 96, 144)
        history = TileHistory(max_steps=128)
        layer = document.get_active_layer()
        snapshots = [layer.image.copy()]

        for index in range(80):
            x, y = (index * 17) % document.width, (index * 23) % document.height
            area = QRect(x, y, 1, 1)
            history.begin(document, dirty_only=True)
            history.capture_before(layer, area)
            layer.image.setPixelColor(x, y, QColor(index * 3 % 256,
                                                    index * 7 % 256,
                                                    index * 11 % 256, 255))
            history.mark_dirty(layer, area)
            self.assertTrue(history.commit(document))
            snapshots.append(layer.image.copy())

        for _ in range(20):
            self.assertTrue(history.undo(document))
        self.assertEqual(layer.image, snapshots[60])
        for _ in range(10):
            self.assertTrue(history.redo(document))
        self.assertEqual(layer.image, snapshots[70])

        area = QRect(4, 5, 1, 1)
        history.begin(document, dirty_only=True)
        history.capture_before(layer, area)
        layer.image.setPixelColor(4, 5, QColor("magenta"))
        history.mark_dirty(layer, area)
        self.assertTrue(history.commit(document))
        self.assertFalse(history.redo(document))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extended-workflow.nebula"
            self.assertTrue(NebulaFormat.save(document, path))
            restored = NebulaFormat.load(path)
        self.assertIsNotNone(restored)
        self.assertEqual((restored.width, restored.height, restored.dpi), (128, 96, 144))
        self.assertEqual(restored.get_active_layer().image.pixelColor(4, 5), QColor("magenta"))

    def test_stroke_stores_only_touched_tiles_and_round_trips(self) -> None:
        document = Document(400, 300)
        layer = document.get_active_layer()
        history = TileHistory(tile_size=64)

        history.begin(document, dirty_only=True)
        history.capture_before(layer, QRect(68, 78, 8, 8))
        layer.image.setPixelColor(70, 80, QColor("red"))
        history.mark_dirty(layer, QRect(68, 78, 8, 8))
        self.assertTrue(history.commit(document))

        self.assertEqual(len(history.steps), 1)
        self.assertEqual(len(history.steps[0].tiles), 1)
        self.assertTrue(history.undo(document))
        self.assertEqual(document.get_active_layer().image.pixelColor(70, 80), QColor(0, 0, 0, 0))
        self.assertTrue(history.redo(document))
        self.assertEqual(document.get_active_layer().image.pixelColor(70, 80), QColor("red"))

    def test_structural_layer_change_restores_layer_pixels(self) -> None:
        document = Document(16, 16)
        history = TileHistory(tile_size=8)
        history.begin(document)
        layer = document.add_layer("added")
        layer.image.setPixelColor(4, 5, QColor("blue"))
        self.assertTrue(history.commit(document))

        self.assertEqual(len(document.layers), 2)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[1].image.pixelColor(4, 5), QColor("blue"))

    def test_structure_only_path_takes_precedence_in_mixed_transaction(self) -> None:
        document = Document(16, 16)
        history = TileHistory()
        history.begin(document, dirty_only=True, structure_only=True)
        added = document.add_layer("Mixed")
        added.image.setPixelColor(6, 7, QColor("magenta"))

        self.assertTrue(history.commit(document))
        self.assertEqual(len(history.steps[-1].tiles), 1)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layers[1].image.pixelColor(6, 7), QColor("magenta"))

    def test_sparse_duplicate_structural_history_does_not_snapshot_other_layers(self) -> None:
        document = Document(512, 384)
        original = document.get_active_layer()
        original.image.setPixelColor(5, 7, QColor(220, 40, 90, 180))
        original.commit_image_cache()
        history = TileHistory()
        history.begin(document, structure_only=True)
        duplicate = LayerManager(document).duplicate_layer(0)
        self.assertIsNotNone(duplicate)
        self.assertTrue(history.commit(document))
        self.assertEqual(len(history.steps[-1].tiles), 1)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layers[1].image.pixelColor(5, 7),
                         QColor(220, 40, 90, 180))

    def test_structural_merge_captures_sparse_layer_union(self) -> None:
        document = Document(128, 64)
        lower = document.get_active_layer()
        lower.image.setPixelColor(2, 2, QColor("red"))
        upper = document.add_layer("Top")
        upper.image.setPixelColor(90, 2, QColor("blue"))
        upper.commit_image_cache()
        lower.commit_image_cache()
        history = TileHistory()
        history.begin(document, structure_only=True)
        upper_keys = upper.tile_store.occupied_keys
        history.capture_layer_before(upper, upper_keys)
        history.capture_layer_before(lower, lower.tile_store.occupied_keys | upper_keys)
        self.assertTrue(LayerManager(document).merge_down(1))
        self.assertTrue(history.commit(document))
        self.assertEqual(len(history.steps[-1].tiles), 2)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[0].image.pixelColor(2, 2), QColor("red"))
        self.assertEqual(document.layers[1].image.pixelColor(90, 2), QColor("blue"))
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(document.layers[0].image.pixelColor(90, 2), QColor("blue"))

    def test_sparse_flatten_history_restores_layers_without_full_snapshots(self) -> None:
        document = Document(128, 64)
        bottom = document.get_active_layer()
        bottom.image.setPixelColor(3, 4, QColor("red"))
        top = document.add_layer("Top")
        top.image.setPixelColor(95, 4, QColor("blue"))
        bottom.commit_image_cache(); top.commit_image_cache()
        history = TileHistory()
        history.begin(document, structure_only=True)
        for layer in document.layers:
            history.capture_layer_before(layer)
        self.assertTrue(LayerManager(document).flatten())
        self.assertTrue(history.commit(document))
        self.assertEqual(len(history.steps[-1].tiles), 4)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[0].image.pixelColor(3, 4), QColor("red"))
        self.assertEqual(document.layers[1].image.pixelColor(95, 4), QColor("blue"))
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(document.layers[0].image.pixelColor(3, 4), QColor("red"))
        self.assertEqual(document.layers[0].image.pixelColor(95, 4), QColor("blue"))

    def test_sparse_merge_visible_history_keeps_hidden_intermediate_and_pixels(self) -> None:
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
        history = TileHistory()
        history.begin(document, structure_only=True)
        for layer in document.layers:
            layer.commit_image_cache()
        key_sets = {layer.id: set(layer.tile_store.occupied_keys)
                    for layer in document.layers}
        target_keys = key_sets[bottom.id] | key_sets[top.id]
        history.capture_layer_before(bottom, target_keys)
        history.capture_layer_before(top, key_sets[top.id])
        self.assertTrue(LayerManager(document).merge_visible())
        self.assertTrue(history.commit(document))
        self.assertEqual(len(history.steps[-1].tiles), 2)
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 3)
        self.assertEqual(document.layers[1].image.pixelColor(70, 2), QColor("green"))
        self.assertEqual(document.layers[2].image.pixelColor(150, 2), QColor("blue"))
        self.assertTrue(history.redo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.active_layer_index, 0)
        self.assertEqual(document.layers[0].image.pixelColor(2, 2), QColor("red"))
        self.assertEqual(document.layers[0].image.pixelColor(150, 2), QColor("blue"))
        self.assertEqual(document.layers[1].name, "Hidden receiver")
        self.assertEqual(document.layers[1].image.pixelColor(70, 2), QColor("green"))

    def test_unchanged_action_is_not_added(self) -> None:
        history = TileHistory()
        document = Document(4, 4)
        history.begin(document)
        self.assertFalse(history.commit(document))
        self.assertEqual(history.index, 0)

    def test_blend_properties_round_trip_through_history(self) -> None:
        document = Document(4, 4)
        history = TileHistory()
        layer = document.get_active_layer()
        history.begin(document)
        layer.blend_mode = "multiply"
        layer.blend_parameters = {"intensity": 0.4, "gamma": 1.5}
        layer.opacity = 0.65
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(layer.blend_mode, "normal")
        self.assertEqual(layer.blend_parameters, {})
        self.assertEqual(layer.opacity, 1.0)
        self.assertTrue(history.redo(document))
        self.assertEqual(layer.blend_mode, "multiply")
        self.assertEqual(layer.blend_parameters["gamma"], 1.5)

    def test_metadata_action_avoids_raster_tile_snapshots(self) -> None:
        document = Document(96, 72)
        layer = document.get_active_layer()
        history = TileHistory()

        history.begin(document)
        layer.visible = False
        layer.opacity = 0.35
        self.assertTrue(history.commit(document))
        self.assertEqual(history.steps[0].tiles, {})

        self.assertTrue(history.undo(document))
        restored = document.get_active_layer()
        self.assertTrue(restored.visible)
        self.assertEqual(restored.opacity, 1.0)
        self.assertTrue(history.redo(document))
        self.assertFalse(document.get_active_layer().visible)
        self.assertEqual(document.get_active_layer().opacity, 0.35)

    def test_selection_action_records_only_selection_tiles(self) -> None:
        document = Document(300, 200)
        history = TileHistory(tile_size=64)
        history.begin(document, selection_only=True)
        document.selection.image.setPixelColor(150, 70, QColor("white"))
        document.selection.invalidate()
        self.assertTrue(history.commit(document))
        self.assertEqual(
            set(history.steps[0].tiles),
            {(SELECTION_TILE_ID, 2, 1)},
        )
        self.assertTrue(history.undo(document))
        self.assertEqual(document.selection.image.pixelColor(150, 70).alpha(), 0)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.selection.image.pixelColor(150, 70).alpha(), 255)

    def test_swapped_undo_tiles_round_trip_from_disk(self) -> None:
        document = Document(64, 64)
        history = TileHistory(tile_size=32)
        layer = document.get_active_layer()
        history.begin(document, dirty_only=True)
        history.capture_before(layer, QRect(3, 4, 1, 1))
        layer.image.setPixelColor(3, 4, QColor("magenta"))
        history.mark_dirty(layer, QRect(3, 4, 1, 1))
        self.assertTrue(history.commit(document))

        step = history.steps[0]
        with tempfile.TemporaryDirectory() as folder:
            swap_path = Path(folder) / "step.zip"
            self.assertGreater(history.write_step_swap(step, swap_path), 0)
            history.attach_step_swap(step, str(swap_path))
            self.assertEqual(step.tiles, {})
            self.assertTrue(history.undo(document))
            self.assertEqual(document.get_active_layer().image.pixelColor(3, 4).alpha(), 0)
            self.assertTrue(history.redo(document))
            self.assertEqual(document.get_active_layer().image.pixelColor(3, 4), QColor("magenta"))

    def test_history_clears_tile_when_restored_state_is_sparse(self) -> None:
        document = Document(32, 32)
        history = TileHistory(tile_size=32)
        layer = document.get_active_layer()
        painted = layer.tile_store.tile(0, 0)
        painted.setPixelColor(7, 9, QColor("cyan"))
        layer.tile_store.set_tile(0, 0, painted)
        layer.discard_image_cache()

        state, _ = history._capture(document)
        history.steps.append(UndoStep(
            state,
            state,
            {(layer.id, 0, 0): (None, painted)},
        ))
        history.index = 1

        self.assertTrue(history.undo(document))
        self.assertEqual(document.get_active_layer().image.pixelColor(7, 9).alpha(), 0)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.get_active_layer().image.pixelColor(7, 9), QColor("cyan"))

    def test_history_clears_selection_tile_when_restored_state_is_sparse(self) -> None:
        document = Document(32, 32)
        history = TileHistory(tile_size=32)
        selected = document.selection.image.copy()
        selected.setPixelColor(7, 9, QColor("white"))
        state, _ = history._capture(document)
        history.steps.append(UndoStep(
            state,
            state,
            {(SELECTION_TILE_ID, 0, 0): (None, selected)},
        ))
        history.index = 1
        document.selection.image = selected.copy()
        document.selection.invalidate()

        self.assertTrue(history.undo(document))
        self.assertEqual(document.selection.image.pixelColor(7, 9).alpha(), 0)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.selection.image.pixelColor(7, 9).alpha(), 255)


if __name__ == "__main__":
    unittest.main()
