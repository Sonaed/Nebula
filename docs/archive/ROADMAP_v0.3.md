# CreativeSystem v0.3 — audit et feuille de route

## État vérifié au 16 septembre 2026

### Stable et à préserver

- Canvas `QOpenGLWidget`, textures par calque et fallback `QPainter`.
- Brush Engine C++17 et bridge C/ctypes (`CreativeCoreBridge`).
- Brush, gomme, pipette composite, Smudge C++ Wet et pression tablette.
- État canonique `BrushSettingsState`, partagé par l'UI, les presets, le C++ et
  le fallback Python.
- Calques raster de base, historique, sauvegarde CSD et presets JSON.

### Présent mais partiel

- Transform/Crop, sélection, modes de fusion, assistants et navigation sont
  implémentés ; vérifier encore leurs interactions et documents réels.
- Brush Engine et presets version 2 couvrent les dynamiques ; la preview et
  l’organisation de tous les paramètres restent partielles.
- Smudge utilise le backend Wet C++, avec une partie de l’orchestration dans
  `Canvas`.
- GPU : dirty rect transmis à la texture existante ; le rendu incrémental doit
  encore être validé sur des pilotes OpenGL variés.
- UI Qt : shell, registre d’actions, raccourcis, workspaces et toolbar
  personnalisable livrés ; campagne manuelle multi-plateforme à poursuivre.

### Absent au début du chantier v0.3

- Fill, Gradient, Blur, Sharpen, formes et courbes.
- Modèle de sélection et outils Rectangle/Ellipse/Lasso/Magic Wand.
- Crop, Clone Stamp, texte non destructif, références.
- Symétries, grille de perspective et assistants.
- Modes de fusion, groupes, masques, clipping et locks avancés.
- Preferences extensibles, registre central des actions/raccourcis et workspaces.

## Découpage d'implémentation

1. **Socle des outils raster** — registre ToolManager, Fill, Gradient, Line,
   Rectangle et Ellipse ; protocole commun d'événements et overlays.
2. **Sélection** — masque 8 bits attaché au document, opérateurs replace/add/
   subtract/intersect, overlays et quatre outils. Toutes les écritures raster
   passent ensuite par ce masque.
3. **Transform et Crop** — transaction de preview/commit/cancel, matrice
   `QTransform`, layer ou sélection, handles et flips. Prévoir une interface de
   transform extensible pour perspective/warp.
4. **Composition des calques** — enum versionnée de blend modes, persistance CSD,
   shader GPU par mode, fallback CPU testé ; duplicate/merge/flatten/locks.
5. **Brush Engine avancé** — enrichir `BrushSettings`, entrée tilt/rotation/
   vélocité, courbes, spacing adaptatif, tips image, texture et smoothing. Étendre
   le bridge C existant sans modifier son ABI de manière incompatible.
6. **Brush UX et presets** — dock repliable unique, preview de trait réelle,
   schéma de preset versionné complet, miniatures, catégories, recherche,
   favoris, import/export.
7. **Navigation et aides** — Hand/Zoom/Rotate, fit/100 %, flip de vue strictement
   visuel, canvas-only, symétries et primitives d'assistants.
8. **Outils métier** — Clone Stamp via le brush actif, références hors pixels,
   texte éditable, Blur/Sharpen, Bezier.
9. **Shell applicatif** — registre d'actions, Preferences, shortcuts avec conflits,
   docks libres, menu Window/Dockers, workspaces et toolbar personnalisable.
10. **Durcissement** — dirty rectangles, mesures de copies CPU/GPU, compatibilité
    CSD/presets, tests de migration, documentation et campagne de stabilité.

Chaque jalon conserve un chemin CPU correct, teste les imports, compile le C++,
exécute CTest et les tests Python concernés, puis contrôle les symboles exportés
du bridge. `main.py` reste réservé au test manuel.

## Incrément 0.3.0-dev.1

