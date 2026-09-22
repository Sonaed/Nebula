from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title: str, expanded: bool = False, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self.header = QPushButton(title)
        self.header.setObjectName("sectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(6, 3, 4, 5)
        self.content_layout.setSpacing(2)
        root.addWidget(self.header)
        root.addWidget(self.content)
        self.header.toggled.connect(self._toggle)
        self._toggle(expanded)

    def _toggle(self, expanded: bool) -> None:
        self.header.setText(("▾ " if expanded else "▸ ") + self.header.text()[2:])
        self.content.setVisible(expanded)

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)
