#include "tile_store.h"

#include <QMutexLocker>
#include <QPainter>
#include <QImageReader>
#include <QSaveFile>
#include <atomic>
#include <cstring>
#include <cmath>
#include <functional>
#include <mutex>

namespace {
std::atomic<unsigned long long> g_revision{1};
std::atomic<unsigned long long> g_access{1};
}

NativeTileStore::NativeTileStore(int width, int height, int tileSize)
    : width_(std::max(1, width)), height_(std::max(1, height)),
      tileSize_(std::max(1, tileSize)) {}

QImage NativeTileStore::blankTile(int tileX, int tileY) const
{
    const int left = tileX * tileSize_;
    const int top = tileY * tileSize_;
    if (tileX < 0 || tileY < 0 || left >= width_ || top >= height_) return {};
    QImage image(std::min(tileSize_, width_ - left),
                 std::min(tileSize_, height_ - top), QImage::Format_ARGB32);
    image.fill(Qt::transparent);
    return image;
}

bool NativeTileStore::setTile(int tileX, int tileY, const QImage& source)
{
    if (source.isNull()) return false;
    QMutexLocker lock(&mutex_);
    const int left = tileX * tileSize_;
    const int top = tileY * tileSize_;
    if (tileX < 0 || tileY < 0 || left >= width_ || top >= height_) return false;
    const QSize expected(std::min(tileSize_, width_ - left),
                         std::min(tileSize_, height_ - top));
    QImage normalized = source.convertToFormat(QImage::Format_ARGB32);
    QImage target;
    if (normalized.size() == expected) {
        // The bridge input wraps caller-owned bytes; make the store own its copy.
        target = normalized.copy();
    } else {
        target = QImage(expected, QImage::Format_ARGB32);
        target.fill(Qt::transparent);
        QPainter painter(&target);
        painter.setCompositionMode(QPainter::CompositionMode_Source);
        painter.drawImage(0, 0, normalized);
        painter.end();
    }

    bool empty = true;
    for (int row = 0; row < target.height() && empty; ++row) {
        const auto* bytes = target.constScanLine(row);
        for (int i = 0; i < target.width() * 4; ++i) {
            if (bytes[i] != 0) { empty = false; break; }
        }
    }
    const Key key{tileX, tileY};
    const auto revision = g_revision.fetch_add(1, std::memory_order_relaxed);
    revisions_[key] = revision;
    accesses_[key] = g_access.fetch_add(1, std::memory_order_relaxed);
    if (empty) tiles_.erase(key);
    else tiles_[key] = Entry{target};
    return true;
}

bool NativeTileStore::applyBatch(const std::vector<TileUpdate>& updates)
{
    // Stage and validate the whole batch before swapping authoritative state.
    std::vector<TileUpdate> prepared;
    prepared.reserve(updates.size());
    for (const auto& update : updates) {
        const int left = update.x * tileSize_;
        const int top = update.y * tileSize_;
        if (update.x < 0 || update.y < 0 || left >= width_ || top >= height_)
            return false;
        if (!update.present) {
            prepared.push_back({update.x, update.y, QImage(), false});
            continue;
        }
        if (update.image.isNull()) return false;
        const QSize expected(std::min(tileSize_, width_ - left),
                             std::min(tileSize_, height_ - top));
        QImage normalized = update.image.convertToFormat(QImage::Format_ARGB32);
        if (normalized.isNull()) return false;
        QImage owned;
        if (normalized.size() == expected) {
            owned = normalized.copy();
        } else {
            owned = QImage(expected, QImage::Format_ARGB32);
            if (owned.isNull()) return false;
            owned.fill(Qt::transparent);
            QPainter painter(&owned);
            painter.setCompositionMode(QPainter::CompositionMode_Source);
            painter.drawImage(0, 0, normalized);
            painter.end();
        }
        if (owned.isNull()) return false;
        prepared.push_back({update.x, update.y, std::move(owned), true});
    }

    // Allocate nodes only for touched tiles. Copying all three store maps
    // for every import/history batch made repeated writes quadratic in the
    // number of resident tiles. Stage everything before acquiring the lock;
    // erasing and merging these preallocated map nodes cannot allocate.
    std::map<Key, Entry> nextTiles;
    std::map<Key, unsigned long long> nextRevisions;
    std::map<Key, unsigned long long> nextAccesses;
    for (const auto& update : prepared) {
        const Key key{update.x, update.y};
        bool empty = !update.present;
        if (update.present) {
            empty = true;
            for (int row = 0; row < update.image.height() && empty; ++row) {
                const auto* bytes = update.image.constScanLine(row);
                for (int i = 0; i < update.image.width() * 4; ++i) {
                    if (bytes[i] != 0) { empty = false; break; }
                }
            }
        }
        if (empty) nextTiles.erase(key);
        else nextTiles[key] = Entry{update.image};
        nextRevisions[key] = 0;
        nextAccesses[key] = 0;
    }
    QMutexLocker lock(&mutex_);
    for (auto& item : nextRevisions) {
        item.second = g_revision.fetch_add(1, std::memory_order_relaxed);
        nextAccesses.at(item.first) = g_access.fetch_add(1, std::memory_order_relaxed);
        tiles_.erase(item.first);
        revisions_.erase(item.first);
        accesses_.erase(item.first);
    }
    tiles_.merge(nextTiles);
    revisions_.merge(nextRevisions);
    accesses_.merge(nextAccesses);
    return true;
}

