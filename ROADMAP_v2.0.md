# CreativeSystem — Roadmap vers la v2.0

## Objectif

Cette roadmap rassemble les chantiers produit demandés pour faire évoluer
CreativeSystem vers une version 2.0. Les éléments sont organisés par étapes
pour rendre leur réalisation et leur validation suivables. La v2.0 vise une
interface cohérente, des formats d’échange fiables, des réglages de fusion
éditables et une meilleure récupération des sessions.

## Jalons

### 1. Interface et préférences

- [x] Refaire l’interface dans un style professionnel, dense et sombre, en
  s’appuyant sur les références Photoshop et Paintstorm.
- [x] Utiliser les icônes SVG Phosphor, en 24 px et poids Regular, avec un style
  cohérent dans toute l’application.
- [x] Appliquer la palette : fond `#1e1e1e`, panneaux `#252525`, bordures
  `#333333`, accent bordeaux `#9B1F35`, hover/focus `#B52840` et couleur
  inactive/muted `#777777`.
- [x] Remplacer toutes les lettres placeholder par une icône SVG propre à
  chaque outil.
- [x] Compléter les fenêtres de préférences : General, Interface, Canvas,
  Input, Tablet, Brush, Performance, CPU, Files, Autosave et Color Management.
- [x] Enregistrer immédiatement les préférences et appliquer en direct les
  réglages déjà reliés : stabilisation, fond et zoom du canevas, anticrénelage,
  pression tablette, espacement du brush, densité UI, limite Undo, format et
  dossier de fichiers, compression CSD et autosave.
- [x] Relier le nombre de threads CPU au worker natif de projection, le budget
  CPU au cache composite, la taille d’icône à la barre d’outils, la limite Undo
  au démarrage et le prélèvement clic droit à l’option correspondante.
- [x] Relier le réglage tablette « Ignore synthetic mouse events » : les
  événements souris synthétiques reçus dans les 120 ms après un événement
  tablette sont filtrés, tandis que les événements souris natifs passent.
- [x] Mémoriser les réglages du brush séparément par outil et restaurer les
  réglages au changement d’outil.
- [ ] Vérifier systématiquement la restauration de chaque préférence après
  redémarrage et implémenter les options encore sans effet (profil couleur,
  langue et gestion d’espace colorimétrique dans les exports).
- [x] Remplacer le réglage trompeur de taille des tuiles par une indication
  explicite : le format interne reste fixé à 64 × 64 px afin de préserver
  l’alignement du store, de l’historique et de la projection.
- **Critère de sortie :** tous les outils ont une icône cohérente, les pages de
  préférences exposent des réglages fonctionnels et les réglages persistants
  sont restaurés au lancement.

### 2. Modes de fusion paramétrables

- [x] Ajouter les paramètres de fusion au panel des calques et les appliquer
  directement au calque sélectionné.
- [x] Garder les presets livrés en lecture seule.
- [x] Permettre de créer un preset custom comme copie d’un preset défaut, puis
  de le modifier et de l’enregistrer.
- [x] Ajouter l’import et l’export au format `.csbl` (CreativeSystem Blend).
- [x] Générer automatiquement une miniature d’aperçu pour chaque preset.
- [x] Embarquer les presets appliqués et leurs paramètres dans le document `.csd`.
- [x] Ajouter à tous les modes les réglages communs :
  - Opacity : `0.0 → 1.0`
  - Mix mode opposé : `0.0 → 1.0` (par exemple Multiply ↔ Screen)
- [x] Ajouter les réglages par famille de modes :
  - **Multiply / Screen :** Intensity `0.0 → 1.0`, Gamma `0.5 → 2.5`, Mix
    Normal `0.0 → 1.0`.
  - **Overlay / Hard Light :** Intensity `0.0 → 1.0`, Pivot `0.0 → 1.0`
    (seuil darken/lighten), Mix Normal `0.0 → 1.0`.
  - **Color Dodge / Color Burn :** Intensity `0.0 → 1.0`, Clamp
    `0.0 → 1.0` (limite les valeurs brûlées), Mix Normal `0.0 → 1.0`.
  - **Soft Light :** Intensity `0.0 → 1.0`, Softness `0.0 → 1.0` (courbe de
    transition), Mix Normal `0.0 → 1.0`.
  - **Hue / Saturation / Color / Luminosity :** Intensity `0.0 → 1.0`, Hue
    Shift `-180 → +180`, Saturation Boost `0.0 → 2.0`.
  - **Difference / Exclusion :** Intensity `0.0 → 1.0`, Offset `0.0 → 1.0`
    (décale les valeurs de comparaison), Mix Normal `0.0 → 1.0`.
