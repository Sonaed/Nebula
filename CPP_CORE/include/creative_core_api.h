#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void* CreativeBrushHandle;
typedef void* CreativeProjectionHandle;
typedef void* CreativeNebulaWriterHandle;
typedef void* CreativeNebulaReaderHandle;
typedef void* CreativeAtlasReaderHandle;
typedef void* CreativeTileStoreHandle;
typedef void* CreativeTextureAtlasHandle;
typedef void* CreativeHistoryCursorHandle;
typedef void* CreativeHistoryPayloadHandle;
typedef void* CreativeDocumentHandle;

// Native document/layer metadata model. Qt/Python owns presentation objects;
// structural state and validation remain in CreativeCore.
CreativeDocumentHandle cs_document_create(int width, int height, int dpi);
void cs_document_destroy(CreativeDocumentHandle handle);
int cs_document_add_layer(CreativeDocumentHandle handle, const char* name,
                          int* index);
void cs_document_reset_layers(CreativeDocumentHandle handle);
int cs_document_create_group(CreativeDocumentHandle handle, const int* indices,
                             int count, const char* name, int* group_index);
int cs_document_remove_group(CreativeDocumentHandle handle, int group_index);
int cs_document_set_group_property(CreativeDocumentHandle handle, int group_index,
                                   int property, double requested, double* output);
void cs_document_reset_groups(CreativeDocumentHandle handle);
int cs_document_group_count(CreativeDocumentHandle handle);
int cs_document_group_for_layer(CreativeDocumentHandle handle, int layer_index);
int cs_document_remove_layer(CreativeDocumentHandle handle, int index);
int cs_document_reorder_layers(CreativeDocumentHandle handle, const int* order,
                               int count, int active_index);
int cs_document_select_layer(CreativeDocumentHandle handle, int index);
int cs_document_rename_layer(CreativeDocumentHandle handle, int index,
                             const char* name);
int cs_document_set_layer_property(CreativeDocumentHandle handle, int index,
                                   int property, double requested,
                                   double* output);
int cs_document_layer_count(CreativeDocumentHandle handle);
int cs_document_active_layer(CreativeDocumentHandle handle);
int cs_document_layer_info(CreativeDocumentHandle handle, int index,
                           uint64_t* id, int* visible, float* opacity,
                           int* locked, int* lock_alpha, int* clipping);
int cs_document_copy_layer_name(CreativeDocumentHandle handle, int index,
                                char* output, int capacity);

typedef struct CsImageView {
    const uint8_t* pixels;
    int width;
    int height;
    int stride;
    int image_format;
} CsImageView;

// Native RGBA texture-atlas packing/storage.  The UI adapter only supplies
// image bytes and receives packed rectangles; shelf allocation and backing
// pixels remain owned by CreativeCore.
CreativeTextureAtlasHandle cs_texture_atlas_create(int size, int padding);
void cs_texture_atlas_destroy(CreativeTextureAtlasHandle handle);
int cs_texture_atlas_add(CreativeTextureAtlasHandle handle, int width, int height,
                         int* x, int* y);
int cs_texture_atlas_write(CreativeTextureAtlasHandle handle, int x, int y,
                           const uint8_t* pixels, int width, int height,
                           int stride);
int cs_texture_atlas_copy(CreativeTextureAtlasHandle handle, int x, int y,
                          uint8_t* output, int width, int height, int stride);

typedef struct CsHistoryImagePair {
    CsImageView before;
    CsImageView after;
    int has_before;
    int has_after;
} CsHistoryImagePair;

typedef struct CsHistoryStoreWrite {
    CreativeTileStoreHandle store;
    int payload_index;
    int tile_x;
    int tile_y;
} CsHistoryStoreWrite;

typedef struct CsTileWrite {
    int tile_x;
    int tile_y;
    const uint8_t* pixels;
    int width;
    int height;
    int stride;
    int image_format;
} CsTileWrite;

typedef struct CsCompositeLayer {
    const uint8_t* pixels;
    int stride;
    int image_format;
    float opacity;
    int mode;
    int visible;
} CsCompositeLayer;

