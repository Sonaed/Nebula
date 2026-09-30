#include "filter_api.h"

#include "document_state.h"
#include "filter_layer.h"
#include "image_filters.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

using cc::filters::DesaturateMode;
using cc::filters::EdgeMode;
using cc::filters::Mask;
using cc::filters::NoiseOptions;
using cc::filters::Surface;

namespace {

Surface surfaceOf(uint8_t* rgba, int width, int height, int stride)
{
    Surface s;
    s.pixels = rgba;
    s.width = width;
    s.height = height;
    s.stride = stride;
    return s;
}

Mask maskOf(const uint8_t* mask, int stride)
{
    Mask m;
    m.data = mask;
    m.stride = mask ? stride : 0;
    return m;
}

bool edgeOf(int edge, EdgeMode* out)
{
    if (edge != 0 && edge != 1) return false;
    *out = edge == 1 ? EdgeMode::Wrap : EdgeMode::Clamp;
    return true;
}

// Aucune exception (std::bad_alloc sur un gros document) ne doit traverser l'ABI C.
template <class F>
int guarded(F&& body)
{
    try {
        return body() ? 1 : 0;
    } catch (const std::exception&) {
        return 0;
    } catch (...) {
        return 0;
    }
}

} // namespace

extern "C" {

int cs_filter_abi_version(void) { return CS_FILTER_ABI_VERSION; }

int cs_filter_gaussian_blur(uint8_t* rgba, int width, int height, int stride,
                            double sigma_x, double sigma_y, int edge,
                            const uint8_t* mask, int mask_stride)
{
    EdgeMode e;
    if (!edgeOf(edge, &e)) return 0;
    return guarded([&] {
        return cc::filters::gaussianBlur(surfaceOf(rgba, width, height, stride),
                                         sigma_x, sigma_y, e, maskOf(mask, mask_stride));
    });
}

int cs_filter_box_blur(uint8_t* rgba, int width, int height, int stride,
                       int radius_x, int radius_y, int edge,
                       const uint8_t* mask, int mask_stride)
{
    EdgeMode e;
    if (!edgeOf(edge, &e)) return 0;
    return guarded([&] {
        return cc::filters::boxBlur(surfaceOf(rgba, width, height, stride), radius_x,
                                    radius_y, e, maskOf(mask, mask_stride));
    });
}

int cs_filter_motion_blur(uint8_t* rgba, int width, int height, int stride,
                          double angle_degrees, double length, int edge,
                          const uint8_t* mask, int mask_stride)
{
    EdgeMode e;
    if (!edgeOf(edge, &e)) return 0;
    return guarded([&] {
        return cc::filters::motionBlur(surfaceOf(rgba, width, height, stride),
                                       angle_degrees, length, e,
                                       maskOf(mask, mask_stride));
    });
}

int cs_filter_unsharp_mask(uint8_t* rgba, int width, int height, int stride,
                           double sigma, double amount, int threshold, int edge,
                           const uint8_t* mask, int mask_stride)
{
    EdgeMode e;
    if (!edgeOf(edge, &e)) return 0;
    return guarded([&] {
        return cc::filters::unsharpMask(surfaceOf(rgba, width, height, stride), sigma,
                                        amount, threshold, e, maskOf(mask, mask_stride));
    });
}

int cs_filter_median(uint8_t* rgba, int width, int height, int stride, int radius,
                     const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::medianFilter(surfaceOf(rgba, width, height, stride), radius,
                                         maskOf(mask, mask_stride));
    });
}

int cs_filter_pixelate(uint8_t* rgba, int width, int height, int stride,
                       int block_width, int block_height,
                       const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::pixelate(surfaceOf(rgba, width, height, stride), block_width,
                                     block_height, maskOf(mask, mask_stride));
    });
}

int cs_filter_edge_detect(uint8_t* rgba, int width, int height, int stride,
                          double strength, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::edgeDetect(surfaceOf(rgba, width, height, stride), strength,
                                       maskOf(mask, mask_stride));
    });
}

