from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from CANVAS.canvas import Canvas
from CANVAS.tile_history import TileHistory
from DOCUMENTS.document import Document
from DOCUMENTS.layer_group import LayerGroup
from DOCUMENTS.blend_modes import (composite_document, composite_document_layers,
                                   composite_layers)
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.layer_manager import LayerManager
from DOCUMENTS.tile_store import TILE_SIZE, TileStore


class LayerGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_layer_property_rules_use_creative_core(self):
        from CORE.native_bridge import load_creative_core
        self.assertIsNotNone(load_creative_core())
        document = Document(16, 16)
        manager = LayerManager(document)
        layer = document.layers[0]
        self.assertFalse(manager.toggle_visibility(0))
        self.assertTrue(manager.toggle_visibility(0))
        self.assertTrue(manager.set_opacity(0, 1.7))
        self.assertEqual(layer.opacity, 1.0)
        self.assertTrue(manager.set_opacity(0, -0.2))
        self.assertEqual(layer.opacity, 0.0)
        self.assertFalse(manager.set_opacity(0, float("nan")))
        self.assertTrue(manager.toggle_lock(0))
        self.assertFalse(manager.toggle_lock(0))
        self.assertTrue(manager.toggle_lock_alpha(0))
        self.assertFalse(manager.toggle_lock_alpha(0))
        self.assertTrue(manager.toggle_clipping(0))
        self.assertFalse(manager.toggle_clipping(0))

    def test_layer_property_commands_do_not_fallback_to_python(self):
        document = Document(16, 16)
        manager = LayerManager(document)
        layer = document.layers[0]
        with patch.object(document._native_state, "set_layer_property", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                manager.toggle_visibility(0)
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                manager.set_opacity(0, 0.25)
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                manager.toggle_lock(0)
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                manager.toggle_lock_alpha(0)
            with self.assertRaisesRegex(RuntimeError, "CreativeCore"):
                manager.toggle_clipping(0)
        self.assertTrue(layer.visible)
        self.assertEqual(layer.opacity, 1.0)
        self.assertFalse(layer.locked)
        self.assertFalse(layer.lock_alpha)
        self.assertFalse(layer.clipping)

    def test_layer_group_selection_is_normalized_by_creative_core(self):
        from CORE.native_bridge import load_creative_core, normalize_layer_group
        self.assertIsNotNone(load_creative_core())
        self.assertEqual(normalize_layer_group([2, 1, 2], [0, 0, 0, 0]), [1, 2])
        self.assertFalse(normalize_layer_group([0, 2], [0, 0, 0]))
        self.assertFalse(normalize_layer_group([0, 1], [1, 0]))
        self.assertFalse(normalize_layer_group([0, 8], [0, 0]))

    def test_document_grouping_requires_native_validation_without_mutating(self):
        document = Document(16, 16)
        document.add_layer("Second")
        before_layers = list(document.layers)
        with patch("DOCUMENTS.document.normalize_layer_group", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                document.group_layers([0, 1], "Pair")
        self.assertEqual(document.layers, before_layers)
        self.assertEqual(document.layer_groups, [])

    def test_visible_merge_plan_is_owned_by_creative_core(self):
        from CORE.native_bridge import (load_creative_core,
                                        plan_visible_layer_merge,
                                        plan_visible_layer_merge_groups)
        library = load_creative_core()
        self.assertIsNotNone(library)
        self.assertTrue(hasattr(library, "cs_layer_stack_plan_visible_merge"))
        self.assertEqual(plan_visible_layer_merge([True, False, True, True], 3),
                         ([1, 1, 0, 0], 0, 0))
        self.assertEqual(plan_visible_layer_merge([False, True, False, True], 2),
                         ([1, 1, 1, 0], 1, 2))
        self.assertFalse(plan_visible_layer_merge([False, True, False], 1))
        with patch("CORE.native_bridge.load_creative_core", return_value=None):
            self.assertIsNone(plan_visible_layer_merge([True, False, True], 2))
        self.assertEqual(plan_visible_layer_merge_groups(
            [True, True, False, True], [-1, 0, 0, 1], [False, True], 3),
            ([1, 0, 0, 1], [1, 1, 1, 0], 0, 0))
        with patch("DOCUMENTS.layer_manager.plan_visible_layer_merge_groups",
                   return_value=None):
            document = Document(16, 16)
            document.add_layer("Second")
            before = list(document.layers)
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                LayerManager(document).merge_visible()
            self.assertEqual(document.layers, before)

    def test_groups_compose_isolated_and_cache_tiles(self):
        canvas = Canvas()
        try:
            document = canvas.document
            document.width = document.height = 64
            bottom = document.layers[0]
            bottom.image = QImage(64, 64, QImage.Format.Format_ARGB32)
            bottom.image.fill(QtTransparent)
            red = document.add_layer("Red")
            red.image = QImage(64, 64, QImage.Format.Format_ARGB32)
            red.image.fill(QColor(255, 0, 0, 255))
            blue = document.add_layer("Blue")
            blue.image = QImage(64, 64, QImage.Format.Format_ARGB32)
            blue.image.fill(QColor(0, 0, 255, 255))
            group = document.group_layers([1, 2], "Paint")
            self.assertIsNotNone(group)
            group.opacity = .5
            for layer in document.layers:
                layer.commit_image_cache(force=True)

            rect = QRect(0, 0, 64, 64)
            entries, pending = canvas._tile_projection_layers(0, 0, rect)
            self.assertFalse(pending)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[1].image.pixelColor(5, 5), QColor(0, 0, 255, 255))
            self.assertEqual(entries[1].opacity, .5)
            composite = composite_layers(64, 64, entries)
            pixel = composite.pixelColor(5, 5)
            self.assertEqual(pixel.red(), 0)
            self.assertEqual(pixel.blue(), 255)
            self.assertIn(pixel.alpha(), (127, 128))
            cache_size = group.cache_size_bytes()
            self.assertGreater(cache_size, 0)
            canvas._tile_projection_layers(0, 0, rect)
            self.assertEqual(group.cache_size_bytes(), cache_size)
        finally:
            canvas.close()

    def test_document_composite_includes_isolated_group_properties(self):
        document = Document(2, 1)
        document.layers[0].image.fill(QtTransparent)
        red = document.add_layer("Red")
        red.image.fill(QColor(255, 0, 0, 255))
        blue = document.add_layer("Blue")
        blue.image.fill(QColor(0, 0, 255, 255))
        group = document.group_layers([1, 2], "Paint")
        group.opacity = 0.5

        composite = composite_document(document)
        pixel = composite.pixelColor(0, 0)
        self.assertEqual((pixel.red(), pixel.green(), pixel.blue()), (0, 0, 255))
        self.assertIn(pixel.alpha(), (127, 128))

        group.visible = False
        self.assertEqual(composite_document(document).pixelColor(0, 0).alpha(), 0)

        group.visible = True
        expected = composite_document(document).pixelColor(0, 0)
        self.assertTrue(LayerManager(document).flatten())
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(document.layer_groups, [])
        self.assertEqual(document.layers[0].image.pixelColor(0, 0), expected)

    def test_document_composite_run_plan_is_native_and_rejects_broken_groups(self):
        from CORE.native_bridge import plan_layer_composite_runs

        self.assertEqual(plan_layer_composite_runs([-1, 0, 0, -1, 1]),
                         [(0, 1, -1), (1, 3, 0), (3, 4, -1), (4, 5, 1)])
        document = Document(2, 1)
        first = document.add_layer("First")
        middle = document.add_layer("Middle")
        last = document.add_layer("Last")
        document.layer_groups.append(LayerGroup(
            name="Invalid legacy group", layer_ids=[first.id, last.id]))
        with self.assertRaisesRegex(ValueError, "contiguous"):
            composite_document_layers(document)

    def test_merge_visible_sparse_path_never_materializes_full_layers(self):
        document = Document(2048, 2048)
        bottom = document.layers[0]
        bottom.discard_image_cache()
        bottom.tile_store.clear_resident()
        upper = document.add_layer("Sparse upper")
        for layer, key, color in (
            (bottom, (0, 0), QColor("red")),
            (upper, (12, 7), QColor("blue")),
        ):
            tile = QImage(TILE_SIZE, TILE_SIZE,
                          QImage.Format.Format_ARGB32)
            tile.fill(color)
            layer.tile_store.set_tile(*key, tile)
            layer.discard_image_cache()

        with patch.object(TileStore, "materialize",
                          side_effect=AssertionError("full layer materialized")):
            self.assertTrue(LayerManager(document).merge_visible())

        self.assertEqual(len(document.layers), 1)
        merged = document.layers[0]
        self.assertEqual(merged.tile_store.occupied_keys, {(0, 0), (12, 7)})
        self.assertEqual(merged.tile_store.tile(0, 0).pixelColor(4, 4), QColor("red"))
        self.assertEqual(merged.tile_store.tile(12, 7).pixelColor(4, 4), QColor("blue"))

    def test_duplicate_layer_fails_cleanly_when_source_scratch_is_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Document(64, 64)
            layer = document.layers[0]
            layer.tile_store.set_scratch_directory(directory)
            tile = QImage(TILE_SIZE, TILE_SIZE, QImage.Format.Format_ARGB32)
            tile.fill(QColor("orange"))
            layer.tile_store.set_tile(0, 0, tile)
            layer.discard_image_cache()
            self.assertGreater(layer.tile_store.evict_tile_to_scratch(0, 0), 0)
            layer.tile_store._swapped[(0, 0)].write_bytes(b"broken")

            self.assertIsNone(LayerManager(document).duplicate_layer(0))
            self.assertEqual(len(document.layers), 1)
            self.assertTrue(layer.tile_store.has_tile(0, 0))
            self.assertFalse(layer.tile_store.tile_is_resident(0, 0))

    def test_group_csd_roundtrip_and_undo_redo(self):
        document = Document(16, 16)
        document.add_layer("Ink")
        document.add_layer("Light")
        history = TileHistory()
        history.begin(document)
        group = document.group_layers([1, 2], "Effects")
        group.visible = False
        group.opacity = .65
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(document.layer_groups, [])
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layer_groups[0].name, "Effects")
        self.assertFalse(document.layer_groups[0].visible)
        history.begin(document)
        document.layer_groups[0].opacity = .4
        document.layer_groups[0].invalidate()
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertAlmostEqual(document.layer_groups[0].opacity, .65)
        self.assertTrue(history.redo(document))
        self.assertAlmostEqual(document.layer_groups[0].opacity, .4)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "grouped.csd")
            self.assertTrue(CSDFormat.save(document, path))
            loaded = CSDFormat.load(path)
        self.assertIsNotNone(loaded)
        self.assertEqual([layer.name for layer in loaded.layers],
                         [layer.name for layer in document.layers])
        self.assertEqual(loaded.layer_groups[0].layer_ids,
                         document.layer_groups[0].layer_ids)
        self.assertFalse(loaded.layer_groups[0].visible)
        self.assertAlmostEqual(loaded.layer_groups[0].opacity, .4)

    def test_group_boundaries_duplicate_delete_and_reorder(self):
        document = Document(8, 8)
        document.layers[0].name = "A"
        for name in ("B", "C", "D"):
            document.add_layer(name)
        manager = LayerManager(document)
        group = document.group_layers([1, 2], "BC")
        self.assertIsNotNone(group)
        self.assertIsNone(document.group_layers([0, 3], "Invalid"))

        # Ungrouped layers cannot be moved into the middle of a group.
        self.assertFalse(manager.move_layer_up(0))
        self.assertEqual([layer.name for layer in document.layers], ["A", "B", "C", "D"])

        # The layer order is bottom to top: first reorder a member, then move the block.
        self.assertTrue(manager.move_layer_up(1))
        self.assertEqual([layer.name for layer in document.layers], ["A", "C", "B", "D"])
        self.assertEqual(group.layer_ids, [layer.id for layer in document.layers[1:3]])
        self.assertTrue(manager.move_layer_up(2))
        self.assertEqual([layer.name for layer in document.layers], ["C", "B", "A", "D"])
        self.assertEqual(group.layer_ids, [layer.id for layer in document.layers[:2]])

        duplicate = manager.duplicate_layer(0)
        self.assertIsNotNone(duplicate)
        self.assertIs(document.group_for_layer(duplicate.id), group)
        self.assertEqual(group.layer_ids, [layer.id for layer in document.layers[:3]])
        self.assertTrue(manager.remove_layer(1))
        self.assertNotIn(duplicate.id, group.layer_ids)
        self.assertTrue(set(group.layer_ids).issubset(
            {entry.id for entry in document.layers}
        ))

    def test_duplicate_layer_copies_only_sparse_tiles_and_all_properties(self):
        document = Document(512, 384)
        source = document.add_layer("Sparse ink")
        source.visible = False
        source.opacity = .37
        source.blend_mode = "multiply"
        source.blend_parameters = {"intensity": .8}
        source.locked = True
        source.lock_alpha = True
        source.clipping = True
        patch = QImage(64, 64, QImage.Format.Format_ARGB32)
        patch.fill(QColor(18, 90, 220, 190))
        self.assertTrue(source.tile_store.set_tile(7, 5, patch))

        duplicate = LayerManager(document).duplicate_layer(1)

        self.assertIsNotNone(duplicate)
        self.assertIsNone(duplicate._image_cache)
        self.assertEqual(duplicate.tile_store.occupied_keys, {(7, 5)})
        self.assertEqual(duplicate.tile_store.tile(7, 5).pixelColor(12, 13),
                         QColor(18, 90, 220, 190))
        self.assertEqual((duplicate.visible, duplicate.opacity, duplicate.blend_mode),
                         (False, .37, "multiply"))
        self.assertEqual(duplicate.blend_parameters, {"intensity": .8})
        self.assertTrue(duplicate.locked)
        self.assertTrue(duplicate.lock_alpha)
        self.assertTrue(duplicate.clipping)

    def test_layer_group_move_down_and_group_removal(self):
        document = Document(8, 8)
        document.layers[0].name = "A"
        for name in ("B", "C", "D"):
            document.add_layer(name)
        manager = LayerManager(document)
        group = document.group_layers([1, 2], "BC")
        self.assertTrue(manager.move_layer_down(1))
        self.assertEqual([layer.name for layer in document.layers], ["A", "D", "B", "C"])
        self.assertEqual(group.layer_ids, [layer.id for layer in document.layers[2:]])
        self.assertTrue(manager.remove_layer(2))
        self.assertIs(document.group_for_layer(document.layers[2].id), group)
        self.assertTrue(manager.remove_layer(2))
        self.assertEqual(document.layer_groups, [])

    def test_native_layer_removal_preserves_active_layer_and_group_members(self):
        document = Document(8, 8)
        for name in ("B", "C", "D"):
            document.add_layer(name)
        group = document.group_layers([1, 2], "BC")
        manager = LayerManager(document)
        document.active_layer_index = 3

        self.assertTrue(manager.remove_layer(1))
        self.assertEqual([layer.name for layer in document.layers], ["Arrière-plan", "C", "D"])
        self.assertEqual(document.active_layer_index, 2)
        self.assertEqual(group.layer_ids, [document.layers[1].id])

        document.active_layer_index = 1
        self.assertTrue(manager.remove_layer(1))
        self.assertEqual(document.active_layer_index, 1)
        self.assertEqual(group.layer_ids, [])
        self.assertNotIn(group, document.layer_groups)

    def test_layer_removal_requires_native_engine_without_mutating_on_failure(self):
        document = Document(8, 8)
        for name in ("B", "C"):
            document.add_layer(name)
        document.active_layer_index = 1
        manager = LayerManager(document)
        with patch("DOCUMENTS.layer_manager.remove_layer_stack", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                manager.remove_layer(1)
        self.assertEqual([layer.name for layer in document.layers],
                         ["Arrière-plan", "B", "C"])
        self.assertEqual(document.active_layer_index, 1)

    def test_merge_and_flatten_keep_group_references_valid(self):
        document = Document(8, 8)
        document.add_layer("Middle")
        document.add_layer("Top")
        manager = LayerManager(document)
        group = document.group_layers([1, 2], "Paint")
        self.assertIsNotNone(group)
        original_group_ids = list(group.layer_ids)

        history = TileHistory()
        history.begin(document)
        self.assertTrue(manager.merge_down(2))
        self.assertEqual(group.layer_ids, [document.layers[1].id])
        self.assertTrue(set(group.layer_ids).issubset({layer.id for layer in document.layers}))
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 3)
        self.assertEqual(document.layer_groups[0].layer_ids, original_group_ids)
        self.assertTrue(history.redo(document))
        group = document.layer_groups[0]
        self.assertEqual(group.layer_ids, [document.layers[1].id])

        history.begin(document)
        self.assertTrue(manager.flatten())
        self.assertEqual(document.layer_groups, [])
        self.assertEqual(len(document.layers), 1)
        self.assertTrue(history.commit(document))
        self.assertTrue(history.undo(document))
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(len(document.layer_groups), 1)
        self.assertTrue(history.redo(document))
        self.assertEqual(document.layer_groups, [])

    def test_merge_down_does_not_fallback_to_qpainter_when_core_is_missing(self):
        document = Document(8, 8)
        lower = document.get_active_layer()
        lower.image.fill(QColor("red"))
        upper = document.add_layer("Upper")
        upper.image.fill(QColor("blue"))
        before_layers = list(document.layers)
        before_pixel = lower.image.pixelColor(0, 0)
        with patch("DOCUMENTS.layer_manager.composite_layer_in_place",
                   return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                LayerManager(document).merge_down(1)
        self.assertEqual(document.layers, before_layers)
        self.assertEqual(lower.image.pixelColor(0, 0), before_pixel)

    def test_removing_layer_below_active_preserves_active_layer(self):
        document = Document(8, 8)
        document.add_layer("Middle")
        active = document.add_layer("Active")
        manager = LayerManager(document)

        self.assertTrue(manager.remove_layer(0))
        self.assertIs(document.get_active_layer(), active)
        self.assertEqual(document.active_layer_index, 1)

    def test_group_aware_reordering_uses_native_core(self):
        document = Document(8, 8)
        document.layers[0].name = "A"
        for name in ("B", "C", "D"):
            document.add_layer(name)
        manager = LayerManager(document)
        group = document.group_layers([1, 2], "BC")
        self.assertIsNotNone(group)

        self.assertTrue(manager.move_layer_up(1))
        self.assertEqual([layer.name for layer in document.layers], ["A", "C", "B", "D"])
        self.assertEqual(document.active_layer_index, 2)
        self.assertTrue(manager.move_layer_up(2))
        self.assertEqual([layer.name for layer in document.layers], ["C", "B", "A", "D"])
        self.assertEqual(document.active_layer_index, 1)
        self.assertTrue(manager.move_layer_down(1))
        self.assertEqual([layer.name for layer in document.layers], ["B", "C", "A", "D"])
        self.assertEqual(document.active_layer_index, 0)

    def test_layer_reordering_requires_native_engine(self):
        document = Document(8, 8)
        document.add_layer("Top")
        manager = LayerManager(document)
        with patch("DOCUMENTS.layer_manager.move_layer_stack", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                manager.move_layer_up(0)


QtTransparent = QColor(0, 0, 0, 0)


if __name__ == "__main__":
    unittest.main()