typedef struct CsAdvancedCompositeLayer {
    const uint8_t* pixels;
    int stride;
    float opacity;
    int mode;
    int visible;
    int clipping;
    float parameters[11];
} CsAdvancedCompositeLayer;

CreativeHistoryCursorHandle cs_history_cursor_create(int maximum_steps);
void cs_history_cursor_destroy(CreativeHistoryCursorHandle handle);
void cs_history_cursor_reset(CreativeHistoryCursorHandle handle);
int cs_history_cursor_begin_transaction(CreativeHistoryCursorHandle handle,
                                        int dirty_only, int selection_only,
                                        int structure_only);
int cs_history_cursor_commit_transaction(CreativeHistoryCursorHandle handle);
int cs_history_cursor_cancel_transaction(CreativeHistoryCursorHandle handle);
int cs_history_cursor_transaction_open(CreativeHistoryCursorHandle handle);
int cs_history_cursor_transaction_mode(CreativeHistoryCursorHandle handle);
int cs_history_cursor_append(CreativeHistoryCursorHandle handle,
                             int* truncated_forward, int* discarded_oldest);
int cs_history_cursor_append_state(CreativeHistoryCursorHandle handle,
                                   const uint8_t* before, uint32_t before_size,
                                   const uint8_t* after, uint32_t after_size,
                                   int* truncated_forward, int* discarded_oldest);
uint32_t cs_history_cursor_state_size(CreativeHistoryCursorHandle handle,
                                      int index, int side);
int cs_history_cursor_copy_state(CreativeHistoryCursorHandle handle, int index,
                                 int side, uint8_t* output, uint32_t capacity);
int cs_history_cursor_discard_oldest(CreativeHistoryCursorHandle handle, int count);
int cs_history_cursor_set_maximum(CreativeHistoryCursorHandle handle, int maximum_steps);
int cs_history_cursor_undo(CreativeHistoryCursorHandle handle);
int cs_history_cursor_redo(CreativeHistoryCursorHandle handle);
void cs_history_cursor_synchronize(CreativeHistoryCursorHandle handle,
                                   int step_count, int index);
int cs_history_validate_layer_state(const uint8_t* payload, uint32_t payload_size,
                                    int document_width, int document_height);
int cs_history_cursor_count(CreativeHistoryCursorHandle handle);
int cs_history_cursor_index(CreativeHistoryCursorHandle handle);
int cs_history_cursor_maximum(CreativeHistoryCursorHandle handle);

CreativeHistoryPayloadHandle cs_history_payload_create(void);
void cs_history_payload_destroy(CreativeHistoryPayloadHandle handle);
int cs_history_payload_append(CreativeHistoryPayloadHandle handle,
                              const CsImageView* before,
                              const CsImageView* after);
int cs_history_payload_append_many(CreativeHistoryPayloadHandle handle,
                                   const CsHistoryImagePair* items, int count,
                                   int* payload_indices, int output_capacity);
int cs_history_payload_tile_info(CreativeHistoryPayloadHandle handle, int index,
                                 int side, int* present, int* width,
                                 int* height, int* image_format);
int cs_history_payload_copy_tile(CreativeHistoryPayloadHandle handle, int index,
                                 int side, uint8_t* output, int width,
                                 int height, int stride, int image_format);
int cs_history_payload_count(CreativeHistoryPayloadHandle handle);
int64_t cs_history_payload_allocated_bytes(CreativeHistoryPayloadHandle handle);
void cs_history_payload_clear(CreativeHistoryPayloadHandle handle);
int cs_history_payload_apply_to_tile_stores(CreativeHistoryPayloadHandle payload,
                                            const CsHistoryStoreWrite* writes,
                                            int count, int side);

int cs_lz4_available(void);
int cs_lz4_compress_bound(int input_size);
int cs_lz4_compress(const uint8_t* input, int input_size,
                    uint8_t* output, int output_capacity, int* output_size);
int cs_lz4_decompress(const uint8_t* input, int input_size,
                      uint8_t* output, int expected_size, int* output_size);
int cs_cslz_max_encoded_size(int raw_size);
int cs_cslz_encode(const uint8_t* rgba, int width, int height, int stride,
                   uint8_t* output, int output_capacity, int* output_size);
