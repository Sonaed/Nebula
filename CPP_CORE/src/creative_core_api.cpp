#include "creative_core_api.h"
#include "document_state.h"

#include "brush_engine.h"
#include "projection_engine.h"
#include "simd_runtime.h"
#include "projection_kernel_dispatch.h"
#include "tile_store.h"
#include "layer_stack.h"
#include "document_rules.h"
#include "history_cursor.h"
#include "history_payload.h"
#include "projection_compositor.h"

#include <QColor>
#include <QBuffer>
#include <QByteArray>
#include <QImage>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QJsonValue>
#include <QSet>
#include <QLinearGradient>
#include <QPainter>
#include <QPainterPath>
#include <QFont>
#include <QFontMetricsF>
#include <QSaveFile>
#include <QString>
#include <QPointF>
#include <QTransform>
#include <QRectF>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <limits>
#include <vector>
#ifdef CREATIVECORE_HAVE_LZ4
#include <lz4.h>
#endif

namespace
{
constexpr int kCslzHeaderSize = 25;
constexpr int kCslzMaxRawBytes = 16 * 1024 * 1024;

uint32_t readLe32(const uint8_t* bytes)
{
    return uint32_t(bytes[0]) | (uint32_t(bytes[1]) << 8) |
           (uint32_t(bytes[2]) << 16) | (uint32_t(bytes[3]) << 24);
}

void writeLe32(uint8_t* bytes, uint32_t value)
{
    bytes[0] = uint8_t(value);
    bytes[1] = uint8_t(value >> 8);
    bytes[2] = uint8_t(value >> 16);
    bytes[3] = uint8_t(value >> 24);
}

bool parseCslz(const uint8_t* encoded, int encodedSize, int& width, int& height,
               int& stride, int& rawSize, int& packedSize, bool& compressed)
{
    if (!encoded || encodedSize < kCslzHeaderSize || encodedSize > 20 * 1024 * 1024 ||
        std::memcmp(encoded, "CSLZ", 4) != 0) return false;
    const uint32_t w = readLe32(encoded + 4);
    const uint32_t h = readLe32(encoded + 8);
    const uint32_t row = readLe32(encoded + 12);
    const uint32_t raw = readLe32(encoded + 16);
    const uint32_t packed = readLe32(encoded + 20);
    const uint8_t flag = encoded[24];
    if (!w || w > 4096 || !h || h > 4096 || row < w * 4u ||
        uint64_t(row) * h != raw || raw > kCslzMaxRawBytes ||
        flag > 1 || packed != uint32_t(encodedSize - kCslzHeaderSize) ||
        !packed || packed > raw || (flag && packed >= raw) || (!flag && packed != raw))
        return false;
    width = static_cast<int>(w);
    height = static_cast<int>(h);
    stride = static_cast<int>(row);
    rawSize = static_cast<int>(raw);
    packedSize = static_cast<int>(packed);
    compressed = flag != 0;
    return true;
}

BrushEngine* getEngine(
    CreativeBrushHandle handle
)
{
    return static_cast<BrushEngine*>(
        handle
    );
}

DocumentState* getDocument(CreativeDocumentHandle handle)
{
    return static_cast<DocumentState*>(handle);
}
}

CreativeDocumentHandle cs_document_create(int width, int height, int dpi)
{
    if (!validateDocumentGeometry(width, height, dpi)) return nullptr;
    try { return new DocumentState(width, height, dpi); }
    catch (...) { return nullptr; }
}

void cs_document_destroy(CreativeDocumentHandle handle)
{
    delete getDocument(handle);
}

int cs_document_add_layer(CreativeDocumentHandle handle, const char* name,
                          int* index)
{
    if (!handle || !name || !index) return 0;
    return getDocument(handle)->addLayer(name, *index) ? 1 : 0;
}

void cs_document_reset_layers(CreativeDocumentHandle handle)
{
    if (handle) getDocument(handle)->resetLayers();
}

int cs_document_create_group(CreativeDocumentHandle handle, const int* indices,
                             int count, const char* name, int* groupIndex)
{
    if (!handle || !indices || count <= 0 || !name || !groupIndex) return 0;
    return getDocument(handle)->createGroup(
        std::vector<int>(indices, indices + count), name, *groupIndex) ? 1 : 0;
}

int cs_document_remove_group(CreativeDocumentHandle handle, int groupIndex)
{
    return handle && getDocument(handle)->removeGroup(groupIndex) ? 1 : 0;
}

int cs_document_set_group_property(CreativeDocumentHandle handle, int groupIndex,
                                   int property, double requested, double* output)
{
    if (!handle || !output) return 0;
    return getDocument(handle)->setGroupProperty(groupIndex, property, requested,
                                                 *output) ? 1 : 0;
}

void cs_document_reset_groups(CreativeDocumentHandle handle)
{
    if (handle) getDocument(handle)->resetGroups();
}

int cs_document_group_count(CreativeDocumentHandle handle)
{
    return handle ? getDocument(handle)->groupCount() : 0;
}

int cs_document_group_for_layer(CreativeDocumentHandle handle, int layerIndex)
{
    return handle ? getDocument(handle)->groupForLayer(layerIndex) : -1;
}

int cs_document_remove_layer(CreativeDocumentHandle handle, int index)
{
    return handle && getDocument(handle)->removeLayer(index) ? 1 : 0;
}

int cs_document_reorder_layers(CreativeDocumentHandle handle, const int* order,
                               int count, int activeIndex)
{
    if (!handle || !order || count < 0) return 0;
    return getDocument(handle)->reorderLayers(
        std::vector<int>(order, order + count), activeIndex) ? 1 : 0;
}

int cs_document_select_layer(CreativeDocumentHandle handle, int index)
{
    return handle && getDocument(handle)->selectLayer(index) ? 1 : 0;
}

int cs_document_rename_layer(CreativeDocumentHandle handle, int index,
                             const char* name)
{
    if (!handle || !name) return 0;
    return getDocument(handle)->renameLayer(index, name) ? 1 : 0;
}

int cs_document_set_layer_property(CreativeDocumentHandle handle, int index,
                                   int property, double requested,
                                   double* output)
{
    if (!handle || !output) return 0;
    return getDocument(handle)->setLayerProperty(index, property, requested,
                                                 *output) ? 1 : 0;
}

int cs_document_layer_count(CreativeDocumentHandle handle)
{
    return handle ? getDocument(handle)->layerCount() : 0;
}

int cs_document_active_layer(CreativeDocumentHandle handle)
{
    return handle ? getDocument(handle)->activeLayer() : -1;
}

int cs_document_layer_info(CreativeDocumentHandle handle, int index,
                           uint64_t* id, int* visible, float* opacity,
                           int* locked, int* lockAlpha, int* clipping)
{
    if (!handle || !id || !visible || !opacity || !locked || !lockAlpha ||
        !clipping) return 0;
    NativeLayerState state;
    if (!getDocument(handle)->layerInfo(index, state)) return 0;
    *id = state.id;
    *visible = state.visible ? 1 : 0;
    *opacity = state.opacity;
    *locked = state.locked ? 1 : 0;
    *lockAlpha = state.lockAlpha ? 1 : 0;
    *clipping = state.clipping ? 1 : 0;
    return 1;
}

int cs_document_copy_layer_name(CreativeDocumentHandle handle, int index,
                                char* output, int capacity)
{
    if (!handle || !output || capacity <= 0) return 0;
    NativeLayerState state;
    if (!getDocument(handle)->layerInfo(index, state)) return 0;
    if (static_cast<int>(state.name.size()) + 1 > capacity) return 0;
    std::memcpy(output, state.name.c_str(), state.name.size() + 1);
    return static_cast<int>(state.name.size());
}

CreativeHistoryCursorHandle cs_history_cursor_create(int maximumSteps)
{
    try { return new HistoryCursor(maximumSteps); }
    catch (...) { return nullptr; }
}

void cs_history_cursor_destroy(CreativeHistoryCursorHandle handle)
{ delete static_cast<HistoryCursor*>(handle); }

void cs_history_cursor_reset(CreativeHistoryCursorHandle handle)
{ if (handle) static_cast<HistoryCursor*>(handle)->reset(); }

int cs_history_cursor_begin_transaction(CreativeHistoryCursorHandle handle,
                                        int dirtyOnly, int selectionOnly,
                                        int structureOnly)
{
    return handle && static_cast<HistoryCursor*>(handle)->beginTransaction(
        dirtyOnly != 0, selectionOnly != 0, structureOnly != 0);
}

int cs_history_cursor_commit_transaction(CreativeHistoryCursorHandle handle)
{ return handle && static_cast<HistoryCursor*>(handle)->commitTransaction(); }

int cs_history_cursor_cancel_transaction(CreativeHistoryCursorHandle handle)
{ return handle && static_cast<HistoryCursor*>(handle)->cancelTransaction(); }

int cs_history_cursor_transaction_open(CreativeHistoryCursorHandle handle)
{ return handle && static_cast<HistoryCursor*>(handle)->transactionOpen(); }

int cs_history_cursor_transaction_mode(CreativeHistoryCursorHandle handle)
{
    if (!handle) return -1;
    return static_cast<int>(static_cast<HistoryCursor*>(handle)->transactionMode());
}

int cs_history_cursor_append(CreativeHistoryCursorHandle handle,
                             int* truncatedForward, int* discardedOldest)
{
    if (!handle || !truncatedForward || !discardedOldest) return 0;
    return static_cast<HistoryCursor*>(handle)->append(*truncatedForward, *discardedOldest);
}

int cs_history_cursor_append_state(CreativeHistoryCursorHandle handle,
                                   const uint8_t* before, uint32_t beforeSize,
                                   const uint8_t* after, uint32_t afterSize,
                                   int* truncatedForward, int* discardedOldest)
{
    if (!handle || !truncatedForward || !discardedOldest) return 0;
    return static_cast<HistoryCursor*>(handle)->appendState(
        before, beforeSize, after, afterSize, *truncatedForward, *discardedOldest);
}

uint32_t cs_history_cursor_state_size(CreativeHistoryCursorHandle handle,
                                      int index, int side)
{
    return handle ? static_cast<HistoryCursor*>(handle)->stateSize(index, side) : 0;
}

int cs_history_cursor_copy_state(CreativeHistoryCursorHandle handle, int index,
                                 int side, uint8_t* output, uint32_t capacity)
{
    return handle && static_cast<HistoryCursor*>(handle)->copyState(index, side, output, capacity) ? 1 : 0;
}

int cs_history_cursor_discard_oldest(CreativeHistoryCursorHandle handle, int count)
{ return handle ? static_cast<HistoryCursor*>(handle)->discardOldest(count) : 0; }

int cs_history_cursor_set_maximum(CreativeHistoryCursorHandle handle, int maximumSteps)
{ return handle ? static_cast<HistoryCursor*>(handle)->setMaximumSteps(maximumSteps) : 0; }

int cs_history_cursor_undo(CreativeHistoryCursorHandle handle)
{ return handle && static_cast<HistoryCursor*>(handle)->undo() ? 1 : 0; }

int cs_history_cursor_redo(CreativeHistoryCursorHandle handle)
{ return handle && static_cast<HistoryCursor*>(handle)->redo() ? 1 : 0; }

void cs_history_cursor_synchronize(CreativeHistoryCursorHandle handle,
                                   int stepCount, int index)
{ if (handle) static_cast<HistoryCursor*>(handle)->synchronize(stepCount, index); }

int cs_history_cursor_count(CreativeHistoryCursorHandle handle)
{ return handle ? static_cast<HistoryCursor*>(handle)->stepCount() : 0; }

int cs_history_cursor_index(CreativeHistoryCursorHandle handle)
{ return handle ? static_cast<HistoryCursor*>(handle)->index() : 0; }

int cs_history_cursor_maximum(CreativeHistoryCursorHandle handle)
{ return handle ? static_cast<HistoryCursor*>(handle)->maximumSteps() : 0; }

