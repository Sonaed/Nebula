#include "brush_async_worker.h"

#include <QColor>
#include <QImage>
#include <QDebug>

#include <chrono>
#include <condition_variable>
#include <mutex>

int main()
{
    BrushEngine engine;
    BrushSettings settings;
    settings.size = 18.0f;
    settings.opacity = 1.0f;
    settings.flow = 1.0f;
    engine.setSettings(settings);
    engine.beginStroke(BrushInput{QPointF(20.0, 20.0), 1.0f});

    QImage source(256, 256, QImage::Format_RGBA8888);
    source.fill(QColor(Qt::white));

    std::mutex mutex;
    std::condition_variable delivered;
    QRect patchRect;
    bool completed = false;
    bool failed = false;
    {
        BrushAsyncWorker worker(engine, source, 42,
            [&](uint64_t, int x, int y, int width, int height,
                const uint8_t*, int, bool complete, const char* error) {
                std::lock_guard lock(mutex);
                if (error) failed = true;
                if (width > 0 && height > 0)
                    patchRect = QRect(x, y, width, height);
                if (complete) completed = true;
                delivered.notify_all();
            });
        const BrushInput start{QPointF(20.0, 20.0), 1.0f};
        const BrushInput end{QPointF(180.0, 140.0), 1.0f};
        if (!worker.submit(start, end)) {
            qCritical() << "[FAIL] async worker rejected a valid segment";
            return 1;
        }
        worker.finish();
        std::unique_lock lock(mutex);
        if (!delivered.wait_for(lock, std::chrono::seconds(3), [&] { return completed; })) {
            qCritical() << "[FAIL] async worker did not complete";
            return 1;
        }
    }

    if (failed || patchRect.isEmpty()) {
        qCritical() << "[FAIL] async worker returned no tile patch";
        return 1;
    }
    qDebug() << "[PASS] async worker returns a tile patch and completes";
    return 0;
}
