#include "image_filters.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <utility>
#include <vector>

#if defined(_MSC_VER)
#define CC_PRAGMA(x) __pragma(x)
#else
#define CC_PRAGMA(x) _Pragma(#x)
#endif

#ifdef _OPENMP
#define CC_OMP_FOR CC_PRAGMA(omp parallel for schedule(static))
// Small surfaces (64 px projection tiles) cost more to hand to a thread team
// than to process: waking OpenMP threads took ~1 ms per call.
#define CC_OMP_FOR_SIZED(pixels) CC_PRAGMA(omp parallel for schedule(static) if((pixels) >= 65536))
#define CC_OMP_PARALLEL CC_PRAGMA(omp parallel)
#define CC_OMP_PARALLEL_SIZED(pixels) CC_PRAGMA(omp parallel if((pixels) >= 65536))
#define CC_OMP_WORKSHARE CC_PRAGMA(omp for schedule(static))
#else
#define CC_OMP_FOR
#define CC_OMP_FOR_SIZED(pixels)
#define CC_OMP_PARALLEL
#define CC_OMP_PARALLEL_SIZED(pixels)
#define CC_OMP_WORKSHARE
#endif

namespace cc {
namespace filters {

namespace {

constexpr double kPi = 3.14159265358979323846;

// ---------------------------------------------------------------- utilitaires

inline int edgeIndex(int i, int n, EdgeMode mode)
{
    if (i >= 0 && i < n) return i;
    if (mode == EdgeMode::Wrap) {
        i %= n;
        return i < 0 ? i + n : i;
    }
    return i < 0 ? 0 : n - 1;
}

inline uint8_t toByte(double v)
{
    if (!(v > 0.0)) return 0; // capture aussi NaN
    if (v >= 255.0) return 255;
    return static_cast<uint8_t>(v + 0.5);
}

inline uint8_t unitToByte(double v) { return toByte(v * 255.0); }

bool argsOk(const Surface& s, const Mask& m)
{
    if (!s.valid()) return false;
    if (m.data && static_cast<long long>(m.stride) < s.width) return false;
    return true;
}

inline size_t idx4(int x, int y, int w)
{
    return (static_cast<size_t>(y) * static_cast<size_t>(w) + static_cast<size_t>(x)) * 4u;
}

// Calcule `out` à partir du pixel courant ; le mélange sous masque est fait ici,
// donc chaque filtre n'a à produire que le pixel « plein ».
template <class F>
void forEachPixel(const Surface& s, const Mask& m, F&& f)
{
    CC_OMP_FOR_SIZED(static_cast<long long>(s.width) * s.height)
    for (int y = 0; y < s.height; ++y) {
        uint8_t* row = s.pixels + static_cast<size_t>(y) * static_cast<size_t>(s.stride);
        const uint8_t* mrow =
            m.data ? m.data + static_cast<size_t>(y) * static_cast<size_t>(m.stride)
                   : nullptr;
        for (int x = 0; x < s.width; ++x) {
            const uint8_t coverage = mrow ? mrow[x] : 255;
            if (coverage == 0) continue;
            uint8_t* px = row + static_cast<size_t>(x) * 4u;
            uint8_t out[4];
            f(x, y, static_cast<const uint8_t*>(px), out);
            if (coverage == 255) {
                std::memcpy(px, out, 4);
            } else {
                const int c = coverage;
                for (int k = 0; k < 4; ++k) {
                    const int a = px[k];
                    const int b = out[k];
                    px[k] = static_cast<uint8_t>(a + ((b - a) * c + (b >= a ? 127 : -127)) / 255);
                }
            }
        }
    }
}

std::vector<uint8_t> copyPacked(const Surface& s)
{
    std::vector<uint8_t> out(static_cast<size_t>(s.width) * static_cast<size_t>(s.height) * 4u);
    for (int y = 0; y < s.height; ++y) {
        std::memcpy(out.data() + idx4(0, y, s.width),
                    s.pixels + static_cast<size_t>(y) * static_cast<size_t>(s.stride),
                    static_cast<size_t>(s.width) * 4u);
    }
    return out;
}

// RGBA8888 droit -> float prémultiplié (0..1).
void loadPremultiplied(const Surface& s, std::vector<float>& planes)
{
    planes.resize(static_cast<size_t>(s.width) * static_cast<size_t>(s.height) * 4u);
    CC_OMP_FOR
    for (int y = 0; y < s.height; ++y) {
        const uint8_t* row = s.pixels + static_cast<size_t>(y) * static_cast<size_t>(s.stride);
        float* out = planes.data() + idx4(0, y, s.width);
        for (int x = 0; x < s.width; ++x) {
            const float a = row[x * 4 + 3] * (1.0f / 255.0f);
            out[x * 4 + 0] = row[x * 4 + 0] * (1.0f / 255.0f) * a;
            out[x * 4 + 1] = row[x * 4 + 1] * (1.0f / 255.0f) * a;
            out[x * 4 + 2] = row[x * 4 + 2] * (1.0f / 255.0f) * a;
            out[x * 4 + 3] = a;
        }
    }
}

// Écrit les plans prémultipliés dans la surface (alpha droit), sous masque.
void commitPremultiplied(const Surface& s, const std::vector<float>& planes,
                         const Mask& m)
{
    forEachPixel(s, m, [&](int x, int y, const uint8_t*, uint8_t* out) {
        const float* p = planes.data() + idx4(x, y, s.width);
        const float a = std::min(1.0f, std::max(0.0f, p[3]));
        if (a <= 1e-6f) {
            out[0] = out[1] = out[2] = out[3] = 0;
            return;
        }
        const float inv = 1.0f / a;
        out[0] = unitToByte(p[0] * inv);
        out[1] = unitToByte(p[1] * inv);
        out[2] = unitToByte(p[2] * inv);
        out[3] = unitToByte(a);
    });
}

// ------------------------------------------------------------ passes de flou

// Convolution 1D exacte le long d'un axe.  `src` et `dst` : plans RGBA float.
void convolveAxis(const float* src, float* dst, int w, int h, bool horizontal,
                  const std::vector<float>& kernel, EdgeMode edge)
{
    const int r = static_cast<int>(kernel.size() / 2);
    const int n = horizontal ? w : h;
    const int lines = horizontal ? h : w;
    const size_t elemStep = horizontal ? 4u : static_cast<size_t>(w) * 4u;
    const size_t lineStep = horizontal ? static_cast<size_t>(w) * 4u : 4u;
    CC_OMP_FOR
    for (int line = 0; line < lines; ++line) {
        const float* base = src + static_cast<size_t>(line) * lineStep;
        float* out = dst + static_cast<size_t>(line) * lineStep;
        for (int i = 0; i < n; ++i) {
            float acc[4] = {0, 0, 0, 0};
            if (i - r >= 0 && i + r < n) {
                for (int j = -r; j <= r; ++j) {
                    const float wgt = kernel[static_cast<size_t>(j + r)];
                    const float* p = base + static_cast<size_t>(i + j) * elemStep;
                    acc[0] += wgt * p[0];
                    acc[1] += wgt * p[1];
                    acc[2] += wgt * p[2];
                    acc[3] += wgt * p[3];
                }
            } else {
                for (int j = -r; j <= r; ++j) {
                    const float wgt = kernel[static_cast<size_t>(j + r)];
                    const float* p = base + static_cast<size_t>(edgeIndex(i + j, n, edge)) * elemStep;
                    acc[0] += wgt * p[0];
                    acc[1] += wgt * p[1];
                    acc[2] += wgt * p[2];
                    acc[3] += wgt * p[3];
                }
            }
            float* o = out + static_cast<size_t>(i) * elemStep;
            o[0] = acc[0];
            o[1] = acc[1];
            o[2] = acc[2];
            o[3] = acc[3];
        }
    }
}

// Moyenne glissante de rayon r (fenêtre 2r+1), O(n) quel que soit r.
void boxAxis(const float* src, float* dst, int w, int h, bool horizontal, int r,
             EdgeMode edge)
{
    const int n = horizontal ? w : h;
    const int lines = horizontal ? h : w;
    const size_t elemStep = horizontal ? 4u : static_cast<size_t>(w) * 4u;
    const size_t lineStep = horizontal ? static_cast<size_t>(w) * 4u : 4u;
    const double inv = 1.0 / static_cast<double>(2 * r + 1);
    CC_OMP_FOR
    for (int line = 0; line < lines; ++line) {
        const float* base = src + static_cast<size_t>(line) * lineStep;
        float* out = dst + static_cast<size_t>(line) * lineStep;
        double sum[4] = {0, 0, 0, 0};
        for (int j = -r; j <= r; ++j) {
            const float* p = base + static_cast<size_t>(edgeIndex(j, n, edge)) * elemStep;
            for (int c = 0; c < 4; ++c) sum[c] += p[c];
        }
        for (int i = 0; i < n; ++i) {
            float* o = out + static_cast<size_t>(i) * elemStep;
            for (int c = 0; c < 4; ++c) o[c] = static_cast<float>(sum[c] * inv);
            const float* add = base + static_cast<size_t>(edgeIndex(i + r + 1, n, edge)) * elemStep;
            const float* sub = base + static_cast<size_t>(edgeIndex(i - r, n, edge)) * elemStep;
            for (int c = 0; c < 4; ++c) sum[c] += static_cast<double>(add[c]) - sub[c];
        }
    }
}

std::vector<float> gaussianKernel(double sigma)
{
    const int r = std::max(1, static_cast<int>(std::ceil(3.0 * sigma)));
    std::vector<float> k(static_cast<size_t>(2 * r + 1));
    double sum = 0.0;
    for (int i = -r; i <= r; ++i) {
        const double v = std::exp(-(static_cast<double>(i) * i) / (2.0 * sigma * sigma));
        k[static_cast<size_t>(i + r)] = static_cast<float>(v);
        sum += v;
    }
    for (float& v : k) v = static_cast<float>(v / sum);
    return k;
}

// Largeurs de boîte dont trois passes approximent une gaussienne d'écart-type
// sigma (méthode de Kutskir).
void boxSizesForGauss(double sigma, int passes, int* radii)
{
    const double wIdeal = std::sqrt(12.0 * sigma * sigma / passes + 1.0);
    int wl = static_cast<int>(std::floor(wIdeal));
    if (wl % 2 == 0) --wl;
    const int wu = wl + 2;
    const double mIdeal = (12.0 * sigma * sigma - passes * wl * wl - 4.0 * passes * wl - 3.0 * passes) /
                          (-4.0 * wl - 4.0);
    const int m = static_cast<int>(std::lround(mIdeal));
    for (int i = 0; i < passes; ++i) radii[i] = ((i < m ? wl : wu) - 1) / 2;
}

// Une passe de moyenne glissante sur un tableau RGBA entrelacé valide sur
// [lo, hi) ; écrit out[lo + r, hi - r).  Aucune gestion de bord : l'appelant
// fournit une ligne déjà étendue.
void boxPass(const float* in, float* out, int lo, int hi, int r)
{
    const double inv = 1.0 / static_cast<double>(2 * r + 1);
    double sum[4] = {0, 0, 0, 0};
    for (int j = lo; j <= lo + 2 * r; ++j)
        for (int c = 0; c < 4; ++c) sum[c] += in[static_cast<size_t>(j) * 4u + c];
    for (int i = lo + r; i < hi - r; ++i) {
        for (int c = 0; c < 4; ++c) out[static_cast<size_t>(i) * 4u + c] = static_cast<float>(sum[c] * inv);
        if (i + 1 < hi - r) {
            for (int c = 0; c < 4; ++c)
                sum[c] += static_cast<double>(in[static_cast<size_t>(i + r + 1) * 4u + c]) -
                          in[static_cast<size_t>(i - r) * 4u + c];
        }
    }
}

// Approximation gaussienne : trois passes de boîte sur une ligne étendue une
// seule fois selon `edge`.  Étendre d'abord (au lieu de gérer le bord à chaque
// passe) donne le même résultat qu'un noyau large unique sur le signal étendu ;
// enchaîner trois passes avec bord répété à chacune déformerait les bordures.
void boxGaussAxis(const std::vector<float>& src, std::vector<float>& dst, int w,
                  int h, bool horizontal, double sigma, EdgeMode edge)
{
    int radii[3];
    boxSizesForGauss(sigma, 3, radii);
    const int R = radii[0] + radii[1] + radii[2];
    const int n = horizontal ? w : h;
    const int lines = horizontal ? h : w;
    const size_t elemStep = horizontal ? 4u : static_cast<size_t>(w) * 4u;
    const size_t lineStep = horizontal ? static_cast<size_t>(w) * 4u : 4u;
    const int total = n + 2 * R;
    // Creating an OpenMP team for a small tile is slower than the filter
    // itself and made descriptor validation/fuzzing appear to hang.  Keep
    // parallel execution for real image-sized work only.
    CC_OMP_PARALLEL_SIZED(static_cast<long long>(w) * h)
    {
        std::vector<float> bufA(static_cast<size_t>(total) * 4u), bufB(static_cast<size_t>(total) * 4u);
        CC_OMP_WORKSHARE
        for (int line = 0; line < lines; ++line) {
            const float* base = src.data() + static_cast<size_t>(line) * lineStep;
            for (int j = 0; j < total; ++j) {
                const float* p = base + static_cast<size_t>(edgeIndex(j - R, n, edge)) * elemStep;
                float* o = bufA.data() + static_cast<size_t>(j) * 4u;
                o[0] = p[0]; o[1] = p[1]; o[2] = p[2]; o[3] = p[3];
            }
            int lo = 0, hi = total;
            float* in = bufA.data();
            float* out = bufB.data();
            for (int pass = 0; pass < 3; ++pass) {
                boxPass(in, out, lo, hi, radii[pass]);
                lo += radii[pass];
                hi -= radii[pass];
                std::swap(in, out);
            }
            float* dline = dst.data() + static_cast<size_t>(line) * lineStep;
            for (int i = 0; i < n; ++i) {
                const float* p = in + static_cast<size_t>(i + R) * 4u;
                float* o = dline + static_cast<size_t>(i) * elemStep;
                o[0] = p[0]; o[1] = p[1]; o[2] = p[2]; o[3] = p[3];
            }
        }
    }
}

// Floute `a` le long d'un axe ; le résultat est laissé dans `a` (b sert de
// tampon de travail).
void blurAxis(std::vector<float>& a, std::vector<float>& b, int w, int h,
              bool horizontal, double sigma, EdgeMode edge)
{
    if (sigma <= 0.0) return;
    if (sigma < kBoxBlurSigmaThreshold) {
        const std::vector<float> kernel = gaussianKernel(sigma);
        convolveAxis(a.data(), b.data(), w, h, horizontal, kernel, edge);
    } else {
        boxGaussAxis(a, b, w, h, horizontal, sigma, edge);
    }
    a.swap(b);
}

void blurPlanes(std::vector<float>& a, int w, int h, double sx, double sy,
                EdgeMode edge)
{
    std::vector<float> b(a.size());
    blurAxis(a, b, w, h, true, sx, edge);
    blurAxis(a, b, w, h, false, sy, edge);
}

inline bool finiteNonNegative(double v) { return std::isfinite(v) && v >= 0.0; }

inline double luma709(double r, double g, double b)
{
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// Générateur déterministe indépendant de l'ordre d'exécution.
inline uint64_t splitmix64(uint64_t& state)
{
    uint64_t z = (state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

inline double uniform01(uint64_t& state)
{
    return static_cast<double>(splitmix64(state) >> 11) * (1.0 / 9007199254740992.0);
}

inline double gaussian01(uint64_t& state)
{
    const double u1 = 1.0 - uniform01(state); // (0, 1]
    const double u2 = uniform01(state);
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * kPi * u2);
}

void rgbToHsv(double r, double g, double b, double& h, double& s, double& v)
{
    const double mx = std::max(r, std::max(g, b));
    const double mn = std::min(r, std::min(g, b));
    const double d = mx - mn;
    v = mx;
    s = mx > 0.0 ? d / mx : 0.0;
    if (d <= 0.0) {
        h = 0.0;
    } else if (mx == r) {
        h = std::fmod((g - b) / d, 6.0);
    } else if (mx == g) {
        h = (b - r) / d + 2.0;
    } else {
        h = (r - g) / d + 4.0;
    }
    h *= 60.0;
    if (h < 0.0) h += 360.0;
}

void hsvToRgb(double h, double s, double v, double& r, double& g, double& b)
{
    const double c = v * s;
    const double hp = h / 60.0;
    const double x = c * (1.0 - std::fabs(std::fmod(hp, 2.0) - 1.0));
    double r1 = 0, g1 = 0, b1 = 0;
    if (hp < 1.0) { r1 = c; g1 = x; }
    else if (hp < 2.0) { r1 = x; g1 = c; }
    else if (hp < 3.0) { g1 = c; b1 = x; }
    else if (hp < 4.0) { g1 = x; b1 = c; }
    else if (hp < 5.0) { r1 = x; b1 = c; }
    else { r1 = c; b1 = x; }
    const double m = v - c;
    r = r1 + m;
    g = g1 + m;
    b = b1 + m;
}

inline double pushToward(double v, double delta)
{
    // delta > 0 : rapproche de 1 ; delta < 0 : rapproche de 0.
    return delta >= 0.0 ? v + (1.0 - v) * delta : v * (1.0 + delta);
}

// Luminance prémultipliée en [0,1], bord répété.
inline double lumaAt(const std::vector<uint8_t>& src, int x, int y, int w, int h)
{
    x = x < 0 ? 0 : (x >= w ? w - 1 : x);
    y = y < 0 ? 0 : (y >= h ? h - 1 : y);
    const uint8_t* p = src.data() + idx4(x, y, w);
    return luma709(p[0], p[1], p[2]) * (p[3] / 255.0) / 255.0;
}

void sobel(const std::vector<uint8_t>& src, int x, int y, int w, int h,
           double& gx, double& gy)
{
    const double tl = lumaAt(src, x - 1, y - 1, w, h), tc = lumaAt(src, x, y - 1, w, h),
                 tr = lumaAt(src, x + 1, y - 1, w, h), ml = lumaAt(src, x - 1, y, w, h),
                 mr = lumaAt(src, x + 1, y, w, h), bl = lumaAt(src, x - 1, y + 1, w, h),
                 bc = lumaAt(src, x, y + 1, w, h), br = lumaAt(src, x + 1, y + 1, w, h);
    gx = (tr + 2.0 * mr + br) - (tl + 2.0 * ml + bl);
    gy = (bl + 2.0 * bc + br) - (tl + 2.0 * tc + tr);
}

} // namespace

// ----------------------------------------------------------------- flous ----

int gaussianReach(double sigma)
{
    if (!(sigma > 0.0) || !std::isfinite(sigma)) return 0;
    if (sigma < kBoxBlurSigmaThreshold)
        return std::max(1, static_cast<int>(std::ceil(3.0 * sigma)));
    int radii[3];
    boxSizesForGauss(sigma, 3, radii);
    return radii[0] + radii[1] + radii[2];
}

bool gaussianBlur(const Surface& s, double sigmaX, double sigmaY, EdgeMode edge,
                  const Mask& mask)
{
    if (!argsOk(s, mask) || !finiteNonNegative(sigmaX) || !finiteNonNegative(sigmaY))
        return false;
    if (sigmaX == 0.0 && sigmaY == 0.0) return true;
    std::vector<float> planes;
    loadPremultiplied(s, planes);
    blurPlanes(planes, s.width, s.height, sigmaX, sigmaY, edge);
    commitPremultiplied(s, planes, mask);
    return true;
}

bool boxBlur(const Surface& s, int radiusX, int radiusY, EdgeMode edge,
             const Mask& mask)
{
    if (!argsOk(s, mask) || radiusX < 0 || radiusY < 0) return false;
    if (radiusX == 0 && radiusY == 0) return true;
    std::vector<float> a;
    loadPremultiplied(s, a);
    std::vector<float> b(a.size());
    if (radiusX > 0) {
        boxAxis(a.data(), b.data(), s.width, s.height, true, radiusX, edge);
        a.swap(b);
    }
    if (radiusY > 0) {
        boxAxis(a.data(), b.data(), s.width, s.height, false, radiusY, edge);
        a.swap(b);
    }
    commitPremultiplied(s, a, mask);
    return true;
}

bool motionBlur(const Surface& s, double angleDegrees, double length,
                EdgeMode edge, const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(angleDegrees) || !finiteNonNegative(length))
        return false;
    if (length == 0.0) return true;
    const int w = s.width, h = s.height;
    std::vector<float> src;
    loadPremultiplied(s, src);
    std::vector<float> dst(src.size());
    const double rad = angleDegrees * kPi / 180.0;
    double dx = std::cos(rad), dy = std::sin(rad);
    // Évite qu'un cos(90°) = 6e-17 fasse basculer floor() sur le pixel voisin
    // (visible en mode Wrap sur les axes exacts).
    if (std::fabs(dx) < 1e-12) dx = 0.0;
    if (std::fabs(dy) < 1e-12) dy = 0.0;
    const int samples = std::max(2, static_cast<int>(std::ceil(length)) + 1);
    std::vector<double> offsets(static_cast<size_t>(samples));
    for (int i = 0; i < samples; ++i)
        offsets[static_cast<size_t>(i)] = -length * 0.5 + length * i / (samples - 1);

    CC_OMP_FOR
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            double acc[4] = {0, 0, 0, 0};
            for (int i = 0; i < samples; ++i) {
                const double fx = x + dx * offsets[static_cast<size_t>(i)];
                const double fy = y + dy * offsets[static_cast<size_t>(i)];
                const double flx = std::floor(fx), fly = std::floor(fy);
                const double tx = fx - flx, ty = fy - fly;
                const int x0 = edgeIndex(static_cast<int>(flx), w, edge);
                const int x1 = edgeIndex(static_cast<int>(flx) + 1, w, edge);
                const int y0 = edgeIndex(static_cast<int>(fly), h, edge);
                const int y1 = edgeIndex(static_cast<int>(fly) + 1, h, edge);
                const float* p00 = src.data() + idx4(x0, y0, w);
                const float* p10 = src.data() + idx4(x1, y0, w);
                const float* p01 = src.data() + idx4(x0, y1, w);
                const float* p11 = src.data() + idx4(x1, y1, w);
                for (int c = 0; c < 4; ++c) {
                    const double top = p00[c] + (p10[c] - p00[c]) * tx;
                    const double bottom = p01[c] + (p11[c] - p01[c]) * tx;
                    acc[c] += top + (bottom - top) * ty;
                }
            }
            float* o = dst.data() + idx4(x, y, w);
            for (int c = 0; c < 4; ++c) o[c] = static_cast<float>(acc[c] / samples);
        }
    }
    commitPremultiplied(s, dst, mask);
    return true;
}

bool unsharpMask(const Surface& s, double sigma, double amount, int threshold,
                 EdgeMode edge, const Mask& mask)
{
    if (!argsOk(s, mask) || !finiteNonNegative(sigma) || !std::isfinite(amount) ||
        threshold < 0 || threshold > 255)
        return false;
    if (sigma == 0.0 || amount == 0.0) return true;
    std::vector<float> original, blurred;
    loadPremultiplied(s, original);
    blurred = original;
    blurPlanes(blurred, s.width, s.height, sigma, sigma, edge);
    const double thr = threshold / 255.0;
    const int w = s.width;
    forEachPixel(s, mask, [&](int x, int y, const uint8_t* in, uint8_t* out) {
        out[3] = in[3];
        const float* b = blurred.data() + idx4(x, y, w);
        const double ba = b[3];
        if (in[3] == 0 || ba <= 1e-6) {
            std::memcpy(out, in, 4);
            return;
        }
        for (int c = 0; c < 3; ++c) {
            const double v = in[c] / 255.0;
            const double vb = std::min(1.0, b[c] / ba); // couleur floue « droite »
            const double diff = v - vb;
            out[c] = std::fabs(diff) < thr ? in[c] : unitToByte(v + amount * diff);
        }
    });
    return true;
}

bool medianFilter(const Surface& s, int radius, const Mask& mask)
{
    if (!argsOk(s, mask) || radius < 0 || radius > 8) return false;
    if (radius == 0) return true;
    const std::vector<uint8_t> src = copyPacked(s);
    const int w = s.width, h = s.height;
    const int window = (2 * radius + 1) * (2 * radius + 1);
    forEachPixel(s, mask, [&](int x, int y, const uint8_t*, uint8_t* out) {
        uint8_t samples[4][289];
        int count = 0;
        for (int dy = -radius; dy <= radius; ++dy) {
            const int yy = std::min(h - 1, std::max(0, y + dy));
            for (int dx = -radius; dx <= radius; ++dx) {
                const int xx = std::min(w - 1, std::max(0, x + dx));
                const uint8_t* p = src.data() + idx4(xx, yy, w);
                for (int c = 0; c < 4; ++c) samples[c][count] = p[c];
                ++count;
            }
        }
        for (int c = 0; c < 4; ++c) {
            std::nth_element(samples[c], samples[c] + window / 2, samples[c] + window);
            out[c] = samples[c][window / 2];
        }
    });
    return true;
}

bool pixelate(const Surface& s, int blockWidth, int blockHeight, const Mask& mask)
{
    if (!argsOk(s, mask) || blockWidth < 1 || blockHeight < 1) return false;
    if (blockWidth == 1 && blockHeight == 1) return true;
    const int w = s.width, h = s.height;
    // Grille ancrée à l'origine du document : le bloc d'un pixel ne dépend pas
    // de la sous-région évaluée.
    const int firstBx = s.originX / blockWidth, firstBy = s.originY / blockHeight;
    const int bx = (s.originX + w - 1) / blockWidth - firstBx + 1;
    const int by = (s.originY + h - 1) / blockHeight - firstBy + 1;
    std::vector<float> premul;
    loadPremultiplied(s, premul);
    std::vector<float> blocks(static_cast<size_t>(bx) * static_cast<size_t>(by) * 4u);
    CC_OMP_FOR
    for (int j = 0; j < by; ++j) {
        for (int i = 0; i < bx; ++i) {
            double acc[4] = {0, 0, 0, 0};
            const int x0 = std::max(0, (firstBx + i) * blockWidth - s.originX);
            const int x1 = std::min(w, (firstBx + i + 1) * blockWidth - s.originX);
            const int y0 = std::max(0, (firstBy + j) * blockHeight - s.originY);
            const int y1 = std::min(h, (firstBy + j + 1) * blockHeight - s.originY);
            for (int y = y0; y < y1; ++y)
                for (int x = x0; x < x1; ++x) {
                    const float* p = premul.data() + idx4(x, y, w);
                    for (int c = 0; c < 4; ++c) acc[c] += p[c];
                }
            const double n = static_cast<double>(x1 - x0) * (y1 - y0);
            float* o = blocks.data() + (static_cast<size_t>(j) * bx + i) * 4u;
            for (int c = 0; c < 4; ++c) o[c] = static_cast<float>(acc[c] / n);
        }
    }
    CC_OMP_FOR
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const int bi = (s.originX + x) / blockWidth - firstBx;
            const int bj = (s.originY + y) / blockHeight - firstBy;
            const float* b = blocks.data() + (static_cast<size_t>(bj) * bx + bi) * 4u;
            float* o = premul.data() + idx4(x, y, w);
            for (int c = 0; c < 4; ++c) o[c] = b[c];
        }
    commitPremultiplied(s, premul, mask);
    return true;
}

