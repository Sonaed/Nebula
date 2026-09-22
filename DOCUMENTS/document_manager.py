from DOCUMENTS.document import Document


class DocumentManager:

    def __init__(self) -> None:

        self.documents: list[Document] = []
        self.active_document: Document | None = None

    def new_document(
        self,
        width: int = 800,
        height: int = 600,
    ) -> Document:

        document = Document(
            width,
            height
        )

        self.documents.append(
            document
        )

        self.active_document = document

        return document

    def set_active_document(
        self,
        document: Document,
    ) -> None:

        if document in self.documents:

            self.active_document = document

    def close_document(
        self,
        document: Document,
    ) -> None:

        if document not in self.documents:
            return

        self.documents.remove(
            document
        )

        if self.active_document is document:

            if self.documents:

                self.active_document = (
                    self.documents[-1]
                )

            else:

                self.active_document = None

    def get_active_document(
        self
    ) -> Document | None:

        return self.active_document