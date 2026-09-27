"""Actions multi-sélection et groupes du panneau Calques (sans Qt : méthodes extraites par AST)."""
import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def extract(path, class_name, method_names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in method_names]
    module = ast.Module(body=body, type_ignores=[])
    namespace = {}
    exec(compile(module, str(path), "exec"), namespace)
    return {name: namespace[name] for name in method_names}


def app_class_name():
    tree = ast.parse((ROOT / "CORE" / "application.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
                isinstance(n, ast.FunctionDef) and n.name == "merge_selected_layers" for n in node.body):
            return node.name


METHODS = ("_selected_layer_targets", "remove_layer", "merge_selected_layers",
           "reorder_layers_into_groups", "duplicate_layer", "toggle_layer_visibility_at",
           "toggle_layer_lock")
APP = extract(ROOT / "CORE" / "application.py", app_class_name(), METHODS)


class FakeLayer:
    def __init__(self, layer_id):
        self.id, self.visible, self.locked = layer_id, True, False
        self.tile_store = SimpleNamespace(occupied_keys={(0, 0)})
    def commit_image_cache(self, *a, **k): pass


class FakeManager:
    def __init__(self, doc):
        self.doc, self.calls = doc, []
    def remove_layer(self, i):
        self.calls.append(("remove", i))
        if len(self.doc.layers) <= 1: return False
        self.doc.layers.pop(i); return True
    def duplicate_layer(self, i):
        self.calls.append(("dup", i))
        layer = FakeLayer(self.doc.layers[i].id + "'"); self.doc.layers.insert(i + 1, layer); return layer
    def merge_down(self, i):
        self.calls.append(("merge", i)); self.doc.layers.pop(i); return True
    def toggle_visibility(self, i):
        self.doc.layers[i].visible = not self.doc.layers[i].visible; self.calls.append(("vis", i)); return True
    def toggle_lock(self, i):
        self.doc.layers[i].locked = not self.doc.layers[i].locked; self.calls.append(("lock", i)); return True
    def reorder_layers(self, order, membership=None):
        self.calls.append(("reorder", list(order), dict(membership or {})))
        self.doc.layers[:] = [self.doc.layers[i] for i in order]; return True


def make_app(names, selected, active=0):
    doc = SimpleNamespace(layers=[FakeLayer(n) for n in names], active_layer_index=active,
                          move_layer_to_group=mock.Mock(return_value=True))
    app = SimpleNamespace()
    app.canvas = SimpleNamespace(document=doc, prune_gpu_layers=mock.Mock(), sync_gpu_layer=mock.Mock(),
                                 _projection_tile_signatures=mock.Mock(), update=mock.Mock())
    app.ui = SimpleNamespace(layers_dock=SimpleNamespace(get_selected_layer_indices=lambda: list(selected)))
    app.layer_manager = FakeManager(doc)
    app.refresh_layers = mock.Mock()
    app.statusBar = lambda: SimpleNamespace(showMessage=mock.Mock())
    history = SimpleNamespace(capture_layer_before=mock.Mock())
    def with_history(operation, changed=None, dirty_only=False, structure_only=False, prepare=None):
        if prepare: prepare(history)
        return operation()
    app._with_layer_history = with_history
    app.history = history
    for name, function in APP.items():
        setattr(app, name, function.__get__(app))
    return app


class MultiSelectTests(unittest.TestCase):
    def test_targets_are_the_selection_or_the_active_layer(self):
        self.assertEqual(make_app("abcd", [1, 2])._selected_layer_targets(), [1, 2])
        self.assertEqual(make_app("abcd", [3], active=2)._selected_layer_targets(), [2])
        self.assertEqual(make_app("abcd", [], active=-1)._selected_layer_targets(), [])

    def test_delete_removes_every_selected_layer_from_the_top_down(self):
        app = make_app("abcde", [1, 3])
        app.remove_layer()
        self.assertEqual([c for c in app.layer_manager.calls], [("remove", 3), ("remove", 1)])
        self.assertEqual([l.id for l in app.canvas.document.layers], ["a", "c", "e"])
        app.refresh_layers.assert_called()

    def test_deleting_everything_keeps_one_layer(self):
        app = make_app("abc", [0, 1, 2])
        app.remove_layer()
        self.assertEqual(len(app.canvas.document.layers), 1)

    def test_single_delete_still_works_on_the_active_layer(self):
        app = make_app("abc", [], active=1)
        app.remove_layer()
        self.assertEqual([l.id for l in app.canvas.document.layers], ["a", "c"])

    def test_duplicate_handles_every_selected_layer(self):
        app = make_app("abcd", [0, 2])
        app.duplicate_layer()
        self.assertEqual([l.id for l in app.canvas.document.layers], ["a", "a'", "b", "c", "c'", "d"])

    def test_eye_click_on_a_selected_layer_applies_to_the_whole_selection(self):
        app = make_app("abcd", [0, 1, 2])
        app.toggle_layer_visibility_at(1)
        self.assertEqual([l.visible for l in app.canvas.document.layers], [False, False, False, True])
        app.toggle_layer_visibility_at(2)              # tous cachés -> tous affichés
        self.assertEqual([l.visible for l in app.canvas.document.layers], [True, True, True, True])

    def test_eye_click_outside_the_selection_only_touches_that_layer(self):
        app = make_app("abcd", [0, 1])
        app.toggle_layer_visibility_at(3)
        self.assertEqual([l.visible for l in app.canvas.document.layers], [True, True, True, False])

    def test_lock_applies_one_state_to_all_selected_layers(self):
        app = make_app("abc", [0, 1, 2], active=0)
        app.canvas.document.layers[1].locked = True
        app.toggle_layer_lock()
        self.assertEqual([l.locked for l in app.canvas.document.layers], [True, True, True])
        app.toggle_layer_lock()
        self.assertEqual([l.locked for l in app.canvas.document.layers], [False, False, False])

    def test_merge_selection_merges_from_the_top_down(self):
        app = make_app("abcde", [1, 2, 3])
        app.merge_selected_layers()
        self.assertEqual(app.layer_manager.calls, [("merge", 3), ("merge", 2)])
        self.assertEqual(app.history.capture_layer_before.call_count, 3)

    def test_merge_refuses_a_gap(self):
        app = make_app("abcde", [0, 2])
        app.merge_selected_layers()
        self.assertEqual(app.layer_manager.calls, [])


class GroupDropTests(unittest.TestCase):
    def test_reorder_then_group_change_in_one_step(self):
        app = make_app("abcd", [])
        app.reorder_layers_into_groups([0, 2, 1, 3], {2: "g"})
        # ordre et appartenance partent ensemble : un seul rebuild natif côté manager
        self.assertEqual(app.layer_manager.calls, [("reorder", [0, 2, 1, 3], {"c": "g"})])
        app.canvas.document.move_layer_to_group.assert_not_called()
        app.refresh_layers.assert_called()

    def test_partial_permutation_is_restored_not_applied(self):
        app = make_app("abcd", [])
        app.reorder_layers_into_groups([0, 1, 3], {})
        self.assertEqual(app.layer_manager.calls, [])
        app.refresh_layers.assert_called()


class DocumentGroupTests(unittest.TestCase):
    def setUp(self):
        stubs = {n: mock.MagicMock() for n in (
            "PySide6", "PySide6.QtGui", "DOCUMENTS.layer", "DOCUMENTS.selection",
            "DOCUMENTS.canvas_objects", "CORE.native_bridge", "DOCUMENTS.color_management")}
        group_module = SimpleNamespace()
        from dataclasses import dataclass, field
        @dataclass
        class LayerGroup:
            name: str = "G"
            id: str = "g"
            layer_ids: list = field(default_factory=list)
            parent_id: str = None
            def invalidate(self): pass
        group_module.LayerGroup = LayerGroup
        stubs["DOCUMENTS.layer_group"] = group_module
        stubs["DOCUMENTS.color_management"].ColorProfile = object
        stubs["DOCUMENTS.color_management"].SRGB = None
        with mock.patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location("doc_under_test", ROOT / "DOCUMENTS" / "document.py")
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.Document, self.Group = module.Document, LayerGroup

    def make(self, names, groups):
        doc = SimpleNamespace(layers=[SimpleNamespace(id=n) for n in names], layer_groups=groups,
                              _native_state=mock.Mock())
        doc.move = self.Document.move_layer_to_group.__get__(doc)
        doc.repair = self.Document.repair_layer_groups.__get__(doc)
        return doc

    def test_layer_joins_a_group_and_membership_follows_stack_order(self):
        g = self.Group(id="g", layer_ids=["a", "c"])
        doc = self.make(["a", "b", "c"], [g])
        self.assertTrue(doc.move("b", "g"))
        self.assertEqual(g.layer_ids, ["a", "b", "c"])

    def test_layer_leaves_its_group(self):
        g = self.Group(id="g", layer_ids=["a", "b"])
        doc = self.make(["a", "b", "c"], [g])
        self.assertTrue(doc.move("b", None))
        self.assertEqual(g.layer_ids, ["a"])

    def test_empty_groups_are_removed(self):
        g = self.Group(id="g", layer_ids=["a"])
        doc = self.make(["a", "b"], [g])
        doc.move("a", None)
        self.assertEqual(doc.layer_groups, [])
        doc._native_state.remove_group.assert_called_once_with(0)

    def test_nested_target_joins_every_ancestor_and_leaves_siblings(self):
        parent = self.Group(id="p", layer_ids=["a", "b"])
        child = self.Group(id="c", layer_ids=["b"], parent_id="p")
        other = self.Group(id="o", layer_ids=["x"])
        doc = self.make(["a", "b", "x", "y"], [child, parent, other])
        doc.move("x", "c")
        self.assertEqual(sorted(child.layer_ids), ["b", "x"])
        self.assertIn("x", parent.layer_ids)
        self.assertNotIn(other, doc.layer_groups)     # vidé donc supprimé

    def test_moving_out_of_a_child_group_keeps_no_ancestor_membership(self):
        parent = self.Group(id="p", layer_ids=["a", "b"])
        child = self.Group(id="c", layer_ids=["b"], parent_id="p")
        doc = self.make(["a", "b", "y"], [child, parent])
        doc.move("b", None)
        self.assertEqual(parent.layer_ids, ["a"])
        self.assertNotIn(child, doc.layer_groups)

    def test_repair_fills_a_gap_left_by_a_layer_inserted_inside_a_group(self):
        g = self.Group(id="g", layer_ids=["a", "c"])
        doc = self.make(["a", "new", "c", "d"], [g])
        self.assertTrue(doc.repair())
        self.assertEqual(g.layer_ids, ["a", "new", "c"])

    def test_repair_is_a_noop_on_a_healthy_document(self):
        g = self.Group(id="g", layer_ids=["a", "b"])
        doc = self.make(["a", "b", "c"], [g])
        self.assertFalse(doc.repair())

    def test_repair_never_steals_a_layer_from_an_unrelated_group(self):
        g = self.Group(id="g", layer_ids=["a", "c", "d"])
        other = self.Group(id="o", layer_ids=["b"])
        doc = self.make(["a", "b", "c", "d"], [g, other])
        self.assertTrue(doc.repair())
        self.assertEqual(g.layer_ids, ["c", "d"])          # plus longue plage
        self.assertEqual(other.layer_ids, ["b"])

    def test_repair_handles_a_parent_missing_a_child_layer(self):
        parent = self.Group(id="p", layer_ids=["a", "c"])
        child = self.Group(id="c", layer_ids=["b", "c"], parent_id="p")
        doc = self.make(["a", "b", "c"], [child, parent])
        doc.repair()
        self.assertEqual(parent.layer_ids, ["a", "b", "c"])

    def test_repair_drops_dangling_ids_and_parents(self):
        g = self.Group(id="g", layer_ids=["a", "ghost"], parent_id="nope")
        doc = self.make(["a", "b"], [g])
        self.assertTrue(doc.repair())
        self.assertEqual((g.layer_ids, g.parent_id), (["a"], None))

    def test_unknown_group_is_refused(self):
        doc = self.make(["a"], [])
        self.assertFalse(doc.move("a", "nope"))


if __name__ == "__main__":
    unittest.main()
