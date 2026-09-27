// Tests de la bibliothèque de filtres CreativeCore (sans Qt).
// Chaque test vérifie une propriété mathématique, pas seulement « ça tourne ».

#include "image_filters.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <random>
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

struct Img
{
    int w, h;
    std::vector<uint8_t> px; // packed RGBA
    Img(int w_, int h_) : w(w_), h(h_), px(static_cast<size_t>(w_) * h_ * 4, 0) {}
    uint8_t* at(int x, int y) { return &px[(static_cast<size_t>(y) * w + x) * 4]; }
    const uint8_t* at(int x, int y) const { return &px[(static_cast<size_t>(y) * w + x) * 4]; }
    Surface surface() { return Surface{px.data(), w, h, w * 4}; }
    void fill(uint8_t r, uint8_t g, uint8_t b, uint8_t a)
    {
        for (size_t i = 0; i < px.size(); i += 4) {
            px[i] = r; px[i + 1] = g; px[i + 2] = b; px[i + 3] = a;
        }
    }
    void randomOpaque(unsigned seed)
    {
        std::mt19937 rng(seed);
        for (size_t i = 0; i < px.size(); i += 4) {
            px[i] = rng() & 255; px[i + 1] = rng() & 255; px[i + 2] = rng() & 255;
            px[i + 3] = 255;
        }
    }
};

int maxDiff(const Img& a, const Img& b)
{
    int d = 0;
    for (size_t i = 0; i < a.px.size(); ++i)
        d = std::max(d, std::abs(static_cast<int>(a.px[i]) - b.px[i]));
    return d;
}

uint64_t checksum(const Img& a)
{
    uint64_t h = 1469598103934665603ULL;
    for (uint8_t v : a.px) h = (h ^ v) * 1099511628211ULL;
    return h;
}

// ----------------------------------------------------------------- flous ----

void testBlurKeepsConstantImages()
{
    std::printf("blur: image constante inchangée\n");
    for (EdgeMode edge : {EdgeMode::Clamp, EdgeMode::Wrap}) {
        Img a(37, 23);
        a.fill(200, 100, 50, 255);
        const Img ref = a;
        CHECK(gaussianBlur(a.surface(), 2.0, 3.0, edge));
        CHECK(maxDiff(a, ref) == 0);
        CHECK(gaussianBlur(a.surface(), 10.0, 12.0, edge)); // chemin boîtes
        CHECK(maxDiff(a, ref) == 0);
        CHECK(boxBlur(a.surface(), 5, 4, edge));
        CHECK(maxDiff(a, ref) == 0);
        CHECK(motionBlur(a.surface(), 33.0, 9.0, edge));
        CHECK(maxDiff(a, ref) == 0);
        // Semi-transparent : l'aller-retour prémultiplié ne doit pas dériver.
        Img b(16, 16);
        b.fill(200, 90, 30, 128);
        const Img refB = b;
        CHECK(gaussianBlur(b.surface(), 3.0, 3.0, edge));
        CHECK(maxDiff(b, refB) <= 1);
    }
}

void testBlurHasNoDarkFringe()
{
    std::printf("blur: pas de frange sombre autour de la transparence\n");
    Img a(40, 20);
    for (int y = 0; y < a.h; ++y)
        for (int x = 0; x < 20; ++x) {
            uint8_t* p = a.at(x, y);
            p[0] = p[1] = p[2] = 255;
            p[3] = 255;
        }
    // moitié droite : transparente à RGB=0, le piège d'un flou en alpha droit
    CHECK(gaussianBlur(a.surface(), 3.0, 0.0));
    int visible = 0, dark = 0;
    for (int y = 0; y < a.h; ++y)
        for (int x = 0; x < a.w; ++x) {
            const uint8_t* p = a.at(x, y);
            if (p[3] >= 4) {
                ++visible;
                if (p[0] < 250 || p[1] < 250 || p[2] < 250) ++dark;
            }
        }
    CHECK(visible > 20 * 20);
    CHECK(dark == 0);
    // L'alpha, lui, doit bien s'adoucir au bord.
    CHECK(a.at(20, 10)[3] > 0 && a.at(20, 10)[3] < 255);
}

void testGaussianImpulse()
{
    std::printf("blur: réponse impulsionnelle = noyau gaussien de référence\n");
    Img a(41, 41);
    a.at(20, 20)[0] = a.at(20, 20)[1] = a.at(20, 20)[2] = 255;
    a.at(20, 20)[3] = 255;
    CHECK(gaussianBlur(a.surface(), 2.0, 2.0));
    // Référence indépendante : noyau 1D normalisé, image = k[dx]·k[dy] (séparable).
    const double sigma = 2.0;
    const int r = 6;
    double k[2 * r + 1], norm = 0.0;
    for (int i = -r; i <= r; ++i) norm += (k[i + r] = std::exp(-i * i / (2 * sigma * sigma)));
    int worst = 0;
    double sum = 0.0;
    for (int y = 0; y < 41; ++y)
        for (int x = 0; x < 41; ++x) {
            const int dx = x - 20, dy = y - 20;
            const double expect = (std::abs(dx) <= r && std::abs(dy) <= r)
                                      ? 255.0 * k[dx + r] * k[dy + r] / (norm * norm) : 0.0;
            worst = std::max(worst, static_cast<int>(std::lround(std::fabs(a.at(x, y)[3] - expect))));
            sum += a.at(x, y)[3] / 255.0;
        }
    CHECK(worst <= 1);
    // L'énergie n'est pas exactement 1 : les queues < 0,5/255 s'arrondissent à 0.
    std::printf("  écart max au noyau: %d niveau, énergie conservée à %.1f %% (perte = quantification 8 bits)\n", worst, sum * 100.0);
    CHECK(sum > 0.90 && sum <= 1.02);
    bool symmetric = true;
    for (int d = 1; d <= 8; ++d) {
        symmetric &= a.at(20 - d, 20)[3] == a.at(20 + d, 20)[3];
        symmetric &= a.at(20, 20 - d)[3] == a.at(20, 20 + d)[3];
        symmetric &= a.at(20 - d, 20)[3] == a.at(20, 20 - d)[3];
    }
    CHECK(symmetric);
    CHECK(a.at(20, 20)[3] > a.at(23, 20)[3]); // décroissance radiale
}

void testBoxApproximationOfGaussian()
{
    std::printf("blur: approximation par boîtes vs gaussienne exacte (sigma=8)\n");
    const int w = 200;
    Img a(w, 1);
    a.randomOpaque(7);
    const Img src = a;
    CHECK(gaussianBlur(a.surface(), 8.0, 0.0)); // sigma >= seuil : boîtes
    const double sigma = 8.0;
    const int r = static_cast<int>(std::ceil(3.0 * sigma)) + 8;
    std::vector<double> k(static_cast<size_t>(2 * r + 1));
    double norm = 0.0;
    for (int i = -r; i <= r; ++i) norm += (k[static_cast<size_t>(i + r)] = std::exp(-i * i / (2 * sigma * sigma)));
    int worst = 0;
    for (int x = 0; x < w; ++x)
        for (int c = 0; c < 3; ++c) {
            double v = 0.0;
            for (int i = -r; i <= r; ++i) {
                const int xx = std::min(w - 1, std::max(0, x + i));
                v += k[static_cast<size_t>(i + r)] * src.at(xx, 0)[c];
            }
            worst = std::max(worst, static_cast<int>(std::lround(std::fabs(v / norm - a.at(x, 0)[c]))));
        }
    std::printf("  écart max boîtes/exact (bords inclus): %d niveaux\n", worst);
    CHECK(worst <= 3); // bords compris : l'extension unique évite la dérive aux bordures
}