int cs_history_validate_layer_state(const uint8_t* payload, uint32_t payloadSize,
                                    int documentWidth, int documentHeight)
{
    if (!payload || payloadSize == 0 || payloadSize > 16u * 1024u * 1024u ||
        documentWidth <= 0 || documentHeight <= 0) return 0;
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(
        QByteArray(reinterpret_cast<const char*>(payload),
                   static_cast<qsizetype>(payloadSize)), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) return 0;
    const QJsonObject root = document.object();
    const QString mode = root.value("history_mode").toString();
    if (mode != QLatin1String("general") && mode != QLatin1String("structure")) return 0;
    const QJsonArray layers = root.value("layers").toArray();
    if (layers.isEmpty() || layers.size() > 100000) return 0;
    QSet<QString> ids;
    for (const QJsonValue& value : layers) {
        if (!value.isObject()) return 0;
        const QJsonObject layer = value.toObject();
        const QString id = layer.value("id").toString();
        if (id.isEmpty() || ids.contains(id)) return 0;
        ids.insert(id);
        if (layer.value("width").toInt(-1) != documentWidth ||
            layer.value("height").toInt(-1) != documentHeight ||
            !layer.value("format").isDouble()) return 0;
        const double opacity = layer.value("opacity").toDouble(-1.0);
        if (!std::isfinite(opacity) || opacity < 0.0 || opacity > 1.0) return 0;
        const QJsonValue parameters = layer.value("blend_parameters");
        if (!parameters.isObject()) return 0;
        const QJsonObject parameterObject = parameters.toObject();
        for (auto it = parameterObject.begin(); it != parameterObject.end(); ++it)
            if (!it.value().isDouble() || !std::isfinite(it.value().toDouble())) return 0;
    }
    const QJsonArray groups = root.value("layer_groups").toArray();
    if (groups.size() > 100000) return 0;
    QSet<QString> groupIds;
    for (const QJsonValue& value : groups) {
        if (!value.isObject()) return 0;
        const QJsonObject group = value.toObject();
        const QString groupId = group.value("id").toString();
        if (groupId.isEmpty() || groupIds.contains(groupId)) return 0;
        groupIds.insert(groupId);
        const QJsonArray members = group.value("layer_ids").toArray();
        if (members.isEmpty()) return 0;
        int previousPosition = -1;
        QSet<QString> localMembers;
        for (const QJsonValue& member : members) {
            const QString id = member.toString();
            if (id.isEmpty() || !ids.contains(id) || localMembers.contains(id)) return 0;
            localMembers.insert(id);
            int position = -1;
            for (qsizetype index = 0; index < layers.size(); ++index)
                if (layers[index].toObject().value("id").toString() == id) {
                    position = static_cast<int>(index);
                    break;
                }
            if (previousPosition >= 0 && position != previousPosition + 1) return 0;
            previousPosition = position;
        }
        const double opacity = group.value("opacity").toDouble(-1.0);
        if (!std::isfinite(opacity) || opacity < 0.0 || opacity > 1.0) return 0;
    }
    const int active = root.value("active_layer_index").toInt(-1);
    return active >= 0 && active < layers.size() ? 1 : 0;
}

CreativeHistoryPayloadHandle cs_history_payload_create(void)
{
    try { return new HistoryPayload(); }
    catch (...) { return nullptr; }
}

void cs_history_payload_destroy(CreativeHistoryPayloadHandle handle)
{ delete static_cast<HistoryPayload*>(handle); }

int cs_history_payload_append(CreativeHistoryPayloadHandle handle,
                              const CsImageView* before, const CsImageView* after)
{
    if (!handle || (!before && !after)) return 0;
    auto wrap = [](const CsImageView* view) -> QImage {
        if (!view || !view->pixels || view->width <= 0 || view->height <= 0 ||
            view->stride <= 0 || view->image_format <= QImage::Format_Invalid ||
            view->image_format > QImage::Format_Alpha8) return {};
        return QImage(const_cast<uint8_t*>(view->pixels), view->width, view->height,
                      view->stride, static_cast<QImage::Format>(view->image_format));
    };
    QImage beforeImage = wrap(before);
    QImage afterImage = wrap(after);
    if ((before && beforeImage.isNull()) || (after && afterImage.isNull())) return 0;
    try {
        return static_cast<HistoryPayload*>(handle)->append(
            before ? &beforeImage : nullptr, after ? &afterImage : nullptr);
    } catch (...) {
        return 0;
    }
}

int cs_history_payload_append_many(CreativeHistoryPayloadHandle handle,
                                   const CsHistoryImagePair* inputs, int count,
                                   int* payloadIndices, int outputCapacity)
{
    if (!handle || count < 0 || outputCapacity < count ||
        (count > 0 && (!inputs || !payloadIndices))) return 0;
    auto wrap = [](const CsImageView* view, QImage& output) -> bool {
        if (!view) return true;
        if (!view->pixels || view->width <= 0 || view->height <= 0 ||
            view->stride <= 0 || view->image_format <= QImage::Format_Invalid ||
            view->image_format > QImage::Format_Alpha8) return false;
        output = QImage(const_cast<uint8_t*>(view->pixels), view->width,
                        view->height, view->stride,
                        static_cast<QImage::Format>(view->image_format));
        return !output.isNull();
    };
    try {
        std::vector<QImage> views;
        views.reserve(static_cast<size_t>(count) * 2);
        std::vector<std::pair<const QImage*, const QImage*>> items;
        items.reserve(static_cast<size_t>(count));
        for (int i = 0; i < count; ++i) {
            if ((inputs[i].has_before != 0 && inputs[i].has_before != 1) ||
                (inputs[i].has_after != 0 && inputs[i].has_after != 1)) return 0;
            const QImage* before = nullptr;
            const QImage* after = nullptr;
            if (inputs[i].has_before) {
                views.emplace_back();
                if (!wrap(&inputs[i].before, views.back())) return 0;
                before = &views.back();
            }
            if (inputs[i].has_after) {
                views.emplace_back();
                if (!wrap(&inputs[i].after, views.back())) return 0;
                after = &views.back();
            }
            items.emplace_back(before, after);
        }
        std::vector<int> indices;
        if (!static_cast<HistoryPayload*>(handle)->appendMany(items, indices) ||
            static_cast<int>(indices.size()) != count) return 0;
        std::copy(indices.begin(), indices.end(), payloadIndices);
        return 1;
    } catch (...) {
        return 0;
    }
}

int cs_history_payload_tile_info(CreativeHistoryPayloadHandle handle, int index,
                                 int side, int* present, int* width,
                                 int* height, int* imageFormat)
{
    if (!handle || !present || !width || !height || !imageFormat) return 0;
    bool exists = false;
    if (!static_cast<HistoryPayload*>(handle)->tileInfo(
            index, side, exists, *width, *height, *imageFormat)) return 0;
    *present = exists ? 1 : 0;
    return 1;
}

int cs_history_payload_copy_tile(CreativeHistoryPayloadHandle handle, int index,
                                 int side, uint8_t* output, int width,
                                 int height, int stride, int imageFormat)
{
    if (!handle || !output || width <= 0 || height <= 0 || stride <= 0 ||
        imageFormat <= QImage::Format_Invalid || imageFormat > QImage::Format_Alpha8)
        return 0;
    QImage target(output, width, height, stride, static_cast<QImage::Format>(imageFormat));
    if (target.isNull()) return 0;
    return static_cast<HistoryPayload*>(handle)->copyTile(index, side, target) ? 1 : 0;
}

int cs_history_payload_count(CreativeHistoryPayloadHandle handle)
{ return handle ? static_cast<HistoryPayload*>(handle)->count() : 0; }

int64_t cs_history_payload_allocated_bytes(CreativeHistoryPayloadHandle handle)
{ return handle ? static_cast<HistoryPayload*>(handle)->allocatedBytes() : 0; }

void cs_history_payload_clear(CreativeHistoryPayloadHandle handle)
{ if (handle) static_cast<HistoryPayload*>(handle)->clear(); }

int cs_history_payload_apply_to_tile_stores(CreativeHistoryPayloadHandle payload,
                                            const CsHistoryStoreWrite* writes,
                                            int count, int side)
{
    if (!payload || count < 0 || count > 1'000'000 || side < 0 || side > 1 ||
        (count > 0 && !writes)) return 0;
    auto* history = static_cast<HistoryPayload*>(payload);
    std::map<NativeTileStore*, std::vector<NativeTileStore::TileUpdate>> grouped;
    try {
        for (int i = 0; i < count; ++i) {
            if (!writes[i].store) return 0;
            auto* store = static_cast<NativeTileStore*>(writes[i].store);
            bool present = false;
            int width = 0, height = 0, format = 0;
            if (!history->tileInfo(writes[i].payload_index, side, present,
                                   width, height, format)) return 0;
            const int x = writes[i].tile_x, y = writes[i].tile_y;
            if (x < 0 || y < 0 || x > (store->width() - 1) / store->tileSize() ||
                y > (store->height() - 1) / store->tileSize()) return 0;
            if (!present) {
                grouped[store].push_back({x, y, QImage(), false});
                continue;
            }
            const int expectedWidth = std::min(store->tileSize(), store->width() - x * store->tileSize());
            const int expectedHeight = std::min(store->tileSize(), store->height() - y * store->tileSize());
            if (width != expectedWidth || height != expectedHeight) return 0;
            QImage image(width, height, static_cast<QImage::Format>(format));
            if (image.isNull() || !history->copyTile(writes[i].payload_index, side, image)) return 0;
            grouped[store].push_back({x, y, std::move(image), true});
        }
        std::vector<NativeTileStore::StoreBatch> batches;
        batches.reserve(grouped.size());
        for (auto& [store, updates] : grouped)
            batches.push_back({store, std::move(updates)});
        return NativeTileStore::applyBatches(batches) ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

int cs_lz4_available(void)
{
#ifdef CREATIVECORE_HAVE_LZ4
    return 1;
#else
    return 0;
#endif
}

int cs_lz4_compress_bound(int inputSize)
{
#ifdef CREATIVECORE_HAVE_LZ4
    if (inputSize < 0) return 0;
    return LZ4_compressBound(inputSize);
#else
    (void)inputSize;
    return 0;
#endif
}

int cs_lz4_compress(const uint8_t* input, int inputSize, uint8_t* output,
                    int outputCapacity, int* outputSize)
{
    if (!input || !output || !outputSize || inputSize <= 0 || outputCapacity <= 0)
        return 0;
#ifdef CREATIVECORE_HAVE_LZ4
    const int written = LZ4_compress_default(
        reinterpret_cast<const char*>(input), reinterpret_cast<char*>(output),
        inputSize, outputCapacity);
    if (written <= 0) return 0;
    *outputSize = written;
    return 1;
#else
    return 0;
#endif
}

int cs_lz4_decompress(const uint8_t* input, int inputSize, uint8_t* output,
                      int expectedSize, int* outputSize)
{
    if (!input || !output || !outputSize || inputSize <= 0 || expectedSize <= 0)
        return 0;
#ifdef CREATIVECORE_HAVE_LZ4
    const int written = LZ4_decompress_safe(
        reinterpret_cast<const char*>(input), reinterpret_cast<char*>(output),
        inputSize, expectedSize);
    if (written < 0) return 0;
    *outputSize = written;
    return 1;
#else
    return 0;
#endif
}

int cs_cslz_max_encoded_size(int rawSize)
{
    if (rawSize <= 0 || rawSize > kCslzMaxRawBytes) return 0;
    const int bound = cs_lz4_compress_bound(rawSize);
    return kCslzHeaderSize + std::max(rawSize, bound);
}

int cs_cslz_encode(const uint8_t* rgba, int width, int height, int stride,
                   uint8_t* output, int outputCapacity, int* outputSize)
{
    if (!rgba || !output || !outputSize || width <= 0 || width > 4096 ||
        height <= 0 || height > 4096 || stride < width * 4 ||
        uint64_t(stride) * height > kCslzMaxRawBytes) return 0;
    const int rawSize = stride * height;
    const int required = cs_cslz_max_encoded_size(rawSize);
    if (required <= 0 || outputCapacity < kCslzHeaderSize + rawSize) return 0;

    int packedSize = 0;
    bool compressed = false;
    if (cs_lz4_available()) {
        const int capacity = cs_lz4_compress_bound(rawSize);
        if (capacity > 0 && outputCapacity >= kCslzHeaderSize + capacity &&
            cs_lz4_compress(rgba, rawSize, output + kCslzHeaderSize,
                            capacity, &packedSize) && packedSize < rawSize) {
            compressed = true;
        }
    }
    if (!compressed) {
        packedSize = rawSize;
        std::memcpy(output + kCslzHeaderSize, rgba, rawSize);
    }
    std::memcpy(output, "CSLZ", 4);
    writeLe32(output + 4, static_cast<uint32_t>(width));
    writeLe32(output + 8, static_cast<uint32_t>(height));
    writeLe32(output + 12, static_cast<uint32_t>(stride));
    writeLe32(output + 16, static_cast<uint32_t>(rawSize));
    writeLe32(output + 20, static_cast<uint32_t>(packedSize));
    output[24] = compressed ? 1 : 0;
    *outputSize = kCslzHeaderSize + packedSize;
    return 1;
}

int cs_cslz_decode_info(const uint8_t* encoded, int encodedSize,
                        int* width, int* height, int* stride,
                        int* rawSize, int* compressed)
{
    if (!width || !height || !stride || !rawSize || !compressed) return 0;
    int packedSize = 0;
    bool isCompressed = false;
    if (!parseCslz(encoded, encodedSize, *width, *height, *stride,
                   *rawSize, packedSize, isCompressed)) return 0;
    *compressed = isCompressed ? 1 : 0;
    return 1;
}

int cs_cslz_decode(const uint8_t* encoded, int encodedSize,
                   uint8_t* output, int outputCapacity)
{
    if (!output) return 0;
    int width = 0, height = 0, stride = 0, rawSize = 0, packedSize = 0;
    bool compressed = false;
    if (!parseCslz(encoded, encodedSize, width, height, stride,
                   rawSize, packedSize, compressed) || outputCapacity < rawSize)
        return 0;
    const uint8_t* payload = encoded + kCslzHeaderSize;
    if (!compressed) {
        std::memcpy(output, payload, rawSize);
        return 1;
    }
    int written = 0;
    return cs_lz4_decompress(payload, packedSize, output, rawSize, &written) &&
           written == rawSize ? 1 : 0;
}

CreativeTileStoreHandle cs_tile_store_create(int width, int height, int tileSize)
{
    try { return new NativeTileStore(width, height, tileSize); }
    catch (...) { return nullptr; }
}

void cs_tile_store_destroy(CreativeTileStoreHandle handle)
{ delete static_cast<NativeTileStore*>(handle); }

int cs_tile_store_set(CreativeTileStoreHandle handle, int tileX, int tileY,
                      const uint8_t* pixels, int width, int height, int stride,
                      int imageFormat)
{
    if (!handle || !pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888)) return 0;
    QImage source(const_cast<uint8_t*>(pixels), width, height, stride,
                  static_cast<QImage::Format>(imageFormat));
    return static_cast<NativeTileStore*>(handle)->setTile(tileX, tileY, source) ? 1 : 0;
}

int cs_tile_store_set_many(CreativeTileStoreHandle handle,
                           const CsTileWrite* writes, int count)
{
    if (!handle || count < 0 || (count > 0 && !writes)) return 0;
    auto* store = static_cast<NativeTileStore*>(handle);
    for (int i = 0; i < count; ++i) {
        const auto& write = writes[i];
        if (!write.pixels || write.width <= 0 || write.height <= 0 ||
            write.stride < write.width * 4 ||
            (write.image_format != QImage::Format_ARGB32 &&
             write.image_format != QImage::Format_RGBA8888)) return 0;
    }
    try {
        std::vector<NativeTileStore::TileUpdate> updates;
        updates.reserve(static_cast<size_t>(count));
        for (int i = 0; i < count; ++i) {
            const auto& write = writes[i];
            QImage source(const_cast<uint8_t*>(write.pixels), write.width,
                          write.height, write.stride,
                          static_cast<QImage::Format>(write.image_format));
            updates.push_back({write.tile_x, write.tile_y, source, true});
        }
        if (!store->applyBatch(updates)) return 0;
    } catch (...) {
        return 0;
    }
    return 1;
}

int cs_tile_store_write_image(CreativeTileStoreHandle handle, const uint8_t* pixels,
                              int width, int height, int stride, int imageFormat,
                              int x, int y, int dirtyWidth, int dirtyHeight,
                              int* changedPairs, int pairCapacity)
{
    if (!handle || !pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        pairCapacity < 0 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888)) return -1;
    QImage source(const_cast<uint8_t*>(pixels), width, height, stride,
                  static_cast<QImage::Format>(imageFormat));
    return static_cast<NativeTileStore*>(handle)->writeImage(
        source, x, y, dirtyWidth, dirtyHeight, changedPairs, pairCapacity);
}

