
from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat


# =============================================
# Création d'un document
# =============================================

document = Document(
    800,
    600
)

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

success = CSDFormat.save(
    document,
    "test.csd"
)

print(
    "Sauvegarde :",
    success
)

# =============================================
# Chargement
# =============================================

loaded_document = CSDFormat.load(
    "test.csd"
)

if loaded_document:

    print(
        "Document chargé !"
    )

    print(
        "Dimensions :",
        loaded_document.width,
        "x",
        loaded_document.height
    )

    print(
        "Nombre de calques :",
        len(
            loaded_document.layers
        )
    )

    for layer in (
        loaded_document.layers
    ):

        print(
            "-",
            layer.name
        )