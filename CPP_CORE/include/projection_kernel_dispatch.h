#pragma once
#include <cstdint>
namespace creative_projection {
using KernelFn = void(*)(const uint8_t*, const uint8_t*, uint8_t*, int);
void reference(const uint8_t*,const uint8_t*,uint8_t*,int) noexcept;
void sse4(const uint8_t*,const uint8_t*,uint8_t*,int) noexcept;
void avx2(const uint8_t*,const uint8_t*,uint8_t*,int) noexcept;
KernelFn select(int mode) noexcept;
bool normal_opaque_batch(const uint8_t* src, uint8_t* dst, int pixels) noexcept;
void note_normal_batch() noexcept;
int normal_batch_calls() noexcept;
void reset_normal_batch_calls() noexcept;
}