int cs_tile_store_copy(CreativeTileStoreHandle handle, int tileX, int tileY,
                       uint8_t* output, int width, int height, int stride,
                       int imageFormat)
{
    if (!handle || !output || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888)) return 0;
    QImage target(output, width, height, stride, static_cast<QImage::Format>(imageFormat));
    return static_cast<NativeTileStore*>(handle)->copyTile(tileX, tileY, target) ? 1 : 0;
}

int cs_tile_store_copy_store(CreativeTileStoreHandle destination,
                             CreativeTileStoreHandle source)
{
    if (!destination || !source) return 0;
    try {
        return static_cast<NativeTileStore*>(destination)->copyResidentFrom(
            *static_cast<NativeTileStore*>(source)) ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

int cs_tile_store_materialize(CreativeTileStoreHandle handle, uint8_t* output,
                              int width, int height, int stride, int imageFormat)
{
    if (!handle || !output || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888)) return 0;
    QImage target(output, width, height, stride, static_cast<QImage::Format>(imageFormat));
    return static_cast<NativeTileStore*>(handle)->materialize(target) ? 1 : 0;
}

int cs_tile_store_info(CreativeTileStoreHandle handle, int tileX, int tileY,
                       int* resident, uint64_t* revision, uint64_t* lastAccess)
{
    if (!handle || !resident || !revision || !lastAccess) return 0;
    bool isResident = false;
    unsigned long long rev = 0, access = 0;
    if (!static_cast<NativeTileStore*>(handle)->tileInfo(tileX, tileY, isResident, rev, access)) return 0;
    *resident = isResident ? 1 : 0; *revision = rev; *lastAccess = access;
    return 1;
}

int cs_tile_store_copy_keys(CreativeTileStoreHandle handle, int* xyPairs, int pairCapacity)
{ return handle ? static_cast<NativeTileStore*>(handle)->copyKeys(xyPairs, pairCapacity) : -1; }

int cs_tile_store_remove(CreativeTileStoreHandle handle, int tileX, int tileY)
{ return handle && static_cast<NativeTileStore*>(handle)->removeTile(tileX, tileY) ? 1 : 0; }

int64_t cs_tile_store_write_png(CreativeTileStoreHandle handle, int tileX,
                                int tileY, const char* path)
{
    if (!handle || !path) return 0;
    return static_cast<NativeTileStore*>(handle)->writeTilePng(
        tileX, tileY, QString::fromUtf8(path));
}

int cs_tile_store_load_png(CreativeTileStoreHandle handle, int tileX, int tileY,
                           const char* path, uint64_t expectedRevision)
{
    if (!handle || !path) return 0;
    return static_cast<NativeTileStore*>(handle)->loadTilePng(
        tileX, tileY, QString::fromUtf8(path), expectedRevision) ? 1 : 0;
}

int64_t cs_image_write_png(const char* path, const uint8_t* pixels, int width,
                           int height, int stride, int imageFormat)
{
    if (!path || !pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888)) return 0;
    QImage source(const_cast<uint8_t*>(pixels), width, height, stride,
                  static_cast<QImage::Format>(imageFormat));
    QSaveFile file(QString::fromUtf8(path));
    if (!file.open(QIODevice::WriteOnly) || !source.save(&file, "PNG") || !file.commit()) {
        file.cancelWriting();
        return 0;
    }
    return source.sizeInBytes();
}

int cs_image_fill(uint8_t* pixels, int width, int height, int stride,
                  int imageFormat, int red, int green, int blue, int alpha)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 &&
         imageFormat != QImage::Format_RGBA8888 &&
         imageFormat != QImage::Format_ARGB32_Premultiplied &&
         imageFormat != QImage::Format_RGBA8888_Premultiplied)) return 0;
    QImage image(pixels, width, height, stride,
                 static_cast<QImage::Format>(imageFormat));
    image.fill(QColor(std::clamp(red, 0, 255), std::clamp(green, 0, 255),
                      std::clamp(blue, 0, 255), std::clamp(alpha, 0, 255)));
    return 1;
}

int cs_image_fill_rect(uint8_t* pixels, int width, int height, int stride,
                       int imageFormat, int x, int y, int rectWidth,
                       int rectHeight, int red, int green, int blue, int alpha)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        rectWidth < 0 || rectHeight < 0 ||
        (imageFormat != QImage::Format_ARGB32 &&
         imageFormat != QImage::Format_RGBA8888 &&
         imageFormat != QImage::Format_ARGB32_Premultiplied &&
         imageFormat != QImage::Format_RGBA8888_Premultiplied)) return 0;
    QImage image(pixels, width, height, stride,
                 static_cast<QImage::Format>(imageFormat));
    const QRect rect = QRect(x, y, rectWidth, rectHeight).intersected(image.rect());
    if (rect.isEmpty()) return 1;
    QPainter painter(&image);
    painter.setCompositionMode(QPainter::CompositionMode_Source);
    painter.fillRect(rect, QColor(std::clamp(red, 0, 255),
                                  std::clamp(green, 0, 255),
                                  std::clamp(blue, 0, 255),
                                  std::clamp(alpha, 0, 255)));
    return painter.isActive() ? 1 : 0;
}

int cs_render_brush_preset_art(
    uint8_t* texture, int textureWidth, int textureHeight, int textureStride,
    int textureFormat, uint8_t* preview, int previewWidth, int previewHeight,
    int previewStride, int previewFormat, float hardness, float size,
    int red, int green, int blue, int alpha)
{
    auto validFormat = [](int format) {
        return format == QImage::Format_ARGB32 || format == QImage::Format_RGBA8888 ||
               format == QImage::Format_ARGB32_Premultiplied ||
               format == QImage::Format_RGBA8888_Premultiplied;
    };
    if (!texture || !preview || textureWidth <= 0 || textureHeight <= 0 ||
        previewWidth <= 0 || previewHeight <= 0 || textureStride < textureWidth * 4 ||
        previewStride < previewWidth * 4 || !validFormat(textureFormat) ||
        !validFormat(previewFormat) || !std::isfinite(hardness) ||
        !std::isfinite(size)) return 0;
    hardness = std::clamp(hardness, 0.0f, 1.0f);
    size = std::clamp(size, 5.0f, 52.0f);
    const QColor brushColor(std::clamp(red, 0, 255), std::clamp(green, 0, 255),
                            std::clamp(blue, 0, 255), std::clamp(alpha, 0, 255));
    QImage textureImage(texture, textureWidth, textureHeight, textureStride,
                        static_cast<QImage::Format>(textureFormat));
    QImage previewImage(preview, previewWidth, previewHeight, previewStride,
                        static_cast<QImage::Format>(previewFormat));
    textureImage.fill(Qt::transparent);
    previewImage.fill(QColor(48, 48, 48));
    QPainter texturePainter(&textureImage);
    texturePainter.setRenderHint(QPainter::Antialiasing, true);
    texturePainter.setPen(Qt::NoPen);
    QColor tipColor(255, 255, 255, static_cast<int>(255.0f * std::max(0.1f, hardness)));
    texturePainter.setBrush(tipColor);
    const int inset = static_cast<int>((1.0f - hardness) * 12.0f);
    texturePainter.drawEllipse(textureImage.rect().adjusted(inset, inset, -inset, -inset));
    texturePainter.end();

    QPainter previewPainter(&previewImage);
    previewPainter.setRenderHint(QPainter::Antialiasing, true);
    previewPainter.setPen(Qt::NoPen);
    previewPainter.setBrush(brushColor);
    const int previewSize = std::clamp(static_cast<int>(size), 5, 52);
    previewPainter.drawEllipse(8, (previewHeight - previewSize) / 2,
                              previewSize, previewSize);
    previewPainter.setPen(QPen(brushColor, 1.0, Qt::SolidLine,
                               Qt::RoundCap, Qt::RoundJoin));
    previewPainter.drawLine(42, previewHeight / 2, previewWidth - 8, previewHeight / 2);
    previewPainter.end();
    return 1;
}

int cs_apply_alpha_mask(uint8_t* image, int imageWidth, int imageHeight,
                        int imageStride, int imageFormat,
                        const uint8_t* mask, int maskWidth, int maskHeight,
                        int maskStride, int maskFormat)
{
    const auto validFormat = [](int format) {
        return format == QImage::Format_ARGB32 || format == QImage::Format_RGBA8888 ||
               format == QImage::Format_ARGB32_Premultiplied ||
               format == QImage::Format_RGBA8888_Premultiplied;
    };
    if (!image || !mask || imageWidth <= 0 || imageHeight <= 0 ||
        maskWidth != imageWidth || maskHeight != imageHeight ||
        imageStride < imageWidth * 4 || maskStride < maskWidth * 4 ||
        !validFormat(imageFormat) || !validFormat(maskFormat)) return 0;
    QImage imageView(image, imageWidth, imageHeight, imageStride,
                     static_cast<QImage::Format>(imageFormat));
    const QImage maskView(const_cast<uint8_t*>(mask), maskWidth, maskHeight,
                          maskStride, static_cast<QImage::Format>(maskFormat));
    for (int y = 0; y < imageHeight; ++y) {
        for (int x = 0; x < imageWidth; ++x) {
            const QRgb source = imageView.pixel(x, y);
            const QRgb coverage = maskView.pixel(x, y);
            const int alpha = qAlpha(source) * qAlpha(coverage) / 255;
            imageView.setPixel(x, y, qRgba(qRed(source), qGreen(source),
                                           qBlue(source), alpha));
        }
    }
    return 1;
}

void cs_tile_store_clear(CreativeTileStoreHandle handle)
{ if (handle) static_cast<NativeTileStore*>(handle)->clear(); }

void cs_tile_store_resize(CreativeTileStoreHandle handle, int width, int height)
{ if (handle) static_cast<NativeTileStore*>(handle)->resize(width, height); }

int64_t cs_tile_store_allocated_bytes(CreativeTileStoreHandle handle)
{ return handle ? static_cast<NativeTileStore*>(handle)->allocatedBytes() : 0; }

