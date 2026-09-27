#pragma once

#include <cstdint>
#include <vector>

// Native owner of the bounded undo timeline position and branch policy.
class HistoryCursor final {
public:
    enum class TransactionMode : int { General = 0, Dirty = 1, Selection = 2, Structure = 3 };
    explicit HistoryCursor(int maximumSteps = 30);

    void reset();
    bool beginTransaction(bool dirtyOnly, bool selectionOnly, bool structureOnly);
    bool commitTransaction();
    bool cancelTransaction();
    bool transactionOpen() const { return transactionOpen_; }
    TransactionMode transactionMode() const { return transactionMode_; }
    int append(int& truncatedForward, int& discardedOldest);
    int appendState(const std::uint8_t* before, std::uint32_t beforeSize,
                    const std::uint8_t* after, std::uint32_t afterSize,
                    int& truncatedForward, int& discardedOldest);
    std::uint32_t stateSize(int index, int side) const;
    bool copyState(int index, int side, std::uint8_t* output,
                   std::uint32_t capacity) const;
    int discardOldest(int requested);
    int setMaximumSteps(int maximumSteps);
    bool undo();
    bool redo();
    void synchronize(int stepCount, int index);
    int stepCount() const { return stepCount_; }
    int index() const { return index_; }
    int maximumSteps() const { return maximumSteps_; }

private:
    int maximumSteps_;
    int stepCount_ = 0;
    int index_ = 0;
    bool transactionOpen_ = false;
    TransactionMode transactionMode_ = TransactionMode::General;
    std::vector<std::vector<std::uint8_t>> beforeStates_;
    std::vector<std::vector<std::uint8_t>> afterStates_;
};
