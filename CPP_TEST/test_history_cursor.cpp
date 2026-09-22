#include "history_cursor.h"
#include "history_payload.h"

#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include <iostream>
#include <QColor>

int main()
{
    HistoryCursor cursor(3);
    int branch = 0, dropped = 0;
    assert(!cursor.transactionOpen());
    assert(cursor.beginTransaction(true, true, true));
    assert(!cursor.beginTransaction(false, false, false));
    assert(cursor.transactionOpen());
    assert(cursor.transactionMode() == HistoryCursor::TransactionMode::Selection);
    assert(cursor.append(branch, dropped) == 0);
    assert(cursor.stepCount() == 0 && cursor.index() == 0);
    assert(!cursor.undo() && !cursor.redo());
    cursor.synchronize(3, 2);
    assert(cursor.stepCount() == 0 && cursor.index() == 0);
    assert(cursor.cancelTransaction());
    assert(!cursor.transactionOpen());
    assert(cursor.transactionMode() == HistoryCursor::TransactionMode::General);
    assert(!cursor.commitTransaction());
    assert(cursor.beginTransaction(true, false, true));
    assert(cursor.transactionMode() == HistoryCursor::TransactionMode::Structure);
    assert(cursor.commitTransaction());
    assert(!cursor.transactionOpen());
    for (int i = 0; i < 3; ++i) cursor.append(branch, dropped);
    assert(cursor.stepCount() == 3 && cursor.index() == 3);
    assert(cursor.undo() && cursor.index() == 2);
    assert(cursor.undo() && cursor.index() == 1);
    assert(cursor.append(branch, dropped) == 2);
    assert(branch == 2 && dropped == 0);
    assert(cursor.stepCount() == 2 && cursor.index() == 2);
    assert(!cursor.redo());
    assert(cursor.undo() && cursor.redo());

    const std::uint8_t stateBefore[]{1, 2, 3};
    const std::uint8_t stateAfter[]{4, 5};
    cursor.reset();
    assert(cursor.appendState(stateBefore, 3, stateAfter, 2, branch, dropped) == 1);
    assert(cursor.stateSize(0, 0) == 3 && cursor.stateSize(0, 1) == 2);
    std::uint8_t copiedState[3]{};
    assert(cursor.copyState(0, 0, copiedState, 3));
    assert(std::memcmp(copiedState, stateBefore, 3) == 0);
    assert(cursor.appendState(stateAfter, 2, stateBefore, 3, branch, dropped) == 2);
    assert(cursor.undo());
    assert(cursor.stateSize(cursor.index(), 0) == 2);
    std::vector<std::uint8_t> oversized(16u * 1024u * 1024u + 1u, 0);
    assert(cursor.appendState(oversized.data(), static_cast<std::uint32_t>(oversized.size()),
                              stateAfter, 2, branch, dropped) == 0);

    cursor.append(branch, dropped);
    cursor.append(branch, dropped);
    assert(cursor.stepCount() == 3 && cursor.index() == 3);
    assert(cursor.setMaximumSteps(2) == 1);
    assert(cursor.stepCount() == 2 && cursor.index() == 2);
    assert(cursor.discardOldest(1) == 1);
    assert(cursor.stepCount() == 1 && cursor.index() == 1);
    cursor.synchronize(5, 5);
    assert(cursor.stepCount() == 2 && cursor.index() == 2);
    cursor.reset();
    assert(cursor.stepCount() == 0 && cursor.index() == 0);

    HistoryPayload payload;
    QImage before(64, 32, QImage::Format_ARGB32);
    before.fill(QColor("crimson"));
    QImage after(64, 32, QImage::Format_ARGB32);
    after.fill(QColor("royalblue"));
    assert(payload.append(&before, &after));
    assert(payload.append(&after, &after) == 2);
    assert(payload.append(nullptr, &after));
    assert(payload.count() == 2);
    assert(payload.allocatedBytes() == 64LL * 32LL * 4LL * 3LL);
    before.fill(Qt::black);
    bool present = false;
    int width = 0, height = 0, format = 0;
    assert(payload.tileInfo(0, 0, present, width, height, format));
    assert(present && width == 64 && height == 32);
    QImage restored(width, height, static_cast<QImage::Format>(format));
    assert(payload.copyTile(0, 0, restored));
    assert(restored.pixelColor(4, 4) == QColor("crimson"));
    assert(payload.tileInfo(1, 0, present, width, height, format) && !present);
    assert(!payload.copyTile(1, 0, restored));
    payload.clear();
    assert(payload.count() == 0 && payload.allocatedBytes() == 0);

    std::cout << "History cursor and native tile payload checks passed\n";
    return 0;
}