int cs_apply_linear_gradient(uint8_t* pixels, int width, int height, int stride,
                             int imageFormat, float startX, float startY,
                             float endX, float endY,
                             int red, int green, int blue, int alpha)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 &&
         imageFormat != QImage::Format_RGBA8888) ||
        !std::isfinite(startX) || !std::isfinite(startY) ||
        !std::isfinite(endX) || !std::isfinite(endY)) return 0;
    QImage image(pixels, width, height, stride,
                 static_cast<QImage::Format>(imageFormat));
    QPointF start(startX, startY);
    QPointF end(endX, endY);
    if (start == end) end.setX(end.x() + 1.0);
    QColor opaque(std::clamp(red, 0, 255), std::clamp(green, 0, 255),
                  std::clamp(blue, 0, 255), std::clamp(alpha, 0, 255));
    QColor transparent = opaque;
    transparent.setAlpha(0);
    QLinearGradient gradient(start, end);
    gradient.setColorAt(0.0, opaque);
    gradient.setColorAt(1.0, transparent);
    QPainter painter(&image);
    painter.setCompositionMode(QPainter::CompositionMode_SourceOver);
    painter.fillRect(image.rect(), gradient);
    painter.end();
    return 1;
}

int cs_layer_stack_move(const int* groupIds, int layerCount, int activeIndex,
                        int direction, int* outputOrder, int* activeAfter)
{
    if (!groupIds || !outputOrder || !activeAfter || layerCount <= 0) return 0;
    std::vector<int> groups(groupIds, groupIds + layerCount);
    std::vector<int> order;
    int nextActive = -1;
    if (!moveLayerStack(groups, activeIndex, direction, order, nextActive)) return 0;
    std::copy(order.begin(), order.end(), outputOrder);
    *activeAfter = nextActive;
    return 1;
}

int cs_layer_stack_remove(int layerCount, int removeIndex, int activeIndex,
                          int* outputOrder, int* activeAfter)
{
    if (!outputOrder || !activeAfter) return 0;
    std::vector<int> order;
    int nextActive = -1;
    if (!removeLayerStack(layerCount, removeIndex, activeIndex, order, nextActive)) return 0;
    std::copy(order.begin(), order.end(), outputOrder);
    *activeAfter = nextActive;
    return 1;
}

int cs_layer_stack_plan_visible_merge(const int* effectiveVisibility,
                                      int layerCount, int activeIndex,
                                      int* outputKeepMask, int* targetIndex,
                                      int* activeAfter)
{
    if (!effectiveVisibility || !outputKeepMask || !targetIndex || !activeAfter ||
        layerCount <= 0) return 0;
    std::vector<int> visibility(effectiveVisibility, effectiveVisibility + layerCount);
    std::vector<int> keepMask;
    int target = -1;
    int nextActive = -1;
    if (!planVisibleLayerMerge(visibility, activeIndex, keepMask, target, nextActive))
        return 0;
    std::copy(keepMask.begin(), keepMask.end(), outputKeepMask);
    *targetIndex = target;
    *activeAfter = nextActive;
    return 1;
}

int cs_layer_stack_plan_visible_merge_groups(
    const int* layerVisibility, const int* groupMembership,
    const int* groupVisibility, int layerCount, int groupCount,
    int activeIndex, int* outputEffectiveVisibility,
    int* outputKeepMask, int* targetIndex, int* activeAfter)
{
    if (!layerVisibility || !groupMembership || !outputEffectiveVisibility ||
        !outputKeepMask || !targetIndex || !activeAfter || layerCount <= 0 ||
        groupCount < 0 || (groupCount > 0 && !groupVisibility)) return 0;
    const std::vector<int> layers(layerVisibility, layerVisibility + layerCount);
    const std::vector<int> membership(groupMembership, groupMembership + layerCount);
    const std::vector<int> groups = groupCount > 0
        ? std::vector<int>(groupVisibility, groupVisibility + groupCount)
        : std::vector<int>{};
    std::vector<int> effective, keep;
    int target = -1;
    int nextActive = -1;
    if (!planVisibleLayerMergeWithGroups(layers, membership, groups, activeIndex,
                                         effective, keep, target, nextActive))
        return 0;
    std::copy(effective.begin(), effective.end(), outputEffectiveVisibility);
    std::copy(keep.begin(), keep.end(), outputKeepMask);
    *targetIndex = target;
    *activeAfter = nextActive;
    return 1;
}

int cs_layer_property_update(int property, double currentValue,
                             double requestedValue, double* outputValue)
{
    if (!outputValue) return 0;
    return updateLayerProperty(property, currentValue, requestedValue,
                               *outputValue) ? 1 : 0;
}

int cs_layer_group_normalize(const int* requestedIndices, int requestedCount,
                             const int* groupedLayers, int layerCount,
                             int* outputIndices, int outputCapacity,
                             int* outputCount)
{
    if (!outputCount || requestedCount < 0 || layerCount <= 0 ||
        outputCapacity < requestedCount || !outputIndices || !groupedLayers ||
        (requestedCount > 0 && !requestedIndices)) return 0;
    std::vector<int> requested;
    if (requestedCount > 0)
        requested.assign(requestedIndices, requestedIndices + requestedCount);
    std::vector<int> grouped(groupedLayers, groupedLayers + layerCount);
    std::vector<int> normalized;
    if (!normalizeLayerGroup(layerCount, requested, grouped, normalized)) return 0;
    std::copy(normalized.begin(), normalized.end(), outputIndices);
    *outputCount = static_cast<int>(normalized.size());
    return 1;
}

int cs_layer_stack_plan_composite_runs(const int* groupIds, int layerCount,
                                       int* outputStarts, int* outputEnds,
                                       int* outputGroupIds, int outputCapacity,
                                       int* outputCount)
{
    if (!groupIds || !outputStarts || !outputEnds || !outputGroupIds ||
        !outputCount || layerCount <= 0 || outputCapacity < layerCount)
        return 0;
    const std::vector<int> groups(groupIds, groupIds + layerCount);
    std::vector<int> starts, ends, runGroups;
    if (!planLayerCompositeRuns(groups, starts, ends, runGroups)) return 0;
    std::copy(starts.begin(), starts.end(), outputStarts);
    std::copy(ends.begin(), ends.end(), outputEnds);
    std::copy(runGroups.begin(), runGroups.end(), outputGroupIds);
    *outputCount = static_cast<int>(starts.size());
    return 1;
}

int cs_layer_stack_plan_group_cleanup(const int* layerGroupIds,
                                      const int* keepLayers, int layerCount,
                                      int groupCount, int* outputKeepGroups,
                                      int* outputMembership, int outputCapacity)
{
    if (!layerGroupIds || !keepLayers || !outputKeepGroups ||
        !outputMembership || layerCount < 0 || groupCount < 0 ||
        outputCapacity < layerCount) return 0;
    const std::vector<int> memberships(layerGroupIds, layerGroupIds + layerCount);
    const std::vector<int> keep(keepLayers, keepLayers + layerCount);
    std::vector<int> keptGroups, surviving;
    if (!planLayerGroupCleanup(memberships, keep, groupCount, keptGroups, surviving))
        return 0;
    std::copy(keptGroups.begin(), keptGroups.end(), outputKeepGroups);
    std::copy(surviving.begin(), surviving.end(), outputMembership);
    return static_cast<int>(surviving.size());
}

int cs_document_validate_geometry(int width, int height, int dpi,
                                  int maximumDimension, uint64_t maximumPixels)
{
    return validateDocumentGeometry(width, height, dpi, maximumDimension,
                                    maximumPixels) ? 1 : 0;
}

int cs_composite_layer_in_place(uint8_t* target, const uint8_t* source,
                                int width, int height, int targetStride,
                                int sourceStride, int targetFormat,
                                int sourceFormat, float opacity, int mode)
{
    if (!target || !source || width <= 0 || height <= 0 ||
        targetStride < width * 4 || sourceStride < width * 4 ||
        !std::isfinite(opacity) || mode < 0 || mode > 11 ||
        (targetFormat != QImage::Format_ARGB32 && targetFormat != QImage::Format_RGBA8888) ||
        (sourceFormat != QImage::Format_ARGB32 && sourceFormat != QImage::Format_RGBA8888))
        return 0;

    static const QPainter::CompositionMode modes[] = {
        QPainter::CompositionMode_SourceOver,
        QPainter::CompositionMode_Darken,
        QPainter::CompositionMode_Multiply,
        QPainter::CompositionMode_ColorBurn,
        QPainter::CompositionMode_Lighten,
        QPainter::CompositionMode_Screen,
        QPainter::CompositionMode_ColorDodge,
        QPainter::CompositionMode_Overlay,
        QPainter::CompositionMode_SoftLight,
        QPainter::CompositionMode_HardLight,
        QPainter::CompositionMode_Difference,
        QPainter::CompositionMode_Exclusion,
    };
    QImage targetImage(target, width, height, targetStride,
                       static_cast<QImage::Format>(targetFormat));
    const QImage sourceImage(const_cast<uint8_t*>(source), width, height, sourceStride,
                             static_cast<QImage::Format>(sourceFormat));
    QPainter painter(&targetImage);
    if (!painter.isActive()) return 0;
    painter.setCompositionMode(modes[mode]);
    painter.setOpacity(std::clamp(opacity, 0.0f, 1.0f));
    painter.drawImage(0, 0, sourceImage);
    painter.end();
    return 1;
}

int cs_composite_layers(uint8_t* target, int width, int height,
                        int targetStride, int targetFormat,
                        const CsCompositeLayer* layers, int layerCount)
{
    if (!target || width <= 0 || height <= 0 ||
        static_cast<int64_t>(targetStride) < static_cast<int64_t>(width) * 4 ||
        static_cast<uint64_t>(width) * static_cast<uint64_t>(height) > 268435456ULL ||
        (targetFormat != QImage::Format_ARGB32 && targetFormat != QImage::Format_RGBA8888) ||
        layerCount < 0 || layerCount > 4096 || (layerCount > 0 && !layers)) return 0;
    static const QPainter::CompositionMode modes[] = {
        QPainter::CompositionMode_SourceOver, QPainter::CompositionMode_Darken,
        QPainter::CompositionMode_Multiply, QPainter::CompositionMode_ColorBurn,
        QPainter::CompositionMode_Lighten, QPainter::CompositionMode_Screen,
        QPainter::CompositionMode_ColorDodge, QPainter::CompositionMode_Overlay,
        QPainter::CompositionMode_SoftLight, QPainter::CompositionMode_HardLight,
        QPainter::CompositionMode_Difference, QPainter::CompositionMode_Exclusion,
    };
    for (int i = 0; i < layerCount; ++i) {
        const auto& layer = layers[i];
        if (!layer.visible) continue;
        if (!layer.pixels || layer.stride < width * 4 || layer.mode < 0 || layer.mode > 11 ||
            (layer.image_format != QImage::Format_ARGB32 &&
             layer.image_format != QImage::Format_RGBA8888) || !std::isfinite(layer.opacity)) return 0;
    }
    QImage targetImage(target, width, height, targetStride,
                       static_cast<QImage::Format>(targetFormat));
    targetImage.fill(Qt::transparent);
    QPainter painter(&targetImage);
    if (!painter.isActive()) return 0;
    for (int i = 0; i < layerCount; ++i) {
        const auto& layer = layers[i];
        if (!layer.visible) continue;
        const QImage source(const_cast<uint8_t*>(layer.pixels), width, height,
                            layer.stride, static_cast<QImage::Format>(layer.image_format));
        painter.setCompositionMode(modes[layer.mode]);
        painter.setOpacity(std::clamp(layer.opacity, 0.0f, 1.0f));
        painter.drawImage(0, 0, source);
    }
    painter.end();
    return 1;
}

