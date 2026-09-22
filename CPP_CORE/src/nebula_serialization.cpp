#include "creative_core_api.h"

#include <QDataStream>
#include <QFile>
#include <QSaveFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QSet>
#include <QtCore/qbytearray.h>
#include <QtCore/qglobal.h>

#include <algorithm>
#include <memory>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>

namespace {
constexpr quint16 kNebulaVersion = 1;
constexpr quint32 kMaxMetadata = 64u * 1024u * 1024u;
constexpr quint32 kMaxChunks = 1'000'000u;
constexpr quint64 kMaxTileBytes = 64u * 64u * 4u;
constexpr quint64 kMaxPackedBytes = 64u * 1024u;
constexpr qsizetype kFileHeaderBytes = 16;
constexpr int kTileSize = 64;
constexpr quint32 kMaxReferences = 256;
constexpr int kMaxDocumentDimension = 100000;

bool integerValue(const QJsonValue& value, qint64& result) {
    if (!value.isDouble()) return false;
    const double number = value.toDouble();
    if (!std::isfinite(number) || std::floor(number) != number ||
        number < static_cast<double>(std::numeric_limits<qint64>::min()) ||
        number > static_cast<double>(std::numeric_limits<qint64>::max())) return false;
    result = static_cast<qint64>(number);
    return true;
}

bool finiteNumber(const QJsonValue& value) {
    return value.isDouble() && std::isfinite(value.toDouble());
}

bool finiteNumberObject(const QJsonValue& value) {
    if (!value.isObject()) return false;
    const QJsonObject object = value.toObject();
    for (auto it = object.begin(); it != object.end(); ++it)
        if (!finiteNumber(it.value())) return false;
    return true;
}

bool validTileManifest(const QJsonObject& root, quint32 expectedChunkCount,
                       qint64 width, qint64 height) {
    const QJsonArray layers = root.value("layers").toArray();
    const QJsonArray references = root.value("references").toArray();
    const QJsonArray records = root.value("chunks").toArray();
    if (!root.value("layers").isArray() || layers.isEmpty() ||
        layers.size() > 100000 || !root.value("chunks").isArray() ||
        records.size() != static_cast<qsizetype>(expectedChunkCount) ||
        expectedChunkCount > kMaxChunks || references.size() > kMaxReferences)
        return false;

    struct Owner { int role; qint64 index; };
    std::unordered_map<quint32, Owner> tileOwners;
    tileOwners.reserve(static_cast<size_t>(records.size()));
    for (const QJsonValue& value : records) {
        if (!value.isObject()) return false;
        const QJsonObject record = value.toObject();
        qint64 id = 0, owner = 0, tx = 0, ty = 0, tileWidth = 0, tileHeight = 0;
        if (!integerValue(record.value("id"), id) || id <= 0 || id > UINT32_MAX ||
            !integerValue(record.value("owner"), owner) ||
            !integerValue(record.value("x"), tx) || !integerValue(record.value("y"), ty) ||
            !integerValue(record.value("width"), tileWidth) ||
            !integerValue(record.value("height"), tileHeight)) return false;
        int role = -1;
        qint64 surfaceWidth = width, surfaceHeight = height;
        const QJsonValue roleValue = record.value("role");
        if (!roleValue.isString()) return false;
        const QString roleName = roleValue.toString();
        if (roleName == QLatin1String("layer") ||
            roleName == QLatin1String("layer_mask")) {
            role = 0;
            if (owner < 0 || owner >= layers.size()) return false;
        } else if (roleName == QLatin1String("selection")) {
            role = 1;
            if (owner != 0) return false;
        } else if (roleName == QLatin1String("reference")) {
            role = 2;
            if (owner < 0 || owner >= references.size() ||
                !references[static_cast<qsizetype>(owner)].isObject()) return false;
            const QJsonObject reference = references[static_cast<qsizetype>(owner)].toObject();
            if (!integerValue(reference.value("width"), surfaceWidth) ||
                !integerValue(reference.value("height"), surfaceHeight) ||
                surfaceWidth <= 0 || surfaceHeight <= 0 ||
                surfaceWidth > kMaxDocumentDimension || surfaceHeight > kMaxDocumentDimension)
                return false;
        } else {
            return false;
        }
        if (tx < 0 || ty < 0 || tx >= (surfaceWidth + kTileSize - 1) / kTileSize ||
            ty >= (surfaceHeight + kTileSize - 1) / kTileSize ||
            tileWidth != std::min<qint64>(kTileSize, surfaceWidth - tx * kTileSize) ||
            tileHeight != std::min<qint64>(kTileSize, surfaceHeight - ty * kTileSize))
            return false;
        if (!tileOwners.emplace(static_cast<quint32>(id), Owner{role, owner}).second)
            return false;
    }
    if (tileOwners.size() != expectedChunkCount) return false;

    bool completeIndex = root.contains("selection_tiles");
    for (const QJsonValue& value : layers)
        completeIndex = completeIndex && value.isObject() && value.toObject().contains("tiles");
    for (const QJsonValue& value : references)
        completeIndex = completeIndex && value.isObject() && value.toObject().contains("tiles");
    if (!completeIndex) return true; // Compatibility with older schema-1 manifests.

    std::unordered_map<quint32, Owner> declarations;
    declarations.reserve(tileOwners.size());
    auto registerIds = [&declarations](const QJsonValue& value, int role,
                                       qint64 owner) {
        if (!value.isArray()) return false;
        for (const QJsonValue& idValue : value.toArray()) {
            qint64 id = 0;
            if (!integerValue(idValue, id) || id <= 0 || id > UINT32_MAX ||
                !declarations.emplace(static_cast<quint32>(id), Owner{role, owner}).second)
                return false;
        }
        return true;
    };
    for (qsizetype i = 0; i < layers.size(); ++i) {
        if (!registerIds(layers[i].toObject().value("tiles"), 0, i)) return false;
        QJsonValue maskIds = layers[i].toObject().value("mask_tiles");
        if (maskIds.isUndefined()) maskIds = QJsonArray{};
        if (!registerIds(maskIds, 0, i)) return false;
    }
    QJsonValue selectionIds = root.value("selection_tiles");
    if (selectionIds.isNull()) selectionIds = QJsonArray{};
    if (!registerIds(selectionIds, 1, 0)) return false;
    for (qsizetype i = 0; i < references.size(); ++i)
        if (!registerIds(references[i].toObject().value("tiles"), 2, i)) return false;
    if (declarations.size() != tileOwners.size()) return false;
    for (const auto& [id, owner] : tileOwners) {
        const auto declared = declarations.find(id);
        if (declared == declarations.end() || declared->second.role != owner.role ||
            declared->second.index != owner.index) return false;
    }
    return true;
}

bool validNebulaManifest(const QByteArray& bytes, quint32 expectedChunkCount,
                         int* outputWidth, int* outputHeight, int* outputDpi) {
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(bytes, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) return false;
    const QJsonObject root = document.object();
    qint64 width = 0, height = 0, dpi = 300;
    if (!integerValue(root.value("width"), width) ||
        !integerValue(root.value("height"), height) ||
        (root.contains("dpi") && !integerValue(root.value("dpi"), dpi)) ||
        width <= 0 || height <= 0 || dpi < 1 || dpi > 9600 ||
        width > kMaxDocumentDimension || height > kMaxDocumentDimension ||
        width * height > 64ll * 1024 * 1024) return false;

    const QJsonValue layersValue = root.value("layers");
    if (!layersValue.isArray()) return false;
    const QJsonArray layers = layersValue.toArray();
    if (layers.isEmpty() || layers.size() > 100000) return false;
    QSet<QString> layerIds;
    for (const QJsonValue& value : layers) {
        if (!value.isObject()) return false;
        const QJsonObject layer = value.toObject();
        if (layer.contains("id")) {
            if (!layer.value("id").isString()) return false;
            const QString id = layer.value("id").toString();
            if (!id.isEmpty() && layerIds.contains(id)) return false;
            if (!id.isEmpty()) layerIds.insert(id);
        }
        if ((layer.contains("blend_parameters") &&
             !finiteNumberObject(layer.value("blend_parameters"))) ||
            (layer.contains("opacity") && !finiteNumber(layer.value("opacity"))))
            return false;
    }

    const QJsonValue referencesValue = root.value("references");
    if (!referencesValue.isUndefined() && !referencesValue.isArray()) return false;
    const QJsonArray references = referencesValue.toArray();
    if (references.size() > kMaxReferences) return false;
    qint64 referencePixels = 0;
    for (const QJsonValue& value : references) {
        if (!value.isObject()) return false;
        const QJsonObject reference = value.toObject();
        qint64 imageWidth = 0, imageHeight = 0;
        if (!integerValue(reference.value("width"), imageWidth) ||
            !integerValue(reference.value("height"), imageHeight) ||
            imageWidth <= 0 || imageHeight <= 0 ||
            imageWidth > kMaxDocumentDimension || imageHeight > kMaxDocumentDimension)
            return false;
        referencePixels += imageWidth * imageHeight;
        if (referencePixels > 64ll * 1024 * 1024) return false;
        for (const auto& field : {qMakePair(QLatin1String("x"), 0.0),
                                  qMakePair(QLatin1String("y"), 0.0),
                                  qMakePair(QLatin1String("scale"), 1.0),
                                  qMakePair(QLatin1String("opacity"), 0.8)})
            if (reference.contains(field.first) &&
                !finiteNumber(reference.value(field.first))) return false;
    }

    const QJsonValue textsValue = root.value("texts");
    if (!textsValue.isUndefined() && !textsValue.isArray()) return false;
    const QJsonArray texts = textsValue.toArray();
    if (texts.size() > 100000) return false;
    for (const QJsonValue& value : texts) {
        if (!value.isObject()) return false;
        const QJsonObject text = value.toObject();
        for (const char* coordinate : {"x", "y"})
            if (text.contains(QLatin1String(coordinate)) &&
                !finiteNumber(text.value(QLatin1String(coordinate)))) return false;
        const QJsonValue colorValue = text.value("color");
        if (!colorValue.isUndefined()) {
            if (!colorValue.isArray()) return false;
            const QJsonArray color = colorValue.toArray();
            if (color.size() != 3 && color.size() != 4) return false;
            for (const QJsonValue& channel : color)
                if (!finiteNumber(channel)) return false;
        }
    }

    const QJsonValue groupsValue = root.value("layer_groups");
    if (!groupsValue.isUndefined() && !groupsValue.isArray()) return false;
    const QJsonArray groups = groupsValue.toArray();
    if (groups.size() > 100000) return false;
    for (const QJsonValue& value : groups) {
        if (!value.isObject()) return false;
        const QJsonObject group = value.toObject();
        if ((group.contains("layer_ids") && !group.value("layer_ids").isArray()) ||
            (group.contains("blend_parameters") &&
             !finiteNumberObject(group.value("blend_parameters"))) ||
            (group.contains("opacity") && !finiteNumber(group.value("opacity"))))
            return false;
    }

    const QJsonValue background = root.value("background");
    if (!background.isNull() && !background.isUndefined()) {
        if (!background.isArray()) return false;
        const QJsonArray color = background.toArray();
        if (color.size() != 4) return false;
        for (const QJsonValue& channel : color)
            if (!finiteNumber(channel)) return false;
    }
    if (root.contains("blend_presets") && !root.value("blend_presets").isObject())
        return false;
    if (root.contains("active_layer")) {
        qint64 active = 0;
        if (!integerValue(root.value("active_layer"), active)) return false;
    }
    if (!validTileManifest(root, expectedChunkCount, width, height)) return false;
    if (outputWidth) *outputWidth = static_cast<int>(width);
    if (outputHeight) *outputHeight = static_cast<int>(height);
    if (outputDpi) *outputDpi = static_cast<int>(dpi);
    return true;
}

quint32 crc32_bytes(const uint8_t* data, qsizetype size) {
    quint32 crc = 0xFFFFFFFFu;
    for (qsizetype i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

QByteArray make_header(quint32 metadata_size, quint32 chunks) {
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.writeRawData("NEBL", 4);
    stream << kNebulaVersion << quint16(0) << metadata_size << chunks;
    return bytes;
}

struct Writer {
    QSaveFile file;
    quint32 expected = 0;
    quint32 written = 0;
    std::unordered_set<quint32> ids;

    Writer(const QString& path, const QByteArray& metadata, quint32 count)
        : file(path), expected(count) {
        if (metadata.isEmpty() || metadata.size() > kMaxMetadata || count > kMaxChunks ||
            !validNebulaManifest(metadata, count, nullptr, nullptr, nullptr) ||
            !file.open(QIODevice::WriteOnly))
            return;
        const QByteArray header = make_header(static_cast<quint32>(metadata.size()), count);
        if (file.write(header) != header.size() || file.write(metadata) != metadata.size())
            file.cancelWriting();
    }

    bool ready() const { return file.isOpen() && !file.error(); }
};

struct Reader {
    QFile file;
    QByteArray metadata;
    quint32 expected = 0;
    quint32 read = 0;
    std::unordered_set<quint32> ids;
    bool valid = false;

    explicit Reader(const QString& path) : file(path) {
        if (!file.open(QIODevice::ReadOnly) || file.size() < kFileHeaderBytes) return;
        QByteArray header = file.read(kFileHeaderBytes);
        QDataStream stream(header);
        stream.setByteOrder(QDataStream::LittleEndian);
        char magic[4]{};
        quint16 version = 0, flags = 0;
        quint32 metadata_size = 0;
        stream.readRawData(magic, 4);
        stream >> version >> flags >> metadata_size >> expected;
        if (QByteArray(magic, 4) != "NEBL" || version != kNebulaVersion || flags != 0 ||
            metadata_size == 0 || metadata_size > kMaxMetadata || expected > kMaxChunks ||
            file.size() < kFileHeaderBytes + metadata_size)
            return;
        metadata = file.read(metadata_size);
        valid = metadata.size() == metadata_size &&
                (expected != 0 || file.atEnd());
    }
};
} // namespace

extern "C" CreativeNebulaWriterHandle cs_nebula_writer_create(
    const char* path, const uint8_t* metadata, uint32_t metadata_size,
    uint32_t chunk_count) {
    if (!path || !metadata || !metadata_size || metadata_size > kMaxMetadata ||
        chunk_count > kMaxChunks)
        return nullptr;
    try {
        auto writer = std::make_unique<Writer>(QString::fromUtf8(path),
                                               QByteArray(reinterpret_cast<const char*>(metadata),
                                                          static_cast<qsizetype>(metadata_size)),
                                               chunk_count);
        return writer->ready() ? writer.release() : nullptr;
    } catch (...) { return nullptr; }
}

extern "C" int cs_nebula_writer_add_tile(CreativeNebulaWriterHandle handle,
                                           uint32_t chunk_id, const uint8_t* rgba,
                                           uint64_t byte_count) {
    auto* writer = static_cast<Writer*>(handle);
    if (!writer || !writer->ready() || !rgba || byte_count == 0 ||
        byte_count > kMaxTileBytes || writer->written >= writer->expected ||
        chunk_id == 0 || writer->ids.count(chunk_id))
        return 0;
    const QByteArray raw(reinterpret_cast<const char*>(rgba), static_cast<qsizetype>(byte_count));
    const QByteArray packed = qCompress(raw, 3);
    if (packed.isEmpty() || static_cast<quint64>(packed.size()) > kMaxPackedBytes) return 0;
    QByteArray record;
    QDataStream stream(&record, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.writeRawData("TILE", 4);
    stream << chunk_id << static_cast<quint64>(raw.size())
           << static_cast<quint64>(packed.size()) << crc32_bytes(rgba, raw.size());
    if (writer->file.write(record) != record.size() ||
        writer->file.write(packed) != packed.size())
        return 0;
    writer->ids.insert(chunk_id);
    ++writer->written;
    return 1;
}

extern "C" int cs_nebula_writer_finish(CreativeNebulaWriterHandle handle) {
    std::unique_ptr<Writer> writer(static_cast<Writer*>(handle));
    if (!writer || !writer->ready() || writer->written != writer->expected) {
        if (writer) writer->file.cancelWriting();
        return 0;
    }
    return writer->file.commit() ? 1 : 0;
}

extern "C" void cs_nebula_writer_cancel(CreativeNebulaWriterHandle handle) {
    std::unique_ptr<Writer> writer(static_cast<Writer*>(handle));
    if (writer) writer->file.cancelWriting();
}

extern "C" CreativeNebulaReaderHandle cs_nebula_reader_open(const char* path) {
    if (!path) return nullptr;
    try {
        auto reader = std::make_unique<Reader>(QString::fromUtf8(path));
        return reader->valid ? reader.release() : nullptr;
    } catch (...) { return nullptr; }
}

extern "C" uint32_t cs_nebula_reader_metadata_size(CreativeNebulaReaderHandle handle) {
    auto* reader = static_cast<Reader*>(handle);
    return reader && reader->valid ? static_cast<uint32_t>(reader->metadata.size()) : 0;
}

extern "C" int cs_nebula_reader_copy_metadata(CreativeNebulaReaderHandle handle,
                                                uint8_t* output, uint32_t capacity) {
    auto* reader = static_cast<Reader*>(handle);
    if (!reader || !reader->valid || !output || capacity < static_cast<uint32_t>(reader->metadata.size()))
        return 0;
    std::copy(reader->metadata.cbegin(), reader->metadata.cend(), reinterpret_cast<char*>(output));
    return 1;
}

extern "C" uint32_t cs_nebula_reader_chunk_count(CreativeNebulaReaderHandle handle) {
    auto* reader = static_cast<Reader*>(handle);
    return reader && reader->valid ? reader->expected : 0;
}

extern "C" int cs_nebula_reader_next_tile(CreativeNebulaReaderHandle handle,
                                            uint32_t* chunk_id, uint8_t* output,
                                            uint64_t capacity, uint64_t* byte_count) {
    auto* reader = static_cast<Reader*>(handle);
    if (!reader || !reader->valid || !chunk_id || !output || !byte_count) return -1;
    if (reader->read >= reader->expected) return reader->file.atEnd() ? 0 : -1;
    QByteArray header = reader->file.read(28);
    if (header.size() != 28) return -1;
    QDataStream stream(header);
    stream.setByteOrder(QDataStream::LittleEndian);
    char kind[4]{};
    quint32 id = 0, crc = 0;
    quint64 raw_size = 0, packed_size = 0;
    stream.readRawData(kind, 4);
    stream >> id >> raw_size >> packed_size >> crc;
    if (QByteArray(kind, 4) != "TILE" || !id || reader->ids.count(id) ||
        !raw_size || raw_size > kMaxTileBytes || packed_size < 4 || packed_size > kMaxPackedBytes)
        return -1;
    const QByteArray packed = reader->file.read(static_cast<qint64>(packed_size));
    if (packed.size() != static_cast<qsizetype>(packed_size)) return -1;
    const auto* packed_bytes = reinterpret_cast<const uint8_t*>(packed.constData());
    const quint32 announced_size = (quint32(packed_bytes[0]) << 24) |
                                   (quint32(packed_bytes[1]) << 16) |
                                   (quint32(packed_bytes[2]) << 8) |
                                   quint32(packed_bytes[3]);
    if (announced_size != raw_size) return -1;
    const QByteArray raw = qUncompress(packed);
    if (raw.size() != static_cast<qsizetype>(raw_size) || crc32_bytes(
            reinterpret_cast<const uint8_t*>(raw.constData()), raw.size()) != crc)
        return -1;
    if (capacity < raw_size) return -2;
    std::copy(raw.cbegin(), raw.cend(), reinterpret_cast<char*>(output));
    *chunk_id = id;
    *byte_count = raw_size;
    reader->ids.insert(id);
    ++reader->read;
    if (reader->read == reader->expected && !reader->file.atEnd()) return -1;
    return 1;
}

extern "C" void cs_nebula_reader_close(CreativeNebulaReaderHandle handle) {
    delete static_cast<Reader*>(handle);
}

extern "C" int cs_nebula_validate_manifest(const uint8_t* metadata,
                                            uint32_t metadataSize,
                                            uint32_t chunkCount,
                                            int* width, int* height, int* dpi) {
    if (!metadata || metadataSize == 0 || metadataSize > kMaxMetadata ||
        chunkCount > kMaxChunks || !width || !height || !dpi) return 0;
    try {
        return validNebulaManifest(QByteArray(reinterpret_cast<const char*>(metadata),
                                              static_cast<qsizetype>(metadataSize)),
                                   chunkCount, width, height, dpi) ? 1 : 0;
    } catch (...) { return 0; }
}
