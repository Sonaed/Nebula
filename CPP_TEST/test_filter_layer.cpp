// Tests des calques de filtre non destructifs (sans Qt).
//
// Propriété centrale : évaluer la pile tuile par tuile (avec halo) donne les
// mêmes pixels que l'évaluer sur le document entier — pour chaque filtre, chaque
// mode de bord, avec opacité et masque, et pour des chaînes mêlant plusieurs
// filtres et calques raster.

#include "document_state.h"
#include "filter_layer.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <random>
#include <string>
#include <vector>

using namespace cc::filters;

namespace {

int g_failures = 0;
int g_checks = 0;

#define CHECK(cond)                                                              \
    do {                                                                         \
        ++g_checks;                                                              \
        if (!(cond)) {                                                           \
            ++g_failures;                                                        \
            std::printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);        \
        }                                                                        \
    } while (0)

FilterDescriptor D(FilterKind kind, std::initializer_list<double> params,
                   EdgeMode edge = EdgeMode::Clamp, int points = 0)
{
    FilterDescriptor d;
    d.kind = kind;
    d.edge = edge;
    d.pointCount = points;
    int i = 0;
    for (double p : params) d.params[i++] = p;
    return d;
}

// ------------------------------------------------------------ source factice --

struct MockSource : StackSource
{
    int W, H;
    std::vector<std::vector<uint8_t>> layers;      // RGBA droit, document entier
    std::vector<std::vector<uint8_t>> entryMasks;  // par index d'entrée ; vide = pas de masque
    int composeCalls = 0;
    bool failNext = false;

    MockSource(int w, int h) : W(w), H(h) {}

    int addLayer(unsigned seed, bool translucent)
    {
        std::vector<uint8_t> px(static_cast<size_t>(W) * H * 4);
        std::mt19937 rng(seed);
        static const uint8_t alphas[4] = {0, 64, 128, 255};
        for (size_t i = 0; i < px.size(); i += 4) {
            px[i] = rng() & 255;
            px[i + 1] = rng() & 255;
            px[i + 2] = rng() & 255;
            px[i + 3] = translucent ? alphas[rng() & 3] : 255;
        }
        layers.push_back(std::move(px));
        return static_cast<int>(layers.size()) - 1;
    }

    void setMask(size_t entryIndex, unsigned seed)
    {
        if (entryMasks.size() <= entryIndex) entryMasks.resize(entryIndex + 1);
        std::vector<uint8_t> m(static_cast<size_t>(W) * H);
        std::mt19937 rng(seed);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x) {
                // Rampe diagonale + quelques 0 et 255 francs.
                const int v = (x * 255 / std::max(1, W - 1) + y * 255 / std::max(1, H - 1)) / 2;
                m[static_cast<size_t>(y) * W + x] = (rng() % 11 == 0) ? 0 : (rng() % 13 == 0 ? 255 : v);
            }
        entryMasks[entryIndex] = std::move(m);
    }

    bool composeRaster(const int* ids, int count, const uint8_t* backdrop,
                       const Rect& rect, uint8_t* out) override
    {
        ++composeCalls;
        if (failNext) {
            failNext = false;
            failed = true;
            return false;
        }
        const int w = rect.width();
        for (int y = rect.y0; y < rect.y1; ++y)
            for (int x = rect.x0; x < rect.x1; ++x) {
                float r = 0, g = 0, b = 0, a = 0; // prémultiplié
                if (backdrop) {
                    const uint8_t* p = backdrop + (static_cast<size_t>(y - rect.y0) * w + (x - rect.x0)) * 4;
                    a = p[3] / 255.0f;
                    r = p[0] / 255.0f * a;
                    g = p[1] / 255.0f * a;
                    b = p[2] / 255.0f * a;
                }
                for (int i = 0; i < count; ++i) {
                    const uint8_t* p = layers[static_cast<size_t>(ids[i])].data() +
                                       (static_cast<size_t>(y) * W + x) * 4;
                    const float sa = p[3] / 255.0f;
                    r = p[0] / 255.0f * sa + r * (1 - sa);
                    g = p[1] / 255.0f * sa + g * (1 - sa);
                    b = p[2] / 255.0f * sa + b * (1 - sa);
                    a = sa + a * (1 - sa);
                }
                uint8_t* o = out + (static_cast<size_t>(y - rect.y0) * w + (x - rect.x0)) * 4;
                if (a <= 1e-6f) {
                    o[0] = o[1] = o[2] = o[3] = 0;
                } else {
                    auto q = [](float v) { return static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, v * 255.0f + 0.5f))); };
                    o[0] = q(r / a);
                    o[1] = q(g / a);
                    o[2] = q(b / a);
                    o[3] = q(a);
                }
            }
        return true;
    }

    bool filterCoverage(int entryIndex, const Rect& rect, uint8_t* out) override
    {
        if (static_cast<size_t>(entryIndex) >= entryMasks.size() ||
            entryMasks[static_cast<size_t>(entryIndex)].empty())
            return false;
        const auto& m = entryMasks[static_cast<size_t>(entryIndex)];
        const int w = rect.width();
        for (int y = rect.y0; y < rect.y1; ++y)
            std::memcpy(out + static_cast<size_t>(y - rect.y0) * w,
                        m.data() + static_cast<size_t>(y) * W + rect.x0, static_cast<size_t>(w));
        return true;
    }
};

