"""Nebula start page: clear entry points, formats, and recent documents."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QScrollArea,
)
from UI.theme.palette import COLORS


class _Artwork(QFrame):
    """Static, cached artwork confined to a welcome card."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeArtwork")
        self.setMinimumSize(250, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._source = QImage(str(Path(__file__).resolve().parents[1] / "resources" / "nebula_welcome.png"))
        self._scaled = QImage()
        box = QVBoxLayout(self)
        box.setContentsMargins(28, 24, 28, 24)
        box.addStretch()
        title = QLabel("Une toile.\nTout un univers.")
        title.setObjectName("artworkTitle")
        box.addWidget(title)
        caption = QLabel("NEBULA  /  ATELIER RASTER")
        caption.setObjectName("artworkCaption")
        box.addWidget(caption)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scaled = self._source.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(COLORS["panel"]))
        painter.drawImage((self.width()-self._scaled.width())//2,
                          (self.height()-self._scaled.height())//2, self._scaled)
        veil = QLinearGradient(0, 0, 0, self.height())
        veil.setColorAt(0, QColor(16, 18, 24, 10))
        veil.setColorAt(1, QColor(16, 18, 24, 235))
        painter.fillRect(self.rect(), veil)
        painter.end()


class HomePage(QWidget):
    new_document_requested = Signal()
    open_document_requested = Signal()
    recent_document_requested = Signal(str)
    preset_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("homeContent")
        scroll.setWidget(content)
        wrapper = QHBoxLayout(content)
        wrapper.setContentsMargins(32, 22, 32, 18)
        wrapper.addStretch()
        body = QWidget()
        body.setMaximumWidth(1120)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        wrapper.addWidget(body, 1)
        wrapper.addStretch()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QHBoxLayout()
        brand = QLabel("◈  NEBULA")
        brand.setObjectName("homeTitle")
        header.addWidget(brand)
        header.addStretch()
        from CORE.version import DISPLAY
        version = QLabel(DISPLAY + "  ·  CreativeSystem")
        version.setObjectName("homeVersion")
        header.addWidget(version)
        layout.addLayout(header)
        layout.addSpacing(8)

        hero = QHBoxLayout()
        hero.setSpacing(32)
        intro = QVBoxLayout()
        eyebrow = QLabel("VOTRE ATELIER NUMÉRIQUE")
        eyebrow.setObjectName("homeSubtitle")
        intro.addWidget(eyebrow)
        title = QLabel("Place à vos\nprochaines idées.")
        title.setObjectName("welcomeTitle")
        intro.addWidget(title)
        description = QLabel("Dessinez, peignez, explorez.\nVotre prochain projet commence ici.")
        description.setObjectName("welcomeDescription")
        description.setIndent(0)
        description.setMargin(0)
        intro.addWidget(description)
        intro.addSpacing(10)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.new_button = self._action_card("newDocumentButton", "+", "Nouveau document", "Une toile à votre mesure", "Ctrl+N")
        self.open_button = self._action_card("openDocumentButton", "↗", "Ouvrir un document", "Reprendre une création", "Ctrl+O")
        actions.addWidget(self.new_button)
        actions.addWidget(self.open_button)
        intro.addLayout(actions)
        hero.addLayout(intro, 3)
        self.artwork = _Artwork()
        hero.addWidget(self.artwork, 2)
        layout.addLayout(hero)

        heading = QLabel("PARTIR D’UN FORMAT")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        formats = QHBoxLayout()
        self.preset_buttons = {}
        for key, title, detail in (("illustration", "Illustration", "2 048 × 2 048 px"),
                                    ("a4", "Papier A4", "210 × 297 mm · 300 ppp"),
                                    ("storyboard", "Écran / storyboard", "1 920 × 1 080 px")):
            button = QPushButton(title + "   ↗\n" + detail)
            button.setObjectName("formatCard")
            button.setMinimumHeight(62)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, key=key: self.preset_requested.emit(key))
            formats.addWidget(button, 1)
            self.preset_buttons[key] = button
        layout.addLayout(formats)

        recent_header = QHBoxLayout()
        heading = QLabel("REPRENDRE UN PROJET")
        heading.setObjectName("sectionTitle")
        recent_header.addWidget(heading)
        recent_header.addStretch()
        note = QLabel("Documents récents")
        note.setObjectName("homeVersion")
        recent_header.addWidget(note)
        layout.addLayout(recent_header)
        recent = QFrame()
        recent.setObjectName("recentFrame")
        self.recent_frame = recent
        self.recent_layout = QVBoxLayout(recent)
        self.recent_layout.setContentsMargins(16, 12, 16, 12)
        self.recent_layout.setSpacing(4)
        layout.addWidget(recent)
        self.set_recent_documents([])
        layout.addStretch(1)
        footer = QLabel("B  Pinceau     E  Gomme     Espace  Déplacer     Tab  Mode focus     Ctrl+K  Commandes")
        footer.setObjectName("homeFooter")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.new_button.clicked.connect(self.new_document_requested.emit)
        self.open_button.clicked.connect(self.open_document_requested.emit)

    @staticmethod
    def _action_card(name, icon, title, description, shortcut):
        button = QPushButton()
        button.setObjectName(name)
        button.setMinimumSize(205, 150)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(title)
        box = QVBoxLayout(button)
        box.setContentsMargins(18, 12, 18, 14)
        box.setSpacing(5)
        top = QHBoxLayout()
        symbol = QLabel(icon)
        symbol.setObjectName("actionIcon")
        key = QLabel(shortcut)
        key.setObjectName("actionShortcut")
        top.addWidget(symbol)
        top.addStretch()
        top.addWidget(key)
        box.addLayout(top)
        box.addStretch()
        for text, style in ((title, "actionTitle"), (description, "actionDescription")):
            label = QLabel(text)
            label.setObjectName(style)
            label.setWordWrap(True)
            box.addWidget(label)
        for label in button.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return button

    @staticmethod
    def _recent_card(path: str) -> QPushButton:
        item = Path(path)
        button = QPushButton(
            f"{item.stem}    ·    {item.suffix.lstrip('.').upper()}\n{item.parent}")
        button.setObjectName("recentDocument")
        button.setToolTip(path)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(f"Ouvrir {item.stem}")
        button.setMinimumHeight(52)
        return button

    def set_recent_documents(self, paths):
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        valid = list(dict.fromkeys(str(Path(path)) for path in paths if Path(path).is_file()))
        if not valid:
            self.recent_label = QLabel("Votre prochaine création apparaîtra ici.\nCréez une toile ou ouvrez un document pour commencer.")
            self.recent_label.setObjectName("emptyRecent")
            self.recent_label.setMinimumHeight(56)
            self.recent_layout.addWidget(self.recent_label)
            self.recent_frame.setMinimumHeight(80)
            return
        visible = valid[:5]
        self.recent_frame.setMinimumHeight(24 + len(visible) * 52 + max(0, len(visible) - 1) * 4)
        for path in visible:
            button = self._recent_card(path)
            button.clicked.connect(lambda _=False, path=path: self.recent_document_requested.emit(path))
            self.recent_layout.addWidget(button)
