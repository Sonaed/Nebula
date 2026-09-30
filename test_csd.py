
from pathlib import Path
from tempfile import TemporaryDirectory

from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat


# =============================================
# Création d'un document
# =============================================

document = Document(800, 600)

# =============================================
# Ajout de calques
# =============================================

document.add_layer(
    "Sketch"
)

document.add_layer(
    "Lineart"
)

# =============================================
# Sauvegarde
# =============================================

with TemporaryDirectory(prefix="nebula-test-") as temp_dir:
    test_path = Path(temp_dir) / "test.csd"
    assert CSDFormat.save(document, str(test_path))
    loaded_document = CSDFormat.load(str(test_path))
    assert loaded_document is not None
    assert (loaded_document.width, loaded_document.height) == (800, 600)
    assert [layer.name for layer in loaded_document.layers][-2:] == ["Sketch", "Lineart"]
print("CSD round-trip: ok")
