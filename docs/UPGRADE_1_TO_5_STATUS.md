# Suivi des chantiers Nebula — étapes 1 à 5

Mis à jour le 22 septembre 2026. Ce document suit l’exécution des cinq
priorités sans confondre une suite de tests verte avec une validation manuelle
complète ou une migration C++ terminée.

Les pixels, le stockage tuilé, les outils, les règles structurelles et le
curseur d’historique sont autoritaires dans CreativeCore. Python/PySide6 reste
limité aux objets miroir des docks, aux événements Qt et à la présentation ; le
test d’architecture interdit tout fallback de rasterisation dans les adaptateurs.
La validation manuelle du parcours courant a été confirmée par l’utilisateur le
22 septembre 2026. La validation sur un document Atlas utilisateur est différée
jusqu’à la construction d’Atlas ; l’audit final des adaptateurs de compatibilité
et la migration architecturale complète restent à achever.

## Avancement vérifié

### 1. Fiabilité des workflows

- Validation actuelle : 268 tests Python via `unittest discover` et 11 cibles
  C++ via CTest passent. `pytest` n'est pas installé, mais l'ensemble des tests
  Python du dossier CPP_TEST a pu être exécuté par le runner standard.
- `build_cpp_native` est l’arbre C++ de référence et porte les 11 cibles ; un
  second arbre propre `build_cpp_nebula` les valide également. Un ancien
  `build_cpp` importé depuis `CreativeSystem v0.2` contient encore une seule
  cible historique ; son cache CMake pointe vers l’ancien chemin et ne doit pas
  être utilisé pour valider Nebula.
- Les tests couvrent notamment brush natif, outils, historique par tuiles,
  sauvegarde/réouverture Nebula, import CSD et restaurations scratch.
- Le benchmark de remplissage compare aussi le même scénario connecté entre le
  chemin de compatibilité et CreativeCore natif.
- Les outils flou/netteté ne rasterisent plus en Python en production : leur
  traitement est exclusivement CreativeCore; la référence Python est conservée
  uniquement pour mesurer et vérifier la parité.
- Le stockage sparse ne possède plus de carte de tuiles Python active : si
  CreativeCore n’est pas disponible, la création du document échoue explicitement.
- Le début d’un trait ne lit plus `layer.image` uniquement pour connaître son
  format : il utilise directement `tile_store.image_format`, évitant ainsi une
  matérialisation complète de la toile à chaque événement tablette/souris.
- Les snapshots de preview du gradient, des formes, de la sélection et du
  verrou alpha passent maintenant par `cs_copy_image_rect` via le helper natif
  `clone_image_native` ; ces chemins n’effectuent plus de copie raster complète
  avec `QImage.copy()` côté Python.
- La primitive `cs_image_fill` centralise maintenant les remplissages de fond,
  de masque de sélection et d’images de référence lors de la création et de
  l’ouverture d’un document ; ces mutations ne passent plus directement par
  `QImage.fill()` dans l’adaptateur Python.
- La primitive native `cs_apply_alpha_mask` est maintenant utilisée par les
  masques alpha éditables des calques : stockage sparse natif, composition plein
  document, projection temps réel par tuile, duplication et round-trip Nebula.
  Un masque absent
  conserve la couverture complète, tandis qu’une tuile de masque absente reste
  implicite et peu coûteuse. Les tests vérifient la multiplication alpha sans
  altération RGB et la persistance des tuiles de masque.
- La génération des aperçus de modes de fusion utilise maintenant les
  primitives natives `cs_image_fill` et `cs_image_fill_rect`; le module de
  presets ne possède plus de rasterisation `QPainter` de production.
- La génération des tips et aperçus de presets de brosse utilise désormais
  `cs_render_brush_preset_art` dans CreativeCore ; Python ne fait plus que
  demander les images natives puis les encoder et les sérialiser.
- Un test d’architecture interdit désormais le retour d’un `QPainter` ou d’un
  `QImage.copy()` de rasterisation dans les adaptateurs `DOCUMENTS` et `TOOLS`;
  les copies de tuiles et de caches sont maintenant servies par
  `clone_image_native`.
- La table de correspondance des modes Qt a été déplacée vers
  `UI/qt_blend_modes.py`; `DOCUMENTS/blend_modes.py` ne dépend plus de
  `QPainter`, même pour les constantes de présentation.
- Les règles de frontière entre CreativeCore, adaptateurs Python et UI sont
  maintenant réunies dans [`ARCHITECTURE_BOUNDARIES.md`](ARCHITECTURE_BOUNDARIES.md)
  pour servir de référence aux prochains modules.
- Le benchmark TileStore a été nettoyé pour ne plus tenter un fallback Python
  supprimé : mesure native actuelle sur ce poste, 256 paires set+copy en
  **7,857 ms**, écriture+matérialisation 1024² en **2,037 ms**, restauration
  Undo de 256 tuiles en lot en **1,903 ms** contre **2,125 ms** unitaire.
- Les buffers transparents temporaires des tuiles sparse, de la projection,
  des masques de sélection et de la restauration Undo/Redo utilisent également
  `cs_image_fill`, ce qui ferme le dernier groupe de remplissages raster dans
  les chemins documentaires actifs.
- La projection des calques est également strictement native : le worker Python
  ne compose plus d’images et refuse de démarrer sans CreativeCore.
- Le chemin TileStore ne conserve plus de carte de tuiles ou d’éviction d’image
  Python : les pixels, révisions et écritures de scratch passent par CreativeCore.
- Le canvas refuse maintenant de démarrer sans BrushEngine CreativeCore : aucun
  chemin de peinture Python de secours n’est accepté.
- Un smoke test headless couvre désormais le démarrage de `CreativeSystem`,
  l’activation du canvas/projection natifs, la boucle Qt et la fermeture propre.
- Un fichier CSD utilisateur réel (`Ornement For Website.csd`) a été importé,
  converti en `.nebula`, puis relu avec dimensions, DPI et quatre calques
  conservés. La fixture produite par le sérialiseur Atlas v3 passe aussi ce
  round-trip automatiquement; aucun `.atlas` de production n’est disponible.
- La trace XP-Pen (`atlas_xppen_events.txt`) confirme la présence d’un stylet
  `28bd:0002`, de pression progressive et de tilt X/Y. Le traitement Qt conserve
  désormais la pression précédente avant de transmettre chaque segment au C++;
  un test protège cette interpolation. Hors sandbox, `libinput` ouvre bien
  `/dev/input/event24` et identifie `XP-Pen Pen` comme tablette calibrée;
  Le smoke test hors écran démarre Nebula, boucle dix secondes puis se ferme
  proprement. Dans la session actuelle, les tentatives Wayland/OpenGL et XCB
  avortent avant toute sortie ; une reproduction avec le pilote graphique
  interactif reste nécessaire. Une session interactive de 30 secondes avec
  écoute `libinput` doit aussi être rejouée sur la machine cible pour valider
  la pression réelle de bout en bout.
- Une séquence `QTabletEvent` synthétique press/move/release vérifie maintenant
  le chemin complet d’événement et l’appel C++ avec pression `0,20 → 0,80` et
  tilt `(15°, 16°)`; elle ne remplace pas le test du périphérique réel.