- Ajout de `TOOLS/fill_tool.py`, flood fill contigu avec tolérance RGBA.
- Branchement au `ToolManager`, au Canvas, à l'historique et au cache GPU.
- Accès par `F` et par le rail d'outils.
- Tests des frontières, de la tolérance et des clics hors image.

## Dépendances

Aucune dépendance nouvelle pour le premier incrément : Qt/PySide6 fournit les
types d'image nécessaires et l'algorithme de remplissage est interne.

## Incrément 0.3.0-dev.2

- Ajout du Gradient linéaire interactif, de la couleur principale vers la
  transparence.
- Preview transactionnelle pendant le glisser, commit à la relâche et historique
  en une seule opération utilisateur.
- Accès par `G` et par le rail d'outils.
- Ajout de Line, Rectangle et Ellipse avec preview transactionnelle et rendu par
  le Brush Engine C++ actif ; fallback Python conservé.

## Incrément 0.3.0-dev.3

- Modèle de sélection persistant attaché au document avec Replace, Add,
  Subtract, Intersect, Select All, Deselect et Invert.
- Rectangle Selection, Ellipse Selection, Lasso et Magic Wand contigu.
- Overlay interactif et cache des limites du masque pour éviter un scan complet
  à chaque frame.
- Format CSD schema 3 : PNG encodés en mémoire, sélection, UUID de calque, blend
  mode, lock, lock alpha, clipping, métadonnées de version/date et chargement
  rétrocompatible des manifests 0.1.

## Incrément 0.3.0-dev.4 — Design System

- Thème CreativeSystem centralisé : palette, métriques et QSS global.
- `NumericSlider`, `CollapsibleSection` et title bar de dock réutilisables.
- Brush Dock compact organisé par catégories repliables, avec 44 paramètres
  connectés directement à l'état canonique et au backend C++.
- Title bars cohérentes sur Brush, Layers, Presets et Color.
- Suppression du refit automatique à chaque resize, source principale des sauts
  visuels et du flickering lors du passage en grand écran.
- Canvas en mode OpenGL `PartialUpdate` et invalidation locale du seul ancien/
  nouveau rectangle du curseur lorsque l'utilisateur ne peint pas.
- Véritable roue HSV interactive avec champ saturation/valeur, rendu mis en cache
  et aucune animation ou minuterie permanente.
