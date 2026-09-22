#pragma once

#include "creative_core_api.h"
#include "projection_worker_pool_adapter.h"
#include "tile_cache.h"

#include <cstdint>
#include <mutex>
#include <vector>

class ProjectionEngine {
public:
    ProjectionEngine(CsProjectionCallback callback, void* userData);
    ~ProjectionEngine();
    bool submit(uint64_t generation, int tileX, int tileY, int width, int height,
                const CsProjectionLayer* layers, int layerCount);
    bool submitBatch(const CsProjectionTile* tiles, int tileCount);
    void setCallback(CsProjectionCallback callback, void* userData);
    void setThreads(int threadCount);
    void stop();

private:
    struct LayerSnapshot {
        std::vector<uint8_t> rgba;
        int width = 0, height = 0, stride = 0, visible = 0, mode = 0, parameterized = 0, clipping = 0;
        float opacity = 1.0f;
        float params[11]{};
        float weights[3]{};
        float totalWeight = 0.0f;
        int oppositeMode = -1;
    };
    struct Job {
        uint64_t generation = 0;
        int x = 0, y = 0, width = 0, height = 0;
        bool parallelRows = false;
        std::vector<LayerSnapshot> layers;
    };
    std::shared_ptr<ProjectionJobPayload> make_job_payload(const Job& job) const;
    void compose_projection_tile(const std::shared_ptr<ProjectionJobPayload>& payload);
    CsProjectionCallback m_callback;
    void* m_userData;
    std::mutex m_mutex;
    bool m_stopping = false;
    int m_threadCount = 0;
    int m_poolSize = 1;
    int m_activeWorkers = 0;
    std::unique_ptr<ProjectionWorkerPoolAdapter> m_workerPool;
    creative_core::TileCache m_tileCache;
};
