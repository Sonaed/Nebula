#include "simd_runtime.h"

#include <cstring>

#if defined(__AVX2__) || defined(__SSE4_1__)
#include <immintrin.h>
#endif

namespace creative_simd {

Backend backend() noexcept {
#if defined(__GNUC__) || defined(__clang__)
    static const Backend value = __builtin_cpu_supports("avx2") ? Backend::AVX2
        : (__builtin_cpu_supports("sse4.1") ? Backend::SSE4 : Backend::Scalar);
    return value;
#elif defined(__AVX2__)
    return Backend::AVX2;
#elif defined(__SSE4_1__)
    return Backend::SSE4;
#else
    return Backend::Scalar;
#endif
}

const char* backendName() noexcept {
    switch (backend()) {
    case Backend::AVX2: return "AVX2";
    case Backend::SSE4: return "SSE4.1";
    default: return "scalar";
    }
}

void restoreAlpha(uint8_t* dst, const uint8_t* src, int pixels) noexcept {
    // Alpha-only updates are normally tiny dirty rectangles.  Keep this
    // path scalar and exact: the former AVX byte-shuffle crossed 128-bit
    // lanes and could corrupt alpha on the second half of a row.
    for (int i = 0; i < pixels; ++i)
        dst[i * 4 + 3] = src[i * 4 + 3];
}

void copyRgba(uint8_t* dst, const uint8_t* src, int pixels) noexcept {
    int i = 0;
#if defined(__AVX2__)
    for (; i + 8 <= pixels && backend() == Backend::AVX2; i += 8)
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(dst + i * 4), _mm256_loadu_si256(reinterpret_cast<const __m256i*>(src + i * 4)));
#endif
#if defined(__SSE4_1__)
    for (; i + 4 <= pixels && backend() == Backend::SSE4; i += 4)
        _mm_storeu_si128(reinterpret_cast<__m128i*>(dst + i * 4), _mm_loadu_si128(reinterpret_cast<const __m128i*>(src + i * 4)));
#endif
    for (; i < pixels; ++i) std::memcpy(dst + i * 4, src + i * 4, 4);
}
}
