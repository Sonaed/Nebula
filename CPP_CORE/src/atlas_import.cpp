#include "creative_core_api.h"

#include <QDataStream>
#include <QFile>
#include <QString>
#include <algorithm>
#include <cmath>
#include <array>
#include <functional>
#include <limits>
#include <memory>
#include <vector>
#include <zlib.h>

namespace {
constexpr quint32 kMaxDimension = 100000;
constexpr quint32 kMaxLayers = 4096;
constexpr quint32 kMaxStringBytes = 1u << 20;
constexpr quint64 kMaxLayerBytes = 1ull << 30;

struct BlobRef { quint64 offset = 0; quint32 packed = 0; quint32 raw = 0; };
struct LayerRef {
    QByteArray name, blend;
    float opacity = 1.0f;
    quint8 visible = 1;
    BlobRef pixels, mask;
};
struct AtlasReader {
    QString path;
    QByteArray name, author, background;
    quint32 width = 0, height = 0, dpi = 72;
    quint64 layerBytes = 0;
    std::vector<LayerRef> layers;
};

bool readString(QDataStream& stream, QByteArray& value)
{
    quint32 size = 0;
    stream >> size;
    if (stream.status() != QDataStream::Ok || size > kMaxStringBytes) return false;
    value.resize(static_cast<qsizetype>(size));
    return size == 0 || stream.readRawData(value.data(), static_cast<int>(size)) == static_cast<int>(size);
}

bool skipBlob(QDataStream& stream, BlobRef& blob, quint64 expected,
              quint64 fileSize, quint64& totalDecoded)
{
    stream >> blob.raw >> blob.packed;
    if (stream.status() != QDataStream::Ok || blob.raw > expected ||
        blob.raw > kMaxLayerBytes || blob.packed > kMaxLayerBytes ||
        (blob.raw && !blob.packed)) return false;
    blob.offset = static_cast<quint64>(stream.device()->pos());
    if (blob.offset > fileSize || blob.packed > fileSize - blob.offset) return false;
    totalDecoded += blob.raw;
    if (totalDecoded > (8ull << 30)) return false;
    return stream.device()->seek(static_cast<qint64>(blob.offset + blob.packed));
}

bool copyString(const QByteArray& value, char* output, uint32_t capacity)
{
    if (!output || !capacity || static_cast<quint64>(value.size()) + 1 > capacity) return false;
    std::copy(value.cbegin(), value.cend(), output);
    output[value.size()] = '\0';
    return true;
}

bool inflateBlob(QFile& file, const BlobRef& blob,
                 const std::function<bool(const uint8_t*, std::size_t, quint64)>& sink)
{
    if (blob.packed > static_cast<quint32>(std::numeric_limits<int>::max()) ||
        !file.seek(static_cast<qint64>(blob.offset))) return false;
    z_stream state{};
    if (inflateInit(&state) != Z_OK) return false;
    std::array<uint8_t, 64 * 1024> input{}, output{};
    quint64 bytesRemaining = blob.packed;
    quint64 outputOffset = 0;
    int status = Z_OK;
    while (status != Z_STREAM_END) {
        if (state.avail_in == 0 && bytesRemaining) {
            const auto count = static_cast<qint64>(std::min<quint64>(bytesRemaining, input.size()));
            if (file.read(reinterpret_cast<char*>(input.data()), count) != count) {
                inflateEnd(&state);
                return false;
            }
            bytesRemaining -= static_cast<quint64>(count);
            state.next_in = input.data();
            state.avail_in = static_cast<uInt>(count);
        }
        state.next_out = output.data();
        state.avail_out = static_cast<uInt>(output.size());
        status = inflate(&state, Z_NO_FLUSH);
        const std::size_t produced = output.size() - state.avail_out;
        if (outputOffset + produced > blob.raw ||
            (produced && !sink(output.data(), produced, outputOffset))) {
            inflateEnd(&state);
            return false;
        }
        outputOffset += produced;
        if (status != Z_OK && status != Z_STREAM_END) {
            inflateEnd(&state);
            return false;
        }
        if (status == Z_OK && state.avail_in == 0 && bytesRemaining == 0 && produced == 0) {
            inflateEnd(&state);
            return false;
        }
    }
    const bool valid = outputOffset == blob.raw && bytesRemaining == 0 && state.avail_in == 0;
    inflateEnd(&state);
    return valid;
}

std::unique_ptr<AtlasReader> parseAtlas(const char* path)
{
    if (!path || !*path) return {};
    auto result = std::make_unique<AtlasReader>();
    result->path = QString::fromUtf8(path);
    QFile file(result->path);
    if (!file.open(QIODevice::ReadOnly) || file.size() < 44) return {};
    QDataStream stream(&file);
    stream.setByteOrder(QDataStream::LittleEndian);
    char magic[4]{};
    quint32 version = 0;
    if (stream.readRawData(magic, 4) != 4 || QByteArray(magic, 4) != "ATLS") return {};
    stream >> version;
    if (version != 2 && version != 3) return {};
    QByteArray appVersion;
    if (!readString(stream, result->name) || !readString(stream, result->author) ||
        !readString(stream, appVersion)) return {};
    stream >> result->width >> result->height;
    if (version == 3) {
        stream >> result->dpi;
        if (!readString(stream, result->background)) return {};
    }
    // The existing ATLS v2/v3 writer stores four native little-endian doubles.
    if (stream.status() != QDataStream::Ok || !result->width || !result->height ||
        result->width > kMaxDimension || result->height > kMaxDimension ||
        !result->dpi || result->dpi > 10000 ||
        !stream.device()->seek(stream.device()->pos() + 4 * sizeof(double))) return {};
    quint32 count = 0;
    stream >> count;
    if (stream.status() != QDataStream::Ok || !count || count > kMaxLayers) return {};
    const quint64 expected = quint64(result->width) * result->height * 4;
    if (expected > kMaxLayerBytes) return {};
    quint64 decoded = 0;
    result->layers.reserve(count);
    for (quint32 index = 0; index < count; ++index) {
        LayerRef layer;
        if (!readString(stream, layer.name) ||
            stream.readRawData(reinterpret_cast<char*>(&layer.opacity), 4) != 4 ||
            stream.readRawData(reinterpret_cast<char*>(&layer.visible), 1) != 1) return {};
        if (!readString(stream, layer.blend) || !std::isfinite(layer.opacity) ||
            layer.opacity < 0.0f || layer.opacity > 1.0f ||
            !skipBlob(stream, layer.pixels, expected, file.size(), decoded) ||
            !skipBlob(stream, layer.mask, expected, file.size(), decoded) ||
            (layer.pixels.raw && layer.pixels.raw != expected) ||
            (layer.mask.raw && layer.mask.raw != expected)) return {};
        result->layers.push_back(std::move(layer));
    }
    result->layerBytes = expected;
    return result;
}
} // namespace

