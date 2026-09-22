#pragma once

#include <cstdint>

namespace creative_simd {
enum class Backend { Scalar, SSE4, AVX2 };

Backend backend() noexcept;
const char* backendName() noexcept;

// Copy alpha bytes from src to dst while preserving RGB. Pointers may be
// unaligned; strides and coordinates are expressed in bytes.
void restoreAlpha(uint8_t* dst, const uint8_t* src, int pixels) noexcept;
void copyRgba(uint8_t* dst, const uint8_t* src, int pixels) noexcept;
}
