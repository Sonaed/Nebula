#pragma once

#include <vector>

// Stateless ordering primitive for the document layer stack. Group IDs are
// compact integers; -1 denotes an ungrouped layer.
bool moveLayerStack(const std::vector<int>& groupIds, int activeIndex,
                    int direction, std::vector<int>& order,
                    int& activeIndexAfter);

// Compute the output-to-input permutation after removing one layer.
bool removeLayerStack(int layerCount, int removeIndex, int activeIndex,
                      std::vector<int>& order, int& activeIndexAfter);

// Plan a destructive merge of all effectively visible layers into the lowest
// visible layer. The mask marks which original entries survive.
bool planVisibleLayerMerge(const std::vector<int>& effectiveVisibility,
                           int activeIndex, std::vector<int>& keepMask,
                           int& targetIndex, int& activeIndexAfter);
bool planVisibleLayerMergeWithGroups(const std::vector<int>& layerVisibility,
                                     const std::vector<int>& groupMembership,
                                     const std::vector<int>& groupVisibility,
                                     int activeIndex,
                                     std::vector<int>& effectiveVisibility,
                                     std::vector<int>& keepMask,
                                     int& targetIndex, int& activeIndexAfter);

// Layer metadata property IDs: 0 visibility toggle, 1 opacity set,
// 2 pixel-lock toggle, 3 alpha-lock toggle, 4 clipping toggle.
bool updateLayerProperty(int property, double currentValue, double requestedValue,
                         double& outputValue);

// Normalize and validate a contiguous, currently ungrouped selection.
bool normalizeLayerGroup(int layerCount, const std::vector<int>& requestedIndices,
                         const std::vector<int>& groupedLayers,
                         std::vector<int>& normalizedIndices);

// Plan document composition runs. Ungrouped layers form one-item runs;
// grouped layers must form one contiguous run per group ID. Group IDs below
// zero other than -1 are invalid. Outputs use half-open [start, end) indices.
bool planLayerCompositeRuns(const std::vector<int>& groupIds,
                            std::vector<int>& starts,
                            std::vector<int>& ends,
                            std::vector<int>& runGroupIds);

// Reconcile group membership after a structural layer removal/merge. The
// output membership is indexed by surviving layers; empty groups are marked 0.
bool planLayerGroupCleanup(const std::vector<int>& layerGroupIds,
                           const std::vector<int>& keepLayer,
                           int groupCount, std::vector<int>& keepGroup,
                           std::vector<int>& survivingMembership);
