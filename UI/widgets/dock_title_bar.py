from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class DockTitleBar(QWidget):
    def __init__(self, dock, title: str) -> None:
        super().__init__(dock)
        self.setObjectName("dockTitleBar")
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 0, 3, 0)
        layout.setSpacing(1)
        label = QLabel(title.upper())
        label.setObjectName("dockTitle")
        layout.addWidget(label)
        layout.addStretch()
        float_button = QPushButton("◇")
        close_button = QPushButton("×")
        for button in (float_button, close_button):
            button.setFixedSize(21, 21)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        float_button.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        close_button.clicked.connect(dock.close)
        layout.addWidget(float_button)
        layout.addWidget(close_button)


def install_dock_title(dock, title: str) -> None:
    dock.setTitleBarWidget(DockTitleBar(dock, title))
