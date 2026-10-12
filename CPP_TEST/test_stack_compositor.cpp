#include "stack_compositor.h"
#include "../CPP_CORE/src/projection_compositor.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

extern "C" int legacy_compose_stack(uint8_t*, int, int, int, const CsStackOp*, int);
namespace {
constexpr float defaults[11] = {1,0,1,1,0,.5f,1,.5f,0,1,0};
struct Fixture {
    int width, height, stride;
    std::mt19937 random;
    std::vector<std::vector<uint8_t>> buffers;
    std::vector<CsStackOp> ops;
    std::array<uint8_t, 1024> table{};
    std::array<float, 24> cube{};
    Fixture(int w, int h, unsigned seed):width(w),height(h),stride(w*4+12),random(seed) {
        for (auto& v:table) v=static_cast<uint8_t>(random());
        for (auto& v:cube) v=static_cast<float>(random()%256)/255.f;
    }
    float unit() { return static_cast<float>(random()%256)/255.f; }
    const uint8_t* pixels() {
        buffers.emplace_back(static_cast<size_t>(stride)*height);
        for (auto& v:buffers.back()) v=static_cast<uint8_t>(random());
        return buffers.back().data();
    }
    void add(int kind, int mode, bool custom=false, bool clip=false) {
        CsStackOp op{};
        op.kind=kind; op.mode=mode; op.visible=random()%5!=0;
        op.clipping=clip; op.opacity=random()%3==0?unit():1.f;
        std::copy(std::begin(defaults),std::end(defaults),op.parameters);
        if (custom) {
            for(int i:{0,1,2,4,5,6,7,10}) op.parameters[i]=unit();
            op.parameters[3]=.5f+2.f*unit(); op.parameters[8]=360.f*unit()-180.f;
            op.parameters[9]=2.f*unit();
        }
        if (kind==CS_STACK_RASTER) {
            op.pixels=random()%7==0?nullptr:pixels();
            op.stride=stride; op.format=random()%2;
        }
        if (random()%3==0) { op.mask=pixels();op.mask_stride=stride; }
        if (kind==CS_STACK_ADJUST) {
            op.adjust_kind=random()%3;
            op.table=op.adjust_kind==2?static_cast<const void*>(cube.data()):table.data();
            op.table_size=2;
        }
        ops.push_back(op);
    }
};
void compare(Fixture& f) {
    std::vector<uint8_t> legacy(static_cast<size_t>(f.stride)*f.height,0xAB),actual=legacy;
    assert(legacy_compose_stack(legacy.data(),f.width,f.height,f.stride,f.ops.data(),f.ops.size())==1);
    assert(cs_compose_stack(actual.data(),f.width,f.height,f.stride,f.ops.data(),f.ops.size())==1);
    if (actual!=legacy) {
        auto i=std::mismatch(actual.begin(),actual.end(),legacy.begin()).first-actual.begin();
        std::fprintf(stderr,"Pixel mismatch at %td: %u != %u (%dx%d, %zu ops)\n",i,actual[i],legacy[i],f.width,f.height,f.ops.size());
        std::abort();
    }
}
void parity() {
    // Fixed seed and multiple run tails; masked nested folders, hidden clip bases,
    // LUTs, adjustments, arbitrary opacity, both byte orders, sparse null tiles.
    for(unsigned seed=0;seed<240;++seed) {
        Fixture f(std::array<int,6>{1,7,63,64,65,131}[seed%6],7,seed+41);
        f.add(CS_STACK_RASTER,seed%16);
        f.add(CS_STACK_GROUP_BEGIN,0);
        for(int i=0;i<5;++i) f.add(CS_STACK_RASTER,(seed+i)%16,seed%2,i%3==1);
        f.add(CS_STACK_GROUP_BEGIN,0);
        f.add(CS_STACK_RASTER,(seed+3)%16);
        f.add(CS_STACK_ADJUST,(seed+7)%16,seed%2,seed%3==0);
        f.add(CS_STACK_RASTER,(seed+5)%16,false,true);
        f.add(CS_STACK_GROUP_END,(seed+8)%16,seed%2);
        f.add(CS_STACK_RASTER,(seed+9)%16,false,true);
        f.add(CS_STACK_GROUP_END,(seed+11)%16,seed%2);
        f.add(CS_STACK_RASTER,(seed+12)%16,false,true);
        f.add(CS_STACK_ADJUST,(seed+13)%16,seed%2);
        f.add(CS_STACK_RASTER,(seed+14)%16,true,true);
        compare(f);
    }
    // Also cover the parallel row path and alpha endpoints.
    for(int mode=0;mode<16;++mode) {
        Fixture f(257,257,mode+77);
        f.add(CS_STACK_RASTER,0); f.add(CS_STACK_RASTER,mode);
        for(auto& data:f.buffers) for(size_t i=3;i<data.size();i+=4) data[i]=(i%3==0?0:255);
        compare(f);
    }
}
void newModes() {
    using projection_compositor::RGB;
    const RGB b{.25f,.75f,.5f},s{.5f,.25f,.75f};
    const std::array<RGB,10> expected{{
        { .75f,1.f,1.f }, {0.f,0.f,.25f}, {.25f,.5f,1.f},
        {.25f,.25f,1.f}, {.25f,.5f,.5f}, {0.f,1.f,1.f},
        b,b,{0.f,.5f,0.f},{.5f,1.f,2.f/3.f}
    }};
    for(int mode=16;mode<=25;++mode) {
        RGB got=projection_compositor::blendRgb(b,s,mode,defaults);
        for(int c=0;c<3;++c) assert(std::abs(got[c]-expected[mode-16][c])<1e-6f);
        // The production stack accepts every new mode with opacity and clipping.
        Fixture f(3,2,mode); f.add(CS_STACK_RASTER,0);f.add(CS_STACK_RASTER,mode,true,true);
        std::vector<uint8_t> out(f.stride*f.height);
        assert(cs_compose_stack(out.data(),f.width,f.height,f.stride,f.ops.data(),f.ops.size())==1);
        for(int B:{0,1,127,128,254,255}) for(int S:{0,1,127,128,254,255}) {
            RGB x{B/255.f,B/255.f,B/255.f},y{S/255.f,S/255.f,S/255.f};
            for(float v:projection_compositor::blendRgb(x,y,mode,defaults)) assert(std::isfinite(v)&&v>=0.f&&v<=1.f);
        }
    }
    assert((projection_compositor::blendRgb({.1f,.9f,.1f},{.8f,.2f,.8f},22,defaults)==RGB{.1f,.9f,.1f}));
    assert((projection_compositor::blendRgb({.1f,.9f,.1f},{.8f,.2f,.8f},23,defaults)==RGB{.8f,.2f,.8f}));
    assert((projection_compositor::blendRgb({0.f,.5f,1.f},{0.f,0.f,0.f},25,defaults)==RGB{1.f,1.f,1.f}));
}
void invalidAndBatch() {
    uint8_t out[8]={42,42,42,42,42,42,42,42};
    CsStackOp op{};std::copy(std::begin(defaults),std::end(defaults),op.parameters);op.visible=1;
    op.mode=26;assert(!cs_compose_stack(out,2,1,8,&op,1));
    op.mode=0;op.kind=CS_STACK_GROUP_END;assert(!cs_compose_stack(out,2,1,8,&op,1));
    op.kind=CS_STACK_GROUP_BEGIN;assert(!cs_compose_stack(out,2,1,8,&op,1));
    for(auto v:out)assert(v==42);
    CsStackJob jobs[2]={{out,1,1,4,nullptr,0,0},{out+4,1,1,4,nullptr,0,0}};
    assert(cs_compose_stack_batch(jobs,2)==2);for(auto v:out)assert(v==0);
}
void benchmark() {
    for(int mode:{0,2,5,7,14}) {
        Fixture f(512,384,19);for(int i=0;i<43;++i)f.add(CS_STACK_RASTER,mode,false,i%6==1);
        for(auto& op:f.ops){op.visible=1;op.mask=nullptr;op.opacity=1.f;}
        std::vector<uint8_t> out(f.stride*f.height),reference=out;
        auto run=[&](auto fn, std::vector<uint8_t>& target) {
            std::vector<double> ms;
            for(int i=0;i<6;++i){
                auto start=std::chrono::steady_clock::now();
                assert(fn(target.data(),f.width,f.height,f.stride,f.ops.data(),static_cast<int>(f.ops.size()))==1);
                if(i>0)ms.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
            }
            std::sort(ms.begin(),ms.end());return ms[ms.size()/2];
        };
        const double before=run(legacy_compose_stack,reference),after=run(cs_compose_stack,out);
        assert(out==reference);
        std::printf("mode %d: before %.3f ms after %.3f ms speedup %.2fx (identical bytes)\n",mode,before,after,before/after);
    }
}
}
int main(int argc,char** argv) {
    if(argc>1&&std::strcmp(argv[1],"--benchmark")==0) benchmark();
    else {parity();newModes();invalidAndBatch();std::puts("stack compositor: 256 legacy stacks byte-identical; 10 new modes and validation OK");}
}