// --------------------------------------------------- détection / relief -----

bool edgeDetect(const Surface& s, double strength, const Mask& mask)
{
    if (!argsOk(s, mask) || !finiteNonNegative(strength)) return false;
    const std::vector<uint8_t> src = copyPacked(s);
    const int w = s.width, h = s.height;
    forEachPixel(s, mask, [&](int x, int y, const uint8_t* in, uint8_t* out) {
        double gx, gy;
        sobel(src, x, y, w, h, gx, gy);
        // Un contour plein contraste (0 -> 1) donne |g| = 4.
        const uint8_t g = unitToByte(std::sqrt(gx * gx + gy * gy) * 0.25 * strength);
        out[0] = out[1] = out[2] = g;
        out[3] = in[3];
    });
    return true;
}

bool emboss(const Surface& s, double angleDegrees, double depth, const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(angleDegrees) || !std::isfinite(depth))
        return false;
    const std::vector<uint8_t> src = copyPacked(s);
    const int w = s.width, h = s.height;
    const double rad = angleDegrees * kPi / 180.0;
    const double dx = std::cos(rad), dy = std::sin(rad);
    forEachPixel(s, mask, [&](int x, int y, const uint8_t* in, uint8_t* out) {
        double gx, gy;
        sobel(src, x, y, w, h, gx, gy);
        const double directional = (gx * dx + gy * dy) * 0.25; // [-1, 1]
        const uint8_t g = unitToByte(0.5 + 0.5 * depth * directional);
        out[0] = out[1] = out[2] = g;
        out[3] = in[3];
    });
    return true;
}

