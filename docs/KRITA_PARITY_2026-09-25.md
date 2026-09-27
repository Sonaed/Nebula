# Nebula → Krita : état de la parité et livraison du 25 septembre 2026

Ce document est volontairement sobre : il dit ce qui est livré et vérifié, ce qui
ne l'est pas, et ce qu'il reste à faire pour qu'on puisse honnêtement parler
d'alternative à Krita. Krita représente plus de vingt ans de développement ; une
session ne le remplace pas, elle peut seulement fermer des écarts précis.

## Livré dans cette session : bibliothèque de filtres natifs

Nebula n'avait aucun noyau de filtre d'image côté CreativeCore (seulement
`cs_apply_rgb_lut` et le pinceau flou/netteté). Ce manque bloquait les filtres
appliqués depuis un menu, les calques de filtre non destructifs et les masques
de filtre — trois piliers de Krita.

| Élément | Fichier |
|---|---|
| Noyaux C++ sans Qt | `CPP_CORE/include/image_filters.h`, `CPP_CORE/src/image_filters.cpp` |
| ABI C `cs_filter_*` (20 symboles, puis 30 avec les calques de filtre) | `CPP_CORE/include/filter_api.h`, `CPP_CORE/src/filter_api.cpp` |
| Adaptateur Python (ctypes, sans NumPy) | `CORE/native_filters.py` |
| Tests C++ (191 vérifications) | `CPP_TEST/test_image_filters.cpp` |
| Tests Python de bout en bout (14) | `CPP_TEST/test_native_filters.py` |
| Intégration CMake (5 lignes) | `CMakeLists.txt` |

Filtres : flou gaussien (exact + approximation par boîtes en O(n) pour les grands
rayons), flou de boîte, flou directionnel, masque flou avec seuil, médiane,
mosaïque, contours de Sobel, estampage, inverser, désaturer (3 modes), teinte /
saturation / valeur, postériser, seuil, bruit gaussien/uniforme déterministe,
« couleur vers alpha », et constructeurs de LUT (niveaux, luminosité/contraste,
courbes monotones de Fritsch–Carlson).

Choix qui comptent pour un usage pro :

- **Masque de couverture 8 bits sur chaque filtre** : c'est la brique pour
  « appliquer dans la sélection » avec bordure douce et pour les masques de filtre.
- **Flous en alpha prémultiplié** : pas de frange sombre autour de la transparence
  (vérifié par test).
- **`EdgeMode::Wrap`** : flou sans couture pour les textures répétables (mode
  wrap-around de Krita) ; vérifié équivariant par translation cyclique.
- **Résultat identique quel que soit le nombre de threads**, avec ou sans OpenMP,
  sous gcc et clang (empreintes comparées).
- L'adaptateur Python vérifie la taille des tampons avant l'appel natif (le C ne
  peut pas le faire) et se charge en mode dégradé (`None`) si le bridge est plus
  ancien que ces symboles, au lieu de faire échouer tout le chargement.

### Mesures (sandbox 2 cœurs, image 2048 × 2048, à refaire sur votre machine)

| Filtre | Temps | Débit |
|---|---:|---:|
| Gaussien σ=2 | 345 ms | 12 MP/s |
| Gaussien σ=20 (boîtes) | 269 ms | 16 MP/s |
| Flou de boîte r=10 | 232 ms | 18 MP/s |
| Masque flou σ=2 | 458 ms | 9 MP/s |
| Flou directionnel L=25 | 1291 ms | 3 MP/s |
| **Médiane r=2** | **2154 ms** | **1,9 MP/s** |
| Teinte/saturation | 126 ms | 33 MP/s |
| Couleur vers alpha | 76 ms | 55 MP/s |
| Inverser (LUT) | 6 ms | 726 MP/s |

La médiane et le flou directionnel sont lents : à optimiser (histogramme glissant,
échantillonnage séparé) avant de les exposer sur de gros documents. Les flous
allouent des plans float pleine image : à appliquer par région/tuile sur les
documents > 4k.

## Ce qui n'est PAS vérifié