- La trace matérielle `../CreativeSystemAtlas_alpha0.1/atlas_xppen_events.txt`
  identifie le périphérique utilisé comme `XP-Pen Pen` `28bd:0002`, zone active
  262×148 mm, avec pression normalisée et inclinaison observée autour de
  `15°/16°`; les événements libinput sont espacés d’environ 3–4 ms. Cette
  référence confirme les valeurs de la séquence synthétique, sans remplacer
  une session physique longue dans Nebula.
- Le dock d’outils ne charge plus `TOOLS.brush_engine` pour son aperçu : celui-ci
  est rendu directement par Qt, et aucun import/instanciation du moteur Python
  legacy ne subsiste dans l’application.
- Les six modules Python orphelins de cet ancien moteur (`brush_engine` et ses
  composants de dynamique/tip/texture/couleur/peinture) ont été supprimés après
  audit des imports; les 266 tests et le smoke test restent verts.
- Les copies de sauvegarde de l’ancien canvas, du brush engine et du dock outils
  ont été supprimées de l’arbre source : il ne reste plus de doublon éditable
  pouvant être repris par erreur comme architecture active. Les références
  CSD/Atlas et le test de parité historique restent conservés volontairement.
- Le packer d’atlas GPU n’utilise plus PIL ni une réserve de pixels Python :
  l’allocation shelf, l’écriture RGBA et la copie des régions sont désormais
  possédées par CreativeCore; l’adaptateur Qt ne conserve que les rectangles et
  transmet les images au backend OpenGL. La destruction explicite de l’handle
  natif couvre aussi la fermeture Qt après disparition du contexte OpenGL.
- `TOOLS/brush.py` ne crée plus l’ancien `BrushEngine` Python : il ne conserve
  qu’un état de contrôle pour l’interface, et toute tentative de rasterisation
  Python est refusée explicitement.
- L’ancien pont `draw_with_gpu_sync()` a été supprimé : il était orphelin et
  pouvait appeler l’ancienne API de dessin Python. Les chemins de peinture
  actifs passent maintenant uniquement par les segments CreativeCore.
- L’état de transaction Undo a été nettoyé : les caches Python `images` et
  `dirty_rects`, jamais consommés au commit/replay, ont été retirés; le payload
  de tuiles natif reste l’unique source de vérité pour les pixels modifiés.
- Le curseur C++ possède désormais aussi les états document cœur `before/after`
  sérialisés en JSON; Undo/Redo les relit depuis CreativeCore, tandis que le
  miroir Python ne conserve plus les métadonnées des textes éditables; seuls
  les pixels des images de référence et les objets Qt reconstruits restent au
  bord de présentation. Chaque état natif est borné à 16 MiB et les pointeurs
  nuls sont rejetés proprement; CTest couvre aussi le rejet d’un état dépassant
  cette limite.
- Le modèle natif document/calques est resynchronisé après les restaurations
  structurelles Undo/Redo, les fusions et l’aplatissement : la liste Qt miroir
  ne peut plus diverger silencieusement de l’état CreativeCore.
- La validation des groupes et leur appartenance native sont maintenant
  possédées par CreativeCore ; Python conserve uniquement les objets Qt,
  identifiants de présentation et caches visuels. Les groupes singleton issus
  d’une suppression sont acceptés pour préserver la sémantique de la V1.
- La visibilité et l’opacité des groupes sont également validées et stockées
  dans CreativeCore ; les actions de l’interface passent par l’adaptateur natif
  et les restaurations structurelles réappliquent ces propriétés.
- Le badge de la barre d’outils ne présente plus de faux « Python fallback » :
  l’absence de CreativeCore est signalée explicitement, conformément au refus
  des mutations raster sans moteur natif.
- Les deux références Python historiques de clone et de filtre ont été sorties
  de `CANVAS/canvas.py` et déplacées dans `CPP_TEST/legacy_brush_reference.py`;
  elles ne peuvent donc plus devenir un chemin d’édition applicatif par erreur.
- Pour les étapes Undo/Redo entièrement sérialisables, les métadonnées document,
  calques, groupes, textes et presets sont désormais conservées uniquement dans
  le curseur natif ; `UndoStep` ne garde qu’un compteur d’octets natifs et les
  payloads de tuiles, sauf les images de référence Qt encore nécessaires à la
  présentation.
- Les images de référence des étapes générales sont maintenant encodées dans
  le JSON d’état natif (PNG/base64, avec la limite CreativeCore de 16 Mio) puis
  reconstruites en `ReferenceImage` uniquement lors du replay Qt. Leur identité,
  position, échelle, opacité et pixels sont couverts par un test Undo/Redo.
- Le recadrage raster ne passe plus par `QImage.copy()` dans `CropTool` : la
  copie de la région est exécutée par `cs_crop_image` dans CreativeCore, avec
  rejet explicite si le moteur natif n’est pas disponible.
- Un rectangle de recadrage vide ne recopie plus silencieusement l’image source :
  `CropTool` renvoie une image nulle et le canvas annule explicitement l’action.
- Le verrouillage alpha ne possède plus de recopie d’octets Python de secours :
  la restauration rectangulaire et par tuile est exclusivement exécutée par
  CreativeCore et l’édition est refusée si cette primitive manque.
- La restauration des tuiles de masque de sélection ne manipule plus `bits()`
  depuis Python : `cs_copy_image_rect` réalise la copie bornée entre images Qt,
  y compris la conversion de format, avant que l’interface ne réaffiche le masque.
- L’extraction des tuiles lors de la sauvegarde `.nebula` délègue désormais la
  découpe et la conversion RGBA à CreativeCore ; le writer Python ne conserve
  que l’assemblage des métadonnées et le flux binaire.
- La capture des tuiles de snapshots Undo/Redo utilise la même primitive native
  de découpe ; aucune copie de pixels par `QImage.copy()` ne subsiste dans ce
  chemin d’historique.
- `TileStore` ne normalise plus les tuiles deux fois côté Python : conversion de
  format, remplissage transparent, clamp et détection d’une tuile vide restent
  centralisés dans l’implémentation native avant publication.
- Le rendu des objets texte pendant la composition du document et le prélèvement
  couleur passe maintenant par `cs_draw_text` ; Python conserve leurs propriétés
  Qt et délègue la rasterisation de glyphes à CreativeCore.
- À l’ouverture d’un `.nebula`, les tuiles de sélection et de références sont
  maintenant recopiées dans leurs images par `cs_copy_image_rect`, sans
  `QPainter.drawImage()` Python dans le chemin de restauration documentaire.
- Le fallback CPU du canvas ne rasterise plus les textes avec `QPainter` : chaque
  tuile affichée reçoit une copie détachée et un rendu `cs_draw_text` natif avant
  l’application des transformations de vue.
- Ce fallback couvre maintenant aussi les tuiles de projection non résidentes
  lorsqu’un texte doit y apparaître ; le rendu conserve donc la couverture
  complète du document sans perdre les bénéfices du stockage sparse.
- Un test positif vérifie que `cs_draw_text` produit effectivement des pixels,
  en complément du test qui interdit tout fallback Python.
- Smoke test de l’application complète validé le 22 septembre 2026 :
  initialisation CreativeCore, boucle Qt hors écran de dix secondes et fermeture
  propre (`FULL_APP_EXIT 0`). Le lancement Wayland/OpenGL de cette session
  s’arrête avec le code 134 avant toute sortie ; il reste à reproduire avec le
  pilote graphique interactif de la machine cible.
