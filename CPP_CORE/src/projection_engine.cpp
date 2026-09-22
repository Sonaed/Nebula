#include "projection_engine.h"
#include "projection_compositor.h"
#include "projection_kernel_dispatch.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#ifdef _OPENMP
#include <omp.h>
#endif

namespace {
using projection_compositor::RGB;
using projection_compositor::Pixel;

float clamp01(float x) { return std::clamp(x, 0.0f, 1.0f); }

using projection_compositor::fromHsl;
using projection_compositor::toHsl;

/* blendRgb moved to projection_compositor.cpp */
/*
    RGB o{};
    for (int c=0;c<3;++c) {
        const float B=b[c], S=s[c];
        switch(mode) {
        case 1: o[c]=std::min(B,S); break; // darken
        case 2: o[c]=std::pow(clamp01(B*S),1.0f/std::max(.01f,p[3])); break;
        case 3: o[c]=std::min(clamp01(1.0f-(1.0f-B)/std::max(S,1e-8f)),p[6]); break;
        case 4: o[c]=std::max(B,S); break;
        case 5: o[c]=std::pow(clamp01(1.0f-(1.0f-B)*(1.0f-S)),1.0f/std::max(.01f,p[3])); break;
        case 6: o[c]=std::min(clamp01(B/std::max(1.0f-S,1e-8f)),p[6]); break;
        case 7: case 9: {
            const float pivot=std::clamp(p[5],.0001f,.9999f);
            const float low=B*S/pivot, high=1.0f-(1.0f-B)*(1.0f-S)/(1.0f-pivot);
            o[c]=(mode==7 ? B : S) < pivot ? low : high; break;
        }
        case 8: {
            const float d=B<=.25f ? ((16*B-12)*B+4)*B : std::sqrt(clamp01(B));
            const float standard=S<=.5f ? B-(1-2*S)*B*(1-B) : B+(2*S-1)*(d-B);
            o[c]=clamp01(B+(standard-B)*((p[7]-.5f)*2.0f)); break;
        }
        case 10: o[c]=std::abs(B-clamp01(S+p[10])); break;
        case 11: { const float v=clamp01(S+p[10]); o[c]=B+v-2*B*v; break; }
        default: o[c]=S; break;
        }
    }
    if (mode>=12 && mode<=15) {
        float hb,sb,lb,hs,ss,ls; toHsl(b,hb,sb,lb); toHsl(s,hs,ss,ls);
        hs += p[8]/360.0f; ss=clamp01(ss*p[9]);
        if(mode==12) return fromHsl(hs,sb,lb);
        if(mode==13) return fromHsl(hb,ss,lb);
        if(mode==14) return fromHsl(hs,ss,lb);
        return fromHsl(hb,sb,ls);
    }
    return o;
}*/
using projection_compositor::blendRgb;

using projection_compositor::candidate;

using projection_compositor::opposite;

}

ProjectionEngine::ProjectionEngine(CsProjectionCallback callback, void* userData)
    : m_callback(callback), m_userData(userData) {
    const unsigned int hardware = std::max(1u, std::thread::hardware_concurrency());
    m_poolSize = static_cast<int>(std::min(16u, hardware));
    m_threadCount = m_poolSize;
    m_workerPool = std::make_unique<ProjectionWorkerPoolAdapter>(static_cast<unsigned>(m_poolSize));
}

ProjectionEngine::~ProjectionEngine() { stop(); }

std::shared_ptr<ProjectionJobPayload> ProjectionEngine::make_job_payload(const Job& job) const {
    auto payload = std::make_shared<ProjectionJobPayload>();
    payload->generation = job.generation; payload->tile_id = (uint64_t(uint32_t(job.x)) << 32) | uint32_t(job.y);
    payload->tile_x = job.x; payload->tile_y = job.y; payload->width = job.width; payload->height = job.height;
    payload->dst_stride = job.width * 4; payload->parallelRows = job.parallelRows; payload->output = std::make_shared<std::vector<uint8_t>>(size_t(job.width) * job.height * 4);
    payload->snapshots.reserve(job.layers.size());
    for (const auto& src : job.layers) { ProjectionLayerSnapshot dst; dst.rgba=src.rgba; dst.width=src.width; dst.height=src.height; dst.stride=src.stride; dst.visible=src.visible; dst.mode=src.mode; dst.parameterized=src.parameterized; dst.clipping=src.clipping; dst.opacity=src.opacity; std::copy(std::begin(src.params),std::end(src.params),std::begin(dst.params)); std::copy(std::begin(src.weights),std::end(src.weights),std::begin(dst.weights)); dst.totalWeight=src.totalWeight; dst.oppositeMode=src.oppositeMode; payload->snapshots.push_back(std::move(dst)); }
    payload->layers = payload->snapshots;
    return payload;
}

