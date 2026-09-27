from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)

from PySide6.QtCore import (
    Qt,
    Signal,
)
from pathlib import Path
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from UI.theme.palette import COLORS


class HomePage(QWidget):

    # Fixed seed keeps the star map calm and recognizable between launches.
    _STAR_FIELD = tuple(
        ((index * 73 + 19) % 997 / 997,
         (index * 131 + 47) % 991 / 991,
         0.6 + ((index * 17) % 10) / 10)
        for index in range(48)
    )

    new_document_requested = Signal()
    open_document_requested = Signal()
    recent_document_requested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None
    ) -> None:

        super().__init__(
            parent
        )

        self.setObjectName(
            "homePage"
        )

        # The welcome artwork is a static resource; scale it only when the
        # widget changes size so ordinary repaints stay inexpensive.
        artwork = Path(__file__).resolve().parents[1] / "resources" / "nebula_welcome.png"
        self._nebula_artwork = QImage(str(artwork))
        self._scaled_nebula = QImage()

        self.create_ui()
        self.create_style()

    def paintEvent(self, event) -> None:
        """Paint the nebula artwork with a dark veil for comfortable reading."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bounds = self.rect()
        painter.fillRect(bounds, QColor(COLORS["window"]))
        if not self._scaled_nebula.isNull():
            painter.drawImage(0, 0, self._scaled_nebula)
            # Preserve the image's saturated color while preventing bright
            # gas clouds from reducing contrast behind the home controls.
            painter.fillRect(bounds, QColor(4, 7, 16, 105))

        painter.setPen(Qt.PenStyle.NoPen)
        for x, y, strength in self._STAR_FIELD:
            alpha = int(18 + strength * 30)
            painter.setBrush(QColor(177, 201, 239, alpha))
            radius = 0.55 + strength * 0.65
            painter.drawEllipse(
                int(bounds.width() * x), int(bounds.height() * y),
                int(radius * 2), int(radius * 2),
            )
        # A handful of crisp blue-white beacons give the field depth without
        # turning the screen into a wallpaper that competes with the canvas.
        for x, y, color in ((0.12, 0.23, QColor(129, 203, 255, 110)),
                            (0.91, 0.55, QColor(255, 203, 134, 115)),
                            (0.72, 0.90, QColor(209, 170, 255, 100))):
            px, py = int(bounds.width() * x), int(bounds.height() * y)
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 48), 1))
            painter.drawLine(px - 5, py, px + 5, py)
            painter.drawLine(px, py - 5, px, py + 5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(px - 1, py - 1, 3, 3)
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._nebula_artwork.isNull() and not self.size().isEmpty():
            self._scaled_nebula = self._nebula_artwork.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Center-crop the expanded image once; paintEvent only blits it.
            x = max(0, (self._scaled_nebula.width() - self.width()) // 2)
            y = max(0, (self._scaled_nebula.height() - self.height()) // 2)
            self._scaled_nebula = self._scaled_nebula.copy(
                x, y, self.width(), self.height()
            )

    # =========================================================
    # UI
    # =========================================================

    def create_ui(
        self
    ) -> None:

        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(
            70,
            50,
            70,
            50
        )

        main_layout.setSpacing(
            0
        )

        self.setLayout(
            main_layout
        )

        # =====================================================
        # HEADER
        # =====================================================

        header_layout = QHBoxLayout()

        title_layout = QVBoxLayout()

        title_layout.setSpacing(
            2
        )

        title = QLabel(
            "CreativeSystem"
        )

        title.setObjectName(
            "homeTitle"
        )

        subtitle = QLabel(
            "NEBULA   /   ATELIER DE PEINTURE NUMÉRIQUE"
        )

        subtitle.setObjectName(
            "homeSubtitle"
        )

        title_layout.addWidget(
            title
        )

        title_layout.addWidget(
            subtitle
        )

        header_layout.addLayout(
            title_layout
        )

        header_layout.addStretch()

        version = QLabel(
            __import__("CORE.version", fromlist=["DISPLAY"]).DISPLAY
        )

        version.setObjectName(
            "homeVersion"
        )

        header_layout.addWidget(
            version,
            alignment=Qt.AlignmentFlag.AlignTop
        )

        main_layout.addLayout(
            header_layout
        )

        # =====================================================
        # ESPACE CENTRAL
        # =====================================================

        main_layout.addStretch()

        welcome = QLabel(
            "Peignez au cœur de votre univers"
        )

        welcome.setObjectName(
            "welcomeTitle"
        )

        welcome.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        main_layout.addWidget(
            welcome
        )

        description = QLabel(
            "Un atelier calme et précis, prêt à suivre votre geste où qu’il vous mène."
        )

        description.setObjectName(
            "welcomeDescription"
        )

        description.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        main_layout.addWidget(
            description
        )

        main_layout.addSpacing(
            35
        )

        # =====================================================
        # ACTIONS
        # =====================================================

        actions_layout = QHBoxLayout()

        actions_layout.setSpacing(
            16
        )

        actions_layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        # -----------------------------------------------------
        # NOUVEAU
        # -----------------------------------------------------

        self.new_button = QPushButton()

        self.new_button.setObjectName(
            "newDocumentButton"
        )

        self.new_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )

        new_layout = QVBoxLayout(
            self.new_button
        )

        new_layout.setContentsMargins(
            20,
            20,
            20,
            20
        )

        new_layout.setSpacing(
            6
        )

        new_icon = QLabel(
            "+"
        )

        new_icon.setObjectName(
            "actionIcon"
        )

        new_icon.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        new_title = QLabel(
            "Nouveau document"
        )

        new_title.setObjectName(
            "actionTitle"
        )

        new_title.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        new_description = QLabel(
            "Créer une nouvelle toile"
        )

        new_description.setObjectName(
            "actionDescription"
        )

        new_description.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        new_layout.addStretch()

        self.new_button.setFixedSize(240, 150)
        new_layout.addWidget(
            new_icon
        )
        new_layout.addWidget(
            new_title
        )
        new_layout.addWidget(
            new_description
        )
        new_layout.addStretch()

        actions_layout.addWidget(
            self.new_button
        )

        # -----------------------------------------------------
        # OUVRIR
        # -----------------------------------------------------

        self.open_button = QPushButton()

        self.open_button.setObjectName(
            "openDocumentButton"
        )

        self.open_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )

        open_layout = QVBoxLayout(
            self.open_button
        )

        open_layout.setContentsMargins(
            20,
            20,
            20,
            20
        )

        open_layout.setSpacing(
            6
        )

        open_icon = QLabel(
            "↗"
        )

        open_icon.setObjectName(
            "actionIcon"
        )

        open_icon.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        open_title = QLabel(
            "Ouvrir un document"
        )

        open_title.setObjectName(
            "actionTitle"
        )

        open_title.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        open_description = QLabel(
            "Ouvrir un fichier existant"
        )

        open_description.setObjectName(
            "actionDescription"
        )

        open_description.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        open_layout.addStretch()

        self.open_button.setFixedSize(240, 150)
        open_layout.addWidget(
            open_icon
        )
        open_layout.addWidget(
            open_title
        )
        open_layout.addWidget(
            open_description
        )
        open_layout.addStretch()

        actions_layout.addWidget(
            self.open_button
        )

        main_layout.addLayout(
            actions_layout
        )

        # =====================================================
        # RÉCENTS
        # =====================================================

        main_layout.addSpacing(
            55
        )

        recent_title = QLabel(
            "DOCUMENTS RÉCENTS"
        )

        recent_title.setObjectName(
            "sectionTitle"
        )

        main_layout.addWidget(
            recent_title
        )

        recent_frame = QFrame()

        recent_frame.setObjectName(
            "recentFrame"
        )

        recent_layout = QVBoxLayout()

        recent_layout.setContentsMargins(
            18,
            18,
            18,
            18
        )

        self.recent_label = QLabel(
            "Aucun document récent"
        )

        self.recent_label.setObjectName(
            "emptyRecent"
        )

        recent_layout.addWidget(
            self.recent_label,
            alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.recent_layout = recent_layout

        recent_frame.setLayout(
            recent_layout
        )

        main_layout.addWidget(
            recent_frame
        )

        # =====================================================
        # FOOTER
        # =====================================================

        main_layout.addStretch()

        footer = QLabel(
            "CREATIVESYSTEM NEBULA   ·   CONÇU POUR LE DESSIN, SANS DISTRACTION"
        )

        footer.setObjectName(
            "homeFooter"
        )

        footer.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        main_layout.addWidget(
            footer
        )

        # =====================================================
        # CONNECTIONS
        # =====================================================

        self.new_button.clicked.connect(
            self.new_document_requested.emit
        )

        self.open_button.clicked.connect(
            self.open_document_requested.emit
        )

    def set_recent_documents(self, paths: list[str]) -> None:
        """Render recent files as direct actions; missing files are omitted."""
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        valid = [str(Path(path)) for path in paths if Path(path).is_file()]
        if not valid:
            self.recent_label = QLabel("Aucun document récent")
            self.recent_label.setObjectName("emptyRecent")
            self.recent_layout.addWidget(self.recent_label, alignment=Qt.AlignmentFlag.AlignCenter)
            return
        for path in valid[:8]:
            button = QPushButton(f"{Path(path).name}\n{Path(path).parent}")
            button.setObjectName("recentDocument")
            button.setToolTip(path)
            button.setMinimumHeight(46)
            button.clicked.connect(lambda _checked=False, value=path: self.recent_document_requested.emit(value))
            self.recent_layout.addWidget(button)

    # =========================================================
    # STYLE
    # =========================================================

    def create_style(self) -> None:
        """Use the application-wide Nebula stylesheet."""
        return