- Un nouveau scénario de bout en bout couvre édition raster, Undo/Redo,
  sauvegarde `.nebula`, fermeture du document et réouverture avec pixels/DPI.
- Un scénario prolongé répète 80 modifications raster, 30 opérations Undo/Redo,
  crée une nouvelle branche après Undo puis sauvegarde/réouvre le document.
- Lancement/stress manuel avec une tablette physique, un pilote OpenGL différent
  et une longue session n’a pas encore été effectué dans cette validation.
- Le curseur de stabilisation agit désormais sur les points du chemin pinceau
  natif C++ : l’ancien filtre de trajectoire est porté dans `BrushEngine`, son
  état est réinitialisé en fin de trait, et l’accélération instanciée est évitée
  uniquement quand ce filtre est activé. Le test natif couvre filtrage et reset;
  un test Canvas confirme aussi que le rendu suit les points stabilisés plutôt
  que l’extrémité brute. La latence sur tablette physique reste à mesurer en
  usage réel.
- L’outil Main ne possède plus de rasteriseur Qt parallèle : son déplacement
  passe exclusivement par la primitive de copie C++ et renvoie un échec sans
  mutation si CreativeCore n’est pas disponible. Les tests vérifient pixels
  intacts et conservation du point de départ lors d’un échec, pour une reprise
  correcte si le moteur redevient disponible.
- Un démarrage/affichage/fermeture Qt hors écran a également été vérifié avec
  le moteur C++ chargé.
- Les boutons réels de la barre d’outils Main et Zoom sont désormais testés à
  travers des événements souris Qt : zoom autour du pointeur, pan à la souris,
  pixels raster invariants et absence de transaction d’historique pour ces
  changements de vue uniquement.
- Les chemins souris et tablette du brush, y compris le tampon clone, ne
  retombent plus sur le rasteriseur Python lorsqu’un dab CreativeCore échoue.
  Le dab est annulé sans mutation et la transaction native est fermée; les
  formes et courbes suivent la même règle. Les tests brush/UI couvrent ce
  comportement avec le moteur actif.
- Le verrou de calque est maintenant testé en matrice souris/stylet pour les
  outils raster exposés (pinceau, gomme, smudge, tampon, filtres, remplissage,
  gradient, formes, recadrage, déplacement, transformation et Bézier). Le
  stylet refuse désormais le début des mêmes mutations raster que la souris;
  les outils de sélection, de prélèvement et de vue restent autorisés.
- L’écrêtage des calques, auparavant seulement mémorisé sans effet dans le
  compositeur, masque maintenant l’alpha des calques concernés sur le calque
  non-écrêté de référence et conserve l’alpha global de la pile. La même règle
  est appliquée par le compositeur C++ asynchrone ; les
  signatures du cache plein canevas, du cache par groupe et de la projection
  par tuile intègrent aussi l’état clipping, pour que le toggle soit visible sans
  invalider artificiellement les pixels. Les tests contrôlent rendu et cache.
- La fusion d’un calque écrêté avec sa base compose désormais le masque avant
  de le supprimer et conserve exactement le résultat visuel. La fusion d’une
  base elle-même écrêtée est refusée sans mutation, car son masque dépend d’un
  calque extérieur à la paire ; deux tests protègent ces comportements.
- La composition plein document (export/aplatissement) compose maintenant les
  groupes comme le canvas : isolation, visibilité, opacité et mode de fusion,
  avec l’état des groupes intégré à la clé du cache. Un test couvre l’alpha du
  groupe, le changement de visibilité après une composition mise en cache et
  l’équivalence pixel après aplatissement.
- « Fusionner les visibles » compose désormais les calques visibles dans le
  calque visible le plus bas, au lieu d’utiliser un calque caché intermédiaire
  comme récepteur. Les états de groupe sont respectés, les couches cachées
  restent intactes et l’historique capture l’union sparse des tuiles modifiées;
  Undo/Redo vérifie pixels visibles et contenu caché conservé. Le compositeur
  accepte une région tuile; un test interdit la matérialisation entière des
  calques. Benchmark `CPP_TEST/benchmark_sparse_merge_visible.py`, toile 4096²,
  quatre calques × deux tuiles 64², médiane de sept runs : 1,030 ms sur ce poste.
- La planification de « Fusionner les visibles » (calque cible, masque de
  conservation, visibilité effective des groupes et nouvel index actif) est
  maintenant une primitive CreativeCore testée en C++; Python fournit les états
  du modèle Qt puis applique le plan aux objets. Si le moteur manque, l’action
  échoue avant mutation au lieu d’exécuter un plan Python parallèle.
- Le regroupement des calques pour la composition d’un document est maintenant
  planifié par CreativeCore; Python ne collecte que les images Qt et les
  propriétés d’affichage des groupes. Le moteur impose des plages contiguës et
  refuse les appartenances multiples ou les groupes disjoints. Cela prévient
  une perte visuelle silencieuse lors de la composition d’un document malformé;
  le plan natif et le rendu des groupes restent couverts par des tests.

### 2. Frontière C++ / interface

- Migrés dans cette tranche : combinaison, inversion, limites et appartenance
  des pixels aux masques de sélection dans CreativeCore ; le modèle Python
  utilise désormais des adaptateurs typés du bridge commun pour ces quatre
  opérations, plutôt que d’appeler directement les symboles ABI.
- La rasterisation des masques rectangle/ellipse/lasso est aussi dans
  CreativeCore ; le suivi des points et l’aperçu restent dans l’interface. Des
  tests comparent pixel à pixel les rendus Qt natif et de compatibilité, avec
  des coordonnées sous-pixel.
- Le rendu raster du dégradé linéaire est maintenant appelé via CreativeCore ;
  un test compare pixel à pixel le rendu natif Qt aux formats ARGB32 et
  RGBA8888. La géométrie du geste reste dans l’interface.
- Le filtre de brosse (lissage/netteté) arrondit maintenant ses pixels comme le
  fallback historique ; une comparaison C++/Python sur un trait sous pression
  au bord du canevas reste à un niveau de canal près.
- Alpha Lock ne duplique plus le canvas complet à l’ouverture d’un stroke ni
  lors d’un remplissage borné par le planificateur natif. La restauration
  d’alpha réutilise les tuiles d’origine capturées par l’historique, avec copie
  du canal alpha par région en C++; seules les tuiles touchées servent de
  baseline. Les workflows natifs vérifient alpha invariant, pixels peints et
  Undo/Redo. Sur un canvas 4096², cela évite la copie RGBA8888 de 64 MiB pour
  un trait local ou un remplissage local.
- L’appel du filtre Canvas passe par le bridge central et réutilise son tampon
  temporaire entre dabs. Benchmark reproductible `CPP_TEST/benchmark_brush_filter.py`
  (lissage, médiane de trois exécutions) : 128², 131,16 ms Python contre
  0,47 ms C++ (×279) ; 256², 270,70 contre 0,92 ms (×293). Mesures locales,
  hors préparation de l’image.
- Le chargement du bridge et les déclarations ABI du pinceau, des presets et
  des outils raster ainsi que des codecs Nebula et Atlas sont centralisés dans
  `CORE/native_bridge.py` ; les adaptateurs ne chargent/configurent plus
  séparément ces symboles.