// ----------------------------------------------------------- couleur --------

bool invert(const Surface& s, const Mask& mask)
{
    uint8_t lut[256];
    buildInvertLut(lut);
    return applyLut(s, lut, lut, lut, mask);
}

bool desaturate(const Surface& s, DesaturateMode mode, const Mask& mask)
{
    if (!argsOk(s, mask)) return false;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        double g;
        switch (mode) {
        case DesaturateMode::Average: g = (in[0] + in[1] + in[2]) / 3.0; break;
        case DesaturateMode::Lightness:
            g = (std::max(in[0], std::max(in[1], in[2])) +
                 std::min(in[0], std::min(in[1], in[2]))) * 0.5;
            break;
        default: g = luma709(in[0], in[1], in[2]); break;
        }
        out[0] = out[1] = out[2] = toByte(g);
        out[3] = in[3];
    });
    return true;
}

bool hsvAdjust(const Surface& s, double hueShiftDegrees, double saturationDelta,
               double valueDelta, const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(hueShiftDegrees) ||
        !std::isfinite(saturationDelta) || !std::isfinite(valueDelta))
        return false;
    saturationDelta = std::min(1.0, std::max(-1.0, saturationDelta));
    valueDelta = std::min(1.0, std::max(-1.0, valueDelta));
    double shift = std::fmod(hueShiftDegrees, 360.0);
    if (shift < 0.0) shift += 360.0;
    if (shift == 0.0 && saturationDelta == 0.0 && valueDelta == 0.0) return true;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        double h, sat, val;
        rgbToHsv(in[0] / 255.0, in[1] / 255.0, in[2] / 255.0, h, sat, val);
        h = std::fmod(h + shift, 360.0);
        sat = std::min(1.0, std::max(0.0, pushToward(sat, saturationDelta)));
        val = std::min(1.0, std::max(0.0, pushToward(val, valueDelta)));
        double r, g, b;
        hsvToRgb(h, sat, val, r, g, b);
        out[0] = unitToByte(r);
        out[1] = unitToByte(g);
        out[2] = unitToByte(b);
        out[3] = in[3];
    });
    return true;
}