int cs_filter_emboss(uint8_t* rgba, int width, int height, int stride,
                     double angle_degrees, double depth,
                     const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::emboss(surfaceOf(rgba, width, height, stride), angle_degrees,
                                   depth, maskOf(mask, mask_stride));
    });
}

int cs_filter_invert(uint8_t* rgba, int width, int height, int stride,
                     const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::invert(surfaceOf(rgba, width, height, stride),
                                   maskOf(mask, mask_stride));
    });
}

int cs_filter_desaturate(uint8_t* rgba, int width, int height, int stride,
                         int mode, const uint8_t* mask, int mask_stride)
{
    if (mode < 0 || mode > 2) return 0;
    return guarded([&] {
        return cc::filters::desaturate(surfaceOf(rgba, width, height, stride),
                                       static_cast<DesaturateMode>(mode),
                                       maskOf(mask, mask_stride));
    });
}

int cs_filter_hsv_adjust(uint8_t* rgba, int width, int height, int stride,
                         double hue_shift_degrees, double saturation_delta,
                         double value_delta, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::hsvAdjust(surfaceOf(rgba, width, height, stride),
                                      hue_shift_degrees, saturation_delta, value_delta,
                                      maskOf(mask, mask_stride));
    });
}

int cs_filter_selective_color(uint8_t* rgba, int width, int height, int stride,
                              const double* bands, int enabled_mask,
                              const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        if (!bands || enabled_mask < 0 ||
            enabled_mask >= (1 << cc::filters::kSelectiveBandCount))
            return false;
        cc::filters::SelectiveColorParams params;
        for (int b = 0; b < cc::filters::kSelectiveBandCount; ++b) {
            params.enabled[b] = ((enabled_mask >> b) & 1) != 0;
            for (int k = 0; k < 4; ++k) {
                const double v = bands[b * 4 + k];
                // Hors plage float : refusé plutôt que converti en infini.
                if (!(v > -1e30 && v < 1e30)) return false;
                params.band[b][k] = static_cast<float>(v);
            }
        }
        return cc::filters::selectiveColor(surfaceOf(rgba, width, height, stride),
                                           params, maskOf(mask, mask_stride));
    });
}

int cs_filter_hue_saturation(uint8_t* rgba, int width, int height, int stride,
                             double hue_degrees, double saturation_percent,
                             double lightness_percent, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::hueSaturation(surfaceOf(rgba, width, height, stride), hue_degrees,
                                          saturation_percent, lightness_percent,
                                          maskOf(mask, mask_stride));
    });
}

int cs_filter_vibrance(uint8_t* rgba, int width, int height, int stride,
                       double vibrance_percent, double saturation_percent,
                       const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::vibrance(surfaceOf(rgba, width, height, stride), vibrance_percent,
                                     saturation_percent, maskOf(mask, mask_stride));
    });
}

int cs_filter_color_balance(uint8_t* rgba, int width, int height, int stride,
                            const double* shifts, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        if (!shifts) return false;
        cc::filters::ColorBalanceParams params;
        for (int k = 0; k < 3; ++k) {
            const double v[3] = {shifts[k], shifts[3 + k], shifts[6 + k]};
            for (double x : v)
                if (!(x > -1e30 && x < 1e30)) return false;
            params.shadows[k] = static_cast<float>(v[0]);
            params.midtones[k] = static_cast<float>(v[1]);
            params.highlights[k] = static_cast<float>(v[2]);
        }
        return cc::filters::colorBalance(surfaceOf(rgba, width, height, stride), params,
                                         maskOf(mask, mask_stride));
    });
}

int cs_filter_luminosity_blend(uint8_t* dst, int width, int height, int stride,
                               const uint8_t* source, int source_stride, int mode,
                               double amount, double feather, int invert)
{
    return guarded([&] {
        if (mode < 0 || mode > 3) return false;
        return cc::filters::luminosityBlend(
            surfaceOf(dst, width, height, stride), source, source_stride,
            static_cast<cc::filters::LuminosityMode>(mode), amount, feather, invert != 0);
    });
}

