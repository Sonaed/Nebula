#pragma once
/*
 * CreativeCore — composition native d'une pile complète (une tuile).
 *
 * Évalue en un seul appel ce que Nebula faisait en Python tuile par tuile :
 * dossiers isolés, jeux d'écrêtage à la Photoshop (les calques écrêtés agissent
 * « par-dessus » la base seule, dont l'alpha, l'opacité et le mode s'appliquent
 * ensuite au jeu entier), calques de réglage (tables RGB, courbe de transfert
 * de dégradé, LUT 3D) avec mode de fusion, opacité et masque, masques de calque.
 * Les modes de fusion et leurs paramètres sont ceux de
 * cs_composite_layers_advanced (projection_compositor).
 */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    CS_STACK_RASTER = 0,       /* calque de pixels (pixels NULL = transparent) */
    CS_STACK_GROUP_BEGIN = 1,  /* ouvre un dossier isolé */
    CS_STACK_GROUP_END = 2,    /* ferme le dossier : opacité/mode/visibilité du dossier */
    CS_STACK_ADJUST = 3        /* calque de réglage */
};

enum {
    CS_STACK_PIXELS_ARGB32 = 0,   /* QImage::Format_ARGB32 (octets B, G, R, A) */
    CS_STACK_PIXELS_RGBA8888 = 1  /* octets R, G, B, A */
};

enum {
    CS_STACK_ADJUST_RGB_TABLES = 0, /* table : 768 octets (R[256], G[256], B[256]) */
    CS_STACK_ADJUST_GRADIENT = 1,   /* table : 1024 octets (256 couleurs RGBA) */
    CS_STACK_ADJUST_LUT3D = 2       /* table : size³×3 float, rouge le plus rapide */
};

typedef struct CsStackOp {
    int kind;
    const uint8_t* pixels;   /* RASTER : même taille que la cible */
    int stride;
    int format;              /* CS_STACK_PIXELS_* */
    const uint8_t* mask;     /* optionnel : couverture dans l'octet alpha (index 3) */
    int mask_stride;
    float opacity;
    int mode;                /* 0..15, comme cs_composite_layers_advanced */
    int visible;
    int clipping;
    float parameters[11];
    int adjust_kind;         /* CS_STACK_ADJUST_* */
    const void* table;
    int table_size;          /* LUT3D : côté du cube */
} CsStackOp;

/* Compose `ops` dans `target` (ARGB32 non prémultiplié, octets B, G, R, A).
 * Retourne 1, ou 0 si un argument est invalide (cible non modifiée). */
int cs_compose_stack(uint8_t* target, int width, int height, int target_stride,
                     const CsStackOp* ops, int op_count);

typedef struct CsStackJob {
    uint8_t* target;         /* ARGB32, width×height */
    int width;
    int height;
    int target_stride;
    const CsStackOp* ops;
    int op_count;
    int result;              /* rempli : 1 réussi, 0 refusé */
} CsStackJob;

/* Compose plusieurs tuiles en parallèle (un thread par tuile). Retourne le
 * nombre de tâches réussies. */
int cs_compose_stack_batch(CsStackJob* jobs, int job_count);

#ifdef __cplusplus
}
#endif