- [x] Vérifier que les réglages sont annulables/rétablissables.
- [x] Lire directement les pixels des cinq formats QImage requis par le
  compositeur et tester les conversions, y compris les formats prémultipliés.
- [ ] Comparer les rendus CPU et GPU des réglages paramétrés ; le chemin GPU
  reste désactivé pour ces modes et le fallback CPU est utilisé.
- **Critère de sortie :** presets défaut protégés, presets custom échangeables,
  aperçu généré, et paramètres conservés dans un `.csd` après fermeture et
  réouverture.

### 3. Formats de document et de brush

- [x] Stabiliser le format `.csd` avec un manifest versionné.
- [x] Inclure dans le `.csd` les presets de fusion utilisés et une miniature du
  document.
- [x] Ajouter les valeurs par défaut rétrocompatibles et vérifier l’ouverture
  d’un manifeste historique sans version de schéma ni métadonnées récentes.
- [x] Ajouter l’import et l’export brush au format `.csbr`.
- [x] Définir `.csbr` comme une archive ZIP contenant `brush.json` (paramètres),
  `texture.png` et `preview.png`.
- [x] Valider les archives incomplètes, les fichiers malformés et les champs
  inconnus sans faire planter l’application.
- **Critère de sortie :** documents et brushes font un aller-retour import,
  ouverture, sauvegarde et réouverture sans perte des données prises en charge.

### 4. Pack de brushes prêt à l’emploi

- [x] Livrer un pack de base généré via JSON CreativeCore, sans dessin manuel.
- [x] Inclure les brushes suivants :
  - Round Hard : dureté `1.0`, flow `1.0`.
  - Round Soft : dureté `0.0`, flow `1.0`.
  - Round Soft Flow : dureté `0.0`, flow `0.3`.
  - Flat Hard : rondeur `0.3`, angle `0°`.
  - Flat Soft : rondeur `0.3`, dureté `0.3`.
  - Ink Pen : dureté `1.0`, pression max.
  - Airbrush : dureté `0.0`, flow `0.2`, spacing `0.05`.
  - Eraser Soft : équivalent de Round Soft.
  - Eraser Hard : équivalent de Round Hard.
- [x] Vérifier que le pack est disponible après installation propre et fonctionne
  avec le backend pris en charge.
- **Critère de sortie :** les neuf brushes sont installés par défaut, chargent
  leurs paramètres attendus et permettent de peindre dès le premier lancement.

### 5. Autosave, récupération et robustesse

- [x] Ajouter l’autosave avec une fréquence réglable et un emplacement de
  récupération dédié.
- [x] Récupérer une session après fermeture inattendue et proposer clairement
  de reprendre ou d’ignorer la récupération.
- [x] Vérifier les sauvegardes interrompues et éviter de remplacer un document
  valide par un fichier incomplet.
- [ ] Chasser les bugs lors de longues sessions, sur de grands canvas et avec
  de nombreux calques. Les contrôles actuels sont des tests unitaires et des
  mesures ponctuelles ; ils ne remplacent pas un soak test interactif.
- [ ] Mesurer l’usage mémoire et surveiller les ralentissements et fuites lors
  de ces scénarios. Une mesure ponctuelle 2048² est consignée ci-dessous.
- **Critère de sortie :** les sessions de stress documentées se terminent sans
  crash reproductible, et une interruption permet de retrouver une sauvegarde
  exploitable.

### 6. Architecture de rendu et mémoire

- [x] Stocker les pixels des calques dans des tuiles CPU creuses de 64 × 64 px ;
  conserver une vue `QImage` de compatibilité pour les outils existants.
- [x] Créer une texture OpenGL par tuile visible, réutiliser les textures et
  borner leur cache GPU ; ne dessiner que les tuiles du viewport.
- [x] Faire composer les modes de fusion sur un thread CPU natif CreativeCore
  (file thread-safe, coalescence par tuile, pool natif configurable jusqu’à 16
  workers et callbacks), puis transférer les images CPU vers le thread UI ; les
  appels OpenGL restent sur le thread UI. Les tuiles d’une requête sont aussi
  soumises en un appel batch ctypes.
