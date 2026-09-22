#include "creative_core_api.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>

int main() {
    const char* name = cs_simd_backend();
    assert(name && (std::strcmp(name, "AVX2") == 0 ||
                    std::strcmp(name, "SSE4.1") == 0 ||
                    std::strcmp(name, "scalar") == 0));

    constexpr int w = 37, h = 3, stride = w * 4;
    std::vector<uint8_t> dst(stride * h, 0xCD), src(stride * h, 0x11);
    for (int i = 0; i < w * h; ++i) {
        dst[i * 4 + 0] = 1; dst[i * 4 + 1] = 2; dst[i * 4 + 2] = 3;
        src[i * 4 + 3] = static_cast<uint8_t>(i);
    }
    cs_image_restore_alpha_rect(dst.data(), src.data(), w, h, stride, stride,
                                3, 1, 31, 3);
    for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x) {
        const int i = y * w + x;
        const bool inside = (y == 1 && x >= 3 && x < 34);
        assert(dst[i * 4 + 0] == 1 && dst[i * 4 + 1] == 2 && dst[i * 4 + 2] == 3);
        assert(dst[i * 4 + 3] == (inside ? static_cast<uint8_t>(i) : 0));
    }
    std::cout << "SIMD backend: " << name << "\n";
    return 0;
}
