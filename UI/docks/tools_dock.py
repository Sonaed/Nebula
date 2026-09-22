from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLayout,
    QPushButton,
    QLabel,
    QSlider,
    QFrame,
    QComboBox,
)

from PySide6.QtCore import Qt, QSettings
from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QPainter,
    QBrush,
    QColor,
    QPaintEvent,
    QImage,
    QRadialGradient,
)

from CANVAS.canvas import Canvas
from TOOLS.brush_preset_manager import BrushPresetManager


class BrushPreview(QFrame):

    def __init__(
        self,
        parent: QWidget | None = None
    ) -> None:

        super().__init__(
            parent
        )

        self.setObjectName(
            "brushPreview"
        )

        self.setMinimumHeight(
            90
        )

        self.setMaximumHeight(
            110
        )

        self.preview_size: float = 40.0

        self.preview_hardness: float = 0.35
        self.preview_settings: dict = {}

        self.setAttribute(
            Qt.WidgetAttribute.WA_OpaquePaintEvent,
            False
        )

    def set_brush(
        self,
        size: float,
        hardness: float
    ) -> None:

        self.preview_size = size

        self.preview_hardness = max(
            0.0,
            min(
                1.0,
                hardness
            )
        )

        self.update()

    def set_settings(self, settings: dict) -> None:
        """Render a small deterministic stroke using the active brush state."""
        self.preview_settings = dict(settings)
        self.set_brush(settings.get("size", 40.0), settings.get("hardness", 0.35))

    def paintEvent(
        self,
        event: QPaintEvent
    ) -> None:

        painter = QPainter(
            self
        )

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        painter.fillRect(
            self.rect(),
            QColor(
                21,
                23,
                26
            )
        )

        preview_diameter = max(
            4.0,
            min(
                self.preview_size,
                70.0
            )
        )

        radius = (
            preview_diameter
            / 2.0
        )

        hardness = (
            self.preview_hardness
        )

        center_x = (
            self.width()
            / 2.0
        )

        center_y = (
            self.height()
            / 2.0
        )

        painter.setPen(
            Qt.PenStyle.NoPen
        )

        # A compact stroke preview communicates spacing/opacity/flow much
        # better than a static dab while remaining cheap (the image is tiny).
        if self.preview_settings:
            image = QImage(180, 64, QImage.Format.Format_RGBA8888)
            image.fill(QColor(0, 0, 0, 0))
            settings = self.preview_settings
            color = QColor(*settings.get("color", [220, 220, 220, 255]))
            preview_painter = QPainter(image)
            preview_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            size = max(2.0, min(64.0, float(settings.get("size", 20.0))))
            opacity = max(0.0, min(1.0, float(settings.get("opacity", 1.0))))
            flow = max(0.0, min(1.0, float(settings.get("flow", 1.0))))
            hardness = max(0.0, min(1.0, float(settings.get("hardness", 0.8))))
            spacing = max(0.05, min(1.0, float(settings.get("spacing", 0.15))))
            steps = max(2, int(144.0 / max(1.0, size * spacing)))
            for index in range(steps + 1):
                t = index / steps
                center = QPointF(18.0 + 144.0 * t, 32.0)
                radius = size * (0.72 + 0.28 * t) * 0.5
                gradient = QRadialGradient(center, max(1.0, radius))
                solid = QColor(color)
                solid.setAlphaF(opacity * flow)
                transparent = QColor(solid)
                transparent.setAlpha(0)
                gradient.setColorAt(0.0, solid)
                gradient.setColorAt(hardness, solid)
                gradient.setColorAt(1.0, transparent)
                preview_painter.setPen(Qt.PenStyle.NoPen)
                preview_painter.setBrush(gradient)
                preview_painter.drawEllipse(center, radius, radius)
            preview_painter.end()
            target = self.rect().adjusted(4, 4, -4, -4)
            painter.drawImage(target, image)
            painter.end()
            return

        if hardness < 0.95:

            steps = 18

            for index in range(
                steps,
                0,
                -1
            ):

                factor = (
                    index
                    / steps
                )

                current_radius = (
                    radius
                    * factor
                )

                distance_from_center = (
                    1.0
                    - factor
                )

                alpha = int(
                    255
                    * max(
                        0.0,
                        1.0
                        - (
                            distance_from_center
                            / max(
                                1.0 - hardness,
                                0.01
                            )
                        )
                    )
                )

                alpha = max(
                    0,
                    min(
                        255,
                        alpha
                    )
                )

                painter.setBrush(
                    QBrush(
                        QColor(
                            225,
                            225,
                            225,
                            alpha
                        )
                    )
                )

                x = int(
                    round(
                        center_x
                        - current_radius
                    )
                )

                y = int(
                    round(
                        center_y
                        - current_radius
                    )
                )

                diameter = int(
                    round(
                        current_radius
                        * 2.0
                    )
                )

                painter.drawEllipse(
                    x,
                    y,
                    diameter,
                    diameter
                )

        else:

            painter.setBrush(
                QBrush(
                    QColor(
                        230,
                        230,
                        230
                    )
                )
            )

            x = int(
                round(
                    center_x
                    - radius
                )
            )

            y = int(
                round(
                    center_y
                    - radius
                )
            )

            diameter = int(
                round(
                    radius
                    * 2.0
                )
            )

            painter.drawEllipse(
                x,
                y,
                diameter,
                diameter
            )

        painter.end()


