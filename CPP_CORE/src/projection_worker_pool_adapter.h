#pragma once
#include "thread_pool.h"
#include <condition_variable>
#include <cstdint>
#include <atomic>
#include <memory>
#include <deque>
#include <functional>
#include <mutex>
struct ProjectionLayerSnapshot { std::vector<uint8_t> rgba; int width=0,height=0,stride=0,visible=0,mode=0,parameterized=0,clipping=0; float opacity=1.0f; float params[11]{}; float weights[3]{}; float totalWeight=0.0f; int oppositeMode=-1; };
struct ProjectionJobPayload { using Completion = std::function<void(uint64_t,int,int,const uint8_t*,int,int,int,const char*)>; uint64_t generation=0,tile_id=0; int tile_x=0,tile_y=0,width=0,height=0,dst_stride=0; bool parallelRows=false; std::vector<ProjectionLayerSnapshot> snapshots; std::vector<ProjectionLayerSnapshot> layers; std::shared_ptr<std::vector<uint8_t>> output; Completion callback; std::atomic<bool> superseded{false}; std::atomic<bool> callback_called{false}; void complete(const char* error=nullptr){bool expected=false;if(callback_called.compare_exchange_strong(expected,true)&&callback)callback(generation,tile_x,tile_y,output?output->data():nullptr,width,height,dst_stride,error);} };
struct ProjectionJob { uint64_t tile_id=0; int tile_x=0,tile_y=0,width=0,height=0,dst_stride=0; bool parallelRows=false; std::vector<ProjectionLayerSnapshot> layers; std::vector<uint8_t> destination; std::shared_ptr<ProjectionJobPayload> payload; std::function<void()> execute; std::function<void()> completed; };
struct ProjectionCompositionView { std::shared_ptr<const ProjectionJobPayload> owner; uint64_t generation=0,tile_id=0; int tile_x=0,tile_y=0,width=0,height=0,dst_stride=0; bool parallelRows=false; const std::vector<ProjectionLayerSnapshot>* snapshots=nullptr; std::vector<uint8_t>* output=nullptr; const ProjectionJobPayload::Completion* callback=nullptr; size_t size()const{return snapshots?snapshots->size():0;} bool empty()const{return size()==0;} const ProjectionLayerSnapshot& layer(size_t i)const{return snapshots->at(i);} auto begin()const{return snapshots?snapshots->begin():std::vector<ProjectionLayerSnapshot>::const_iterator{};} auto end()const{return snapshots?snapshots->end():std::vector<ProjectionLayerSnapshot>::const_iterator{};} uint8_t* output_data(){return output&& !output->empty()?output->data():nullptr;} };
inline ProjectionCompositionView make_legacy_composition_view(const std::shared_ptr<ProjectionJobPayload>& p){ProjectionCompositionView v;v.owner=p;if(p){v.generation=p->generation;v.tile_id=p->tile_id;v.tile_x=p->tile_x;v.tile_y=p->tile_y;v.width=p->width;v.height=p->height;v.dst_stride=p->dst_stride;v.parallelRows=p->parallelRows;v.snapshots=&p->snapshots;v.output=p->output.get();v.callback=&p->callback;}return v;}
class ProjectionWorkerPoolAdapter {
public:
 explicit ProjectionWorkerPoolAdapter(unsigned n=0):pool(n){unsigned count=n?n:(pool.size()); for(unsigned i=0;i<count;++i) pool.enqueue([this]{worker_loop();});}
 void submit(int tile,std::function<void()> f){ProjectionJob j;j.tile_id=tile;j.execute=std::move(f);submit(std::move(j));}
 void submit(ProjectionJob job){submit((int)job.tile_id,[j=std::move(job)]()mutable{if(j.execute)j.execute();if(j.completed)j.completed();});}
 void replace_tile(uint64_t id, ProjectionJob job){std::lock_guard l(m);if(stopping)return;for(auto it=q.begin();it!=q.end();)if(it->tile_id==id){if(it->payload)it->payload->superseded=true;it=q.erase(it);}else ++it;q.push_back(std::move(job));cv.notify_one();}
 bool acquire_projection_job(ProjectionJob& out){std::unique_lock l(m);cv.wait(l,[&]{return stopping||!q.empty();});if(stopping&&q.empty())return false;out=std::move(q.front());q.pop_front();++active;return true;}
 void complete_projection_job(ProjectionJob&){complete();}
 void wait_projection_idle(){wait_idle();}
 void stop_projection_workers(){stop();}
 bool acquire(int& tile,std::function<void()>& f){ProjectionJob j;if(!acquire_projection_job(j))return false;tile=(int)j.tile_id;f=std::move(j.execute);return true;}
 void complete(){std::lock_guard l(m);if(active) --active;done.notify_all();}
 void stop(){ {std::lock_guard l(m); stopping=true;} cv.notify_all(); pool.stop(); done.notify_all(); }
 void wait_idle(){std::unique_lock l(m);done.wait(l,[&]{return active==0&&q.empty();});}
 void set_workers(unsigned n){std::lock_guard l(m);workers=n;}
 unsigned active_workers()const{std::lock_guard l(m);return active;}
 unsigned size()const{return pool.size();}
 private: creative_core::ThreadPool pool; mutable std::mutex m; std::condition_variable cv,done; std::deque<ProjectionJob> q; unsigned active=0,workers=0; bool stopping=false;
 void worker_loop(){for(;;){ProjectionJob j;if(!acquire_projection_job(j))return;try{if(j.execute)j.execute();if(j.completed)j.completed();}catch(...){ }complete_projection_job(j);}}
};
