#include "stack_compositor.h"
#include "projection_compositor.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace {

using projection_compositor::Pixel;
using projection_compositor::RGB;

struct Prepared {
    float p[11];
    float w[3];
    int opposite;
    float total;
    float opacity;
};

void prepare(const CsStackOp& op, Prepared& out)
{
    for (int k = 0; k < 11; ++k) out.p[k] = op.parameters[k];
    out.p[0] = std::clamp(out.p[0], 0.0f, 1.0f);
    out.p[1] = std::clamp(out.p[1], 0.0f, 1.0f);
    out.p[2] = std::clamp(out.p[2], 0.0f, 1.0f);
    out.p[3] = std::clamp(out.p[3], 0.5f, 2.5f);
    out.p[4] = std::clamp(out.p[4], 0.0f, 1.0f);
    out.p[5] = std::clamp(out.p[5], 0.0f, 1.0f);
    out.p[6] = std::clamp(out.p[6], 0.0f, 1.0f);
    out.p[7] = std::clamp(out.p[7], 0.0f, 1.0f);
    out.p[8] = std::clamp(out.p[8], -180.0f, 180.0f);
    out.p[9] = std::clamp(out.p[9], 0.0f, 2.0f);
    out.p[10] = std::clamp(out.p[10], 0.0f, 1.0f);
    out.opposite = projection_compositor::opposite(op.mode);
    out.w[0] = out.p[2] * (1.0f - out.p[4]) * (1.0f - out.p[1]);
    out.w[1] = 1.0f - out.p[2] * (1.0f - out.p[4]);
    out.w[2] = out.p[2] * (1.0f - out.p[4]) * out.p[1];
    out.total = out.w[0] + out.w[1] + (out.opposite >= 0 ? out.w[2] : 0.0f);
    out.opacity = std::clamp(op.opacity, 0.0f, 1.0f) * out.p[0];
}

inline void readPixel(const CsStackOp& op, int x, int y, RGB& rgb, float& a)
{
    if (!op.pixels) { rgb = {0, 0, 0}; a = 0.0f; return; }
    const uint8_t* px = op.pixels + static_cast<size_t>(y) * op.stride + static_cast<size_t>(x) * 4u;
    if (op.format == CS_STACK_PIXELS_RGBA8888) {
        rgb = {px[0] / 255.0f, px[1] / 255.0f, px[2] / 255.0f};
    } else {
        rgb = {px[2] / 255.0f, px[1] / 255.0f, px[0] / 255.0f};
    }
    a = px[3] / 255.0f;
}

inline float maskAt(const CsStackOp& op, int x, int y)
{
    if (!op.mask) return 1.0f;
    return op.mask[static_cast<size_t>(y) * op.mask_stride + static_cast<size_t>(x) * 4u + 3u] / 255.0f;
}

RGB adjust(const CsStackOp& op, const RGB& in)
{
    RGB out = in;
    if (op.adjust_kind == CS_STACK_ADJUST_RGB_TABLES) {
        const auto* t = static_cast<const uint8_t*>(op.table);
        for (int c = 0; c < 3; ++c) {
            const int i = static_cast<int>(std::lround(std::clamp(in[c], 0.0f, 1.0f) * 255.0f));
            out[c] = t[c * 256 + i] / 255.0f;
        }
    } else if (op.adjust_kind == CS_STACK_ADJUST_GRADIENT) {
        const auto* t = static_cast<const uint8_t*>(op.table);
        const float lum = std::clamp(in[0] * 0.30f + in[1] * 0.59f + in[2] * 0.11f, 0.0f, 1.0f) * 255.0f;
        const int i = std::min(254, static_cast<int>(lum));
        const float f = std::min(1.0f, lum - static_cast<float>(i));
        for (int c = 0; c < 3; ++c)
            out[c] = (t[i * 4 + c] * (1.0f - f) + t[(i + 1) * 4 + c] * f) / 255.0f;
    } else if (op.adjust_kind == CS_STACK_ADJUST_LUT3D) {
        const auto* t = static_cast<const float*>(op.table);
        const int n = op.table_size;
        int i0[3];
        float f[3];
        for (int c = 0; c < 3; ++c) {
            const float p = std::clamp(in[c], 0.0f, 1.0f) * static_cast<float>(n - 1);
            int b = static_cast<int>(p);
            if (b >= n - 1) b = n - 2;
            i0[c] = b;
            f[c] = p - static_cast<float>(b);
        }
        RGB acc{0, 0, 0};
        for (int corner = 0; corner < 8; ++corner) {
            const int r = i0[0] + (corner & 1), g = i0[1] + ((corner >> 1) & 1),
                      b = i0[2] + ((corner >> 2) & 1);
            const float w = ((corner & 1) ? f[0] : 1 - f[0]) *
                            (((corner >> 1) & 1) ? f[1] : 1 - f[1]) *
                            (((corner >> 2) & 1) ? f[2] : 1 - f[2]);
            const float* v = t + ((static_cast<size_t>(b) * n + g) * n + r) * 3u;
            acc[0] += w * v[0]; acc[1] += w * v[1]; acc[2] += w * v[2];
        }
        out = {std::clamp(acc[0], 0.0f, 1.0f), std::clamp(acc[1], 0.0f, 1.0f),
               std::clamp(acc[2], 0.0f, 1.0f)};
    }
    return out;
}