int cs_cslz_decode_info(const uint8_t* encoded, int encoded_size,
                        int* width, int* height, int* stride,
                        int* raw_size, int* compressed);
int cs_cslz_decode(const uint8_t* encoded, int encoded_size,
                   uint8_t* output, int output_capacity);

// Sparse resident tile map; Python owns only Qt adapters and scratch files.
CreativeTileStoreHandle cs_tile_store_create(int width, int height, int tile_size);
void cs_tile_store_destroy(CreativeTileStoreHandle handle);
int cs_tile_store_set(CreativeTileStoreHandle handle, int tile_x, int tile_y,
                      const uint8_t* pixels, int width, int height, int stride,
                      int image_format);
int cs_tile_store_set_many(CreativeTileStoreHandle handle,
                           const CsTileWrite* writes, int count);
int cs_tile_store_write_image(CreativeTileStoreHandle handle, const uint8_t* pixels,
                              int width, int height, int stride, int image_format,
                              int x, int y, int dirty_width, int dirty_height,
                              int* changed_xy_pairs, int pair_capacity);
int cs_tile_store_copy(CreativeTileStoreHandle handle, int tile_x, int tile_y,
                       uint8_t* output, int width, int height, int stride,
                       int image_format);
int cs_tile_store_copy_store(CreativeTileStoreHandle destination,
                             CreativeTileStoreHandle source);
int cs_tile_store_materialize(CreativeTileStoreHandle handle, uint8_t* output,
                              int width, int height, int stride, int image_format);
int cs_tile_store_info(CreativeTileStoreHandle handle, int tile_x, int tile_y,
                       int* resident, uint64_t* revision, uint64_t* last_access);
int cs_tile_store_copy_keys(CreativeTileStoreHandle handle, int* xy_pairs,
                            int pair_capacity);
int cs_tile_store_remove(CreativeTileStoreHandle handle, int tile_x, int tile_y);
int64_t cs_tile_store_write_png(CreativeTileStoreHandle handle, int tile_x,
                                int tile_y, const char* path);
int cs_tile_store_load_png(CreativeTileStoreHandle handle, int tile_x, int tile_y,
                           const char* path, uint64_t expected_revision);
int64_t cs_image_write_png(const char* path, const uint8_t* pixels, int width,
                           int height, int stride, int image_format);
int cs_image_fill(uint8_t* pixels, int width, int height, int stride,
                  int image_format, int red, int green, int blue, int alpha);
int cs_image_fill_rect(uint8_t* pixels, int width, int height, int stride,
                       int image_format, int x, int y, int rect_width,
                       int rect_height, int red, int green, int blue, int alpha);
int cs_render_brush_preset_art(
    uint8_t* texture, int texture_width, int texture_height, int texture_stride,
    int texture_format, uint8_t* preview, int preview_width, int preview_height,
    int preview_stride, int preview_format, float hardness, float size,
    int red, int green, int blue, int alpha);
int cs_apply_alpha_mask(uint8_t* image, int image_width, int image_height,
                        int image_stride, int image_format,
                        const uint8_t* mask, int mask_width, int mask_height,
                        int mask_stride, int mask_format);
void cs_tile_store_clear(CreativeTileStoreHandle handle);
void cs_tile_store_resize(CreativeTileStoreHandle handle, int width, int height);
int64_t cs_tile_store_allocated_bytes(CreativeTileStoreHandle handle);

// Native Nebula file I/O. The UI supplies document metadata and one raw tile
// at a time; the C++ bridge owns the binary envelope, compression, CRC and
// atomic file commit.
CreativeNebulaWriterHandle cs_nebula_writer_create(
    const char* path, const uint8_t* metadata, uint32_t metadata_size,
    uint32_t chunk_count);
int cs_nebula_writer_add_tile(CreativeNebulaWriterHandle handle,
                              uint32_t chunk_id, const uint8_t* rgba,
                              uint64_t byte_count);
int cs_nebula_writer_finish(CreativeNebulaWriterHandle handle);
void cs_nebula_writer_cancel(CreativeNebulaWriterHandle handle);

