// Noyaux ABI 5 : courbe de transfert de dégradé, LUT 3D, alpha, PackBits.
#include "document_state.h"
#include "image_filters.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

using namespace cc::filters;

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("ÉCHEC %s:%d %s\n", __FILE__, __LINE__, #cond); ++failures; } } while (0)

static Surface surface(std::vector<uint8_t>& px, int w, int h)
{
    Surface s; s.pixels = px.data(); s.width = w; s.height = h; s.stride = w * 4; return s;
}

int main()
{
    // Dégradé noir -> blanc inversé : table[i] = 255 - i.
    std::vector<uint8_t> table(1024);
    for (int i = 0; i < 256; ++i) { table[i*4] = table[i*4+1] = table[i*4+2] = uint8_t(255 - i); table[i*4+3] = 255; }
    std::vector<uint8_t> px = {0,0,0,200, 255,255,255,10, 255,0,0,255};
    CHECK(gradientMap(surface(px, 3, 1), table.data()));
    CHECK(px[0] == 255 && px[3] == 200);
    CHECK(px[4] == 0 && px[7] == 10);
    CHECK(px[8] >= 177 && px[8] <= 179);   // luminance(rouge pur) = 0.30 -> 76.5 -> 255-76.5

    // LUT 3D identité de taille 2 : les pixels ne bougent pas.
    std::vector<float> identity = {0,0,0, 1,0,0, 0,1,0, 1,1,0, 0,0,1, 1,0,1, 0,1,1, 1,1,1};
    std::vector<uint8_t> colors = {12,200,77,255, 255,1,128,64};
    std::vector<uint8_t> copy = colors;
    CHECK(lut3d(surface(colors, 2, 1), identity.data(), 2));
    for (size_t i = 0; i < colors.size(); ++i) CHECK(colors[i] == copy[i]);
    // LUT qui échange rouge et bleu.
    std::vector<float> swap(8 * 3);
    for (int b = 0; b < 2; ++b) for (int g = 0; g < 2; ++g) for (int r = 0; r < 2; ++r) {
        float* v = &swap[((b * 2 + g) * 2 + r) * 3]; v[0] = float(b); v[1] = float(g); v[2] = float(r);
    }
    CHECK(lut3d(surface(colors, 2, 1), swap.data(), 2));
    CHECK(colors[0] == 77 && colors[2] == 12 && colors[3] == 255);
    CHECK(!lut3d(surface(colors, 2, 1), swap.data(), 1));

    std::vector<uint8_t> a = {1,2,3,4, 5,6,7,8};
    std::vector<uint8_t> b = {0,0,0,99, 0,0,0,42};
    CHECK(setAlpha(surface(a, 2, 1), 255));
    CHECK(a[3] == 255 && a[7] == 255 && a[0] == 1);
    CHECK(copyAlpha(surface(a, 2, 1), b.data(), 8));
    CHECK(a[3] == 99 && a[7] == 42 && a[4] == 5);

    // PackBits : littéral de 3, répétition de 4, no-op 128, sortie bornée.
    const uint8_t packed[] = {2, 'a', 'b', 'c', uint8_t(253), 'z', 128, 0, 'q'};
    uint8_t out[16] = {0};
    CHECK(unpackBits(packed, sizeof packed, out, sizeof out) == 8);
    CHECK(out[0] == 'a' && out[2] == 'c' && out[3] == 'z' && out[6] == 'z' && out[7] == 'q');
    CHECK(unpackBits(packed, sizeof packed, out, 5) == 5);
    const uint8_t truncated[] = {10, 'x'};
    CHECK(unpackBits(truncated, sizeof truncated, out, sizeof out) == 1);

    // Dossiers PSD imbriqués : un dossier peut englober des dossiers complets
    // et des calques libres, jamais couper un dossier en deux.
    DocumentState doc(64, 64, 72);
    for (int i = 0; i < 6; ++i) { int index = 0; CHECK(doc.addLayer("L", index)); }
    int child = -1, child2 = -1, parent = -1, refused = -1;
    CHECK(doc.createGroup({1, 2}, "enfant", child));
    CHECK(doc.createGroup({4}, "enfant 2", child2));
    CHECK(doc.createGroup({1, 2, 3, 4}, "parent", parent));
    CHECK(!doc.createGroup({2, 3}, "coupe", refused));
    CHECK(!doc.createGroup({0, 5}, "trou", refused));
    CHECK(doc.groupForLayer(2) == child && doc.groupForLayer(3) == parent);

    if (failures == 0) std::printf("test_psd_kernels : OK\n");
    return failures == 0 ? 0 : 1;
}