void testWrapIsShiftEquivariant()
{
    std::printf("blur: mode Wrap = équivariant par translation cyclique\n");
    const int w = 29, h = 17, sx = 11, sy = 5;
    Img base(w, h);
    base.randomOpaque(11);
    Img shifted(w, h);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            std::memcpy(shifted.at((x + sx) % w, (y + sy) % h), base.at(x, y), 4);
    for (double sigma : {2.0, 9.0}) {
        Img a = base, b = shifted;
        CHECK(gaussianBlur(a.surface(), sigma, sigma, EdgeMode::Wrap));
        CHECK(gaussianBlur(b.surface(), sigma, sigma, EdgeMode::Wrap));
        Img aShifted(w, h);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
                std::memcpy(aShifted.at((x + sx) % w, (y + sy) % h), a.at(x, y), 4);
        const int tol = sigma < 6.0 ? 0 : 1; // le chemin boîtes somme dans un autre ordre
        CHECK(maxDiff(aShifted, b) <= tol);
    }
    // Contre-preuve : en mode Clamp le résultat n'est PAS équivariant.
    Img a = base, b = shifted;
    gaussianBlur(a.surface(), 2.0, 2.0, EdgeMode::Clamp);
    gaussianBlur(b.surface(), 2.0, 2.0, EdgeMode::Clamp);
    Img aShifted(w, h);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            std::memcpy(aShifted.at((x + sx) % w, (y + sy) % h), a.at(x, y), 4);
    CHECK(maxDiff(aShifted, b) > 0);
}

void testTinyImagesAndHugeRadii()
{
    std::printf("blur: images minuscules et rayons supérieurs à l'image\n");
    for (EdgeMode edge : {EdgeMode::Clamp, EdgeMode::Wrap}) {
        Img one(1, 1);
        one.fill(10, 20, 30, 255);
        CHECK(gaussianBlur(one.surface(), 50.0, 50.0, edge));
        CHECK(one.at(0, 0)[0] == 10 && one.at(0, 0)[3] == 255);
        Img small(3, 2);
        small.randomOpaque(3);
        CHECK(gaussianBlur(small.surface(), 20.0, 1.0, edge));
        CHECK(boxBlur(small.surface(), 40, 40, edge));
        CHECK(motionBlur(small.surface(), 45.0, 100.0, edge));
        CHECK(medianFilter(small.surface(), 8));
    }
}

void testMotionBlur()
{
    std::printf("blur: directionnel\n");
    Img rows(12, 12), cols(12, 12);
    for (int y = 0; y < 12; ++y)
        for (int x = 0; x < 12; ++x) {
            const uint8_t r = (y % 2) ? 255 : 0, c = (x % 2) ? 255 : 0;
            uint8_t* p = rows.at(x, y);
            p[0] = p[1] = p[2] = r; p[3] = 255;
            p = cols.at(x, y);
            p[0] = p[1] = p[2] = c; p[3] = 255;
        }
    Img rowsRef = rows, colsRef = cols;
    CHECK(motionBlur(rows.surface(), 0.0, 4.0, EdgeMode::Wrap)); // // aux rayures
    CHECK(maxDiff(rows, rowsRef) == 0);
    CHECK(motionBlur(cols.surface(), 90.0, 4.0, EdgeMode::Wrap)); // // aux colonnes
    CHECK(maxDiff(cols, colsRef) == 0);
    Img stripes = colsRef;
    CHECK(motionBlur(stripes.surface(), 0.0, 2.0, EdgeMode::Wrap)); // 3 échantillons
    CHECK(stripes.at(4, 5)[0] == 170); // (255+0+255)/3
    CHECK(stripes.at(5, 5)[0] == 85);  // (0+255+0)/3
}

void testUnsharp()
{
    std::printf("netteté: accentue un bord, respecte seuil, alpha et aplats\n");
    Img a(30, 10);
    for (int y = 0; y < 10; ++y)
        for (int x = 0; x < 30; ++x) {
            uint8_t* p = a.at(x, y);
            p[0] = p[1] = p[2] = x < 15 ? 100 : 150;
            p[3] = 255;
        }
    const Img ref = a;
    Img flat(8, 8);
    flat.fill(90, 120, 200, 255);
    const Img flatRef = flat;
    CHECK(unsharpMask(flat.surface(), 2.0, 2.0));
    CHECK(maxDiff(flat, flatRef) == 0);

    Img t = a;
    CHECK(unsharpMask(t.surface(), 1.5, 1.0, 255)); // seuil maximal : rien ne passe
    CHECK(maxDiff(t, ref) == 0);

    CHECK(unsharpMask(a.surface(), 1.5, 1.0));
    CHECK(a.at(14, 5)[0] < 100); // sous-oscillation côté sombre
    CHECK(a.at(15, 5)[0] > 150); // sur-oscillation côté clair
    CHECK(a.at(2, 5)[0] == 100 && a.at(27, 5)[0] == 150); // loin du bord : intact
    bool alphaIntact = true;
    for (size_t i = 3; i < a.px.size(); i += 4) alphaIntact &= a.px[i] == 255;
    CHECK(alphaIntact);
}

void testMedian()
{
    std::printf("médiane: supprime le poivre et sel, conserve les bords\n");
    Img a(21, 21);
    a.fill(128, 128, 128, 255);
    for (int y = 2; y < 21; y += 6)
        for (int x = 2; x < 21; x += 6) std::memset(a.at(x, y), 255, 3);
    CHECK(medianFilter(a.surface(), 1));
    Img gray(21, 21);
    gray.fill(128, 128, 128, 255);
    CHECK(maxDiff(a, gray) == 0);

    Img edge(20, 10);
    for (int y = 0; y < 10; ++y)
        for (int x = 0; x < 20; ++x) {
            uint8_t* p = edge.at(x, y);
            p[0] = p[1] = p[2] = x < 10 ? 0 : 255; p[3] = 255;
        }
    const Img edgeRef = edge;
    CHECK(medianFilter(edge.surface(), 2));
    CHECK(maxDiff(edge, edgeRef) == 0); // une marche est un point fixe de la médiane
}

void testPixelate()
{
    std::printf("mosaïque: blocs uniformes, moyenne exacte, blocs partiels\n");
    Img a(10, 7);
    a.randomOpaque(5);
    const Img src = a;
    CHECK(pixelate(a.surface(), 4, 4));
    bool uniform = true, meanOk = true;
    for (int by = 0; by < 7; by += 4)
        for (int bx = 0; bx < 10; bx += 4) {
            const int x1 = std::min(10, bx + 4), y1 = std::min(7, by + 4);
            for (int c = 0; c < 3; ++c) {
                double mean = 0.0;
                for (int y = by; y < y1; ++y)
                    for (int x = bx; x < x1; ++x) mean += src.at(x, y)[c];
                mean /= (x1 - bx) * (y1 - by);
                for (int y = by; y < y1; ++y)
                    for (int x = bx; x < x1; ++x) {
                        uniform &= a.at(x, y)[c] == a.at(bx, by)[c];
                        meanOk &= std::fabs(a.at(x, y)[c] - mean) <= 0.51;
                    }
            }
        }
    CHECK(uniform);
    CHECK(meanOk);
    Img b(5, 5);
    CHECK(!pixelate(b.surface(), 0, 3));
}

