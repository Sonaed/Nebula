#include "layer_stack.h"

#include <algorithm>
#include <numeric>
#include <cstddef>
#include <cmath>
#include <unordered_set>

bool moveLayerStack(const std::vector<int>& groupIds, int activeIndex,
                    int direction, std::vector<int>& order,
                    int& activeIndexAfter)
{
    const int count = static_cast<int>(groupIds.size());
    if (count < 2 || activeIndex < 0 || activeIndex >= count ||
        (direction != -1 && direction != 1)) return false;

    order.resize(groupIds.size());
    std::iota(order.begin(), order.end(), 0);
    const int group = groupIds[activeIndex];
    const int adjacent = activeIndex + direction;
    if (group < 0) {
        if (adjacent < 0 || adjacent >= count || groupIds[adjacent] >= 0)
            return false;
        std::swap(order[activeIndex], order[adjacent]);
    } else {
        int first = count;
        int last = -1;
        for (int index = 0; index < count; ++index) {
            if (groupIds[index] != group) continue;
            first = std::min(first, index);
            last = index;
        }
        if (last < first) return false;
        for (int index = first; index <= last; ++index)
            if (groupIds[index] != group) return false;

        if (direction > 0) {
            if (activeIndex < last) {
                std::swap(order[activeIndex], order[activeIndex + 1]);
            } else if (first > 0) {
                std::rotate(order.begin() + first - 1,
                            order.begin() + first,
                            order.begin() + last + 1);
            } else {
                return false;
            }
        } else {
            if (activeIndex > first) {
                std::swap(order[activeIndex], order[activeIndex - 1]);
            } else if (last + 1 < count) {
                std::rotate(order.begin() + first,
                            order.begin() + last + 1,
                            order.begin() + last + 2);
            } else {
                return false;
            }
        }
    }

    const auto selected = std::find(order.begin(), order.end(), activeIndex);
    activeIndexAfter = static_cast<int>(std::distance(order.begin(), selected));
    return true;
}

bool removeLayerStack(int layerCount, int removeIndex, int activeIndex,
                      std::vector<int>& order, int& activeIndexAfter)
{
    if (layerCount <= 1 || removeIndex < 0 || removeIndex >= layerCount ||
        activeIndex < 0 || activeIndex >= layerCount) return false;

    order.clear();
    order.reserve(static_cast<size_t>(layerCount - 1));
    for (int index = 0; index < layerCount; ++index)
        if (index != removeIndex) order.push_back(index);

    if (activeIndex > removeIndex) activeIndexAfter = activeIndex - 1;
    else if (activeIndex < removeIndex) activeIndexAfter = activeIndex;
    else activeIndexAfter = std::min(removeIndex, layerCount - 2);
    return true;
}

bool planVisibleLayerMerge(const std::vector<int>& effectiveVisibility,
                           int activeIndex, std::vector<int>& keepMask,
                           int& targetIndex, int& activeIndexAfter)
{
    const int count = static_cast<int>(effectiveVisibility.size());
    if (count < 2 || activeIndex < 0 || activeIndex >= count) return false;

    targetIndex = -1;
    int visibleCount = 0;
    for (int index = 0; index < count; ++index) {
        if (effectiveVisibility[index] == 0) continue;
        if (effectiveVisibility[index] != 1) return false;
        if (targetIndex < 0) targetIndex = index;
        ++visibleCount;
    }
    if (visibleCount < 2) return false;

    keepMask.assign(static_cast<size_t>(count), 1);
    int removedBeforeActive = 0;
    for (int index = 0; index < count; ++index) {
        if (effectiveVisibility[index] != 1 || index == targetIndex) continue;
        keepMask[static_cast<size_t>(index)] = 0;
        if (index < activeIndex) ++removedBeforeActive;
    }
    activeIndexAfter = effectiveVisibility[static_cast<size_t>(activeIndex)] == 1
        ? targetIndex : activeIndex - removedBeforeActive;
    return true;
}

