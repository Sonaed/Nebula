import unittest
from unittest.mock import patch

from CORE.native_bridge import load_creative_core, validate_document_geometry
from DOCUMENTS.document import Document
from DOCUMENTS.layer_manager import LayerManager


class DocumentGeometryTests(unittest.TestCase):
    def test_geometry_rules_are_shared_with_creative_core(self):
        self.assertIsNotNone(load_creative_core())
        self.assertTrue(validate_document_geometry(800, 600, 300))
        self.assertTrue(validate_document_geometry(8000, 8000, 300,
                                                   maximum_pixels=64_000_000))
        self.assertFalse(validate_document_geometry(8001, 8000, 300,
                                                    maximum_pixels=64_000_000))
        self.assertFalse(validate_document_geometry(0, 600, 300))
        self.assertFalse(validate_document_geometry(800, 600, 9601))

    def test_document_rejects_geometry_before_selection_allocation(self):
        for width, height, dpi in ((0, 10, 300), (10, -1, 300),
                                   (9000, 9000, 300), (10, 10, 0)):
            with self.subTest(width=width, height=height, dpi=dpi):
                with self.assertRaises(ValueError):
                    Document(width, height, dpi)

    def test_document_does_not_reimplement_geometry_if_native_engine_is_missing(self):
        with patch("DOCUMENTS.document.validate_document_geometry", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CreativeCore is required"):
                Document(800, 600, 300)

    def test_document_layer_model_is_backed_by_native_state(self):
        document = Document(64, 64, 300)
        manager = LayerManager(document)
        manager.add_layer("Ink")
        self.assertEqual(document._native_state.layer_count, 2)
        self.assertEqual(document._native_state.active_layer, 1)
        self.assertTrue(manager.rename_layer(1, "Line art"))
        self.assertEqual(document._native_state.layer_info(1)["name"], "Line art")
        self.assertTrue(manager.set_opacity(1, 0.4))
        self.assertAlmostEqual(document._native_state.layer_info(1)["opacity"], 0.4)
        self.assertTrue(manager.toggle_visibility(1) is False)
        self.assertFalse(document._native_state.layer_info(1)["visible"])
        self.assertTrue(manager.remove_layer(1))
        self.assertEqual(document._native_state.layer_count, 1)

    def test_group_properties_use_native_document_state(self):
        document = Document(64, 64, 300)
        document.add_layer("Ink")
        group = document.group_layers([0, 1], "Paint")
        self.assertIsNotNone(group)
        self.assertEqual(document._native_state.group_count, 1)
        self.assertTrue(document.set_group_visibility(group.id, False))
        self.assertFalse(group.visible)
        self.assertTrue(document.set_group_opacity(group.id, 0.35))
        self.assertAlmostEqual(group.opacity, 0.35)
        self.assertEqual(document._native_state.group_count, 1)
        self.assertTrue(document.ungroup_layers(group.id))
        self.assertEqual(document._native_state.group_count, 0)