struct Frame {
    Pixel acc;
    bool pending = false;
    bool pendingHidden = false;
    bool replace = false;      // adjustment used as a clip base: overwrite, don't blend
    RGB work{};
    float baseAlpha = 0.0f;
    int baseOp = -1;
};

// Blend `rgb` on an opaque working colour and keep it opaque (clip "atop").
inline RGB blendOpaque(const RGB& work, const RGB& rgb, float alpha, const CsStackOp& op,
                       const Prepared& p)
{
    Pixel tmp;
    tmp.rgb = work;
    tmp.a = 1.0f;
    projection_compositor::compose_layer(tmp, rgb, std::clamp(alpha, 0.0f, 1.0f), op.mode, p.p,
                                         p.opposite, p.w, p.total);
    return tmp.rgb;
}

void flush(Frame& f, const CsStackOp* ops, const std::vector<Prepared>& prepared)
{
    if (!f.pending) return;
    f.pending = false;
    if (f.pendingHidden) return;
    if (f.replace) { f.acc.rgb = f.work; return; }
    const auto& op = ops[f.baseOp];
    const auto& p = prepared[static_cast<size_t>(f.baseOp)];
    const float alpha = std::clamp(f.baseAlpha * p.opacity, 0.0f, 1.0f);
    if (alpha <= 0.0f) return;
    projection_compositor::compose_layer(f.acc, f.work, alpha, op.mode, p.p, p.opposite, p.w,
                                         p.total);
}

} // namespace

