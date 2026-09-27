#pragma once

/*
 * Calques de filtre non destructifs (sans Qt).
 *
 * Un calque de filtre ne stocke aucun pixel : il porte un FilterDescriptor
 * (quel filtre, quels paramètres) et s'applique au résultat de tout ce qui se
 * trouve en dessous de lui, à travers sa propre opacité et son masque de
 * couverture.  Le document reste éditable : changer un paramètre ne détruit rien.
 *
 * Difficulté centrale : un flou lit des pixels voisins, alors que la composition
 * se fait tuile par tuile.  evaluateStack() calcule, pour une région demandée,
 * la région élargie (halo) dont chaque filtre a besoin, la fait composer par la
 * source, puis applique les filtres de bas en haut.  Le résultat d'une région est
 * identique, pixel pour pixel (±1 pour l'approximation gaussienne par boîtes), à
 * celui du document entier — propriété vérifiée par les tests.
 *
 * Périmètre v1 : un seul « scope » de composition (le document, ou l'intérieur
 * d'un groupe évalué à part).  Les modes de fusion et l'écrêtage des calques
 * raster sont délégués à la source (StackSource::composeRaster).
 */

#include "image_filters.h"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace cc {
namespace filters {

// Identifiants stables : ils sont écrits dans les fichiers, ne jamais renuméroter.
enum class FilterKind : uint8_t
{
    GaussianBlur = 1,       // p0 sigmaX, p1 sigmaY
    BoxBlur = 2,            // p0 rayonX, p1 rayonY (entiers)
    MotionBlur = 3,         // p0 angle°, p1 longueur px
    UnsharpMask = 4,        // p0 sigma, p1 amount, p2 seuil 0..255
    Median = 5,             // p0 rayon 0..8
    Pixelate = 6,           // p0 largeur bloc, p1 hauteur bloc (>= 1)
    EdgeDetect = 7,         // p0 force
    Emboss = 8,             // p0 angle°, p1 profondeur
    Invert = 9,             // aucun paramètre
    Desaturate = 10,        // p0 mode 0..2
    HsvAdjust = 11,         // p0 teinte°, p1 saturation, p2 valeur (-1..1)
    Posterize = 12,         // p0 niveaux 2..256
    Threshold = 13,         // p0 niveau 0..255
    Noise = 14,             // p0 amount 0..1, p1 graine (< 2^53), p2 gauss, p3 mono, p4 alpha
    ColorToAlpha = 15,      // p0..p2 RGB 0..255, p3 tolérance 0..1
    Levels = 16,            // p0 noirIn, p1 blancIn, p2 gamma, p3 noirOut, p4 blancOut
    BrightnessContrast = 17,// p0 luminosité, p1 contraste (-1..1)
    Curve = 18              // pointCount 2..4 ; p = x0,y0,x1,y1,x2,y2,x3,y3
};

constexpr int kFilterParamCount = 8;
constexpr size_t kDescriptorBytes = 76; // 'CSFD' v1 : en-tête 8 + 8 × f64 + CRC32

struct FilterDescriptor
{
    FilterKind kind = FilterKind::Invert;
    EdgeMode edge = EdgeMode::Clamp; // ignoré par les filtres sans notion de bord
    int pointCount = 0;              // Curve uniquement
    double params[kFilterParamCount] = {0, 0, 0, 0, 0, 0, 0, 0};
};

// Vérifie les plages de chaque paramètre (aucune valeur non finie).
bool validateDescriptor(const FilterDescriptor& d);

// Format binaire versionné, little-endian explicite, contrôlé par CRC32.
bool encodeDescriptor(const FilterDescriptor& d, std::vector<uint8_t>& out);
// Refuse toute charge de taille, magic, version, CRC ou paramètres invalides.
bool decodeDescriptor(const uint8_t* data, size_t size, FilterDescriptor& out);
uint32_t descriptorCrc32(const uint8_t* data, size_t size);

// Applique le filtre à la surface (sous masque).  Valide le descripteur d'abord.
bool applyDescriptor(const Surface& s, const FilterDescriptor& d, const Mask& mask = {});

// Pixels voisins lus de chaque côté (0 pour les filtres ponctuels).
int descriptorReach(const FilterDescriptor& d);
// Vrai si le filtre honore EdgeMode (flous, netteté) ; les autres répètent le bord.
bool descriptorUsesEdgeMode(FilterKind kind);

struct Rect
{
    int x0 = 0, y0 = 0, x1 = 0, y1 = 0; // demi-ouvert [x0,x1) × [y0,y1)
    int width() const { return x1 - x0; }
    int height() const { return y1 - y0; }
    bool empty() const { return x1 <= x0 || y1 <= y0; }
    bool operator==(const Rect& o) const
    {
        return x0 == o.x0 && y0 == o.y0 && x1 == o.x1 && y1 == o.y1;
    }
};

// Région du document nécessaire pour calculer `region` après ce filtre : halo,
// borné au document.  En mode Wrap, un halo qui franchit un bord prend l'axe
// entier (la sous-image dont les bords sont ceux du document se replie alors
// exactement comme le document).  La mosaïque s'aligne sur sa grille.
Rect expandRectForFilter(const FilterDescriptor& d, const Rect& region, int docWidth,
                         int docHeight);

// ------------------------------------------------------------ évaluation ----

struct StackEntry
{
    bool isFilter = false;
    bool visible = true;
    float opacity = 1.0f;     // opacité du calque de filtre (ignorée pour un raster)
    int rasterId = 0;         // identifiant opaque transmis à la source
    FilterDescriptor filter;  // si isFilter
};

class StackSource
{
public:
    virtual ~StackSource() = default;
    // Compose les calques raster `ids` (de bas en haut) sur `backdrop` (RGBA8
    // droit, lignes jointives width*4 ; nullptr = fond transparent) pour `rect`,
    // en coordonnées document.  Écrit rect.width()*rect.height()*4 octets dans out.
    virtual bool composeRaster(const int* ids, int count, const uint8_t* backdrop,
                               const Rect& rect, uint8_t* out) = 0;
    // Couverture 0..255 du masque du calque de filtre `entryIndex` sur `rect`.
    // Retourne false pour « pas de masque » (couverture pleine).
    virtual bool filterCoverage(int entryIndex, const Rect& rect, uint8_t* out) = 0;
    // Mis à true par la source si une de ses lectures a échoué.
    bool failed = false;
};

// Évalue la pile pour `region` (dans le document) ; out = RGBA8 droit, lignes
// jointives.  Retourne false si un descripteur est invalide, la région hors du
// document, ou si la source signale une erreur.
bool evaluateStack(const std::vector<StackEntry>& entries, StackSource& source,
                   int docWidth, int docHeight, const Rect& region,
                   std::vector<uint8_t>& out);

} // namespace filters
} // namespace cc