- La composition standard des calques ne passe plus par une boucle `QPainter`
  Python : les entrées sont validées puis rendues par une nouvelle API C++ batch
  en un seul appel bridge pour les douze modes Qt standards. Les modes
  paramétrés et l’écrêtage utilisent aussi une API batch CreativeCore; le
  ancien compositeur NumPy a été déplacé vers `CPP_TEST/legacy_blend_reference.py`
  et n’est plus présent dans le paquet applicatif. Les tests
  comparent les modes standards à Qt, les modes avancés/clipping à leur
  référence pixel à pixel, et vérifient le refus sans mutation si CreativeCore
  manque. La primitive borne aussi les documents à 268 Mpx et 4 096 entrées
  avant calcul. L’oracle NumPy historique est uniquement conservé dans
  `CPP_TEST/legacy_blend_reference.py` pour les tests et benchmarks ; il n’existe
  plus dans le paquet applicatif et n’est pas sélectionnable par l’UI.
- La fusion descendante des calques ne possède plus de rasteriseur QPainter de
  secours : le lot de composition est préparé par CreativeCore et l’opération
  est refusée avant publication si le moteur natif n’est pas disponible. Un test
  vérifie que la pile et les pixels restent inchangés dans ce cas.
- L'encodage/décodage LZ4 historique `CSLZ` passe maintenant par l'ABI
  CreativeCore ; Python ne charge plus de seconde bibliothèque native pour ce
  codec. Le fallback sans LZ4 écrit du brut, tandis que les blocs LZ4 existants
  restent lisibles quand le support optionnel est compilé. Le lecteur valide
  dimensions, stride, taille attendue et longueur du payload avant allocation.
  La sérialisation complète de l'en-tête (format little-endian inchangé), son
  contrôle strict, le choix brut/LZ4 et le décodage sont désormais aussi dans
  CreativeCore ; l'adaptateur Python ne fait que convertir le buffer validé en
  `QImage`. Les tests de round-trip et de rejet d'en-tête passent.
- Le décodage Atlas (infos document, infos de calque et copie raster) passe
  maintenant par une unique fonction du bridge ; `format_atlas.py` ne manipule
  plus le handle natif et ne fait que reconstruire les objets Qt du document.
  Le bridge refuse aussi les documents dont le volume total de calques
  décodés dépasse 512 MiB avant de copier le premier raster.
- Les handles reader/writer Nebula et l’accès aux buffers de chunks sont
  également encapsulés dans des objets du bridge ; `format_nebula.py` ne déclare
  ni n’appelle plus directement l’ABI `ctypes`. Il conserve la validation
  sémantique des champs du modèle et l’assemblage Qt. CreativeCore valide
  maintenant en plus la grille et les références croisées de toutes les tuiles.
  Le reader réutilise un
  buffer natif pour tous les chunks et le writer un tampon extensible pour ses
  ajouts ; les tests vérifient l’identité des buffers et le contenu transmis.
- La rasterisation affine du calque et du masque de sélection (rotation,
  translation, échelle et extraction selon le masque) est aussi exécutée en C++ ;
  l’interface ne fait que fournir les buffers et paramètres. La déclaration ABI
  et le passage des buffers passent maintenant par `CORE/native_bridge.py`.
  L’implémentation de secours affine pixel-par-pixel a été retirée du code
  applicatif : en l’absence du moteur, l’outil signale explicitement l’erreur
  au lieu de basculer silencieusement sur une seconde logique Python. Une
  référence Qt indépendante reste dans les tests pour vérifier la parité.
- Le déplacement raster entier est maintenant exécuté par une primitive C++
  de copie de lignes avec clipping; `MoveTool` conserve seulement le suivi du
  geste. Les tests vérifient les bords, la transparence et
  les pixels semi-transparents. Benchmark reproductible
  `CPP_TEST/benchmark_move_tool.py`, toile 2048², médiane de cinq exécutions :
  4,233 ms natif contre 4,452 ms Qt sur ce poste; gain modeste, mais la logique
  d’édition est désormais centralisée.
- Remplissage contigu et baguette magique utilisent aussi les adaptateurs du
  bridge central, au lieu de re-déclarer leur ABI dans les outils ; le rendu du
  gradient et les transformations suivent désormais la même frontière.
- Le remplissage contigu ne contient plus de second algorithme scanline Python :
  il charge CreativeCore et refuse explicitement l’opération si le moteur natif
  ou le format d’image n’est pas pris en charge. L’aperçu de région suit la même
  règle ; les tests couvrent région/tolérance, aperçu sans mutation, clic hors
  toile et erreur d’absence du moteur.
- Les outils de sélection rectangle, ellipse, lasso et baguette magique n’ont
  plus de chemins de rasterisation/flood-fill Python dans l’application. Ils
  exigent CreativeCore ; le suivi de pointeur et les points du geste restent
  côté interface. Une référence Qt indépendante compare pixel à pixel les
  formes natives, et les tests vérifient le refus explicite si le moteur manque.
- Le rendu du dégradé n’a plus d’implémentation QPainter de secours dans
  `GradientTool` : une seule logique CreativeCore définit le résultat. Une
  comparaison pixel à pixel avec Qt reste dans les tests, avec un cas qui
  vérifie qu’une panne native ne modifie pas l’image.
- La génération des trajectoires de peinture ligne/rectangle/ellipse est
  maintenant dans CreativeCore ; `ShapeTools` ne fait que convertir les points
  natifs en `QPointF` pour l’interface et le pinceau. Des cas de référence
  vérifient exactement la géométrie précédente, y compris ellipse dégénérée et
  coordonnées fractionnaires, et le test moteur absent vérifie le refus.
- La normalisation/clamp du rectangle de recadrage est maintenant calculée dans
  CreativeCore avec coordonnées entières 64 bits aux frontières, intersection
  inclusive avec les limites du document et résultat vide hors-canevas. Python
  ne fait que construire `QRect` puis déléguer la copie raster à `cs_crop_image`.
  Les tests couvrent le clamp, la région entièrement extérieure et le refus si
  le moteur manque.
- Le modèle `SelectionMask` utilise désormais également les primitives C++ pour
  les opérations booléennes (y compris le remplacement), l’inversion, les
  limites et l’appartenance d’un pixel. Les scans et composites de secours
  Python sont retirés ; l’image Qt et le cache des limites restent des détails
  d’adaptation. Des tests vérifient explicitement l’échec sans moteur natif.
- Le calcul des permutations de déplacement des calques (y compris les blocs
  de groupe et l’indice actif) n’a plus de seconde implémentation dans
  `LayerManager` Python. CreativeCore fournit l’ordre ; Python ne fait que
  réordonner les objets Qt et invalider les caches de groupe. La suite couvre
  les frontières de groupe, les déplacements haut/bas et l’absence du moteur.
- La suppression d’un calque exige maintenant aussi le plan natif de
  permutation/indice actif ; son ancien recalcul Python est retiré. Si
  CreativeCore manque, l’opération échoue avant toute mutation. Les tests
  couvrent le refus sans altération et le maintien des références de groupes.
- Les règles de visibilité, opacité, verrou pixel, alpha lock et clipping ne
  basculent plus sur des toggles/clamps Python si l’API manque : elles refusent
  la mutation avant de toucher au modèle. La logique continue d’être calculée
  dans CreativeCore ; seuls les champs Qt sont ensuite mis à jour.
- La validation des sélections de calques pour créer un groupe n’a plus de
  doublon Python. CreativeCore doit valider contiguïté, plages, doublons et
  membres déjà groupés avant que `Document` ne crée l’objet Qt. Une panne du
  bridge laisse le document sans groupe partiel.
