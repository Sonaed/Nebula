#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Authoritative, UI-independent document/layer metadata model. Pixel storage
// remains in TileStore; this object owns the structural state consumed by the
// Qt adapter.
struct NativeLayerState {
    std::uint64_t id = 0;
    std::string name;
    bool visible = true;
    float opacity = 1.0f;
    int blendMode = 0;
    bool locked = false;
    bool lockAlpha = false;
    bool clipping = false;
};

struct NativeGroupState {
    std::uint64_t id = 0;
    std::string name;
    std::vector<int> layerIndices;
    bool visible = true;
    float opacity = 1.0f;
};

class DocumentState {
public:
    DocumentState(int width, int height, int dpi);

    int width() const { return width_; }
    int height() const { return height_; }
    int dpi() const { return dpi_; }
    int layerCount() const { return static_cast<int>(layers_.size()); }
    int activeLayer() const { return activeLayer_; }

    bool addLayer(const std::string& name, int& index);
    void resetLayers();
    bool createGroup(const std::vector<int>& indices, const std::string& name,
                     int& groupIndex);
    bool removeGroup(int groupIndex);
    bool setGroupProperty(int groupIndex, int property, double requested,
                          double& output);
    void resetGroups();
    int groupCount() const { return static_cast<int>(groups_.size()); }
    int groupForLayer(int layerIndex) const;
    bool removeLayer(int index);
    bool reorderLayers(const std::vector<int>& order, int activeIndex);
    bool selectLayer(int index);
    bool renameLayer(int index, const std::string& name);
    bool setLayerProperty(int index, int property, double requested,
                          double& output);
    bool layerInfo(int index, NativeLayerState& output) const;

private:
    int width_;
    int height_;
    int dpi_;
    int activeLayer_ = -1;
    std::uint64_t nextLayerId_ = 1;
    std::uint64_t nextGroupId_ = 1;
    std::vector<NativeLayerState> layers_;
    std::vector<NativeGroupState> groups_;
};
