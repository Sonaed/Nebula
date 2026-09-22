from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


FLOAT_GROUPS = {
    "Base": [
        ("size", "Taille", 0.1, 1000.0, 1.0),
        ("opacity", "Opacité", 0.0, 1.0, 0.01),
        ("flow", "Flow", 0.0, 1.0, 0.01),
        ("hardness", "Dureté", 0.0, 1.0, 0.01),
        ("spacing", "Espacement", 0.001, 5.0, 0.01),
        ("roundness", "Rondeur", 0.01, 1.0, 0.01),
        ("angle", "Angle", -360.0, 360.0, 1.0),
        ("scatter", "Dispersion", 0.0, 5.0, 0.01),
        ("sizeJitter", "Variation taille", 0.0, 1.0, 0.01),
        ("rotationJitter", "Variation rotation", 0.0, 360.0, 1.0),
    ],
    "Pression": [
        ("minimumSize", "Taille minimale", 0.0, 1.0, 0.01),
        ("minimumOpacity", "Opacité minimale", 0.0, 1.0, 0.01),
        ("minimumFlow", "Flow minimal", 0.0, 1.0, 0.01),
        ("velocitySize", "Vitesse → taille", 0.0, 1.0, 0.01),
        ("velocityOpacity", "Vitesse → opacité", 0.0, 1.0, 0.01),
        ("velocityFlow", "Vitesse → flow", 0.0, 1.0, 0.01),
        ("tiltSize", "Inclinaison → taille", 0.0, 1.0, 0.01),
        ("tiltOpacity", "Inclinaison → opacité", 0.0, 1.0, 0.01),
        ("randomSize", "Aléatoire → taille", 0.0, 1.0, 0.01),
        ("randomOpacity", "Aléatoire → opacité", 0.0, 1.0, 0.01),
        ("velocitySpacing", "Vitesse → espacement", 0.0, 1.0, 0.01),
    ],
    "Texture": [
        ("textureStrength", "Intensité", 0.0, 1.0, 0.01),
        ("textureScale", "Échelle", 0.01, 20.0, 0.05),
        ("textureRandomScale", "Échelle aléatoire", 0.0, 1.0, 0.01),
        ("textureRandomOffset", "Décalage aléatoire", 0.0, 1.0, 0.01),
        ("textureBrightness", "Luminosité", -1.0, 1.0, 0.01),
        ("textureContrast", "Contraste", 0.0, 4.0, 0.05),
    ],
    "Couleur": [
        ("hueJitter", "Variation teinte", 0.0, 1.0, 0.01),
        ("saturationJitter", "Variation saturation", 0.0, 1.0, 0.01),
        ("brightnessJitter", "Variation luminosité", 0.0, 1.0, 0.01),
        ("gradientAmount", "Quantité gradient", 0.0, 1.0, 0.01),
    ],
    "Peinture / Wet": [
        ("paintMix", "Paint mix", 0.0, 1.0, 0.01),
        ("wetness", "Humidité", 0.0, 1.0, 0.01),
        ("pickup", "Pickup", 0.0, 1.0, 0.01),
        ("dilution", "Dilution", 0.0, 1.0, 0.01),
        ("smudge", "Smudge", 0.0, 1.0, 0.01),
        ("paintPersistence", "Persistance", 0.0, 1.0, 0.01),
        ("colorCarry", "Transport couleur", 0.0, 1.0, 0.01),
    ],
}

BOOL_GROUPS = {
    "Pression": [
        ("pressureSize", "Pression → taille"),
        ("pressureOpacity", "Pression → opacité"),
        ("pressureFlow", "Pression → flow"),
    ],
    "Texture": [
        ("textureMirror", "Miroir"),
        ("textureAffectOpacity", "Texture sur l’opacité"),
    ],
    "Couleur": [
        ("dirtyColor", "Dirty color"),
        ("strokeGradient", "Gradient du trait"),
        ("linearGradient", "Gradient linéaire"),
        ("radialGradient", "Gradient radial"),
    ],
    "Peinture / Wet": [
        ("wetMix", "Wet mix"),
        ("sampleCanvas", "Échantillonner le canvas"),
    ],
}


