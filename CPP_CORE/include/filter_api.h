#pragma once

/*
 * ABI C des filtres raster CreativeCore (voir image_filters.h).
 *
 * Contrat commun :
 *  - `rgba` : tampon RGBA8888 en alpha droit, modifié en place ; `stride` en
 *    octets (>= width * 4).  L'appelant garantit que le tampon contient au moins
 *    stride * (height - 1) + width * 4 octets : la bibliothèque ne peut pas le
 *    vérifier (l'adaptateur Python le fait avant l'appel).
 *  - `mask` : NULL, ou couverture 8 bits width x height (ligne = `mask_stride`
 *    octets, >= width).  0 = pixel intact, 255 = filtre plein.
 *  - `edge` : 0 = bord répété (clamp), 1 = repli périodique (wrap).
 *  - Retour : 1 = succès, 0 = argument invalide ou mémoire insuffisante ; dans
 *    ce cas le tampon n'est pas modifié.  Aucune exception ne traverse l'ABI.
 */

#include <stdint.h>

#include "creative_core_api.h" // CreativeDocumentHandle

#ifdef __cplusplus
extern "C" {
#endif

// Incrémenté à chaque changement incompatible de cette interface.
// 2 : descripteurs, calques de filtre du document, évaluation de pile.
// 3 : cs_filter_selective_color.
// 4 : noyaux des calques de réglage (teinte/saturation, vibrance, balance des
//     couleurs, mélange par luminosité).
#define CS_FILTER_ABI_VERSION 4
int cs_filter_abi_version(void);

int cs_filter_gaussian_blur(uint8_t* rgba, int width, int height, int stride,
                            double sigma_x, double sigma_y, int edge,
                            const uint8_t* mask, int mask_stride);
int cs_filter_box_blur(uint8_t* rgba, int width, int height, int stride,
                       int radius_x, int radius_y, int edge,
                       const uint8_t* mask, int mask_stride);
int cs_filter_motion_blur(uint8_t* rgba, int width, int height, int stride,
                          double angle_degrees, double length, int edge,
                          const uint8_t* mask, int mask_stride);
int cs_filter_unsharp_mask(uint8_t* rgba, int width, int height, int stride,
                           double sigma, double amount, int threshold, int edge,
                           const uint8_t* mask, int mask_stride);
int cs_filter_median(uint8_t* rgba, int width, int height, int stride, int radius,
                     const uint8_t* mask, int mask_stride);
int cs_filter_pixelate(uint8_t* rgba, int width, int height, int stride,
                       int block_width, int block_height,
                       const uint8_t* mask, int mask_stride);
int cs_filter_edge_detect(uint8_t* rgba, int width, int height, int stride,
                          double strength, const uint8_t* mask, int mask_stride);
int cs_filter_emboss(uint8_t* rgba, int width, int height, int stride,
                     double angle_degrees, double depth,
                     const uint8_t* mask, int mask_stride);

int cs_filter_invert(uint8_t* rgba, int width, int height, int stride,
                     const uint8_t* mask, int mask_stride);
// mode : 0 = luminance Rec. 709, 1 = moyenne, 2 = (max + min) / 2.
int cs_filter_desaturate(uint8_t* rgba, int width, int height, int stride,
                         int mode, const uint8_t* mask, int mask_stride);
int cs_filter_hsv_adjust(uint8_t* rgba, int width, int height, int stride,
                         double hue_shift_degrees, double saturation_delta,
                         double value_delta, const uint8_t* mask, int mask_stride);
// Couleur sélective.  `bands` : 9 x 4 doubles {C, M, Y, K} en pourcentage, dans
// l'ordre reds, yellows, greens, cyans, blues, magentas, whites, neutrals, blacks
// (ABI >= 3).  Bit i de `enabled_mask` : la bande i est appliquée.
int cs_filter_selective_color(uint8_t* rgba, int width, int height, int stride,
                              const double* bands, int enabled_mask,
                              const uint8_t* mask, int mask_stride);
// Calques de réglage (ABI >= 4) : mêmes résultats, au bit près, que les anciennes
// implémentations NumPy de DOCUMENTS/adjustments.py.  Pourcentages, teinte en degrés.
int cs_filter_hue_saturation(uint8_t* rgba, int width, int height, int stride,
                             double hue_degrees, double saturation_percent,
                             double lightness_percent, const uint8_t* mask, int mask_stride);
int cs_filter_vibrance(uint8_t* rgba, int width, int height, int stride,
                       double vibrance_percent, double saturation_percent,
                       const uint8_t* mask, int mask_stride);
// `shifts` : 9 doubles = ombres RGB, tons moyens RGB, hautes lumières RGB (en %).
int cs_filter_color_balance(uint8_t* rgba, int width, int height, int stride,
                            const double* shifts, const uint8_t* mask, int mask_stride);
// dst = source * (1 - m) + dst * m avec m dérivé de la luminance de `source`
// (mode : 0 plein, 1 lumières, 2 ombres, 3 tons moyens) ; alpha pris dans `source`.
int cs_filter_luminosity_blend(uint8_t* dst, int width, int height, int stride,
                               const uint8_t* source, int source_stride, int mode,
                               double amount, double feather, int invert);
// Effets de calque : size 1..32, color = RGBA 8 bits.  Ombre portée / lueur (calque
// au-dessus de l'ombre) et contour extérieur.
int cs_filter_drop_shadow(uint8_t* rgba, int width, int height, int stride, int offset_x,
                          int offset_y, int size, int r, int g, int b, int a);
int cs_filter_stroke(uint8_t* rgba, int width, int height, int stride, int size,
                     int r, int g, int b, int a);
// Écrêtage : dst.rgb = mélange(dst, changed) selon l'alpha de mask_source.
int cs_filter_blend_by_alpha(uint8_t* dst, int width, int height, int stride,
                             const uint8_t* changed, int changed_stride,
                             const uint8_t* mask_source, int mask_stride);
// Masque de sélection 32 bits (valeur = octet alpha, réécrite dans les 4 octets).
int cs_filter_selection_feather(uint8_t* mask, int width, int height, int stride, int radius);
int cs_filter_selection_morph(uint8_t* mask, int width, int height, int stride, int radius,
                              int grow);
int cs_filter_select_color_range(uint8_t* mask, int width, int height, int stride,
                                 const uint8_t* source, int source_stride,
                                 int red, int green, int blue, int tolerance);
int cs_filter_posterize(uint8_t* rgba, int width, int height, int stride,
                        int levels, const uint8_t* mask, int mask_stride);
int cs_filter_threshold(uint8_t* rgba, int width, int height, int stride,
                        int level, const uint8_t* mask, int mask_stride);
int cs_filter_add_noise(uint8_t* rgba, int width, int height, int stride,
                        double amount, uint64_t seed, int gaussian,
                        int monochrome, int affect_alpha,
                        const uint8_t* mask, int mask_stride);
int cs_filter_color_to_alpha(uint8_t* rgba, int width, int height, int stride,
                             int red, int green, int blue, double tolerance,
                             const uint8_t* mask, int mask_stride);

// Tables 256 octets fournies par l'appelant.
int cs_filter_build_levels_lut(int in_black, int in_white, double gamma,
                               int out_black, int out_white, uint8_t* lut256);
int cs_filter_build_brightness_contrast_lut(double brightness, double contrast,
                                            uint8_t* lut256);
// Retourne 0 (et laisse l'identité) si les points de contrôle sont invalides.
int cs_filter_build_curve_lut(const double* xs, const double* ys, int count,
                              uint8_t* lut256);
int cs_filter_apply_lut(uint8_t* rgba, int width, int height, int stride,
                        const uint8_t* red_lut, const uint8_t* green_lut,
                        const uint8_t* blue_lut, const uint8_t* mask,
                        int mask_stride);

// ---------------------------------------------- calques de filtre (ABI >= 2) --
//
// Un descripteur est une charge binaire de 76 octets (voir filter_layer.h) :
// versionnée, contrôlée par CRC32.  Ces fonctions retournent 1/0 comme ci-dessus.

// params8 : 8 doubles (paramètres inutilisés à 0).  edge : 0 clamp, 1 wrap.
// `out` doit pouvoir contenir 76 octets.
int cs_filter_descriptor_encode(int kind, int edge, int point_count,
                                const double* params8, uint8_t* out, int capacity,
                                int* size);
int cs_filter_descriptor_decode(const uint8_t* payload, int size, int* kind,
                                int* edge, int* point_count, double* params8);
// Pixels voisins lus de chaque côté par ce filtre (0 = filtre ponctuel).
int cs_filter_descriptor_reach(const uint8_t* payload, int size, int* reach);
// Région du document requise pour calculer [x0,x1)x[y0,y1) après ce filtre
// (halo borné au document, aligné sur la grille pour la mosaïque).  out4 = x0,y0,x1,y1.
int cs_filter_descriptor_expand_rect(const uint8_t* payload, int size, int doc_width,
                                     int doc_height, int x0, int y0, int x1, int y1,
                                     int* out4);
// Applique le filtre décrit à un tampon RGBA8888 en place.  (origin_x, origin_y) :
// position du pixel (0,0) dans le document (bruit et mosaïque en dépendent).
// opacity dans [0,1] mélange le résultat avec l'original.
int cs_filter_descriptor_apply(uint8_t* rgba, int width, int height, int stride,
                               int origin_x, int origin_y, const uint8_t* payload,
                               int size, float opacity, const uint8_t* mask,
                               int mask_stride);

// Calques de filtre dans le modèle natif du document.  Un calque de filtre n'a
// aucun pixel : le hôte ne doit pas lui allouer de TileStore.
int cs_document_add_filter_layer(CreativeDocumentHandle handle, const char* name,
                                 const uint8_t* payload, int size, int* index);
int cs_document_set_filter_payload(CreativeDocumentHandle handle, int index,
                                   const uint8_t* payload, int size);
// 0 = raster, 1 = filtre, -1 = index invalide.
int cs_document_layer_kind(CreativeDocumentHandle handle, int index);
// Copie la charge (76 octets) ; retourne 0 pour un calque raster.
int cs_document_copy_filter_payload(CreativeDocumentHandle handle, int index,
                                    uint8_t* out, int capacity, int* size);

typedef struct CsFilterStackEntry {
    int is_filter;          // 0 = calque raster, 1 = calque de filtre
    int visible;
    float opacity;          // filtre uniquement
    int raster_id;          // raster : identifiant opaque rendu à `compose`
    const uint8_t* payload; // filtre : descripteur
    int payload_size;
} CsFilterStackEntry;

// Compose les rasters `raster_ids` (bas -> haut) sur `backdrop` (RGBA8 droit,
// lignes jointives ; NULL = transparent) pour le rectangle document (x,y,w,h) ;
// écrit w*h*4 octets dans `out`.  Retourne 1 (ok) ou 0 (échec).
typedef int (*CsStackComposeFn)(void* user, const int* raster_ids, int count,
                                const uint8_t* backdrop, int x, int y, int width,
                                int height, uint8_t* out);
// Couverture 0..255 du masque du filtre `entry_index` sur le rectangle : retourne
// 1 si `out` (w*h octets) a été écrit, 0 pour « pas de masque », < 0 en cas d'échec.
typedef int (*CsStackCoverageFn)(void* user, int entry_index, int x, int y, int width,
                                 int height, uint8_t* out);

// Évalue la pile (entrées de bas en haut) pour la région (x,y,width,height) du
// document ; écrit width*height*4 octets dans `out`.  Le résultat d'une région
// est identique à celui du document entier : le hôte peut évaluer tuile par tuile.
int cs_filter_stack_evaluate(const CsFilterStackEntry* entries, int count,
                             int doc_width, int doc_height, int x, int y, int width,
                             int height, CsStackComposeFn compose,
                             CsStackCoverageFn coverage, void* user, uint8_t* out,
                             int out_capacity);

#ifdef __cplusplus
}
#endif
