from __future__ import annotations

from pathlib import Path

from DOCUMENTS.document import Document
from DOCUMENTS.format_nebula import NebulaFormat, load_document


class RecoveryManager:
    """Atomic crash recovery snapshot for the current editable document."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else (
            Path.home() / ".local" / "share" / "CreativeSystem" / "recovery" / "current.nbl"
        )
        self.legacy_path = self.path.with_suffix(".csd")

    def save(self, document: Document) -> bool:
        return NebulaFormat.save(document, self.path)

    def load(self) -> Document | None:
        if self.path.is_file():
            return load_document(self.path)
        # Preserve an interrupted session created by the previous CSD build.
        return load_document(self.legacy_path) if self.legacy_path.is_file() else None

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
            self.legacy_path.unlink(missing_ok=True)
        except OSError:
            pass