- Le constructeur `Document` ne recalcule plus en Python les limites de
  dimensions, DPI et pixels quand la validation native échoue. Il refuse la
  construction avant allocation ; CreativeCore reste l’unique règle commune,
  avec un test couvrant l’absence du moteur.
- La construction du delta d’un UndoStep envoie maintenant toutes les paires
  de tuiles en un seul appel bridge ; CreativeCore compare les pixels, ignore
  les tuiles identiques, copie celles qui changent et renvoie leurs index. Les
  clés restent dans l’adaptateur Python pour associer tuiles et calques. Le test
  couvre suppression des paires identiques et index corrects après filtrage.
- Les derniers chemins Python de stockage des pixels Undo et de gestion du
  curseur Undo/Redo ont été supprimés : payload et chronologie CreativeCore sont
  obligatoires. Le document échoue explicitement à démarrer son historique si
  le moteur manque ; aucune image Undo n’est retenue dans un dictionnaire
  Python. Les tests vérifient ce refus et les workflows de branchement/Undo.
- Le clipping d’une région de capture et le calcul de sa plage de tuiles sont
  maintenant natifs : CreativeCore valide les dimensions et renvoie les bornes
  demi-ouvertes; `TileHistory` conserve l’itération sur cette plage et la collecte
  des images Qt. Les tests couvrent frontière de tuile, région partiellement
  extérieure, région disjointe et refus si l’API native manque.
- Le stockage résident sparse des tuiles (pixels, révisions, recency, clés et
  octets résidents) est maintenant possédé par `NativeTileStore` en C++ ; Python
  conserve l’adaptateur Qt, le scratch disque, l’éviction asynchrone et les
  callbacks.
- Les appels ABI du stockage tuilé sont maintenant encapsulés dans
  `NativeTileStoreHandle` (`CORE/native_bridge.py`) : l’adaptateur
  `DOCUMENTS/tile_store.py` échange des images Qt et des coordonnées, sans
  manipuler pointeurs, tableaux C ni fonctions `cs_tile_store_*` directement.
  Les tests ciblés puis les suites complètes passent après cette centralisation.
- La restauration Undo/Redo regroupe maintenant les écritures de tuiles par
  calque dans un seul appel bridge `set_tiles_batch`; les deltas par tuile,
  caches et scratch restent gérés par les adaptateurs. Cela supprime une
  traversée Python/C++ par tuile sur les actions d’historique multi-tuiles.
  Les 176 tests Python et 10 tests C++ passent après ce changement. Le benchmark
  reproductible `CPP_TEST/benchmark_tile_store.py`, 256 tuiles de 64², médiane
  de 7 répétitions : 3,229 ms en appels unitaires et 2,968 ms en batch (×1,09
  localement). Le coût reste dominé par la normalisation/copieuse Qt et le scan
  des pixels transparents dans NativeTileStore.
- Le clonage d’un store sparse se fait maintenant en une seule opération C++
  avec partage implicite des QImages (copy-on-write), révisions neuves et
  vérification des dimensions; seules les tuiles scratch sont chargées au
  préalable, puis elles sont ré-évincées dans le store source. Un test confirme
  l’indépendance des deux copies et un autre la préservation du scratch.
- Le calcul de permutation du stack de calques (frontières de groupes et
  nouvel indice actif inclus) est maintenant une primitive CreativeCore testée
  en C++; le gestionnaire Python applique seulement la permutation aux objets
  Qt existants.
- La suppression d’un calque calcule également en C++ l’ordre restant et le
  nouvel index actif ; Python conserve les objets d’interface, l’invalidation
  des groupes et le branchement à l’historique. Les tests couvrent la suppression
  du calque actif, d’un calque avant/après celui-ci, le retrait du dernier membre
  d’un groupe et la voie de compatibilité.
- Les règles des commandes de visibilité, opacité, verrouillage pixel, alpha
  lock et clipping sont maintenant évaluées dans CreativeCore ; les adaptateurs
  de `LayerManager` écrivent ensuite la valeur sur l’objet Qt. L’opacité est
  bornée en natif et les valeurs non finies sont refusées. Les tests natifs
  couvrent chaque règle et un test d’intégration force le bridge compilé.
- La normalisation et la validation du groupement de calques (indices uniques,
  plage valide, sélection contiguë et absence d’appartenance existante) sont
  maintenant une règle CreativeCore. Python fournit les identifiants de groupes
  associés aux objets Qt puis crée le modèle `LayerGroup`; les tests natifs et
  d’intégration couvrent sélections désordonnées/dupliquées, discontinues,
  invalides et déjà groupées.
- La géométrie du document (dimensions bornées, budget pixel calculé en 64 bits
  et DPI valide) est maintenant une règle C++ commune, appelée par le constructeur
  avant l’allocation dense du masque et par les imports/exports CSD et Nebula.
  Les chemins de compatibilité appliquent les mêmes limites si le bridge est
  absent; les tests couvrent bornes, DPI et refus avant construction.
- Les signatures de l’API de projection asynchrone sont déclarées dans le
  bridge partagé ; le worker ne redéfinit plus les types d’appel C++.
- La restauration de l’alpha (Alpha Lock) passe désormais par l’adaptateur du
  bridge pour fournir les buffers et la zone, avec un fallback ligne par ligne
  conservé uniquement si CreativeCore n’est pas disponible.
- La fusion vers le bas traite maintenant les seules tuiles occupées pour les
  modes directs ; les modes paramétrés/HSL parcourent l’union sparse des deux
  calques par tuile et appellent leur compositor natif sur ces images locales.
  Elle ne matérialise plus les canvases entiers. Un test compare les 16 modes
  paramétrés à la référence Python,
  y compris pixels transparents, noir/blanc exacts, opacité et paramètres ; un
  autre couvre la fusion avec un calque HSL inférieur. Le chemin NumPy reste
  uniquement comme compatibilité si le bridge manque.
- Les transactions génériques de dessin ne copient plus les images complètes
  au début et à la fin du geste : elles capturent les tuiles occupées des
  calques et les tuiles sous les limites de sélection, puis comparent leur
  union sparse à la validation. Cela détecte aussi les tuiles nouvelles,
  supprimées ou redimensionnées. Les opérations dirty-only et structurelles
  gardent leur capture ciblée existante.
- Les usages Canvas, gestion mémoire et sérialisation qui lisaient le dictionnaire
  privé des tuiles passent maintenant par l’adaptateur.
- La duplication d’un calque copie maintenant uniquement ses tuiles occupées,
  plutôt que de matérialiser/copier toute la toile; les paramètres de fusion,
  visibilité et verrous sont conservés. Le test couvre une toile sparse de
  512×384. Benchmark reproductible `CPP_TEST/benchmark_sparse_layer_copy.py`
  sur une toile 4096² à une tuile occupée : médiane locale de 5 répétitions,
  0,050 ms pour la copie sparse contre 163,694 ms pour l’ancienne voie image
  complète. Cette mesure dépend du poste et ne couvre pas les calques denses.
- Avant un remplissage natif, CreativeCore calcule maintenant sans mutation la
  région connectée. L’historique capture ses seules tuiles avant modification
  puis enregistre le delta, au lieu de snapshotter aussi toute l’image et la
  sélection. Le chemin de compatibilité garde son ancien comportement; un test
  valide le plan sans effet de bord et un test de workflow vérifie Undo.
