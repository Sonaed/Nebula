#pragma once

#include "brush_engine.h"

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <thread>

class BrushAsyncWorker {
public:
    using Callback = std::function<void(uint64_t, int, int, int, int,
                                        const uint8_t*, int, bool, const char*)>;
    using SourceProvider = std::function<QImage()>;

    BrushAsyncWorker(const BrushEngine& brush, const QImage& image,
                     uint64_t strokeId, Callback callback);
    BrushAsyncWorker(const BrushEngine& brush, SourceProvider source,
                     uint64_t strokeId, Callback callback);
    ~BrushAsyncWorker();

    bool submit(const BrushInput& start, const BrushInput& end);
    void finish();
    void cancel();

private:
    struct Segment { BrushInput start; BrushInput end; };
    void run();
    QRect dirtyRect(const Segment& segment) const;
    void deliver(const QRect& rect, bool complete, const char* error = nullptr);

    BrushEngine m_brush;
    // Source materialization happens on this worker.  The common source is a
    // borrowed QImage; the sparse TileStore variant builds that QImage here,
    // removing full-document materialization from the tablet/UI thread.
    SourceProvider m_sourceProvider;
    QImage m_image;
    uint64_t m_strokeId;
    Callback m_callback;
    std::thread m_thread;
    std::mutex m_mutex;
    std::condition_variable m_ready;
    std::deque<Segment> m_segments;
    bool m_finishing = false;
    bool m_cancelled = false;
};