- Correction du flickering alpha en plein écran : blending séparé RGB/alpha
  (`SRC_ALPHA` pour la couleur, `ONE` pour l'alpha) et fenêtre principale
  explicitement opaque pour le compositeur du bureau.

## Incrément 0.3.0-dev.5 — Preferences et workspaces

- Fenêtre Preferences à navigation latérale avec les 13 catégories prévues.
- Page Shortcuts recherchable, édition via `QKeySequenceEdit`, contrôle simple des
  conflits et restauration des valeurs par défaut.
- Réglages persistants via `QSettings` et premiers contrôles Interface/Tablet.
- Menu Window/Dockers fondé sur les `toggleViewAction()` natifs des docks.
- Sauvegarde/restauration versionnée de geometry/state Qt et workspaces nommés,
  avec regroupement des repaint pendant leur chargement.

## Incrément 0.3.0-dev.6 — Actions et Layers

- Raccourcis par défaut et personnalisés regroupés dans `ActionRegistry` ; retrait
  des `QShortcut` applicatifs dupliqués.
- Menu Select et actions Fill/Gradient/Line/Rectangle/Ellipse enregistrés.
- Liste Layers rendue par un delegate CreativeSystem compact avec thumbnail,
  visibilité, sélection, lock, alpha lock et indicateur de clipping.

## Incrément 0.3.0-dev.7 — Brush Presets

- Format de preset v2 rétrocompatible avec catégorie et favori.
- Grille compacte avec thumbnails générés depuis couleur, taille et opacité.
- Recherche instantanée et filtre de catégories.
- Favoris, duplication, suppression, import et export JSON.

## Incrément 0.3.0-dev.8 — Transform affine

- Moteur `TransformTool` indépendant fondé sur `QTransform`.
- Translation, rotation, scale X/Y, scale uniforme par facteurs égaux et flips.
- Cible automatique : sélection active ou calque entier.
- Le masque de sélection suit la même matrice que ses pixels.
- Overlay interactif recalé sur les limites de la sélection et commandes Layer
  pour rotation 90° et miroirs horizontal/vertical.

## Incrément 0.3.0-dev.9 — Crop et rotation interactive

- Crop interactif avec rectangle, validation, annulation `Esc` et commit
  document-wide des images de calques.
- Poignée de rotation au-dessus du cadre Transform.
- Historique conservé pour crop/rotation et sélection recréée à la nouvelle
  dimension du document.

## Incrément 0.3.0-dev.10 — Composition des calques

- Registre des 16 modes de fusion demandés, basé sur les modes Qt disponibles.
- Composition CPU correcte pour export, pipette et fallback Canvas.
- GPU normal conservé sans copie supplémentaire ; documents avec mode non-Normal
  basculent automatiquement vers le fallback CPU afin de garantir la fidélité.
- `Esc` annule aussi proprement les transactions Transform/Crop sans ajouter de
  point fantôme dans l'historique.
- Merge Down, Merge Visible, Flatten, Lock Layer et Lock Alpha sont disponibles
  dans `LayerManager` et dans le menu Layer.
- Le mode de fusion, le lock et l'alpha lock sont maintenant modifiables
  directement dans le dock Layers et resynchronisés avec le calque actif.
- Correction préventive des halos noirs autour des bords alpha du brush GPU :
  textures prémultipliées et blending RGB/alpha adapté.

## Incrément 0.3.0-dev.11 — Compatibilité OpenGL et flickering

- Contexte OpenGL desktop GLSL 3.x demandé avant la création de `QApplication`
  pour éviter le chemin GLSL-ES 1.00 de `QOpenGLTextureBlitter`.
- Repli CPU explicite lorsque le pilote ne fournit qu'un contexte OpenGL ES ou
  une version GLSL trop ancienne, sans boucle de compilation de shaders cassés.

## Incrément 0.3.0-dev.12 — Composition fiable des calques

- Les documents contenant un mode de fusion non-Normal sont composés dans une
  `QImage` raster avant affichage du `QOpenGLWidget`.
- Multiply, Overlay, Screen, Difference, HSL et les autres modes ne dépendent
  plus des capacités variables du moteur QPainter OpenGL ; le chemin GPU
  optimisé reste actif pour les calques Normal.

## Incrément 0.3.0-dev.13 — Alpha Lock fonctionnel

- L'Alpha Lock capture l'alpha existant au début des traits et le restaure
  après les chemins de peinture Python et CreativeCore C++.
- Le remplissage, les gradients et les formes respectent également les pixels
  transparents existants ; le verrouillage normal reste inchangé.

## Incrément 0.3.0-dev.14 — Dynamiques Brush Engine

- Ajout des paramètres canoniques vitesse → taille/opacité/flow, inclinaison,
  variation aléatoire et vitesse → espacement.
- Le moteur Python existant les évalue immédiatement ; le panneau Brush et les
  presets partagent le même état, en préparation de l'exposition complète des
  canaux d'entrée dans CreativeCore C++.

## Incrément 0.3.0-dev.15 — Raccordement CreativeCore des dynamiques vitesse

- Les paramètres vitesse → taille/opacité/flow sont maintenant exposés par
  l'API C (`cs_brush_set_velocity_*`) et appliqués par le moteur C++ réellement
  utilisé par le Canvas.
- Le bridge ctypes, les presets et le panneau utilisent ces symboles ; le
  fallback Python conserve les mêmes paramètres.
- Inclinaison et dynamiques aléatoires restent la prochaine sous-étape, car
  elles nécessitent de transmettre les champs tilt/rotation de `QTabletEvent`
  jusqu'à `BrushInput`.

## Incrément 0.3.0-dev.16 — Inclinaison tablette CreativeCore

- Ajout de `cs_brush_draw_segment_tilt` sans casser l'ancienne API C.
- `QTabletEvent.xTilt()/yTilt()` est transmis au `BrushInput` C++ à chaque
  segment ; tilt → taille/opacité est évalué par le moteur actif.
- Build C++ et tests unitaires validés ; la rotation du stylet et les courbes
  personnalisables restent les prochaines extensions de la branche dynamics.

## Incrément 0.3.0-dev.17 — Preview Brush réaliste

- La preview du panneau Brush rend désormais un trait court avec le moteur
  Python (taille, dureté, opacité, flow, pression et espacement) au lieu d'un
  simple point statique.
- Le rendu est déterministe, limité à une petite image et sans timer/repaint
  continu ; il se resynchronise avec l'état canonique et les presets.

## Incrément 0.3.0-dev.18 — Navigation canvas

- Rotation de vue non destructive avec reset dédié.
- Zoom 100 %, Fit Canvas et miroir horizontal/vertical de l'affichage.
- Mode Canvas Only qui masque temporairement docks et toolbar sans modifier le
  document ; les raccourcis clavier de vue sont également disponibles.
- Les rotations/miroirs de vue passent par le fallback raster pour préserver le
  rendu exact, tandis que le pipeline GPU normal reste inchangé.

## Incrément 0.3.0-dev.19 — Axes de symétrie

- Guides visuels horizontal/vertical dans le canvas.
- Réplication des traits autour des axes dans le chemin Python de secours,
  activable depuis le menu Affichage.

## Incrément 0.3.0-dev.20 — Symétrie CreativeCore

- Les segments et points de départ sont répliqués par le brush C++ autour des
  axes activés, sans changer l'ABI du bridge.
- Les signes X/Y de l'inclinaison du stylet sont réfléchis avec la géométrie.
- Test d'intégration ajouté pour valider les pixels produits de part et d'autre
  de l'axe par le backend C++.

## Incrément 0.3.0-dev.21 — Outils de vue et assistants

- Outils Main, Zoom et Rotation de vue ajoutés au registre d'actions, aux menus
  et au rail d'outils ; H, Z et Maj+R les activent.
- Zoom au pointeur par clic/roulette et rotation interactive par glisser ; la
  vue tournée ou miroir inverse correctement les coordonnées d'entrée et ses
  overlays restent alignés avec l'image.
- Fit Canvas tient compte de la rotation de vue ; les actions de vue et de
  symétrie sont à cocher dans les menus.
- Assistants exclusifs Règle, Ellipse et Perspective à un point : guides visuels
  et contraintes du brush dans le document, souris comme tablette.
- Le point de fuite de l'assistant Perspective se place par Maj+clic souris ou
  stylet et suit les dimensions courantes du document.
- Le rail d'outils est défilable pour conserver l'accès à tous les outils.
- Tests couvrant la conversion de coordonnées, le zoom ancré et les contraintes
  des assistants.

## Incrément 0.3.0-dev.22 — Optimisations du dessin et des mises à jour GPU

- Alpha Lock : l’alpha du snapshot pris au début du trait est restauré par
  CreativeCore uniquement dans le dirty rect du segment ; RGB peint préservé.
- Smudge : échantillonnage direct des pixels RGBA8888 depuis les scanlines et
  test de distance au carré avant le calcul de la pondération.
- GPU : les mises à jour utilisent `glTexSubImage2D` via ctypes pour téléverser
  le dirty rect dans la texture du calque existante, sans recréer la texture.
- Vérification : build C++, CTest, compilation Python et tests synthétiques du
  bridge/restauration alpha réussis ; test manuel dans l’application confirmé.

## Reprise

- Étapes 1 à 9 terminées ; l’étape 10 est terminée.
- Premier outil métier livré : Clone Stamp (`0.3.0-dev.23`).
- Étape 8 terminée avec les références, le texte éditable, Blur/Sharpen et Bezier
  (`0.3.0-dev.24`).
- Étape 10 terminée : couverture dirty rect, compatibilité CSD, mesures de
  transfert et validation automatisée du shell.
- Prochaine étape : poursuivre la roadmap v0.3 avec validation manuelle sur
  pilotes OpenGL, documents de grande taille et workflows complets.

## Incrément 0.3.0-dev.25 — Shell applicatif

- Les raccourcis en conflit sont refusés avec un message qui nomme l’action
  propriétaire ; l’éditeur de raccourci revient à la séquence active.
- La toolbar accepte des actions configurables par menu contextuel et conserve
  les choix dans QSettings.
- Les workspaces intégrés Default, Painting, Drawing et Minimal sont enregistrés
  comme dispositions distinctes ; les workspaces enregistrés apparaissent dans
  le menu Fenêtre et la session restaure la disposition courante.
- Tous les docks, y compris la rail d’outils, peuvent être déplacés, détachés et
  fermés ; le menu Fenêtre/Dockers expose leurs actions de visibilité.
- Vérification : compilation Python, 6 tests UI et smoke test de création du
  shell et des workspaces réussis.

## Incrément 0.3.0-dev.26 — Durcissement

- Le renderer GPU expose des compteurs cumulés pour les uploads complets, les
  sous-uploads dirty rect et les octets copiés vers le buffer temporaire ; les
  compteurs peuvent être lus puis remis à zéro.
- Le dirty rect reçu est borné à la texture et un changement sans bornes force
  explicitement le transfert complet.
- Le chargement CSD rejette les manifests sans calque, les DPI invalides et les
  calques dont les dimensions ne correspondent pas au document ; l’opacité est
  ramenée dans l’intervalle valide.
- La migration legacy n’écrit plus de membre `document.json` dupliqué dans les
  archives de test ; tests ajoutés pour les manifests malformés et le suivi des
  dirty rects.
- Vérification : 52 tests Python, build C++ et CTest réussis, ainsi que la
  compilation des modules Python et la vérification des symboles C exportés.

## Incrément 0.3.0-dev.23 — Clone Stamp

- Outil Clone Stamp ajouté au rail, au menu Outils et au registre de raccourcis
  (`K`). Maj+clic définit le point source sur le calque actif.
- Le bridge CreativeCore clone le contenu source avec le tip, la texture,
  l’opacité, le flow et les dynamiques du brush actif.
- Un snapshot source au début de chaque trait évite que le clonage lise ses
  propres écritures pendant le trait ; Undo reste une opération par trait.
- Le fallback CPU fournit un clone à tip rond piloté par taille, dureté,
  espacement, opacité et pression.
- Vérification : test d’intégration du bridge, suite BrushIntegration,
  compilation Python, build C++ et CTest réussis.

## Incrément 0.3.0-dev.24 — Outils métier

- Images de référence non destructives : import, affichage par-dessus le canvas,
  déplacement, zoom à la molette, suppression et persistance CSD v4.
- Texte éditable non destructif : ajout/modification par clic, Maj+glisser pour
  déplacer, suppression, rendu au-dessus des calques et inclusion dans la
  composition/export ; CSD v4 conserve texte, position, couleur et police.
- Blur et Sharpen appliquent un filtre local sous un tip rond piloté par la taille,
  l’espacement, l’opacité et la pression ; CreativeCore C++ et fallback CPU.
- Bezier : deux poignées glissées définissent une courbe cubique ; preview,
  souris/stylet et rendu final avec le brush actif, en une entrée d’historique.
- Undo/Redo couvre les objets texte et référence. CSD reste rétrocompatible avec
  les manifests antérieurs qui ne contiennent pas ces champs.
- Vérification : 49 tests Python, CTest, build C++, compilation Python et smoke
  tests UI/rendu réussis.
