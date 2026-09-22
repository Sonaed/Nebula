# Migration d’Atlas vers CreativeSystem Nebula

État vérifié le 21 septembre 2026. Nebula est l’application maintenue ; Atlas
reste intact comme référence et ses projets sources ne sont jamais écrasés.

## Correspondance des capacités

| Atlas alpha 0.1 | Destination Nebula | État et limites |
| --- | --- | --- |
| `TileStore`, LRU, scratch et mémoire | `CPP_CORE/src/tile_store.cpp`, `DOCUMENTS/tile_store.py`, `CORE/memory_manager.py` | Pixels résidents, révisions et recency sont autoritaires en C++; l’adaptateur Python garde encore le registre des fichiers scratch, les callbacks Qt et l’orchestration d’éviction. |
| Historique raster par tuiles | `CANVAS/tile_history.py`, `CPP_CORE` | Annulation/rétablissement par tuiles, changements structurels et stockage déporté testés. |
| BrushEngine et entrées tablette | `CPP_CORE/src/brush_engine.cpp`, bridge C | Moteur de peinture natif, pression/inclinaison, gomme, wet/smudge, clonage et filtres ; l’interface transmet les événements. |
| Pointe d’image (`BitmapBrush`) | API C++ `cs_brush_set_bitmap_tip_*`, dock Brush et preset `.csbr` | Pointe couleur chargée/décodée dans CreativeCore, conservée dans les presets et couverte par un test de rendu pixel. Texture de masque et pointe couleur sont deux fonctions séparées. |
| Calques, opacité, visibilité, fusion | `DOCUMENTS` + projection C++ | Modes de fusion et groupes plus riches que les modes réellement calculés par le moteur FusionCreator d’Atlas. |
| Sérialisation `.atlas` v2/v3 | `CPP_CORE/src/atlas_import.cpp` + adaptateur de document | Import en lecture seule. Les pixels, nom/auteur, DPI, visibilité, opacité, modes de fusion et couverture du masque sont conservés ; les masques Atlas sont incorporés à l’alpha du calque car Nebula ne possède pas encore d’objet masque éditable indépendant. |
| Export PNG/TIFF aplati | Export de Nebula | Couverture déjà présente, les exports ne remplacent pas le document éditable. |
| Roue et interface GTK | Roue/docks PySide6 et thème Nebula | Le visuel GTK expérimental n’est pas repris ; Nebula reçoit une direction visuelle propre, inspirée des références fournies. |

## Import des projets Atlas

L’ouverture d’un fichier `.atlas` lit sa signature `ATLS` et ses versions 2 ou 3
dans le pont C++. Le parseur borne les dimensions, le nombre de calques, les
chaînes et les blocs zlib ; les pixels compressés restent sur disque jusqu’à la
demande de copie d’un calque. Un bloc invalide ou tronqué fait échouer le
chargement au lieu de produire un document partiel.

Le fichier Atlas original est ouvert en lecture seule. **Enregistrer** demande
un nouveau chemin ; une sauvegarde `.nebula` produit le format natif versionné
et ne remplace pas le fichier `.atlas`. Les modes Atlas connus sont convertis
vers leurs équivalents Nebula (`add` → `addition`, `sub` → `subtract`, `sat` →
`saturation`, `lum` → `luminosity`). Les chaînes de mode inconnues deviennent
`normal` pour garder le document ouvrable.

Atlas v2 ne sérialisait ni DPI ni couleur de fond ; l’import lui donne 72 DPI et
un fond transparent. La projection sauvegardée par Atlas n’est pas un contenu
de l’œuvre ; Nebula ajuste son viewport au document à l’ouverture.

## Éléments volontairement non repris

L’audit a distingué le code compilé des fonctions réellement disponibles dans
l’application Atlas :

- l’API plugin ne contient que des structures de métadonnées et des pointeurs
  d’entrée/sortie ; aucun chargement/exécution de plugin opérationnel n’est
  raccordé à l’application ;
- `ToolCreator` valide des chaînes puis crée un outil dont les callbacks ne
  font rien ; l’exécution Python embarquée contredit en outre la règle selon
  laquelle Python reste réservé à l’interface ;
- plusieurs modes du `FusionCreatorEngine` ont des kernels CPU/GLSL identité,
  et la « validation GLSL » se limite à rechercher quelques mots ; ils ne sont
  pas des modes de fusion utilisables à reprendre ;
- les classes expérimentales `BlurBrush`, `SmearBrush`, `DodgeBrush` et
  `BurnBrush` ne sont pas enregistrées dans le flux d’outils de l’application
  Atlas. Leurs implémentations sont des approximations (par exemple, le flou
  remplace les couleurs par leur moyenne) ; les outils Nebula de flou,
  netteté, smudge et clonage sont déjà raccordés et testés.

Ne pas porter ces amorces n’enlève donc pas une capacité de dessin accessible
dans Atlas. Un système de plugins ou des outils scriptables pourront être
conçus plus tard comme fonctionnalités explicites, isolées et sûres, pas comme
une importation de ces stubs.

## Validation reproductible

- `python -m unittest CPP_TEST.test_atlas_import CPP_TEST.test_bitmap_brush_api -v`
  couvre Atlas v2/v3, masques, propriétés de calques, rejet des fichiers
  tronqués, conversion `.atlas` → `.nebula` et invariance de l’original ; il
  vérifie aussi l’effet d’une texture bitmap et d’une pointe couleur dans le
  moteur natif, ainsi que la persistance de la pointe couleur dans `.csbr`.
- `cmake --build build_cpp_native -j2` puis
  `ctest --test-dir build_cpp_native --output-on-failure` valident la
  compilation et le noyau C++.

## Écart d’architecture restant

La fusion des fonctionnalités d’Atlas ne signifie pas que toute la logique de
Nebula est déjà C++ : le modèle de document, le TileStore, la gestion des
calques, les sélections, plusieurs outils et une partie de l’historique vivent
encore en Python. La règle cible reste « Python/PySide6 = interface ; logique
du dessin et des documents = C++ ». Leur transfert complet exige une migration
API par API et des tests de parité ; cette documentation ne le présente pas à
tort comme terminé.