// --------------------------------------------------- détection / relief -----

void testEdgeDetectAndEmboss()
{
    std::printf("contours et relief\n");
    Img flat(12, 12);
    flat.fill(77, 150, 210, 200);
    Img e = flat;
    CHECK(edgeDetect(e.surface()));
    bool zero = true, alphaOk = true;
    for (int i = 0; i < 12 * 12; ++i) {
        zero &= e.px[i * 4] == 0 && e.px[i * 4 + 1] == 0 && e.px[i * 4 + 2] == 0;
        alphaOk &= e.px[i * 4 + 3] == 200;
    }
    CHECK(zero && alphaOk);

    Img step(16, 8);
    for (int y = 0; y < 8; ++y)
        for (int x = 0; x < 16; ++x) {
            uint8_t* p = step.at(x, y);
            p[0] = p[1] = p[2] = x < 8 ? 0 : 255; p[3] = 255;
        }
    Img s1 = step, s2 = step;
    CHECK(edgeDetect(s1.surface(), 1.0));
    CHECK(edgeDetect(s2.surface(), 0.5));
    CHECK(s1.at(7, 4)[0] == 255 && s1.at(8, 4)[0] == 255); // plein contraste = 255
    CHECK(s1.at(2, 4)[0] == 0 && s1.at(13, 4)[0] == 0);
    CHECK(std::abs(s2.at(7, 4)[0] - 128) <= 1);

    Img em = step, emFlat = flat;
    CHECK(emboss(em.surface(), 0.0, 1.0));
    CHECK(emboss(emFlat.surface(), 45.0, 1.0));
    CHECK(emFlat.at(5, 5)[0] == 128); // aplat = gris moyen
    CHECK(em.at(7, 4)[0] > 200);      // montée dans le sens de la lumière
    Img emBack = step;
    CHECK(emboss(emBack.surface(), 180.0, 1.0));
    CHECK(emBack.at(7, 4)[0] < 60);   // descente : sombre
}

// ----------------------------------------------------------- couleur --------

void testInvertDesaturate()
{
    std::printf("inverser / désaturer\n");
    Img a(9, 9);
    a.randomOpaque(21);
    a.at(1, 1)[3] = 77;
    const Img ref = a;
    CHECK(invert(a.surface()));
    CHECK(a.at(3, 3)[0] == 255 - ref.at(3, 3)[0]);
    CHECK(a.at(1, 1)[3] == 77);
    CHECK(invert(a.surface()));
    CHECK(maxDiff(a, ref) == 0);

    Img g(4, 4);
    g.fill(90, 90, 90, 255);
    Img gRef = g;
    CHECK(desaturate(g.surface()));
    CHECK(maxDiff(g, gRef) == 0);
    Img c(2, 2);
    c.fill(255, 0, 0, 255);
    Img c2 = c, c3 = c;
    CHECK(desaturate(c.surface(), DesaturateMode::Luminance));
    CHECK(desaturate(c2.surface(), DesaturateMode::Average));
    CHECK(desaturate(c3.surface(), DesaturateMode::Lightness));
    CHECK(c.at(0, 0)[0] == 54 && c.at(0, 0)[1] == 54);   // 0.2126*255
    CHECK(c2.at(0, 0)[0] == 85);
    CHECK(c3.at(0, 0)[0] == 128);
}

void testHsv()
{
    std::printf("teinte / saturation / valeur\n");
    Img a(64, 64);
    a.randomOpaque(99);
    a.at(3, 3)[3] = 40;
    const Img ref = a;
    Img id = a;
    CHECK(hsvAdjust(id.surface(), 360.0, 0.0, 0.0));
    CHECK(maxDiff(id, ref) == 0);
    CHECK(hsvAdjust(a.surface(), 1e-9, 1e-15, 0.0)); // force la conversion aller-retour
    CHECK(maxDiff(a, ref) == 0);                      // et elle doit être exacte

    Img p(2, 2);
    p.fill(255, 0, 0, 255);
    Img g = p, b = p;
    CHECK(hsvAdjust(g.surface(), 120.0, 0.0, 0.0));
    CHECK(hsvAdjust(b.surface(), 240.0, 0.0, 0.0));
    CHECK(g.at(0, 0)[0] == 0 && g.at(0, 0)[1] == 255 && g.at(0, 0)[2] == 0);
    CHECK(b.at(0, 0)[0] == 0 && b.at(0, 0)[1] == 0 && b.at(0, 0)[2] == 255);
    Img neg = p;
    CHECK(hsvAdjust(neg.surface(), -120.0, 0.0, 0.0)); // = +240
    CHECK(neg.at(0, 0)[2] == 255);

    Img mix(8, 8);
    mix.randomOpaque(4);
    Img gray = mix, dark = mix;
    CHECK(hsvAdjust(gray.surface(), 0.0, -1.0, 0.0));
    CHECK(hsvAdjust(dark.surface(), 0.0, 0.0, -1.0));
    bool grayOk = true, darkOk = true;
    for (int i = 0; i < 64; ++i) {
        const uint8_t* q = &gray.px[static_cast<size_t>(i) * 4];
        grayOk &= q[0] == q[1] && q[1] == q[2];
        const uint8_t* d = &dark.px[static_cast<size_t>(i) * 4];
        darkOk &= d[0] == 0 && d[1] == 0 && d[2] == 0 && d[3] == 255;
    }
    CHECK(grayOk && darkOk);
}

void testPosterizeThreshold()
{
    std::printf("postériser / seuil\n");
    Img a(16, 16);
    for (int i = 0; i < 256; ++i) {
        uint8_t* p = &a.px[static_cast<size_t>(i) * 4];
        p[0] = p[1] = p[2] = static_cast<uint8_t>(i);
        p[3] = 255;
    }
    Img two = a, four = a, t = a;
    CHECK(posterize(two.surface(), 2));
    CHECK(posterize(four.surface(), 4));
    bool ok2 = true, ok4 = true, mono = true;
    for (int i = 0; i < 256; ++i) {
        const int v2 = two.px[static_cast<size_t>(i) * 4];
        const int v4 = four.px[static_cast<size_t>(i) * 4];
        ok2 &= v2 == 0 || v2 == 255;
        ok4 &= v4 == 0 || v4 == 85 || v4 == 170 || v4 == 255;
        if (i) mono &= v4 >= four.px[static_cast<size_t>(i - 1) * 4];
    }
    CHECK(ok2 && ok4 && mono);
    CHECK(!posterize(a.surface(), 1) && !posterize(a.surface(), 257));
    CHECK(threshold(t.surface(), 128));
    CHECK(t.px[127 * 4] == 0 && t.px[128 * 4] == 255);
}

