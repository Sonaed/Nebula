from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
)


class DocumentDialog(QDialog):

    def __init__(
        self,
        parent: QWidget | None = None
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

        layout = QVBoxLayout()

        self.setLayout(
            layout
        )

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

        layout.addLayout(
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

        return (
            self.width_spin.value(),
            self.height_spin.value()
        )

    def get_dpi(
        self
    ) -> int:

        return self.dpi_spin.value()

    def get_background(
        self
    ) -> str:

        value = self.background_combo.currentData()

        if isinstance(
            value,
            str
        ):

            return value

        return "white"