bool NativeTileStore::applyBatches(const std::vector<StoreBatch>& batches)
{
    struct PreparedBatch {
        NativeTileStore* store;
        std::vector<TileUpdate> updates;
        std::map<Key, Entry> tiles;
        std::map<Key, unsigned long long> revisions;
        std::map<Key, unsigned long long> accesses;
    };
    try {
        std::vector<NativeTileStore*> ordered;
        ordered.reserve(batches.size());
        for (const auto& batch : batches) {
            if (!batch.store) return false;
            ordered.push_back(batch.store);
        }
        std::sort(ordered.begin(), ordered.end(), std::less<NativeTileStore*>{});
        if (std::adjacent_find(ordered.begin(), ordered.end()) != ordered.end()) return false;
        std::vector<std::unique_lock<QMutex>> locks;
        locks.reserve(ordered.size());
        for (auto* store : ordered) locks.emplace_back(store->mutex_);

        std::vector<PreparedBatch> prepared;
        prepared.reserve(batches.size());
        for (const auto& batch : batches) {
            PreparedBatch next{batch.store, {}, batch.store->tiles_,
                               batch.store->revisions_, batch.store->accesses_};
            next.updates.reserve(batch.updates.size());
            for (const auto& update : batch.updates) {
                const int left = update.x * batch.store->tileSize_;
                const int top = update.y * batch.store->tileSize_;
                if (update.x < 0 || update.y < 0 || left >= batch.store->width_ ||
                    top >= batch.store->height_) return false;
                if (!update.present) {
                    next.updates.push_back({update.x, update.y, QImage(), false});
                    continue;
                }
                if (update.image.isNull()) return false;
                const QSize expected(
                    std::min(batch.store->tileSize_, batch.store->width_ - left),
                    std::min(batch.store->tileSize_, batch.store->height_ - top));
                QImage normalized = update.image.convertToFormat(QImage::Format_ARGB32);
                if (normalized.isNull()) return false;
                QImage owned;
                if (normalized.size() == expected) {
                    owned = normalized.copy();
                } else {
                    owned = QImage(expected, QImage::Format_ARGB32);
                    if (owned.isNull()) return false;
                    owned.fill(Qt::transparent);
                    QPainter painter(&owned);
                    painter.setCompositionMode(QPainter::CompositionMode_Source);
                    painter.drawImage(0, 0, normalized);
                    painter.end();
                }
                if (owned.isNull()) return false;
                next.updates.push_back({update.x, update.y, std::move(owned), true});
            }
            for (const auto& update : next.updates) {
                const Key key{update.x, update.y};
                if (!update.present) {
                    next.tiles.erase(key);
                } else {
                    bool empty = true;
                    for (int row = 0; row < update.image.height() && empty; ++row) {
                        const auto* bytes = update.image.constScanLine(row);
                        for (int i = 0; i < update.image.width() * 4; ++i) {
                            if (bytes[i] != 0) { empty = false; break; }
                        }
                    }
                    if (empty) next.tiles.erase(key);
                    else next.tiles[key] = Entry{update.image};
                }
                next.revisions[key] = g_revision.fetch_add(1, std::memory_order_relaxed);
                next.accesses[key] = g_access.fetch_add(1, std::memory_order_relaxed);
            }
            prepared.push_back(std::move(next));
        }
        // All copies and validations are complete while every store is locked;
        // swaps cannot allocate, so observers see either side of the transaction.
        for (auto& next : prepared) {
            next.store->tiles_.swap(next.tiles);
            next.store->revisions_.swap(next.revisions);
            next.store->accesses_.swap(next.accesses);
        }
        return true;
    } catch (...) {
        return false;
    }
}