- Le build CMake **complet** et `ctest` : l'environnement de cette session n'a pas
  Qt6. Vérifié à la place : la configuration/génération CMake avec un Qt factice
  (tous les fichiers et cibles résolus) et la compilation des trois nouvelles
  unités avec les options exactes générées par CMake.
- Aucune intégration UI : rien n'appelle encore ces filtres depuis un menu ou un
  dock. Les suites Python existantes (PySide6) n'ont pas été relancées.
- Aucune comparaison de rendu avec Krita ; aucune mesure sur votre matériel.

## Écarts restants avec Krita, par priorité

**1. Bloquants pour un usage quotidien** (déjà identifiés dans
`AUDIT_NEBULA_VS_PHOTOSHOP_2026-09-25.md`) : worker de pinceau asynchrone par
tuiles, composition GPU exacte avec tests de parité, solidité PSD/Nebula. Aucun
ajout de fonctionnalité ne compense un trait qui saccade.

**2. Ce que ces filtres débloquent directement**
- Calques de filtre et masques de filtre non destructifs (le noyau + le masque de
  couverture existent maintenant ; reste le modèle de calque et la persistance).
- Dialogue de filtre avec aperçu en direct sur la sélection.
- Masques de transparence / de sélection sur calques (le masque alpha par tuiles
  existe déjà côté document).

**3. Écarts structurels majeurs**
- Couleur : 16 bits entiers / flottants, ICC complet, CMJN/Lab (Nebula : sRGB 8 bits).
- Moteurs de pinceau : Krita en propose une douzaine de familles (pixel, smudge,
  clone, filtre, déformation, poils, sketch, spray, particules...). Nebula a un
  moteur pixel riche + humide + smudge + clone.
- Formats : KRA, ORA en lecture/écriture ; PSD plus complet.
- Animation (calques image par image, oignons), calques vectoriels, scripting
  Python, filtres de type G'MIC, mode wrap-around de peinture (l'`EdgeMode::Wrap`
  des filtres en est la moitié).

## Déjà à niveau ou proche

Stabilisateur de trait à trois modes (`TOOLS/brush_smoothing.py`), assistants
règle/ellipse/perspective, symétrie, groupes et masques de calque, écrêtage,
transformations (affine, perspective, liquify, warp), historique par deltas de
tuiles.

## Livré ensuite : calques de filtre non destructifs (modèle + évaluateur)

Un calque de filtre ne porte aucun pixel : un descripteur (quel filtre, quels
paramètres) appliqué au résultat de tout ce qui est en dessous, à travers son
opacité et son masque. Changer un paramètre ne détruit rien.

| Élément | Fichier |
|---|---|
| Descripteur, halo, évaluateur de pile (sans Qt) | `CPP_CORE/include/filter_layer.h`, `CPP_CORE/src/filter_layer.cpp` |
| Type de calque « filtre » dans le modèle natif | `document_state.h/.cpp` (`kind`, `filterPayload`, `addFilterLayer`, `setFilterPayload`) |
| ABI C v2 (+10 symboles : descripteurs, calques, `cs_filter_stack_evaluate`) | `filter_api.h/.cpp` |
| Adaptateur Python (`encode_filter`, `add_filter_layer`, `evaluate_stack`...) | `CORE/native_filters.py` |
| Tests | `CPP_TEST/test_filter_layer.cpp` (12 106 vérifications), `CPP_TEST/test_native_filters.py` (22 tests) |

**Le problème difficile** : un flou lit des pixels voisins, alors que la composition
de Nebula se fait tuile par tuile. `evaluateStack` calcule, pour une région, la
région élargie (halo) que chaque filtre exige, la fait composer par la source,
puis applique les filtres de bas en haut. Cas particuliers traités : bords du
document (clamp), mode Wrap (un halo qui franchit un bord prend l'axe entier, ce
qui replie exactement comme le document), grille de la mosaïque (alignement),
bruit dépendant de la position absolue (`Surface::originX/Y`), chaînes de filtres
mêlés à des calques raster.