StackEntry raster(int id)
{
    StackEntry e;
    e.rasterId = id;
    return e;
}

StackEntry filter(const FilterDescriptor& d, float opacity = 1.0f, bool visible = true)
{
    StackEntry e;
    e.isFilter = true;
    e.filter = d;
    e.opacity = opacity;
    e.visible = visible;
    return e;
}

// Évalue par tuiles et assemble un document entier.
std::vector<uint8_t> evaluateTiled(const std::vector<StackEntry>& stack, MockSource& src,
                                   int tileW, int tileH, bool* ok)
{
    std::vector<uint8_t> whole(static_cast<size_t>(src.W) * src.H * 4, 0);
    *ok = true;
    for (int y0 = 0; y0 < src.H; y0 += tileH)
        for (int x0 = 0; x0 < src.W; x0 += tileW) {
            Rect r{x0, y0, std::min(src.W, x0 + tileW), std::min(src.H, y0 + tileH)};
            std::vector<uint8_t> tile;
            if (!evaluateStack(stack, src, src.W, src.H, r, tile)) {
                *ok = false;
                return whole;
            }
            for (int y = r.y0; y < r.y1; ++y)
                std::memcpy(whole.data() + (static_cast<size_t>(y) * src.W + r.x0) * 4,
                            tile.data() + static_cast<size_t>(y - r.y0) * r.width() * 4,
                            static_cast<size_t>(r.width()) * 4);
        }
    return whole;
}

std::vector<uint8_t> evaluateWhole(const std::vector<StackEntry>& stack, MockSource& src, bool* ok)
{
    std::vector<uint8_t> out;
    *ok = evaluateStack(stack, src, src.W, src.H, Rect{0, 0, src.W, src.H}, out);
    return out;
}

int maxDiff(const std::vector<uint8_t>& a, const std::vector<uint8_t>& b)
{
    if (a.size() != b.size()) return 999;
    int d = 0;
    for (size_t i = 0; i < a.size(); ++i) d = std::max(d, std::abs(int(a[i]) - int(b[i])));
    return d;
}

// ----------------------------------------------------------- descripteurs ----

void testDescriptorRoundTrip()
{
    std::printf("descripteur: encodage/décodage de chaque type\n");
    const FilterDescriptor all[] = {
        D(FilterKind::GaussianBlur, {2.5, 3.0}, EdgeMode::Wrap),
        D(FilterKind::BoxBlur, {4, 3}),
        D(FilterKind::MotionBlur, {30, 9}, EdgeMode::Wrap),
        D(FilterKind::UnsharpMask, {2, 1.5, 3}),
        D(FilterKind::Median, {2}),
        D(FilterKind::Pixelate, {5, 4}),
        D(FilterKind::EdgeDetect, {1.5}),
        D(FilterKind::Emboss, {45, 1}),
        D(FilterKind::Invert, {}),
        D(FilterKind::Desaturate, {2}),
        D(FilterKind::HsvAdjust, {40, 0.2, -0.1}),
        D(FilterKind::Posterize, {5}),
        D(FilterKind::Threshold, {100}),
        D(FilterKind::Noise, {0.1, 4294967295.0, 1, 0, 1}),
        D(FilterKind::ColorToAlpha, {255, 128, 0, 0.1}),
        D(FilterKind::Levels, {10, 240, 1.4, 0, 255}),
        D(FilterKind::BrightnessContrast, {0.1, -0.3}),
        D(FilterKind::Curve, {0, 0, 0.5, 0.75, 1, 1}, EdgeMode::Clamp, 3),
    };
    for (const auto& d : all) {
        std::vector<uint8_t> bytes;
        CHECK(validateDescriptor(d));
        CHECK(encodeDescriptor(d, bytes));
        CHECK(bytes.size() == kDescriptorBytes);
        FilterDescriptor back;
        CHECK(decodeDescriptor(bytes.data(), bytes.size(), back));
        CHECK(back.kind == d.kind && back.edge == d.edge && back.pointCount == d.pointCount);
        CHECK(std::memcmp(back.params, d.params, sizeof d.params) == 0);
        std::vector<uint8_t> again;
        CHECK(encodeDescriptor(back, again) && again == bytes); // forme canonique
    }
}

