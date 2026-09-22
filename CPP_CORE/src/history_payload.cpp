#include "history_payload.h"

#include <QMutexLocker>
#include <cstring>

int HistoryPayload::append(const QImage* before, const QImage* after)
{
    const bool hasBefore = before && !before->isNull();
    const bool hasAfter = after && !after->isNull();
    if (!hasBefore && !hasAfter) return 2;
    if (hasBefore && hasAfter && *before == *after) return 2;
    QImage oldImage = before ? before->copy() : QImage();
    QImage newImage = after ? after->copy() : QImage();
    if ((before && !before->isNull() && oldImage.isNull()) ||
        (after && !after->isNull() && newImage.isNull())) return 0;
    QMutexLocker lock(&mutex_);
    tiles_.emplace_back(std::move(oldImage), std::move(newImage));
    return 1;
}

bool HistoryPayload::appendMany(
    const std::vector<std::pair<const QImage*, const QImage*>>& items,
    std::vector<int>& payloadIndices)
{
    std::vector<int> indices(items.size(), -1);
    QMutexLocker lock(&mutex_);
    const size_t originalSize = tiles_.size();
    try {
        tiles_.reserve(originalSize + items.size());
        for (size_t i = 0; i < items.size(); ++i) {
            const QImage* before = items[i].first;
            const QImage* after = items[i].second;
            const bool hasBefore = before && !before->isNull();
            const bool hasAfter = after && !after->isNull();
            if (!hasBefore && !hasAfter) continue;
            if (hasBefore && hasAfter && *before == *after) continue;
            QImage oldImage = hasBefore ? before->copy() : QImage();
            QImage newImage = hasAfter ? after->copy() : QImage();
            if ((hasBefore && oldImage.isNull()) || (hasAfter && newImage.isNull())) {
                tiles_.resize(originalSize);
                return false;
            }
            indices[i] = static_cast<int>(tiles_.size());
            tiles_.emplace_back(std::move(oldImage), std::move(newImage));
        }
    } catch (...) {
        tiles_.resize(originalSize);
        return false;
    }
    payloadIndices.swap(indices);
    return true;
}

bool HistoryPayload::tileInfo(int index, int side, bool& present, int& width,
                              int& height, int& format) const
{
    QMutexLocker lock(&mutex_);
    if (index < 0 || index >= static_cast<int>(tiles_.size()) ||
        (side != 0 && side != 1)) return false;
    const QImage& image = side == 0 ? tiles_[index].first : tiles_[index].second;
    present = !image.isNull();
    width = image.width();
    height = image.height();
    format = static_cast<int>(image.format());
    return true;
}

bool HistoryPayload::copyTile(int index, int side, QImage& output) const
{
    QMutexLocker lock(&mutex_);
    if (index < 0 || index >= static_cast<int>(tiles_.size()) ||
        (side != 0 && side != 1)) return false;
    const QImage& image = side == 0 ? tiles_[index].first : tiles_[index].second;
    if (image.isNull() || output.size() != image.size() || output.format() != image.format() ||
        output.bytesPerLine() < image.bytesPerLine())
        return false;
    for (int y = 0; y < image.height(); ++y)
        std::memcpy(output.scanLine(y), image.constScanLine(y),
                    static_cast<size_t>(image.bytesPerLine()));
    return true;
}

int HistoryPayload::count() const
{
    QMutexLocker lock(&mutex_);
    return static_cast<int>(tiles_.size());
}

long long HistoryPayload::allocatedBytes() const
{
    QMutexLocker lock(&mutex_);
    long long bytes = 0;
    for (const auto& pair : tiles_)
        bytes += pair.first.sizeInBytes() + pair.second.sizeInBytes();
    return bytes;
}

void HistoryPayload::clear()
{
    QMutexLocker lock(&mutex_);
    tiles_.clear();
}