namespace {

// Modulo à la Python/NumPy : résultat du signe du diviseur (diviseur > 0).
inline float floorMod(float x, float m)
{
    float r = std::fmod(x, m);
    if (r != 0.0f && r < 0.0f) r += m;
    return r;
}

inline float clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

// result += weight * (-c * (1 - result)) ; result *= clip(1 - weight * k).
inline void applySelectiveBand(float* rgb, float weight, const float cmyk[4])
{
    rgb[0] += weight * (-cmyk[0] * (1.0f - rgb[0]));
    rgb[1] += weight * (-cmyk[1] * (1.0f - rgb[1]));
    rgb[2] += weight * (-cmyk[2] * (1.0f - rgb[2]));
    const float f = clamp01(1.0f - weight * cmyk[3]);
    rgb[0] *= f;
    rgb[1] *= f;
    rgb[2] *= f;
}

} // namespace

bool selectiveColor(const Surface& s, const SelectiveColorParams& params, const Mask& mask)
{
    if (!argsOk(s, mask)) return false;
    bool any = false;
    float cmyk[kSelectiveBandCount][4];
    for (int b = 0; b < kSelectiveBandCount; ++b) {
        for (int k = 0; k < 4; ++k) {
            if (!std::isfinite(params.band[b][k])) return false;
            cmyk[b][k] = params.band[b][k] / 100.0f;
        }
        any = any || params.enabled[b];
    }
    if (!any) return true;
    static const float kCenters[6] = {0.0f, 60.0f, 120.0f, 180.0f, 240.0f, 300.0f};
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        const float r = static_cast<float>(in[0]) / 255.0f;
        const float g = static_cast<float>(in[1]) / 255.0f;
        const float b = static_cast<float>(in[2]) / 255.0f;
        const float mx = std::max(r, std::max(g, b));
        const float mn = std::min(r, std::min(g, b));
        const float delta = mx - mn;
        const float safeDelta = std::max(delta, 1e-8f);
        float hue = 0.0f;
        if (delta > 1e-8f) {
            // Trois tests successifs, le dernier qui s'applique gagne : c'est le
            // comportement historique (égalités de canaux comprises).
            if (mx == r) hue = floorMod((g - b) / safeDelta, 6.0f);
            if (mx == g) hue = (b - r) / safeDelta + 2.0f;
            if (mx == b) hue = (r - g) / safeDelta + 4.0f;
        }
        hue *= 60.0f;
        const float saturation = delta / std::max(mx, 1e-8f);
        const float luminance = 0.2126f * r + 0.7152f * g + 0.0722f * b;

        float rgb[3] = {r, g, b};
        for (int band = 0; band < 6; ++band) {
            if (!params.enabled[band]) continue;
            const float distance =
                std::fabs(floorMod(hue - kCenters[band] + 180.0f, 360.0f) - 180.0f);
            const float weight = clamp01(1.0f - distance / 45.0f) * saturation;
            applySelectiveBand(rgb, weight, cmyk[band]);
        }
        const bool inTone[3] = {luminance >= 0.75f, saturation <= 0.25f, luminance <= 0.25f};
        for (int t = 0; t < 3; ++t) {
            const int band = kBandWhites + t;
            if (!params.enabled[band]) continue;
            float weight = inTone[t] ? 1.0f : 0.0f;
            if (band != kBandNeutrals) weight *= 1.0f - saturation;
            applySelectiveBand(rgb, weight, cmyk[band]);
        }
        for (int c = 0; c < 3; ++c)
            out[c] = static_cast<uint8_t>(std::nearbyint(clamp01(rgb[c]) * 255.0f));
        out[3] = in[3];
    });
    return true;
}