CreativeAtlasReaderHandle cs_atlas_reader_open(const char* path)
{ return parseAtlas(path).release(); }

int cs_atlas_reader_document_info(CreativeAtlasReaderHandle handle,
    char* name, uint32_t nameCapacity, char* author, uint32_t authorCapacity,
    uint32_t* width, uint32_t* height,
    uint32_t* dpi, uint32_t* layerCount, char* background, uint32_t backgroundCapacity)
{
    auto* reader = static_cast<AtlasReader*>(handle);
    if (!reader || !width || !height || !dpi || !layerCount ||
        !copyString(reader->name, name, nameCapacity) ||
        !copyString(reader->author, author, authorCapacity) ||
        !copyString(reader->background, background, backgroundCapacity)) return 0;
    *width = reader->width; *height = reader->height; *dpi = reader->dpi;
    *layerCount = static_cast<uint32_t>(reader->layers.size());
    return 1;
}

int cs_atlas_reader_layer_info(CreativeAtlasReaderHandle handle, uint32_t index,
    char* name, uint32_t nameCapacity, float* opacity, int* visible,
    char* blend, uint32_t blendCapacity)
{
    auto* reader = static_cast<AtlasReader*>(handle);
    if (!reader || index >= reader->layers.size() || !opacity || !visible) return 0;
    const auto& layer = reader->layers[index];
    if (!copyString(layer.name, name, nameCapacity) ||
        !copyString(layer.blend, blend, blendCapacity)) return 0;
    *opacity = layer.opacity; *visible = layer.visible != 0;
    return 1;
}

int cs_atlas_reader_copy_layer(CreativeAtlasReaderHandle handle, uint32_t index,
    uint8_t* rgba, uint64_t capacity)
{
    auto* reader = static_cast<AtlasReader*>(handle);
    if (!reader || index >= reader->layers.size() || !rgba ||
        capacity < reader->layerBytes || reader->layerBytes > kMaxLayerBytes) return 0;
    QFile file(reader->path);
    if (!file.open(QIODevice::ReadOnly)) return 0;
    const auto& layer = reader->layers[index];
    std::fill(rgba, rgba + reader->layerBytes, 0);
    if (!inflateBlob(file, layer.pixels,
        [rgba](const uint8_t* block, std::size_t size, quint64 offset) {
            std::copy(block, block + size, rgba + offset);
            return true;
        })) return 0;
    // Atlas writes an RGBA mask; apply its alpha in bounded chunks instead of
    // allocating a second full-document bitmap alongside the pixel buffer.
    if (!inflateBlob(file, layer.mask,
        [rgba](const uint8_t* block, std::size_t size, quint64 offset) {
            for (std::size_t i = 0; i < size; ++i) {
                const quint64 position = offset + i;
                if ((position & 3u) == 3u)
                    rgba[position] = static_cast<uint8_t>(
                        (unsigned(rgba[position]) * block[i] + 127u) / 255u);
            }
            return true;
        })) return 0;
    return 1;
}

void cs_atlas_reader_close(CreativeAtlasReaderHandle handle)
{ delete static_cast<AtlasReader*>(handle); }