void ProjectionEngine::setCallback(CsProjectionCallback callback, void* userData) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_callback=callback; m_userData=userData;
}

void ProjectionEngine::setThreads(int threadCount) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_threadCount = threadCount <= 0 ? m_poolSize : std::clamp(threadCount, 1, m_poolSize);
    if (m_workerPool) m_workerPool->set_workers(static_cast<unsigned>(m_threadCount));
}

void ProjectionEngine::compose_projection_tile(const std::shared_ptr<ProjectionJobPayload>& payload) {
    if (!payload) return;
    auto view = make_legacy_composition_view(payload);
    std::vector<uint8_t>& output = *payload->output;
    const creative_core::TileKey cacheKey{view.generation, view.tile_x, view.tile_y};
    if (m_tileCache.get(cacheKey, output)) return;
    output.assign(static_cast<size_t>(view.width) * view.height * 4, 0);
    if (view.size() == 1) {
        const auto& layer = view.layer(0);
        if (layer.visible && !layer.clipping && layer.mode == 0 && layer.opacity >= 1.0f &&
            layer.width >= view.width && layer.height >= view.height &&
            layer.stride >= view.width * 4) {
            for (int y = 0; y < view.height; ++y) {
                const uint8_t* src = layer.rgba.data() + static_cast<size_t>(y) * layer.stride;
                uint8_t* dst = output.data() + static_cast<size_t>(y) * view.width * 4;
                creative_projection::normal_opaque_batch(src, dst, view.width);
            }
            m_tileCache.put(cacheKey, output);
            return;
        }
    }
#ifdef _OPENMP
    int threadCount;
    { std::lock_guard<std::mutex> lock(m_mutex); threadCount = m_threadCount; }
    omp_set_num_threads(std::max(1, threadCount));
#endif
#ifdef _OPENMP
#pragma omp parallel for if(view.parallelRows && view.width * view.height >= 4096) schedule(static)
#endif
    for (int y = 0; y < view.height; ++y) for (int x = 0; x < view.width; ++x) {
        Pixel acc;
        float clipAlpha = 0.0f;
        for (const auto& layer : view) {
            if (!layer.visible) continue;
            const uint8_t* px = layer.rgba.data() + static_cast<size_t>(y) * layer.stride + x * 4;
            RGB src{px[0] / 255.0f, px[1] / 255.0f, px[2] / 255.0f};
            float sa = clamp01((px[3] / 255.0f) * layer.opacity);
            if (layer.clipping) sa *= clipAlpha;
            else clipAlpha = sa;
            if (layer.mode == 0 && sa >= 1.0f && acc.a <= 1e-8f) {
                uint8_t tmp[4];
                creative_projection::normal_opaque_batch(px, tmp, 1);
            }
            const float clippedBackdropAlpha = acc.a;
            projection_compositor::compose_layer(acc, src, sa, layer.mode, layer.params,
                                                 layer.oppositeMode, layer.weights, layer.totalWeight);
            if (layer.clipping) acc.a = clippedBackdropAlpha;
        }
        uint8_t* dst = output.data() + (static_cast<size_t>(y) * view.width + x) * 4;
        for (int c = 0; c < 3; ++c)
            dst[c] = static_cast<uint8_t>(std::clamp(std::lround(clamp01(acc.rgb[c]) * 255), 0L, 255L));
        dst[3] = static_cast<uint8_t>(std::clamp(std::lround(clamp01(acc.a) * 255), 0L, 255L));
    }
    m_tileCache.put(cacheKey, output);
}

bool ProjectionEngine::submit(uint64_t generation,int tileX,int tileY,int width,int height,
                              const CsProjectionLayer* layers,int layerCount) {
    const CsProjectionTile tile{generation, tileX, tileY, width, height, layers, layerCount};
    return submitBatch(&tile, 1);
}