class BrushSettingsDialog(QDialog):
    """Éditeur de l'état canonique utilisé par le Canvas."""

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.setWindowTitle("Paramètres du brush C++")
        self.resize(620, 620)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        values = canvas.get_cpp_brush_settings()

        for group_name, fields in FLOAT_GROUPS.items():
            page = QWidget()
            form = QFormLayout(page)

            for key, label, minimum, maximum, step in fields:
                spin = QDoubleSpinBox()
                spin.setRange(minimum, maximum)
                spin.setDecimals(3)
                spin.setSingleStep(step)
                spin.setValue(float(values[key]))
                spin.valueChanged.connect(
                    lambda value, setting=key:
                    self.canvas.set_brush_setting(setting, value)
                )
                form.addRow(label, spin)

            for key, label in BOOL_GROUPS.get(group_name, []):
                check = QCheckBox()
                check.setChecked(bool(values[key]))
                check.toggled.connect(
                    lambda checked, setting=key:
                    self.canvas.set_brush_setting(setting, checked)
                )
                form.addRow(label, check)

            if group_name == "Texture":
                load_texture = QPushButton("Charger une texture bitmap…")
                load_texture.clicked.connect(self._load_texture)
                clear_texture = QPushButton("Retirer la texture")
                clear_texture.clicked.connect(self.canvas.clear_brush_texture)
                load_tip = QPushButton("Charger une pointe bitmap couleur…")
                load_tip.clicked.connect(self._load_bitmap_tip)
                clear_tip = QPushButton("Retirer la pointe bitmap")
                clear_tip.clicked.connect(self.canvas.clear_brush_bitmap_tip)
                form.addRow(load_texture)
                form.addRow(clear_texture)
                form.addRow(load_tip)
                form.addRow(clear_tip)

            if group_name == "Couleur":
                self._add_color_button(form, "color", "Couleur principale", values)
                self._add_color_button(form, "gradientColor", "Couleur gradient", values)

            if group_name == "Peinture / Wet":
                blend = QComboBox()
                blend.addItems(["Normal", "Multiply", "Screen", "Overlay", "Darken", "Lighten"])
                blend.setCurrentIndex(int(values["blendMode"]))
                blend.currentIndexChanged.connect(
                    lambda index: self.canvas.set_brush_setting("blendMode", index)
                )
                form.addRow("Mode de mélange", blend)

            tabs.addTab(page, group_name)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _add_color_button(self, form, key, label, values) -> None:
        button = QPushButton()
        self._update_color_button(button, values[key])

        def choose() -> None:
            current = self.canvas.get_cpp_brush_settings()[key]
            color = QColorDialog.getColor(QColor(*current), self, label)
            if color.isValid():
                rgba = [color.red(), color.green(), color.blue(), color.alpha()]
                self.canvas.set_brush_setting(key, rgba)
                self._update_color_button(button, rgba)

        button.clicked.connect(choose)
        form.addRow(label, button)

    def _load_texture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir une texture de pinceau",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
        )
        if path and not self.canvas.load_brush_texture(path):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Texture invalide",
                "Le moteur C++ n’a pas pu charger cette image. "
                "Choisis une image lisible de 4096 × 4096 pixels maximum.",
            )

    def _load_bitmap_tip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir une pointe de pinceau bitmap",
            "",
            "Image PNG (*.png)",
        )
        if path and not self.canvas.load_brush_bitmap_tip(path):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Pointe bitmap invalide",
                "Le moteur C++ n’a pas pu charger cette image. "
                "Choisis un PNG lisible de 4096 × 4096 pixels maximum.",
            )

    @staticmethod
    def _update_color_button(button, rgba) -> None:
        color = QColor(*rgba)
        button.setText(color.name(QColor.HexArgb))
        button.setStyleSheet(f"background: {color.name()};")


__all__ = ["BrushSettingsDialog"]
