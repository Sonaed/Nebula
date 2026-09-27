import sys
from pathlib import Path

# Racine du projet pour permettre les imports UI / TOOLS.
ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
)

from UI.docks.brush_presets_dock import (
    BrushPresetsDock,
)


class FakeCanvas:
    def __init__(self):
        self.current = None

    def load_cpp_brush_preset(
        self,
        name,
    ):
        self.current = name

        print(
            f"Fake Canvas → {name}"
        )

        return True

    def get_cpp_brush_settings(self):
        return {
            "size": 50.0,
            "opacity": 1.0,
            "flow": 1.0,
            "hardness": 0.8,
            "spacing": 0.15,
            "roundness": 1.0,
            "angle": 0.0,
            "scatter": 0.0,
            "sizeJitter": 0.0,
            "rotationJitter": 0.0,
            "textureStrength": 0.0,
            "textureScale": 1.0,
            "textureRandomScale": 0.0,
            "textureRandomOffset": 0.0,
            "textureBrightness": 0.0,
            "textureContrast": 1.0,
            "textureMirror": False,
            "textureAffectOpacity": True,
            "dirtyColor": False,
            "hueJitter": 0.0,
            "saturationJitter": 0.0,
            "brightnessJitter": 0.0,
            "strokeGradient": False,
            "linearGradient": True,
            "radialGradient": False,
            "gradientAmount": 0.0,
            "blendMode": 0,
            "paintMix": 1.0,
            "wetMix": False,
            "sampleCanvas": True,
            "wetness": 0.0,
            "pickup": 0.0,
            "dilution": 0.0,
            "smudge": 0.0,
            "paintPersistence": 1.0,
            "colorCarry": 1.0,
            "pressureSize": True,
            "pressureOpacity": False,
            "pressureFlow": False,
            "minimumSize": 0.01,
            "minimumOpacity": 0.0,
            "minimumFlow": 0.0,
            "eraser": False,
            "color": [20, 60, 220, 255],
            "gradientColor": [220, 70, 180, 255],
        }


app = QApplication(sys.argv)

window = QMainWindow()
window.resize(
    800,
    700
)

dock = BrushPresetsDock(
    FakeCanvas(),
    window,
)

from PySide6.QtCore import Qt

window.addDockWidget(
    Qt.DockWidgetArea.RightDockWidgetArea,
    dock,
)

window.show()

print(
    "✓ BrushPresetsDock test OK"
)

sys.exit(
    app.exec()
)