- [x] Mettre en cache les composites par tuile et invalider les zones dont la
  révision des pixels ou les propriétés de calque ont changé ; ne projeter que
  les tuiles du viewport courant.
- [x] Ajouter le scratch PNG configurable dans Préférences > Performance ;
  évincer en arrière-plan les tuiles hors viewport suivant leur dernière
  utilisation, puis les recharger en arrière-plan pour le rendu GPU et la
  projection. Le swap existant couvre aussi les deltas Undo/Redo.
- [x] Aligner les captures Undo dirty-only sur les tuiles 64 px et éviter de
  matérialiser une image pleine pour capturer/restaurer les pixels concernés.
- [x] Borner le cache composite pleine image réservé aux exports/compatibilité ;
  utiliser la projection tuilée pour les modes de fusion à l’écran.
- [ ] Rendre toute la transaction de stroke asynchrone. Le dessin C++ et la
  validation Undo se font encore dans les appels d’outils existants ; la
  projection des tuiles, elle, est asynchrone. Le tampon QImage contigu est
  maintenant conservé pendant le stroke et chaque segment ne synchronise que
  son dirty rect, ce qui supprime les rematérialisations complètes à chaque
  repaint ; le calcul C++ d’un segment reste synchrone.
- [x] Mesurer le noyau de composition natif face à `composite_layers()` :
  ×14,6 (64 × 64) et ×17,5 (128 × 128 et 256 × 256), cinq calques paramétrés
  sur le build Release/OpenMP. Cette mesure ne couvre pas l’orchestration
  complète du worker.
- [ ] Atteindre ×10 sur le chemin projection complet. Le benchmark 256 tuiles ×
  5 calques mesuré après activation du pool donne 64,0 ms à 8 threads contre
  138,2 ms avant (×2,16) en requêtes unitaires ; le batch donne 75,7 ms contre
  92,6 ms (×1,22). Le gain ×10 bout en bout n’est pas atteint.
- [ ] Créer les textures composites directement dans un contexte OpenGL partagé.
  Le worker natif renvoie actuellement des pixels CPU ; Qt les consomme sur le
  thread UI pour préserver l’affinité du contexte `QOpenGLWidget`.
- [x] Ajouter des groupes de calques contigus avec visibilité, opacité,
  composition isolée, cache de tuiles, Undo/Redo et persistance CSD. La liste
  conserve son ordre plat pour compatibilité ; les groupes imbriqués ne sont pas
  pris en charge.
- [ ] Adapter CreativeCore à un accès natif par tuile. Son API pinceau utilise
  toujours un buffer contigu : la compatibilité matérialise temporairement une
  image complète du calque pendant le stroke.
- [ ] Mesurer les coutures entre textures indépendantes, le coût des gros
  transferts C++ et la réactivité du rechargement scratch sur de grands fichiers.
- **Critère de sortie :** les tuiles limitent les transferts et la composition
  aux zones modifiées ; les workflows existants restent compatibles ; les
  prochains travaux explicitement ouverts ci-dessus sont validés avant release.

## Validation de la version

### Travail réalisé et mesures (16 septembre 2026)

- Suite Python avant les derniers réglages : **87 tests réussis**. Vérification
  finale de cette passe : **96 tests réussis** (`python -m unittest discover
  -s CPP_TEST -p 'test_*.py'`). Tests C++ : **2/2 réussis**
  (`ctest --test-dir build_cpp_native --output-on-failure`).
- La projection des tuiles blend s’exécute en C++ natif ; le test d’intégration
  compare les 16 modes à la référence Python. Le test C++ vérifie la file de
  travail asynchrone et le résultat Multiply.
- Le picker lit une seule tuile sans matérialiser le calque. Si elle est swappée,
  le prélèvement reprend après chargement asynchrone ; des tests couvrent ces
  deux chemins.
- Mesures locales Release/OpenMP : gain natif **×14,6 à ×17,5** pour 5 calques
  sur des tuiles 64–256 px. Le contexte graphique Wayland de cette session a
  avorté pendant l’initialisation de `QApplication`; le canvas natif s’est
  construit et fermé proprement avec le backend offscreen.
