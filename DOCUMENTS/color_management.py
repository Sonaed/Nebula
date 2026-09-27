"""Color-profile metadata and conversion helpers.

Qt owns the actual ICC transform when a profile is available.  Keeping the
profile name in the document metadata makes it survive Nebula/PSD round trips
without forcing every renderer to understand ICC internals.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PySide6.QtGui import QColorSpace, QImage


@dataclass(frozen=True)
class ColorProfile:
    name: str
    icc_bytes: bytes = b""

    @property
    def is_embedded(self) -> bool:
        return bool(self.icc_bytes)


SRGB = ColorProfile("sRGB")


def profile_from_image(image: QImage) -> ColorProfile:
    space = image.colorSpace()
    if not space.isValid():
        return SRGB
    description = bytes(space.iccProfile())
    return ColorProfile(space.description() or "embedded ICC", description)


def load_profile(path: str | Path) -> ColorProfile:
    data = Path(path).read_bytes()
    if len(data) < 128:
        raise ValueError("ICC profile is truncated")
    return ColorProfile(Path(path).stem, data)


def convert_to_profile(image: QImage, profile: ColorProfile) -> QImage:
    if profile.name.lower() == "srgb" and not profile.icc_bytes:
        result = QImage(image)
        result.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        return result
    space = QColorSpace.fromIccProfile(profile.icc_bytes)
    if not space.isValid():
        raise ValueError("Invalid ICC profile")
    result = QImage(image)
    if not result.convertToColorSpace(space):
        raise ValueError("Qt could not convert the image to the ICC profile")
    return result


__all__ = ["ColorProfile", "SRGB", "profile_from_image", "load_profile", "convert_to_profile"]