bool ProjectionEngine::submitBatch(const CsProjectionTile* tiles, int tileCount) {
    if (!tiles || tileCount <= 0 || tileCount > 4096) return false;
    constexpr float defaults[11]={1,0,1,1,0,.5f,1,.5f,0,1,0};
    constexpr float minima[11]={0,0,0,.5f,0,0,0,0,-180,0,0};
    constexpr float maxima[11]={1,1,1,2.5f,1,1,1,1,180,2,1};
    std::vector<Job> batch;
    batch.reserve(static_cast<size_t>(tileCount));
    for (int tileIndex = 0; tileIndex < tileCount; ++tileIndex) {
        const auto& srcTile = tiles[tileIndex];
        if (srcTile.width <= 0 || srcTile.height <= 0 || srcTile.layer_count < 0 ||
            srcTile.layer_count > 1024 || (srcTile.layer_count > 0 && !srcTile.layers)) return false;
        Job job;
        job.generation = srcTile.generation; job.x = srcTile.tile_x; job.y = srcTile.tile_y;
        job.width = srcTile.width; job.height = srcTile.height;
        job.layers.reserve(static_cast<size_t>(srcTile.layer_count));
        for (int i = 0; i < srcTile.layer_count; ++i) {
            const auto& src = srcTile.layers[i];
            if (!src.rgba || src.width < srcTile.width || src.height < srcTile.height ||
                src.stride < src.width * 4) return false;
            LayerSnapshot layer; layer.width = src.width; layer.height = src.height; layer.stride = src.stride;
            layer.visible = src.visible; layer.opacity = src.opacity; layer.mode = std::clamp(src.blend_mode, 0, 15); layer.clipping = src.clipping;
            layer.parameterized = src.parameterized;
            std::copy(src.blend_parameters, src.blend_parameters + 11, layer.params);
            for (int p = 0; p < 11; ++p) {
                if (!std::isfinite(layer.params[p])) layer.params[p] = defaults[p];
                layer.params[p] = std::clamp(layer.params[p], minima[p], maxima[p]);
            }
            if (layer.mode == 8 && !layer.parameterized) layer.params[7] = 1.0f;
            layer.opacity = std::clamp(layer.opacity, 0.0f, 1.0f) * layer.params[0];
            layer.oppositeMode = opposite(layer.mode);
            layer.weights[0] = layer.params[2] * (1-layer.params[4]) * (1-layer.params[1]);
            layer.weights[1] = 1-layer.params[2] * (1-layer.params[4]);
            layer.weights[2] = layer.params[2] * (1-layer.params[4]) * layer.params[1];
            layer.totalWeight = layer.weights[0] + layer.weights[1] +
                                (layer.oppositeMode >= 0 ? layer.weights[2] : 0);
            layer.rgba.resize(static_cast<size_t>(src.stride) * src.height);
            for (int row = 0; row < src.height; ++row)
                std::memcpy(layer.rgba.data() + static_cast<size_t>(row) * src.stride,
                            src.rgba + static_cast<size_t>(row) * src.stride,
                            static_cast<size_t>(src.stride));
            job.layers.push_back(std::move(layer));
        }
        batch.push_back(std::move(job));
    }
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_stopping || !m_workerPool) return false;
    }
    CsProjectionCallback callback;
    void* userData;
    { std::lock_guard<std::mutex> lock(m_mutex); callback = m_callback; userData = m_userData; }
    for (auto& job : batch) {
        auto payload = make_job_payload(job);
        payload->callback = [callback, userData](uint64_t generation, int x, int y, const uint8_t* data,
                                                  int width, int height, int stride, const char* error) {
            if (callback) callback(generation, x, y, data, width, height, stride, error, userData);
        };
        ProjectionJob workerJob;
        workerJob.tile_id = payload->tile_id;
        workerJob.payload = payload;
        workerJob.execute = [this, payload] { compose_projection_tile(payload); };
        workerJob.completed = [payload] { payload->complete(); };
        m_workerPool->replace_tile(workerJob.tile_id, std::move(workerJob));
    }
    return true;
}

void ProjectionEngine::stop() {
    { std::lock_guard<std::mutex> lock(m_mutex); if(m_stopping) return; m_stopping=true; }
    if (m_workerPool) {
        m_workerPool->wait_projection_idle();
        m_workerPool->stop_projection_workers();
    }
}