- Modules Python modifiés compilés avec `py_compile`.
- Après les correctifs stylet, groupes, tablette et réglages par outil : suite
  complète à **96/96**,
  CTest **2/2**, `compileall` réussi et application démarrée/fermée sur
  Wayland/OpenGL avec code de sortie 0.
- Une validation graphique antérieure avait obtenu des contextes OpenGL valides
  pour le canvas et l’aperçu ; ce lancement Wayland n’a pas pu être répété ici.
  Les tests couvrent le stockage creux, les rectangles sales, l’accès LRU, le
  swap PNG synchrone/asynchrone, Undo, les limites viewport et la projection
  blend native.
- Compositeur mesuré sur un document de 2048 × 2048 avec cinq calques : rendu
  froid **3,8 s**, rendu répété en cache **1,5 ms** en moyenne, rendu après
  modification d’un calque **3,6 s**, mémoire maximale du processus **233 Mio**.
  Cette mesure ponctuelle ne remplace pas les essais de longues sessions ; le
  coût d’un nouveau rendu reste à réduire.
- Le test de lecture directe des pixels couvre ARGB32, ARGB32 prémultiplié,
  RGB32, RGBA8888 et RGBA8888 prémultiplié.
- Le test d’ouverture historique CSD vérifie un manifeste sans version de
  schéma ni plusieurs métadonnées récentes. Les autres historiques et migrations
  ne sont pas encore couverts.
- La suite inclut les aller-retours CSD/CSBR/CSBL, archives malformées,
  récupération, Undo/Redo et intégration du brush. Ces tests passent ; ils ne
  valident pas encore une session graphique prolongée multi-plateforme.
- Le réglage CPU « Worker threads » pilote maintenant le nombre de threads
  OpenMP du worker natif (Automatic conserve l’ajustement automatique). Une
  valeur QSettings illisible retombe en mode Automatic au lieu de désactiver la
  projection native. « Image cache limit » borne le cache composite de
  compatibilité ; ce n’est pas un quota mémoire général.
- Le chemin du stylet conservait puis relâchait auparavant le cache QImage à
  chaque `paintGL`; l’événement tablette suivant rematérialisait donc tout le
  calque et réécrivait l’image complète après le segment C++. Le calque actif
  garde maintenant son buffer RGBA pendant le stroke via `adopt_image_cache`,
  les invalidations rendent seulement le dirty rect, puis le buffer est libéré
  au prochain rendu hors stroke. Un test automatise 30 segments et vérifie
  zéro nouvelle matérialisation ainsi que la restauration Undo/Redo.
- Les calques restent ordonnés dans une liste plate, mais le document prend
  maintenant en charge des groupes contigus. Leur cache isolé est invalidé par
  révision de pixels et leurs propriétés d’opacité/visibilité sont restaurées
  par Undo/Redo. Les groupes imbriqués ne sont pas pris en charge.
- Le filtre des événements souris synthétiques de la tablette est configurable
  et actif après chaque événement tablette pendant 120 ms. Les événements souris
  natifs ne sont pas supprimés.
- Le brush natif par tuile, les strokes asynchrones de bout en bout et la sortie
  texture OpenGL partagée restent ouverts.

- [x] Vérifier par tests les workflows de peinture, Undo/Redo, sauvegarde,
  ouverture, récupération et les archives malformées CSD/CSBR/CSBL.
- [x] Auditer le coût ctypes, la parallélisation des tuiles et l’accès OpenGL ;
  ajouter un pool C++ natif et une API batch. Mesures et limites dans
  [`AUDIT_PROJECTION_PERFORMANCE.md`](AUDIT_PROJECTION_PERFORMANCE.md).
- [ ] Comparer les rendus CPU et GPU des modes de fusion paramétrés.
- [ ] Tester les longues sessions, grands canvas et documents multicouches sur
  les plateformes ciblées ; le lancement Wayland/OpenGL validé ici est un smoke
  test court, pas un test d’endurance.
- [x] Documenter les changements de réglages et les limites d’architecture dans
  README et l’audit d’architecture.

## Dépendance

La version 2.0 s’appuie sur la stabilisation des workflows essentiels et du
format `.csd` prévue dans [`ROADMAP_v1.0.md`](ROADMAP_v1.0.md). Les critères
v1.0 restent à valider avant la publication de la v2.0.