bool NativeTileStore::thumbnail(QImage& output) const
{
    if (output.isNull()) return false;
    QMutexLocker lock(&mutex_);
    output.fill(Qt::transparent);
    QPainter painter(&output);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    // Use the same uniform scale as the layer panel, including rounded height.
    const double scale = std::max(output.width(), output.height()) /
                         static_cast<double>(std::max(width_, height_));
    for (const auto& item : tiles_) {
        const auto& image = item.second.image;
        painter.drawImage(QRectF(item.first.first * tileSize_ * scale,
                                 item.first.second * tileSize_ * scale,
                                 image.width() * scale, image.height() * scale), image);
    }
    return painter.end();
}

bool NativeTileStore::importRgba(const QImage& image, int x, int y)
{
    if (image.isNull() || image.format() != QImage::Format_RGBA8888) return false;
    {
        QMutexLocker lock(&mutex_);
        if (!tiles_.empty()) return false;
    }
    // Clip with wide arithmetic: PSD layer origins can be negative.
    const int left = static_cast<int>(std::max(0LL, std::min<long long>(width(), x)));
    const int top = static_cast<int>(std::max(0LL, std::min<long long>(height(), y)));
    const int right = static_cast<int>(std::max(0LL, std::min<long long>(width(), static_cast<long long>(x) + image.width())));
    const int bottom = static_cast<int>(std::max(0LL, std::min<long long>(height(), static_cast<long long>(y) + image.height())));
    if (right <= left || bottom <= top) return true;
    std::vector<TileUpdate> batch;
    batch.reserve(256);
    for (int ty = top / tileSize_; ty <= (bottom - 1) / tileSize_; ++ty) {
        for (int tx = left / tileSize_; tx <= (right - 1) / tileSize_; ++tx) {
            const QRect area(tx * tileSize_, ty * tileSize_,
                             std::min(tileSize_, width() - tx * tileSize_),
                             std::min(tileSize_, height() - ty * tileSize_));
            QImage tile(area.size(), QImage::Format_ARGB32);
            if (tile.isNull()) return false;
            tile.fill(Qt::transparent);
            bool populated = false;
            for (int row = std::max(top, area.top()); row < std::min(bottom, area.bottom() + 1); ++row) {
                const auto* source = image.constScanLine(row - y);
                auto* target = reinterpret_cast<QRgb*>(tile.scanLine(row - area.top()));
                for (int column = std::max(left, area.left()); column < std::min(right, area.right() + 1); ++column) {
                    const auto* pixel = source + static_cast<qint64>(column - x) * 4;
                    if (pixel[3]) {
                        target[column - area.left()] = qRgba(pixel[0], pixel[1], pixel[2], pixel[3]);
                        populated = true;
                    }
                }
            }
            // Invisible RGB in zero-alpha pixels is deliberately canonicalized
            // to zero, matching the PSD importer without NumPy boolean copies.
            if (populated) batch.push_back({tx, ty, std::move(tile), true});
            if (batch.size() == 256) {
                if (!applyBatch(batch)) return false;
                batch.clear();
            }
        }
    }
    return batch.empty() || applyBatch(batch);
}

