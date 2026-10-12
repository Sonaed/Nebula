from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
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
        ("flow", "Flux", 0.0, 1.0, 0.01),
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
        ("minimumFlow", "Flux minimal", 0.0, 1.0, 0.01),
        ("velocitySize", "Vitesse → taille", 0.0, 1.0, 0.01),
        ("velocityOpacity", "Vitesse → opacité", 0.0, 1.0, 0.01),
        ("velocityFlow", "Vitesse → flux", 0.0, 1.0, 0.01),
        ("tiltFollow", "Inclinaison → orientation", 0.0, 1.0, 0.01),
        ("tiltElongation", "Inclinaison → aplatissement", 0.0, 1.0, 0.01),
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
        ("gradientAmount", "Quantité de dégradé", 0.0, 1.0, 0.01),
    ],
    "Peinture / Wet": [
        ("paintMix", "Mélange", 0.0, 1.0, 0.01),
        ("wetness", "Humidité", 0.0, 1.0, 0.01),
        ("pickup", "Prélèvement", 0.0, 1.0, 0.01),
        ("dilution", "Dilution", 0.0, 1.0, 0.01),
        ("smudge", "Estompage", 0.0, 1.0, 0.01),
        ("paintPersistence", "Persistance", 0.0, 1.0, 0.01),
        ("colorCarry", "Transport couleur", 0.0, 1.0, 0.01),
    ],
    "Double pointe": [
        ("dualSizeRatio", "Taille de la 2ᵉ pointe", 0.05, 3.0, 0.01),
        ("dualSpacing", "Espacement", 0.01, 3.0, 0.01),
        ("dualScatter", "Dispersion", 0.0, 3.0, 0.01),
        ("dualCount", "Nombre", 1.0, 16.0, 1.0),
        ("dualHardness", "Dureté (pointe ronde)", 0.0, 1.0, 0.01),
    ],
}

# Photoshop's dual brush modes, in the engine's order.
DUAL_MODES = ["Produit", "Obscurcir", "Densité couleur +", "Densité linéaire +",
              "Incrustation", "Densité couleur −", "Mélange maximal", "Hauteur linéaire"]

BOOL_GROUPS = {
    "Base": [
        ("antialiasing", "Anticrénelage"),
        ("wrapAround", "Répéter aux bords de la toile"),
    ],
    "Pression": [
        ("pressureSize", "Pression → taille"),
        ("pressureOpacity", "Pression → opacité"),
        ("pressureFlow", "Pression → flux"),
    ],
    "Texture": [
        ("textureMirror", "Miroir"),
        ("textureAffectOpacity", "Texture sur l’opacité"),
    ],
    "Couleur": [
        ("dirtyColor", "Couleur sale (garde la couleur précédente)"),
        ("strokeGradient", "Dégradé le long du trait"),
        ("linearGradient", "Dégradé linéaire"),
        ("radialGradient", "Dégradé radial"),
    ],
    "Peinture / Wet": [
        ("wetMix", "Peinture humide"),
        ("sampleCanvas", "Prélever la couleur de la toile"),
    ],
    "Double pointe": [
        ("dualBrush", "Activer la double pointe"),
    ],
}


class BrushSettingsDialog(QDialog):
    """Éditeur de l'état canonique utilisé par le Canvas."""

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.setWindowTitle("Réglages du pinceau")
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
                percent = (minimum >= -1.0 and maximum <= 1.0 and step <= 0.01) or key in (
                    "spacing", "scatter", "dualSizeRatio", "dualSpacing", "dualScatter")
                scale = 100.0 if percent else 1.0
                spin.setRange(minimum * scale, maximum * scale)
                spin.setDecimals(0 if percent or step >= 1.0 else 2)
                spin.setSingleStep(1.0 if percent else step)
                spin.setSuffix(" %" if percent else (" °" if key in ("angle", "rotationJitter") else
                                                    (" px" if key == "size" else "")))
                spin.setValue(float(values[key]) * scale)
                spin.valueChanged.connect(
                    lambda value, setting=key, factor=scale:
                    self.canvas.set_brush_setting(setting, value / factor)
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
                blend.addItems(["Normal", "Produit", "Écran", "Incrustation", "Obscurcir", "Éclaircir"])
                blend.setCurrentIndex(int(values["blendMode"]))
                blend.currentIndexChanged.connect(
                    lambda index: self.canvas.set_brush_setting("blendMode", index)
                )
                form.addRow("Mode de mélange", blend)

            if group_name == "Double pointe":
                dual_mode = QComboBox()
                dual_mode.addItems(DUAL_MODES)
                dual_mode.setCurrentIndex(int(values.get("dualMode", 0)))
                dual_mode.currentIndexChanged.connect(
                    lambda index: self.canvas.set_brush_setting("dualMode", float(index)))
                form.addRow("Mode de fusion", dual_mode)

            tabs.addTab(page, {"Peinture / Wet": "Peinture", "Pression": "Dynamique"}.get(group_name, group_name))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Fermer")
        buttons.button(QDialogButtonBox.Close).setIcon(QIcon())
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
