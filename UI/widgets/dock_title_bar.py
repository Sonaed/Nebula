from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QPushButton, QWidget


class DockTitleBar(QWidget):
    """Compact dock title that gets out of the way when it is redundant.

    A dock that sits in a tab group is already named by its tab: showing an
    extra "CALQUES" header under the "Calques" tab only stacked chrome on top
    of the content.  The header therefore collapses whenever the dock shares
    a tab group with another visible dock, and comes back when it is alone or
    floating (so it can still be identified, moved and closed).
    """

    EXPANDED_HEIGHT = 26

    def __init__(self, dock, title: str) -> None:
        super().__init__(dock)
        self._dock = dock
        self.setObjectName("dockTitleBar")
        self.setFixedHeight(self.EXPANDED_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(2)
        self._label = QLabel(title.upper())
        self._label.setObjectName("dockTitle")
        layout.addWidget(self._label)
        layout.addStretch()
        self._float_button = QPushButton("◇")
        self._float_button.setToolTip("Détacher / rattacher le panneau")
        self._close_button = QPushButton("×")
        self._close_button.setToolTip("Fermer le panneau (Fenêtre ▸ Panneaux pour le rouvrir)")
        for button in (self._float_button, self._close_button):
            button.setObjectName("dockTitleButton")
            button.setFixedSize(20, 20)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._float_button.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self._close_button.clicked.connect(dock.close)
        layout.addWidget(self._float_button)
        layout.addWidget(self._close_button)
        self._pending = False
        dock.topLevelChanged.connect(self.schedule_refresh)
        dock.visibilityChanged.connect(self.schedule_refresh)
        dock.dockLocationChanged.connect(self.schedule_refresh)
        self.schedule_refresh()

    def schedule_refresh(self, *_args) -> None:
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self.refresh)

    def _in_tab_group(self) -> bool:
        dock = self._dock
        window = dock.parentWidget()
        if dock.isFloating() or not isinstance(window, QMainWindow):
            return False
        try:
            siblings = window.tabifiedDockWidgets(dock)
        except RuntimeError:
            return False
        return any(sibling.isVisibleTo(window) for sibling in siblings)

    def refresh(self) -> None:
        self._pending = False
        try:
            collapsed = self._in_tab_group()
        except RuntimeError:  # dock already destroyed
            return
        height = 0 if collapsed else self.EXPANDED_HEIGHT
        if self.height() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)
        for child in (self._label, self._float_button, self._close_button):
            child.setVisible(not collapsed)
        # Siblings may need to expand/collapse too (e.g. a tab was closed).
        window = self._dock.parentWidget()
        if isinstance(window, QMainWindow):
            for sibling in window.tabifiedDockWidgets(self._dock):
                bar = sibling.titleBarWidget()
                if isinstance(bar, DockTitleBar) and not bar._pending:
                    expected = 0 if bar._in_tab_group() else bar.EXPANDED_HEIGHT
                    if bar.height() != expected:
                        bar.schedule_refresh()


class DockGrip(QWidget):
    """Slim, label-free handle for narrow docks such as the tool rail.

    The default title of a 54 px wide dock was elided to a meaningless "…".
    """

    def __init__(self, dock) -> None:
        super().__init__(dock)
        self.setObjectName("dockGrip")
        self.setFixedHeight(6)
        self.setToolTip("Glisser pour déplacer le panneau")
        self.setCursor(Qt.CursorShape.SizeAllCursor)


def install_dock_title(dock, title: str) -> None:
    dock.setTitleBarWidget(DockTitleBar(dock, title))


def install_dock_grip(dock) -> None:
    dock.setTitleBarWidget(DockGrip(dock))
