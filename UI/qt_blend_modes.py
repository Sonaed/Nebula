"""Qt-only composition mapping used by the presentation layer."""
from __future__ import annotations

from PySide6.QtGui import QPainter


_QT_NAMES = {
    "normal": "CompositionMode_SourceOver",
    "darken": "CompositionMode_Darken",
    "multiply": "CompositionMode_Multiply",
    "color_burn": "CompositionMode_ColorBurn",
    "lighten": "CompositionMode_Lighten",
    "screen": "CompositionMode_Screen",
    "color_dodge": "CompositionMode_ColorDodge",
    "overlay": "CompositionMode_Overlay",
    "soft_light": "CompositionMode_SoftLight",
    "hard_light": "CompositionMode_HardLight",
    "difference": "CompositionMode_Difference",
    "exclusion": "CompositionMode_Exclusion",
    "hue": "CompositionMode_HslHue",
    "saturation": "CompositionMode_HslSaturation",
    "color": "CompositionMode_HslColor",
    "luminosity": "CompositionMode_HslLuminosity",
}


def composition_mode(name: str):
    normalized = str(name or "normal").lower()
    qt_name = _QT_NAMES.get(normalized, _QT_NAMES["normal"])
    return getattr(
        QPainter.CompositionMode,
        qt_name,
        QPainter.CompositionMode.CompositionMode_SourceOver,
    )