void testDescriptorCorruption()
{
    std::printf("descripteur: toute altération est refusée\n");
    std::vector<uint8_t> good;
    CHECK(encodeDescriptor(D(FilterKind::GaussianBlur, {3, 3}), good));
    FilterDescriptor out;
    int accepted = 0;
    for (size_t i = 0; i < good.size(); ++i)
        for (int bit = 0; bit < 8; ++bit) {
            auto bad = good;
            bad[i] ^= static_cast<uint8_t>(1u << bit);
            accepted += decodeDescriptor(bad.data(), bad.size(), out) ? 1 : 0;
        }
    CHECK(accepted == 0); // CRC32 : aucune inversion d'un seul bit ne passe
    CHECK(!decodeDescriptor(good.data(), good.size() - 1, out));
    auto longer = good;
    longer.push_back(0);
    CHECK(!decodeDescriptor(longer.data(), longer.size(), out));
    CHECK(!decodeDescriptor(nullptr, good.size(), out));
    CHECK(!decodeDescriptor(good.data(), 0, out));

    // Charge au CRC valide mais aux valeurs illégales : la validation doit refuser.
    auto forged = [&](FilterKind k, std::initializer_list<double> params, int edge, int points) {
        std::vector<uint8_t> b = good;
        b[5] = static_cast<uint8_t>(k);
        b[6] = static_cast<uint8_t>(edge);
        b[7] = static_cast<uint8_t>(points);
        std::memset(b.data() + 8, 0, 64);
        int i = 0;
        for (double p : params) {
            uint64_t bits;
            std::memcpy(&bits, &p, 8);
            for (int k2 = 0; k2 < 8; ++k2) b[8 + 8 * i + k2] = static_cast<uint8_t>(bits >> (8 * k2));
            ++i;
        }
        const uint32_t crc = descriptorCrc32(b.data(), 72);
        for (int k2 = 0; k2 < 4; ++k2) b[72 + k2] = static_cast<uint8_t>(crc >> (8 * k2));
        return b;
    };
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();
    struct Case { FilterKind k; std::initializer_list<double> p; int edge, points; bool ok; };
    const Case cases[] = {
        {FilterKind::GaussianBlur, {3, 3}, 0, 0, true},
        {FilterKind::GaussianBlur, {nan, 3}, 0, 0, false},
        {FilterKind::GaussianBlur, {-1, 3}, 0, 0, false},
        {FilterKind::GaussianBlur, {inf, 3}, 0, 0, false},
        {FilterKind::GaussianBlur, {1e9, 3}, 0, 0, false},
        {FilterKind::GaussianBlur, {3, 3}, 2, 0, false},          // bord inconnu
        {FilterKind::GaussianBlur, {3, 3}, 0, 1, false},          // points hors Curve
        {FilterKind::GaussianBlur, {3, 3, 9}, 0, 0, false},       // paramètre inutilisé non nul
        {FilterKind::BoxBlur, {2.5, 1}, 0, 0, false},             // non entier
        {FilterKind::Median, {9}, 0, 0, false},
        {FilterKind::Pixelate, {0, 4}, 0, 0, false},
        {FilterKind::Posterize, {1}, 0, 0, false},
        {FilterKind::Levels, {200, 100, 1, 0, 255}, 0, 0, false},  // blanc <= noir
        {FilterKind::Levels, {0, 255, 0, 0, 255}, 0, 0, false},    // gamma nul
        {FilterKind::Noise, {0.1, 1e300, 1, 0, 0}, 0, 0, false},  // graine > 2^53
        {FilterKind::Noise, {0.1, 5, 2, 0, 0}, 0, 0, false},       // booléen invalide
        {FilterKind::ColorToAlpha, {256, 0, 0, 0}, 0, 0, false},
        {FilterKind::Curve, {0.5, 0, 0.2, 1}, 0, 2, false},        // x non croissants
        {FilterKind::Curve, {0, 0, 1, 1}, 0, 1, false},            // < 2 points
        {FilterKind::Curve, {0, 0, 1, 1}, 0, 5, false},            // > 4 points
        {FilterKind::Curve, {0, 0, 1, 2}, 0, 2, false},            // y hors [0,1]
        {FilterKind::Curve, {0, 0, 1, 1}, 0, 2, true},
        {static_cast<FilterKind>(0), {}, 0, 0, false},
        {static_cast<FilterKind>(99), {}, 0, 0, false},
    };
    for (const auto& c : cases) {
        auto b = forged(c.k, c.p, c.edge, c.points);
        CHECK(decodeDescriptor(b.data(), b.size(), out) == c.ok);
    }
}

