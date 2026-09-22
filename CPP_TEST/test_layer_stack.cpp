#include "layer_stack.h"
#include "document_rules.h"
#include "document_state.h"

#include <cassert>
#include <vector>
#include <cmath>

int main()
{
    std::vector<int> order;
    int active = -1;

    assert(moveLayerStack({-1, 3, 3, -1}, 0, 1, order, active) == false);
    assert(moveLayerStack({-1, 3, 3, -1}, 3, -1, order, active) == false);

    assert(moveLayerStack({-1, 3, 3, -1}, 1, 1, order, active));
    assert((order == std::vector<int>{0, 2, 1, 3}));
    assert(active == 2);

    assert(moveLayerStack({-1, 3, 3, -1}, 2, 1, order, active));
    assert((order == std::vector<int>{1, 2, 0, 3}));
    assert(active == 1);

    assert(moveLayerStack({-1, 3, 3, -1}, 1, -1, order, active));
    assert((order == std::vector<int>{0, 2, 1, 3}));
    assert(active == 0);

    assert(!moveLayerStack({4, -1, 4}, 0, 1, order, active));
    assert(!moveLayerStack({1, 2, 1}, 0, 1, order, active));
    assert(!moveLayerStack({-1}, 0, 0, order, active));

    assert(removeLayerStack(4, 1, 3, order, active));
    assert((order == std::vector<int>{0, 2, 3}));
    assert(active == 2);
    assert(removeLayerStack(4, 3, 3, order, active));
    assert((order == std::vector<int>{0, 1, 2}));
    assert(active == 2);
    assert(removeLayerStack(4, 1, 0, order, active));
    assert(active == 0);
    assert(!removeLayerStack(1, 0, 0, order, active));
    assert(!removeLayerStack(3, 3, 0, order, active));

    std::vector<int> keep;
    int target = -1;
    assert(planVisibleLayerMerge({1, 0, 1, 1}, 3, keep, target, active));
    assert(target == 0);
    assert((keep == std::vector<int>{1, 1, 0, 0}));
    assert(active == 0);
    assert(planVisibleLayerMerge({0, 1, 0, 1}, 2, keep, target, active));
    assert(target == 1);
    assert((keep == std::vector<int>{1, 1, 1, 0}));
    assert(active == 2);
    assert(!planVisibleLayerMerge({0, 1, 0}, 1, keep, target, active));
    assert(!planVisibleLayerMerge({1, 0}, -1, keep, target, active));
    std::vector<int> effective;
    assert(planVisibleLayerMergeWithGroups({1, 1, 0, 1}, {-1, 0, 0, 1},
                                           {0, 1}, 3, effective, keep,
                                           target, active));
    assert((effective == std::vector<int>{1, 0, 0, 1}));
    assert((keep == std::vector<int>{1, 1, 1, 0}));
    assert(target == 0 && active == 0);
    assert(!planVisibleLayerMergeWithGroups({1}, {1}, {}, 0, effective, keep,
                                            target, active));

    double property = -1.0;
    assert(updateLayerProperty(0, 0.0, 0.0, property) && property == 1.0);
    assert(updateLayerProperty(2, 1.0, 0.0, property) && property == 0.0);
    assert(updateLayerProperty(3, 0.0, 0.0, property) && property == 1.0);
    assert(updateLayerProperty(4, 1.0, 0.0, property) && property == 0.0);
    assert(updateLayerProperty(1, 0.4, 1.5, property) && property == 1.0);
    assert(updateLayerProperty(1, 0.4, -0.5, property) && property == 0.0);
    assert(!updateLayerProperty(1, 0.4, NAN, property));
    assert(!updateLayerProperty(9, 0.0, 0.0, property));

    std::vector<int> normalized;
    assert(normalizeLayerGroup(4, {2, 1, 2}, {0, 0, 0, 0}, normalized));
    assert((normalized == std::vector<int>{1, 2}));
    assert(!normalizeLayerGroup(3, {0, 2}, {0, 0, 0}, normalized));
    assert(!normalizeLayerGroup(3, {0, 1}, {1, 0, 0}, normalized));
    assert(!normalizeLayerGroup(2, {0, 8}, {0, 0}, normalized));
    assert(!normalizeLayerGroup(2, {0, 1}, {0}, normalized));
    std::vector<int> starts, ends, runGroups;
    assert(planLayerCompositeRuns({-1, 0, 0, -1, 2}, starts, ends, runGroups));
    assert((starts == std::vector<int>{0, 1, 3, 4}));
    assert((ends == std::vector<int>{1, 3, 4, 5}));
    assert((runGroups == std::vector<int>{-1, 0, -1, 2}));
    assert(!planLayerCompositeRuns({0, -1, 0}, starts, ends, runGroups));
    assert(!planLayerCompositeRuns({-2, -1}, starts, ends, runGroups));
    assert(!planLayerCompositeRuns({}, starts, ends, runGroups));
    std::vector<int> keptGroups, surviving;
    assert(planLayerGroupCleanup({-1, 0, 0, 1}, {1, 0, 1, 0}, 2,
                                 keptGroups, surviving));
    assert((keptGroups == std::vector<int>{1, 0}));
    assert((surviving == std::vector<int>{-1, 0}));
    assert(!planLayerGroupCleanup({0, 2}, {1, 1}, 2, keptGroups, surviving));
    assert(validateDocumentGeometry(800, 600, 300));
    assert(validateDocumentGeometry(8000, 8000, 300, 100000, 64000000));
    assert(!validateDocumentGeometry(8001, 8000, 300, 100000, 64000000));
    assert(!validateDocumentGeometry(10, 10, 0));

    DocumentState document(320, 240, 300);
    int layer = -1;
    assert(document.addLayer("Background", layer) && layer == 0);
    assert(document.addLayer("Ink", layer) && layer == 1);
    assert(document.layerCount() == 2 && document.activeLayer() == 1);
    assert(document.selectLayer(0) && document.activeLayer() == 0);
    assert(document.renameLayer(1, "Line art"));
    double opacity = -1.0;
    assert(document.setLayerProperty(1, 1, 0.35, opacity));
    assert(std::abs(opacity - 0.35) < 0.0001);
    assert(document.setLayerProperty(1, 0, 0.0, opacity) && opacity == 0.0);
    assert(document.removeLayer(0) && document.layerCount() == 1);
    assert(document.activeLayer() == 0);
    assert(!document.removeLayer(0));

    DocumentState grouped(320, 240, 300);
    assert(grouped.addLayer("A", layer) && layer == 0);
    assert(grouped.addLayer("B", layer) && layer == 1);
    assert(grouped.addLayer("C", layer) && layer == 2);
    int groupIndex = -1;
    assert(grouped.createGroup({1, 2}, "Paint", groupIndex));
    assert(groupIndex == 0 && grouped.groupCount() == 1);
    assert(grouped.groupForLayer(0) == -1);
    assert(grouped.groupForLayer(1) == 0);
    double groupValue = -1.0;
    assert(grouped.setGroupProperty(0, 0, 0.0, groupValue) && groupValue == 0.0);
    assert(grouped.setGroupProperty(0, 1, 0.35, groupValue));
    assert(std::abs(groupValue - 0.35) < 0.0001);
    assert(!grouped.setGroupProperty(0, 9, 0.0, groupValue));
    // A complete root group can be wrapped without making any leaf a
    // sibling of itself.  This is the native hierarchy used by the UI model.
    assert(grouped.createGroup({1, 2}, "Folder", groupIndex));
    assert(groupIndex == 1 && grouped.groupCount() == 2);
    assert(grouped.groupForLayer(1) == 0);
    assert(!grouped.createGroup({0, 2}, "Invalid", groupIndex));
    assert(grouped.removeGroup(0) && grouped.groupCount() == 1);
    return 0;
}