void testNoise()
{
    std::printf("bruit: déterminisme, statistiques, monochrome\n");
    Img a(300, 300), b(300, 300), c(300, 300);
    a.fill(128, 128, 128, 255);
    b = a;
    c = a;
    NoiseOptions o;
    o.amount = 0.05;
    o.seed = 42;
    CHECK(addNoise(a.surface(), o));
    CHECK(addNoise(b.surface(), o));
    CHECK(maxDiff(a, b) == 0);
    o.seed = 43;
    CHECK(addNoise(c.surface(), o));
    CHECK(maxDiff(a, c) > 0);

    double sum = 0.0, sum2 = 0.0;
    const size_t n = 300u * 300u;
    for (size_t i = 0; i < n; ++i) {
        const double d = a.px[i * 4] - 128.0;
        sum += d;
        sum2 += d * d;
    }
    const double mean = sum / n, sd = std::sqrt(sum2 / n - mean * mean);
    std::printf("  gaussien: moyenne %.3f, écart-type %.3f (cible %.2f)\n", mean, sd, 0.05 * 255);
    CHECK(std::fabs(mean) < 0.3);
    CHECK(std::fabs(sd - 12.75) < 0.4);

    Img u(300, 300);
    u.fill(128, 128, 128, 255);
    NoiseOptions uo;
    uo.amount = 0.05;
    uo.gaussian = false;
    uo.monochrome = true;
    CHECK(addNoise(u.surface(), uo));
    double us = 0.0, us2 = 0.0;
    bool mono = true;
    for (size_t i = 0; i < n; ++i) {
        const double d = u.px[i * 4] - 128.0;
        us += d;
        us2 += d * d;
        mono &= u.px[i * 4] == u.px[i * 4 + 1] && u.px[i * 4 + 1] == u.px[i * 4 + 2];
        mono &= u.px[i * 4 + 3] == 255;
    }
    const double um = us / n, usd = std::sqrt(us2 / n - um * um);
    std::printf("  uniforme: moyenne %.3f, écart-type %.3f\n", um, usd);
    CHECK(mono);
    CHECK(std::fabs(um) < 0.3 && std::fabs(usd - 12.75) < 0.5);
}

void testColorToAlpha()
{
    std::printf("couleur vers alpha: reconstruction exacte sur la clé\n");
    const uint8_t keys[3][3] = {{255, 255, 255}, {0, 0, 0}, {128, 64, 200}};
    for (const auto& key : keys) {
        Img a(64, 64);
        a.randomOpaque(1234);
        const Img src = a;
        CHECK(colorToAlpha(a.surface(), key[0], key[1], key[2]));
        int worst = 0;
        for (int i = 0; i < 64 * 64; ++i) {
            const uint8_t* n = &a.px[static_cast<size_t>(i) * 4];
            const uint8_t* s = &src.px[static_cast<size_t>(i) * 4];
            const double alpha = n[3] / 255.0;
            for (int c = 0; c < 3; ++c) {
                const double back = n[c] * alpha + key[c] * (1.0 - alpha);
                worst = std::max(worst, static_cast<int>(std::lround(std::fabs(back - s[c]))));
            }
        }
        std::printf("  clé (%d,%d,%d): erreur de reconstruction max %d\n", key[0], key[1], key[2], worst);
        CHECK(worst <= 2);
    }
    Img w(4, 4);
    w.fill(255, 255, 255, 255);
    Img k = w;
    CHECK(colorToAlpha(w.surface(), 255, 255, 255));
    CHECK(w.at(1, 1)[3] == 0);
    Img black(2, 2);
    black.fill(0, 0, 0, 255);
    CHECK(colorToAlpha(black.surface(), 255, 255, 255));
    CHECK(black.at(0, 0)[3] == 255 && black.at(0, 0)[0] == 0);
    Img near(2, 2);
    near.fill(250, 250, 250, 255);
    CHECK(colorToAlpha(near.surface(), 255, 255, 255, 0.5));
    CHECK(near.at(0, 0)[3] == 0); // sous la tolérance : transparent
    // alpha d'entrée respecté
    Img half(2, 2);
    half.fill(0, 0, 0, 100);
    CHECK(colorToAlpha(half.surface(), 255, 255, 255));
    CHECK(half.at(0, 0)[3] == 100);
    (void)k;
}

// ------------------------------------------------------------------ LUT -----

void testLuts()
{
    std::printf("LUT: niveaux, luminosité/contraste, courbes\n");
    uint8_t lut[256];
    buildLevelsLut(0, 255, 1.0, 0, 255, lut);
    bool identity = true;
    for (int i = 0; i < 256; ++i) identity &= lut[i] == i;
    CHECK(identity);
    buildLevelsLut(0, 255, 2.0, 0, 255, lut);
    CHECK(lut[128] > 170 && lut[0] == 0 && lut[255] == 255);
    buildLevelsLut(0, 255, 1.0, 255, 0, lut);
    CHECK(lut[0] == 255 && lut[255] == 0);
    buildLevelsLut(50, 200, 1.0, 0, 255, lut);
    CHECK(lut[50] == 0 && lut[200] == 255 && lut[10] == 0 && lut[250] == 255);
    buildLevelsLut(200, 50, 1.0, 0, 255, lut); // entrées incohérentes : pas de crash
    CHECK(lut[0] == 0 && lut[255] == 255);

    buildBrightnessContrastLut(0.0, 0.0, lut);
    identity = true;
    for (int i = 0; i < 256; ++i) identity &= lut[i] == i;
    CHECK(identity);
    buildBrightnessContrastLut(0.2, 0.0, lut);
    CHECK(lut[100] > 100);
    buildBrightnessContrastLut(0.0, -1.0, lut);
    CHECK(lut[0] == 128 && lut[255] == 128);
    buildBrightnessContrastLut(0.0, 0.5, lut);
    CHECK(lut[64] < 64 && lut[192] > 192);

    const double idx[2] = {0.0, 1.0}, idy[2] = {0.0, 1.0};
    CHECK(buildCurveLut(idx, idy, 2, lut));
    identity = true;
    for (int i = 0; i < 256; ++i) identity &= lut[i] == i;
    CHECK(identity);
    const double cx[3] = {0.0, 128.0 / 255.0, 1.0}, cy[3] = {0.0, 0.75, 1.0};
    CHECK(buildCurveLut(cx, cy, 3, lut));
    CHECK(lut[128] == 191); // passe par le point de contrôle
    bool monotone = true;
    for (int i = 1; i < 256; ++i) monotone &= lut[i] >= lut[i - 1];
    CHECK(monotone && lut[0] == 0 && lut[255] == 255);
    const double sx[5] = {0.0, 0.2, 0.4, 0.8, 1.0}, sy[5] = {0.0, 0.05, 0.9, 0.95, 1.0};
    CHECK(buildCurveLut(sx, sy, 5, lut)); // forte pente : ne doit pas déborder
    monotone = true;
    for (int i = 1; i < 256; ++i) monotone &= lut[i] >= lut[i - 1];
    CHECK(monotone);
    const double bx[3] = {0.5, 0.2, 1.0};
    CHECK(!buildCurveLut(bx, cy, 3, lut));
    CHECK(lut[77] == 77); // reste l'identité
    const double px[2] = {0.25, 0.75}, py[2] = {0.3, 0.6};
    CHECK(buildCurveLut(px, py, 2, lut));
    CHECK(lut[0] == static_cast<uint8_t>(std::lround(0.3 * 255)) &&
          lut[255] == static_cast<uint8_t>(std::lround(0.6 * 255)));
}