void testDescriptorFuzz()
{
    std::printf("descripteur: fuzz structuré (validation cohérente, aucun crash)\n");
    std::mt19937_64 rng(2026);
    // Nombre de paramètres utiles par type (indice = FilterKind), Curve géré à part.
    const int used[19] = {0, 2, 2, 2, 3, 1, 2, 1, 2, 0, 1, 3, 1, 1, 5, 4, 5, 2, 0};
    const double plausible[] = {0, 0, 0.5, 1, 1, 2, 3, 4, 5, 7, 8, 12, 45, 90, 100, 128, 200, 255, 0.25, 0.75, -0.5, -1};
    const double hostile[] = {-0.0, -1e12, 1e12, 256, 4096, 1e-300, 0.1,
                              std::numeric_limits<double>::quiet_NaN(),
                              std::numeric_limits<double>::infinity()};
    int accepted = 0, rejected = 0;
    // Thousands of structurally distinct payloads are enough for this ABI
    // fuzzer.  Larger counts mostly repeat costly, yet valid, 1000px blur
    // descriptors on a 7×5 fixture and turn a unit test into a multi-minute
    // stress run.
    constexpr int fuzzIterations = 4000;
    for (int iter = 0; iter < fuzzIterations; ++iter) {
        std::vector<uint8_t> b(kDescriptorBytes, 0);
        b[0] = 'C'; b[1] = 'S'; b[2] = 'F'; b[3] = 'D'; b[4] = 1;
        const int kind = 1 + int(rng() % 18);
        b[5] = static_cast<uint8_t>(kind);
        b[6] = static_cast<uint8_t>(rng() % 20 == 0 ? 2 : rng() % 2);
        const int points = kind == 18 ? 2 + int(rng() % 3) : 0;
        b[7] = static_cast<uint8_t>(rng() % 25 == 0 ? 5 : points);
        const int count = kind == 18 ? 2 * points : used[kind];
        for (int i = 0; i < 8; ++i) {
            double v = 0.0;
            if (i < count) {
                v = (rng() % 8 == 0) ? hostile[rng() % (sizeof hostile / sizeof hostile[0])]
                                     : plausible[rng() % (sizeof plausible / sizeof plausible[0])];
                if (kind == 18) v = (i % 2 == 0) ? double(i / 2) / 4.0 + (rng() % 10) / 100.0
                                                 : (rng() % 101) / 100.0; // x croissants, y dans [0,1]
            } else if (rng() % 30 == 0) {
                v = 1.0; // paramètre inutilisé non nul : doit être refusé
            }
            uint64_t bits;
            std::memcpy(&bits, &v, 8);
            for (int k = 0; k < 8; ++k) b[8 + 8 * i + k] = static_cast<uint8_t>(bits >> (8 * k));
        }
        const uint32_t crc = descriptorCrc32(b.data(), 72);
        for (int k = 0; k < 4; ++k) b[72 + k] = static_cast<uint8_t>(crc >> (8 * k));
        FilterDescriptor d;
        if (!decodeDescriptor(b.data(), b.size(), d)) {
            ++rejected;
            continue;
        }
        ++accepted;
        std::vector<uint8_t> again;
        if (!(validateDescriptor(d) && encodeDescriptor(d, again) && again == b)) {
            CHECK(false);
            continue;
        }
        std::vector<uint8_t> px(7 * 5 * 4, 123);
        Surface s;
        s.pixels = px.data(); s.width = 7; s.height = 5; s.stride = 28;
        if (!applyDescriptor(s, d)) CHECK(false); // valide => applicable
        if (descriptorReach(d) < 0) CHECK(false);
        const Rect r = expandRectForFilter(d, Rect{2, 1, 5, 4}, 7, 5);
        CHECK(r.x0 <= 2 && r.x1 >= 5 && r.y0 <= 1 && r.y1 >= 4 && r.x0 >= 0 && r.x1 <= 7);
    }
    std::printf("  %d acceptés, %d refusés sur %d tirages\n", accepted, rejected, fuzzIterations);
    CHECK(accepted > 400 && rejected > 400);
}