int NativeTileStore::writeImage(const QImage& image, int x, int y, int width, int height,
                                int* changedCoordinates, int pairCapacity)
{
    if (image.isNull() || image.size() != QSize(this->width(), this->height()) ||
        width <= 0 || height <= 0) return 0;
    const QRect requested(x, y, width, height);
    const QRect bounds(0, 0, this->width(), this->height());
    const QRect dirty = requested.intersected(bounds);
    if (dirty.isEmpty()) return 0;
    const int leftTile = dirty.left() / tileSize_;
    const int rightTile = dirty.right() / tileSize_;
    const int topTile = dirty.top() / tileSize_;
    const int bottomTile = dirty.bottom() / tileSize_;
    int changed = 0;
    for (int ty = topTile; ty <= bottomTile; ++ty) {
        for (int tx = leftTile; tx <= rightTile; ++tx) {
            const QRect tileRect(tx * tileSize_, ty * tileSize_,
                std::min(tileSize_, this->width() - tx * tileSize_),
                std::min(tileSize_, this->height() - ty * tileSize_));
            const QRect affected = tileRect.intersected(dirty);
            QImage patch;
            if (affected == tileRect) {
                patch = image.copy(tileRect);
            } else {
                // Preserve pixels outside a dirty-rectangle write.
                patch = QImage(tileRect.size(), QImage::Format_ARGB32);
                if (!copyTile(tx, ty, patch)) return -1;
                QPainter painter(&patch);
                painter.setCompositionMode(QPainter::CompositionMode_Source);
                painter.drawImage(affected.topLeft() - tileRect.topLeft(), image, affected);
                painter.end();
            }
            if (!setTile(tx, ty, patch)) return -1;
            if (changedCoordinates && changed < pairCapacity) {
                changedCoordinates[changed * 2] = tx;
                changedCoordinates[changed * 2 + 1] = ty;
            }
            ++changed;
        }
    }
    return changed;
}

bool NativeTileStore::copyTile(int tileX, int tileY, QImage& output)
{
    QMutexLocker lock(&mutex_);
    QImage expected = blankTile(tileX, tileY);
    if (expected.isNull() || output.isNull() || output.size() != expected.size()) return false;
    output.fill(Qt::transparent);
    const auto it = tiles_.find(Key{tileX, tileY});
    accesses_[Key{tileX, tileY}] = g_access.fetch_add(1, std::memory_order_relaxed);
    if (it == tiles_.end()) return true;
    QPainter painter(&output);
    painter.setCompositionMode(QPainter::CompositionMode_Source);
    painter.drawImage(0, 0, it->second.image);
    painter.end();
    return true;
}