static bool effectParams(int size, int r, int g, int b, int a, cc::filters::LayerEffectParams& out)
{
    for (int v : {r, g, b, a})
        if (v < 0 || v > 255) return false;
    out.size = size;
    out.color[0] = static_cast<uint8_t>(r); out.color[1] = static_cast<uint8_t>(g);
    out.color[2] = static_cast<uint8_t>(b); out.color[3] = static_cast<uint8_t>(a);
    return true;
}

int cs_filter_drop_shadow(uint8_t* rgba, int width, int height, int stride, int offset_x,
                          int offset_y, int size, int r, int g, int b, int a)
{
    return guarded([&] {
        cc::filters::LayerEffectParams params;
        if (!effectParams(size, r, g, b, a, params)) return false;
        params.offsetX = offset_x;
        params.offsetY = offset_y;
        return cc::filters::dropShadow(surfaceOf(rgba, width, height, stride), params);
    });
}

int cs_filter_stroke(uint8_t* rgba, int width, int height, int stride, int size,
                     int r, int g, int b, int a)
{
    return guarded([&] {
        cc::filters::LayerEffectParams params;
        if (!effectParams(size, r, g, b, a, params)) return false;
        return cc::filters::outlineStroke(surfaceOf(rgba, width, height, stride), params);
    });
}

int cs_filter_blend_by_alpha(uint8_t* dst, int width, int height, int stride,
                             const uint8_t* changed, int changed_stride,
                             const uint8_t* mask_source, int mask_stride)
{
    return guarded([&] {
        return cc::filters::blendByAlpha(surfaceOf(dst, width, height, stride), changed,
                                         changed_stride, mask_source, mask_stride);
    });
}

int cs_filter_selection_feather(uint8_t* mask, int width, int height, int stride, int radius)
{
    return guarded([&] {
        return cc::filters::selectionFeather(surfaceOf(mask, width, height, stride), radius);
    });
}

int cs_filter_selection_morph(uint8_t* mask, int width, int height, int stride, int radius,
                              int grow)
{
    return guarded([&] {
        return cc::filters::selectionMorph(surfaceOf(mask, width, height, stride), radius,
                                           grow != 0);
    });
}

int cs_filter_select_color_range(uint8_t* mask, int width, int height, int stride,
                                 const uint8_t* source, int source_stride,
                                 int red, int green, int blue, int tolerance)
{
    return guarded([&] {
        return cc::filters::selectColorRange(surfaceOf(mask, width, height, stride), source,
                                             source_stride, red, green, blue, tolerance);
    });
}

int cs_filter_posterize(uint8_t* rgba, int width, int height, int stride,
                        int levels, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::posterize(surfaceOf(rgba, width, height, stride), levels,
                                      maskOf(mask, mask_stride));
    });
}

int cs_filter_threshold(uint8_t* rgba, int width, int height, int stride,
                        int level, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::threshold(surfaceOf(rgba, width, height, stride), level,
                                      maskOf(mask, mask_stride));
    });
}

int cs_filter_add_noise(uint8_t* rgba, int width, int height, int stride,
                        double amount, uint64_t seed, int gaussian,
                        int monochrome, int affect_alpha,
                        const uint8_t* mask, int mask_stride)
{
    NoiseOptions options;
    options.amount = amount;
    options.seed = seed;
    options.gaussian = gaussian != 0;
    options.monochrome = monochrome != 0;
    options.affectAlpha = affect_alpha != 0;
    return guarded([&] {
        return cc::filters::addNoise(surfaceOf(rgba, width, height, stride), options,
                                     maskOf(mask, mask_stride));
    });
}

int cs_filter_color_to_alpha(uint8_t* rgba, int width, int height, int stride,
                             int red, int green, int blue, double tolerance,
                             const uint8_t* mask, int mask_stride)
{
    if (red < 0 || red > 255 || green < 0 || green > 255 || blue < 0 || blue > 255)
        return 0;
    return guarded([&] {
        return cc::filters::colorToAlpha(surfaceOf(rgba, width, height, stride),
                                         static_cast<uint8_t>(red),
                                         static_cast<uint8_t>(green),
                                         static_cast<uint8_t>(blue), tolerance,
                                         maskOf(mask, mask_stride));
    });
}