void testMasks()
{
    std::printf("masque: 0 = intact, 255 = plein, intermédiaire = mélange\n");
    Img base(12, 4);
    base.randomOpaque(8);
    Img full = base;
    CHECK(invert(full.surface()));

    std::vector<uint8_t> mask(12 * 4, 0);
    for (int y = 0; y < 4; ++y) {
        for (int x = 4; x < 8; ++x) mask[static_cast<size_t>(y) * 12 + x] = 255;
        mask[static_cast<size_t>(y) * 12 + 8] = 128;
    }
    Img a = base;
    Mask m{mask.data(), 12};
    CHECK(invert(a.surface(), m));
    bool zeroOk = true, fullOk = true, halfOk = true;
    for (int y = 0; y < 4; ++y) {
        for (int x = 0; x < 12; ++x)
            for (int c = 0; c < 4; ++c) {
                const int o = base.at(x, y)[c], f = full.at(x, y)[c], r = a.at(x, y)[c];
                if (x < 4 || x > 8) zeroOk &= r == o;
                if (x >= 4 && x < 8) fullOk &= r == f;
                if (x == 8) halfOk &= std::abs(r - (o + (f - o) * 128 / 255.0)) <= 1.0;
            }
    }
    CHECK(zeroOk && fullOk && halfOk);

    // Le masque s'applique aussi aux flous (pixel non couvert : octets identiques,
    // même transparents avec RGB ≠ 0).
    Img t(10, 4);
    t.randomOpaque(2);
    t.at(0, 0)[3] = 0;
    const Img tRef = t;
    std::vector<uint8_t> none(10 * 4, 0);
    CHECK(gaussianBlur(t.surface(), 3.0, 3.0, EdgeMode::Clamp, Mask{none.data(), 10}));
    CHECK(maxDiff(t, tRef) == 0);
    // Stride de masque invalide
    CHECK(!invert(t.surface(), Mask{none.data(), 5}));
}

void testInvalidArguments()
{
    std::printf("arguments invalides: refus sans modification\n");
    Img a(8, 8);
    a.randomOpaque(6);
    const Img ref = a;
    Surface bad = a.surface();
    bad.pixels = nullptr;
    CHECK(!gaussianBlur(bad, 1, 1));
    bad = a.surface();
    bad.stride = 8 * 4 - 1;
    CHECK(!invert(bad));
    bad = a.surface();
    bad.width = 0;
    CHECK(!invert(bad));
    CHECK(!gaussianBlur(a.surface(), -1.0, 1.0));
    CHECK(!gaussianBlur(a.surface(), std::nan(""), 1.0));
    CHECK(!boxBlur(a.surface(), -1, 0));
    CHECK(!motionBlur(a.surface(), 0.0, -3.0));
    CHECK(!unsharpMask(a.surface(), 1.0, 1.0, 300));
    CHECK(!medianFilter(a.surface(), 9));
    CHECK(!hsvAdjust(a.surface(), std::nan(""), 0, 0));
    CHECK(!colorToAlpha(a.surface(), 0, 0, 0, 2.0));
    CHECK(!applyLut(a.surface(), nullptr, nullptr, nullptr));
    NoiseOptions bo;
    bo.amount = -1.0;
    CHECK(!addNoise(a.surface(), bo));
    CHECK(maxDiff(a, ref) == 0);
    // Sigma nul = no-op valide
    CHECK(gaussianBlur(a.surface(), 0.0, 0.0));
    CHECK(maxDiff(a, ref) == 0);
}

void testStrideRespected()
{
    std::printf("stride: les octets de remplissage ne sont jamais touchés\n");
    const int w = 7, h = 5, stride = 7 * 4 + 12;
    std::vector<uint8_t> buf(static_cast<size_t>(stride) * h, 0xAB);
    std::mt19937 rng(1);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            uint8_t* p = &buf[static_cast<size_t>(y) * stride + x * 4];
            p[0] = rng() & 255; p[1] = rng() & 255; p[2] = rng() & 255; p[3] = 255;
        }
    Surface s{buf.data(), w, h, stride};
    CHECK(gaussianBlur(s, 1.5, 1.5, EdgeMode::Wrap));
    CHECK(medianFilter(s, 1));
    CHECK(pixelate(s, 3, 2));
    CHECK(edgeDetect(s));
    CHECK(motionBlur(s, 30.0, 5.0));
    bool pad = true;
    for (int y = 0; y < h; ++y)
        for (int i = w * 4; i < stride; ++i) pad &= buf[static_cast<size_t>(y) * stride + i] == 0xAB;
    CHECK(pad);
}

// Empreinte pour comparer les exécutions mono/multi-thread depuis un script.
// ------------------------------------------------ couleur sélective -------

// Référence indépendante, en double précision et écrite d'après la description
// (pas d'après le noyau) : teinte par HSV classique, poids triangulaire de 45°.
void referenceSelective(const SelectiveColorParams& p, const uint8_t* in, uint8_t* out)
{
    double c[3] = {in[0] / 255.0, in[1] / 255.0, in[2] / 255.0};
    const double mx = std::max(c[0], std::max(c[1], c[2]));
    const double mn = std::min(c[0], std::min(c[1], c[2]));
    const double d = mx - mn;
    double hue = 0.0;
    if (d > 1e-8) {
        if (mx == c[0]) hue = std::fmod((c[1] - c[2]) / d + 6.0, 6.0);
        else if (mx == c[1]) hue = (c[2] - c[0]) / d + 2.0;
        else hue = (c[0] - c[1]) / d + 4.0;
    }
    hue *= 60.0;
    const double sat = mx > 1e-8 ? d / mx : 0.0;
    const double lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    auto apply = [&](int band, double w) {
        for (int k = 0; k < 3; ++k) c[k] += w * (-(p.band[band][k] / 100.0) * (1.0 - c[k]));
        const double f = std::min(1.0, std::max(0.0, 1.0 - w * p.band[band][3] / 100.0));
        for (int k = 0; k < 3; ++k) c[k] *= f;
    };
    for (int b = 0; b < 6; ++b) {
        if (!p.enabled[b]) continue;
        double dist = std::fmod(std::fabs(hue - 60.0 * b), 360.0);
        dist = std::min(dist, 360.0 - dist);
        apply(b, std::max(0.0, 1.0 - dist / 45.0) * sat);
    }
    if (p.enabled[kBandWhites] && lum >= 0.75) apply(kBandWhites, 1.0 - sat);
    if (p.enabled[kBandNeutrals] && sat <= 0.25) apply(kBandNeutrals, 1.0);
    if (p.enabled[kBandBlacks] && lum <= 0.25) apply(kBandBlacks, 1.0 - sat);
    for (int k = 0; k < 3; ++k)
        out[k] = static_cast<uint8_t>(std::lround(std::min(1.0, std::max(0.0, c[k])) * 255.0));
    out[3] = in[3];
}

SelectiveColorParams sampleSelective()
{
    SelectiveColorParams p;
    const float v[kSelectiveBandCount][4] = {
        {-40, 10, 5, 0}, {20, -30, 0, 10}, {0, 25, -25, 0}, {50, 0, 0, -10}, {-15, -15, 40, 5},
        {30, 30, -30, 0}, {0, 0, 20, -20}, {10, -10, 10, 10}, {-20, 0, 0, 30}};
    std::memcpy(p.band, v, sizeof v);
    for (int b = 0; b < kSelectiveBandCount; ++b) p.enabled[b] = true;
    return p;
}

