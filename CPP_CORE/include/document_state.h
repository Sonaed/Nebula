#pragma once

#include <cstddef>
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
    // 0 = raster (pixels dans le TileStore), 1 = filtre non destructif : aucun
    // pixel, `filterPayload` porte un FilterDescriptor encodé (filter_layer.h).
    int kind = 0;
    std::vector<std::uint8_t> filterPayload;
};

constexpr int kLayerKindRaster = 0;
constexpr int kLayerKindFilter = 1;

struct NativeGroupState {
    std::uint64_t id = 0;
    std::string name;
    std::vector<int> layerIndices;
    int parentGroup = -1;
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
    // Ajoute au sommet un calque de filtre ; refuse toute charge qui n'est pas un
    // descripteur valide (taille, CRC, plages).
    bool addFilterLayer(const std::string& name, const std::uint8_t* payload,
                        std::size_t size, int& index);
    // Remplace le descripteur d'un calque de filtre existant (refus sur raster).
    bool setFilterPayload(int index, const std::uint8_t* payload, std::size_t size);
    void resetLayers();
    bool createGroup(const std::vector<int>& indices, const std::string& name,
                     int& groupIndex);
    bool createEnclosingGroup(const std::vector<int>& requested, const std::string& name,
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
