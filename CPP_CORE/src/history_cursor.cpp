#include "history_cursor.h"

#include <algorithm>
#include <cstring>

namespace {
constexpr std::uint32_t kMaxHistoryStateBytes = 16u * 1024u * 1024u;
}

HistoryCursor::HistoryCursor(int maximumSteps)
    : maximumSteps_(std::max(1, maximumSteps)) {}

void HistoryCursor::reset()
{
    stepCount_ = 0;
    index_ = 0;
    transactionOpen_ = false;
    beforeStates_.clear();
    afterStates_.clear();
}

bool HistoryCursor::beginTransaction(bool dirtyOnly, bool selectionOnly,
                                     bool structureOnly)
{
    if (transactionOpen_) return false;
    // Match the established capture precedence: selection, structure, dirty, general.
    transactionMode_ = selectionOnly ? TransactionMode::Selection
        : structureOnly ? TransactionMode::Structure
        : dirtyOnly ? TransactionMode::Dirty
        : TransactionMode::General;
    transactionOpen_ = true;
    return true;
}

bool HistoryCursor::commitTransaction()
{
    if (!transactionOpen_) return false;
    transactionOpen_ = false;
    transactionMode_ = TransactionMode::General;
    return true;
}

bool HistoryCursor::cancelTransaction()
{
    if (!transactionOpen_) return false;
    transactionOpen_ = false;
    transactionMode_ = TransactionMode::General;
    return true;
}

int HistoryCursor::append(int& truncatedForward, int& discardedOldest)
{
    truncatedForward = 0;
    discardedOldest = 0;
    if (transactionOpen_) return 0;
    truncatedForward = std::max(0, stepCount_ - index_);
    stepCount_ = index_;
    ++stepCount_;
    index_ = stepCount_;
    discardedOldest = discardOldest(std::max(0, stepCount_ - maximumSteps_));
    beforeStates_.resize(static_cast<std::size_t>(stepCount_));
    afterStates_.resize(static_cast<std::size_t>(stepCount_));
    return index_;
}

int HistoryCursor::appendState(const std::uint8_t* before, std::uint32_t beforeSize,
                               const std::uint8_t* after, std::uint32_t afterSize,
                               int& truncatedForward, int& discardedOldest)
{
    if ((!before && beforeSize) || (!after && afterSize) || transactionOpen_
        || beforeSize > kMaxHistoryStateBytes || afterSize > kMaxHistoryStateBytes) return 0;
    truncatedForward = std::max(0, stepCount_ - index_);
    if (truncatedForward > 0) {
        beforeStates_.resize(static_cast<std::size_t>(index_));
        afterStates_.resize(static_cast<std::size_t>(index_));
    }
    stepCount_ = index_;
    ++stepCount_;
    index_ = stepCount_;
    beforeStates_.emplace_back();
    afterStates_.emplace_back();
    if (beforeSize) beforeStates_.back().assign(before, before + beforeSize);
    if (afterSize) afterStates_.back().assign(after, after + afterSize);
    discardedOldest = discardOldest(std::max(0, stepCount_ - maximumSteps_));
    return index_;
}

std::uint32_t HistoryCursor::stateSize(int index, int side) const
{
    if (index < 0 || index >= stepCount_ || (side != 0 && side != 1)) return 0;
    const auto& states = side == 0 ? beforeStates_ : afterStates_;
    if (static_cast<std::size_t>(index) >= states.size()) return 0;
    return static_cast<std::uint32_t>(states[static_cast<std::size_t>(index)].size());
}

bool HistoryCursor::copyState(int index, int side, std::uint8_t* output,
                              std::uint32_t capacity) const
{
    const std::uint32_t size = stateSize(index, side);
    if (size == 0 || !output || capacity < size) return false;
    const auto& states = side == 0 ? beforeStates_ : afterStates_;
    std::memcpy(output, states[static_cast<std::size_t>(index)].data(), size);
    return true;
}

int HistoryCursor::discardOldest(int requested)
{
    const int removed = std::clamp(requested, 0, stepCount_);
    if (removed > 0) {
        const auto count = static_cast<std::size_t>(removed);
        if (count <= beforeStates_.size()) beforeStates_.erase(beforeStates_.begin(), beforeStates_.begin() + count);
        if (count <= afterStates_.size()) afterStates_.erase(afterStates_.begin(), afterStates_.begin() + count);
    }
    stepCount_ -= removed;
    index_ = std::max(0, index_ - removed);
    return removed;
}

int HistoryCursor::setMaximumSteps(int maximumSteps)
{
    maximumSteps_ = std::max(1, maximumSteps);
    return discardOldest(std::max(0, stepCount_ - maximumSteps_));
}

bool HistoryCursor::undo()
{
    if (transactionOpen_ || index_ <= 0) return false;
    --index_;
    return true;
}

bool HistoryCursor::redo()
{
    if (transactionOpen_ || index_ >= stepCount_) return false;
    ++index_;
    return true;
}

void HistoryCursor::synchronize(int stepCount, int index)
{
    if (transactionOpen_) return;
    stepCount_ = std::max(0, stepCount);
    index_ = std::clamp(index, 0, stepCount_);
    beforeStates_.resize(static_cast<std::size_t>(stepCount_));
    afterStates_.resize(static_cast<std::size_t>(stepCount_));
    if (stepCount_ > maximumSteps_) {
        discardOldest(stepCount_ - maximumSteps_);
    }
}
