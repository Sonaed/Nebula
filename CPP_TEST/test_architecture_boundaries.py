from __future__ import annotations

import unittest
from pathlib import Path


class ArchitectureBoundaryTests(unittest.TestCase):
    """Prevent production raster logic from drifting back into Python adapters."""

    ROOT = Path(__file__).resolve().parents[1]

    def test_document_and_tool_adapters_have_no_python_raster_fallback(self) -> None:
        forbidden = ("QPainter(", "QImage.copy(", ".copy()")
        allowed = set()
        violations = []
        for directory in (self.ROOT / "DOCUMENTS", self.ROOT / "TOOLS"):
            for path in sorted(directory.glob("*.py")):
                if path in allowed or path.name == "__init__.py":
                    continue
                text = path.read_text(encoding="utf-8")
                for marker in forbidden:
                    if marker in text:
                        violations.append(f"{path.relative_to(self.ROOT)}: {marker}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
