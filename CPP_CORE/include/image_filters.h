#pragma once

/*
 * CreativeCore — bibliothèque de filtres raster.
 *
 * Toutes les opérations travaillent en place sur un tampon RGBA8888 en alpha
 * droit (non prémultiplié), l'ordre d'octets étant R, G, B, A — le même
 * contrat que cs_apply_rgb_lut.  Cette unité ne dépend ni de Qt ni de Python :
 * elle est testable seule et réutilisable par le bridge C, les tests et les
 * futurs calques de filtre non destructifs.
 *
 * Conventions communes :
 *  - `Mask` est une couverture 8 bits de même taille que la surface (0 = pixel
 *    intact, 255 = filtre appliqué en plein, valeurs intermédiaires = mélange).
 *    C'est ce qui permet d'appliquer n'importe quel filtre « dans la
 *    sélection » avec une bordure douce, comme Krita.
 *  - Les flous et convolutions opèrent en alpha prémultiplié pour éviter les
 *    franges sombres autour des zones transparentes.
 *  - `EdgeMode::Wrap` traite l'image comme un motif répétable (mode wrap-around
 *    de Krita) : un flou « wrap » d'une texture reste raccordable.
 *  - Toutes les fonctions retournent false sans rien modifier si un argument est
 *    invalide.  Le résultat est déterministe et indépendant du nombre de threads.
 */

#include <cstddef>
#include <cstdint>

namespace cc {
namespace filters {

enum class EdgeMode : int
{
    Clamp = 0, // répète le pixel de bord
    Wrap = 1   // repli périodique (texture sans couture)
};

struct Surface
{
    uint8_t* pixels = nullptr;
    int width = 0;
    int height = 0;
    int stride = 0; // octets par ligne, >= width * 4
    // Coordonnées document du pixel (0,0).  Sert aux filtres dont le résultat
    // dépend de la position absolue (bruit, grille de la mosaïque) : évaluer une
    // sous-région donne alors exactement les mêmes pixels que l'image entière.
    int originX = 0;
    int originY = 0;