void testSelectiveColor()
{
    // 1. Aucune bande active : identité exacte, alpha compris.
    {
        Img a(19, 13), b(19, 13);
        a.randomOpaque(11);
        for (size_t i = 3; i < a.px.size(); i += 4) a.px[i] = static_cast<uint8_t>(i * 7);
        b.px = a.px;
        SelectiveColorParams none;
        CHECK(selectiveColor(a.surface(), none));
        CHECK(maxDiff(a, b) == 0);
        // Bandes valorisées mais désactivées : toujours l'identité.
        SelectiveColorParams off = sampleSelective();
        for (bool& e : off.enabled) e = false;
        CHECK(selectiveColor(a.surface(), off));
        CHECK(maxDiff(a, b) == 0);
    }
    // 2. Toutes les couleurs 8 bits primaires/secondaires + aléatoire : noyau float32
    //    contre la référence double.  Les deux arrondissent différemment aux
    //    demi-valeurs, donc l'écart toléré est d'un niveau ; on borne aussi la
    //    fréquence de cet écart.
    {
        Img a(257, 129);
        a.randomOpaque(5);
        for (size_t i = 3; i < a.px.size(); i += 4) a.px[i] = static_cast<uint8_t>(i * 13);
        Img expect = a;
        const SelectiveColorParams p = sampleSelective();
        for (size_t i = 0; i < a.px.size(); i += 4) referenceSelective(p, &a.px[i], &expect.px[i]);
        // Les bandes de tons ont des seuils francs (saturation <= 0,25, luminance
        // <= 0,25 ou >= 0,75) : pile sur le seuil, float32 et double tombent de
        // part et d'autre.  Ces pixels-là sont exclus de la comparaison ; le seuil
        // lui-même est vérifié plus bas.
        auto nearThreshold = [](const uint8_t* q) {
            const double r = q[0] / 255.0, g = q[1] / 255.0, b = q[2] / 255.0;
            const double mx = std::max(r, std::max(g, b)), mn = std::min(r, std::min(g, b));
            const double sat = mx > 0 ? (mx - mn) / mx : 0.0;
            const double lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            return std::fabs(sat - 0.25) < 1e-4 || std::fabs(lum - 0.25) < 1e-4 ||
                   std::fabs(lum - 0.75) < 1e-4;
        };
        Img before = a;
        CHECK(selectiveColor(a.surface(), p));
        size_t compared = 0, off = 0;
        int worst = 0;
        for (size_t i = 0; i < a.px.size(); i += 4) {
            if (nearThreshold(&before.px[i])) continue;
            ++compared;
            int d = 0;
            for (int k = 0; k < 4; ++k) d = std::max(d, std::abs(a.px[i + k] - expect.px[i + k]));
            worst = std::max(worst, d);
            off += d != 0;
        }
        CHECK(compared > a.px.size() / 4 * 9 / 10);
        CHECK(worst <= 1);
        CHECK(off * 100 < compared); // < 1 % des pixels diffèrent d'un niveau
    }
    // 3. Chaque bande isolée n'agit que sur ses pixels : du rouge pur ne bouge pas
    //    sous « bleus », mais bouge sous « rouges ».
    {
        Img px(1, 1);
        px.fill(230, 20, 20, 255);
        SelectiveColorParams p;
        p.enabled[kBandBlues] = true;
        p.band[kBandBlues][0] = 80; p.band[kBandBlues][3] = 50;
        Img before = px;
        CHECK(selectiveColor(px.surface(), p));
        CHECK(maxDiff(px, before) == 0);
        SelectiveColorParams q;
        q.enabled[kBandReds] = true;
        q.band[kBandReds][0] = 80; // moins de rouge (cyan +)
        CHECK(selectiveColor(px.surface(), q));
        CHECK(px.px[0] < before.px[0]);
        CHECK(px.px[3] == 255);
    }
    // 4. Gris pur : saturation nulle, donc aucune bande de teinte ni blancs/noirs ;
    //    seule « neutres » agit (poids 1).
    {
        Img px(1, 1);
        px.fill(128, 128, 128, 200);
        SelectiveColorParams p = sampleSelective();
        for (int b : {kBandReds, kBandYellows, kBandGreens, kBandCyans, kBandBlues,
                      kBandMagentas, kBandWhites, kBandBlacks}) p.enabled[b] = false;
        Img ref = px;
        referenceSelective(p, ref.at(0, 0), ref.at(0, 0));
        CHECK(selectiveColor(px.surface(), p));
        CHECK(maxDiff(px, ref) <= 1);
        CHECK(px.px[3] == 200);
    }
    // 5. Le noir (k > 0) assombrit ; k < 0 est sans effet ; jamais hors 0..255.
    {
        Img px(1, 1);
        px.fill(255, 255, 255, 255);
        SelectiveColorParams p;
        p.enabled[kBandNeutrals] = true;
        p.band[kBandNeutrals][3] = 100;
        CHECK(selectiveColor(px.surface(), p));
        CHECK(px.px[0] == 0 && px.px[1] == 0 && px.px[2] == 0);
        // Comportement historique conservé : le facteur noir est borné à 1, un noir
        // négatif n'éclaircit donc pas (il n'y a pas de « moins de noir »).
        p.band[kBandNeutrals][3] = -500;
        px.fill(10, 20, 30, 255);
        px.px[2] = 20; // neutre : saturation <= 0,25
        Img same = px;
        CHECK(selectiveColor(px.surface(), p));
        CHECK(maxDiff(px, same) == 0);
    }
    // 5b. Le seuil « neutres » est inclusif : saturation exactement 0,25 (200,150,150
    //     -> (200-150)/200) est neutre, un peu plus saturé ne l'est plus.
    {
        SelectiveColorParams p;
        p.enabled[kBandNeutrals] = true;
        p.band[kBandNeutrals][3] = 100; // noir plein : le pixel neutre devient noir
        Img on(1, 1), over(1, 1);
        on.fill(200, 150, 150, 255);
        over.fill(200, 149, 149, 255);
        CHECK(selectiveColor(on.surface(), p));
        CHECK(selectiveColor(over.surface(), p));
        CHECK(on.px[0] == 0);
        CHECK(over.px[0] == 200);
    }
    // 6. Masque : moitié de couverture = mélange, zéro = intact.
    {
        Img a(8, 8), b(8, 8), c(8, 8);
        a.randomOpaque(3);
        b.px = a.px;
        c.px = a.px;
        std::vector<uint8_t> zero(64, 0), full(64, 255);
        const SelectiveColorParams p = sampleSelective();
        CHECK(selectiveColor(b.surface(), p, Mask{zero.data(), 8}));
        CHECK(maxDiff(a, b) == 0);
        CHECK(selectiveColor(a.surface(), p));
        CHECK(selectiveColor(c.surface(), p, Mask{full.data(), 8}));
        CHECK(maxDiff(a, c) == 0);
    }
    // 7. Stride > width : le remplissage entre lignes n'est jamais touché.
    {
        const int w = 5, h = 4, stride = w * 4 + 12;
        std::vector<uint8_t> buf(static_cast<size_t>(stride) * h, 0xAB);
        std::mt19937 rng(9);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w * 4; ++x) buf[static_cast<size_t>(y) * stride + x] = rng() & 255;
        std::vector<uint8_t> pad = buf;
        Surface s{buf.data(), w, h, stride};
        CHECK(selectiveColor(s, sampleSelective()));
        for (int y = 0; y < h; ++y)
            for (int x = w * 4; x < stride; ++x)
                CHECK(buf[static_cast<size_t>(y) * stride + x] == 0xAB);
    }
    // 8. Arguments invalides : refus sans modification.
    {
        Img a(4, 4);
        a.randomOpaque(1);
        Img b = a;
        SelectiveColorParams bad = sampleSelective();
        bad.band[2][1] = std::nanf("");
        CHECK(!selectiveColor(a.surface(), bad));
        bad.band[2][1] = INFINITY;
        CHECK(!selectiveColor(a.surface(), bad));
        CHECK(maxDiff(a, b) == 0);
        Surface empty{};
        CHECK(!selectiveColor(empty, sampleSelective()));
    }
    // 9. Déterminisme et pixel par pixel : évaluer par bandes horizontales donne
    //    exactement l'image entière (le noyau est ponctuel).
    {
        Img whole(37, 23);
        whole.randomOpaque(21);
        Img parts = whole;
        const SelectiveColorParams p = sampleSelective();
        CHECK(selectiveColor(whole.surface(), p));
        for (int y = 0; y < parts.h; y += 5) {
            const int rows = std::min(5, parts.h - y);
            Surface s{parts.at(0, y), parts.w, rows, parts.w * 4};
            CHECK(selectiveColor(s, p));
        }
        CHECK(maxDiff(whole, parts) == 0);
    }
}

