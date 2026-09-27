#pragma once

#include <QImage>
#include <QMutex>
#include <utility>
#include <vector>

// Owns immutable before/after raster deltas for undo steps in CreativeCore.
class HistoryPayload final {
public:
    // 1=stored, 2=unchanged, 0=invalid/failure.
    int append(const QImage* before, const QImage* after);
    bool appendMany(const std::vector<std::pair<const QImage*, const QImage*>>& items,
                    std::vector<int>& payloadIndices);
    bool tileInfo(int index, int side, bool& present, int& width, int& height,
                  int& format) const;
    bool copyTile(int index, int side, QImage& output) const;
    int count() const;
    long long allocatedBytes() const;
    void clear();

private:
    mutable QMutex mutex_;
    std::vector<std::pair<QImage, QImage>> tiles_;
};