    bool valid() const
    {
        return pixels && width > 0 && height > 0 && originX >= 0 && originY >= 0 &&
               static_cast<long long>(stride) >= static_cast<long long>(width) * 4;
    }
};

struct Mask
{
    const uint8_t* data = nullptr; // nullptr : filtre appliqué partout
    int stride = 0;                // octets par ligne, >= width
};

// ---------------------------------------------------------------- flous ----

// Flou gaussien séparable.  sigma <= 0 sur un axe = pas de flou sur cet axe.
// Exact pour les petits sigma ; approximation par trois passes de boîte (erreur
// < 1 %) au-delà de kBoxBlurSigmaThreshold pour rester en O(n) quel que soit le
// rayon.
constexpr double kBoxBlurSigmaThreshold = 6.0;
bool gaussianBlur(const Surface& s, double sigmaX, double sigmaY,
                  EdgeMode edge = EdgeMode::Clamp, const Mask& mask = {});

// Nombre de pixels voisins lus de chaque côté par gaussianBlur / unsharpMask
// pour ce sigma (noyau exact, ou somme des rayons de boîte).  Une sous-région
// entourée d'un halo au moins égal à cette valeur donne le même résultat que
// l'image entière.
int gaussianReach(double sigma);

// Flou de boîte (moyenne glissante), rayons en pixels (>= 0).
bool boxBlur(const Surface& s, int radiusX, int radiusY,
             EdgeMode edge = EdgeMode::Clamp, const Mask& mask = {});

// Flou directionnel : moyenne le long d'un segment de `length` pixels centré sur
// chaque pixel, orienté de `angleDegrees` (0 = horizontal, sens trigonométrique
// écran, y vers le bas).
bool motionBlur(const Surface& s, double angleDegrees, double length,
                EdgeMode edge = EdgeMode::Clamp, const Mask& mask = {});

// Masque flou (unsharp mask).  `amount` typique 0.5–2, `threshold` en niveaux
// 0–255 : les différences plus faibles ne sont pas accentuées (préserve grain
// et aplats).  L'alpha n'est jamais modifié.
bool unsharpMask(const Surface& s, double sigma, double amount, int threshold = 0,
                 EdgeMode edge = EdgeMode::Clamp, const Mask& mask = {});

// Médiane carrée de rayon 1..8 sur chaque canal (anti-bruit, préserve les bords).
bool medianFilter(const Surface& s, int radius, const Mask& mask = {});

// Mosaïque : moyenne de blocs blockWidth × blockHeight ancrés à l'origine du
// document (voir Surface::originX).  Les blocs coupés par le bord de la surface
// sont moyennés sur leur partie visible : alignez la sous-région sur la grille.
bool pixelate(const Surface& s, int blockWidth, int blockHeight,
              const Mask& mask = {});

// ------------------------------------------------- détection / relief ------

// Détection de contours de Sobel sur la luminance.  Sortie en niveaux de gris
// (contour clair sur fond noir), alpha conservé.  `strength` multiplie le
// gradient (1 = brut).
bool edgeDetect(const Surface& s, double strength = 1.0, const Mask& mask = {});

// Estampage : dérivée directionnelle de la luminance, gris moyen sur les aplats.
bool emboss(const Surface& s, double angleDegrees, double depth,
            const Mask& mask = {});

// ----------------------------------------------------------- couleur -------

bool invert(const Surface& s, const Mask& mask = {});

enum class DesaturateMode : int
{
    Luminance = 0, // Rec. 709
    Average = 1,
    Lightness = 2 // (max + min) / 2
};
bool desaturate(const Surface& s, DesaturateMode mode = DesaturateMode::Luminance,
                const Mask& mask = {});

// Décalage de teinte (degrés, cyclique), delta de saturation et de valeur dans
// [-1, 1] (relatif : -1 supprime, +1 double la valeur/sature au maximum).
bool hsvAdjust(const Surface& s, double hueShiftDegrees, double saturationDelta,
               double valueDelta, const Mask& mask = {});

// Couleur sélective (à la Photoshop) : neuf bandes — six teintes puis blancs,
// neutres, noirs — reçoivent chacune un décalage cyan / magenta / jaune / noir en
// pourcentage.  Le poids d'une bande de teinte décroît linéairement sur 45° de
// part et d'autre de son centre et est proportionnel à la saturation ; les
// bandes de tons (blancs, neutres, noirs) se basent sur la luminance / saturation
// du pixel d'origine.  Les bandes sont appliquées dans l'ordre de l'énumération.
// Arithmétique float32 dans le même ordre que l'ancienne version NumPy, pour que
// les documents existants ne changent pas de rendu.
enum SelectiveBand : int
{
    kBandReds = 0,
    kBandYellows,
    kBandGreens,
    kBandCyans,
    kBandBlues,
    kBandMagentas,
    kBandWhites,
    kBandNeutrals,
    kBandBlacks,
    kSelectiveBandCount
};
struct SelectiveColorParams
{
    // Décalages en pourcentage (typiquement -100..100), {C, M, Y, K}.
    float band[kSelectiveBandCount][4] = {};
    bool enabled[kSelectiveBandCount] = {};
};
bool selectiveColor(const Surface& s, const SelectiveColorParams& params,
                    const Mask& mask = {});

// ---------------------------------------------- calques de réglage ---------
//
// Noyaux des calques de réglage de Nebula.  Ils reproduisent à l'identique les
// anciennes implémentations NumPy de DOCUMENTS/adjustments.py (arithmétique
// float32 dans le même ordre, arrondi au plus proche pair) : ouvrir un document
// existant ne change donc aucun pixel.  Ils sont distincts de hsvAdjust /
// posterize ci-dessus, dont les définitions (interpolation « pushToward », etc.)
// sont différentes.

// Teinte en degrés (cyclique), saturation et clarté en pourcentage (+100 double
// la saturation ; la clarté est additive sur la valeur HSV).
bool hueSaturation(const Surface& s, double hueDegrees, double saturationPercent,
                   double lightnessPercent, const Mask& mask = {});

// Vibrance : sature davantage les couleurs peu saturées.  Pourcentages.
bool vibrance(const Surface& s, double vibrancePercent, double saturationPercent,
              const Mask& mask = {});

// Balance des couleurs : décalages RGB en pourcentage pour les ombres, les tons
// moyens et les hautes lumières, pondérés par la luminance du pixel.
struct ColorBalanceParams
{
    float shadows[3] = {0, 0, 0};
    float midtones[3] = {0, 0, 0};
    float highlights[3] = {0, 0, 0};
};
bool colorBalance(const Surface& s, const ColorBalanceParams& params,
                  const Mask& mask = {});

// Mélange d'un réglage avec l'original selon la luminance de l'ORIGINAL :
// dst = source * (1 - m) + dst * m, alpha repris de la source.  `dst` contient le
// résultat du réglage (modifié en place), `source` l'image avant réglage (même
// géométrie, stride `sourceStride`).
enum class LuminosityMode : int
{
    Flat = 0, // masque plein (mode inconnu inclus)
    Lights = 1,
    Shadows = 2,
    Midtones = 3
};
bool luminosityBlend(const Surface& dst, const uint8_t* source, int sourceStride,
                     LuminosityMode mode, double amount, double feather, bool invert,
                     const Mask& mask = {});

// Effets de calque (PSD) : ombre portée / lueur externe et contour.
// `size` : 1..32.  L'ombre est le canal alpha décalé de (offsetX, offsetY), flouté
// par deux passes de moyenne (rayon `size`, bords répliqués), teinté par `color`
// (RGBA 8 bits, alpha = opacité) puis placé SOUS le calque.
struct LayerEffectParams
{
    int offsetX = 4;
    int offsetY = 4;
    int size = 6;
    uint8_t color[4] = {0, 0, 0, 160};
};
bool dropShadow(const Surface& s, const LayerEffectParams& params);
// Contour extérieur : dilatation carrée de l'alpha sur `size` pixels ; les pixels
// ajoutés prennent la couleur, leur alpha = couverture * color[3] / 255.
bool outlineStroke(const Surface& s, const LayerEffectParams& params);

// ------------------------------------------- masques de sélection / écrêtage --

// dst.rgb = dst.rgb * (1 - m) + changed.rgb * m, m = alpha(maskSource) / 255 ;
// l'alpha de dst est conservé.  Sert aux réglages « écrêtés » (clipping).
bool blendByAlpha(const Surface& dst, const uint8_t* changed, int changedStride,
                  const uint8_t* maskSource, int maskStride);

// Les opérations suivantes lisent l'octet alpha (indice 3) d'un masque de
// sélection 32 bits et écrivent la nouvelle valeur dans les quatre octets.
// Flou par deux moyennes de boîte (rayon >= 1, bords répliqués), arrondi au plus près pair.
bool selectionFeather(const Surface& mask, int radius);
// Dilatation (grow) ou érosion carrée de rayon >= 1.  Hors image = 0 : l'érosion
// ronge donc aussi les bords de l'image.
bool selectionMorph(const Surface& mask, int radius, bool grow);
// Sélection douce autour d'une couleur RGB : alpha = 255 - distance * 255 /
// max(1, tolerance * sqrt(3)), bornée à 0..255 (troncature).  `source` : RGBA 8 bits
// de même taille que `mask`.
bool selectColorRange(const Surface& mask, const uint8_t* source, int sourceStride,
                      int red, int green, int blue, int tolerance);

bool posterize(const Surface& s, int levels, const Mask& mask = {});
bool threshold(const Surface& s, int level, const Mask& mask = {});

// Bruit additif déterministe (même graine = même résultat, quel que soit le
// découpage en threads).  amount 0–1 : écart-type du bruit relatif à 255, pour
// la loi gaussienne comme pour la loi uniforme.
struct NoiseOptions
{
    double amount = 0.1;
    uint64_t seed = 1;
    bool gaussian = true;    // sinon uniforme
    bool monochrome = false; // même bruit sur R, G et B
    bool affectAlpha = false;
};
bool addNoise(const Surface& s, const NoiseOptions& options, const Mask& mask = {});

// « Couleur vers alpha » : rend transparente la couleur choisie en calculant
// l'alpha minimal tel que composer le résultat sur cette couleur redonne le
// pixel d'origine.  `tolerance` 0–1 : les pixels dont l'alpha calculé est
// inférieur deviennent totalement transparents (transition linéaire au-dessus).
bool colorToAlpha(const Surface& s, uint8_t red, uint8_t green, uint8_t blue,
                  double tolerance = 0.0, const Mask& mask = {});

// ------------------------------------------------------------- LUT ---------

// Table 8 bits → 8 bits.
void buildInvertLut(uint8_t lut[256]);
void buildLevelsLut(int inBlack, int inWhite, double gamma, int outBlack,
                    int outWhite, uint8_t lut[256]);
// brightness et contrast dans [-1, 1].
void buildBrightnessContrastLut(double brightness, double contrast,
                                uint8_t lut[256]);
// Courbe monotone (Fritsch–Carlson) passant par les points de contrôle
// (x, y) ∈ [0,1]², x strictement croissants.  Retourne false si < 2 points ou
// abscisses invalides ; `lut` reste alors l'identité.
bool buildCurveLut(const double* xs, const double* ys, int count,
                   uint8_t lut[256]);

// Applique des LUT indépendantes R/G/B (alpha inchangé), sous masque.
bool applyLut(const Surface& s, const uint8_t* red, const uint8_t* green,
              const uint8_t* blue, const Mask& mask = {});


// ------------------------------------------- réglages Photoshop (ABI 5) ----

// Courbe de transfert de dégradé : la luminance du pixel
// (0.30 R + 0.59 G + 0.11 B, pondération de Photoshop) indexe une table de
// 256 couleurs RGBA ; seule la couleur est remplacée (alpha d'origine
// conservé), interpolation linéaire entre deux entrées.
bool gradientMap(const Surface& s, const uint8_t* table256Rgba, const Mask& mask = {});

// Table de correspondance 3D (.cube) : `table` contient size³ triplets RGB
// float 0..1, rouge variant le plus vite.  Interpolation trilinéaire ; alpha
// conservé.  size ∈ [2, 256].
bool lut3d(const Surface& s, const float* table, int size, const Mask& mask = {});

// Remplace l'alpha de chaque pixel par `alpha` (RGB inchangé).
bool setAlpha(const Surface& s, uint8_t alpha);

// Copie l'alpha de `source` (RGBA8888 de même taille) dans `s`.
bool copyAlpha(const Surface& s, const uint8_t* source, int sourceStride);

// PackBits (compression « RLE » des PSD).  Retourne le nombre d'octets écrits
// (au plus `capacity`) ou -1 si les arguments sont invalides.
long unpackBits(const uint8_t* input, size_t length, uint8_t* output, size_t capacity);

} // namespace filters
} // namespace cc
