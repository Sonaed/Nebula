#include "document_state.h"

#include "document_rules.h"
#include "layer_stack.h"

#include <algorithm>
#include <cmath>

DocumentState::DocumentState(int width, int height, int dpi)
    : width_(width), height_(height), dpi_(dpi)
{
}

bool DocumentState::addLayer(const std::string& name, int& index)
{
    if (name.empty() || !validateDocumentGeometry(width_, height_, dpi_))
        return false;
    NativeLayerState layer;
    layer.id = nextLayerId_++;
    layer.name = name;
    layers_.push_back(std::move(layer));
    index = static_cast<int>(layers_.size()) - 1;
    activeLayer_ = index;
    return true;
}

void DocumentState::resetLayers()
{
    layers_.clear();
    activeLayer_ = -1;
    groups_.clear();
}

bool DocumentState::createGroup(const std::vector<int>& indices,
                                const std::string& name, int& groupIndex)
{
    if (name.empty()) return false;
    std::vector<int> grouped(static_cast<std::size_t>(layerCount()), 0);
    for (const auto& group : groups_)
        for (int index : group.layerIndices)
            if (index >= 0 && index < layerCount()) grouped[static_cast<std::size_t>(index)] = 1;
    std::vector<int> normalized;
    if (indices.size() == 1) {
        const int index = indices.front();
        if (index < 0 || index >= layerCount() || grouped[static_cast<std::size_t>(index)])
            return false;
        normalized = indices;
    } else if (!normalizeLayerGroup(layerCount(), indices, grouped, normalized)) {
        // Wrapping one complete root group is the only overlap allowed.  It
        // makes a new parent without giving any leaf layer two siblings.
        std::vector<int> requested = indices;
        std::sort(requested.begin(), requested.end());
        requested.erase(std::unique(requested.begin(), requested.end()), requested.end());
        auto child = std::find_if(groups_.begin(), groups_.end(),
            [&requested](const NativeGroupState& group) {
                auto members = group.layerIndices;
                std::sort(members.begin(), members.end());
                return group.parentGroup < 0 && members == requested;
            });
        if (child == groups_.end()) return false;
        normalized = std::move(requested);
        const int childIndex = static_cast<int>(std::distance(groups_.begin(), child));
        NativeGroupState group;
        group.id = nextGroupId_++;
        group.name = name;
        group.layerIndices = normalized;
        groups_.push_back(std::move(group));
        groupIndex = static_cast<int>(groups_.size()) - 1;
        groups_[static_cast<std::size_t>(childIndex)].parentGroup = groupIndex;
        return true;
    }
    if (normalized.empty()) {
        return false;
    }
    NativeGroupState group;
    group.id = nextGroupId_++;
    group.name = name;
    group.layerIndices = std::move(normalized);
    groups_.push_back(std::move(group));
    groupIndex = static_cast<int>(groups_.size()) - 1;
    return true;
}

bool DocumentState::removeGroup(int groupIndex)
{
    if (groupIndex < 0 || groupIndex >= groupCount()) return false;
    groups_.erase(groups_.begin() + groupIndex);
    return true;
}

bool DocumentState::setGroupProperty(int groupIndex, int property, double requested,
                                     double& output)
{
    if (groupIndex < 0 || groupIndex >= groupCount()) return false;
    auto& group = groups_[static_cast<std::size_t>(groupIndex)];
    const double current = property == 0 ? (group.visible ? 1.0 : 0.0)
                                         : (property == 1 ? group.opacity : -1.0);
    if (property != 0 && property != 1) return false;
    if (!updateLayerProperty(property, current, requested, output)) return false;
    if (property == 0) group.visible = output != 0.0;
    else group.opacity = static_cast<float>(output);
    return true;
}

void DocumentState::resetGroups()
{
    groups_.clear();
}

int DocumentState::groupForLayer(int layerIndex) const
{
    if (layerIndex < 0 || layerIndex >= layerCount()) return -1;
    for (int group = 0; group < groupCount(); ++group) {
        const auto& indices = groups_[static_cast<std::size_t>(group)].layerIndices;
        // Groups are stored children-first, so the first matching group is
        // the direct (deepest) owner exposed to UI commands.
        if (std::find(indices.begin(), indices.end(), layerIndex) != indices.end())
            return group;
    }
    return -1;
}

bool DocumentState::removeLayer(int index)
{
    if (layers_.size() <= 1 || index < 0 || index >= layerCount())
        return false;
    layers_.erase(layers_.begin() + index);
    if (activeLayer_ > index) --activeLayer_;
    else if (activeLayer_ == index)
        activeLayer_ = std::min(index, layerCount() - 1);
    return true;
}

bool DocumentState::reorderLayers(const std::vector<int>& order, int activeIndex)
{
    if (static_cast<int>(order.size()) != layerCount() ||
        activeIndex < 0 || activeIndex >= layerCount()) return false;
    std::vector<bool> seen(order.size(), false);
    std::vector<NativeLayerState> reordered;
    reordered.reserve(order.size());
    for (int source : order) {
        if (source < 0 || source >= layerCount() || seen[source]) return false;
        seen[source] = true;
        reordered.push_back(layers_[static_cast<std::size_t>(source)]);
    }
    layers_.swap(reordered);
    activeLayer_ = activeIndex;
    return true;
}

bool DocumentState::selectLayer(int index)
{
    if (index < 0 || index >= layerCount()) return false;
    activeLayer_ = index;
    return true;
}

bool DocumentState::renameLayer(int index, const std::string& name)
{
    if (index < 0 || index >= layerCount() || name.empty()) return false;
    layers_[static_cast<std::size_t>(index)].name = name;
    return true;
}

bool DocumentState::setLayerProperty(int index, int property, double requested,
                                     double& output)
{
    if (index < 0 || index >= layerCount()) return false;
    auto& layer = layers_[static_cast<std::size_t>(index)];
    double current = 0.0;
    switch (property) {
    case 0: current = layer.visible ? 1.0 : 0.0; break;
    case 1: current = layer.opacity; break;
    case 2: current = layer.locked ? 1.0 : 0.0; break;
    case 3: current = layer.lockAlpha ? 1.0 : 0.0; break;
    case 4: current = layer.clipping ? 1.0 : 0.0; break;
    default: return false;
    }
    if (!updateLayerProperty(property, current, requested, output)) return false;
    switch (property) {
    case 0: layer.visible = output != 0.0; break;
    case 1: layer.opacity = static_cast<float>(output); break;
    case 2: layer.locked = output != 0.0; break;
    case 3: layer.lockAlpha = output != 0.0; break;
    case 4: layer.clipping = output != 0.0; break;
    default: return false;
    }
    return true;
}

bool DocumentState::layerInfo(int index, NativeLayerState& output) const
{
    if (index < 0 || index >= layerCount()) return false;
    output = layers_[static_cast<std::size_t>(index)];
    return true;
}