extern "C" int cs_compose_stack(uint8_t* target, int width, int height, int targetStride,
                                const CsStackOp* ops, int opCount)
{
    if (!target || width <= 0 || height <= 0 || targetStride < width * 4 || opCount < 0 ||
        opCount > 65536 || (opCount > 0 && !ops) ||
        static_cast<long long>(width) * height > 268435456LL)
        return 0;
    int depth = 0, maxDepth = 1;
    std::vector<Prepared> prepared(static_cast<size_t>(opCount));
    for (int i = 0; i < opCount; ++i) {
        const auto& op = ops[i];
        if (op.kind < 0 || op.kind > 3 || op.mode < 0 || op.mode > 15 || !std::isfinite(op.opacity))
            return 0;
        for (float v : op.parameters) if (!std::isfinite(v)) return 0;
        if (op.kind == CS_STACK_RASTER && op.pixels &&
            (op.stride < width * 4 || (op.format != 0 && op.format != 1)))
            return 0;
        if (op.mask && op.mask_stride < width * 4) return 0;
        if (op.kind == CS_STACK_ADJUST && op.visible) {
            if (!op.table) return 0;
            if (op.adjust_kind == CS_STACK_ADJUST_LUT3D && (op.table_size < 2 || op.table_size > 256))
                return 0;
            if (op.adjust_kind < 0 || op.adjust_kind > 2) return 0;
        }
        if (op.kind == CS_STACK_GROUP_BEGIN) maxDepth = std::max(maxDepth, ++depth + 1);
        if (op.kind == CS_STACK_GROUP_END && --depth < 0) return 0;
        prepared[static_cast<size_t>(i)] = Prepared{};
        prepare(op, prepared[static_cast<size_t>(i)]);
    }
    if (depth != 0) return 0;

#ifdef _OPENMP
#pragma omp parallel for schedule(static) if(static_cast<long long>(width) * height >= 65536)
#endif
    for (int y = 0; y < height; ++y) {
        std::vector<Frame> frames;
        frames.reserve(static_cast<size_t>(maxDepth) + 1);
        uint8_t* row = target + static_cast<size_t>(y) * targetStride;
        for (int x = 0; x < width; ++x) {
            frames.clear();
            frames.emplace_back();
            for (int i = 0; i < opCount; ++i) {
                const auto& op = ops[i];
                const auto& p = prepared[static_cast<size_t>(i)];
                Frame& f = frames.back();
                switch (op.kind) {
                case CS_STACK_RASTER: {
                    if (op.clipping) {
                        if (!f.pending || f.pendingHidden || !op.visible) break;
                        RGB rgb; float a;
                        readPixel(op, x, y, rgb, a);
                        a *= maskAt(op, x, y) * p.opacity;
                        if (a > 0.0f) f.work = blendOpaque(f.work, rgb, a, op, p);
                        break;
                    }
                    flush(f, ops, prepared);
                    f.pending = true;
                    f.replace = false;
                    f.pendingHidden = !op.visible;
                    if (!op.visible) break;
                    readPixel(op, x, y, f.work, f.baseAlpha);
                    f.baseAlpha *= maskAt(op, x, y);
                    f.baseOp = i;
                    break;
                }
                case CS_STACK_GROUP_BEGIN:
                    flush(f, ops, prepared);
                    frames.emplace_back();
                    break;
                case CS_STACK_GROUP_END: {
                    flush(frames.back(), ops, prepared);
                    const Pixel child = frames.back().acc;
                    frames.pop_back();
                    Frame& parent = frames.back();
                    parent.pending = true;
                    parent.replace = false;
                    parent.pendingHidden = !op.visible;
                    parent.work = child.rgb;
                    parent.baseAlpha = child.a * maskAt(op, x, y);
                    parent.baseOp = i;
                    break;
                }
                case CS_STACK_ADJUST: {
                    if (op.clipping) {
                        if (!f.pending || f.pendingHidden || !op.visible) break;
                        const float cover = p.opacity * maskAt(op, x, y);
                        if (cover > 0.0f) f.work = blendOpaque(f.work, adjust(op, f.work), cover, op, p);
                        break;
                    }
                    flush(f, ops, prepared);
                    if (!op.visible) {
                        f.pending = true;
                        f.pendingHidden = true;
                        break;
                    }
                    const float cover = p.opacity * maskAt(op, x, y);
                    if (f.acc.a > 0.0f && cover > 0.0f)
                        f.acc.rgb = blendOpaque(f.acc.rgb, adjust(op, f.acc.rgb), cover, op, p);
                    // Layers clipped onto an adjustment act on the stack below it.
                    f.pending = true;
                    f.pendingHidden = false;
                    f.replace = true;
                    f.work = f.acc.rgb;
                    f.baseAlpha = f.acc.a;
                    f.baseOp = i;
                    break;
                }
                default:
                    break;
                }
            }
            flush(frames.back(), ops, prepared);
            const Pixel& out = frames.front().acc;
            uint8_t* px = row + static_cast<size_t>(x) * 4u;
            auto to8 = [](float v) {
                return static_cast<uint8_t>(std::clamp(std::lround(v * 255.0f), 0l, 255l));
            };
            const float a = std::clamp(out.a, 0.0f, 1.0f);
            px[0] = a > 0.0f ? to8(out.rgb[2]) : 0;
            px[1] = a > 0.0f ? to8(out.rgb[1]) : 0;
            px[2] = a > 0.0f ? to8(out.rgb[0]) : 0;
            px[3] = to8(a);
        }
    }
    return 1;
}

extern "C" int cs_compose_stack_batch(CsStackJob* jobs, int jobCount)
{
    if (!jobs || jobCount <= 0 || jobCount > 65536) return 0;
    int succeeded = 0;
#ifdef _OPENMP
#pragma omp parallel for schedule(dynamic, 1) reduction(+:succeeded) if(jobCount > 1)
#endif
    for (int i = 0; i < jobCount; ++i) {
        CsStackJob& job = jobs[i];
        job.result = cs_compose_stack(job.target, job.width, job.height, job.target_stride,
                                      job.ops, job.op_count);
        succeeded += job.result;
    }
    return succeeded;
}