void testExpandRect()
{
    std::printf("halo: régions élargies bornées, alignées, Wrap = axe entier\n");
    const int W = 100, H = 80;
    const Rect r{30, 20, 50, 40};
    auto g2 = D(FilterKind::GaussianBlur, {2, 2});
    Rect e = expandRectForFilter(g2, r, W, H);
    CHECK(e.x0 == 30 - 6 && e.x1 == 50 + 6 && e.y0 == 20 - 6 && e.y1 == 40 + 6);
    // Bord clamp : borné au document
    e = expandRectForFilter(g2, Rect{0, 0, 20, 20}, W, H);
    CHECK(e.x0 == 0 && e.y0 == 0 && e.x1 == 26 && e.y1 == 26);
    // Wrap qui franchit un bord : axe entier sur cet axe seulement
    auto w2 = D(FilterKind::GaussianBlur, {2, 2}, EdgeMode::Wrap);
    e = expandRectForFilter(w2, Rect{0, 20, 20, 40}, W, H);
    CHECK(e.x0 == 0 && e.x1 == W && e.y0 == 14 && e.y1 == 46);
    // Mosaïque : alignement sur la grille
    e = expandRectForFilter(D(FilterKind::Pixelate, {5, 4}), Rect{7, 7, 19, 12}, W, H);
    CHECK(e.x0 == 5 && e.x1 == 20 && e.y0 == 4 && e.y1 == 12);
    e = expandRectForFilter(D(FilterKind::Pixelate, {30, 30}), Rect{85, 60, 99, 79}, W, H);
    CHECK(e.x1 == W && e.y1 == H && e.x0 == 60 && e.y0 == 60);
    // Filtre ponctuel : inchangé
    CHECK(expandRectForFilter(D(FilterKind::Invert, {}), r, W, H) == r);

    std::mt19937 rng(5);
    for (int i = 0; i < 2000; ++i) {
        FilterDescriptor d = D(FilterKind::GaussianBlur, {double(rng() % 30), double(rng() % 30)},
                               (rng() & 1) ? EdgeMode::Wrap : EdgeMode::Clamp);
        if (rng() % 3 == 0) d = D(FilterKind::Median, {double(rng() % 9)});
        if (rng() % 5 == 0) d = D(FilterKind::Pixelate, {double(1 + rng() % 40), double(1 + rng() % 40)});
        const int x0 = rng() % W, y0 = rng() % H;
        Rect reg{x0, y0, x0 + 1 + int(rng() % (W - x0)), y0 + 1 + int(rng() % (H - y0))};
        const Rect ex = expandRectForFilter(d, reg, W, H);
        CHECK(ex.x0 <= reg.x0 && ex.y0 <= reg.y0 && ex.x1 >= reg.x1 && ex.y1 >= reg.y1);
        CHECK(ex.x0 >= 0 && ex.y0 >= 0 && ex.x1 <= W && ex.y1 <= H);
    }
}

// --------------------------------------------- équivalence tuiles / entier ----

struct Case
{
    const char* name;
    FilterDescriptor d;
    int tolerance;
};

