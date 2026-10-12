"""Bounded deterministic regression subset of the extended stress runner."""
import unittest
from CPP_TEST.fuzz_undo_redo import run

class EditingSequenceTests(unittest.TestCase):
    def test_linear_history(self):
        for seed in (1, 7):
            with self.subTest(seed=seed):
                self.assertEqual(run(seed, 80)['status'], 'OK')

    def test_branched_history(self):
        for seed in (1, 11):
            with self.subTest(seed=seed):
                self.assertEqual(run(seed, 100, True)['status'], 'OK')