int cs_composite_layers_advanced(uint8_t* target, int width, int height,
                                 int targetStride,
                                 const CsAdvancedCompositeLayer* layers,
                                 int layerCount)
{
    if (!target || width <= 0 || height <= 0 ||
        static_cast<int64_t>(targetStride) < static_cast<int64_t>(width) * 4 ||
        static_cast<uint64_t>(width) * static_cast<uint64_t>(height) > 268435456ULL ||
        layerCount < 0 || layerCount > 4096 || (layerCount > 0 && !layers)) return 0;
    for (int i = 0; i < layerCount; ++i) {
        const auto& layer = layers[i];
        if (!layer.visible) continue;
        if (!layer.pixels || layer.stride < width * 4 || layer.mode < 0 || layer.mode > 15 ||
            !std::isfinite(layer.opacity)) return 0;
        for (float value : layer.parameters)
            if (!std::isfinite(value)) return 0;
    }
    QImage output(target, width, height, targetStride, QImage::Format_ARGB32);
    output.fill(Qt::transparent);
    std::vector<float> parameters;
    std::vector<float> weights;
    std::vector<int> opposites;
    std::vector<float> totals;
    try {
        parameters.resize(static_cast<size_t>(layerCount) * 11);
        weights.resize(static_cast<size_t>(layerCount) * 3);
        opposites.resize(static_cast<size_t>(layerCount));
        totals.resize(static_cast<size_t>(layerCount));
    } catch (...) {
        return 0;
    }
    for (int i = 0; i < layerCount; ++i) {
        const auto& layer = layers[i];
        float* p = parameters.data() + static_cast<size_t>(i) * 11;
        std::copy(std::begin(layer.parameters), std::end(layer.parameters), p);
        p[0] = std::clamp(p[0], 0.0f, 1.0f);
        p[1] = std::clamp(p[1], 0.0f, 1.0f);
        p[2] = std::clamp(p[2], 0.0f, 1.0f);
        p[3] = std::clamp(p[3], 0.5f, 2.5f);
        p[4] = std::clamp(p[4], 0.0f, 1.0f);
        p[5] = std::clamp(p[5], 0.0f, 1.0f);
        p[6] = std::clamp(p[6], 0.0f, 1.0f);
        p[7] = std::clamp(p[7], 0.0f, 1.0f);
        p[8] = std::clamp(p[8], -180.0f, 180.0f);
        p[9] = std::clamp(p[9], 0.0f, 2.0f);
        p[10] = std::clamp(p[10], 0.0f, 1.0f);
        opposites[i] = projection_compositor::opposite(layer.mode);
        float* w = weights.data() + static_cast<size_t>(i) * 3;
        w[0] = p[2] * (1.0f - p[4]) * (1.0f - p[1]);
        w[1] = 1.0f - p[2] * (1.0f - p[4]);
        w[2] = p[2] * (1.0f - p[4]) * p[1];
        totals[i] = w[0] + w[1] + (opposites[i] >= 0 ? w[2] : 0.0f);
    }
#ifdef _OPENMP
#pragma omp parallel for if(width * height >= 16384) schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        auto* dst = reinterpret_cast<QRgb*>(target + static_cast<size_t>(y) * targetStride);
        for (int x = 0; x < width; ++x) {
            projection_compositor::Pixel accumulated{{0.0f, 0.0f, 0.0f}, 0.0f};
            float clippingAlpha = 0.0f;
            for (int i = 0; i < layerCount; ++i) {
                const auto& layer = layers[i];
                if (!layer.visible) continue;
                const auto* src = reinterpret_cast<const QRgb*>(
                    layer.pixels + static_cast<size_t>(y) * layer.stride);
                const QRgb pixel = src[x];
                float sourceAlpha = qAlpha(pixel) / 255.0f *
                    std::clamp(layer.opacity, 0.0f, 1.0f) * parameters[static_cast<size_t>(i) * 11];
                // Clipped layers borrow coverage from the nearest base layer;
                // their blend changes RGB but must not expand the base alpha.
                if (layer.clipping) sourceAlpha *= clippingAlpha;
                else clippingAlpha = std::clamp(sourceAlpha, 0.0f, 1.0f);
                const float backdropAlpha = accumulated.a;
                const projection_compositor::RGB source{
                    qRed(pixel) / 255.0f, qGreen(pixel) / 255.0f, qBlue(pixel) / 255.0f};
                const size_t offset = static_cast<size_t>(i) * 11;
                projection_compositor::compose_layer(accumulated, source,
                    std::clamp(sourceAlpha, 0.0f, 1.0f), layer.mode,
                    parameters.data() + offset, opposites[i],
                    weights.data() + static_cast<size_t>(i) * 3, totals[i]);
                if (layer.clipping) accumulated.a = backdropAlpha;
            }
            dst[x] = qRgba(
                std::clamp(std::lround(accumulated.rgb[0] * 255.0f), 0l, 255l),
                std::clamp(std::lround(accumulated.rgb[1] * 255.0f), 0l, 255l),
                std::clamp(std::lround(accumulated.rgb[2] * 255.0f), 0l, 255l),
                std::clamp(std::lround(accumulated.a * 255.0f), 0l, 255l));
        }
    }
    return 1;
}

CreativeProjectionHandle cs_projection_start(CsProjectionCallback callback, void* userData)
{
    try { return new ProjectionEngine(callback, userData); }
    catch (...) { return nullptr; }
}

void cs_projection_stop(CreativeProjectionHandle handle)
{
    delete static_cast<ProjectionEngine*>(handle);
}

void cs_projection_set_callback(CreativeProjectionHandle handle,
                                CsProjectionCallback callback, void* userData)
{
    if (handle) static_cast<ProjectionEngine*>(handle)->setCallback(callback, userData);
}

void cs_projection_set_threads(CreativeProjectionHandle handle, int threadCount)
{
    if (handle) static_cast<ProjectionEngine*>(handle)->setThreads(threadCount);
}

int cs_projection_invalidate(CreativeProjectionHandle handle, uint64_t generation,
                             int tileX, int tileY, int width, int height,
                             const CsProjectionLayer* layers, int layerCount)
{
    if (!handle) return 0;
    return static_cast<ProjectionEngine*>(handle)->submit(
        generation, tileX, tileY, width, height, layers, layerCount) ? 1 : 0;
}

int cs_projection_invalidate_batch(CreativeProjectionHandle handle,
                                   const CsProjectionTile* tiles, int tileCount)
{
    if (!handle || !tiles || tileCount <= 0) return 0;
    return static_cast<ProjectionEngine*>(handle)->submitBatch(tiles, tileCount) ? 1 : 0;
}

void cs_image_restore_alpha_rect(
    uint8_t* dst, const uint8_t* src,
    int width, int height, int dstStride, int srcStride,
    int x, int y, int rectWidth, int rectHeight)
{
    if (!dst || !src || width <= 0 || height <= 0 ||
        dstStride < width * 4 || srcStride < width * 4 ||
        rectWidth <= 0 || rectHeight <= 0)
        return;
    const int x0 = std::clamp(x, 0, width);
    const int y0 = std::clamp(y, 0, height);
    const int x1 = std::clamp(x + rectWidth, 0, width);
    const int y1 = std::clamp(y + rectHeight, 0, height);
    for (int row = y0; row < y1; ++row) {
        uint8_t* out = dst + row * dstStride + x0 * 4 + 3;
        const uint8_t* in = src + row * srcStride + x0 * 4 + 3;
        creative_simd::restoreAlpha(out - 3, in - 3, x1 - x0);
    }
}

int cs_image_restore_alpha_tile(uint8_t* dst, int dstWidth, int dstHeight,
                                int dstStride, const uint8_t* src,
                                int srcWidth, int srcHeight, int srcStride,
                                int dstX, int dstY, int srcX, int srcY,
                                int rectWidth, int rectHeight)
{
    if (!dst || !src || dstWidth <= 0 || dstHeight <= 0 || srcWidth <= 0 ||
        srcHeight <= 0 || dstStride < dstWidth * 4 || srcStride < srcWidth * 4 ||
        rectWidth <= 0 || rectHeight <= 0 || dstX < 0 || dstY < 0 ||
        srcX < 0 || srcY < 0 || dstX > dstWidth || dstY > dstHeight ||
        srcX > srcWidth || srcY > srcHeight ||
        rectWidth > dstWidth - dstX || rectHeight > dstHeight - dstY ||
        rectWidth > srcWidth - srcX || rectHeight > srcHeight - srcY) return 0;
    for (int row = 0; row < rectHeight; ++row) {
        const uint8_t* source = src + (srcY + row) * srcStride + srcX * 4 + 3;
        uint8_t* target = dst + (dstY + row) * dstStride + dstX * 4 + 3;
        for (int column = 0; column < rectWidth; ++column)
            target[column * 4] = source[column * 4];
    }
    return 1;
}

const char* cs_simd_backend() { return creative_simd::backendName(); }
int cs_projection_normal_batch_calls() { return creative_projection::normal_batch_calls(); }
void cs_projection_reset_batch_calls() { creative_projection::reset_normal_batch_calls(); }

void cs_filter_brush_segment(
    uint8_t* rgba, int width, int height, int stride,
    float startX, float startY, float startPressure,
    float endX, float endY, float endPressure,
    float size, float spacing, float opacity, int sharpen)
{
    if (!rgba || width <= 0 || height <= 0 || stride < width * 4)
        return;
    size = std::max(1.0f, size);
    spacing = std::max(0.02f, spacing);
    opacity = std::clamp(opacity, 0.0f, 1.0f);
    const float dx = endX - startX;
    const float dy = endY - startY;
    const float length = std::hypot(dx, dy);
    const int steps = std::max(1, static_cast<int>(std::ceil(length / std::max(0.5f, size * spacing))));
    const int filterRadius = std::clamp(static_cast<int>(std::round(size * 0.06f)), 1, 5);
    std::vector<uint8_t> snapshot;
    for (int step = 0; step <= steps; ++step) {
        const float t = static_cast<float>(step) / steps;
        const float pressure = std::clamp(startPressure + (endPressure - startPressure) * t, 0.05f, 1.0f);
        const float cx = startX + dx * t;
        const float cy = startY + dy * t;
        const int dabRadius = std::max(1, static_cast<int>(std::ceil(size * pressure * 0.5f)));
        const int left = std::max(0, static_cast<int>(std::floor(cx)) - dabRadius);
        const int top = std::max(0, static_cast<int>(std::floor(cy)) - dabRadius);
        const int right = std::min(width - 1, static_cast<int>(std::ceil(cx)) + dabRadius);
        const int bottom = std::min(height - 1, static_cast<int>(std::ceil(cy)) + dabRadius);
        if (right < left || bottom < top) continue;
        const int srcLeft = std::max(0, left - filterRadius);
        const int srcTop = std::max(0, top - filterRadius);
        const int srcRight = std::min(width - 1, right + filterRadius);
        const int srcBottom = std::min(height - 1, bottom + filterRadius);
        const int srcWidth = srcRight - srcLeft + 1;
        const int srcHeight = srcBottom - srcTop + 1;
        snapshot.resize(static_cast<size_t>(srcWidth) * srcHeight * 4);
        for (int row = 0; row < srcHeight; ++row)
            std::memcpy(snapshot.data() + static_cast<size_t>(row) * srcWidth * 4,
                        rgba + (srcTop + row) * stride + srcLeft * 4,
                        static_cast<size_t>(srcWidth) * 4);
        for (int y = top; y <= bottom; ++y) {
            uint8_t* dst = rgba + y * stride;
            for (int x = left; x <= right; ++x) {
                const float ddx = x + 0.5f - cx;
                const float ddy = y + 0.5f - cy;
                const float distance = std::hypot(ddx, ddy);
                if (distance >= dabRadius) continue;
                const float coverage = opacity * pressure * (1.0f - distance / dabRadius);
                if (coverage <= 0.0f) continue;
                float sums[4] = {0, 0, 0, 0};
                float premul[3] = {0, 0, 0};
                int count = 0;
                for (int oy = -filterRadius; oy <= filterRadius; ++oy) {
                    const int sy = std::clamp(y + oy, 0, height - 1);
                    for (int ox = -filterRadius; ox <= filterRadius; ++ox) {
                        const int sx = std::clamp(x + ox, 0, width - 1);
                        const uint8_t* p = snapshot.data() +
                            (static_cast<size_t>(sy - srcTop) * srcWidth + (sx - srcLeft)) * 4;
                        const float a = p[3] / 255.0f;
                        for (int c = 0; c < 3; ++c) premul[c] += p[c] * a;
                        sums[3] += p[3];
                        ++count;
                    }
                }
                const uint8_t* original = snapshot.data() +
                    (static_cast<size_t>(y - srcTop) * srcWidth + (x - srcLeft)) * 4;
                const float blurredAlpha = sums[3] / count;
                for (int c = 0; c < 3; ++c) {
                    const float blurred = sums[3] > 0.0f ? premul[c] * 255.0f / sums[3] : original[c];
                    const float value = sharpen ? original[c] + 0.85f * (original[c] - blurred) : blurred;
                    dst[x * 4 + c] = static_cast<uint8_t>(std::clamp(
                        std::nearbyint(original[c] + (value - original[c]) * coverage),
                        0.0f, 255.0f));
                }
                if (!sharpen) {
                    const float oldAlpha = original[3];
                    dst[x * 4 + 3] = static_cast<uint8_t>(std::clamp(
                        std::nearbyint(oldAlpha + (blurredAlpha - oldAlpha) * coverage),
                        0.0f, 255.0f));
                }
            }
        }
    }
}

CreativeBrushHandle
cs_brush_create()
{
    return new BrushEngine();
}

void
cs_brush_destroy(
    CreativeBrushHandle handle
)
{
    delete getEngine(handle);
}

