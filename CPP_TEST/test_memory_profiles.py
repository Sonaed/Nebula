"""26.2 memory-budget policy regression checks (no window required)."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from CORE.memory_manager import MEMORY_PROFILES, recommended_limit_mb
from DOCUMENTS.psd_import import estimate_import_budget


class MemoryProfileTests(unittest.TestCase):
    def test_profiles_are_ordered_and_bounded(self):
        self.assertEqual(set(MEMORY_PROFILES), {"Prudent", "Équilibré", "Performance"})
        prudent, balanced, performance = (recommended_limit_mb(name) for name in MEMORY_PROFILES)
        self.assertLessEqual(prudent, balanced); self.assertLessEqual(balanced, performance)
        self.assertGreaterEqual(prudent, 512); self.assertLessEqual(performance, 65536)

    def test_psd_budget_reports_full_layer_cost_without_decoding_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "header-only.psd"
            path.write_bytes(b"8BPS" + struct.pack(">H", 1) + b"\0" * 6 + struct.pack(">HIIHH", 4, 8000, 8000, 8, 3))
            budget = estimate_import_budget(path)
        self.assertEqual(budget.per_full_layer_bytes, 8000 * 8000 * 4)
        self.assertGreater(budget.estimated_bytes, budget.per_full_layer_bytes)

    def test_invalid_psd_header_is_clear(self):
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"not-a-psd"); stream.flush()
            with self.assertRaises(ValueError): estimate_import_budget(stream.name)


if __name__ == "__main__": unittest.main()
