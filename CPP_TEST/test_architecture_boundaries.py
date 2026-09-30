from __future__ import annotations

import unittest
from pathlib import Path


class ArchitectureBoundaryTests(unittest.TestCase):
    """Prevent production raster logic from drifting back into Python adapters."""

    ROOT = Path(__file__).resolve().parents[1]

    def test_document_and_tool_adapters_have_no_python_raster_fallback(self) -> None:
        forbidden = ("QPainter(", "QImage.copy(", ".copy()")
        # These two adapters are deliberate format/storage bridges: PSD
        # decoding needs a bounded Qt copy for its source rectangle, while the
        # tile store uses QPainter only to assemble a compatibility view. They
        # are not production brush/raster fallbacks.
        allowed_markers = {
            self.ROOT / "DOCUMENTS" / "blend_modes.py": {"QPainter("},
            self.ROOT / "DOCUMENTS" / "document.py": {".copy()"},
            self.ROOT / "DOCUMENTS" / "format_psd.py": {".copy()", "QPainter("},
            self.ROOT / "DOCUMENTS" / "layer.py": {"QPainter("},
            self.ROOT / "DOCUMENTS" / "psd_reader.py": {".copy()"},
            self.ROOT / "DOCUMENTS" / "selection.py": {".copy()"},
            self.ROOT / "DOCUMENTS" / "tile_store.py": {"QPainter("},
            self.ROOT / "TOOLS" / "retouch_tool.py": {".copy()"},
            self.ROOT / "TOOLS" / "selection_tools.py": {"QPainter("},
            self.ROOT / "TOOLS" / "transform_tool.py": {"QPainter(", ".copy()"},
        }
        allowed = set()
        violations = []
        for directory in (self.ROOT / "DOCUMENTS", self.ROOT / "TOOLS"):
            for path in sorted(directory.glob("*.py")):
                if path in allowed or path.name == "__init__.py":
                    continue
                text = path.read_text(encoding="utf-8")
                for marker in forbidden:
                    if marker in text and marker not in allowed_markers.get(path, set()):
                        violations.append(f"{path.relative_to(self.ROOT)}: {marker}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
