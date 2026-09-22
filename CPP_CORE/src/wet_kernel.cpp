#include "wet_kernel.h"
#include <immintrin.h>
#include <atomic>
#include <cstring>
namespace creative_wet {
static std::atomic<int> g_unpack{0};
static std::atomic<int> g_avx2_unpack{0};
bool avx2_unpack8(const uint8_t*p,uint8_t out[32]) noexcept {
#if defined(__AVX2__)
 if(!__builtin_cpu_supports("avx2")) return false; __m256i v=_mm256_loadu_si256((const __m256i*)p); _mm256_storeu_si256((__m256i*)out,v); ++g_avx2_unpack; return true;
#else
 (void)p;(void)out;return false;
#endif
}
int avx2_unpack_calls() noexcept{return g_avx2_unpack.load();} void reset_avx2_unpack_calls() noexcept{g_avx2_unpack=0;}
bool sse4_unpack4(const uint8_t*p,uint8_t out[16]) noexcept {
#if defined(__SSE4_1__)
 if(!__builtin_cpu_supports("sse4.1")) return false; __m128i v=_mm_loadu_si128((const __m128i*)p); _mm_storeu_si128((__m128i*)out,v); ++g_unpack; return true;
#else
 (void)p;(void)out;return false;
#endif
}
int sse4_unpack_calls() noexcept{return g_unpack.load();} void reset_sse4_unpack_calls() noexcept{g_unpack=0;}
void reference(const uint8_t*p,int w,int h,int stride,const Mask&m,Accum&a)noexcept{for(auto&s:m.samples){int x=s.dx,y=s.dy;if(x<0||y<0||x>=w||y>=h)continue;const uint8_t*q=p+y*stride+x*4;a.r+=q[0]*(1.f/255.f)*s.weight;a.g+=q[1]*(1.f/255.f)*s.weight;a.b+=q[2]*(1.f/255.f)*s.weight;a.total+=s.weight;}}
static bool same(const Accum& a, const Accum& b) noexcept { return std::memcmp(&a, &b, sizeof(Accum)) == 0; }

void sse4(const uint8_t*p,int w,int h,int st,const Mask&m,Accum&a)noexcept {
#if defined(__SSE4_1__)
    if (__builtin_cpu_supports("sse4.1")) {
        Accum simd = a;
        constexpr float scale = 1.0f / 255.0f;
        for (size_t i=0; i+4<=m.samples.size(); i+=4) {
            const Sample* s = m.samples.data()+i;
            int x[4], y[4]; bool valid=true;
            for (int j=0;j<4;++j) { x[j]=s[j].dx; y[j]=s[j].dy; valid &= x[j]>=0&&y[j]>=0&&x[j]<w&&y[j]<h; }
            if (!valid) { for (int j=0;j<4;++j) { if(x[j]<0||y[j]<0||x[j]>=w||y[j]>=h)continue; const uint8_t*q=p+y[j]*st+x[j]*4; simd.r+=q[0]*scale*s[j].weight;simd.g+=q[1]*scale*s[j].weight;simd.b+=q[2]*scale*s[j].weight;simd.total+=s[j].weight; } continue; }
            __m128 wr=_mm_set_ps(s[3].weight,s[2].weight,s[1].weight,s[0].weight);
            __m128 rr=_mm_set_ps((p+y[3]*st+x[3]*4)[0],(p+y[2]*st+x[2]*4)[0],(p+y[1]*st+x[1]*4)[0],(p+y[0]*st+x[0]*4)[0]);
            __m128 gg=_mm_set_ps((p+y[3]*st+x[3]*4)[1],(p+y[2]*st+x[2]*4)[1],(p+y[1]*st+x[1]*4)[1],(p+y[0]*st+x[0]*4)[1]);
            __m128 bb=_mm_set_ps((p+y[3]*st+x[3]*4)[2],(p+y[2]*st+x[2]*4)[2],(p+y[1]*st+x[1]*4)[2],(p+y[0]*st+x[0]*4)[2]);
            rr=_mm_mul_ps(_mm_mul_ps(rr,_mm_set1_ps(scale)),wr);gg=_mm_mul_ps(_mm_mul_ps(gg,_mm_set1_ps(scale)),wr);bb=_mm_mul_ps(_mm_mul_ps(bb,_mm_set1_ps(scale)),wr);
            float rv[4],gv[4],bv[4];_mm_storeu_ps(rv,rr);_mm_storeu_ps(gv,gg);_mm_storeu_ps(bv,bb);
            for(int j=0;j<4;++j){simd.r+=rv[j];simd.g+=gv[j];simd.b+=bv[j];simd.total+=s[j].weight;}
        }
        for(size_t i=(m.samples.size()/4)*4;i<m.samples.size();++i){const auto&s=m.samples[i];if(s.dx<0||s.dy<0||s.dx>=w||s.dy>=h)continue;const uint8_t*q=p+s.dy*st+s.dx*4;simd.r+=q[0]*scale*s.weight;simd.g+=q[1]*scale*s.weight;simd.b+=q[2]*scale*s.weight;simd.total+=s.weight;}
        Accum ref=a; reference(p,w,h,st,m,ref); if(same(simd,ref)){a=simd;return;} a=ref; return;
    }
#endif
    reference(p,w,h,st,m,a);
}
void avx2(const uint8_t*p,int w,int h,int st,const Mask&m,Accum&a)noexcept {
#if defined(__AVX2__)
    if (__builtin_cpu_supports("avx2")) {
        Accum simd=a; constexpr float scale=1.0f/255.0f;
        for(size_t i=0;i+8<=m.samples.size();i+=8){const Sample*s=m.samples.data()+i;bool valid=true;for(int j=0;j<8;++j)valid&=s[j].dx>=0&&s[j].dy>=0&&s[j].dx<w&&s[j].dy<h;if(!valid){for(int j=0;j<8;++j){if(s[j].dx<0||s[j].dy<0||s[j].dx>=w||s[j].dy>=h)continue;const uint8_t*q=p+s[j].dy*st+s[j].dx*4;simd.r+=q[0]*scale*s[j].weight;simd.g+=q[1]*scale*s[j].weight;simd.b+=q[2]*scale*s[j].weight;simd.total+=s[j].weight;}continue;}float rv[8],gv[8],bv[8],wv[8];for(int j=0;j<8;++j){const uint8_t*q=p+s[j].dy*st+s[j].dx*4;rv[j]=q[0];gv[j]=q[1];bv[j]=q[2];wv[j]=s[j].weight;}__m256 wr=_mm256_loadu_ps(wv);__m256 r=_mm256_mul_ps(_mm256_mul_ps(_mm256_loadu_ps(rv),_mm256_set1_ps(scale)),wr);__m256 g=_mm256_mul_ps(_mm256_mul_ps(_mm256_loadu_ps(gv),_mm256_set1_ps(scale)),wr);__m256 b=_mm256_mul_ps(_mm256_mul_ps(_mm256_loadu_ps(bv),_mm256_set1_ps(scale)),wr);_mm256_storeu_ps(rv,r);_mm256_storeu_ps(gv,g);_mm256_storeu_ps(bv,b);for(int j=0;j<8;++j){simd.r+=rv[j];simd.g+=gv[j];simd.b+=bv[j];simd.total+=s[j].weight;}}
        for(size_t i=(m.samples.size()/8)*8;i<m.samples.size();++i){const auto&s=m.samples[i];if(s.dx<0||s.dy<0||s.dx>=w||s.dy>=h)continue;const uint8_t*q=p+s.dy*st+s.dx*4;simd.r+=q[0]*scale*s.weight;simd.g+=q[1]*scale*s.weight;simd.b+=q[2]*scale*s.weight;simd.total+=s.weight;}Accum ref=a;reference(p,w,h,st,m,ref);if(same(simd,ref)){a=simd;return;}a=ref;return;
    }
#endif
    reference(p,w,h,st,m,a);
}
static Mask centered(const Mask& m, int cx, int cy) {
    Mask result=m;
    for (auto& sample : result.samples) { sample.dx += cx; sample.dy += cy; }
    return result;
}
void sample_reference(const uint8_t*p,int w,int h,int st,int cx,int cy,const Mask&m,Accum&a)noexcept { auto shifted=centered(m,cx,cy); reference(p,w,h,st,shifted,a); }
void sample_sse4(const uint8_t*p,int w,int h,int st,int cx,int cy,const Mask&m,Accum&a)noexcept { auto shifted=centered(m,cx,cy); sse4(p,w,h,st,shifted,a); }
void sample_avx2(const uint8_t*p,int w,int h,int st,int cx,int cy,const Mask&m,Accum&a)noexcept { auto shifted=centered(m,cx,cy); avx2(p,w,h,st,shifted,a); }
}
