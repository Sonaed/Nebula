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
    QFrame,
    QGridLayout,
)

from PySide6.QtCore import Qt
from UI.widgets.document_preview import _CanvasPreview

# Dimensions are stored in pixels; print presets explicitly carry their DPI.
DOCUMENT_PRESETS = (
    ("illustration", "Illustration · carré", 2048, 2048, 300),
    ("storyboard", "Écran / storyboard · Full HD", 1920, 1080, 72),
    ("portrait", "Portrait · illustration", 2400, 3200, 300),
    ("a4", "Papier A4 · 210 × 297 mm", 2480, 3508, 300),
    ("a3", "Papier A3 · 297 × 420 mm", 3508, 4961, 300),
    ("4k", "Écran · 4K UHD", 3840, 2160, 72),
    ("vertical", "Écran vertical · 9:16", 1080, 1920, 72),
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

    def __init__(self, parent: QWidget | None = None, pixel_art: bool = False,
                 preset: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nouveau document")
        self.setObjectName("newDocumentDialog")
        self.setMinimumWidth(680)
        self.resize(720, 560)
        self._updating_dimensions = False
        self._aspect_ratio = 4 / 3
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        title = QLabel("Une nouvelle toile.")
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        subtitle = QLabel("Choisissez un format, puis faites-le vôtre.")
        subtitle.setObjectName("dialogDescription")
        outer.addWidget(subtitle)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        standard = QWidget()
        self.tabs.addTab(standard, "Dessin · peinture")
        self._pixel_enabled = bool(pixel_art)
        if self._pixel_enabled:
            self.tabs.addTab(self._build_pixel_tab(), "Pixel Art")
        layout = QHBoxLayout(standard)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(24)
        form = QVBoxLayout()
        form.setSpacing(12)
        form.addWidget(QLabel("FORMAT DE DÉPART"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Personnalisé", None)
        for key, name, w, h, dpi in DOCUMENT_PRESETS:
            self.preset_combo.addItem(name, (w, h, dpi, key))
        form.addWidget(self.preset_combo)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.width_spin, self.height_spin, self.dpi_spin = QSpinBox(), QSpinBox(), QSpinBox()
        for row, (label, spin, value, maximum, suffix) in enumerate((
            ("Largeur", self.width_spin, 800, 20000, " px"),
            ("Hauteur", self.height_spin, 600, 20000, " px"),
            ("Résolution", self.dpi_spin, 300, 2400, " ppp"),
        )):
            spin.setRange(1, maximum)
            spin.setValue(value)
            spin.setSuffix(suffix)
            spin.setMinimumWidth(128)
            spin.setAccessibleName(label)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(spin, row, 1)
        form.addLayout(grid)
        row = QHBoxLayout()
        self.aspect_lock = QCheckBox("Lier les proportions")
        self.aspect_lock.toggled.connect(self._set_aspect_lock)
        row.addWidget(self.aspect_lock)
        self.swap_button = QPushButton("⇄")
        self.swap_button.setToolTip("Permuter largeur et hauteur")
        self.swap_button.setAccessibleName("Permuter largeur et hauteur")
        self.swap_button.clicked.connect(self.swap_orientation)
        row.addWidget(self.swap_button)
        form.addLayout(row)
        form.addWidget(QLabel("ARRIÈRE-PLAN"))
        self.background_combo = QComboBox()
        for name, value in (("Blanc", "white"), ("Transparent", "transparent"), ("Noir", "black")):
            self.background_combo.addItem(name, value)
        form.addWidget(self.background_combo)
        form.addStretch()
        layout.addLayout(form, 1)
        panel = QFrame()
        panel.setObjectName("documentPreviewPanel")
        preview_layout = QVBoxLayout(panel)
        self.preview = _CanvasPreview()
        preview_layout.addWidget(self.preview, 1)
        self.estimate_label = QLabel()
        self.estimate_label.setObjectName("documentEstimate")
        self.estimate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.estimate_label.setWordWrap(True)
        preview_layout.addWidget(self.estimate_label)
        layout.addWidget(panel, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.create_button = QPushButton("Créer la toile")
        self.create_button.setObjectName("documentCreate")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        outer.addLayout(buttons)
        self.preset_combo.currentIndexChanged.connect(self.change_preset)
        self.width_spin.valueChanged.connect(lambda _: self._dimension_changed("width"))
        self.height_spin.valueChanged.connect(lambda _: self._dimension_changed("height"))
        self.dpi_spin.valueChanged.connect(self._dpi_changed)
        self.background_combo.currentIndexChanged.connect(self._update_preview)
        if preset:
            for index in range(1, self.preset_combo.count()):
                if self.preset_combo.itemData(index)[3] == preset:
                    self.preset_combo.setCurrentIndex(index)
                    break
        self._update_preview()

    def _set_aspect_lock(self, checked):
        self._aspect_ratio = self.width_spin.value() / self.height_spin.value()

    def _dimension_changed(self, axis):
        if self._updating_dimensions:
            return
        self._updating_dimensions = True
        try:
            if self.aspect_lock.isChecked():
                if axis == "width":
                    intended = round(self.width_spin.value() / self._aspect_ratio)
                    self.height_spin.setValue(intended)
                    if self.height_spin.value() != intended:
                        self.width_spin.setValue(round(self.height_spin.value() * self._aspect_ratio))
                else:
                    intended = round(self.height_spin.value() * self._aspect_ratio)
                    self.width_spin.setValue(intended)
                    if self.width_spin.value() != intended:
                        self.height_spin.setValue(round(self.width_spin.value() / self._aspect_ratio))
            self.preset_combo.setCurrentIndex(0)
        finally:
            self._updating_dimensions = False
        self._update_preview()

    def swap_orientation(self):
        self._updating_dimensions = True
        try:
            w, h = self.get_dimensions()
            self.width_spin.setValue(h)
            self.height_spin.setValue(w)
            self._aspect_ratio = h / w
            self.preset_combo.setCurrentIndex(0)
        finally:
            self._updating_dimensions = False
        self._update_preview()

    def _dpi_changed(self, *_):
        if not self._updating_dimensions:
            self.preset_combo.setCurrentIndex(0)
        self._update_preview()

    def _update_preview(self, *_):
        w, h = self.width_spin.value(), self.height_spin.value()
        dpi = self.dpi_spin.value()
        self.preview.dimensions = (w, h)
        self.preview.background = self.background_combo.currentData()
        self.preview.update()
        self.estimate_label.setText(
            f"{w/dpi*25.4:.1f} × {h/dpi*25.4:.1f} mm à {dpi} ppp\n"
            f"{w*h/1_000_000:.1f} Mpx · {w*h*4/1048576:.1f} Mio / calque RGBA\n"
            "Estimation hors historique et caches")

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

    def change_preset(self, index: int) -> None:
        preset = self.preset_combo.itemData(index)
        if preset is None or self._updating_dimensions:
            return
        width, height, dpi, _key = preset
        self._updating_dimensions = True
        try:
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
            self.dpi_spin.setValue(dpi)
            self._aspect_ratio = width / height
        finally:
            self._updating_dimensions = False
        self._update_preview()

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