// ------------------------------------------------ calques de réglage -------

namespace {

// Teinte / 6 comme l'ancienne version NumPy : trois tests successifs, le dernier
// qui s'applique gagne.  Pour des entrées 8 bits delta vaut 0 ou au moins 1/255,
// les deux anciens seuils (delta != 0 et delta > 1e-8) sont donc équivalents.
inline float hueOverSix(float r, float g, float b, float mx, float delta)
{
    float h = 0.0f;
    if (delta > 1e-8f) {
        const float d = std::max(delta, 1e-8f);
        if (mx == r) h = floorMod((g - b) / d, 6.0f);
        if (mx == g) h = (b - r) / d + 2.0f;
        if (mx == b) h = (r - g) / d + 4.0f;
    }
    return h / 6.0f;
}

inline void hsvToRgbBytes(float h, float sat, float val, uint8_t* out)
{
    const float h6 = h * 6.0f;
    const float fl = std::floor(h6);
    int i = static_cast<int>(fl) % 6;
    if (i < 0) i += 6;
    const float f = h6 - fl;
    const float p = val * (1.0f - sat);
    const float q = val * (1.0f - f * sat);
    const float t = val * (1.0f - (1.0f - f) * sat);
    float c[3];
    switch (i) {
    case 0: c[0] = val; c[1] = t; c[2] = p; break;
    case 1: c[0] = q; c[1] = val; c[2] = p; break;
    case 2: c[0] = p; c[1] = val; c[2] = t; break;
    case 3: c[0] = p; c[1] = q; c[2] = val; break;
    case 4: c[0] = t; c[1] = p; c[2] = val; break;
    default: c[0] = val; c[1] = p; c[2] = q; break;
    }
    for (int k = 0; k < 3; ++k) out[k] = static_cast<uint8_t>(std::nearbyint(c[k] * 255.0f));
}

} // namespace

bool hueSaturation(const Surface& s, double hueDegrees, double saturationPercent,
                   double lightnessPercent, const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(hueDegrees) || !std::isfinite(saturationPercent) ||
        !std::isfinite(lightnessPercent))
        return false;
    const float shift = static_cast<float>(hueDegrees / 360.0);
    const float satScale = static_cast<float>(1.0 + saturationPercent / 100.0);
    const float lightShift = static_cast<float>(lightnessPercent / 100.0);
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        const float r = static_cast<float>(in[0]) / 255.0f;
        const float g = static_cast<float>(in[1]) / 255.0f;
        const float b = static_cast<float>(in[2]) / 255.0f;
        const float mx = std::max(r, std::max(g, b));
        const float mn = std::min(r, std::min(g, b));
        const float delta = mx - mn;
        float sat = mx == 0.0f ? 0.0f : delta / std::max(mx, 1e-8f);
        float h = floorMod(hueOverSix(r, g, b, mx, delta) + shift, 1.0f);
        sat = clamp01(sat * satScale);
        const float val = clamp01(mx + lightShift);
        hsvToRgbBytes(h, sat, val, out);
        out[3] = in[3];
    });
    return true;
}

bool vibrance(const Surface& s, double vibrancePercent, double saturationPercent,
              const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(vibrancePercent) || !std::isfinite(saturationPercent))
        return false;
    const float vib = static_cast<float>(vibrancePercent / 100.0);
    const float satShift = static_cast<float>(saturationPercent / 100.0);
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        const float r = static_cast<float>(in[0]) / 255.0f;
        const float g = static_cast<float>(in[1]) / 255.0f;
        const float b = static_cast<float>(in[2]) / 255.0f;
        const float mx = std::max(r, std::max(g, b));
        const float mn = std::min(r, std::min(g, b));
        const float delta = mx - mn;
        const float sat = delta / std::max(mx, 1e-8f);
        const float satDelta = vib * (1.0f - sat) + satShift;
        hsvToRgbBytes(hueOverSix(r, g, b, mx, delta), clamp01(sat * (1.0f + satDelta)), mx, out);
        out[3] = in[3];
    });
    return true;
}

bool colorBalance(const Surface& s, const ColorBalanceParams& p, const Mask& mask)
{
    if (!argsOk(s, mask)) return false;
    for (int k = 0; k < 3; ++k)
        if (!std::isfinite(p.shadows[k]) || !std::isfinite(p.midtones[k]) ||
            !std::isfinite(p.highlights[k]))
            return false;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        const float rgb[3] = {static_cast<float>(in[0]) / 255.0f, static_cast<float>(in[1]) / 255.0f,
                              static_cast<float>(in[2]) / 255.0f};
        const float lum = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        const float sh = clamp01(1.0f - lum * 2.0f);
        const float hi = clamp01((lum - 0.5f) * 2.0f);
        const float mi = clamp01(1.0f - sh - hi);
        for (int k = 0; k < 3; ++k) {
            const float correction =
                (sh * p.shadows[k] + mi * p.midtones[k] + hi * p.highlights[k]) / 100.0f;
            out[k] = static_cast<uint8_t>(std::nearbyint(clamp01(rgb[k] + correction) * 255.0f));
        }
        out[3] = in[3];
    });
    return true;
}

bool luminosityBlend(const Surface& dst, const uint8_t* source, int sourceStride,
                     LuminosityMode mode, double amount, double feather, bool invert,
                     const Mask& mask)
{
    if (!argsOk(dst, mask) || !source || sourceStride < dst.width * 4 ||
        !std::isfinite(amount) || !std::isfinite(feather))
        return false;
    const float exponent = static_cast<float>(1.0 / std::max(0.01, feather));
    const float gain = static_cast<float>(amount);
    forEachPixel(dst, mask, [&](int x, int y, const uint8_t* in, uint8_t* out) {
        const uint8_t* src = source + static_cast<size_t>(y) * static_cast<size_t>(sourceStride) +
                             static_cast<size_t>(x) * 4u;
        const float lum = 0.2126f * (static_cast<float>(src[0]) / 255.0f) +
                          0.7152f * (static_cast<float>(src[1]) / 255.0f) +
                          0.0722f * (static_cast<float>(src[2]) / 255.0f);
        float m;
        switch (mode) {
        case LuminosityMode::Lights: m = clamp01((lum - 0.35f) / 0.65f); break;
        case LuminosityMode::Shadows: m = clamp01((0.65f - lum) / 0.65f); break;
        case LuminosityMode::Midtones: m = clamp01(1.0f - std::fabs(lum - 0.5f) / 0.5f); break;
        default: m = 1.0f; break;
        }
        m = std::pow(m, exponent);
        if (invert) m = 1.0f - m;
        m = clamp01(m * gain);
        for (int k = 0; k < 3; ++k)
            out[k] = static_cast<uint8_t>(std::nearbyint(
                static_cast<float>(src[k]) * (1.0f - m) + static_cast<float>(in[k]) * m));
        out[3] = src[3];
    });
    return true;
}

