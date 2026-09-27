import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
spec = importlib.util.spec_from_file_location("layer_drop", Path(__file__).resolve().parents[1] / "UI" / "models" / "layer_drop.py")
layer_drop = importlib.util.module_from_spec(spec); spec.loader.exec_module(layer_drop)
plan, filt = layer_drop.plan_layer_drop, layer_drop.filter_rows

L = lambda i, g=None: ("layer", i, g)
G = lambda g, parent=None: ("group", g, parent)


class DropPlanTests(unittest.TestCase):
    # pile (haut -> bas) : 5, [G: 4, 3], 2, 1, 0
    BEFORE = [L(5), G("g"), L(4, "g"), L(3, "g"), L(2), L(1), L(0)]

    def test_plain_reorder_has_no_group_changes(self):
        after = [L(2), L(5), G("g"), L(4, "g"), L(3, "g"), L(1), L(0)]
        order, changes = plan(self.BEFORE, after, {2})
        self.assertEqual(order, [0, 1, 3, 4, 5, 2])
        self.assertEqual(changes, {})

    def test_drop_between_children_joins_the_group(self):
        after = [L(5), G("g"), L(4, "g"), L(2), L(3, "g"), L(1), L(0)]
        order, changes = plan(self.BEFORE, after, {2})
        self.assertEqual(changes, {2: "g"})
        self.assertEqual(order, [0, 1, 3, 2, 4, 5])

    def test_drop_right_under_the_header_joins_the_group(self):
        after = [L(5), G("g"), L(2), L(4, "g"), L(3, "g"), L(1), L(0)]
        self.assertEqual(plan(self.BEFORE, after, {2})[1], {2: "g"})

    def test_drop_above_the_header_stays_outside(self):
        after = [L(5), L(2), G("g"), L(4, "g"), L(3, "g"), L(1), L(0)]
        self.assertEqual(plan(self.BEFORE, after, {2})[1], {})

    def test_dragging_a_child_out_of_its_group(self):
        after = [L(4, "g"), L(5), G("g"), L(3, "g"), L(2), L(1), L(0)]
        # 4 est maintenant au-dessus du calque 5 (racine) : il quitte le groupe
        order, changes = plan(self.BEFORE, after, {4})
        self.assertEqual(changes, {4: None})

    def test_child_dropped_below_the_group_leaves_it(self):
        # repositionné après le dernier enfant, au-dessus de la racine 2
        after = [L(5), G("g"), L(3, "g"), L(4), L(2), L(1), L(0)]
        self.assertEqual(plan(self.BEFORE, after, {4})[1], {4: None})

    def test_moving_a_folder_row_is_rejected(self):
        after = [G("g"), L(4, "g"), L(3, "g"), L(5), L(2), L(1), L(0)]
        self.assertIsNone(plan(self.BEFORE, after, set()))

    def test_last_row_means_outside(self):
        after = [L(5), G("g"), L(4, "g"), L(3, "g"), L(1), L(0), L(2)]
        self.assertEqual(plan(self.BEFORE, after, {2})[1], {})

    def test_multi_moves_share_the_same_target(self):
        before = [L(3), L(2), G("g"), L(1, "g"), L(0, "g")]
        after = [G("g"), L(1, "g"), L(3), L(2), L(0, "g")]
        _order, changes = plan(before, after, {3, 2})
        self.assertEqual(changes, {3: "g", 2: "g"})

    def test_nested_group_target_is_the_direct_owner(self):
        before = [L(4), G("p"), L(3, "p"), G("c", "p"), L(2, "c"), L(1, "c"), L(0)]
        after = [G("p"), L(3, "p"), G("c", "p"), L(4), L(2, "c"), L(1, "c"), L(0)]
        self.assertEqual(plan(before, after, {4})[1], {4: "c"})


class FilterTests(unittest.TestCase):
    ROWS = [("layer", 5, None, "Ciel"), ("group", "g", None, "Personnage"),
            ("layer", 4, "g", "Yeux"), ("layer", 3, "g", "Peau"),
            ("layer", 2, None, "Fond"), ("layer", 0, None, "Ciel bas")]

    def test_empty_text_shows_everything(self):
        self.assertEqual(filt(self.ROWS, "  "), set(range(6)))

    def test_layer_match_keeps_its_group_header(self):
        self.assertEqual(filt(self.ROWS, "yeux"), {1, 2})

    def test_case_insensitive_and_multiple_hits(self):
        self.assertEqual(filt(self.ROWS, "CIEL"), {0, 5})

    def test_group_name_match_shows_all_children(self):
        self.assertEqual(filt(self.ROWS, "person"), {1, 2, 3})

    def test_no_match_hides_everything(self):
        self.assertEqual(filt(self.ROWS, "zzz"), set())

    def test_nested_context_is_kept(self):
        rows = [("group", "p", None, "P"), ("group", "c", "p", "C"), ("layer", 1, "c", "needle")]
        self.assertEqual(filt(rows, "needle"), {0, 1, 2})


if __name__ == "__main__":
    unittest.main()