- Python conserve les objets Qt miroir et le cache de limites ; le modèle
  structurel natif possède maintenant la création, suppression, sélection,
  ordre, renommage et propriétés des calques, tandis que l’adaptateur passe les
  buffers Qt à l’API native.
- Restent en Python : orchestration et métadonnées d’Undo/Redo (le curseur, la
  comparaison pixel et les images avant/après sont natifs ; la restauration des
  tuiles est batchée),
  géométrie interactive/preview de plusieurs outils et commandes de transformation.
  La règle « Python/PySide6 = présentation » n’est donc pas encore satisfaite.
- La sélection exige désormais les primitives CreativeCore et refuse l’action
  sans modifier le masque si le moteur ou son API manquent; aucun rendu de
  sélection Qt de repli n’est conservé dans le chemin applicatif.

### 3. Fiabilité des fichiers et du scratch

- Les écritures de tuiles scratch publient maintenant un fichier temporaire par
  remplacement atomique ; un échec disque laisse la tuile résidente et conserve
  l’ancien scratch valide.
- Tests ajoutés pour échec d’écriture et échec du remplacement atomique.
- Une écriture partielle n’écrase plus un scratch tronqué par une tuile vide ;
  le document conserve le fichier d’origine afin de permettre un diagnostic ou
  une récupération.
- Une lecture scratch synchrone ne remplace plus un fichier absent, tronqué ou
  de dimensions incohérentes par une tuile transparente : elle lève une erreur
  de stockage explicite et conserve le fichier et l’entrée sparse. Les requêtes
  asynchrones conservent aussi le motif d’échec pour le callback suivant. Le
  décodage PNG vérifie les dimensions avant allocation et la lecture brute est
  strictement bornée; le CSLZ vérifie les dimensions attendues avant allocation.
- Le clonage sparse abandonne maintenant proprement si une tuile scratch source
  est corrompue; l’opération de duplication retire son calque temporaire et ne
  publie aucun calque partiel. Le fichier source reste disponible pour diagnostic.
- Un test de reprise vérifie qu’un autosave Nebula échoué à cause d’un scratch
  corrompu conserve octet pour octet l’instantané de récupération précédent,
  puis que cet instantané reste ouvrable avec ses pixels d’origine.
- Le minuteur d’autosauvegarde diffère maintenant son travail pendant une
  transaction d’édition ouverte : il ne sérialise pas un trait/transform incomplet
  et n’efface pas le dernier instantané parce que l’index Undo n’a pas encore
  avancé. Un test cible ce cas.
- L’écriture d’image vers les tuiles et la matérialisation d’un calque passent
  par des opérations batch natives ; les tuiles évincées sont rechargées avant
  la matérialisation.
- Le scratch PNG est maintenant écrit atomiquement et décodé par CreativeCore ;
  les anciennes tuiles `CSLZ` conservent un chemin de lecture de compatibilité.
- Le test de stress LRU confirme qu’une tuile froide est évincée puis rechargée
  sans perte pixel.
- L’import a maintenant une fixture binaire produite par le véritable
  `AtlasSerializer::save` v3 de CreativeSystem Atlas, puis relue par l’importeur
  CreativeCore/Nebula. Le test vérifie dimensions, DPI, propriétés du calque,
  pixels RGBA et application du masque d’alpha. L’exemple est conservé dans
  `CPP_TEST/atlas_v3_serializer_sample.atlas` avec sa provenance documentée;
  aucun document Atlas utilisateur n’étant disponible, un aller-retour sur un
  fichier de production reste à valider.
- Le lecteur Nebula borne maintenant la surface des images denses avant de
  construire le document ou les images de référence ; des tests confirment le
  rejet de métadonnées surdimensionnées avant toute allocation Qt.
- CreativeCore valide tous les propriétaires, coordonnées et formats de tuile
  contre la grille exacte du document/référence avant de construire le document ;
  les coordonnées négatives et les dimensions de tuile incohérentes sont
  rejetées avant allocation. Python ne conserve ensuite que l’index d’adaptation
  chunk → enregistrement pour remplir les objets Qt.
- La déclaration redondante des tuiles dans le manifeste est maintenant
  recoupée nativement avec chaque enregistrement binaire (unicité, rôle et
  propriétaire). Si CreativeCore est indisponible, le chargement s’arrête avant
  la construction du document au lieu d’utiliser un validateur parallèle.
- Les structures de calques, groupes, textes, couleurs, presets et références
  sont aussi validées en amont par `cs_nebula_validate_manifest` ; les
  coordonnées flottantes non finies et les paramètres mal typés sont rejetés
  avant toute allocation d’image. Le writer réutilise exactement cette
  validation avant publication, et renvoie la géométrie validée au bridge.
- Lorsque les index redondants du manifeste sont présents, CreativeCore recoupe
  leurs listes de tuiles avec les enregistrements binaires, y compris le rôle et
  le propriétaire de chaque tuile ; les divergences sont rejetées en amont.
- Les paramètres de fusion des calques et groupes doivent contenir des valeurs
  numériques finies, pour éviter qu’un document malformé fasse échouer le worker
  de projection au premier rendu.
- L’import CSD borne le manifeste, la surface du document, le volume cumulé des
  calques et les images référencées ; `QImageReader` vérifie dimensions et
  budget avant le décodage raster. Des cas limites confirment le rejet des
  dimensions de canevas et d’images de référence hostiles avant allocation.
- L’import CSD vérifie aussi avant allocation les coordonnées des références,
  la structure des objets texte et les propriétés des groupes ; des manifests
  altérés sont rejetés avant de construire le document.
- L’export Nebula applique maintenant la limite du nombre de tuiles pendant la
  construction des enregistrements, avant d’accumuler un index surdimensionné
  ou d’ouvrir le writer; il refuse aussi les grilles de calques incohérentes et
  les images de référence hors limites. Deux tests garantissent le rejet avant
  création du fichier.

### 4. Cohérence édition / historique

- Les commandes d’ajout, duplication, renommage, suppression, déplacement,
  visibilité, opacité, fusion, aplatissement et verrouillage des calques sont
  maintenant groupées comme transactions undoables sans interrompre une
  transaction de curseur déjà ouverte.
- Les commandes de métadonnées (visibilité, opacité, verrouillage, ordre,
  groupes, renommage et ajout vierge) capturent désormais un état sans pixels ;
  suppression, duplication, fusion et aplatissement conservent les snapshots
  nécessaires à la restauration du contenu.
- Les transactions d’ajout, duplication et suppression de calque n’embarquent
  plus les pixels ni les copies d’images de référence/texte de tout le document.
  La duplication enregistre seulement les tuiles du nouveau calque; la
  suppression capture ses tuiles avant action. Merge-down capture l’union sparse
  des clés des deux calques afin de restaurer aussi les tuiles qui étaient
  absentes du calque cible. Tests couvrent Undo/Redo pixel exact. Benchmark
  reproductible `CPP_TEST/benchmark_layer_history.py` : sur une toile 1024² avec
  cinq calques et 128 tuiles occupées, médiane de 3 répétitions, duplication+
  historique prend 10,247 ms en structural sparse, 12,760 ms en historique
  générique sparse et 27,024 ms sur la référence legacy à snapshots complets.
  Ce sont des mesures locales ; le script exécute explicitement les trois voies.