class ToolsDock(QDockWidget):

    def __init__(
        self,
        window: QWidget,
        canvas: Canvas
    ) -> None:

        super().__init__(
            "OUTILS",
            window
        )

        self.canvas: Canvas = canvas

        self.area = (
            Qt.DockWidgetArea.LeftDockWidgetArea
        )

        self.setObjectName(
            "ToolsDock"
        )

        self.setMinimumWidth(
            230
        )

        self.setMaximumWidth(
            320
        )

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.create_content()
        self.create_style()

    # =========================================================
    # CONTENU
    # =========================================================

    def create_content(
        self
    ) -> None:

        content = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            10,
            10,
            10,
            10
        )

        layout.setSpacing(
            7
        )

        content.setLayout(
            layout
        )

        self.setWidget(
            content
        )

        # =====================================================
        # IDENTITÉ
        # =====================================================

        title = QLabel(
            "CreativeSystem"
        )

        title.setObjectName(
            "appTitle"
        )

        layout.addWidget(
            title
        )

        version = QLabel(
            "DIGITAL PAINTING  ·  v0.2"
        )

        version.setObjectName(
            "appVersion"
        )

        layout.addWidget(
            version
        )

        layout.addSpacing(
            7
        )

        # =====================================================
        # OUTILS
        # =====================================================

        layout.addWidget(
            self.create_section_title(
                "OUTILS"
            )
        )

        tools_row_1 = QHBoxLayout()

        self.brush_button = QPushButton(
            "Pinceau"
        )

        self.brush_button.setObjectName(
            "toolButton"
        )

        self.eraser_button = QPushButton(
            "Gomme"
        )

        self.eraser_button.setObjectName(
            "toolButton"
        )

        tools_row_1.addWidget(
            self.brush_button
        )

        tools_row_1.addWidget(
            self.eraser_button
        )

        layout.addLayout(
            tools_row_1
        )

        tools_row_2 = QHBoxLayout()

        self.move_button = QPushButton(
            "Déplacer"
        )

        self.move_button.setObjectName(
            "toolButton"
        )

        self.move_button.setToolTip(
            "Déplacer le calque · M"
        )

        self.transform_button = QPushButton(
            "Transformer"
        )

        self.transform_button.setObjectName(
            "toolButton"
        )

        self.transform_button.setToolTip(
            "Transformer le calque · T"
        )

        tools_row_2.addWidget(
            self.move_button
        )

        tools_row_2.addWidget(
            self.transform_button
        )

        layout.addLayout(
            tools_row_2
        )

        tools_row_3 = QHBoxLayout()
        self.picker_button = QPushButton("Pipette")
        self.picker_button.setObjectName("toolButton")
        self.picker_button.setToolTip("Prélever la couleur composite · I")
        self.smudge_button = QPushButton("Smudge")
        self.smudge_button.setObjectName("toolButton")
        self.smudge_button.setToolTip("Mélanger et étaler la peinture · S")
        tools_row_3.addWidget(self.picker_button)
        tools_row_3.addWidget(self.smudge_button)
        layout.addLayout(tools_row_3)

        self.tool_buttons = {
            "brush": self.brush_button,
            "eraser": self.eraser_button,
            "move": self.move_button,
            "transform": self.transform_button,
            "picker": self.picker_button,
            "smudge": self.smudge_button,
        }
        for button in self.tool_buttons.values():
            button.setCheckable(True)
        self.set_active_tool("brush")

        self.move_button.clicked.connect(
            self.canvas.tools.set_move
        )

        self.transform_button.clicked.connect(
            self.canvas.tools.set_transform
        )


        # =====================================================
        # HISTORIQUE
        # =====================================================

        history_row = QHBoxLayout()

        self.undo_button = QPushButton(
            "↶"
        )

        self.undo_button.setToolTip(
            "Annuler"
        )

        self.redo_button = QPushButton(
            "↷"
        )

        self.redo_button.setToolTip(
            "Rétablir"
        )

        history_row.addWidget(
            self.undo_button
        )

        history_row.addWidget(
            self.redo_button
        )

        layout.addLayout(
            history_row
        )

        self.add_separator(
            layout
        )

        # =====================================================
        # DOCUMENT
        # =====================================================

        layout.addWidget(
            self.create_section_title(
                "DOCUMENT"
            )
        )

        self.new_button = QPushButton(
            "Nouveau"
        )

        self.open_button = QPushButton(
            "Ouvrir..."
        )

        self.save_button = QPushButton(
            "Enregistrer"
        )

        self.save_as_button = QPushButton(
            "Enregistrer sous..."
        )

        layout.addWidget(
            self.new_button
        )

        layout.addWidget(
            self.open_button
        )

        layout.addWidget(
            self.save_button
        )

        layout.addWidget(
            self.save_as_button
        )

        self.add_separator(
            layout
        )

        # =====================================================
        # COULEUR
        # =====================================================

        layout.addWidget(
            self.create_section_title(
                "COULEUR"
            )
        )

        self.color_button = QPushButton(
            "■   #000000"
        )

        self.color_button.setObjectName(
            "colorButton"
        )

        self.color_button.setMinimumHeight(
            34
        )

        layout.addWidget(
            self.color_button
        )

        self.add_separator(
            layout
        )

        # =====================================================
        # BROSSE
        # =====================================================

        layout.addWidget(
            self.create_section_title(
                "BROSSE"
            )
        )

        brush_card = QFrame()

        brush_card.setObjectName(
            "brushCard"
        )

        brush_layout = QVBoxLayout()

        brush_layout.setContentsMargins(
            9,
            9,
            9,
            9
        )

        brush_layout.setSpacing(
            6
        )

        brush_card.setLayout(
            brush_layout
        )

        layout.addWidget(
            brush_card
        )

        # -----------------------------------------------------
        # APERÇU
        # -----------------------------------------------------

        self.brush_preview = BrushPreview()

        brush_layout.addWidget(
            self.brush_preview
        )

        # -----------------------------------------------------
        # PRESET
        # -----------------------------------------------------

        preset_row = QHBoxLayout()

        self.preset_name = QLabel(
            "Soft Round"
        )

        self.preset_name.setObjectName(
            "presetName"
        )

        self.preset_type = QLabel(
            "PAINT"
        )

        self.preset_type.setObjectName(
            "presetType"
        )

        preset_row.addWidget(
            self.preset_name
        )

        preset_row.addStretch()

        preset_row.addWidget(
            self.preset_type
        )

        brush_layout.addLayout(
            preset_row
        )

        # -----------------------------------------------------
        # PRESET COMBO
        # -----------------------------------------------------

        self.preset_combo = QComboBox()

        self.preset_combo.setObjectName(
            "presetCombo"
        )

        self.preset_manager = BrushPresetManager()
        self.preset_combo.addItems(
            self.preset_manager.list_presets()
        )

        brush_layout.addWidget(
            self.preset_combo
        )

        self.preset_combo.currentTextChanged.connect(
            self.change_preset
        )
        # -----------------------------------------------------
        # TAILLE
        # -----------------------------------------------------

        self.size_value = QLabel(
            "10 px"
        )

        self.size_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Taille",
            self.size_value
        )

        self.size_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.size_slider.setRange(
            1,
            500
        )

        self.size_slider.setValue(
            10
        )

        brush_layout.addWidget(
            self.size_slider
        )

        # -----------------------------------------------------
        # OPACITÉ
        # -----------------------------------------------------

        self.opacity_value = QLabel(
            "100 %"
        )

        self.opacity_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Opacité",
            self.opacity_value
        )

        self.opacity_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.opacity_slider.setRange(
            1,
            100
        )

        self.opacity_slider.setValue(
            100
        )

        brush_layout.addWidget(
            self.opacity_slider
        )

        # -----------------------------------------------------
        # PRESSION → TAILLE
        # -----------------------------------------------------

        self.pressure_size_value = QLabel(
            "100 %"
        )

        self.pressure_size_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Pression → Taille",
            self.pressure_size_value
        )

        self.pressure_size_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.pressure_size_slider.setRange(
            0,
            100
        )

        self.pressure_size_slider.setValue(
            100
        )

        brush_layout.addWidget(
            self.pressure_size_slider
        )

        # -----------------------------------------------------
        # PRESSION → OPACITÉ
        # -----------------------------------------------------

        self.pressure_opacity_value = QLabel(
            "0 %"
        )

        self.pressure_opacity_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Pression → Opacité",
            self.pressure_opacity_value
        )

        self.pressure_opacity_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.pressure_opacity_slider.setRange(
            0,
            100
        )

        self.pressure_opacity_slider.setValue(
            0
        )

        brush_layout.addWidget(
            self.pressure_opacity_slider
        )

        # -----------------------------------------------------
        # ESPACEMENT
        # -----------------------------------------------------

        self.spacing_value = QLabel(
            "15 %"
        )

        self.spacing_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Espacement",
            self.spacing_value
        )

        self.spacing_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.spacing_slider.setRange(
            1,
            100
        )

        self.spacing_slider.setValue(
            15
        )

        brush_layout.addWidget(
            self.spacing_slider
        )

        # -----------------------------------------------------
        # STABILISATION
        # -----------------------------------------------------

        self.smoothing_value = QLabel(
            "0 %"
        )

        self.smoothing_value.setObjectName(
            "valueLabel"
        )

        self.add_parameter(
            brush_layout,
            "Stabilisation",
            self.smoothing_value
        )

        self.smoothing_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.smoothing_slider.setRange(
            0,
            100
        )

        preferences = QSettings("CreativeSystem", "CreativeSystem")
        stabilization_enabled = preferences.value("input/stabilization", True, bool)
        stabilization_amount = preferences.value("input/stabilization_amount", 20, int)
        self.smoothing_slider.setValue(
            max(0, min(100, stabilization_amount)) if stabilization_enabled else 0
        )

        brush_layout.addWidget(
            self.smoothing_slider
        )


        self.smoothing_slider.valueChanged.connect(

            self.change_smoothing

        )
        self.change_smoothing(self.smoothing_slider.value())

        layout.addStretch()

        self.update_brush_preview()

    # =========================================================
    # PRESET
    # =========================================================

    def change_smoothing(
        self,
        value: int
    ) -> None:

        self.canvas.tools.brush.set_smoothing(
            value / 100.0
        )

        self.smoothing_value.setText(
            f"{value} %"
        )

    def change_preset(
        self,
        name: str
    ) -> None:

        if not self.canvas.load_cpp_brush_preset(name):
            return
        self.sync_from_canvas(name)

    # =========================================================
    # APERÇU BROSSE
    # =========================================================

    def update_brush_preview(
        self
    ) -> None:

        brush = self.canvas.tools.brush

        self.brush_preview.set_brush(
            brush.size,
            brush.hardness
        )

    def sync_from_canvas(self, preset_name: str | None = None) -> None:
        """Rafraîchit les contrôles sans réécrire l'état canonique."""
        settings = self.canvas.get_cpp_brush_settings()
        controls = [
            (self.size_slider, round(float(settings["size"]))),
            (self.opacity_slider, round(float(settings["opacity"]) * 100)),
            (self.pressure_size_slider, 100 if settings["pressureSize"] else 0),
            (self.pressure_opacity_slider, 100 if settings["pressureOpacity"] else 0),
            (self.spacing_slider, round(float(settings["spacing"]) * 100)),
        ]
        for control, value in controls:
            blocked = control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(blocked)

        self.set_brush_size_value(controls[0][1])
        self.set_brush_opacity_value(controls[1][1])
        self.set_pressure_size_value(controls[2][1])
        self.set_pressure_opacity_value(controls[3][1])
        self.set_spacing_value(controls[4][1])
        if not isinstance(preset_name, str):
            preset_name = None
        if preset_name:
            self.preset_name.setText(preset_name)
            blocked = self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentText(preset_name)
            self.preset_combo.blockSignals(blocked)
        self.update_brush_preview()

    def set_active_tool(self, tool_name: str) -> None:
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool_name)

    # =========================================================
    # STYLE
    # =========================================================

    def create_style(
        self
    ) -> None:

        self.setStyleSheet(
            """
            QDockWidget {
                color: #e8edf7;
            }

            QDockWidget::title {
                background-color: #101727;
                color: #a0adc3;
                padding: 8px 11px;
                border: 1px solid #26344d;
                border-bottom: 0;
                font-size: 10px;
                font-weight: 700;
            }

            QDockWidget > QWidget {
                background-color: #101727;
                border: 1px solid #26344d;
            }

            QWidget {
                color: #e8edf7;
                font-size: 12px;
            }

            QLabel#appTitle {
                color: #f1f3ff;
                font-size: 17px;
                font-weight: 700;
            }

            QLabel#appVersion {
                color: #68758c;
                font-size: 9px;
                font-weight: 600;
            }

            QLabel#panelTitle {
                color: #8997b0;
                font-size: 9px;
                font-weight: 700;
            }

            QLabel#valueLabel {
                color: #a0adc3;
                font-size: 10px;
            }

            QLabel#parameterLabel {
                color: #b7c2d8;
                font-size: 10px;
            }

            QLabel#presetName {
                color: #e8edf7;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#presetType {
                color: #71809a;
                font-size: 8px;
                font-weight: 700;
            }

            QFrame#brushCard {
                background-color: #0c1321;
                border: 1px solid #202e46;
                border-radius: 6px;
            }

            QFrame#brushPreview {
                background-color: #0c1321;
                border: 1px solid #202e46;
                border-radius: 5px;
            }

            QPushButton {
                background-color: #1c2940;
                color: #e8edf7;
                border: 1px solid #26344d;
                border-radius: 5px;
                padding: 7px 9px;
                min-height: 18px;
            }

            QPushButton:hover {
                background-color: #253550;
                border-color: #7868d8;
            }

            QPushButton:pressed {
                background-color: #151f32;
            }

            QPushButton#toolButton {
                background-color: #151f32;
                font-weight: 600;
            }

            QPushButton#toolButton:checked {
                background-color: #332f59;
                border-color: #7868d8;
                color: #ffffff;
            }

            QPushButton#colorButton {
                background-color: #151f32;
                border-color: #33445f;
                font-weight: 600;
            }

            QComboBox#presetCombo {
                background-color: #151f32;
                color: #e8edf7;
                border: 1px solid #26344d;
                border-radius: 5px;
                padding: 6px 8px;
                min-height: 18px;
            }

            QComboBox#presetCombo:hover {
                border-color: #62c5d7;
            }

            QComboBox#presetCombo QAbstractItemView {
                background-color: #151f32;
                color: #e8edf7;
                border: 1px solid #26344d;
                selection-background-color: #332f59;
            }

            QSlider::groove:horizontal {
                height: 4px;
                background: #1c2940;
                border-radius: 2px;
            }

            QSlider::handle:horizontal {
                width: 11px;
                height: 11px;
                margin: -4px 0;
                background: #c5cce0;
                border-radius: 6px;
            }

            QSlider::handle:horizontal:hover {
                background: #62c5d7;
            }

            QFrame#separator {
                background-color: #26344d;
                max-height: 1px;
            }
            """
        )

    # =========================================================
    # UTILITAIRES
    # =========================================================

    def create_section_title(
        self,
        text: str
    ) -> QLabel:

        label = QLabel(
            text
        )

        label.setObjectName(
            "panelTitle"
        )

        return label

    def add_separator(
        self,
        layout: QVBoxLayout
    ) -> None:

        separator = QFrame()

        separator.setObjectName(
            "separator"
        )

        separator.setFrameShape(
            QFrame.Shape.HLine
        )

        separator.setFixedHeight(
            1
        )

        layout.addWidget(
            separator
        )

    def add_parameter(
        self,
        layout: QVBoxLayout,
        title: str,
        value_label: QLabel
    ) -> None:

        row = QHBoxLayout()

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "parameterLabel"
        )

        row.addWidget(
            title_label
        )

        row.addStretch()

        row.addWidget(
            value_label
        )

        layout.addLayout(
            row
        )

    # =========================================================
    # VALEURS
    # =========================================================

    def set_brush_size_value(
        self,
        value: int
    ) -> None:

        self.size_value.setText(
            f"{value} px"
        )

        self.brush_preview.set_brush(
            value,
            self.canvas.tools.brush.hardness
        )

    def set_brush_opacity_value(
        self,
        value: int
    ) -> None:

        self.opacity_value.setText(
            f"{value} %"
        )

    def set_pressure_size_value(
        self,
        value: int
    ) -> None:

        self.pressure_size_value.setText(
            f"{value} %"
        )

    def set_pressure_opacity_value(
        self,
        value: int
    ) -> None:

        self.pressure_opacity_value.setText(
            f"{value} %"
        )

    def set_spacing_value(
        self,
        value: int
    ) -> None:

        self.spacing_value.setText(
            f"{value} %"
        )

    def set_color(
        self,
        color_name: str
    ) -> None:

        self.color_button.setText(
            f"■   {color_name}"
        )
