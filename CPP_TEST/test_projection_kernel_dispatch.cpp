#include "projection_kernel_dispatch.h"
#include <cassert>
#include <random>
#include <vector>
int main(){std::mt19937 g(7);std::vector<uint8_t>b(257*4),s(b.size()),r(b.size()),o(b.size());for(auto&v:b)v=g();for(auto&v:s)v=g();creative_projection::reference(b.data(),s.data(),r.data(),257);creative_projection::KernelFn fns[3]={creative_projection::sse4,creative_projection::avx2,creative_projection::select(0)};for(auto fn:fns){fn(b.data(),s.data(),o.data(),257);assert(o==r);}return 0;}
