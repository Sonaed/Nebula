#include "projection_kernel_dispatch.h"
#include <cstring>
#include <immintrin.h>
#include <atomic>
namespace creative_projection {
static std::atomic<int> g_calls{0};
void note_normal_batch() noexcept { ++g_calls; }
int normal_batch_calls() noexcept { return g_calls.load(); }
void reset_normal_batch_calls() noexcept { g_calls = 0; }
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