// ------------------------------------------------- effets de calque -------

namespace {

// Moyenne glissante sur `n` valeurs, bords répliqués, rayon r.  `in` et `out`
// ont le même pas ; l'entrée est convertie en double pour que la somme des
// passes entières reste exacte.
void boxMean1D(const float* in, float* out, int n, int step, int r)
{
    const double weight = 1.0 / (2 * r + 1);
    double sum = 0.0;
    auto at = [&](int i) {
        return static_cast<double>(in[static_cast<size_t>(std::min(std::max(i, 0), n - 1)) * step]);
    };
    for (int k = -r; k <= r; ++k) sum += at(k);
    for (int i = 0; i < n; ++i) {
        out[static_cast<size_t>(i) * step] = static_cast<float>(sum * weight);
        sum += at(i + r + 1) - at(i - r);
    }
}

bool effectArgsOk(const Surface& s, const LayerEffectParams& p)
{
    return s.valid() && p.size >= 1 && p.size <= 32;
}

} // namespace

bool dropShadow(const Surface& s, const LayerEffectParams& p)
{
    if (!effectArgsOk(s, p)) return false;
    const int w = s.width, h = s.height, r = p.size;
    const size_t count = static_cast<size_t>(w) * static_cast<size_t>(h);
    std::vector<float> a(count, 0.0f), b(count, 0.0f);
    for (int y = 0; y < h; ++y) {
        const int sy = y - p.offsetY;
        if (sy < 0 || sy >= h) continue;
        for (int x = 0; x < w; ++x) {
            const int sx = x - p.offsetX;
            if (sx < 0 || sx >= w) continue;
            a[static_cast<size_t>(y) * w + x] = static_cast<float>(
                s.pixels[static_cast<size_t>(sy) * s.stride + static_cast<size_t>(sx) * 4u + 3]);
        }
    }
    // Axe vertical puis horizontal, avec un arrondi float32 entre les passes
    // (comme l'ancienne version NumPy, afin d'obtenir les mêmes alphas).
    for (int x = 0; x < w; ++x) boxMean1D(a.data() + x, b.data() + x, h, w, r);
    for (int y = 0; y < h; ++y)
        boxMean1D(b.data() + static_cast<size_t>(y) * w, a.data() + static_cast<size_t>(y) * w, w, 1, r);

    const float opacity = static_cast<float>(p.color[3]) / 255.0f;
    for (int y = 0; y < h; ++y) {
        uint8_t* row = s.pixels + static_cast<size_t>(y) * s.stride;
        for (int x = 0; x < w; ++x) {
            const float shadowAlphaF = std::floor(a[static_cast<size_t>(y) * w + x] * opacity);
            const float sa = std::min(255.0f, std::max(0.0f, shadowAlphaF)) / 255.0f;
            if (sa <= 0.0f) continue;
            uint8_t* px = row + static_cast<size_t>(x) * 4u;
            const float la = static_cast<float>(px[3]) / 255.0f;
            const float outA = la + sa * (1.0f - la); // calque au-dessus de l'ombre
            if (outA <= 0.0f) continue;
            for (int k = 0; k < 3; ++k) {
                const float v = (static_cast<float>(px[k]) * la +
                                 static_cast<float>(p.color[k]) * sa * (1.0f - la)) /
                                std::max(outA, 1e-6f);
                px[k] = static_cast<uint8_t>(std::nearbyint(std::min(255.0f, std::max(0.0f, v))));
            }
            px[3] = static_cast<uint8_t>(std::nearbyint(std::min(1.0f, outA) * 255.0f));
        }
    }
    return true;
}

bool outlineStroke(const Surface& s, const LayerEffectParams& p)
{
    if (!effectArgsOk(s, p)) return false;
    const int w = s.width, h = s.height, r = p.size;
    const size_t count = static_cast<size_t>(w) * static_cast<size_t>(h);
    std::vector<uint8_t> alpha(count), horizontal(count), outline(count);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            alpha[static_cast<size_t>(y) * w + x] =
                s.pixels[static_cast<size_t>(y) * s.stride + static_cast<size_t>(x) * 4u + 3];
    // Dilatation carrée séparable, hors image = alpha 0.
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            uint8_t m = 0;
            for (int k = std::max(0, x - r); k <= std::min(w - 1, x + r); ++k)
                m = std::max(m, alpha[static_cast<size_t>(y) * w + k]);
            horizontal[static_cast<size_t>(y) * w + x] = m;
        }
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            uint8_t m = 0;
            for (int k = std::max(0, y - r); k <= std::min(h - 1, y + r); ++k)
                m = std::max(m, horizontal[static_cast<size_t>(k) * w + x]);
            outline[static_cast<size_t>(y) * w + x] = m;
        }
    for (int y = 0; y < h; ++y) {
        uint8_t* row = s.pixels + static_cast<size_t>(y) * s.stride;
        for (int x = 0; x < w; ++x) {
            const size_t i = static_cast<size_t>(y) * w + x;
            const int mask = std::max(0, static_cast<int>(outline[i]) - static_cast<int>(alpha[i]));
            if (mask == 0) continue;
            uint8_t* px = row + static_cast<size_t>(x) * 4u;
            px[0] = p.color[0]; px[1] = p.color[1]; px[2] = p.color[2];
            px[3] = std::max<uint8_t>(alpha[i], static_cast<uint8_t>(mask * p.color[3] / 255));
        }
    }
    return true;
}

// ------------------------------------------- masques de sélection / écrêtage --

namespace {

// Extrême glissant (fenêtre [i-r, i+r] rognée aux bords) en O(n) par file
// monotone.  `hitsOutside` : la fenêtre sort de l'image => l'extérieur vaut 0.
template <class Better>
void slidingExtreme(const uint8_t* in, uint8_t* out, int n, int step, int r, bool zeroOutside,
                    Better better, std::vector<int>& queue)
{
    queue.assign(static_cast<size_t>(n) + 1, 0);
    int head = 0, tail = 0, next = 0;
    auto value = [&](int i) { return in[static_cast<size_t>(i) * step]; };
    for (int i = 0; i < n; ++i) {
        const int hi = std::min(n - 1, i + r);
        for (; next <= hi; ++next) {
            while (tail > head && !better(value(queue[tail - 1]), value(next))) --tail;
            queue[tail++] = next;
        }
        while (queue[head] < i - r) ++head;
        uint8_t v = value(queue[head]);
        if (zeroOutside && (i - r < 0 || i + r > n - 1)) v = 0;
        out[static_cast<size_t>(i) * step] = v;
    }
}

} // namespace

bool blendByAlpha(const Surface& dst, const uint8_t* changed, int changedStride,
                  const uint8_t* maskSource, int maskStride)
{
    if (!dst.valid() || !changed || !maskSource || changedStride < dst.width * 4 ||
        maskStride < dst.width * 4)
        return false;
    CC_OMP_FOR
    for (int y = 0; y < dst.height; ++y) {
        uint8_t* d = dst.pixels + static_cast<size_t>(y) * dst.stride;
        const uint8_t* c = changed + static_cast<size_t>(y) * changedStride;
        const uint8_t* m = maskSource + static_cast<size_t>(y) * maskStride;
        for (int x = 0; x < dst.width; ++x, d += 4, c += 4, m += 4) {
            const float mask = static_cast<float>(m[3]) / 255.0f;
            for (int k = 0; k < 3; ++k)
                d[k] = static_cast<uint8_t>(std::nearbyint(
                    static_cast<float>(d[k]) * (1.0f - mask) + static_cast<float>(c[k]) * mask));
        }
    }
    return true;
}