**Comment c'est vérifié** — pas seulement « ça tourne » :
- Évaluer par tuiles (16×13, 7×9, 61×5, 5×47, jusqu'à 1×1 pixel) donne les mêmes
  pixels que le document entier, et les mêmes que l'application directe du filtre
  sans évaluateur (référence indépendante) : 0 niveau d'écart sur les 18 types de
  filtre, les deux modes de bord, avec opacité et masque, et sur une chaîne de 11
  entrées (dont un filtre invisible et un filtre d'opacité 0).
- **Tests de mutation** : j'ai volontairement cassé la logique de halo de quatre
  façons (halo trop court d'un seul pixel, alignement de mosaïque supprimé, Wrap
  sans axe entier, opacité ignorée). Les quatre sont détectées.
- Charge binaire : chaque inversion d'un bit isolé est refusée (CRC32) ; 20 000
  descripteurs générés (7 305 acceptés, 12 695 refusés) sont cohérents et aucun ne
  fait planter l'application.
- ASan + UBSan, build sans OpenMP, clang : mêmes résultats.
- Un vrai bug trouvé par les tests Python et corrigé : les vues mémoire ctypes
  refusaient l'écriture par tranche dans les callbacks de composition.

**Limites connues de ce module** (elles décident de la suite) :
1. **Pas encore branché** sur `ProjectionEngine` (qui compose un tableau de calques
   raster par tuile), ni sur `nebula_serialization` (persistance `.nebula`), ni sur
   le dock Calques : ces fichiers dépendent de Qt, impossible à compiler ici.
   Le contrat d'intégration est prêt : composer chaque segment de rasters avec le
   résultat précédent comme calque Normal du bas, exactement ce que fait
   `StackSource::composeRaster`.
2. Un seul « scope » de composition : les filtres à l'intérieur d'un groupe
   imbriqué, l'écrêtage d'un filtre sur un calque précis et les modes de fusion
   d'un calque de filtre (Krita permet un filtre en mode Multiplier, etc.) ne sont
   pas gérés ; l'opacité s'applique par interpolation des canaux RGBA droits.
3. Les flous allouent des plans float par région : à évaluer par tuile avec halo
   (c'est précisément ce que fait l'évaluateur), pas sur un document 8k entier.
4. Médiane et flou directionnel restent lents (voir mesures ci-dessus).

## Couleur sélective native (correction du test d'architecture)

`DOCUMENTS/adjustments.py::apply_selective_color` calculait les pixels en NumPy
(`flat.copy()`), ce que `test_architecture_boundaries` interdit. Le noyau est
maintenant natif : `cc::filters::selectiveColor`, exposé par `cs_filter_selective_color`
(ABI filtres 3) et `NativeFilters.selective_color`. Il n'y a **plus de repli
Python** : sans bridge récent, la fonction lève `RuntimeError`.

- Vérifié bit à bit contre l'ancienne implémentation NumPy reproduite dans
  `CPP_TEST/test_native_filters.py` (0 octet de différence sur 5 jeux de bandes,
  cas limites inclus) ; 4 sabotages volontaires du noyau sont tous détectés.
- Comportement historique conservé, y compris ses particularités : un « noir »
  négatif n'éclaircit pas (le facteur est borné à 1) ; les seuils blancs/neutres/noirs
  sont des seuils francs (saturation <= 0,25, luminance <= 0,25 ou >= 0,75).
- ASan/UBSan, gcc, clang, 1 et 4 threads : mêmes résultats.

## Réglages : plus aucune logique raster Python (ABI 4)

`DOCUMENTS/adjustments.py` ne recalcule plus un seul pixel côté Python.
- **Noyaux natifs ajoutés** : `hueSaturation`, `vibrance`, `colorBalance`,
  `luminosityBlend` (masque de luminosité), `dropShadow`, `outlineStroke`.
  Teinte/saturation, vibrance et balance des couleurs sont **identiques bit à bit**
  à l'ancien NumPy (même arithmétique float32, même ordre, `nearbyint`) ; le mélange
  par luminosité est à ±1 niveau (`powf` de la libm contre `np.power`, mesuré : plus de
  99,9 % des valeurs strictement égales). Seuil : noyau `threshold` existant (double,
  exact). Exposition : table de 256 entrées puis `cs_apply_rgb_lut`.
- **Plus de repli Python** : un bridge trop ancien lève `RuntimeError` au lieu de
  recalculer lentement en NumPy ; les replis des courbes/niveaux/inversion/postérisation
  sont supprimés pour la même raison.
- **`apply_layer_effects`** était appelée pour *chaque tuile projetée* et recopiait
  l'image même sans effet : elle renvoie maintenant l'image telle quelle quand il n'y
  a rien à faire (gain direct sur la projection).
- **Changement de comportement volontaire** : l'ombre portée passait *par-dessus* le
  calque (l'ombre recouvrait le calque là où elle chevauchait) ; elle passe désormais
  *sous* lui. Alpha de l'ombre identique à l'ancien flou (±1). Le contour est
  identique bit à bit. L'ombre est calculée tuile par tuile dans le chemin de
  projection, donc coupée aux bords de tuile : limite historique, non traitée ici.
- `-ffp-contract=off` sur `image_filters.cpp` : pas de FMA, donc mêmes arrondis sur
  toute machine.
- Tests : `CPP_TEST/test_native_filters.py` (`AdjustmentKernelParityTests`,
  `LayerEffectKernelTests`, références NumPy recopiées telles quelles),
  `CPP_TEST/test_adjustments_native.py` (câblage avec un faux `QImage`, sans Qt),
  `CPP_TEST/test_image_filters.cpp` (noyaux, cas limites, ASan/UBSan propres).

### Sélection et réglages écrêtés : NumPy supprimé aussi
- `selection.py` : flou, dilatation, érosion (`feather/expand/contract`) et
  « plage de couleurs » passent par `selectionFeather`, `selectionMorph`,
  `selectColorRange`. Flou, dilatation et érosion sont **identiques bit à bit** à
  l'ancien code (y compris l'érosion qui ronge aussi les bords de l'image) ; la
  dilatation/érosion est en O(n) quel que soit le rayon (l'ancienne version
  construisait (2r+1)² vues).
- **Bug corrigé** dans la plage de couleurs : l'ancien code élevait au carré des
  `int16` (débordement dès qu'un canal diffère de plus de 181 : 255² ne tient pas
  sur 16 bits), donc les couleurs éloignées donnaient une distance fausse, voire NaN.
  Le noyau calcule la vraie distance euclidienne.
- `blend_modes.apply_clipped_adjustment` (calques de réglage écrêtés) : noyau
  `blendByAlpha`, identique bit à bit à l'ancien mélange.
- Toujours sans repli : bridge trop ancien = `RuntimeError`.
- Tests : `SelectionKernelTests`, `CPP_TEST/test_selection_native.py`, noyaux C++
  (ASan/UBSan propres).

## Ce que « tout faire » n'a pas pu inclure

Ces chantiers exigent Qt/OpenGL, absents de l'environnement de cette session, et
je n'écris pas de code de ce type sans pouvoir le compiler et le tester :
- **Worker de pinceau asynchrone** (Palier A de l'audit) : `brush_engine` repose
  sur `QImage`.
- **Composition GPU exacte** (Palier B) : OpenGL, tests de parité sur GPU réel.
- **Persistance des calques de filtre dans `.nebula`** et intégration à l'UI.
- Couleur 16 bits/flottante, ICC, KRA/ORA, animation, calques vectoriels : chacun
  est un chantier de plusieurs semaines, pas un ajout.

## Prochaine étape recommandée

Sur votre machine (avec Qt) : (1) lancer `ctest` pour valider le build complet ;
(2) brancher `evaluateStack` dans la projection en fournissant une
`StackSource` qui appelle le compositeur existant ; (3) écrire `filterPayload`
(76 octets par calque) dans `nebula_serialization` avec migration de version ;
(4) ajouter le calque de filtre au dock Calques (création, paramètres, masque).
L'interface qu'elles consomment est testée ; leur taille réelle reste à estimer, je n'ai pas pu lire ni compiler les fichiers concernés.