bool planVisibleLayerMergeWithGroups(const std::vector<int>& layerVisibility,
                                     const std::vector<int>& groupMembership,
                                     const std::vector<int>& groupVisibility,
                                     int activeIndex,
                                     std::vector<int>& effectiveVisibility,
                                     std::vector<int>& keepMask,
                                     int& targetIndex, int& activeIndexAfter)
{
    if (layerVisibility.empty() || layerVisibility.size() != groupMembership.size())
        return false;
    std::vector<int> effective;
    effective.reserve(layerVisibility.size());
    for (size_t index = 0; index < layerVisibility.size(); ++index) {
        const int visible = layerVisibility[index];
        const int group = groupMembership[index];
        if ((visible != 0 && visible != 1) || group < -1 ||
            (group >= 0 && (group >= static_cast<int>(groupVisibility.size()) ||
             (groupVisibility[static_cast<size_t>(group)] != 0 &&
              groupVisibility[static_cast<size_t>(group)] != 1))))
            return false;
        effective.push_back(visible && (group < 0 ||
            groupVisibility[static_cast<size_t>(group)]) ? 1 : 0);
    }
    std::vector<int> keep;
    int target = -1;
    int activeAfter = -1;
    if (!planVisibleLayerMerge(effective, activeIndex, keep, target, activeAfter))
        return false;
    effectiveVisibility.swap(effective);
    keepMask.swap(keep);
    targetIndex = target;
    activeIndexAfter = activeAfter;
    return true;
}

bool updateLayerProperty(int property, double currentValue, double requestedValue,
                         double& outputValue)
{
    if (!std::isfinite(currentValue) || !std::isfinite(requestedValue)) return false;
    switch (property) {
    case 0: case 2: case 3: case 4:
        outputValue = currentValue == 0.0 ? 1.0 : 0.0;
        return true;
    case 1:
        outputValue = std::clamp(requestedValue, 0.0, 1.0);
        return true;
    default:
        return false;
    }
}

bool normalizeLayerGroup(int layerCount, const std::vector<int>& requestedIndices,
                         const std::vector<int>& groupedLayers,
                         std::vector<int>& normalizedIndices)
{
    if (layerCount <= 0 || static_cast<int>(groupedLayers.size()) != layerCount)
        return false;
    normalizedIndices = requestedIndices;
    std::sort(normalizedIndices.begin(), normalizedIndices.end());
    normalizedIndices.erase(std::unique(normalizedIndices.begin(), normalizedIndices.end()),
                            normalizedIndices.end());
    if (normalizedIndices.size() < 2 || normalizedIndices.front() < 0 ||
        normalizedIndices.back() >= layerCount) return false;
    for (size_t i = 0; i < normalizedIndices.size(); ++i) {
        const int index = normalizedIndices[i];
        if (groupedLayers[index] != 0 ||
            (i > 0 && index != normalizedIndices[i - 1] + 1)) return false;
    }
    return true;
}

bool planLayerCompositeRuns(const std::vector<int>& groupIds,
                            std::vector<int>& starts,
                            std::vector<int>& ends,
                            std::vector<int>& runGroupIds)
{
    if (groupIds.empty()) return false;
    std::vector<int> plannedStarts;
    std::vector<int> plannedEnds;
    std::vector<int> plannedGroups;
    std::unordered_set<int> seenGroups;
    for (int index = 0; index < static_cast<int>(groupIds.size());) {
        const int group = groupIds[static_cast<size_t>(index)];
        if (group < -1) return false;
        const int start = index++;
        if (group >= 0) {
            if (!seenGroups.insert(group).second) return false;
            while (index < static_cast<int>(groupIds.size()) &&
                   groupIds[static_cast<size_t>(index)] == group)
                ++index;
        }
        plannedStarts.push_back(start);
        plannedEnds.push_back(index);
        plannedGroups.push_back(group);
    }
    starts.swap(plannedStarts);
    ends.swap(plannedEnds);
    runGroupIds.swap(plannedGroups);
    return true;
}

bool planLayerGroupCleanup(const std::vector<int>& layerGroupIds,
                           const std::vector<int>& keepLayer,
                           int groupCount, std::vector<int>& keepGroup,
                           std::vector<int>& survivingMembership)
{
    if (groupCount < 0 || layerGroupIds.size() != keepLayer.size()) return false;
    keepGroup.assign(static_cast<size_t>(groupCount), 0);
    survivingMembership.clear();
    survivingMembership.reserve(layerGroupIds.size());
    for (size_t index = 0; index < layerGroupIds.size(); ++index) {
        const int group = layerGroupIds[index];
        if ((keepLayer[index] != 0 && keepLayer[index] != 1) ||
            group < -1 || group >= groupCount) return false;
        if (!keepLayer[index]) continue;
        survivingMembership.push_back(group);
        if (group >= 0) keepGroup[static_cast<size_t>(group)] = 1;
    }
    return true;
}