void
cs_brush_set_size(
    CreativeBrushHandle handle,
    float size
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.size = size;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_opacity(
    CreativeBrushHandle handle,
    float opacity
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.opacity =
        opacity;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_flow(
    CreativeBrushHandle handle,
    float flow
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.flow =
        flow;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_hardness(
    CreativeBrushHandle handle,
    float hardness
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.hardness =
        hardness;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_spacing(
    CreativeBrushHandle handle,
    float spacing
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.spacing =
        spacing;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_roundness(
    CreativeBrushHandle handle,
    float roundness
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.roundness =
        roundness;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_angle(
    CreativeBrushHandle handle,
    float angle
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.angle =
        angle;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_scatter(
    CreativeBrushHandle handle,
    float scatter
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.scatter =
        scatter;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_size_jitter(
    CreativeBrushHandle handle,
    float jitter
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.sizeJitter =
        jitter;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_rotation_jitter(
    CreativeBrushHandle handle,
    float jitter
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.rotationJitter =
        jitter;

    engine->setSettings(
        settings
    );
}

namespace
{
void setVelocitySetting(CreativeBrushHandle handle, float value, int channel)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;
    BrushSettings settings = engine->settings();
    if (channel == 0) settings.velocitySize = value;
    else if (channel == 1) settings.velocityOpacity = value;
    else settings.velocityFlow = value;
    engine->setSettings(settings);
}
}

void cs_brush_set_velocity_size(CreativeBrushHandle handle, float value)
{ setVelocitySetting(handle, value, 0); }

void cs_brush_set_velocity_opacity(CreativeBrushHandle handle, float value)
{ setVelocitySetting(handle, value, 1); }

void cs_brush_set_velocity_flow(CreativeBrushHandle handle, float value)
{ setVelocitySetting(handle, value, 2); }

void
cs_brush_set_texture_strength(
    CreativeBrushHandle handle,
    float strength
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureStrength =
        strength;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_scale(
    CreativeBrushHandle handle,
    float scale
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureScale =
        scale;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_random_scale(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureRandomScale =
        value;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_random_offset(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureRandomOffset =
        value;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_brightness(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureBrightness =
        value;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_contrast(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureContrast =
        value;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_mirror(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureMirror =
        enabled != 0;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_texture_affect_opacity(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.textureAffectOpacity =
        enabled != 0;

    engine->setSettings(
        settings
    );
}

int cs_brush_set_texture_path(CreativeBrushHandle handle, const char* path)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine || !path || !*path)
        return 0;

    QImageReader reader(QString::fromUtf8(path));
    const QSize dimensions = reader.size();
    // Check dimensions before decoding so a hostile image cannot allocate an
    // unbounded temporary buffer on the UI thread.
    if (!dimensions.isValid() || dimensions.width() > 4096 ||
        dimensions.height() > 4096)
        return 0;

    QImage source = reader.read();
    if (source.isNull())
        return 0;
    engine->setTexture(source);
    return engine->hasTexture() ? 1 : 0;
}

void cs_brush_clear_texture(CreativeBrushHandle handle)
{
    if (BrushEngine* engine = getEngine(handle))
        engine->clearTexture();
}

int cs_brush_set_bitmap_tip_path(CreativeBrushHandle handle, const char* path)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine || !path || !*path) return 0;
    QImageReader reader(QString::fromUtf8(path));
    const QSize dimensions = reader.size();
    if (!dimensions.isValid() || dimensions.width() > 4096 ||
        dimensions.height() > 4096) return 0;
    const QImage bitmap = reader.read();
    return engine->setBitmapTip(bitmap) ? 1 : 0;
}

int cs_brush_set_bitmap_tip_png(CreativeBrushHandle handle,
                                const uint8_t* data, uint64_t byteCount)
{
    BrushEngine* engine = getEngine(handle);
    constexpr uint64_t kMaxEncodedTipBytes = 32ull * 1024 * 1024;
    if (!engine || !data || !byteCount || byteCount > kMaxEncodedTipBytes ||
        byteCount > static_cast<uint64_t>(std::numeric_limits<qsizetype>::max())) return 0;
    QByteArray encoded(reinterpret_cast<const char*>(data), static_cast<qsizetype>(byteCount));
    QBuffer buffer(&encoded);
    if (!buffer.open(QIODevice::ReadOnly)) return 0;
    QImageReader reader(&buffer, "PNG");
    const QSize dimensions = reader.size();
    if (!dimensions.isValid() || dimensions.width() > 4096 || dimensions.height() > 4096)
        return 0;
    return engine->setBitmapTip(reader.read()) ? 1 : 0;
}

void cs_brush_clear_bitmap_tip(CreativeBrushHandle handle)
{
    if (BrushEngine* engine = getEngine(handle)) engine->clearBitmapTip();
}

void
cs_brush_set_dirty_color(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.dirtyColor = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_hue_jitter(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.hueJitter = value;
    engine->setSettings(settings);
}

void
cs_brush_set_saturation_jitter(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.saturationJitter = value;
    engine->setSettings(settings);
}

void
cs_brush_set_brightness_jitter(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.brightnessJitter = value;
    engine->setSettings(settings);
}

void
cs_brush_set_stroke_gradient(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.useStrokeGradient = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_linear_gradient(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.useLinearGradient = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_radial_gradient(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.useRadialGradient = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_gradient_amount(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.gradientAmount = value;
    engine->setSettings(settings);
}

void
cs_brush_set_gradient_color(
    CreativeBrushHandle handle,
    uint8_t red,
    uint8_t green,
    uint8_t blue,
    uint8_t alpha
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();

    settings.gradientColor =
        QColor(
            red,
            green,
            blue,
            alpha
        );

    engine->setSettings(settings);
}

void
cs_brush_set_blend_mode(
    CreativeBrushHandle handle,
    int mode
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();

    switch (mode)
    {
    case 0:
        settings.blendMode =
            BrushBlendMode::Normal;
        break;

    case 1:
        settings.blendMode =
            BrushBlendMode::Multiply;
        break;

    case 2:
        settings.blendMode =
            BrushBlendMode::Screen;
        break;

    case 3:
        settings.blendMode =
            BrushBlendMode::Overlay;
        break;

    case 4:
        settings.blendMode =
            BrushBlendMode::Darken;
        break;

    case 5:
        settings.blendMode =
            BrushBlendMode::Lighten;
        break;

    default:
        settings.blendMode =
            BrushBlendMode::Normal;
        break;
    }

    engine->setSettings(settings);
}

void
cs_brush_set_paint_mix(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.paintMix = value;
    engine->setSettings(settings);
}

void
cs_brush_set_wetness(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.wetness = value;
    engine->setSettings(settings);
}

void
cs_brush_set_pickup(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.pickup = value;
    engine->setSettings(settings);
}

void
cs_brush_set_dilution(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.dilution = value;
    engine->setSettings(settings);
}

void
cs_brush_set_smudge(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.smudge = value;
    engine->setSettings(settings);
}

void
cs_brush_set_paint_persistence(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.paintPersistence = value;
    engine->setSettings(settings);
}

void
cs_brush_set_color_carry(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.colorCarry = value;
    engine->setSettings(settings);
}

void
cs_brush_set_wet_mix(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.wetMix = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_sample_canvas(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.sampleCanvas = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_smudge_tool(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;
    BrushSettings settings = engine->settings();
    settings.smudgeTool = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_eraser(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushSettings settings =
        engine->settings();

    settings.eraser =
        enabled != 0;

    engine->setSettings(
        settings
    );
}

void
cs_brush_set_color(
    CreativeBrushHandle handle,
    uint8_t red,
    uint8_t green,
    uint8_t blue,
    uint8_t alpha
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    engine->setColor(
        QColor(
            red,
            green,
            blue,
            alpha
        )
    );
}

void
cs_brush_begin_stroke(
    CreativeBrushHandle handle,
    float x,
    float y,
    float pressure
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    BrushInput input;

    input.position =
        QPointF(
            x,
            y
        );

    input.pressure =
        pressure;

    engine->beginStroke(
        input
    );
}

void
cs_brush_draw_segment(
    CreativeBrushHandle handle,
    uint8_t* rgba,
    int width,
    int height,
    int bytesPerLine,
    float startX,
    float startY,
    float startPressure,
    float endX,
    float endY,
    float endPressure
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine ||
        !rgba ||
        width <= 0 ||
        height <= 0)
    {
        return;
    }

    /*
     * QImage ne copie pas les pixels :
     * il travaille directement sur le buffer
     * fourni par Python.
     */
    QImage image(
        rgba,
        width,
        height,
        bytesPerLine,
        QImage::Format_RGBA8888
    );

    BrushInput start;

    start.position =
        QPointF(
            startX,
            startY
        );

    start.pressure =
        startPressure;

    BrushInput end;

    end.position =
        QPointF(
            endX,
            endY
        );

    end.pressure =
        endPressure;

    engine->drawSegment(
        image,
        start,
        end
    );
}

void cs_brush_draw_segment_clone(
    CreativeBrushHandle handle, uint8_t* target, const uint8_t* source,
    int width, int height, int bytesPerLine, int sourceBytesPerLine,
    int cloneOffsetX, int cloneOffsetY,
    float startX, float startY, float startPressure, float startTiltX, float startTiltY,
    float endX, float endY, float endPressure, float endTiltX, float endTiltY)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine || !target || !source || width <= 0 || height <= 0)
        return;
    QImage targetImage(target, width, height, bytesPerLine, QImage::Format_RGBA8888);
    const QImage sourceImage(source, width, height, sourceBytesPerLine, QImage::Format_RGBA8888);
    BrushInput start;
    start.position = QPointF(startX, startY);
    start.pressure = startPressure;
    start.tiltX = startTiltX;
    start.tiltY = startTiltY;
    BrushInput end;
    end.position = QPointF(endX, endY);
    end.pressure = endPressure;
    end.tiltX = endTiltX;
    end.tiltY = endTiltY;
    engine->drawSegment(targetImage, start, end, &sourceImage, cloneOffsetX, cloneOffsetY);
}

void cs_brush_draw_segment_tilt(
    CreativeBrushHandle handle, uint8_t* rgba, int width, int height,
    int bytesPerLine, float startX, float startY, float startPressure,
    float startTiltX, float startTiltY, float endX, float endY,
    float endPressure, float endTiltX, float endTiltY)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine || !rgba || width <= 0 || height <= 0) return;
    QImage image(rgba, width, height, bytesPerLine, QImage::Format_RGBA8888);
    BrushInput start; start.position = QPointF(startX, startY);
    start.pressure = startPressure; start.tiltX = startTiltX; start.tiltY = startTiltY;
    BrushInput end; end.position = QPointF(endX, endY);
    end.pressure = endPressure; end.tiltX = endTiltX; end.tiltY = endTiltY;
    engine->drawSegment(image, start, end);
}

void
cs_brush_end_stroke(
    CreativeBrushHandle handle
)
{
    BrushEngine* engine =
        getEngine(handle);

    if (!engine)
        return;

    engine->endStroke();
}

void cs_brush_set_smoothing(CreativeBrushHandle handle, float strength)
{
    if (auto* engine = getEngine(handle)) engine->setSmoothing(strength);
}

int cs_brush_smooth_point(CreativeBrushHandle handle, float x, float y, float* outX, float* outY)
{
    auto* engine = getEngine(handle);
    if (!engine || !outX || !outY) return 0;
    const QPointF point = engine->smoothPoint(QPointF(x, y));
    *outX = static_cast<float>(point.x());
    *outY = static_cast<float>(point.y());
    return 1;
}

namespace
{
bool withinTolerance(QRgb pixel, QRgb target, int tolerance)
{
    return std::max({
        std::abs(qRed(pixel) - qRed(target)),
        std::abs(qGreen(pixel) - qGreen(target)),
        std::abs(qBlue(pixel) - qBlue(target)),
        std::abs(qAlpha(pixel) - qAlpha(target)),
    }) <= tolerance;
}
}

int cs_fill(
    uint8_t* pixels, int width, int height, int bytesPerLine, int imageFormat,
    int startX, int startY, int tolerance,
    uint8_t red, uint8_t green, uint8_t blue, uint8_t alpha,
    int* outX, int* outY, int* outWidth, int* outHeight)
{
    if (!pixels || width <= 0 || height <= 0 || bytesPerLine < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888) ||
        startX < 0 || startX >= width || startY < 0 || startY >= height ||
        !outX || !outY || !outWidth || !outHeight)
        return 0;

    try {
        QImage image(pixels, width, height, bytesPerLine, static_cast<QImage::Format>(imageFormat));
        const QRgb target = image.pixel(startX, startY);
        const QRgb replacement = qRgba(red, green, blue, alpha);
        tolerance = std::clamp(tolerance, 0, 255);
        *outX = *outY = *outWidth = *outHeight = 0;
        if (withinTolerance(replacement, target, tolerance))
            return 1;

        auto matches = [&](int x, int y) {
            return withinTolerance(image.pixel(x, y), target, tolerance);
        };
        std::deque<QPoint> pending;
        pending.emplace_back(startX, startY);
        int minX = startX, maxX = startX, minY = startY, maxY = startY;
        bool changed = false;

        while (!pending.empty()) {
            const QPoint seed = pending.back();
            pending.pop_back();
            const int y = seed.y();
            if (y < 0 || y >= height || seed.x() < 0 || seed.x() >= width || !matches(seed.x(), y))
                continue;

            int left = seed.x();
            while (left > 0 && matches(left - 1, y)) --left;
            int right = seed.x();
            while (right + 1 < width && matches(right + 1, y)) ++right;

            if (image.format() == QImage::Format_ARGB32) {
                QRgb* row = reinterpret_cast<QRgb*>(image.scanLine(y));
                std::fill(row + left, row + right + 1, replacement);
            } else {
                for (int x = left; x <= right; ++x)
                    image.setPixel(x, y, replacement);
            }
            changed = true;
            minX = std::min(minX, left); maxX = std::max(maxX, right);
            minY = std::min(minY, y); maxY = std::max(maxY, y);

            for (int adjacentY : {y - 1, y + 1}) {
                if (adjacentY < 0 || adjacentY >= height) continue;
                int x = left;
                while (x <= right) {
                    while (x <= right && !matches(x, adjacentY)) ++x;
                    if (x <= right) {
                        pending.emplace_back(x, adjacentY);
                        while (x <= right && matches(x, adjacentY)) ++x;
                    }
                }
            }
        }

        if (changed) {
            *outX = minX; *outY = minY;
            *outWidth = maxX - minX + 1; *outHeight = maxY - minY + 1;
        }
        return 1;
    } catch (...) {
        return 0;
    }
}

int cs_fill_bounds(const uint8_t* pixels, int width, int height, int bytesPerLine,
                   int imageFormat, int startX, int startY, int tolerance,
                   int* outX, int* outY, int* outWidth, int* outHeight)
{
    if (!pixels || width <= 0 || height <= 0 || bytesPerLine < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888) ||
        startX < 0 || startX >= width || startY < 0 || startY >= height ||
        !outX || !outY || !outWidth || !outHeight) return 0;
    try {
        const QImage image(const_cast<uint8_t*>(pixels), width, height, bytesPerLine,
                           static_cast<QImage::Format>(imageFormat));
        const QRgb target = image.pixel(startX, startY);
        tolerance = std::clamp(tolerance, 0, 255);
        auto matches = [&](int x, int y) {
            return withinTolerance(image.pixel(x, y), target, tolerance);
        };
        std::vector<uint8_t> visited(static_cast<size_t>(width) * height, 0);
        auto seen = [&](int x, int y) -> uint8_t& {
            return visited[static_cast<size_t>(y) * width + x];
        };
        std::deque<QPoint> pending;
        pending.emplace_back(startX, startY);
        int minX = startX, maxX = startX, minY = startY, maxY = startY;
        bool found = false;
        while (!pending.empty()) {
            const QPoint seed = pending.back(); pending.pop_back();
            const int y = seed.y(), x = seed.x();
            if (y < 0 || y >= height || x < 0 || x >= width || seen(x, y) || !matches(x, y))
                continue;
            int left = x, right = x;
            while (left > 0 && !seen(left - 1, y) && matches(left - 1, y)) --left;
            while (right + 1 < width && !seen(right + 1, y) && matches(right + 1, y)) ++right;
            for (int px = left; px <= right; ++px) seen(px, y) = 1;
            found = true;
            minX = std::min(minX, left); maxX = std::max(maxX, right);
            minY = std::min(minY, y); maxY = std::max(maxY, y);
            for (int adjacentY : {y - 1, y + 1}) {
                if (adjacentY < 0 || adjacentY >= height) continue;
                int px = left;
                while (px <= right) {
                    while (px <= right && (seen(px, adjacentY) || !matches(px, adjacentY))) ++px;
                    if (px <= right) {
                        pending.emplace_back(px, adjacentY);
                        while (px <= right && !seen(px, adjacentY) && matches(px, adjacentY)) ++px;
                    }
                }
            }
        }
        *outX = *outY = *outWidth = *outHeight = 0;
        if (found) {
            *outX = minX; *outY = minY;
            *outWidth = maxX - minX + 1; *outHeight = maxY - minY + 1;
        }
        return 1;
    } catch (...) {
        return 0;
    }
}

int cs_selection_combine(uint8_t* destination, const uint8_t* candidate,
                         int width, int height, int destinationStride,
                         int candidateStride, int operation)
{
    if (!destination || !candidate || width <= 0 || height <= 0 ||
        destinationStride < width * 4 || candidateStride < width * 4 ||
        operation < 0 || operation > 3)
        return 0;
    QImage target(destination, width, height, destinationStride, QImage::Format_ARGB32);
    const QImage source(candidate, width, height, candidateStride, QImage::Format_ARGB32);
    if (operation == 0) {
        for (int y = 0; y < height; ++y)
            std::memcpy(destination + y * destinationStride,
                        candidate + y * candidateStride, width * 4);
        return 1;
    }
    QPainter painter(&target);
    const QPainter::CompositionMode modes[] = {
        QPainter::CompositionMode_Source,
        QPainter::CompositionMode_SourceOver,
        QPainter::CompositionMode_DestinationOut,
        QPainter::CompositionMode_DestinationIn,
    };
    painter.setCompositionMode(modes[operation]);
    painter.drawImage(0, 0, source);
    painter.end();
    return 1;
}

int cs_selection_invert(uint8_t* pixels, int width, int height, int stride)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4) return 0;
    QImage image(pixels, width, height, stride, QImage::Format_ARGB32);
    for (int y = 0; y < height; ++y) {
        auto* row = reinterpret_cast<QRgb*>(image.scanLine(y));
        for (int x = 0; x < width; ++x) row[x] = qRgba(255, 255, 255, 255 - qAlpha(row[x]));
    }
    return 1;
}

int cs_selection_bounds(const uint8_t* pixels, int width, int height, int stride,
                        int* x, int* y, int* boundsWidth, int* boundsHeight)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4 ||
        !x || !y || !boundsWidth || !boundsHeight) return 0;
    QImage image(const_cast<uint8_t*>(pixels), width, height, stride, QImage::Format_ARGB32);
    int left = width, top = height, right = -1, bottom = -1;
    for (int row = 0; row < height; ++row) {
        const auto* scan = reinterpret_cast<const QRgb*>(image.constScanLine(row));
        for (int column = 0; column < width; ++column) {
            if (qAlpha(scan[column]) == 0) continue;
            left = std::min(left, column); right = std::max(right, column);
            top = std::min(top, row); bottom = std::max(bottom, row);
        }
    }
    if (right < left) { *x = *y = *boundsWidth = *boundsHeight = 0; return 1; }
    *x = left; *y = top; *boundsWidth = right - left + 1; *boundsHeight = bottom - top + 1;
    return 1;
}

int cs_selection_contains(const uint8_t* pixels, int width, int height, int stride,
                          int x, int y, int* selected)
{
    if (!pixels || width <= 0 || height <= 0 || stride < width * 4 || !selected)
        return 0;
    if (x < 0 || x >= width || y < 0 || y >= height) { *selected = 0; return 1; }
    QImage image(const_cast<uint8_t*>(pixels), width, height, stride, QImage::Format_ARGB32);
    *selected = qAlpha(image.pixel(x, y)) > 0 ? 1 : 0;
    return 1;
}

int cs_selection_shape_mask(uint8_t* output, int width, int height, int stride,
                            int shape, const float* pointsXY, int pointCount)
{
    if (!output || width <= 0 || height <= 0 || stride < width * 4 ||
        shape < 0 || shape > 2 || pointCount < 0 || pointCount > 1000000 ||
        (pointCount > 0 && !pointsXY)) return 0;
    QImage mask(output, width, height, stride, QImage::Format_ARGB32);
    mask.fill(Qt::transparent);
    if (pointCount == 0) return 1;
    for (int index = 0; index < pointCount * 2; ++index)
        if (!std::isfinite(pointsXY[index])) return 0;

    QPainter painter(&mask);
    if (!painter.isActive()) return 0;
    painter.setRenderHint(QPainter::Antialiasing, false);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(255, 255, 255, 255));
    if (shape == 0 || shape == 1) {
        const QPointF first(pointsXY[0], pointsXY[1]);
        const QPointF last(pointsXY[(pointCount - 1) * 2],
                           pointsXY[(pointCount - 1) * 2 + 1]);
        const QRectF bounds(first, last);
        if (shape == 0) painter.drawRect(bounds.normalized());
        else painter.drawEllipse(bounds.normalized());
    } else if (pointCount >= 3) {
        QPainterPath path(QPointF(pointsXY[0], pointsXY[1]));
        for (int index = 1; index < pointCount; ++index)
            path.lineTo(QPointF(pointsXY[index * 2], pointsXY[index * 2 + 1]));
        path.closeSubpath();
        painter.drawPath(path);
    }
    painter.end();
    return 1;
}

int cs_shape_path(int shape, double startX, double startY,
                  double endX, double endY, double* outputXY,
                  int pointCapacity, int* pointCount)
{
    if (shape < 0 || shape > 2 || !std::isfinite(startX) ||
        !std::isfinite(startY) || !std::isfinite(endX) ||
        !std::isfinite(endY) || !outputXY || !pointCount || pointCapacity < 2)
        return 0;
    std::vector<QPointF> points;
    const QPointF start(startX, startY), end(endX, endY);
    if (shape == 0) {
        points = {start, end};
    } else {
        const QRectF bounds = QRectF(start, end).normalized();
        if (shape == 1) {
            points = {bounds.topLeft(), bounds.topRight(), bounds.bottomRight(),
                      bounds.bottomLeft(), bounds.topLeft()};
        } else {
            constexpr double pi = 3.14159265358979323846;
            const double radiusX = bounds.width() / 2.0;
            const double radiusY = bounds.height() / 2.0;
            const QPointF center = bounds.center();
            const double circumference = (radiusX > 0.0 && radiusY > 0.0)
                ? pi * (3.0 * (radiusX + radiusY) -
                    std::sqrt((3.0 * radiusX + radiusY) *
                              (radiusX + 3.0 * radiusY)))
                : 0.0;
            const int count = std::max(16, std::min(720,
                static_cast<int>(std::ceil(circumference / 3.0))));
            points.reserve(static_cast<size_t>(count + 1));
            for (int index = 0; index < count; ++index) {
                const double angle = 2.0 * pi * index / count;
                points.emplace_back(center.x() + radiusX * std::cos(angle),
                                    center.y() + radiusY * std::sin(angle));
            }
            points.push_back(points.front());
        }
    }
    if (static_cast<int>(points.size()) > pointCapacity) return 0;
    for (size_t index = 0; index < points.size(); ++index) {
        outputXY[index * 2] = points[index].x();
        outputXY[index * 2 + 1] = points[index].y();
    }
    *pointCount = static_cast<int>(points.size());
    return 1;
}

int cs_crop_rect(int startX, int startY, int endX, int endY,
                 int boundsX, int boundsY, int boundsWidth, int boundsHeight,
                 int* cropX, int* cropY, int* cropWidth, int* cropHeight)
{
    if (!cropX || !cropY || !cropWidth || !cropHeight ||
        boundsWidth <= 0 || boundsHeight <= 0) return 0;
    const int64_t boundsRight = static_cast<int64_t>(boundsX) + boundsWidth - 1;
    const int64_t boundsBottom = static_cast<int64_t>(boundsY) + boundsHeight - 1;
    const int64_t left = std::max<int64_t>(boundsX, std::min(startX, endX));
    const int64_t top = std::max<int64_t>(boundsY, std::min(startY, endY));
    const int64_t right = std::min<int64_t>(boundsRight, std::max(startX, endX));
    const int64_t bottom = std::min<int64_t>(boundsBottom, std::max(startY, endY));
    if (right < left || bottom < top) {
        *cropX = *cropY = *cropWidth = *cropHeight = 0;
        return 1;
    }
    *cropX = static_cast<int>(left);
    *cropY = static_cast<int>(top);
    *cropWidth = static_cast<int>(right - left + 1);
    *cropHeight = static_cast<int>(bottom - top + 1);
    return 1;
}

int cs_crop_image(const uint8_t* source, int sourceWidth, int sourceHeight,
                  int sourceStride, int sourceFormat, int cropX, int cropY,
                  int cropWidth, int cropHeight, uint8_t* output,
                  int outputStride, int outputFormat)
{
    const auto validFormat = [](int format) {
        return format == QImage::Format_ARGB32 ||
               format == QImage::Format_RGBA8888;
    };
    if (!source || !output || sourceWidth <= 0 || sourceHeight <= 0 ||
        sourceStride < sourceWidth * 4 || cropX < 0 || cropY < 0 ||
        cropWidth <= 0 || cropHeight <= 0 || cropX + cropWidth > sourceWidth ||
        cropY + cropHeight > sourceHeight || outputStride < cropWidth * 4 ||
        !validFormat(sourceFormat) || !validFormat(outputFormat)) return 0;
    const QImage input(const_cast<uint8_t*>(source), sourceWidth, sourceHeight,
                       sourceStride, static_cast<QImage::Format>(sourceFormat));
    const QImage cropped = input.copy(QRect(cropX, cropY, cropWidth, cropHeight))
                               .convertToFormat(static_cast<QImage::Format>(outputFormat));
    if (cropped.isNull()) return 0;
    for (int row = 0; row < cropHeight; ++row) {
        std::memcpy(output + row * outputStride,
                    cropped.constScanLine(row), static_cast<size_t>(cropWidth) * 4);
    }
    return 1;
}

int cs_copy_image_rect(const uint8_t* source, int sourceWidth, int sourceHeight,
                       int sourceStride, int sourceFormat, int sourceX,
                       int sourceY, uint8_t* destination, int destinationWidth,
                       int destinationHeight, int destinationStride,
                       int destinationFormat, int destinationX, int destinationY,
                       int copyWidth, int copyHeight)
{
    const auto validFormat = [](int format) {
        return format == QImage::Format_ARGB32 ||
               format == QImage::Format_RGBA8888;
    };
    if (!source || !destination || sourceWidth <= 0 || sourceHeight <= 0 ||
        destinationWidth <= 0 || destinationHeight <= 0 || copyWidth <= 0 ||
        copyHeight <= 0 || sourceStride < sourceWidth * 4 ||
        destinationStride < destinationWidth * 4 || sourceX < 0 || sourceY < 0 ||
        destinationX < 0 || destinationY < 0 ||
        sourceX + copyWidth > sourceWidth || sourceY + copyHeight > sourceHeight ||
        destinationX + copyWidth > destinationWidth ||
        destinationY + copyHeight > destinationHeight ||
        !validFormat(sourceFormat) || !validFormat(destinationFormat)) return 0;

    const QImage input(const_cast<uint8_t*>(source), sourceWidth, sourceHeight,
                       sourceStride, static_cast<QImage::Format>(sourceFormat));
    QImage output(destination, destinationWidth, destinationHeight,
                  destinationStride, static_cast<QImage::Format>(destinationFormat));
    if (input.format() == output.format()) {
        for (int row = 0; row < copyHeight; ++row) {
            std::memcpy(output.scanLine(destinationY + row) + destinationX * 4,
                        input.constScanLine(sourceY + row) + sourceX * 4,
                        static_cast<size_t>(copyWidth) * 4);
        }
        return 1;
    }
    const QImage patch = input.copy(QRect(sourceX, sourceY, copyWidth, copyHeight))
                             .convertToFormat(output.format());
    if (patch.isNull()) return 0;
    QPainter painter(&output);
    painter.setCompositionMode(QPainter::CompositionMode_Source);
    painter.drawImage(destinationX, destinationY, patch);
    return painter.isActive() ? 1 : 0;
}

int cs_draw_text(uint8_t* image, int width, int height, int stride, int imageFormat,
                 const char* textUtf8, const char* fontSerializedUtf8,
                 double x, double y, int red, int green, int blue, int alpha)
{
    if (!image || !textUtf8 || !fontSerializedUtf8 || width <= 0 || height <= 0 ||
        stride < width * 4) return 0;
    const QImage::Format format = static_cast<QImage::Format>(imageFormat);
    if (format != QImage::Format_ARGB32 && format != QImage::Format_RGBA8888 &&
        format != QImage::Format_ARGB32_Premultiplied &&
        format != QImage::Format_RGBA8888_Premultiplied) return 0;
    QImage target(image, width, height, stride, format);
    QFont font;
    if (!font.fromString(QString::fromUtf8(fontSerializedUtf8))) return 0;
    QPainter painter(&target);
    painter.setFont(font);
    painter.setPen(QColor(std::clamp(red, 0, 255), std::clamp(green, 0, 255),
                          std::clamp(blue, 0, 255), std::clamp(alpha, 0, 255)));
    painter.drawText(QPointF(x, y + QFontMetricsF(font).ascent()),
                     QString::fromUtf8(textUtf8));
    return painter.isActive() ? 1 : 0;
}

int cs_tile_range_for_rect(int canvasWidth, int canvasHeight, int tileSize,
                           int rectX, int rectY, int rectWidth, int rectHeight,
                           int* firstTileX, int* firstTileY,
                           int* endTileX, int* endTileY)
{
    if (!firstTileX || !firstTileY || !endTileX || !endTileY ||
        canvasWidth <= 0 || canvasHeight <= 0 || tileSize <= 0 ||
        rectWidth < 0 || rectHeight < 0) return 0;
    *firstTileX = *firstTileY = *endTileX = *endTileY = 0;
    if (rectWidth == 0 || rectHeight == 0) return 1;
    const int64_t left = std::max<int64_t>(0, rectX);
    const int64_t top = std::max<int64_t>(0, rectY);
    const int64_t right = std::min<int64_t>(canvasWidth,
        static_cast<int64_t>(rectX) + rectWidth);
    const int64_t bottom = std::min<int64_t>(canvasHeight,
        static_cast<int64_t>(rectY) + rectHeight);
    if (right <= left || bottom <= top) return 1;
    *firstTileX = static_cast<int>(left / tileSize);
    *firstTileY = static_cast<int>(top / tileSize);
    *endTileX = static_cast<int>((right + tileSize - 1) / tileSize);
    *endTileY = static_cast<int>((bottom + tileSize - 1) / tileSize);
    return 1;
}

int cs_transform_layer(const uint8_t* sourcePixels, const uint8_t* selectionPixels,
                       int width, int height, int sourceStride, int selectionStride,
                       int imageFormat, uint8_t* outputPixels, int outputStride,
                       uint8_t* outputSelectionPixels, int outputSelectionStride,
                       float translateX, float translateY, float scaleX, float scaleY,
                       float rotationDegrees, int* usedSelection)
{
    if (!sourcePixels || !outputPixels || !usedSelection || width <= 0 || height <= 0 ||
        sourceStride < width * 4 || outputStride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888) ||
        (selectionPixels && (!outputSelectionPixels || selectionStride < width * 4 ||
                             outputSelectionStride < width * 4))) return 0;
    QImage sourceView(const_cast<uint8_t*>(sourcePixels), width, height, sourceStride,
                      static_cast<QImage::Format>(imageFormat));
    const QImage source = sourceView.convertToFormat(QImage::Format_ARGB32).copy();
    QImage output(outputPixels, width, height, outputStride, QImage::Format_ARGB32);
    QImage selectionView;
    QImage selection;
    bool hasSelection = false;
    int left = width, top = height, right = -1, bottom = -1;
    if (selectionPixels) {
        selectionView = QImage(const_cast<uint8_t*>(selectionPixels), width, height,
                               selectionStride, QImage::Format_ARGB32);
        selection = selectionView.copy();
        for (int y = 0; y < height; ++y) {
            const auto* row = reinterpret_cast<const QRgb*>(selection.constScanLine(y));
            for (int x = 0; x < width; ++x) {
                if (qAlpha(row[x]) == 0) continue;
                hasSelection = true;
                left = std::min(left, x); right = std::max(right, x);
                top = std::min(top, y); bottom = std::max(bottom, y);
            }
        }
    }
    *usedSelection = hasSelection ? 1 : 0;

    QImage transformSource(width, height, QImage::Format_ARGB32);
    transformSource.fill(Qt::transparent);
    if (hasSelection) {
        output.fill(Qt::transparent);
        for (int y = 0; y < height; ++y) {
            const auto* sourceRow = reinterpret_cast<const QRgb*>(source.constScanLine(y));
            const auto* maskRow = reinterpret_cast<const QRgb*>(selection.constScanLine(y));
            auto* outputRow = reinterpret_cast<QRgb*>(output.scanLine(y));
            auto* transformRow = reinterpret_cast<QRgb*>(transformSource.scanLine(y));
            for (int x = 0; x < width; ++x) {
                if (qAlpha(maskRow[x]) == 0) outputRow[x] = sourceRow[x];
                else {
                    transformRow[x] = sourceRow[x];
                    outputRow[x] = qRgba(0, 0, 0, 0);
                }
            }
        }
    } else {
        transformSource = source;
        output.fill(Qt::transparent);
    }

    const QRectF bounds = hasSelection
        ? QRectF(left, top, right - left + 1, bottom - top + 1)
        : QRectF(0, 0, width, height);
    const QPointF center = bounds.center();
    QTransform transform;
    transform.translate(center.x() + translateX, center.y() + translateY);
    transform.rotate(rotationDegrees);
    transform.scale(scaleX, scaleY);
    transform.translate(-center.x(), -center.y());

    QPainter imagePainter(&output);
    imagePainter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    imagePainter.setTransform(transform);
    imagePainter.drawImage(0, 0, transformSource);
    imagePainter.end();

    if (selectionPixels && outputSelectionPixels) {
        QImage transformedMask(outputSelectionPixels, width, height,
                               outputSelectionStride, QImage::Format_ARGB32);
        transformedMask.fill(Qt::transparent);
        if (hasSelection) {
            QPainter maskPainter(&transformedMask);
            maskPainter.setTransform(transform);
            maskPainter.drawImage(0, 0, selection);
            maskPainter.end();
        }
    }
    return 1;
}

int cs_translate_image(const uint8_t* sourcePixels, int width, int height,
                       int sourceStride, int imageFormat, uint8_t* outputPixels,
                       int outputStride, int dx, int dy)
{
    if (!sourcePixels || !outputPixels || width <= 0 || height <= 0 ||
        sourceStride < width * 4 || outputStride < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888))
        return 0;
    QImage source(const_cast<uint8_t*>(sourcePixels), width, height, sourceStride,
                  static_cast<QImage::Format>(imageFormat));
    QImage output(outputPixels, width, height, outputStride,
                  static_cast<QImage::Format>(imageFormat));
    output.fill(Qt::transparent);
    const long long left = std::max(0LL, static_cast<long long>(dx));
    const long long top = std::max(0LL, static_cast<long long>(dy));
    const long long right = std::min(static_cast<long long>(width),
                                     static_cast<long long>(width) + dx);
    const long long bottom = std::min(static_cast<long long>(height),
                                      static_cast<long long>(height) + dy);
    if (right <= left || bottom <= top) return 1;
    const int copyWidth = static_cast<int>(right - left);
    const size_t bytes = static_cast<size_t>(copyWidth) * 4;
    for (int y = static_cast<int>(top); y < bottom; ++y) {
        const int sourceY = y - dy;
        const int sourceX = static_cast<int>(left) - dx;
        std::memcpy(output.scanLine(y) + static_cast<int>(left) * 4,
                    source.constScanLine(sourceY) + sourceX * 4, bytes);
    }
    return 1;
}

int cs_magic_wand(
    const uint8_t* pixels, int width, int height, int bytesPerLine, int imageFormat,
    int startX, int startY, int tolerance,
    uint8_t* maskArgb32, int maskBytesPerLine)
{
    if (!pixels || !maskArgb32 || width <= 0 || height <= 0 ||
        bytesPerLine < width * 4 || maskBytesPerLine < width * 4 ||
        (imageFormat != QImage::Format_ARGB32 && imageFormat != QImage::Format_RGBA8888) ||
        startX < 0 || startX >= width || startY < 0 || startY >= height)
        return 0;

    try {
        QImage image(const_cast<uint8_t*>(pixels), width, height, bytesPerLine, static_cast<QImage::Format>(imageFormat));
        QImage mask(maskArgb32, width, height, maskBytesPerLine, QImage::Format_ARGB32);
        mask.fill(0);
        tolerance = std::clamp(tolerance, 0, 255);
        const QRgb target = image.pixel(startX, startY);
        auto matches = [&](int x, int y) {
            return withinTolerance(image.pixel(x, y), target, tolerance);
        };
        auto selected = [&](int x, int y) {
            return qAlpha(reinterpret_cast<const QRgb*>(mask.constScanLine(y))[x]) != 0;
        };
        std::deque<QPoint> pending;
        pending.emplace_back(startX, startY);

        while (!pending.empty()) {
            const QPoint seed = pending.back();
            pending.pop_back();
            const int y = seed.y();
            if (!matches(seed.x(), y) || selected(seed.x(), y)) continue;

            int left = seed.x();
            while (left > 0 && matches(left - 1, y) && !selected(left - 1, y)) --left;
            int right = seed.x();
            while (right + 1 < width && matches(right + 1, y) && !selected(right + 1, y)) ++right;
            QRgb* maskRow = reinterpret_cast<QRgb*>(mask.scanLine(y));
            std::fill(maskRow + left, maskRow + right + 1, qRgba(255, 255, 255, 255));

            for (int adjacentY : {y - 1, y + 1}) {
                if (adjacentY < 0 || adjacentY >= height) continue;
                int x = left;
                while (x <= right) {
                    while (x <= right && (!matches(x, adjacentY) || selected(x, adjacentY))) ++x;
                    if (x <= right) {
                        pending.emplace_back(x, adjacentY);
                        while (x <= right && matches(x, adjacentY) && !selected(x, adjacentY)) ++x;
                    }
                }
            }
        }
        return 1;
    } catch (...) {
        return 0;
    }
}


void
cs_brush_set_pressure_size(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.pressureSize = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_pressure_opacity(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.pressureOpacity = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_pressure_flow(
    CreativeBrushHandle handle,
    int enabled
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.pressureFlow = enabled != 0;
    engine->setSettings(settings);
}

void
cs_brush_set_minimum_size(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.minimumSize = value;
    engine->setSettings(settings);
}

void
cs_brush_set_minimum_opacity(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.minimumOpacity = value;
    engine->setSettings(settings);
}

void
cs_brush_set_minimum_flow(
    CreativeBrushHandle handle,
    float value
)
{
    BrushEngine* engine = getEngine(handle);
    if (!engine) return;

    BrushSettings settings = engine->settings();
    settings.minimumFlow = value;
    engine->setSettings(settings);
}