CreativeNebulaReaderHandle cs_nebula_reader_open(const char* path);
uint32_t cs_nebula_reader_metadata_size(CreativeNebulaReaderHandle handle);
int cs_nebula_reader_copy_metadata(CreativeNebulaReaderHandle handle,
                                   uint8_t* output, uint32_t capacity);
uint32_t cs_nebula_reader_chunk_count(CreativeNebulaReaderHandle handle);
int cs_nebula_reader_next_tile(CreativeNebulaReaderHandle handle,
                               uint32_t* chunk_id, uint8_t* output,
                               uint64_t capacity, uint64_t* byte_count);
void cs_nebula_reader_close(CreativeNebulaReaderHandle handle);
// Validate document metadata plus tile ownership/grid/index consistency before
// image allocation. Also returns validated canvas dimensions and DPI.
int cs_nebula_validate_manifest(const uint8_t* metadata,
                                uint32_t metadata_size, uint32_t chunk_count,
                                int* width, int* height, int* dpi);

// Read-only import bridge for Atlas v2/v3 files. The reader keeps compressed
// layer data on disk and inflates one layer only when the UI requests it.
CreativeAtlasReaderHandle cs_atlas_reader_open(const char* path);
int cs_atlas_reader_document_info(CreativeAtlasReaderHandle handle,
                                  char* name, uint32_t name_capacity,
                                  char* author, uint32_t author_capacity,
                                  uint32_t* width, uint32_t* height,
                                  uint32_t* dpi, uint32_t* layer_count,
                                  char* background, uint32_t background_capacity);
int cs_atlas_reader_layer_info(CreativeAtlasReaderHandle handle,
                               uint32_t layer_index,
                               char* name, uint32_t name_capacity,
                               float* opacity, int* visible,
                               char* blend, uint32_t blend_capacity);
int cs_atlas_reader_copy_layer(CreativeAtlasReaderHandle handle,
                               uint32_t layer_index,
                               uint8_t* rgba, uint64_t rgba_capacity);
void cs_atlas_reader_close(CreativeAtlasReaderHandle handle);

typedef struct CsProjectionLayer {
    const uint8_t* rgba;
    int width;
    int height;
    int stride;
    int visible;
    float opacity;
    int blend_mode;
    // opacity, opposite_mix, intensity, gamma, mix_normal, pivot, clamp,
    // softness, hue_shift, saturation_boost, offset (in that order).
    float blend_parameters[11];
    int parameterized;
    int clipping;
} CsProjectionLayer;

typedef struct CsProjectionTile {
    uint64_t generation;
    int tile_x;
    int tile_y;
    int width;
    int height;
    const CsProjectionLayer* layers;
    int layer_count;
} CsProjectionTile;

typedef void (*CsProjectionCallback)(
    uint64_t generation, int tile_x, int tile_y,
    const uint8_t* rgba, int width, int height, int stride,
    const char* error, void* user_data);

CreativeProjectionHandle cs_projection_start(CsProjectionCallback callback, void* user_data);
void cs_projection_stop(CreativeProjectionHandle handle);
void cs_projection_set_callback(CreativeProjectionHandle handle,
                                CsProjectionCallback callback, void* user_data);
void cs_projection_set_threads(CreativeProjectionHandle handle, int thread_count);
int cs_projection_invalidate(
    CreativeProjectionHandle handle, uint64_t generation,
    int tile_x, int tile_y, int width, int height,
    const CsProjectionLayer* layers, int layer_count);
int cs_projection_invalidate_batch(
    CreativeProjectionHandle handle, const CsProjectionTile* tiles,
    int tile_count);

void cs_image_restore_alpha_rect(
    uint8_t* dst, const uint8_t* src,
    int width, int height, int dstStride, int srcStride,
    int x, int y, int rectWidth, int rectHeight);
int cs_image_restore_alpha_tile(uint8_t* dst, int dstWidth, int dstHeight,
                                int dstStride, const uint8_t* src,
                                int srcWidth, int srcHeight, int srcStride,
                                int dstX, int dstY, int srcX, int srcY,
                                int rectWidth, int rectHeight);