int cs_filter_build_levels_lut(int in_black, int in_white, double gamma,
                               int out_black, int out_white, uint8_t* lut256)
{
    if (!lut256) return 0;
    cc::filters::buildLevelsLut(in_black, in_white, gamma, out_black, out_white, lut256);
    return 1;
}

int cs_filter_build_brightness_contrast_lut(double brightness, double contrast,
                                            uint8_t* lut256)
{
    if (!lut256) return 0;
    cc::filters::buildBrightnessContrastLut(brightness, contrast, lut256);
    return 1;
}

int cs_filter_build_curve_lut(const double* xs, const double* ys, int count,
                              uint8_t* lut256)
{
    if (!lut256) return 0;
    return guarded([&] { return cc::filters::buildCurveLut(xs, ys, count, lut256); });
}

int cs_filter_apply_lut(uint8_t* rgba, int width, int height, int stride,
                        const uint8_t* red_lut, const uint8_t* green_lut,
                        const uint8_t* blue_lut, const uint8_t* mask,
                        int mask_stride)
{
    return guarded([&] {
        return cc::filters::applyLut(surfaceOf(rgba, width, height, stride), red_lut,
                                     green_lut, blue_lut, maskOf(mask, mask_stride));
    });
}

int cs_filter_gradient_map(uint8_t* rgba, int width, int height, int stride,
                           const uint8_t* table256_rgba, const uint8_t* mask,
                           int mask_stride)
{
    return guarded([&] {
        return cc::filters::gradientMap(surfaceOf(rgba, width, height, stride), table256_rgba,
                                        maskOf(mask, mask_stride));
    });
}

int cs_filter_lut3d(uint8_t* rgba, int width, int height, int stride,
                    const float* table, int size, const uint8_t* mask, int mask_stride)
{
    return guarded([&] {
        return cc::filters::lut3d(surfaceOf(rgba, width, height, stride), table, size,
                                  maskOf(mask, mask_stride));
    });
}

int cs_filter_set_alpha(uint8_t* rgba, int width, int height, int stride, int alpha)
{
    return guarded([&] {
        if (alpha < 0 || alpha > 255) return false;
        return cc::filters::setAlpha(surfaceOf(rgba, width, height, stride),
                                     static_cast<uint8_t>(alpha));
    });
}

int cs_filter_copy_alpha(uint8_t* rgba, int width, int height, int stride,
                         const uint8_t* source, int source_stride)
{
    return guarded([&] {
        return cc::filters::copyAlpha(surfaceOf(rgba, width, height, stride), source,
                                      source_stride);
    });
}

long cs_psd_unpackbits(const uint8_t* input, size_t length, uint8_t* output, size_t capacity)
{
    try {
        return cc::filters::unpackBits(input, length, output, capacity);
    } catch (...) {
        return -1;
    }
}

} // extern "C"

// ------------------------------------------------- calques de filtre (v2) ----

namespace {

using cc::filters::FilterDescriptor;
using cc::filters::FilterKind;
using cc::filters::Rect;
using cc::filters::StackEntry;
using cc::filters::StackSource;

bool decodePayload(const uint8_t* payload, int size, FilterDescriptor* out)
{
    return payload && size > 0 &&
           cc::filters::decodeDescriptor(payload, static_cast<size_t>(size), *out);
}

DocumentState* documentOf(CreativeDocumentHandle handle)
{
    return static_cast<DocumentState*>(handle);
}

class CallbackSource : public StackSource
{
public:
    CallbackSource(CsStackComposeFn compose, CsStackCoverageFn coverage, void* user)
        : compose_(compose), coverage_(coverage), user_(user)
    {
    }

