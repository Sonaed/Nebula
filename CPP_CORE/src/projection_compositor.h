#pragma once
#include <array>
namespace projection_compositor {
using RGB = std::array<float, 3>;
struct Pixel { RGB rgb{}; float a = 0.0f; };
RGB fromHsl(float h, float s, float l);
void toHsl(const RGB& rgb, float& h, float& s, float& l);
RGB blendRgb(const RGB& b, const RGB& s, int mode, const float* p);
Pixel candidate(const Pixel& backdrop, const RGB& source, float sourceA, int mode, const float* params);
int opposite(int mode);
void compose_layer(Pixel& acc, const RGB& src, float sa, int mode, const float* params,
                   int oppositeMode, const float* weights, float total);
}
