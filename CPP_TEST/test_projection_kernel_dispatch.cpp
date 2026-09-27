#include "projection_kernel_dispatch.h"
#include <cassert>
#include <random>
#include <vector>
static uint8_t div255(uint32_t v) { return static_cast<uint8_t>((v + 127u) / 255u); }
static uint8_t blend(uint8_t b, uint8_t s, int mode) {
    switch (mode) {
    case 0: return s;
    case 2: return div255(static_cast<uint32_t>(b) * s);
    case 5: return static_cast<uint8_t>(255u - div255(static_cast<uint32_t>(255u-b) * (255u-s)));
    case 7: return b < 128 ? div255(2u * b * s) : static_cast<uint8_t>(255u - div255(2u * (255u-b) * (255u-s)));
    case 9: return s < 128 ? div255(2u * b * s) : static_cast<uint8_t>(255u - div255(2u * (255u-b) * (255u-s)));
    default: return s;
    }
}
int main(){
    std::mt19937 g(7);
    std::vector<uint8_t>b(257*4),s(b.size()),r(b.size()),o(b.size());
    for(auto&v:b)v=static_cast<uint8_t>(g());
    for(auto&v:s)v=static_cast<uint8_t>(g());
    creative_projection::reference(b.data(),s.data(),r.data(),257);
    creative_projection::KernelFn fns[3]={creative_projection::sse4,creative_projection::avx2,creative_projection::select(0)};
    for(auto fn:fns){fn(b.data(),s.data(),o.data(),257);assert(o==r);}
    for (int mode : {0, 2, 5, 7, 9}) {
        for (size_t i = 0; i < o.size(); i += 4)
            for (int c = 0; c < 4; ++c)
                r[i+c] = blend(b[i+c], s[i+c], mode);
        assert(creative_projection::opaque_blend_batch(b.data(), s.data(), o.data(), 257, mode));
        assert(o == r);
    }
    assert(!creative_projection::opaque_blend_batch(b.data(), s.data(), o.data(), 257, 3));
    return 0;
}