// Paint a foreground-to-transparent linear gradient into a caller-owned Qt
// image buffer. Geometry/events remain in the UI; raster composition is native.
int cs_apply_linear_gradient(uint8_t* pixels, int width, int height, int stride,
                             int image_format, float start_x, float start_y,
                             float end_x, float end_y,
                             int red, int green, int blue, int alpha);

// Return a permutation mapping output stack indices to input indices.
// direction is +1 for move-up and -1 for move-down; returns 1 on a move.
int cs_layer_stack_move(const int* group_ids, int layer_count, int active_index,
                        int direction, int* output_order, int* active_after);
int cs_layer_stack_remove(int layer_count, int remove_index, int active_index,
                          int* output_order, int* active_after);
int cs_layer_stack_plan_visible_merge(const int* effective_visibility,
                                      int layer_count, int active_index,
                                      int* output_keep_mask, int* target_index,
                                      int* active_after);
int cs_layer_stack_plan_visible_merge_groups(
    const int* layer_visibility, const int* group_membership,
    const int* group_visibility, int layer_count, int group_count,
    int active_index, int* output_effective_visibility,
    int* output_keep_mask, int* target_index, int* active_after);
int cs_layer_property_update(int property, double current_value,
                             double requested_value, double* output_value);
int cs_layer_group_normalize(const int* requested_indices, int requested_count,
                             const int* grouped_layers, int layer_count,
                             int* output_indices, int output_capacity,
                             int* output_count);
int cs_layer_stack_plan_composite_runs(const int* group_ids, int layer_count,
                                       int* output_starts, int* output_ends,
                                       int* output_group_ids, int output_capacity,
                                       int* output_count);
int cs_layer_stack_plan_group_cleanup(const int* layer_group_ids,
                                      const int* keep_layers, int layer_count,
                                      int group_count, int* output_keep_groups,
                                      int* output_membership, int output_capacity);
int cs_document_validate_geometry(int width, int height, int dpi,
                                  int maximum_dimension, uint64_t maximum_pixels);

// Composite one raster layer onto an existing raster using Qt's exact blend
// mode semantics; mode follows the CreativeCore projection mode numbering.
int cs_composite_layer_in_place(uint8_t* target, const uint8_t* source,
                                int width, int height, int target_stride,
                                int source_stride, int target_format,
                                int source_format, float opacity, int mode);
int cs_composite_layers(uint8_t* target, int width, int height,
                        int target_stride, int target_format,
                        const CsCompositeLayer* layers, int layer_count);
int cs_composite_layers_advanced(uint8_t* target, int width, int height,
                                 int target_stride,
                                 const CsAdvancedCompositeLayer* layers,
                                 int layer_count);

const char* cs_simd_backend();
int cs_projection_normal_batch_calls();
void cs_projection_reset_batch_calls();

void cs_filter_brush_segment(
    uint8_t* rgba, int width, int height, int stride,
    float startX, float startY, float startPressure,
    float endX, float endY, float endPressure,
    float size, float spacing, float opacity, int sharpen);

CreativeBrushHandle
cs_brush_create();

void
cs_brush_destroy(
    CreativeBrushHandle handle
);

void
cs_brush_set_size(
    CreativeBrushHandle handle,
    float size
);

void
cs_brush_set_opacity(
    CreativeBrushHandle handle,
    float opacity
);

void
cs_brush_set_flow(
    CreativeBrushHandle handle,
    float flow
);

void
cs_brush_set_hardness(
    CreativeBrushHandle handle,
    float hardness
);

void
cs_brush_set_spacing(
    CreativeBrushHandle handle,
    float spacing
);

void
cs_brush_set_roundness(
    CreativeBrushHandle handle,
    float roundness
);

void
cs_brush_set_angle(
    CreativeBrushHandle handle,
    float angle
);

void
cs_brush_set_scatter(
    CreativeBrushHandle handle,
    float scatter
);

void
cs_brush_set_size_jitter(
    CreativeBrushHandle handle,
    float jitter
);