bool selectionFeather(const Surface& mask, int radius)
{
    if (!mask.valid() || radius < 1) return false;
    const int w = mask.width, h = mask.height;
    const size_t count = static_cast<size_t>(w) * static_cast<size_t>(h);
    std::vector<double> a(count), b(count);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            a[static_cast<size_t>(y) * w + x] =
                mask.pixels[static_cast<size_t>(y) * mask.stride + static_cast<size_t>(x) * 4u + 3];
    const double weight = 1.0 / (2 * radius + 1);
    auto pass = [&](const double* in, double* out, int n, int step) {
        auto at = [&](int i) { return in[static_cast<size_t>(std::min(std::max(i, 0), n - 1)) * step]; };
        double sum = 0.0;
        for (int k = -radius; k <= radius; ++k) sum += at(k);
        for (int i = 0; i < n; ++i) {
            out[static_cast<size_t>(i) * step] = sum * weight;
            sum += at(i + radius + 1) - at(i - radius);
        }
    };
    for (int x = 0; x < w; ++x) pass(a.data() + x, b.data() + x, h, w);              // axe vertical
    for (int y = 0; y < h; ++y) pass(b.data() + static_cast<size_t>(y) * w, a.data() + static_cast<size_t>(y) * w, w, 1);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const double v = std::nearbyint(a[static_cast<size_t>(y) * w + x]);
            const uint8_t byte = static_cast<uint8_t>(v < 0.0 ? 0.0 : (v > 255.0 ? 255.0 : v));
            uint8_t* px = mask.pixels + static_cast<size_t>(y) * mask.stride + static_cast<size_t>(x) * 4u;
            px[0] = px[1] = px[2] = px[3] = byte;
        }
    return true;
}

bool selectionMorph(const Surface& mask, int radius, bool grow)
{
    if (!mask.valid() || radius < 1) return false;
    const int w = mask.width, h = mask.height;
    const size_t count = static_cast<size_t>(w) * static_cast<size_t>(h);
    std::vector<uint8_t> a(count), b(count);
    std::vector<int> queue;
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            a[static_cast<size_t>(y) * w + x] =
                mask.pixels[static_cast<size_t>(y) * mask.stride + static_cast<size_t>(x) * 4u + 3];
    auto run = [&](const uint8_t* in, uint8_t* out, int n, int step) {
        if (grow) slidingExtreme(in, out, n, step, radius, false,
                                 [](uint8_t p, uint8_t q) { return p >= q; }, queue);
        else slidingExtreme(in, out, n, step, radius, true,
                            [](uint8_t p, uint8_t q) { return p <= q; }, queue);
    };
    for (int x = 0; x < w; ++x) run(a.data() + x, b.data() + x, h, w);
    for (int y = 0; y < h; ++y) run(b.data() + static_cast<size_t>(y) * w, a.data() + static_cast<size_t>(y) * w, w, 1);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            uint8_t* px = mask.pixels + static_cast<size_t>(y) * mask.stride + static_cast<size_t>(x) * 4u;
            px[0] = px[1] = px[2] = px[3] = a[static_cast<size_t>(y) * w + x];
        }
    return true;
}

bool selectColorRange(const Surface& mask, const uint8_t* source, int sourceStride,
                      int red, int green, int blue, int tolerance)
{
    if (!mask.valid() || !source || sourceStride < mask.width * 4) return false;
    for (int v : {red, green, blue})
        if (v < 0 || v > 255) return false;
    const double range = std::max(1.0, static_cast<double>(tolerance) * 1.732);
    CC_OMP_FOR
    for (int y = 0; y < mask.height; ++y) {
        const uint8_t* s = source + static_cast<size_t>(y) * sourceStride;
        uint8_t* d = mask.pixels + static_cast<size_t>(y) * mask.stride;
        for (int x = 0; x < mask.width; ++x, s += 4, d += 4) {
            const double dr = s[0] - red, dg = s[1] - green, db = s[2] - blue;
            const double distance = std::sqrt(dr * dr + dg * dg + db * db);
            double a = 255.0 - distance * 255.0 / range;
            a = a < 0.0 ? 0.0 : (a > 255.0 ? 255.0 : a);
            d[0] = d[1] = d[2] = d[3] = static_cast<uint8_t>(a);
        }
    }
    return true;
}

bool posterize(const Surface& s, int levels, const Mask& mask)
{
    if (levels < 2 || levels > 256) return false;
    uint8_t lut[256];
    for (int i = 0; i < 256; ++i) {
        const int q = std::min(levels - 1, i * levels / 256);
        lut[i] = toByte(q * 255.0 / (levels - 1));
    }
    return applyLut(s, lut, lut, lut, mask);
}

bool threshold(const Surface& s, int level, const Mask& mask)
{
    if (!argsOk(s, mask) || level < 0 || level > 255) return false;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        const uint8_t v = luma709(in[0], in[1], in[2]) >= level ? 255 : 0;
        out[0] = out[1] = out[2] = v;
        out[3] = in[3];
    });
    return true;
}

bool addNoise(const Surface& s, const NoiseOptions& o, const Mask& mask)
{
    if (!argsOk(s, mask) || !finiteNonNegative(o.amount)) return false;
    if (o.amount == 0.0) return true;
    const double sigma = o.amount * 255.0;
    const double halfWidth = sigma * std::sqrt(3.0); // même écart-type que la gaussienne
    forEachPixel(s, mask, [&](int x, int y, const uint8_t* in, uint8_t* out) {
        uint64_t state = o.seed * 0x9E3779B97F4A7C15ULL ^
                         (static_cast<uint64_t>(x + s.originX) * 0xD1B54A32D192ED03ULL) ^
                         (static_cast<uint64_t>(y + s.originY) * 0x8CB92BA72F3D8DD7ULL);
        splitmix64(state); // brasse la graine
        auto draw = [&]() {
            return o.gaussian ? gaussian01(state) * sigma
                              : (uniform01(state) * 2.0 - 1.0) * halfWidth;
        };
        double n[4];
        n[0] = draw();
        n[1] = o.monochrome ? n[0] : draw();
        n[2] = o.monochrome ? n[0] : draw();
        n[3] = o.affectAlpha ? draw() : 0.0;
        for (int c = 0; c < 4; ++c) out[c] = toByte(in[c] + n[c]);
    });
    return true;
}

bool colorToAlpha(const Surface& s, uint8_t red, uint8_t green, uint8_t blue,
                  double tolerance, const Mask& mask)
{
    if (!argsOk(s, mask) || !std::isfinite(tolerance) || tolerance < 0.0 ||
        tolerance > 1.0)
        return false;
    const double key[3] = {red / 255.0, green / 255.0, blue / 255.0};
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        if (in[3] == 0) {
            std::memcpy(out, in, 4);
            return;
        }
        double p[3] = {in[0] / 255.0, in[1] / 255.0, in[2] / 255.0};
        // Alpha minimal tel que key*(1-a) + nouvelle*a = p avec nouvelle ∈ [0,1].
        double a = 0.0;
        for (int c = 0; c < 3; ++c) {
            double ac = 0.0;
            if (p[c] > key[c]) ac = (p[c] - key[c]) / (1.0 - key[c]);
            else if (p[c] < key[c]) ac = (key[c] - p[c]) / key[c];
            a = std::max(a, ac);
        }
        double effective = a;
        if (tolerance > 0.0)
            effective = a <= tolerance ? 0.0 : (tolerance >= 1.0 ? 0.0 : (a - tolerance) / (1.0 - tolerance));
        if (effective <= 0.0) {
            out[0] = out[1] = out[2] = 0;
            out[3] = 0;
            return;
        }
        for (int c = 0; c < 3; ++c) {
            const double n = key[c] + (p[c] - key[c]) / effective;
            out[c] = unitToByte(std::min(1.0, std::max(0.0, n)));
        }
        out[3] = unitToByte((in[3] / 255.0) * effective);
    });
    return true;
}

// ------------------------------------------------------------------- LUT ----

void buildInvertLut(uint8_t lut[256])
{
    for (int i = 0; i < 256; ++i) lut[i] = static_cast<uint8_t>(255 - i);
}

void buildLevelsLut(int inBlack, int inWhite, double gamma, int outBlack,
                    int outWhite, uint8_t lut[256])
{
    inBlack = std::min(254, std::max(0, inBlack));
    inWhite = std::min(255, std::max(inBlack + 1, inWhite));
    outBlack = std::min(255, std::max(0, outBlack));
    outWhite = std::min(255, std::max(0, outWhite));
    if (!(gamma > 0.0) || !std::isfinite(gamma)) gamma = 1.0;
    for (int i = 0; i < 256; ++i) {
        double t = static_cast<double>(i - inBlack) / (inWhite - inBlack);
        t = std::min(1.0, std::max(0.0, t));
        t = std::pow(t, 1.0 / gamma);
        lut[i] = toByte(outBlack + t * (outWhite - outBlack));
    }
}

