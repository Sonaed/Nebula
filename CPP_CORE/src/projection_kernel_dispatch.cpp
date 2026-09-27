#include "projection_kernel_dispatch.h"
#include <cstring>
#include <immintrin.h>
#include <atomic>
namespace creative_projection {
static std::atomic<int> g_calls{0};
void note_normal_batch() noexcept { ++g_calls; }
int normal_batch_calls() noexcept { return g_calls.load(); }
void reset_normal_batch_calls() noexcept { g_calls = 0; }
static inline uint8_t rounded_div255(uint32_t value) noexcept {
    return static_cast<uint8_t>((value + 127u) / 255u);
}
static inline uint8_t opaque_blend_scalar(uint8_t b, uint8_t s, int mode) noexcept {
    switch (mode) {
    case 0: return s;
    case 2: return rounded_div255(static_cast<uint32_t>(b) * s);
    case 5: return static_cast<uint8_t>(255u - rounded_div255(static_cast<uint32_t>(255u-b) * (255u-s)));
    case 7:
        return b < 128 ? rounded_div255(2u * static_cast<uint32_t>(b) * s)
                       : static_cast<uint8_t>(255u - rounded_div255(2u * static_cast<uint32_t>(255u-b) * (255u-s)));
    case 9:
        return s < 128 ? rounded_div255(2u * static_cast<uint32_t>(b) * s)
                       : static_cast<uint8_t>(255u - rounded_div255(2u * static_cast<uint32_t>(255u-b) * (255u-s)));
    default: return s;
    }
}
bool opaque_blend_batch(const uint8_t* backdrop, const uint8_t* source,
                        uint8_t* out, int pixels, int mode) noexcept {
    if (!backdrop || !source || !out || pixels <= 0) return false;
    if (mode == 0) { std::memcpy(out, source, static_cast<size_t>(pixels) * 4); return true; }
    if (mode != 2 && mode != 5 && mode != 7 && mode != 9) return false;
    int i = 0;
#if defined(__AVX2__)
    if (__builtin_cpu_supports("avx2") && (mode == 2 || mode == 5)) {
        // Four RGBA bytes per pixel are processed independently; alpha is
        // included and remains 255 for the opaque fast path.
        const __m256i maxv = _mm256_set1_epi16(255);
        // (x + 127) / 255 rounded-to-nearest equals ((x + 128) * 257) >> 16
        // for the complete 8-bit product range.  The +128 is important at
        // exact byte boundaries; using +127 with mulhi loses one there.
        const __m256i bias = _mm256_set1_epi16(128);
        for (; i + 8 <= pixels; i += 8) {
            const __m256i b = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(backdrop + i * 4));
            const __m256i s = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(source + i * 4));
            const __m128i blo = _mm256_castsi256_si128(b), bhi = _mm256_extracti128_si256(b, 1);
            const __m128i slo = _mm256_castsi256_si128(s), shi = _mm256_extracti128_si256(s, 1);
            const __m256i b0 = _mm256_cvtepu8_epi16(blo), b1 = _mm256_cvtepu8_epi16(bhi);
            const __m256i s0 = _mm256_cvtepu8_epi16(slo), s1 = _mm256_cvtepu8_epi16(shi);
            auto blend = [&](const __m256i& bv, const __m256i& sv) {
                if (mode == 2) return _mm256_mulhi_epu16(_mm256_add_epi16(_mm256_mullo_epi16(bv, sv), bias), _mm256_set1_epi16(257));
                const __m256i db = _mm256_sub_epi16(maxv, bv), ds = _mm256_sub_epi16(maxv, sv);
                const __m256i product = _mm256_mulhi_epu16(_mm256_add_epi16(_mm256_mullo_epi16(db, ds), bias), _mm256_set1_epi16(257));
                if (mode == 5) return _mm256_sub_epi16(maxv, product);
                return bv;
            };
            alignas(32) uint16_t values[32];
            _mm256_store_si256(reinterpret_cast<__m256i*>(values), blend(b0, s0));
            _mm256_store_si256(reinterpret_cast<__m256i*>(values + 16), blend(b1, s1));
            for (int k = 0; k < 32; ++k) out[i * 4 + k] = static_cast<uint8_t>(values[k]);
        }
    }
#endif
    for (; i < pixels; ++i)
        for (int c = 0; c < 4; ++c)
            out[i * 4 + c] = opaque_blend_scalar(backdrop[i * 4 + c], source[i * 4 + c], mode);
    return true;
}
void reference(const uint8_t* backdrop,const uint8_t* source,uint8_t* out,int pixels) noexcept { if(pixels>0) std::memcpy(out,source,(size_t)pixels*4); }
void sse4(const uint8_t* b,const uint8_t* s,uint8_t* o,int n) noexcept { reference(b,s,o,n); }
void avx2(const uint8_t* b,const uint8_t* s,uint8_t* o,int n) noexcept { reference(b,s,o,n); }
KernelFn select(int) noexcept {
#if defined(__GNUC__) || defined(__clang__)
 if(__builtin_cpu_supports("avx2")) return avx2;
 if(__builtin_cpu_supports("sse4.1")) return sse4;
#endif
 return reference;
}
bool normal_opaque_batch(const uint8_t* src,uint8_t* dst,int pixels) noexcept { note_normal_batch(); int i=0;
#if defined(__AVX2__)
 if(__builtin_cpu_supports("avx2")){for(;i+8<=pixels;i+=8)_mm256_storeu_si256((__m256i*)(dst+i*4),_mm256_loadu_si256((const __m256i*)(src+i*4)));}
#endif
#if defined(__SSE4_1__)
 if(i==0&&__builtin_cpu_supports("sse4.1")){for(;i+4<=pixels;i+=4)_mm_storeu_si128((__m128i*)(dst+i*4),_mm_loadu_si128((const __m128i*)(src+i*4)));}
#endif
 for(;i<pixels;++i)std::memcpy(dst+i*4,src+i*4,4); return pixels>0;
}
}