void testSingleFilterTileEquivalence()
{
    std::printf("équivalence: chaque filtre évalué par tuiles = document entier\n");
    const int W = 53, H = 41;
    std::vector<Case> cases;
    for (EdgeMode edge : {EdgeMode::Clamp, EdgeMode::Wrap}) {
        cases.push_back({"gaussian s=2,3", D(FilterKind::GaussianBlur, {2, 3}, edge), 0});
        cases.push_back({"gaussian s=9,7 (boîtes)", D(FilterKind::GaussianBlur, {9, 7}, edge), 1});
        cases.push_back({"box 4,3", D(FilterKind::BoxBlur, {4, 3}, edge), 1});
        cases.push_back({"motion 30°/9", D(FilterKind::MotionBlur, {30, 9}, edge), 1});
        cases.push_back({"motion 0°/12", D(FilterKind::MotionBlur, {0, 12}, edge), 0});
        cases.push_back({"unsharp 2,1.5,3", D(FilterKind::UnsharpMask, {2, 1.5, 3}, edge), 0});
        cases.push_back({"unsharp 8,1,0 (boîtes)", D(FilterKind::UnsharpMask, {8, 1, 0}, edge), 1});
    }
    cases.push_back({"median 2", D(FilterKind::Median, {2}), 0});
    cases.push_back({"pixelate 5x4", D(FilterKind::Pixelate, {5, 4}), 0});
    cases.push_back({"pixelate 16x16", D(FilterKind::Pixelate, {16, 16}), 0});
    cases.push_back({"edge 1", D(FilterKind::EdgeDetect, {1}), 0});
    cases.push_back({"emboss 45", D(FilterKind::Emboss, {45, 1}), 0});
    cases.push_back({"invert", D(FilterKind::Invert, {}), 0});
    cases.push_back({"desaturate", D(FilterKind::Desaturate, {0}), 0});
    cases.push_back({"hsv", D(FilterKind::HsvAdjust, {40, 0.2, -0.1}), 0});
    cases.push_back({"posterize 5", D(FilterKind::Posterize, {5}), 0});
    cases.push_back({"threshold", D(FilterKind::Threshold, {100}), 0});
    cases.push_back({"noise (position absolue)", D(FilterKind::Noise, {0.1, 7, 1, 0, 0}), 0});
    cases.push_back({"color to alpha", D(FilterKind::ColorToAlpha, {255, 255, 255, 0.1}), 0});
    cases.push_back({"levels", D(FilterKind::Levels, {10, 240, 1.4, 0, 255}), 0});
    cases.push_back({"brightness/contrast", D(FilterKind::BrightnessContrast, {0.1, 0.3}), 0});
    cases.push_back({"curve", D(FilterKind::Curve, {0, 0, 0.5, 0.75, 1, 1}, EdgeMode::Clamp, 3), 0});

    int worstOverall = 0;
    for (const auto& c : cases) {
        for (float opacity : {1.0f, 0.6f})
            for (bool masked : {false, true}) {
                MockSource src(W, H);
                const int id = src.addLayer(100 + int(c.d.kind), true);
                std::vector<StackEntry> stack = {raster(id), filter(c.d, opacity)};
                if (masked) src.setMask(1, 77);
                bool okW = false, okT = false;
                const auto whole = evaluateWhole(stack, src, &okW);
                // Référence INDÉPENDANTE : filtre appliqué directement sur le document
                // composé, sans halo ni évaluateur.
                std::vector<uint8_t> ref(static_cast<size_t>(W) * H * 4);
                const int ids[1] = {id};
                src.composeRaster(ids, 1, nullptr, Rect{0, 0, W, H}, ref.data());
                const std::vector<uint8_t> base = ref;
                std::vector<uint8_t> mask;
                Mask m;
                if (masked) {
                    mask = src.entryMasks[1];
                    m.data = mask.data();
                    m.stride = W;
                }
                Surface s;
                s.pixels = ref.data(); s.width = W; s.height = H; s.stride = W * 4;
                CHECK(applyDescriptor(s, c.d, m));
                if (opacity < 1.0f)
                    for (size_t i = 0; i < ref.size(); ++i) {
                        const float o = base[i], f = ref[i];
                        ref[i] = static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, std::floor(o + (f - o) * opacity + 0.5f))));
                    }
                CHECK(okW);
                const int dWhole = maxDiff(whole, ref);
                const auto tiled = evaluateTiled(stack, src, 16, 13, &okT);
                CHECK(okT);
                const int dTiled = maxDiff(tiled, ref);
                worstOverall = std::max(worstOverall, dTiled);
                if (dWhole > c.tolerance || dTiled > c.tolerance) {
                    std::printf("  ÉCART %-26s op=%.1f mask=%d  entier=%d tuiles=%d (tol %d)\n", c.name,
                                opacity, masked, dWhole, dTiled, c.tolerance);
                }
                CHECK(dWhole <= c.tolerance);
                CHECK(dTiled <= c.tolerance);
            }
    }
    std::printf("  écart maximal toutes configurations : %d niveau(x)\n", worstOverall);
}