- Merge-down, merge visible et aplatissement utilisent maintenant aussi les
  deltas structurels quand l’opération est déclenchée par l’application. Les
  récepteurs sauvegardent l’union des clés sparse qui peuvent être écrites, et
  les sources supprimées leurs tuiles d’origine; Undo/Redo des pixels, groupes
  et couches intermédiaires est vérifié par des tests dédiés, y compris des
  appels aux commandes d’application réelles via un adaptateur de test.
- Le déplacement group-aware des calques est vérifié sur le chemin C++ natif,
  sans recours au chemin Python de compatibilité, et reste undoable.
- Sélectionner tout, inverser et désélectionner enregistrent uniquement le
  masque dans l’historique, sans snapshotter les pixels des calques.
- Les formes de sélection souris ouvrent maintenant une transaction au début
  du geste et la valident à la fin ; Échap annule le geste proprement. Les
  raccourcis Ctrl+A/Ctrl+D/Ctrl+I passent aussi par des transactions masque-seul.
  Des tests UI vérifient Undo/Redo, la non-capture des pixels calque et
  l’annulation d’un geste en cours. Cela corrigeait une absence d’historique
  dans ces chemins interactifs.
- Le flux tablette est désormais aligné sur celui de la souris pour les formes
  (dont le lasso) et la baguette magique ; tests de geste stylet, annulation
  Undo/Redo et transaction unique.
- Formes de peinture, gradient et recadrage prennent aussi en charge les phases
  tablette press/move/release. Échap restaure les images preview pour les
  formes/gradients avant d’annuler la transaction. Les tests vérifient
  sauvegarde Undo/Redo et restauration du document.
- Le remplissage tablette utilise le même outil CreativeCore que la souris,
  avec transaction Undo et respect du verrou de calque ; test UI du pixel
  modifié, de l’annulation et du refus sur calque verrouillé.
- La restauration explicite d’une tuile absente efface désormais la tuile
  courante ; un test vérifie le cycle Undo/Redo sparse.
- La politique du curseur d’historique (branche après Undo, limites, index,
  Undo/Redo) est maintenant une classe CreativeCore C++ exposée par le bridge.
  Les images avant/après des deltas raster sont aussi copiées et possédées par
  `HistoryPayload` en C++; son opérateur natif compare les paires avant/après
  et ne stocke que les deltas réellement modifiés. Python ne garde que les clés
  d'indexation et les métadonnées document. Le bridge restitue les images à la demande, le memory
  manager lit leur coût natif et le spill zip les encode une par une. CTest
  vérifie l'indépendance des copies et les tuiles absentes; 10/10 C++ passent.
- `TileHistory` traite maintenant le compte, le curseur, la troncature de branche
  et la limite renvoyés par le curseur natif comme source de vérité ; Python ne
  fait que supprimer les métadonnées/archives scratch correspondantes. Les
  clamps redondants ont été retirés et toute divergence entre liste Python et
  timeline C++ est signalée au lieu de laisser Undo/Redo continuer sur un état
  incohérent. Des tests couvrent branche après Undo, dépassement de capacité et
  divergence injectée.
- Le même curseur CreativeCore possède maintenant l’état et le mode de la
  transaction d’édition : il choisit la priorité sélection > structure > geste
  local > générale, refuse les débuts imbriqués et gère commit/annulation/reset.
  Undo/Redo, append et synchronisation externe sont refusés tant que l’édition
  est ouverte. `TileHistory` conserve les snapshots Qt comme payload d’adaptation,
  mais suit le mode natif unique, vérifie l’état miroir et annule proprement si
  la capture initiale échoue. Tests C++ et Python couvrent le cycle, les modes
  mixtes, l’échec de capture et les opérations incompatibles.
- Les transactions raster/dirty et sélection n’incluent plus les snapshots des
  images de référence ni des objets texte, qu’elles ne modifient pas. Les
  transactions structurelles continuent de les exclure; seuls les workflows
  généraux, susceptibles de modifier ces objets, les capturent pour Undo/Redo.
  Cela évite leur copie et comparaison pendant les gestes raster; un test vérifie
  l’absence des copies et la conservation des objets au Undo.
- Les scopes Undo raster/dirty et sélection ne sérialisent plus les métadonnées
  de toute la pile : leurs snapshots contiennent uniquement le scope et les
  dimensions nécessaires. Replay restaure les tuiles sur les mêmes objets
  `Layer`/`LayerGroup`, sans recréer le modèle document; les modes structure et
  général gardent leur restauration complète. Les tests vérifient l’identité des
  calques/groupes et les pixels de masque après Undo/Redo.
  `benchmark_history_snapshot_modes.py`,
  médiane de neuf captures sur 128 calques 128×96 : 0,0018 ms dirty contre
  0,7231 ms structure (×401,72 sur ce poste); ce benchmark isole la capture de
  métadonnées, pas un trait complet ni la latence UI.
- Undo/Redo des tuiles de calque résidentes applique maintenant directement le
  côté avant/après `HistoryPayload` au `NativeTileStore` via un batch C++ : les
  images raster ne retraversent plus Python lors de ces restaurations. Les
  sélections, payloads déportés sur disque et configurations sans store natif
  conservent leur chemin d’adaptation; les tests d’historique couvrent les
  tuiles absentes, gestes, opérations structurelles, branchement et spill.
- Le même invariant est maintenant appliqué aux tuiles absentes du masque de
  sélection : Undo/Redo efface ou restaure la région au lieu de conserver des
  pixels de sélection périmés.
- Les snapshots structurels de `TileHistory` sont maintenant validés par
  CreativeCore avant capture et avant restauration : géométrie historique,
  identifiants
  uniques, formats, opacités, paramètres de fusion et groupes contigus sont
  contrôlés nativement. Une absence du validateur ou un état incohérent annule
  la transaction sans laisser le curseur ouvert; Python conserve seulement le
  payload d’adaptation et la reconstruction Qt.
- La suppression d’un calque conserve maintenant le calque actif lorsqu’un
  élément inférieur est retiré ; fusion et aplatissement nettoient les
  références/caches de groupes pour éviter les identifiants orphelins. Ces
  mutations sont aussi vérifiées en Undo/Redo.
- Les matrices automatisées souris/stylet couvrent les outils raster sous
  verrou, Alpha Lock et maintenant clipping/fusion; cela ne remplace pas encore
  l’audit manuel complet de chaque outil et de chaque geste contre la V1.
- Les nouvelles primitives natives de sélection passent par les mêmes chemins
  de test fonctionnels que les opérations booléennes et les transformations.
- L’application d’un lot de tuiles et les deltas natifs Undo/Redo sont maintenant
  préparés avant publication puis validés atomiquement par calque. Une tuile
  invalide ou une erreur de préparation ne laisse plus les premières tuiles du
  lot appliquées. Le test C++ vérifie que pixels et occupation restent inchangés
  après rejet d’un lot invalide.
- La restauration d’un delta Undo/Redo résident qui touche plusieurs calques
  est maintenant soumise en un seul lot atomique CreativeCore : tous les
  TileStore sont verrouillés dans un ordre stable, leurs résultats préparés puis
  publiés ensemble. Un lot invalide sur le second calque laisse aussi le premier
  intact; un cas de test couvre le rejet et un autre la réussite. Les clés
  absentes du document (par exemple après une mutation structurelle) sont
  ignorées comme auparavant; la gestion du scratch disque et les métadonnées de
  chronologie demeurent orchestrées côté Python.