    bool composeRaster(const int* ids, int count, const uint8_t* backdrop,
                       const Rect& rect, uint8_t* out) override
    {
        if (!compose_(user_, ids, count, backdrop, rect.x0, rect.y0, rect.width(),
                      rect.height(), out)) {
            failed = true;
            return false;
        }
        return true;
    }

    bool filterCoverage(int entryIndex, const Rect& rect, uint8_t* out) override
    {
        if (!coverage_) return false;
        const int r = coverage_(user_, entryIndex, rect.x0, rect.y0, rect.width(),
                                rect.height(), out);
        if (r < 0) failed = true;
        return r > 0;
    }

private:
    CsStackComposeFn compose_;
    CsStackCoverageFn coverage_;
    void* user_;
};

} // namespace

extern "C" {

int cs_filter_descriptor_encode(int kind, int edge, int point_count,
                                const double* params8, uint8_t* out, int capacity,
                                int* size)
{
    if (!params8 || !out || !size || kind < 0 || kind > 255 ||
        (edge != 0 && edge != 1) || point_count < 0 || point_count > 255 ||
        capacity < static_cast<int>(cc::filters::kDescriptorBytes))
        return 0;
    return guarded([&] {
        FilterDescriptor d;
        d.kind = static_cast<FilterKind>(kind);
        d.edge = edge == 1 ? EdgeMode::Wrap : EdgeMode::Clamp;
        d.pointCount = point_count;
        std::copy(params8, params8 + cc::filters::kFilterParamCount, d.params);
        std::vector<uint8_t> bytes;
        if (!cc::filters::encodeDescriptor(d, bytes)) return false;
        std::memcpy(out, bytes.data(), bytes.size());
        *size = static_cast<int>(bytes.size());
        return true;
    });
}

int cs_filter_descriptor_decode(const uint8_t* payload, int size, int* kind,
                                int* edge, int* point_count, double* params8)
{
    if (!kind || !edge || !point_count || !params8) return 0;
    FilterDescriptor d;
    if (!decodePayload(payload, size, &d)) return 0;
    *kind = static_cast<int>(d.kind);
    *edge = d.edge == EdgeMode::Wrap ? 1 : 0;
    *point_count = d.pointCount;
    std::copy(d.params, d.params + cc::filters::kFilterParamCount, params8);
    return 1;
}

int cs_filter_descriptor_reach(const uint8_t* payload, int size, int* reach)
{
    FilterDescriptor d;
    if (!reach || !decodePayload(payload, size, &d)) return 0;
    *reach = cc::filters::descriptorReach(d);
    return 1;
}

int cs_filter_descriptor_expand_rect(const uint8_t* payload, int size, int doc_width,
                                     int doc_height, int x0, int y0, int x1, int y1,
                                     int* out4)
{
    FilterDescriptor d;
    if (!out4 || !decodePayload(payload, size, &d) || doc_width <= 0 || doc_height <= 0 ||
        x0 < 0 || y0 < 0 || x1 <= x0 || y1 <= y0 || x1 > doc_width || y1 > doc_height)
        return 0;
    const Rect r = cc::filters::expandRectForFilter(d, Rect{x0, y0, x1, y1}, doc_width,
                                                    doc_height);
    out4[0] = r.x0;
    out4[1] = r.y0;
    out4[2] = r.x1;
    out4[3] = r.y1;
    return 1;
}

int cs_filter_descriptor_apply(uint8_t* rgba, int width, int height, int stride,
                               int origin_x, int origin_y, const uint8_t* payload,
                               int size, float opacity, const uint8_t* mask,
                               int mask_stride)
{
    FilterDescriptor d;
    if (!decodePayload(payload, size, &d) || !std::isfinite(opacity) || opacity < 0.0f ||
        opacity > 1.0f)
        return 0;
    return guarded([&] {
        Surface s = surfaceOf(rgba, width, height, stride);
        s.originX = origin_x;
        s.originY = origin_y;
        if (!s.valid()) return false;
        if (opacity <= 0.0f) return true; // sans effet
        if (opacity >= 1.0f)
            return cc::filters::applyDescriptor(s, d, maskOf(mask, mask_stride));
        std::vector<uint8_t> original(static_cast<size_t>(width) * height * 4);
        for (int y = 0; y < height; ++y)
            std::memcpy(original.data() + static_cast<size_t>(y) * width * 4,
                        rgba + static_cast<size_t>(y) * stride,
                        static_cast<size_t>(width) * 4);
        if (!cc::filters::applyDescriptor(s, d, maskOf(mask, mask_stride))) return false;
        for (int y = 0; y < height; ++y) {
            uint8_t* row = rgba + static_cast<size_t>(y) * stride;
            const uint8_t* orig = original.data() + static_cast<size_t>(y) * width * 4;
            for (int i = 0; i < width * 4; ++i) {
                const float o = orig[i], f = row[i];
                row[i] = static_cast<uint8_t>(
                    std::min(255.0f, std::max(0.0f, std::floor(o + (f - o) * opacity + 0.5f))));
            }
        }
        return true;
    });
}

int cs_document_add_filter_layer(CreativeDocumentHandle handle, const char* name,
                                 const uint8_t* payload, int size, int* index)
{
    if (!handle || !name || !index || !payload || size <= 0) return 0;
    return guarded([&] {
        return documentOf(handle)->addFilterLayer(name, payload, static_cast<size_t>(size),
                                                  *index);
    });
}

int cs_document_set_filter_payload(CreativeDocumentHandle handle, int index,
                                   const uint8_t* payload, int size)
{
    if (!handle || !payload || size <= 0) return 0;
    return guarded([&] {
        return documentOf(handle)->setFilterPayload(index, payload, static_cast<size_t>(size));
    });
}

int cs_document_layer_kind(CreativeDocumentHandle handle, int index)
{
    if (!handle) return -1;
    NativeLayerState layer;
    if (!documentOf(handle)->layerInfo(index, layer)) return -1;
    return layer.kind;
}

int cs_document_copy_filter_payload(CreativeDocumentHandle handle, int index,
                                    uint8_t* out, int capacity, int* size)
{
    if (!handle || !out || !size) return 0;
    NativeLayerState layer;
    if (!documentOf(handle)->layerInfo(index, layer) || layer.kind != kLayerKindFilter ||
        capacity < static_cast<int>(layer.filterPayload.size()))
        return 0;
    std::memcpy(out, layer.filterPayload.data(), layer.filterPayload.size());
    *size = static_cast<int>(layer.filterPayload.size());
    return 1;
}

int cs_filter_stack_evaluate(const CsFilterStackEntry* entries, int count,
                             int doc_width, int doc_height, int x, int y, int width,
                             int height, CsStackComposeFn compose,
                             CsStackCoverageFn coverage, void* user, uint8_t* out,
                             int out_capacity)
{
    if (!compose || !out || count < 0 || count > 4096 || (count > 0 && !entries) ||
        width <= 0 || height <= 0 || doc_width <= 0 || doc_height <= 0)
        return 0;
    const long long needed = static_cast<long long>(width) * height * 4;
    if (needed > static_cast<long long>(out_capacity)) return 0;
    return guarded([&] {
        std::vector<StackEntry> stack(static_cast<size_t>(count));
        for (int i = 0; i < count; ++i) {
            StackEntry& e = stack[static_cast<size_t>(i)];
            e.isFilter = entries[i].is_filter != 0;
            e.visible = entries[i].visible != 0;
            e.opacity = entries[i].opacity;
            e.rasterId = entries[i].raster_id;
            if (e.isFilter && !decodePayload(entries[i].payload, entries[i].payload_size, &e.filter))
                return false;
            if (e.isFilter && !std::isfinite(e.opacity)) return false;
        }
        CallbackSource source(compose, coverage, user);
        std::vector<uint8_t> result;
        if (!cc::filters::evaluateStack(stack, source, doc_width, doc_height,
                                        Rect{x, y, x + width, y + height}, result))
            return false;
        std::memcpy(out, result.data(), result.size());
        return true;
    });
}

} // extern "C"
