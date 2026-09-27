#include "filter_layer.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace cc {
namespace filters {

namespace {

constexpr uint8_t kVersion = 1;
constexpr double kMaxExactInteger = 9007199254740992.0; // 2^53

bool isInteger(double v, double lo, double hi)
{
    return std::isfinite(v) && v >= lo && v <= hi && v == std::floor(v);
}

bool inRange(double v, double lo, double hi)
{
    return std::isfinite(v) && v >= lo && v <= hi;
}

// Nombre de paramètres significatifs ; -1 = type inconnu.
int usedParams(const FilterDescriptor& d)
{
    switch (d.kind) {
    case FilterKind::GaussianBlur: return 2;
    case FilterKind::BoxBlur: return 2;
    case FilterKind::MotionBlur: return 2;
    case FilterKind::UnsharpMask: return 3;
    case FilterKind::Median: return 1;
    case FilterKind::Pixelate: return 2;
    case FilterKind::EdgeDetect: return 1;
    case FilterKind::Emboss: return 2;
    case FilterKind::Invert: return 0;
    case FilterKind::Desaturate: return 1;
    case FilterKind::HsvAdjust: return 3;
    case FilterKind::Posterize: return 1;
    case FilterKind::Threshold: return 1;
    case FilterKind::Noise: return 5;
    case FilterKind::ColorToAlpha: return 4;
    case FilterKind::Levels: return 5;
    case FilterKind::BrightnessContrast: return 2;
    case FilterKind::Curve: return 2 * d.pointCount;
    }
    return -1;
}

void putU32(uint8_t* p, uint32_t v)
{
    p[0] = static_cast<uint8_t>(v);
    p[1] = static_cast<uint8_t>(v >> 8);
    p[2] = static_cast<uint8_t>(v >> 16);
    p[3] = static_cast<uint8_t>(v >> 24);
}

uint32_t getU32(const uint8_t* p)
{
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

void putF64(uint8_t* p, double v)
{
    uint64_t bits;
    std::memcpy(&bits, &v, 8);
    for (int i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(bits >> (8 * i));
}

double getF64(const uint8_t* p)
{
    uint64_t bits = 0;
    for (int i = 0; i < 8; ++i) bits |= static_cast<uint64_t>(p[i]) << (8 * i);
    double v;
    std::memcpy(&v, &bits, 8);
    return v;
}

int ceilDiv(int a, int b) { return (a + b - 1) / b; }

} // namespace

uint32_t descriptorCrc32(const uint8_t* data, size_t size)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

bool validateDescriptor(const FilterDescriptor& d)
{
    const int used = usedParams(d);
    if (used < 0) return false;
    if (d.edge != EdgeMode::Clamp && d.edge != EdgeMode::Wrap) return false;
    if (d.kind == FilterKind::Curve) {
        if (d.pointCount < 2 || d.pointCount > 4) return false;
    } else if (d.pointCount != 0) {
        return false;
    }
    for (int i = 0; i < kFilterParamCount; ++i) {
        if (!std::isfinite(d.params[i])) return false;
        if (i >= used && d.params[i] != 0.0) return false; // forme canonique
    }
    const double* p = d.params;
    switch (d.kind) {
    case FilterKind::GaussianBlur: return inRange(p[0], 0, 1000) && inRange(p[1], 0, 1000);
    case FilterKind::BoxBlur: return isInteger(p[0], 0, 1000) && isInteger(p[1], 0, 1000);
    case FilterKind::MotionBlur: return inRange(p[0], -100000, 100000) && inRange(p[1], 0, 4000);
    case FilterKind::UnsharpMask:
        return inRange(p[0], 0, 1000) && inRange(p[1], -50, 50) && isInteger(p[2], 0, 255);
    case FilterKind::Median: return isInteger(p[0], 0, 8);
    case FilterKind::Pixelate: return isInteger(p[0], 1, 4096) && isInteger(p[1], 1, 4096);
    case FilterKind::EdgeDetect: return inRange(p[0], 0, 1000);
    case FilterKind::Emboss: return inRange(p[0], -100000, 100000) && inRange(p[1], -100, 100);
    case FilterKind::Invert: return true;
    case FilterKind::Desaturate: return isInteger(p[0], 0, 2);
    case FilterKind::HsvAdjust:
        return inRange(p[0], -100000, 100000) && inRange(p[1], -1, 1) && inRange(p[2], -1, 1);
    case FilterKind::Posterize: return isInteger(p[0], 2, 256);
    case FilterKind::Threshold: return isInteger(p[0], 0, 255);
    case FilterKind::Noise:
        return inRange(p[0], 0, 1) && isInteger(p[1], 0, kMaxExactInteger) &&
               isInteger(p[2], 0, 1) && isInteger(p[3], 0, 1) && isInteger(p[4], 0, 1);
    case FilterKind::ColorToAlpha:
        return isInteger(p[0], 0, 255) && isInteger(p[1], 0, 255) &&
               isInteger(p[2], 0, 255) && inRange(p[3], 0, 1);
    case FilterKind::Levels:
        return isInteger(p[0], 0, 254) && isInteger(p[1], 1, 255) && p[1] > p[0] &&
               inRange(p[2], 0.1, 10.0) && isInteger(p[3], 0, 255) && isInteger(p[4], 0, 255);
    case FilterKind::BrightnessContrast: return inRange(p[0], -1, 1) && inRange(p[1], -1, 1);
    case FilterKind::Curve:
        for (int i = 0; i < d.pointCount; ++i) {
            if (!inRange(p[2 * i], 0, 1) || !inRange(p[2 * i + 1], 0, 1)) return false;
            if (i > 0 && !(p[2 * i] > p[2 * i - 2])) return false;
        }
        return true;
    }
    return false;
}

bool encodeDescriptor(const FilterDescriptor& d, std::vector<uint8_t>& out)
{
    if (!validateDescriptor(d)) return false;
    out.assign(kDescriptorBytes, 0);
    out[0] = 'C'; out[1] = 'S'; out[2] = 'F'; out[3] = 'D';
    out[4] = kVersion;
    out[5] = static_cast<uint8_t>(d.kind);
    out[6] = static_cast<uint8_t>(d.edge);
    out[7] = static_cast<uint8_t>(d.pointCount);
    for (int i = 0; i < kFilterParamCount; ++i) putF64(out.data() + 8 + 8 * i, d.params[i]);
    putU32(out.data() + 72, descriptorCrc32(out.data(), 72));
    return true;
}

bool decodeDescriptor(const uint8_t* data, size_t size, FilterDescriptor& out)
{
    if (!data || size != kDescriptorBytes) return false;
    if (data[0] != 'C' || data[1] != 'S' || data[2] != 'F' || data[3] != 'D') return false;
    if (data[4] != kVersion) return false;
    if (getU32(data + 72) != descriptorCrc32(data, 72)) return false;
    FilterDescriptor d;
    d.kind = static_cast<FilterKind>(data[5]);
    if (data[6] > 1) return false;
    d.edge = data[6] == 1 ? EdgeMode::Wrap : EdgeMode::Clamp;
    d.pointCount = data[7];
    for (int i = 0; i < kFilterParamCount; ++i) d.params[i] = getF64(data + 8 + 8 * i);
    if (!validateDescriptor(d)) return false;
    out = d;
    return true;
}

bool descriptorUsesEdgeMode(FilterKind kind)
{
    return kind == FilterKind::GaussianBlur || kind == FilterKind::BoxBlur ||
           kind == FilterKind::MotionBlur || kind == FilterKind::UnsharpMask;
}

int descriptorReach(const FilterDescriptor& d)
{
    const double* p = d.params;
    switch (d.kind) {
    case FilterKind::GaussianBlur: return std::max(gaussianReach(p[0]), gaussianReach(p[1]));
    case FilterKind::BoxBlur: return static_cast<int>(std::max(p[0], p[1]));
    case FilterKind::MotionBlur:
        return p[1] > 0.0 ? static_cast<int>(std::ceil(p[1] * 0.5)) + 2 : 0; // + interpolation bilinéaire
    case FilterKind::UnsharpMask: return p[1] == 0.0 ? 0 : gaussianReach(p[0]);
    case FilterKind::Median: return static_cast<int>(p[0]);
    case FilterKind::EdgeDetect:
    case FilterKind::Emboss: return 1;
    default: return 0;
    }
}

bool applyDescriptor(const Surface& s, const FilterDescriptor& d, const Mask& mask)
{
    if (!validateDescriptor(d)) return false;
    const double* p = d.params;
    switch (d.kind) {
    case FilterKind::GaussianBlur: return gaussianBlur(s, p[0], p[1], d.edge, mask);
    case FilterKind::BoxBlur:
        return boxBlur(s, static_cast<int>(p[0]), static_cast<int>(p[1]), d.edge, mask);
    case FilterKind::MotionBlur: return motionBlur(s, p[0], p[1], d.edge, mask);
    case FilterKind::UnsharpMask:
        return unsharpMask(s, p[0], p[1], static_cast<int>(p[2]), d.edge, mask);
    case FilterKind::Median: return medianFilter(s, static_cast<int>(p[0]), mask);
    case FilterKind::Pixelate:
        return pixelate(s, static_cast<int>(p[0]), static_cast<int>(p[1]), mask);
    case FilterKind::EdgeDetect: return edgeDetect(s, p[0], mask);
    case FilterKind::Emboss: return emboss(s, p[0], p[1], mask);
    case FilterKind::Invert: return invert(s, mask);
    case FilterKind::Desaturate:
        return desaturate(s, static_cast<DesaturateMode>(static_cast<int>(p[0])), mask);
    case FilterKind::HsvAdjust: return hsvAdjust(s, p[0], p[1], p[2], mask);
    case FilterKind::Posterize: return posterize(s, static_cast<int>(p[0]), mask);
    case FilterKind::Threshold: return threshold(s, static_cast<int>(p[0]), mask);
    case FilterKind::Noise: {
        NoiseOptions o;
        o.amount = p[0];
        o.seed = static_cast<uint64_t>(p[1]);
        o.gaussian = p[2] != 0.0;
        o.monochrome = p[3] != 0.0;
        o.affectAlpha = p[4] != 0.0;
        return addNoise(s, o, mask);
    }
    case FilterKind::ColorToAlpha:
        return colorToAlpha(s, static_cast<uint8_t>(p[0]), static_cast<uint8_t>(p[1]),
                            static_cast<uint8_t>(p[2]), p[3], mask);
    case FilterKind::Levels: {
        uint8_t lut[256];
        buildLevelsLut(static_cast<int>(p[0]), static_cast<int>(p[1]), p[2],
                       static_cast<int>(p[3]), static_cast<int>(p[4]), lut);
        return applyLut(s, lut, lut, lut, mask);
    }
    case FilterKind::BrightnessContrast: {
        uint8_t lut[256];
        buildBrightnessContrastLut(p[0], p[1], lut);
        return applyLut(s, lut, lut, lut, mask);
    }
    case FilterKind::Curve: {
        double xs[4], ys[4];
        for (int i = 0; i < d.pointCount; ++i) {
            xs[i] = p[2 * i];
            ys[i] = p[2 * i + 1];
        }
        uint8_t lut[256];
        if (!buildCurveLut(xs, ys, d.pointCount, lut)) return false;
        return applyLut(s, lut, lut, lut, mask);
    }
    }
    return false;
}

Rect expandRectForFilter(const FilterDescriptor& d, const Rect& region, int docWidth,
                         int docHeight)
{
    Rect o = region;
    if (d.kind == FilterKind::Pixelate) {
        const int bw = static_cast<int>(d.params[0]), bh = static_cast<int>(d.params[1]);
        o.x0 = region.x0 / bw * bw;
        o.y0 = region.y0 / bh * bh;
        o.x1 = std::min(docWidth, ceilDiv(region.x1, bw) * bw);
        o.y1 = std::min(docHeight, ceilDiv(region.y1, bh) * bh);
        return o;
    }
    const int halo = descriptorReach(d);
    if (halo == 0) return region;
    const bool wrap = descriptorUsesEdgeMode(d.kind) && d.edge == EdgeMode::Wrap;
    auto axis = [&](int lo, int hi, int extent, int& outLo, int& outHi) {
        const int nlo = lo - halo, nhi = hi + halo;
        if (nlo < 0 || nhi > extent) {
            if (wrap) { // l'axe entier : ses bords sont ceux du document
                outLo = 0;
                outHi = extent;
                return;
            }
            outLo = std::max(0, nlo);
            outHi = std::min(extent, nhi);
            return;
        }
        outLo = nlo;
        outHi = nhi;
    };
    axis(region.x0, region.x1, docWidth, o.x0, o.x1);
    axis(region.y0, region.y1, docHeight, o.y0, o.y1);
    return o;
}

namespace {

bool rectInside(const Rect& r, int w, int h)
{
    return !r.empty() && r.x0 >= 0 && r.y0 >= 0 && r.x1 <= w && r.y1 <= h;
}

size_t bytesOf(const Rect& r)
{
    return static_cast<size_t>(r.width()) * static_cast<size_t>(r.height()) * 4u;
}

// Applique le filtre sur `input` (couvrant `inRect`) et ne garde que `outRect`.
bool filterRegion(const std::vector<uint8_t>& input, const Rect& inRect,
                  const StackEntry& entry, int entryIndex, StackSource& source,
                  const Rect& outRect, std::vector<uint8_t>& result)
{
    const int iw = inRect.width(), ih = inRect.height();
    const int ow = outRect.width(), oh = outRect.height();
    const int ox = outRect.x0 - inRect.x0, oy = outRect.y0 - inRect.y0;
    auto crop = [&](const std::vector<uint8_t>& src, std::vector<uint8_t>& dst) {
        dst.resize(bytesOf(outRect));
        for (int y = 0; y < oh; ++y)
            std::memcpy(dst.data() + static_cast<size_t>(y) * ow * 4,
                        src.data() + (static_cast<size_t>(oy + y) * iw + ox) * 4,
                        static_cast<size_t>(ow) * 4);
    };
    if (entry.opacity <= 0.0f) { // filtre sans effet : pas de calcul
        crop(input, result);
        return true;
    }
    // Couverture : nulle dans le halo (les pixels y sont lus mais jamais écrits).
    std::vector<uint8_t> mask(static_cast<size_t>(iw) * ih, 0);
    std::vector<uint8_t> coverage(static_cast<size_t>(ow) * oh, 255);
    source.failed = false;
    source.filterCoverage(entryIndex, outRect, coverage.data()); // false = pas de masque
    if (source.failed) return false;
    for (int y = 0; y < oh; ++y)
        std::memcpy(mask.data() + static_cast<size_t>(oy + y) * iw + ox,
                    coverage.data() + static_cast<size_t>(y) * ow, static_cast<size_t>(ow));

    std::vector<uint8_t> filtered = input;
    Surface s;
    s.pixels = filtered.data();
    s.width = iw;
    s.height = ih;
    s.stride = iw * 4;
    s.originX = inRect.x0;
    s.originY = inRect.y0;
    Mask m;
    m.data = mask.data();
    m.stride = iw;
    if (!applyDescriptor(s, entry.filter, m)) return false;

    std::vector<uint8_t> original;
    crop(input, original);
    crop(filtered, result);
    const float opacity = std::min(1.0f, entry.opacity);
    if (opacity < 1.0f) {
        for (size_t i = 0; i < result.size(); ++i) {
            const float o = original[i], f = result[i];
            result[i] = static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, std::floor(o + (f - o) * opacity + 0.5f))));
        }
    }
    return true;
}

} // namespace