void testChains()
{
    std::printf("équivalence: chaînes raster/filtres mêlés, tuiles de tailles variées\n");
    const int W = 61, H = 47;
    MockSource src(W, H);
    const int a = src.addLayer(1, false), b = src.addLayer(2, true), c = src.addLayer(3, true),
              d = src.addLayer(4, true);
    std::vector<StackEntry> stack = {
        raster(a),
        filter(D(FilterKind::GaussianBlur, {2.5, 2.5}, EdgeMode::Wrap), 1.0f),       // 1
        raster(b),
        filter(D(FilterKind::Pixelate, {6, 5}), 0.8f),                               // 3
        raster(c),
        filter(D(FilterKind::Emboss, {45, 1}), 1.0f),                                // 5 (masque)
        filter(D(FilterKind::Invert, {}), 1.0f, /*visible=*/false),                  // 6 invisible
        filter(D(FilterKind::Median, {2}), 0.0f),                                    // 7 opacité 0
        filter(D(FilterKind::UnsharpMask, {1.5, 1.2, 2}, EdgeMode::Clamp), 0.9f),    // 8
        raster(d),
        filter(D(FilterKind::MotionBlur, {20, 7}, EdgeMode::Wrap), 0.7f),            // 10
    };
    src.setMask(5, 9);
    src.setMask(10, 21);
    bool ok = false;
    const auto whole = evaluateWhole(stack, src, &ok);
    CHECK(ok);
    CHECK(whole.size() == static_cast<size_t>(W) * H * 4);
    for (auto tile : {std::pair<int, int>{16, 13}, {7, 9}, {61, 5}, {5, 47}, {1, 1}, {30, 23}}) {
        const auto tiled = evaluateTiled(stack, src, tile.first, tile.second, &ok);
        CHECK(ok);
        const int dd = maxDiff(tiled, whole);
        std::printf("  tuiles %2dx%-2d : écart max %d\n", tile.first, tile.second, dd);
        CHECK(dd <= 1);
    }
    // Le résultat n'est pas trivial : chaque filtre visible a bien changé l'image.
    auto without = stack;
    without.erase(without.begin() + 10);
    bool ok2 = false;
    const auto noLast = evaluateWhole(without, src, &ok2);
    CHECK(ok2 && maxDiff(noLast, whole) > 5);
}

void testStackEdgeCases()
{
    std::printf("pile: cas limites et erreurs propagées\n");
    MockSource src(20, 10);
    const int a = src.addLayer(1, true);
    std::vector<uint8_t> out;

    // Aucune entrée : image transparente
    CHECK(evaluateStack({}, src, 20, 10, Rect{0, 0, 20, 10}, out));
    CHECK(out.size() == 800 && std::all_of(out.begin(), out.end(), [](uint8_t v) { return v == 0; }));
    // Seulement des rasters = composition directe
    CHECK(evaluateStack({raster(a)}, src, 20, 10, Rect{3, 2, 9, 7}, out) && out.size() == 6 * 5 * 4);
    // Filtre seul sur fond transparent : Invert ne crée pas de pixels visibles
    CHECK(evaluateStack({filter(D(FilterKind::Invert, {}))}, src, 20, 10, Rect{0, 0, 20, 10}, out));
    bool anyAlpha = false;
    for (size_t i = 3; i < out.size(); i += 4) anyAlpha |= out[i] != 0;
    CHECK(!anyAlpha);
    // Région invalide
    CHECK(!evaluateStack({raster(a)}, src, 20, 10, Rect{0, 0, 21, 10}, out));
    CHECK(!evaluateStack({raster(a)}, src, 20, 10, Rect{5, 5, 5, 9}, out));
    CHECK(!evaluateStack({raster(a)}, src, 20, 10, Rect{-1, 0, 4, 4}, out));
    CHECK(!evaluateStack({raster(a)}, src, 0, 10, Rect{0, 0, 1, 1}, out));
    // Descripteur invalide
    FilterDescriptor bad = D(FilterKind::GaussianBlur, {-1, 1});
    CHECK(!evaluateStack({raster(a), filter(bad)}, src, 20, 10, Rect{0, 0, 20, 10}, out));
    // Échec de la source
    src.failNext = true;
    CHECK(!evaluateStack({raster(a)}, src, 20, 10, Rect{0, 0, 20, 10}, out));
    CHECK(evaluateStack({raster(a)}, src, 20, 10, Rect{0, 0, 20, 10}, out)); // et se rétablit
    // Opacité 0 : mêmes pixels que sans le calque, sans appel inutile
    bool ok1, ok2;
    std::vector<StackEntry> withZero = {raster(a), filter(D(FilterKind::GaussianBlur, {5, 5}), 0.0f)};
    const auto r0 = evaluateWhole(withZero, src, &ok1);
    const auto r1 = evaluateWhole({raster(a)}, src, &ok2);
    CHECK(ok1 && ok2 && r0 == r1);
}

