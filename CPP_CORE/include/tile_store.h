#pragma once

#include <QImage>
#include <QMutex>
#include <QString>
#include <algorithm>
#include <map>
#include <utility>
#include <vector>

// Authoritative sparse resident pixel storage. Scratch persistence and Qt
// event delivery remain adapters owned by the UI layer during migration.
class NativeTileStore final {
public:
    struct TileUpdate { int x; int y; QImage image; bool present = true; };
    struct StoreBatch { NativeTileStore* store; std::vector<TileUpdate> updates; };

    NativeTileStore(int width, int height, int tileSize);

    bool setTile(int tileX, int tileY, const QImage& image);
    bool applyBatch(const std::vector<TileUpdate>& updates);
    static bool applyBatches(const std::vector<StoreBatch>& batches);
    int writeImage(const QImage& image, int x, int y, int width, int height,
                   int* changedCoordinates, int pairCapacity);
    bool copyTile(int tileX, int tileY, QImage& output);
    bool copyResidentFrom(const NativeTileStore& source);
    bool materialize(QImage& output) const;
    long long writeTilePng(int tileX, int tileY, const QString& path) const;
    bool loadTilePng(int tileX, int tileY, const QString& path,
                     unsigned long long expectedRevision);
    bool tileInfo(int tileX, int tileY, bool& resident,
                  unsigned long long& revision, unsigned long long& lastAccess) const;
    int copyKeys(int* coordinates, int pairCapacity) const;
    bool removeTile(int tileX, int tileY);
    void clear();
    void resize(int width, int height);
    int width() const;
    int height() const;
    int tileSize() const;
    int tileCount() const;
    long long allocatedBytes() const;

private:
    using Key = std::pair<int, int>;
    struct Entry { QImage image; };
    QImage blankTile(int tileX, int tileY) const;

    mutable QMutex mutex_;
    int width_;
    int height_;
    int tileSize_;
    std::map<Key, Entry> tiles_;
    std::map<Key, unsigned long long> revisions_;
    std::map<Key, unsigned long long> accesses_;
};