bool evaluateStack(const std::vector<StackEntry>& entries, StackSource& source,
                   int docWidth, int docHeight, const Rect& region,
                   std::vector<uint8_t>& out)
{
    if (docWidth <= 0 || docHeight <= 0 || !rectInside(region, docWidth, docHeight))
        return false;
    if (entries.size() > 4096) return false;
    for (const auto& e : entries)
        if (e.isFilter && !validateDescriptor(e.filter)) return false;
    for (const auto& e : entries)
        if (e.isFilter && !std::isfinite(e.opacity)) return false;

    const int n = static_cast<int>(entries.size());
    // rects[k] : région où l'état APRÈS l'entrée k doit être connu.
    std::vector<Rect> rects(static_cast<size_t>(n));
    Rect need = region;
    for (int k = n - 1; k >= 0; --k) {
        rects[static_cast<size_t>(k)] = need;
        const auto& e = entries[static_cast<size_t>(k)];
        if (e.visible && e.isFilter && e.opacity > 0.0f)
            need = expandRectForFilter(e.filter, need, docWidth, docHeight);
    }

    Rect stateRect = need; // région de l'état en bas de pile
    std::vector<uint8_t> state;
    bool haveState = false;
    std::vector<int> pending;
    auto flush = [&]() -> bool {
        if (pending.empty()) return true;
        std::vector<uint8_t> composed(bytesOf(stateRect));
        source.failed = false;
        if (!source.composeRaster(pending.data(), static_cast<int>(pending.size()),
                                  haveState ? state.data() : nullptr, stateRect,
                                  composed.data()) || source.failed)
            return false;
        state.swap(composed);
        haveState = true;
        pending.clear();
        return true;
    };

    for (int k = 0; k < n; ++k) {
        const auto& e = entries[static_cast<size_t>(k)];
        if (!e.visible) continue;
        if (!e.isFilter) {
            pending.push_back(e.rasterId);
            continue;
        }
        if (e.opacity <= 0.0f) continue; // n'a aucun effet et n'a pas élargi les régions
        if (!flush()) return false;
        if (!haveState) { // rien en dessous : fond transparent
            state.assign(bytesOf(stateRect), 0);
            haveState = true;
        }
        const Rect outRect = rects[static_cast<size_t>(k)];
        std::vector<uint8_t> next;
        if (!filterRegion(state, stateRect, e, k, source, outRect, next)) return false;
        if (source.failed) return false;
        state.swap(next);
        stateRect = outRect;
    }
    if (!flush()) return false;
    if (!haveState) state.assign(bytesOf(stateRect), 0);
    if (!(stateRect == region)) return false; // invariant : cohérence des régions
    out.swap(state);
    return true;
}

} // namespace filters
} // namespace cc
