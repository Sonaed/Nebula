#include "creative_core_api.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace {

struct TextureAtlas {
    int size = 0;
    int padding = 0;
    int cursorX = 0;
    int cursorY = 0;
    int rowHeight = 0;
    std::vector<std::uint8_t> pixels;

    TextureAtlas(int atlasSize, int atlasPadding)
        : size(atlasSize), padding(atlasPadding),
          pixels(static_cast<std::size_t>(atlasSize) * atlasSize * 4u, 0u) {}
};

TextureAtlas* atlas(CreativeTextureAtlasHandle handle)
{
    return static_cast<TextureAtlas*>(handle);
}

bool validRect(const TextureAtlas& value, int x, int y, int width, int height)
{
    return width > 0 && height > 0 && x >= 0 && y >= 0 &&
           width <= value.size - x && height <= value.size - y;
}

} // namespace

CreativeTextureAtlasHandle cs_texture_atlas_create(int size, int padding)
{
    if (size <= 0 || size > 8192 || padding < 0 || padding > size) return nullptr;
    try { return new TextureAtlas(size, padding); }
    catch (...) { return nullptr; }
}

void cs_texture_atlas_destroy(CreativeTextureAtlasHandle handle)
{
    delete atlas(handle);
}

int cs_texture_atlas_add(CreativeTextureAtlasHandle handle, int width, int height,
                         int* x, int* y)
{
    TextureAtlas* value = atlas(handle);
    if (!value || !x || !y || width <= 0 || height <= 0 ||
        width > value->size || height > value->size) return 0;
    if (value->cursorX + width + value->padding > value->size) {
        value->cursorX = 0;
        value->cursorY += value->rowHeight + value->padding;
        value->rowHeight = 0;
    }
    if (value->cursorY + height > value->size) return 0;
    *x = value->cursorX;
    *y = value->cursorY;
    value->cursorX += width + value->padding;
    value->rowHeight = std::max(value->rowHeight, height);
    return 1;
}

int cs_texture_atlas_write(CreativeTextureAtlasHandle handle, int x, int y,
                           const uint8_t* pixels, int width, int height,
                           int stride)
{
    TextureAtlas* value = atlas(handle);
    if (!value || !pixels || stride < width * 4 || !validRect(*value, x, y, width, height))
        return 0;
    for (int row = 0; row < height; ++row) {
        auto* destination = value->pixels.data() +
            (static_cast<std::size_t>(y + row) * value->size + x) * 4u;
        std::memcpy(destination, pixels + static_cast<std::size_t>(row) * stride,
                    static_cast<std::size_t>(width) * 4u);
    }
    return 1;
}

int cs_texture_atlas_copy(CreativeTextureAtlasHandle handle, int x, int y,
                          uint8_t* output, int width, int height, int stride)
{
    TextureAtlas* value = atlas(handle);
    if (!value || !output || stride < width * 4 || !validRect(*value, x, y, width, height))
        return 0;
    for (int row = 0; row < height; ++row) {
        const auto* source = value->pixels.data() +
            (static_cast<std::size_t>(y + row) * value->size + x) * 4u;
        std::memcpy(output + static_cast<std::size_t>(row) * stride, source,
                    static_cast<std::size_t>(width) * 4u);
    }
    return 1;
}