void buildBrightnessContrastLut(double brightness, double contrast,
                                uint8_t lut[256])
{
    brightness = std::isfinite(brightness) ? std::min(1.0, std::max(-1.0, brightness)) : 0.0;
    contrast = std::isfinite(contrast) ? std::min(0.9999, std::max(-1.0, contrast)) : 0.0;
    const double slope = std::tan((contrast + 1.0) * kPi / 4.0);
    for (int i = 0; i < 256; ++i) {
        const double v = (i / 255.0 - 0.5) * slope + 0.5 + brightness;
        lut[i] = unitToByte(v);
    }
}

bool buildCurveLut(const double* xs, const double* ys, int count, uint8_t lut[256])
{
    for (int i = 0; i < 256; ++i) lut[i] = static_cast<uint8_t>(i);
    if (!xs || !ys || count < 2) return false;
    for (int i = 0; i < count; ++i) {
        if (!std::isfinite(xs[i]) || !std::isfinite(ys[i]) || xs[i] < 0.0 || xs[i] > 1.0)
            return false;
        if (i > 0 && !(xs[i] > xs[i - 1])) return false;
    }
    const size_t n = static_cast<size_t>(count);
    std::vector<double> y(n), h(n - 1), delta(n - 1), m(n);
    for (size_t i = 0; i < n; ++i) y[i] = std::min(1.0, std::max(0.0, ys[i]));
    for (size_t i = 0; i + 1 < n; ++i) {
        h[i] = xs[i + 1] - xs[i];
        delta[i] = (y[i + 1] - y[i]) / h[i];
    }
    // Fritsch–Carlson : pentes initiales, puis limitation pour garantir la
    // monotonie entre chaque paire de points.
    m[0] = delta[0];
    m[n - 1] = delta[n - 2];
    for (size_t i = 1; i + 1 < n; ++i)
        m[i] = (delta[i - 1] * delta[i] <= 0.0) ? 0.0 : 0.5 * (delta[i - 1] + delta[i]);
    for (size_t i = 0; i + 1 < n; ++i) {
        if (delta[i] == 0.0) {
            m[i] = m[i + 1] = 0.0;
            continue;
        }
        const double a = m[i] / delta[i], b = m[i + 1] / delta[i];
        const double sum = a * a + b * b;
        if (sum > 9.0) {
            const double tau = 3.0 / std::sqrt(sum);
            m[i] = tau * a * delta[i];
            m[i + 1] = tau * b * delta[i];
        }
    }
    size_t seg = 0;
    for (int i = 0; i < 256; ++i) {
        const double x = i / 255.0;
        double v;
        if (x <= xs[0]) {
            v = y[0];
        } else if (x >= xs[n - 1]) {
            v = y[n - 1];
        } else {
            while (seg + 2 < n && x > xs[seg + 1]) ++seg;
            const double t = (x - xs[seg]) / h[seg];
            const double t2 = t * t, t3 = t2 * t;
            v = (2 * t3 - 3 * t2 + 1) * y[seg] + (t3 - 2 * t2 + t) * h[seg] * m[seg] +
                (-2 * t3 + 3 * t2) * y[seg + 1] + (t3 - t2) * h[seg] * m[seg + 1];
        }
        lut[i] = unitToByte(v);
    }
    return true;
}

bool applyLut(const Surface& s, const uint8_t* red, const uint8_t* green,
              const uint8_t* blue, const Mask& mask)
{
    if (!argsOk(s, mask) || !red || !green || !blue) return false;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        out[0] = red[in[0]];
        out[1] = green[in[1]];
        out[2] = blue[in[2]];
        out[3] = in[3];
    });
    return true;
}


bool gradientMap(const Surface& s, const uint8_t* table, const Mask& mask)
{
    if (!argsOk(s, mask) || !table) return false;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        // Fixed-point 0.30/0.59/0.11 scaled by 1024*255 keeps the result
        // deterministic across compilers.
        const int lum = in[0] * 307 + in[1] * 604 + in[2] * 113;   // 0 .. 255*1024
        const int index = lum >> 10;
        const int frac = lum & 1023;
        const uint8_t* a = table + static_cast<size_t>(index) * 4u;
        const uint8_t* b = table + static_cast<size_t>(index < 255 ? index + 1 : 255) * 4u;
        for (int k = 0; k < 3; ++k)
            out[k] = static_cast<uint8_t>((a[k] * (1024 - frac) + b[k] * frac + 512) >> 10);
        out[3] = in[3];
    });
    return true;
}

bool lut3d(const Surface& s, const float* table, int size, const Mask& mask)
{
    if (!argsOk(s, mask) || !table || size < 2 || size > 256) return false;
    const size_t n = static_cast<size_t>(size);
    const float scale = static_cast<float>(size - 1) / 255.0f;
    forEachPixel(s, mask, [&](int, int, const uint8_t* in, uint8_t* out) {
        float f[3];
        size_t i0[3];
        for (int k = 0; k < 3; ++k) {
            const float p = in[k] * scale;
            size_t base = static_cast<size_t>(p);
            if (base >= n - 1) base = n - 2;
            i0[k] = base;
            f[k] = p - static_cast<float>(base);
        }
        float acc[3] = {0.0f, 0.0f, 0.0f};
        for (int corner = 0; corner < 8; ++corner) {
            const size_t r = i0[0] + (corner & 1);
            const size_t g = i0[1] + ((corner >> 1) & 1);
            const size_t b = i0[2] + ((corner >> 2) & 1);
            const float w = ((corner & 1) ? f[0] : 1.0f - f[0]) *
                            (((corner >> 1) & 1) ? f[1] : 1.0f - f[1]) *
                            (((corner >> 2) & 1) ? f[2] : 1.0f - f[2]);
            const float* v = table + ((b * n + g) * n + r) * 3u;
            acc[0] += w * v[0];
            acc[1] += w * v[1];
            acc[2] += w * v[2];
        }
        for (int k = 0; k < 3; ++k) {
            const float value = acc[k] * 255.0f + 0.5f;
            out[k] = static_cast<uint8_t>(value <= 0.0f ? 0 : (value >= 255.0f ? 255 : value));
        }
        out[3] = in[3];
    });
    return true;
}

bool setAlpha(const Surface& s, uint8_t alpha)
{
    if (!s.valid()) return false;
    CC_OMP_FOR_SIZED(static_cast<long long>(s.width) * s.height)
    for (int y = 0; y < s.height; ++y) {
        uint8_t* row = s.pixels + static_cast<size_t>(y) * static_cast<size_t>(s.stride);
        for (int x = 0; x < s.width; ++x) row[static_cast<size_t>(x) * 4u + 3u] = alpha;
    }
    return true;
}

bool copyAlpha(const Surface& s, const uint8_t* source, int sourceStride)
{
    if (!s.valid() || !source || sourceStride < s.width * 4) return false;
    CC_OMP_FOR_SIZED(static_cast<long long>(s.width) * s.height)
    for (int y = 0; y < s.height; ++y) {
        uint8_t* row = s.pixels + static_cast<size_t>(y) * static_cast<size_t>(s.stride);
        const uint8_t* src = source + static_cast<size_t>(y) * static_cast<size_t>(sourceStride);
        for (int x = 0; x < s.width; ++x)
            row[static_cast<size_t>(x) * 4u + 3u] = src[static_cast<size_t>(x) * 4u + 3u];
    }
    return true;
}

long unpackBits(const uint8_t* input, size_t length, uint8_t* output, size_t capacity)
{
    if ((!input && length) || (!output && capacity)) return -1;
    size_t in = 0, out = 0;
    while (in < length && out < capacity) {
        const uint8_t header = input[in++];
        if (header < 128) {
            size_t count = static_cast<size_t>(header) + 1u;
            if (count > length - in) count = length - in;
            if (count > capacity - out) count = capacity - out;
            std::memcpy(output + out, input + in, count);
            in += static_cast<size_t>(header) + 1u;
            out += count;
        } else if (header > 128) {
            size_t count = 257u - header;
            if (in >= length) break;
            if (count > capacity - out) count = capacity - out;
            std::memset(output + out, input[in], count);
            ++in;
            out += count;
        }
    }
    return static_cast<long>(out);
}

} // namespace filters
} // namespace cc
