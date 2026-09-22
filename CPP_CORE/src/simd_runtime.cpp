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
    int i = 0;
#if defined(__AVX2__)
    // AVX2 is selected only when this translation unit was built with AVX2;
    // runtime dispatch still reports the scalar backend otherwise.
    const __m256i alphaMask = _mm256_setr_epi8(
        0, 1, 2, 0x80, 4, 5, 6, 0x80, 8, 9, 10, 0x80,
        12, 13, 14, 0x80, 16, 17, 18, 0x80, 20, 21, 22, 0x80,
        24, 25, 26, 0x80, 28, 29, 30, 0x80);
    const __m256i alphaInsert = _mm256_setr_epi8(
        0x80, 0x80, 0x80, 3, 0x80, 0x80, 0x80, 7, 0x80, 0x80, 0x80, 11,
        0x80, 0x80, 0x80, 15, 0x80, 0x80, 0x80, 19, 0x80, 0x80, 0x80, 23,
        0x80, 0x80, 0x80, 27, 0x80, 0x80, 0x80, 31);
    for (; i + 8 <= pixels && backend() == Backend::AVX2; i += 8) {
        __m256i d = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(dst + i * 4));
        __m256i s = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(src + i * 4));
        __m256i a = _mm256_shuffle_epi8(s, alphaInsert);
        __m256i keep = _mm256_shuffle_epi8(d, alphaMask);
        __m256i out = _mm256_or_si256(keep, a);
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(dst + i * 4), out);
    }
#endif
#if defined(__SSE4_1__)
    const __m128i alphaMask128 = _mm_setr_epi8(0, 1, 2, 0x80, 4, 5, 6, 0x80, 8, 9, 10, 0x80, 12, 13, 14, 0x80);
    const __m128i alphaInsert128 = _mm_setr_epi8(0x80, 0x80, 0x80, 3, 0x80, 0x80, 0x80, 7, 0x80, 0x80, 0x80, 11, 0x80, 0x80, 0x80, 15);
    for (; i + 4 <= pixels && backend() == Backend::SSE4; i += 4) {
        __m128i d = _mm_loadu_si128(reinterpret_cast<const __m128i*>(dst + i * 4));
        __m128i s = _mm_loadu_si128(reinterpret_cast<const __m128i*>(src + i * 4));
        _mm_storeu_si128(reinterpret_cast<__m128i*>(dst + i * 4),
                         _mm_or_si128(_mm_shuffle_epi8(d, alphaMask128), _mm_shuffle_epi8(s, alphaInsert128)));
    }
#endif
    for (; i < pixels; ++i) dst[i * 4 + 3] = src[i * 4 + 3];
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