// ------------------------------------------------ calques de réglage -------

void testAdjustmentKernels()
{
    // Identité : paramètres neutres, alpha intact.
    {
        Img a(31, 17), b(31, 17);
        a.randomOpaque(21);
        for (size_t i = 3; i < a.px.size(); i += 4) a.px[i] = static_cast<uint8_t>(i * 5);
        b.px = a.px;
        CHECK(hueSaturation(a.surface(), 0.0, 0.0, 0.0));
        for (size_t i = 3; i < a.px.size(); i += 4) CHECK(a.px[i] == b.px[i]);
        CHECK(maxDiff(a, b) <= 1); // aller-retour HSV : au plus un niveau
        ColorBalanceParams none;
        Img c = b;
        CHECK(colorBalance(c.surface(), none));
        CHECK(maxDiff(c, b) == 0);
    }
    // Rotation de teinte de 120° : rouge -> vert, vert -> bleu.
    {
        Img a(2, 1);
        a.at(0, 0)[0] = 255; a.at(0, 0)[3] = 255;
        a.at(1, 0)[1] = 255; a.at(1, 0)[3] = 255;
        CHECK(hueSaturation(a.surface(), 120.0, 0.0, 0.0));
        CHECK(a.at(0, 0)[0] == 0 && a.at(0, 0)[1] == 255 && a.at(0, 0)[2] == 0);
        CHECK(a.at(1, 0)[0] == 0 && a.at(1, 0)[1] == 0 && a.at(1, 0)[2] == 255);
    }
    // Désaturation totale : gris (R = G = B) ; vibrance -100 %% sans effet sur un gris.
    {
        Img a(9, 9);
        a.randomOpaque(3);
        CHECK(hueSaturation(a.surface(), 0.0, -100.0, 0.0));
        bool grey = true;
        for (int y = 0; y < 9; ++y)
            for (int x = 0; x < 9; ++x) grey = grey && a.at(x, y)[0] == a.at(x, y)[1] && a.at(x, y)[1] == a.at(x, y)[2];
        CHECK(grey);
        Img b = a;
        CHECK(vibrance(a.surface(), 100.0, 0.0));
        CHECK(maxDiff(a, b) == 0);
    }
    // Balance : le décalage des ombres n'atteint pas le blanc, celui des hautes lumières pas le noir.
    {
        Img a(2, 1);
        a.at(0, 0)[3] = 255;                                   // noir
        a.at(1, 0)[0] = a.at(1, 0)[1] = a.at(1, 0)[2] = 255; a.at(1, 0)[3] = 255;
        ColorBalanceParams p;
        p.shadows[0] = 50.0f;
        CHECK(colorBalance(a.surface(), p));
        CHECK(a.at(0, 0)[0] == 128 && a.at(0, 0)[1] == 0);     // 0.5 * 255 arrondi
        CHECK(a.at(1, 0)[0] == 255);
    }
    // Mélange par luminosité : m = 0 rend la source, amount 1 rend le réglage.
    {
        Img src(13, 7), adj(13, 7), out(13, 7);
        src.randomOpaque(8);
        for (size_t i = 3; i < src.px.size(); i += 4) src.px[i] = static_cast<uint8_t>(i);
        adj.fill(10, 20, 30, 99);
        out.px = adj.px;
        CHECK(luminosityBlend(out.surface(), src.px.data(), src.w * 4, LuminosityMode::Flat, 0.0, 0.5, false));
        for (int y = 0; y < 7; ++y)
            for (int x = 0; x < 13; ++x)
                CHECK(std::equal(out.at(x, y), out.at(x, y) + 4, src.at(x, y)));
        out.px = adj.px;
        CHECK(luminosityBlend(out.surface(), src.px.data(), src.w * 4, LuminosityMode::Flat, 1.0, 0.5, false));
        for (int y = 0; y < 7; ++y)
            for (int x = 0; x < 13; ++x)
                CHECK(out.at(x, y)[0] == 10 && out.at(x, y)[1] == 20 && out.at(x, y)[3] == src.at(x, y)[3]);
        // Arguments invalides.
        CHECK(!luminosityBlend(out.surface(), nullptr, src.w * 4, LuminosityMode::Flat, 1.0, 0.5, false));
        CHECK(!luminosityBlend(out.surface(), src.px.data(), src.w * 4 - 1, LuminosityMode::Flat, 1.0, 0.5, false));
    }
    // Paramètres non finis refusés, image intacte.
    {
        Img a(4, 4), b(4, 4);
        a.randomOpaque(1);
        b.px = a.px;
        CHECK(!hueSaturation(a.surface(), std::nan(""), 0.0, 0.0));
        CHECK(!vibrance(a.surface(), 0.0, HUGE_VAL));
        ColorBalanceParams bad;
        bad.midtones[1] = std::numeric_limits<float>::infinity();
        CHECK(!colorBalance(a.surface(), bad));
        CHECK(maxDiff(a, b) == 0);
    }
}

