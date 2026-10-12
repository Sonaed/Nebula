#include "tile_store.h"

#include <QColor>
#include <QImage>
#include <QPainter>

#include <cassert>
#include <cstdint>
#include <iostream>

int main()
{
    NativeTileStore store(70, 67, 64);
    QImage source(70, 67, QImage::Format_ARGB32);
    source.fill(QColor(180, 40, 70, 210));
    int keys[8]{};
    const int changed = store.writeImage(source, 0, 0, 70, 67, keys, 4);
    assert(changed == 4);
    assert(store.tileCount() == 4);
    assert(store.allocatedBytes() == 70LL * 67LL * 4LL);

    QImage composite(70, 67, QImage::Format_ARGB32);
    assert(store.materialize(composite));
    assert(composite.pixelColor(69, 66) == QColor(180, 40, 70, 210));

    QImage overlay(70, 67, QImage::Format_ARGB32);
    overlay.fill(Qt::transparent);
    overlay.setPixelColor(65, 65, QColor("cyan"));
    assert(store.writeImage(overlay, 65, 65, 1, 1, nullptr, 0) == 1);
    QImage edgeTile(6, 3, QImage::Format_ARGB32);
    assert(store.copyTile(1, 1, edgeTile));
    assert(edgeTile.pixelColor(1, 1) == QColor("cyan"));
    assert(edgeTile.pixelColor(0, 0) == QColor(180, 40, 70, 210));


    bool resident = false;
    unsigned long long revision = 0, access = 0;
    assert(store.tileInfo(1, 1, resident, revision, access));
    assert(resident && revision > 0 && access > 0);
    assert(store.removeTile(1, 1));
    assert(store.tileInfo(1, 1, resident, revision, access));
    assert(!resident && revision > 0);

    NativeTileStore clone(70, 67, 64);
    assert(clone.copyResidentFrom(store));
    assert(clone.tileCount() == 3);
    QImage clonedTile(64, 64, QImage::Format_ARGB32);
    assert(clone.copyTile(0, 0, clonedTile));
    assert(clonedTile.pixelColor(2, 2) == QColor(180, 40, 70, 210));
    QImage changedCloneTile(64, 64, QImage::Format_ARGB32);
    changedCloneTile.fill(QColor("lime"));
    assert(clone.setTile(0, 0, changedCloneTile));
    QImage originalTile(64, 64, QImage::Format_ARGB32);
    assert(store.copyTile(0, 0, originalTile));
    assert(originalTile.pixelColor(2, 2) == QColor(180, 40, 70, 210));
    assert(clone.copyTile(0, 0, clonedTile));
    assert(clonedTile.pixelColor(2, 2) == QColor("lime"));

    NativeTileStore atomic(70, 67, 64);
    QImage initial(64, 64, QImage::Format_ARGB32);
    initial.fill(QColor("red"));
    assert(atomic.setTile(0, 0, initial));
    QImage replacement(64, 64, QImage::Format_ARGB32);
    replacement.fill(QColor("blue"));
    const std::vector<NativeTileStore::TileUpdate> invalidBatch{
        {0, 0, replacement, true}, {2, 0, replacement, true}};
    assert(!atomic.applyBatch(invalidBatch));
    QImage unchanged(64, 64, QImage::Format_ARGB32);
    assert(atomic.copyTile(0, 0, unchanged));
    assert(unchanged.pixelColor(0, 0) == QColor("red"));
    assert(atomic.tileCount() == 1);

    // A batch touches only its own keys; duplicates are last-write-wins,
    // including explicit removals, while unrelated resident tiles survive.
    assert(atomic.setTile(1, 0, initial));
    const std::vector<NativeTileStore::TileUpdate> repeatedBatch{
        {0, 0, replacement, true}, {0, 0, QImage(), false},
        {0, 0, initial, true}};
    assert(atomic.applyBatch(repeatedBatch));
    assert(atomic.tileCount() == 2);
    assert(atomic.copyTile(0, 0, unchanged));
    assert(unchanged.pixelColor(0, 0) == QColor("red"));
    assert(atomic.applyBatch({{0, 0, QImage(), false}}));
    assert(atomic.tileCount() == 1);
    assert(atomic.tileInfo(0, 0, resident, revision, access));
    assert(!resident && revision > 0);

    NativeTileStore first(64, 64, 64);
    NativeTileStore second(64, 64, 64);
    QImage firstBefore(64, 64, QImage::Format_ARGB32);
    QImage secondBefore(64, 64, QImage::Format_ARGB32);
    firstBefore.fill(QColor("red"));
    secondBefore.fill(QColor("green"));
    assert(first.setTile(0, 0, firstBefore));
    assert(second.setTile(0, 0, secondBefore));
    QImage firstAfter(64, 64, QImage::Format_ARGB32);
    QImage secondAfter(64, 64, QImage::Format_ARGB32);
    firstAfter.fill(QColor("blue"));
    secondAfter.fill(QColor("yellow"));
    const std::vector<NativeTileStore::StoreBatch> crossStoreFailure{
        {&first, {{0, 0, firstAfter, true}}},
        {&second, {{0, 0, secondAfter, true}, {1, 0, secondAfter, true}}},
    };
    assert(!NativeTileStore::applyBatches(crossStoreFailure));
    QImage check(64, 64, QImage::Format_ARGB32);
    assert(first.copyTile(0, 0, check));
    assert(check.pixelColor(0, 0) == QColor("red"));
    assert(second.copyTile(0, 0, check));
    assert(check.pixelColor(0, 0) == QColor("green"));
    const std::vector<NativeTileStore::StoreBatch> crossStoreSuccess{
        {&first, {{0, 0, firstAfter, true}}},
        {&second, {{0, 0, secondAfter, true}}},
    };
    assert(NativeTileStore::applyBatches(crossStoreSuccess));
    assert(first.copyTile(0, 0, check));
    assert(check.pixelColor(0, 0) == QColor("blue"));
    assert(second.copyTile(0, 0, check));
    assert(check.pixelColor(0, 0) == QColor("yellow"));

    NativeTileStore incompatible(69, 67, 64);
    assert(!incompatible.copyResidentFrom(store));

    NativeTileStore compositeTarget(64, 64, 64);
    NativeTileStore compositeSource(64, 64, 64);
    QImage bottom(64, 64, QImage::Format_ARGB32);
    QImage top(64, 64, QImage::Format_ARGB32);
    bottom.fill(QColor(42, 126, 213, 203));
    top.fill(QColor(223, 71, 119, 177));
    QImage expected = bottom.copy();
    QPainter expectedPainter(&expected);
    expectedPainter.setCompositionMode(QPainter::CompositionMode_Overlay);
    expectedPainter.setOpacity(0.63);
    expectedPainter.drawImage(0, 0, top);
    expectedPainter.end();
    assert(compositeTarget.setTile(0, 0, bottom));
    assert(compositeSource.setTile(0, 0, top));
    assert(compositeTarget.compositeFrom(compositeSource, 0.63f, 7));
    assert(compositeTarget.copyTile(0, 0, check));
    assert(check == expected);
    assert(compositeSource.copyTile(0, 0, check));
    assert(check == top); // Merge must never mutate the source layer.

    // The opaque Normal fast path shares source backing pixels. A subsequent
    // target blend must detach them, never alter the upper/source layer.
    QImage translucentOverlay(64, 64, QImage::Format_ARGB32);
    translucentOverlay.fill(QColor(12, 240, 80, 128));
    NativeTileStore overlayStore(64, 64, 64);
    assert(overlayStore.setTile(0, 0, translucentOverlay));
    assert(compositeTarget.compositeFrom(overlayStore, 1.0f, 0));
    assert(compositeSource.copyTile(0, 0, check));
    assert(check == top);


    NativeTileStore opacityProbe(128, 64, 64);
    QImage opaqueTile(64, 64, QImage::Format_ARGB32);
    QImage translucentTile(64, 64, QImage::Format_ARGB32);
    opaqueTile.fill(QColor("black"));
    translucentTile.fill(QColor(20, 30, 40, 254));
    assert(opacityProbe.setTile(0, 0, opaqueTile));
    assert(opacityProbe.setTile(1, 0, translucentTile));
    int opaquePairs[4]{};
    assert(opacityProbe.copyOpaqueKeys(nullptr, 0) == 1);
    assert(opacityProbe.copyOpaqueKeys(opaquePairs, 2) == 1);
    assert(opaquePairs[0] == 0 && opaquePairs[1] == 0);
    std::cout << "NativeTileStore sparse/write/materialize/dirty-rect/clone checks passed\n";
    return 0;
}