bool NativeTileStore::compositeFrom(const NativeTileStore& source, float opacity, int mode)
{
    if (&source == this || !std::isfinite(opacity) || mode < 0 || mode > 11 ||
        width_ != source.width_ || height_ != source.height_ || tileSize_ != source.tileSize_)
        return false;
    static const QPainter::CompositionMode modes[] = {
        QPainter::CompositionMode_SourceOver, QPainter::CompositionMode_Darken,
        QPainter::CompositionMode_Multiply, QPainter::CompositionMode_ColorBurn,
        QPainter::CompositionMode_Lighten, QPainter::CompositionMode_Screen,
        QPainter::CompositionMode_ColorDodge, QPainter::CompositionMode_Overlay,
        QPainter::CompositionMode_SoftLight, QPainter::CompositionMode_HardLight,
        QPainter::CompositionMode_Difference, QPainter::CompositionMode_Exclusion,
    };
    // A stable two-store lock prevents a merge racing a simultaneous native read.
    std::unique_lock<QMutex> first(mutex_, std::defer_lock);
    std::unique_lock<QMutex> second(source.mutex_, std::defer_lock);
    if (std::less<const NativeTileStore*>{}(this, &source)) std::lock(first, second);
    else std::lock(second, first);
    try {
        for (const auto& [key, sourceEntry] : source.tiles_) {
            auto target = tiles_.find(key);
            if (target == tiles_.end()) {
                QImage blank = blankTile(key.first, key.second);
                if (blank.isNull()) return false;
                target = tiles_.emplace(key, Entry{std::move(blank)}).first;
            }
            // Source-over with a fully opaque source is an exact replacement.
            // Sharing the immutable source backing store avoids a QPainter setup
            // and a full per-pixel blend for dense paint layers; a later write
            // detaches normally through QImage copy-on-write.
            bool sourceOpaque = (mode == 0 && opacity >= 1.0f - 1e-7f);
            for (int row = 0; sourceOpaque && row < sourceEntry.image.height(); ++row) {
                const auto* pixels = reinterpret_cast<const QRgb*>(sourceEntry.image.constScanLine(row));
                for (int column = 0; column < sourceEntry.image.width(); ++column) {
                    if (qAlpha(pixels[column]) != 255) { sourceOpaque = false; break; }
                }
            }
            if (sourceOpaque) {
                target->second.image = sourceEntry.image;
                revisions_[key] = g_revision.fetch_add(1, std::memory_order_relaxed);
                accesses_[key] = g_access.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            QPainter painter(&target->second.image);
            if (!painter.isActive()) return false;
            painter.setCompositionMode(modes[mode]);
            painter.setOpacity(std::clamp(opacity, 0.0f, 1.0f));
            painter.drawImage(0, 0, sourceEntry.image);
            painter.end();
            revisions_[key] = g_revision.fetch_add(1, std::memory_order_relaxed);
            accesses_[key] = g_access.fetch_add(1, std::memory_order_relaxed);
        }
    } catch (...) { return false; }
    return true;
}

bool NativeTileStore::copyResidentFrom(const NativeTileStore& source)
{
    if (this == &source) return true;
    std::map<Key, Entry> copiedTiles;
    int sourceWidth = 0, sourceHeight = 0, sourceTileSize = 0;
    {
        QMutexLocker sourceLock(&source.mutex_);
        sourceWidth = source.width_;
        sourceHeight = source.height_;
        sourceTileSize = source.tileSize_;
        copiedTiles = source.tiles_; // QImage data remains implicitly shared.
    }

    std::map<Key, unsigned long long> copiedRevisions;
    std::map<Key, unsigned long long> copiedAccesses;
    for (const auto& [key, _entry] : copiedTiles) {
        copiedRevisions[key] = g_revision.fetch_add(1, std::memory_order_relaxed);
        copiedAccesses[key] = g_access.fetch_add(1, std::memory_order_relaxed);
    }
    {
        QMutexLocker targetLock(&mutex_);
        if (width_ != sourceWidth || height_ != sourceHeight ||
            tileSize_ != sourceTileSize) return false;
        tiles_ = std::move(copiedTiles);
        revisions_ = std::move(copiedRevisions);
        accesses_ = std::move(copiedAccesses);
    }
    return true;
}

bool NativeTileStore::materialize(QImage& output) const
{
    QMutexLocker lock(&mutex_);
    if (output.isNull() || output.size() != QSize(width_, height_)) return false;
    output.fill(Qt::transparent);
    QPainter painter(&output);
    painter.setCompositionMode(QPainter::CompositionMode_Source);
    for (const auto& [key, entry] : tiles_)
        painter.drawImage(key.first * tileSize_, key.second * tileSize_, entry.image);
    painter.end();
    return true;
}

long long NativeTileStore::writeTilePng(int tileX, int tileY, const QString& path) const
{
    QImage image;
    {
        QMutexLocker lock(&mutex_);
        const auto it = tiles_.find(Key{tileX, tileY});
        if (it == tiles_.end()) return 0;
        image = it->second.image;
    }
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly) || !image.save(&file, "PNG") || !file.commit()) {
        file.cancelWriting();
        return 0;
    }
    return image.sizeInBytes();
}

bool NativeTileStore::loadTilePng(int tileX, int tileY, const QString& path,
                                  unsigned long long expectedRevision)
{
    QImageReader reader(path);
    QImage image = reader.read();
    if (image.isNull()) return false;
    image = image.convertToFormat(QImage::Format_ARGB32);
    QMutexLocker lock(&mutex_);
    const Key key{tileX, tileY};
    const int left = tileX * tileSize_, top = tileY * tileSize_;
    if (tileX < 0 || tileY < 0 || left >= width_ || top >= height_) return false;
    const QSize expected(std::min(tileSize_, width_ - left),
                         std::min(tileSize_, height_ - top));
    const auto rev = revisions_.find(key);
    const unsigned long long currentRevision = rev == revisions_.end() ? 0 : rev->second;
    if (currentRevision != expectedRevision || tiles_.find(key) != tiles_.end() ||
        image.size() != expected) return false;
    tiles_[key] = Entry{image.copy()};
    accesses_[key] = g_access.fetch_add(1, std::memory_order_relaxed);
    return true;
}

