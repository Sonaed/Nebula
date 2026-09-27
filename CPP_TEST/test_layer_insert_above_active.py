"""Un nouveau calque se place juste au-dessus du calque actif (et dans son groupe)."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class FakeNative:
    def __init__(self):
        self.order_calls, self.selected = [], None
    def reorder_layers(self, order, active):
        self.order_calls.append((list(order), active)); return True
    def select_layer(self, index):
        self.selected = index; return True
    def reset_layers(self): pass
    def add_layer(self, name): return 0
    def set_layer_property(self, *a): return 1


class FakeDocument:
    def __init__(self, names, active, groups=()):
        self.layers = [SimpleNamespace(id=n, name=n) for n in names]
        self.active_layer_index = active
        self.layer_groups = list(groups)
        self._native_state = FakeNative()
        self.synced = 0
        for name in ("groups_containing", "repair_layer_groups", "move_layer_to_group"):
            setattr(self, name, getattr(DocumentClass, name).__get__(self))
    def add_layer(self, name):
        layer = SimpleNamespace(id=name, name=name)
        self.layers.append(layer)
        self.active_layer_index = len(self.layers) - 1
        return layer
    def get_active_layer(self):
        return self.layers[self.active_layer_index] if 0 <= self.active_layer_index < len(self.layers) else None
    def group_for_layer(self, layer_id):
        return next((g for g in self.layer_groups if layer_id in g.layer_ids), None)
    def sync_native_state(self):
        # CreativeCore refuse un groupe qui n'est pas une plage contiguë (erreur réelle constatée).
        positions = {layer.id: i for i, layer in enumerate(self.layers)}
        for group in self.layer_groups:
            found = sorted(positions[i] for i in group.layer_ids if i in positions)
            if found != list(range(found[0], found[-1] + 1)):
                raise RuntimeError("CreativeCore a refusé la restauration des groupes")
        self.synced += 1


def load_document_class():
    from dataclasses import dataclass, field
    stubs = {n: mock.MagicMock() for n in (
        "PySide6", "PySide6.QtGui", "DOCUMENTS.layer", "DOCUMENTS.selection",
        "DOCUMENTS.canvas_objects", "CORE.native_bridge", "DOCUMENTS.color_management")}
    stubs["DOCUMENTS.layer_group"] = SimpleNamespace(LayerGroup=object)
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("doc_for_insert", ROOT / "DOCUMENTS" / "document.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.Document


DocumentClass = None


def load_manager():
    stubs = {}
    for name in ("DOCUMENTS.document", "DOCUMENTS.layer", "DOCUMENTS.blend_modes", "CORE.native_bridge"):
        stubs[name] = mock.MagicMock(name=name)
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("lm_under_test", ROOT / "DOCUMENTS" / "layer_manager.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.LayerManager


class InsertAboveActiveTests(unittest.TestCase):
    def setUp(self):
        global DocumentClass
        DocumentClass = DocumentClass or load_document_class()
        self.LayerManager = load_manager()

    def names(self, doc):
        return [layer.id for layer in doc.layers]

    def test_new_layer_goes_right_above_the_active_one(self):
        doc = FakeDocument(["bg", "a", "b", "c"], active=1)
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(self.names(doc), ["bg", "a", "new", "b", "c"])
        self.assertEqual(doc.active_layer_index, 2)
        self.assertEqual(doc._native_state.order_calls[-1], ([0, 1, 4, 2, 3], 2))

    def test_active_top_layer_keeps_the_old_behaviour(self):
        doc = FakeDocument(["bg", "a"], active=1)
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(self.names(doc), ["bg", "a", "new"])
        self.assertEqual(doc.active_layer_index, 2)
        self.assertEqual(doc._native_state.order_calls, [])

    def test_no_active_layer_puts_it_on_top(self):
        doc = FakeDocument(["bg", "a"], active=-1)
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(self.names(doc), ["bg", "a", "new"])
        self.assertEqual(doc.active_layer_index, 2)

    def test_new_layer_joins_the_group_of_the_active_layer(self):
        group = SimpleNamespace(id="g", layer_ids=["a", "b"], parent_id=None, invalidate=mock.Mock())
        doc = FakeDocument(["bg", "a", "b", "c"], active=1, groups=[group])
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(group.layer_ids, ["a", "new", "b"])
        group.invalidate.assert_called()

    def test_new_layer_joins_every_ancestor_of_a_nested_group(self):
        parent = SimpleNamespace(id="p", layer_ids=["a", "b"], parent_id=None, invalidate=mock.Mock())
        child = SimpleNamespace(id="c", layer_ids=["b"], parent_id="p", invalidate=mock.Mock())
        doc = FakeDocument(["bg", "a", "b", "x"], active=2, groups=[child, parent])
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(child.layer_ids, ["b", "new"])
        self.assertEqual(parent.layer_ids, ["a", "b", "new"])

    def test_inserting_in_the_middle_of_a_group_never_hits_the_native_refusal(self):
        group = SimpleNamespace(id="g", layer_ids=["a", "b", "c"], parent_id=None, invalidate=mock.Mock())
        doc = FakeDocument(["bg", "a", "b", "c", "x"], active=2, groups=[group])
        self.LayerManager(doc).add_layer("new")            # ne doit pas lever
        self.assertEqual(group.layer_ids, ["a", "b", "new", "c"])
        self.assertEqual(self.names(doc), ["bg", "a", "b", "new", "c", "x"])

    def test_reorder_with_membership_rebuilds_natively_only_when_contiguous(self):
        group = SimpleNamespace(id="g", layer_ids=["a", "b"], parent_id=None, invalidate=mock.Mock())
        doc = FakeDocument(["a", "b", "z"], active=0, groups=[group])
        # z est déposé entre a et b et rejoint le groupe
        self.LayerManager(doc).reorder_layers([0, 2, 1], {"z": "g"})
        self.assertEqual(group.layer_ids, ["a", "z", "b"])
        self.assertEqual(self.names(doc), ["a", "z", "b"])

    def test_layer_outside_groups_stays_outside(self):
        group = SimpleNamespace(id="g", layer_ids=["b"], parent_id=None, invalidate=mock.Mock())
        doc = FakeDocument(["bg", "a", "b"], active=1, groups=[group])
        self.LayerManager(doc).add_layer("new")
        self.assertEqual(group.layer_ids, ["b"])


if __name__ == "__main__":
    unittest.main()