void testLayerEffects()
{
    // Contour : un carré opaque 4x4 dans 20x20, contour de 2 px.
    Img a(20, 20);
    for (int y = 8; y < 12; ++y)
        for (int x = 8; x < 12; ++x) { a.at(x, y)[0] = 50; a.at(x, y)[3] = 255; }
    Img before = a;
    LayerEffectParams p;
    p.size = 2;
    p.color[0] = 255; p.color[1] = 0; p.color[2] = 0; p.color[3] = 255;
    CHECK(outlineStroke(a.surface(), p));
    CHECK(a.at(9, 9)[0] == 50);                                  // intérieur intact
    CHECK(a.at(6, 6)[0] == 255 && a.at(6, 6)[3] == 255);         // coin (dilatation carrée)
    CHECK(a.at(5, 5)[3] == 0 && a.at(14, 14)[3] == 0);           // hors de portée
    CHECK(a.at(8, 8)[3] == 255 && a.at(8, 8)[0] == 50);          // forme d'origine intacte
    // Ombre : décalée vers le bas-droite, placée sous le calque.
    Img s = before;
    LayerEffectParams q;
    q.offsetX = 3; q.offsetY = 3; q.size = 1;
    q.color[0] = 0; q.color[1] = 0; q.color[2] = 0; q.color[3] = 255;
    CHECK(dropShadow(s.surface(), q));
    for (int y = 8; y < 12; ++y)
        for (int x = 8; x < 12; ++x) CHECK(s.at(x, y)[0] == 50 && s.at(x, y)[3] == 255);
    CHECK(s.at(13, 13)[3] > 0);                                  // ombre visible sous le décalage
    CHECK(s.at(2, 2)[3] == 0);                                   // rien de l'autre côté
    // Coins et minuscules images : aucun accès hors borne (ASan/UBSan).
    for (int w : {1, 2, 3}) {
        Img t(w, w);
        t.fill(9, 9, 9, 200);
        LayerEffectParams big;
        big.size = 32; big.offsetX = -50; big.offsetY = 50;
        CHECK(dropShadow(t.surface(), big));
        CHECK(outlineStroke(t.surface(), big));
    }
    // Arguments invalides.
    Img u(4, 4);
    LayerEffectParams bad;
    bad.size = 0;
    CHECK(!dropShadow(u.surface(), bad));
    bad.size = 33;
    CHECK(!outlineStroke(u.surface(), bad));
    CHECK(!dropShadow(Surface{}, LayerEffectParams{}));
}

void testSelectionKernels()
{
    // Tailles minuscules et rayons énormes : aucun accès hors borne (ASan/UBSan).
    for (int w : {1, 2, 5}) {
        for (int h : {1, 3}) {
            for (int r : {1, 2, 100}) {
                Img a(w, h);
                a.randomOpaque(w * 31 + h * 7 + r);
                CHECK(selectionFeather(a.surface(), r));
                CHECK(selectionMorph(a.surface(), r, true));
                CHECK(selectionMorph(a.surface(), r, false));
            }
        }
    }
    // Dilatation d'un point : carré (2r+1)² ; érosion de ce carré : le point.
    {
        Img a(15, 15);
        a.at(7, 7)[3] = 255;
        CHECK(selectionMorph(a.surface(), 2, true));
        CHECK(a.at(5, 5)[3] == 255 && a.at(9, 9)[3] == 255 && a.at(4, 7)[3] == 0 && a.at(7, 10)[3] == 0);
        CHECK(a.at(5, 5)[0] == 255 && a.at(5, 5)[2] == 255); // valeur dans les quatre octets
        CHECK(selectionMorph(a.surface(), 2, false));
        CHECK(a.at(7, 7)[3] == 255 && a.at(6, 7)[3] == 0);
    }
    // Un aplat 255 flouté reste 255 à l'intérieur ; un aplat 0 reste 0.
    {
        Img a(21, 21);
        for (int y = 0; y < 21; ++y) for (int x = 0; x < 21; ++x) a.at(x, y)[3] = 255;
        CHECK(selectionFeather(a.surface(), 4));
        CHECK(a.at(10, 10)[3] == 255 && a.at(0, 0)[3] == 255);   // bords répliqués
    }
    // Couleur : même couleur = 255, très différente = 0, alpha de la source ignoré.
    {
        Img src(2, 1), m(2, 1);
        src.at(0, 0)[0] = 10; src.at(0, 0)[1] = 20; src.at(0, 0)[2] = 30; src.at(0, 0)[3] = 0;
        src.at(1, 0)[0] = 255; src.at(1, 0)[1] = 255; src.at(1, 0)[2] = 255; src.at(1, 0)[3] = 255;
        CHECK(selectColorRange(m.surface(), src.px.data(), src.w * 4, 10, 20, 30, 16));
        CHECK(m.at(0, 0)[3] == 255 && m.at(1, 0)[3] == 0);
        CHECK(!selectColorRange(m.surface(), src.px.data(), src.w * 4, 256, 0, 0, 16));
        CHECK(!selectColorRange(m.surface(), nullptr, src.w * 4, 0, 0, 0, 16));
    }
    // Écrêtage : masque 0 = base, masque 255 = réglé, alpha de la base conservé.
    {
        Img base(2, 1), changed(2, 1), clip(2, 1);
        base.fill(100, 100, 100, 77);
        changed.fill(200, 0, 50, 255);
        clip.at(0, 0)[3] = 0;
        clip.at(1, 0)[3] = 255;
        CHECK(blendByAlpha(base.surface(), changed.px.data(), changed.w * 4, clip.px.data(), clip.w * 4));
        CHECK(base.at(0, 0)[0] == 100 && base.at(1, 0)[0] == 200 && base.at(1, 0)[2] == 50);
        CHECK(base.at(0, 0)[3] == 77 && base.at(1, 0)[3] == 77);
        CHECK(!blendByAlpha(base.surface(), changed.px.data(), 4, clip.px.data(), clip.w * 4));
    }
    CHECK(!selectionFeather(Surface{}, 3));
    Img z(3, 3);
    CHECK(!selectionFeather(z.surface(), 0) && !selectionMorph(z.surface(), 0, true));
}

void printDeterminismDigest()
{
    Img a(97, 61);
    a.randomOpaque(31337);
    Img b = a, c = a, d = a, e = a;
    gaussianBlur(a.surface(), 3.0, 2.0, EdgeMode::Wrap);
    gaussianBlur(b.surface(), 11.0, 9.0, EdgeMode::Clamp);
    medianFilter(c.surface(), 2);
    NoiseOptions o;
    o.amount = 0.1;
    o.seed = 9;
    addNoise(d.surface(), o);
    unsharpMask(e.surface(), 2.0, 1.5, 3);
    motionBlur(e.surface(), 17.0, 11.0, EdgeMode::Wrap);
    std::printf("DIGEST %016llx %016llx %016llx %016llx %016llx\n",
                static_cast<unsigned long long>(checksum(a)), static_cast<unsigned long long>(checksum(b)),
                static_cast<unsigned long long>(checksum(c)), static_cast<unsigned long long>(checksum(d)),
                static_cast<unsigned long long>(checksum(e)));
}

} // namespace

int main()
{
    testBlurKeepsConstantImages();
    testBlurHasNoDarkFringe();
    testGaussianImpulse();
    testBoxApproximationOfGaussian();
    testWrapIsShiftEquivariant();
    testTinyImagesAndHugeRadii();
    testMotionBlur();
    testUnsharp();
    testMedian();
    testPixelate();
    testEdgeDetectAndEmboss();
    testInvertDesaturate();
    testHsv();
    testPosterizeThreshold();
    testNoise();
    testColorToAlpha();
    testLuts();
    testMasks();
    testInvalidArguments();
    testStrideRespected();
    testSelectiveColor();
    testAdjustmentKernels();
    testLayerEffects();
    testSelectionKernels();
    printDeterminismDigest();
    std::printf("\n%d vérifications, %d échec(s)\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
