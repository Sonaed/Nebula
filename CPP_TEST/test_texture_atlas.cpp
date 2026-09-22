#include "creative_core_api.h"

#include <cstdint>
#include <vector>

int main()
{
    CreativeTextureAtlasHandle atlas = cs_texture_atlas_create(8, 1);
    if (!atlas) return 1;

    int x = -1;
    int y = -1;
    if (!cs_texture_atlas_add(atlas, 3, 2, &x, &y) || x != 0 || y != 0) {
        cs_texture_atlas_destroy(atlas);
        return 2;
    }

    const std::vector<std::uint8_t> source{
        1, 2, 3, 4,  5, 6, 7, 8,  9, 10, 11, 12,
        13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
    };
    if (!cs_texture_atlas_write(atlas, x, y, source.data(), 3, 2, 12)) {
        cs_texture_atlas_destroy(atlas);
        return 3;
    }

    std::vector<std::uint8_t> copied(source.size(), 0);
    if (!cs_texture_atlas_copy(atlas, x, y, copied.data(), 3, 2, 12)
        || copied != source) {
        cs_texture_atlas_destroy(atlas);
        return 4;
    }

    int rejected_x = 0;
    int rejected_y = 0;
    if (cs_texture_atlas_add(atlas, 9, 1, &rejected_x, &rejected_y)
        || cs_texture_atlas_copy(atlas, 7, 7, copied.data(), 3, 2, 12)) {
        cs_texture_atlas_destroy(atlas);
        return 5;
    }

    cs_texture_atlas_destroy(atlas);
    return 0;
}