// -------------------------------------------------------- calque document ----

void testDocumentFilterLayers()
{
    std::printf("document: calques de filtre (validation, réordonnancement, suppression)\n");
    DocumentState doc(64, 64, 72);
    int base = -1, f1 = -1, f2 = -1;
    CHECK(doc.addLayer("Fond", base) && base == 0);

    std::vector<uint8_t> blur, inv;
    CHECK(encodeDescriptor(D(FilterKind::GaussianBlur, {3, 3}, EdgeMode::Wrap), blur));
    CHECK(encodeDescriptor(D(FilterKind::Invert, {}), inv));

    CHECK(doc.addFilterLayer("Flou", blur.data(), blur.size(), f1) && f1 == 1);
    CHECK(doc.addFilterLayer("Inverser", inv.data(), inv.size(), f2) && f2 == 2);
    NativeLayerState info;
    CHECK(doc.layerInfo(f1, info) && info.kind == kLayerKindFilter && info.filterPayload == blur);
    CHECK(doc.layerInfo(base, info) && info.kind == kLayerKindRaster && info.filterPayload.empty());
    CHECK(doc.activeLayer() == f2);

    // Refus : nom vide, charge corrompue, tronquée, nulle — et rien n'est ajouté.
    int idx = -1;
    auto corrupt = blur;
    corrupt[20] ^= 1;
    CHECK(!doc.addFilterLayer("", blur.data(), blur.size(), idx));
    CHECK(!doc.addFilterLayer("X", corrupt.data(), corrupt.size(), idx));
    CHECK(!doc.addFilterLayer("X", blur.data(), blur.size() - 1, idx));
    CHECK(!doc.addFilterLayer("X", nullptr, 0, idx));
    CHECK(doc.layerCount() == 3);

    // Remplacement de descripteur : seulement sur un calque de filtre, et validé.
    std::vector<uint8_t> box;
    CHECK(encodeDescriptor(D(FilterKind::BoxBlur, {2, 2}), box));
    CHECK(doc.setFilterPayload(f1, box.data(), box.size()));
    CHECK(doc.layerInfo(f1, info) && info.filterPayload == box);
    CHECK(!doc.setFilterPayload(base, box.data(), box.size()));    // raster
    CHECK(!doc.setFilterPayload(99, box.data(), box.size()));
    CHECK(!doc.setFilterPayload(f1, corrupt.data(), corrupt.size()));
    CHECK(doc.layerInfo(f1, info) && info.filterPayload == box);   // inchangé

    // Réordonner : le type et la charge suivent leur calque.
    NativeLayerState before1, before2;
    doc.layerInfo(f1, before1);
    doc.layerInfo(f2, before2);
    CHECK(doc.reorderLayers({2, 0, 1}, 0)); // [Inverser, Fond, Flou]
    CHECK(doc.layerInfo(0, info) && info.id == before2.id && info.kind == kLayerKindFilter &&
          info.filterPayload == inv);
    CHECK(doc.layerInfo(1, info) && info.kind == kLayerKindRaster);
    CHECK(doc.layerInfo(2, info) && info.id == before1.id && info.filterPayload == box);

    // Supprimer un calque de filtre laisse les autres intacts.
    CHECK(doc.removeLayer(0));
    CHECK(doc.layerCount() == 2);
    CHECK(doc.layerInfo(1, info) && info.filterPayload == box);

    // Propriétés communes (visibilité, opacité) s'appliquent aussi au filtre.
    double out = 0;
    CHECK(doc.setLayerProperty(1, 1, 0.4, out) && std::fabs(out - 0.4) < 1e-6);
    CHECK(doc.setLayerProperty(1, 0, 0.0, out));
    CHECK(doc.layerInfo(1, info) && !info.visible && std::fabs(info.opacity - 0.4f) < 1e-6);
}

} // namespace

int main()
{
    testDescriptorRoundTrip();
    testDescriptorCorruption();
    testDescriptorFuzz();
    testExpandRect();
    testSingleFilterTileEquivalence();
    testChains();
    testStackEdgeCases();
    testDocumentFilterLayers();
    std::printf("\n%d vérifications, %d échec(s)\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