- Le nettoyage des appartenances de groupes après suppression, fusion descendante
  et fusion visible est maintenant planifié par CreativeCore. Le plan produit
  les groupes à conserver et les memberships des calques survivants avant la
  mutation; Python applique seulement ce résultat aux objets Qt. Les groupes
  devenus vides sont invalidés et leurs identifiants vidés, avec couverture
  Undo/Redo et suppression du dernier membre.

### 5. Mesure des performances

- Benchmark reproductible `CPP_TEST/benchmark_layer_composition.py`, canevas
  768², cinq calques, médiane de neuf répétitions : référence Qt 9,094 ms,
  nouvelle API C++ batch + bridge 8,661 ms (≈×1,05 localement). Les pixels
  échantillonnés concordent; le gain est négligeable, donc cette migration est
  retenue pour centraliser le moteur et réduire les appels de frontière, pas
  comme optimisation mesurée. Mesure hors projection UI.
- Recheck du 22 septembre 2026 sur le même scénario : référence Qt 7,348 ms,
  CreativeCore batch + bridge 7,886 ms (0,93×). Cette variation confirme que
  cette frontière ne doit pas être vendue comme un gain universel ; elle reste
  justifiée par l’unicité du moteur et la suppression du chemin raster divergent.
- Benchmark reproductible `CPP_TEST/benchmark_brush_smoothing.py`, 5 000 points
  d’entrée, force 0,72, médiane de neuf répétitions : filtre natif avec la
  frontière `ctypes` 8,784 ms (1,757 µs/point), ancien filtre Python 35,790 ms
  (7,158 µs/point), soit ×4,07 sur ce poste. Cette mesure isole le filtrage et
  n’inclut ni rasterisation du trait, ni livraison tablette, ni rendu UI.
- Baseline brush 800 × 600, médiane CPU C++ via ctypes (7 répétitions) : trait
  dense 17,223 ms ; diagonale moyenne 14,178 ms ; ligne large douce 42,500 ms.
- Projection 32 tuiles × 5 calques, trois répétitions : environ 9,4–10,0 ms
  en soumission unitaire selon le nombre de threads et 11,1–11,3 ms en batch.
  Le batch réduit le temps de soumission Python, mais n’améliore pas le temps
  total sur ce petit lot ; ne pas extrapoler cette mesure aux grandes toiles.
- TileStore, mesure de suivi via `CPP_TEST/benchmark_tile_store.py` (médiane de
  cinq répétitions) : 256 couples set/copy coûtent **7,857 ms** en natif ; le
  pipeline 1024² write+materialize coûte **2,037 ms**. La restauration de 256
  tuiles coûte **1,903 ms** en batch contre **2,125 ms** en appels unitaires.
  Le benchmark ne compare plus un fallback Python supprimé.
- Benchmark reproductible `CPP_TEST/benchmark_history_payload_batch.py`, 256
  paires de tuiles 64², ordre alterné, médiane de sept répétitions : insertion
  individuelle 7,338 ms, insertion native en lot 7,466 ms (×0,98 sur cette
  mesure locale). Le lot réduit les appels ABI, mais le coût des copies d’images
  et du conditionnement `ctypes` domine ici ; aucune accélération stable n’est
  revendiquée.
- Recheck du 22 septembre 2026 : insertion individuelle 6,628 ms contre
  insertion native en lot 6,617 ms. Le résultat reste statistiquement équivalent
  et confirme le choix d’atomicité/cohérence plutôt qu’une promesse de vitesse.
- Transformation d’une sélection 768² sur une toile 1024², médiane de cinq
  exécutions : 13,15 ms en C++ contre 1907,77 ms sur le chemin de compatibilité
  pixel-par-pixel (×145 sur ce poste). La mesure comprend les copies QImage et
  n’est pas un engagement de performance sur d’autres systèmes.
- Rasterisation des formes de sélection (`CPP_TEST/benchmark_selection_shapes.py`,
  médiane de 9 mesures alternées après deux échauffements, 1024 sommets pour le
  lasso) : sur 1024², natif et compatibilité varient selon les formes et les
  exécutions (environ 0,8–1,6 ms chacun) ; sur 2048² les deux chemins sont
  proches (environ 3,0–4,1 ms). Cette frontière centralise le rendu en C++, mais
  le benchmark ne montre pas encore de gain stable ; ces mesures locales
  servent de garde-fou et non de promesse.
- Remplissage connecté uniforme, médiane de trois répétitions : 128² passe de
  141,08 ms en compatibilité à 0,296 ms en CreativeCore (×476) ; 256² passe de
  551,39 ms à 1,067 ms (×517). Cette différence expose le coût des points de
  frontière du fallback Python ; seul le chemin C++ est adapté aux grandes
  régions. Mesure locale, hors création de l’image.
- Fusion paramétrée de deux calques Soft Light, benchmark reproductible dans
  `CPP_TEST/benchmark_blend_merge.py`, médiane de cinq répétitions : 256²,
  16,739 ms Python contre 1,092 ms C++ batch (×15,32) ; 512², 75,476 contre
  7,640 ms (×9,88). Les temps natifs incluent normalisation des images et
  appel bridge; mesures locales, hors préparation du document.
- Fusion sparse vers le bas, benchmark reproductible
  `CPP_TEST/benchmark_sparse_merge_down.py`, toile 2048² avec deux tuiles 64²
  occupées, médiane de cinq répétitions : 0,220 ms par fusion tuilée contre
  49,399 ms pour matérialiser et composer les deux canvases entiers (×224,36
  localement). Le scénario est volontairement sparse et ne prédit pas les
  performances d’un document dense.
- Ce sont des baselines locales, pas une preuve de performance universelle.
  Restent à mesurer le chemin UI complet, les grands lots, mémoire/scratch sous
  pression, transferts GPU et temps de stroke avec capture Undo.
- Calibration du plan de tuiles sur toile 4096² (4 096 clés, médiane de
  15 passages) : boucle Python de référence 0,145 ms; plan natif puis itération
  Python 0,235 ms. Un essai copiant les 4 096 paires depuis C++ prenait 0,890 ms
  à cause du pont et de la création des objets Python; cette variante a été
  écartée. Le calcul natif centralise donc la règle géométrique, sans gain de
  performance revendiqué.
- Atlas de textures natif, benchmark reproductible
  `CPP_TEST/benchmark_texture_atlas.py` : 256 régions RGBA 32×32, médiane de
  sept passages à 3,789 ms, soit 14,801 µs par région sur ce poste. Cette
  mesure couvre l’allocation native, la copie RGBA et la frontière ctypes,
  mais pas le transfert GPU réel.

## Suite recommandée

1. Continuer à faire posséder par CreativeCore le cycle de vie des transactions
   et l’orchestration finale de l’édition; les métadonnées de session et
   l’application Undo/Redo restent encore principalement dans `TileHistory`
   Python.
2. Tester scratch plein/illisible, un document Atlas utilisateur si disponible,
   les aller-retour et la récupération après interruption.
3. Mesurer le chemin UI complet, grands lots, mémoire/scratch sous pression,
   transferts GPU et temps de stroke avec capture Undo.
4. Achever l’audit fonctionnel outil par outil contre les workflows de référence
   V1, puis retirer les chemins legacy/fallback seulement après parité vérifiée.
