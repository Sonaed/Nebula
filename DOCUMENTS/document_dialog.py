from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
)

# Préréglages « prêts pour le pixel art » (module Pixel Art d'Existence).
# (nom, largeur, hauteur, tuile, palette, zoom)
PIXEL_PRESETS = [
    ("Icône 16 × 16", 16, 16, 0, "PICO-8", 32),
    ("Sprite 32 × 32", 32, 32, 16, "PICO-8", 16),
    ("Sprite 64 × 64", 64, 64, 16, "DawnBringer 16", 8),
    ("Tuile 16 × 16 (en boucle)", 16, 16, 16, "DawnBringer 16", 32),
    ("Tileset 128 × 128 · tuiles 16", 128, 128, 16, "DawnBringer 16", 6),
    ("Game Boy 160 × 144", 160, 144, 8, "Game Boy", 4),
    ("PICO-8 128 × 128", 128, 128, 8, "PICO-8", 6),
    ("Scène 320 × 180", 320, 180, 0, "DawnBringer 16", 4),
    ("Portrait 96 × 96", 96, 96, 0, "DawnBringer 16", 6),
    ("1-bit 64 × 64", 64, 64, 0, "1-bit", 8),
]


class DocumentDialog(QDialog):

    def __init__(
        self,
        parent: QWidget | None = None,
        pixel_art: bool = False,
    ) -> None:

        super().__init__(
            parent
        )

        self.setWindowTitle(
            "Nouveau document"
        )

        self.setFixedWidth(
            420
        )

        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        standard = QWidget()
        layout = QVBoxLayout(standard)
        self.tabs.addTab(standard, "Standard")
        self._pixel_enabled = bool(pixel_art)
        if self._pixel_enabled:
            self.tabs.addTab(self._build_pixel_tab(), "▦ Pixel Art")

        # =====================================================
        # FORMAT
        # =====================================================

        preset_title = QLabel(
            "Format"
        )

        layout.addWidget(
            preset_title
        )

        self.preset_combo = QComboBox()

        self.preset_combo.addItem(
            "Personnalisé",
            None
        )

        self.preset_combo.addItem(
            "800 × 600",
            (800, 600)
        )

        self.preset_combo.addItem(
            "1920 × 1080 (Full HD)",
            (1920, 1080)
        )

        self.preset_combo.addItem(
            "2560 × 1440 (QHD)",
            (2560, 1440)
        )

        self.preset_combo.addItem(
            "3840 × 2160 (4K UHD)",
            (3840, 2160)
        )

        layout.addWidget(
            self.preset_combo
        )

        # =====================================================
        # LARGEUR
        # =====================================================

        width_layout = QHBoxLayout()

        width_label = QLabel(
            "Largeur"
        )

        self.width_spin = QSpinBox()

        self.width_spin.setMinimum(
            1
        )

        self.width_spin.setMaximum(
            20000
        )

        self.width_spin.setValue(
            800
        )

        self.width_spin.setSuffix(
            " px"
        )

        width_layout.addWidget(
            width_label
        )

        width_layout.addWidget(
            self.width_spin
        )

        layout.addLayout(
            width_layout
        )

        # =====================================================
        # HAUTEUR
        # =====================================================

        height_layout = QHBoxLayout()

        height_label = QLabel(
            "Hauteur"
        )

        self.height_spin = QSpinBox()

        self.height_spin.setMinimum(
            1
        )

        self.height_spin.setMaximum(
            20000
        )

        self.height_spin.setValue(
            600
        )

        self.height_spin.setSuffix(
            " px"
        )

        height_layout.addWidget(
            height_label
        )

        height_layout.addWidget(
            self.height_spin
        )

        layout.addLayout(
            height_layout
        )

        # =====================================================
        # DPI
        # =====================================================

        dpi_layout = QHBoxLayout()

        dpi_label = QLabel(
            "Résolution"
        )

        self.dpi_spin = QSpinBox()

        self.dpi_spin.setMinimum(
            1
        )

        self.dpi_spin.setMaximum(
            2400
        )

        self.dpi_spin.setValue(
            300
        )

        self.dpi_spin.setSuffix(
            " DPI"
        )

        dpi_layout.addWidget(
            dpi_label
        )

        dpi_layout.addWidget(
            self.dpi_spin
        )

        layout.addLayout(
            dpi_layout
        )

        # =====================================================
        # FOND
        # =====================================================

        background_title = QLabel(
            "Fond"
        )

        layout.addWidget(
            background_title
        )

        self.background_combo = QComboBox()

        self.background_combo.addItem(
            "Blanc",
            "white"
        )

        self.background_combo.addItem(
            "Transparent",
            "transparent"
        )

        self.background_combo.addItem(
            "Noir",
            "black"
        )

        layout.addWidget(
            self.background_combo
        )

        # =====================================================
        # BOUTONS
        # =====================================================

        buttons_layout = QHBoxLayout()

        cancel_button = QPushButton(
            "Annuler"
        )

        create_button = QPushButton(
            "Créer"
        )

        buttons_layout.addWidget(
            cancel_button
        )

        buttons_layout.addWidget(
            create_button
        )

        outer.addLayout(
            buttons_layout
        )

        # =====================================================
        # CONNEXIONS
        # =====================================================

        self.preset_combo.currentIndexChanged.connect(
            self.change_preset
        )

        cancel_button.clicked.connect(
            self.reject
        )

        create_button.clicked.connect(
            self.accept
        )

    # =========================================================
    # PIXEL ART
    # =========================================================

    def _build_pixel_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(QLabel("Toile prête pour le pixel art"))
        self.pixel_list = QListWidget()
        for name, w, h, tile, palette, zoom in PIXEL_PRESETS:
            detail = f"{w} × {h} px · palette {palette}" + (f" · tuiles {tile}" if tile else "")
            item = QListWidgetItem(f"{name}\n   {detail}")
            item.setData(256, (w, h, tile, palette, zoom))
            self.pixel_list.addItem(item)
        self.pixel_list.addItem(QListWidgetItem("Personnalisé…"))
        self.pixel_list.currentRowChanged.connect(self._pixel_row)
        box.addWidget(self.pixel_list, 1)
        row = QHBoxLayout()
        self.pixel_w, self.pixel_h, self.pixel_tile = QSpinBox(), QSpinBox(), QSpinBox()
        for spin, label, value in ((self.pixel_w, "L", 32), (self.pixel_h, "H", 32), (self.pixel_tile, "Tuile", 16)):
            spin.setRange(0 if spin is self.pixel_tile else 1, 4096)
            spin.setValue(value)
            row.addWidget(QLabel(label))
            row.addWidget(spin)
        self.pixel_tile.setSpecialValueText("—")
        box.addLayout(row)
        self.pixel_background = QComboBox()
        self.pixel_background.addItem("Transparent", "transparent")
        self.pixel_background.addItem("Blanc", "white")
        self.pixel_background.addItem("Noir", "black")
        box.addWidget(self.pixel_background)
        self.pixel_wrap = QCheckBox("Dessin en boucle + aperçu mosaïque (tuile)")
        box.addWidget(self.pixel_wrap)
        self._pixel_extra = ("PICO-8", 16)
        self.pixel_list.setCurrentRow(1)
        return page

    def _pixel_row(self, row: int) -> None:
        item = self.pixel_list.item(row)
        data = item.data(256) if item else None
        custom = data is None
        for spin in (self.pixel_w, self.pixel_h, self.pixel_tile):
            spin.setEnabled(custom)
        if data:
            w, h, tile, palette, zoom = data
            self.pixel_w.setValue(w)
            self.pixel_h.setValue(h)
            self.pixel_tile.setValue(tile)
            self._pixel_extra = (palette, zoom)
            self.pixel_wrap.setChecked(w == h == tile)

    def is_pixel(self) -> bool:
        return self._pixel_enabled and self.tabs.currentIndex() == 1

    def get_pixel_preset(self) -> dict | None:
        if not self.is_pixel():
            return None
        w, h = self.pixel_w.value(), self.pixel_h.value()
        palette, zoom = self._pixel_extra
        if self.pixel_list.currentItem() is not None and self.pixel_list.currentItem().data(256) is None:
            zoom = max(1, min(32, 512 // max(w, h)))
        return {"tile": self.pixel_tile.value(), "palette": palette, "zoom": zoom,
                "wrap": self.pixel_wrap.isChecked()}

    # =========================================================
    # PRESETS
    # =========================================================

    def change_preset(
        self,
        index: int
    ) -> None:

        preset = self.preset_combo.itemData(
            index
        )

        if preset is None:

            self.width_spin.setEnabled(
                True
            )

            self.height_spin.setEnabled(
                True
            )

            return

        width, height = preset

        self.width_spin.setValue(
            width
        )

        self.height_spin.setValue(
            height
        )

        self.width_spin.setEnabled(
            False
        )

        self.height_spin.setEnabled(
            False
        )

    # =========================================================
    # VALEURS
    # =========================================================

    def get_dimensions(
        self
    ) -> tuple[int, int]:

        if self.is_pixel():
            return self.pixel_w.value(), self.pixel_h.value()
        return (
            self.width_spin.value(),
            self.height_spin.value()
        )

    def get_dpi(
        self
    ) -> int:

        return 72 if self.is_pixel() else self.dpi_spin.value()

    def get_background(
        self
    ) -> str:

        value = (self.pixel_background if self.is_pixel() else self.background_combo).currentData()

        if isinstance(
            value,
            str
        ):

            return value

        return "white"