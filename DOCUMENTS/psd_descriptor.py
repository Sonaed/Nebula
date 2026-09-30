"""Photoshop ActionDescriptor parser (pure Python, no dependency).

Used by the PSD reader for adjustment-layer settings (Color Lookup ``clrL``,
fill layers, Curves presets...).  Values are returned as plain Python
objects: dicts for descriptors, lists for VlLs, (unit, value) tuples for
UntF, bytes for tdta.  Unknown OSType codes stop parsing of that descriptor
cleanly instead of guessing.
"""
from __future__ import annotations

import struct


class DescriptorError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.o = offset

    def take(self, n: int) -> bytes:
        if n < 0 or self.o + n > len(self.data):
            raise DescriptorError("descripteur tronqué")
        chunk = self.data[self.o:self.o + n]
        self.o += n
        return chunk

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def key(self) -> str:
        length = self.u32()
        raw = self.take(length if length else 4)
        return raw.decode("latin-1")

    def unicode(self) -> str:
        count = self.u32()
        text = self.take(count * 2).decode("utf-16-be", "replace")
        return text.rstrip("\0")


def _value(r: _Reader, ostype: str):
    if ostype in ("Objc", "GlbO"):
        return _descriptor(r)
    if ostype == "VlLs":
        return [_value(r, r.take(4).decode("latin-1")) for _ in range(r.u32())]
    if ostype == "doub":
        return r.f64()
    if ostype == "UntF":
        unit = r.take(4).decode("latin-1")
        return (unit, r.f64())
    if ostype == "UnFl":
        unit = r.take(4).decode("latin-1")
        return (unit, [r.f64() for _ in range(r.u32())])
    if ostype == "TEXT":
        return r.unicode()
    if ostype == "enum":
        r.key()
        return r.key()
    if ostype == "long":
        return r.i32()
    if ostype == "comp":
        return struct.unpack(">q", r.take(8))[0]
    if ostype == "bool":
        return bool(r.take(1)[0])
    if ostype in ("type", "GlbC"):
        r.unicode()
        return r.key()
    if ostype == "alis":
        return r.take(r.u32())
    if ostype == "tdta":
        return r.take(r.u32())
    if ostype == "Pth ":
        return r.take(r.u32())
    if ostype == "obj ":
        items = []
        for _ in range(r.u32()):
            kind = r.take(4).decode("latin-1")
            if kind == "prop":
                r.unicode(); r.key(); items.append(r.key())
            elif kind == "Clss":
                r.unicode(); items.append(r.key())
            elif kind == "Enmr":
                r.unicode(); r.key(); r.key(); items.append(r.key())
            elif kind == "rele":
                r.unicode(); r.key(); items.append(r.u32())
            elif kind == "Idnt" or kind == "indx":
                items.append(r.u32())
            elif kind == "name":
                r.unicode(); r.key(); items.append(r.unicode())
            else:
                raise DescriptorError(f"référence inconnue {kind!r}")
        return items
    raise DescriptorError(f"type de descripteur inconnu {ostype!r}")


def _descriptor(r: _Reader) -> dict:
    result = {"_name": r.unicode(), "_class": r.key()}
    for _ in range(r.u32()):
        key = r.key()
        ostype = r.take(4).decode("latin-1")
        result[key] = _value(r, ostype)
    return result


def parse_descriptor(data: bytes, offset: int = 0) -> dict:
    """Parse a descriptor starting at ``offset`` (after its version field)."""
    return _descriptor(_Reader(data, offset))


def parse_versioned_descriptor(data: bytes, offset: int = 0) -> dict:
    """Parse ``u32 version (16)`` followed by a descriptor."""
    reader = _Reader(data, offset)
    version = reader.u32()
    if version != 16:
        raise DescriptorError(f"version de descripteur {version} non prise en charge")
    return _descriptor(reader)


__all__ = ["parse_descriptor", "parse_versioned_descriptor", "DescriptorError"]