bool NativeTileStore::tileInfo(int tileX, int tileY, bool& resident,
                               unsigned long long& revision,
                               unsigned long long& lastAccess) const
{
    QMutexLocker lock(&mutex_);
    const int left = tileX * tileSize_, top = tileY * tileSize_;
    if (tileX < 0 || tileY < 0 || left >= width_ || top >= height_) return false;
    const Key key{tileX, tileY};
    const auto it = tiles_.find(key);
    resident = it != tiles_.end();
    const auto revIt = revisions_.find(key);
    const auto accessIt = accesses_.find(key);
    revision = revIt == revisions_.end() ? 0 : revIt->second;
    lastAccess = accessIt == accesses_.end() ? revision : accessIt->second;
    return true;
}

int NativeTileStore::copyKeys(int* coordinates, int pairCapacity) const
{
    QMutexLocker lock(&mutex_);
    if (coordinates && pairCapacity > 0) {
        int index = 0;
        for (const auto& [key, _entry] : tiles_) {
            if (index >= pairCapacity) break;
            coordinates[index * 2] = key.first;
            coordinates[index * 2 + 1] = key.second;
            ++index;
        }
    }
    return coordinates && pairCapacity > 0
        ? std::min(pairCapacity, static_cast<int>(tiles_.size()))
        : static_cast<int>(tiles_.size());
}

int NativeTileStore::copyKeyRevisions(int* coordinates, unsigned long long* revisions,
                                      int pairCapacity) const
{
    QMutexLocker lock(&mutex_);
    const bool fill = coordinates && revisions && pairCapacity > 0;
    if (fill) {
        int index = 0;
        for (const auto& [key, _entry] : tiles_) {
            if (index >= pairCapacity) break;
            coordinates[index * 2] = key.first;
            coordinates[index * 2 + 1] = key.second;
            const auto found = revisions_.find(key);
            revisions[index] = found == revisions_.end() ? 0ULL : found->second;
            ++index;
        }
    }
    return fill ? std::min(pairCapacity, static_cast<int>(tiles_.size()))
                : static_cast<int>(tiles_.size());
}

int NativeTileStore::copyOpaqueKeys(int* coordinates, int pairCapacity) const
{
    QMutexLocker lock(&mutex_);
    const bool fill = coordinates && pairCapacity > 0;
    int count = 0;
    for (const auto& [key, entry] : tiles_) {
        const QImage& image = entry.image;
        bool opaque = !image.isNull();
        for (int row = 0; row < image.height() && opaque; ++row) {
            const auto* pixels = reinterpret_cast<const QRgb*>(image.constScanLine(row));
            for (int column = 0; column < image.width(); ++column) {
                if (qAlpha(pixels[column]) != 255) {
                    opaque = false;
                    break;
                }
            }
        }
        if (!opaque) continue;
        if (fill && count < pairCapacity) {
            coordinates[count * 2] = key.first;
            coordinates[count * 2 + 1] = key.second;
        }
        ++count;
    }
    return fill ? std::min(pairCapacity, count) : count;
}

bool NativeTileStore::removeTile(int tileX, int tileY)
{
    QMutexLocker lock(&mutex_);
    return tiles_.erase(Key{tileX, tileY}) != 0;
}

void NativeTileStore::clear()
{
    QMutexLocker lock(&mutex_);
    tiles_.clear();
    revisions_.clear();
    accesses_.clear();
}

void NativeTileStore::resize(int width, int height)
{
    QMutexLocker lock(&mutex_);
    width_ = std::max(1, width);
    height_ = std::max(1, height);
    tiles_.clear();
    revisions_.clear();
    accesses_.clear();
}

int NativeTileStore::width() const { QMutexLocker lock(&mutex_); return width_; }
int NativeTileStore::height() const { QMutexLocker lock(&mutex_); return height_; }
int NativeTileStore::tileSize() const { return tileSize_; }
int NativeTileStore::tileCount() const { QMutexLocker lock(&mutex_); return static_cast<int>(tiles_.size()); }

long long NativeTileStore::allocatedBytes() const
{
    QMutexLocker lock(&mutex_);
    long long total = 0;
    for (const auto& [_, entry] : tiles_) total += entry.image.sizeInBytes();
    return total;
}
