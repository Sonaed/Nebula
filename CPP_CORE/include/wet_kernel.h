#pragma once
#include "wet_mask.h"
#include <cstdint>
namespace creative_wet { struct Accum{float r=0,g=0,b=0,total=0;}; void reference(const uint8_t*,int,int,int,const Mask&,Accum&) noexcept; void sse4(const uint8_t*,int,int,int,const Mask&,Accum&) noexcept; void avx2(const uint8_t*,int,int,int,const Mask&,Accum&) noexcept; }
namespace creative_wet { void sample_reference(const uint8_t*,int,int,int,int,int,const Mask&,Accum&) noexcept; void sample_sse4(const uint8_t*,int,int,int,int,int,const Mask&,Accum&) noexcept; void sample_avx2(const uint8_t*,int,int,int,int,int,const Mask&,Accum&) noexcept; }
namespace creative_wet { bool sse4_unpack4(const uint8_t*,uint8_t out[16]) noexcept; int sse4_unpack_calls() noexcept; void reset_sse4_unpack_calls() noexcept; }
namespace creative_wet { bool avx2_unpack8(const uint8_t*,uint8_t out[32]) noexcept; int avx2_unpack_calls() noexcept; void reset_avx2_unpack_calls() noexcept; }
