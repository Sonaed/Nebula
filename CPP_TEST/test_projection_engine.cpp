#include "creative_core_api.h"

#include <array>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <vector>

struct Result {
    std::mutex mutex;
    std::condition_variable ready;
    bool done=false;
    uint64_t generation=0;
    std::vector<uint8_t> pixels; int width=0,height=0,stride=0;
    std::string error;
};

static void receive(uint64_t generation,int,int,const uint8_t* rgba,int width,int height,
                    int stride,const char* error,void* context) {
    auto* result=static_cast<Result*>(context);
    std::lock_guard<std::mutex> lock(result->mutex);
    result->generation=generation;
    if(error) result->error=error;
    else if(rgba&&width>0&&height>0&&stride>=width*4) { result->width=width; result->height=height; result->stride=stride; result->pixels.assign(rgba,rgba+stride*height); }
    result->done=true;
    result->ready.notify_one();
}

int main() {
    cs_projection_reset_batch_calls();
    Result result;
    auto handle=cs_projection_start(receive,&result);
    if(!handle) return 1;
    constexpr int W=13; std::array<uint8_t,W*4> bottom{};
    for(int x=0;x<W;++x){bottom[x*4]=100+x;bottom[x*4+1]=150;bottom[x*4+2]=200;bottom[x*4+3]=255;}
    CsProjectionLayer layers[2]{};
    layers[0].rgba=bottom.data(); layers[0].width=W; layers[0].height=1; layers[0].stride=W*4;
    layers[0].visible=1; layers[0].opacity=1.0f; layers[0].blend_mode=0;
    layers[0].blend_parameters[0]=1; layers[0].blend_parameters[2]=1;
    layers[0].blend_parameters[3]=1; layers[0].blend_parameters[5]=.5f;
    layers[0].blend_parameters[6]=1; layers[0].blend_parameters[7]=.5f;
    layers[0].blend_parameters[9]=1;
    layers[0].parameterized=1;
    layers[1].rgba=bottom.data(); layers[1].width=W; layers[1].height=1; layers[1].stride=W*4; layers[1].visible=0;
    layers[1].blend_parameters[0]=1; layers[1].blend_parameters[1]=0;
    layers[1].blend_parameters[2]=1; layers[1].blend_parameters[3]=1;
    layers[1].blend_parameters[4]=0; layers[1].blend_parameters[5]=.5f;
    layers[1].blend_parameters[6]=1; layers[1].blend_parameters[7]=.5f;
    layers[1].blend_parameters[8]=0; layers[1].blend_parameters[9]=1;
    layers[1].blend_parameters[10]=0;
    layers[1].parameterized=1;
    if(!cs_projection_invalidate(handle,42,3,7,W,1,layers,2)) { cs_projection_stop(handle); return 2; }
    {
        std::unique_lock<std::mutex> lock(result.mutex);
        if(!result.ready.wait_for(lock,std::chrono::seconds(3),[&]{return result.done;})) {
            lock.unlock(); cs_projection_stop(handle); return 3;
        }
    }
    bool valid=result.error.empty()&&result.generation==42&&result.width==W&&result.pixels.size()>=W*4;
    for(int i=0;i<W*4&&valid;++i) valid=result.pixels[i]==bottom[i];
    cs_projection_stop(handle);
    if (cs_projection_normal_batch_calls() <= 0) return 5;
    return valid?0:4;
}
