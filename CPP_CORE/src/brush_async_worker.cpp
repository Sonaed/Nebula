#include "brush_async_worker.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

BrushAsyncWorker::BrushAsyncWorker(const BrushEngine& brush, const QImage& image,
                                   uint64_t strokeId, Callback callback)
    : BrushAsyncWorker(brush, [image] { return image; }, strokeId, std::move(callback)) {}

BrushAsyncWorker::BrushAsyncWorker(const BrushEngine& brush, SourceProvider source,
                                   uint64_t strokeId, Callback callback)
    : m_brush(brush), m_sourceProvider(std::move(source)), m_strokeId(strokeId),
      m_callback(std::move(callback)), m_thread(&BrushAsyncWorker::run, this) {}

BrushAsyncWorker::~BrushAsyncWorker() { cancel(); if (m_thread.joinable()) m_thread.join(); }

bool BrushAsyncWorker::submit(const BrushInput& start, const BrushInput& end) {
    std::lock_guard lock(m_mutex);
    if (m_finishing || m_cancelled) return false;
    m_segments.push_back({start, end});
    m_ready.notify_one();
    return true;
}

void BrushAsyncWorker::finish() { { std::lock_guard lock(m_mutex); m_finishing = true; } m_ready.notify_one(); }
void BrushAsyncWorker::cancel() { { std::lock_guard lock(m_mutex); m_cancelled = true; m_segments.clear(); } m_ready.notify_one(); }

QRect BrushAsyncWorker::dirtyRect(const Segment& segment) const {
    const auto& settings = m_brush.settings();
    const float reach = std::max(1.0f, settings.size *
        (1.0f + settings.sizeJitter + settings.scatter) * 0.5f) + 3.0f;
    const int left = int(std::floor(std::min(segment.start.position.x(), segment.end.position.x()) - reach));
    const int top = int(std::floor(std::min(segment.start.position.y(), segment.end.position.y()) - reach));
    const int right = int(std::ceil(std::max(segment.start.position.x(), segment.end.position.x()) + reach));
    const int bottom = int(std::ceil(std::max(segment.start.position.y(), segment.end.position.y()) + reach));
    return QRect(left, top, right - left + 1, bottom - top + 1)
        .intersected(QRect(0, 0, m_image.width(), m_image.height()));
}

void BrushAsyncWorker::deliver(const QRect& rect, bool complete, const char* error) {
    if (!m_callback) return;
    if (rect.isEmpty()) { m_callback(m_strokeId, 0, 0, 0, 0, nullptr, 0, complete, error); return; }
    const int stride = rect.width() * 4;
    std::vector<uint8_t> patch(size_t(stride) * size_t(rect.height()));
    for (int y = 0; y < rect.height(); ++y)
        std::memcpy(patch.data() + size_t(y) * stride,
                    m_image.constScanLine(rect.y() + y) + rect.x() * 4, size_t(stride));
    m_callback(m_strokeId, rect.x(), rect.y(), rect.width(), rect.height(), patch.data(), stride, complete, error);
}

void BrushAsyncWorker::run() {
    // This deep copy deliberately happens on the worker, not in the C ABI
    // entry point called by Canvas.tabletEvent().  Canvas keeps the source
    // layer alive and joins/cancels this worker before replacing a document;
    // no UI-side pixels are edited until this worker returns its first patch.
    m_image = m_sourceProvider ? m_sourceProvider() : QImage();
    m_sourceProvider = {};
    if (m_image.isNull()) {
        deliver(QRect(), true, "Native brush worker could not snapshot image");
        return;
    }
    // Four input segments are enough to amortise a Python callback and a
    // tile-store write, while keeping the first queued segment immediately
    // responsive on a normal stylus stream.
    constexpr size_t maxSegmentsPerPatch = 4;
    for (;;) {
        std::vector<Segment> segments;
        bool complete = false;
        {
            std::unique_lock lock(m_mutex);
            m_ready.wait(lock, [&] { return m_cancelled || !m_segments.empty() || m_finishing; });
            if (m_cancelled) return;
            if (m_segments.empty() && m_finishing) { complete = true; }
            else {
                const size_t count = std::min(maxSegmentsPerPatch, m_segments.size());
                segments.reserve(count);
                for (size_t index = 0; index < count; ++index) {
                    segments.push_back(m_segments.front());
                    m_segments.pop_front();
                }
            }
        }
        if (complete) { m_brush.endStroke(); deliver(QRect(), true); return; }
        try {
            QRect dirty;
            for (const Segment& segment : segments) {
                const QRect rect = dirtyRect(segment);
                dirty = dirty.isEmpty() ? rect : dirty.united(rect);
                m_brush.drawSegment(m_image, segment.start, segment.end);
            }
            deliver(dirty, false);
        } catch (...) { deliver(QRect(), true, "Native brush worker failed"); return; }
    }
}
