"""Compatibility helpers for legacy CSLZ scratch tiles.

All codec calls cross the shared CreativeCore bridge; this module owns only
the legacy raw-versus-compressed file-format policy.
"""
from __future__ import annotations

from CORE.native_bridge import (
    encode_cslz_bytes,
    decode_cslz_bytes,
    lz4_compress_bytes,
    lz4_decompress_bytes,
)


def compress(data: bytes) -> tuple[bytes, bool]:
    packed = lz4_compress_bytes(data)
    if packed is None or len(packed) >= len(data):
        return data, False
    return packed, True


def decompress(data: bytes, size: int, compressed: bool) -> bytes:
    if not compressed:
        if len(data) != int(size):
            raise ValueError("invalid raw tile size")
        return data
    unpacked = lz4_decompress_bytes(data, int(size))
    if unpacked is None:
        raise ValueError("CreativeCore LZ4 support is unavailable")
    return unpacked


def encode_record(data: bytes, width: int, height: int, stride: int):
    """Encode a complete legacy CSLZ record in CreativeCore."""
    return encode_cslz_bytes(data, width, height, stride)


def decode_record(data: bytes, expected_size=None):
    """Decode a complete legacy CSLZ record in CreativeCore."""
    return decode_cslz_bytes(data, expected_size)