void
cs_brush_set_rotation_jitter(
    CreativeBrushHandle handle,
    float jitter
);

void cs_brush_set_velocity_size(CreativeBrushHandle handle, float value);
void cs_brush_set_velocity_opacity(CreativeBrushHandle handle, float value);
void cs_brush_set_velocity_flow(CreativeBrushHandle handle, float value);

void
cs_brush_set_texture_strength(
    CreativeBrushHandle handle,
    float strength
);

void
cs_brush_set_texture_scale(
    CreativeBrushHandle handle,
    float scale
);

void
cs_brush_set_texture_random_scale(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_texture_random_offset(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_texture_brightness(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_texture_contrast(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_texture_mirror(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_texture_affect_opacity(
    CreativeBrushHandle handle,
    int enabled
);

// Loads and decodes a grayscale brush texture in the native brush engine.
// Returns 1 on success; invalid or oversized images leave the current texture
// unchanged. The UI may pass the chosen file path but never decodes the pixels.
int cs_brush_set_texture_path(CreativeBrushHandle handle, const char* path);
void cs_brush_clear_texture(CreativeBrushHandle handle);
int cs_brush_set_bitmap_tip_path(CreativeBrushHandle handle, const char* path);
int cs_brush_set_bitmap_tip_png(CreativeBrushHandle handle,
                                const uint8_t* data, uint64_t byte_count);
void cs_brush_clear_bitmap_tip(CreativeBrushHandle handle);

void
cs_brush_set_dirty_color(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_hue_jitter(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_saturation_jitter(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_brightness_jitter(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_stroke_gradient(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_linear_gradient(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_radial_gradient(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_gradient_amount(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_gradient_color(
    CreativeBrushHandle handle,
    uint8_t red,
    uint8_t green,
    uint8_t blue,
    uint8_t alpha
);

void
cs_brush_set_blend_mode(
    CreativeBrushHandle handle,
    int mode
);

void
cs_brush_set_paint_mix(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_wetness(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_pickup(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_dilution(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_smudge(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_paint_persistence(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_color_carry(
    CreativeBrushHandle handle,
    float value
);

void
cs_brush_set_wet_mix(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_sample_canvas(
    CreativeBrushHandle handle,
    int enabled
);

void cs_brush_set_smudge_tool(CreativeBrushHandle handle, int enabled);

void
cs_brush_set_eraser(
    CreativeBrushHandle handle,
    int enabled
);

void
cs_brush_set_color(
    CreativeBrushHandle handle,
    uint8_t red,
    uint8_t green,
    uint8_t blue,
    uint8_t alpha
);

void cs_brush_set_pressure_size(CreativeBrushHandle handle, int enabled);
void cs_brush_set_pressure_opacity(CreativeBrushHandle handle, int enabled);
void cs_brush_set_pressure_flow(CreativeBrushHandle handle, int enabled);
void cs_brush_set_minimum_size(CreativeBrushHandle handle, float value);
void cs_brush_set_minimum_opacity(CreativeBrushHandle handle, float value);
void cs_brush_set_minimum_flow(CreativeBrushHandle handle, float value);

void
cs_brush_begin_stroke(
    CreativeBrushHandle handle,
    float x,
    float y,
    float pressure
);

void
cs_brush_draw_segment(
    CreativeBrushHandle handle,
    uint8_t* rgba,
    int width,
    int height,
    int bytesPerLine,
    float startX,
    float startY,
    float startPressure,
    float endX,
    float endY,
    float endPressure
);

void cs_brush_draw_segment_clone(
    CreativeBrushHandle handle,
    uint8_t* target, const uint8_t* source,
    int width, int height, int bytesPerLine,
    int sourceBytesPerLine, int cloneOffsetX, int cloneOffsetY,
    float startX, float startY, float startPressure, float startTiltX, float startTiltY,
    float endX, float endY, float endPressure, float endTiltX, float endTiltY);

void cs_brush_draw_segment_tilt(
    CreativeBrushHandle handle, uint8_t* rgba, int width, int height,
    int bytesPerLine, float startX, float startY, float startPressure,
    float startTiltX, float startTiltY, float endX, float endY,
    float endPressure, float endTiltX, float endTiltY
);

void
cs_brush_end_stroke(
    CreativeBrushHandle handle
);
void cs_brush_set_smoothing(CreativeBrushHandle handle, float strength);
int cs_brush_smooth_point(CreativeBrushHandle handle, float x, float y, float* outX, float* outY);

int cs_fill(
    uint8_t* pixels, int width, int height, int bytesPerLine, int imageFormat,
    int startX, int startY, int tolerance,
    uint8_t red, uint8_t green, uint8_t blue, uint8_t alpha,
    int* outX, int* outY, int* outWidth, int* outHeight
);
int cs_fill_bounds(
    const uint8_t* pixels, int width, int height, int bytesPerLine, int imageFormat,
    int startX, int startY, int tolerance,
    int* outX, int* outY, int* outWidth, int* outHeight
);

int cs_magic_wand(
    const uint8_t* pixels, int width, int height, int bytesPerLine, int imageFormat,
    int startX, int startY, int tolerance,
    uint8_t* maskArgb32, int maskBytesPerLine
);

// Selection-mask primitives. operation: 0 replace, 1 add, 2 subtract, 3 intersect.
int cs_selection_combine(uint8_t* destination, const uint8_t* candidate,
                         int width, int height, int destination_stride,
                         int candidate_stride, int operation);
int cs_selection_invert(uint8_t* pixels, int width, int height, int stride);
int cs_selection_bounds(const uint8_t* pixels, int width, int height, int stride,
                        int* x, int* y, int* bounds_width, int* bounds_height);
int cs_selection_contains(const uint8_t* pixels, int width, int height, int stride,
                          int x, int y, int* selected);
// Rasterize a white ARGB32 mask: 0 rectangle, 1 ellipse, 2 closed lasso.
int cs_selection_shape_mask(uint8_t* output, int width, int height, int stride,
                            int shape, const float* points_xy, int point_count);
// Generate a painting-tool path: 0 line, 1 rectangle, 2 ellipse.
int cs_shape_path(int shape, double start_x, double start_y,
                  double end_x, double end_y, double* output_xy,
                  int point_capacity, int* point_count);
// Return an inclusive, normalized crop rectangle clipped to the document bounds.
int cs_crop_rect(int start_x, int start_y, int end_x, int end_y,
                 int bounds_x, int bounds_y, int bounds_width, int bounds_height,
                 int* crop_x, int* crop_y, int* crop_width, int* crop_height);
int cs_crop_image(const uint8_t* source, int source_width, int source_height,
                  int source_stride, int source_format, int crop_x, int crop_y,
                  int crop_width, int crop_height, uint8_t* output,
                  int output_stride, int output_format);
int cs_copy_image_rect(const uint8_t* source, int source_width, int source_height,
                       int source_stride, int source_format, int source_x,
                       int source_y, uint8_t* destination, int destination_width,
                       int destination_height, int destination_stride,
                       int destination_format, int destination_x, int destination_y,
                       int copy_width, int copy_height);
int cs_draw_text(uint8_t* image, int width, int height, int stride, int image_format,
                 const char* text_utf8, const char* font_serialized_utf8,
                 double x, double y, int red, int green, int blue, int alpha);
// Return the half-open tile-coordinate range intersecting a pixel rectangle.
int cs_tile_range_for_rect(int canvas_width, int canvas_height, int tile_size,
                           int rect_x, int rect_y, int rect_width, int rect_height,
                           int* first_tile_x, int* first_tile_y,
                           int* end_tile_x, int* end_tile_y);
int cs_transform_layer(const uint8_t* source, const uint8_t* selection,
                       int width, int height, int source_stride,
                       int selection_stride, int image_format,
                       uint8_t* output, int output_stride,
                       uint8_t* output_selection, int output_selection_stride,
                       float translate_x, float translate_y, float scale_x,
                       float scale_y, float rotation_degrees,
                       int* used_selection);
int cs_translate_image(const uint8_t* source, int width, int height,
                       int source_stride, int image_format,
                       uint8_t* output, int output_stride, int dx, int dy);

#ifdef __cplusplus
}
#endif
