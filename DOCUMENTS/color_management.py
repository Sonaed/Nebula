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

    def validate(self) -> None:
        if self.icc_bytes and len(self.icc_bytes) < 128:
            raise ValueError("ICC profile is truncated")
        if self.icc_bytes and not QColorSpace.fromIccProfile(self.icc_bytes).isValid():
            raise ValueError("Invalid ICC profile")


@dataclass(frozen=True)
class SoftProofSettings:
    """Explicit, serializable output-intent policy for proof previews/exports."""
    profile: ColorProfile
    rendering_intent: str = "relative_colorimetric"
    black_point_compensation: bool = True
    paper_white: bool = False


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
    profile.validate()
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


def linearize(image: QImage) -> QImage:
    """Return an image tagged as linear sRGB without silently changing pixels."""
    result = QImage(image)
    result.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgbLinear))
    return result


def soft_proof(image: QImage, settings: SoftProofSettings) -> QImage:
    """Convert a proof image to the declared output intent.

    Qt performs the ICC transform; the policy object remains available to the
    UI/export layer so proof settings are never implicit or lost in a document.
    """
    settings.profile.validate()
    return convert_to_profile(image, settings.profile)


__all__ = ["ColorProfile", "SoftProofSettings", "SRGB", "profile_from_image", "load_profile", "convert_to_profile", "linearize", "soft_proof"]
