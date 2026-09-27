# Audit architecture — tuiles, projection, scratch et cache

Date : 16 septembre 2026. Cet audit décrit l’état du dépôt avant les corrections
de cette passe et sert de plan d’implémentation.

## État observé

### Mémoire du canvas et pinceau

- `Document.layers` est une liste plate de `Layer`.
- Un calque possède maintenant un `TileStore` creux en 64 × 64, mais les outils
  Python, l’historique et CreativeCore accèdent encore à `layer.image`, une
  `QImage` complète matérialisée à la demande.
- L’API C++ de stroke reçoit un pointeur RGBA contigu, largeur, hauteur et
  stride. Elle ne reçoit ni origine de tuile ni accès paginé. Ce chemin conserve
  une image complète pendant le stroke ; le stockage tuilé réduit surtout la
  RAM au repos et les transferts GPU.
- `TileHistory` enregistre des deltas, mais avant cette passe ses captures
  dirty-only lisaient les vues `QImage` complètes. Les deltas devaient être
  alignés sur les tuiles du renderer (64 px).

### Rendu et composition — état et port natif

- `Canvas.paintGL` affiche les calques normaux en textures OpenGL. Le renderer
  calcule le rectangle visible, puis dessine les tuiles correspondantes.
- Avant le port, les modes non normaux passaient par
  `Canvas._ensure_projection` → `ProjectionWorker._drain` →
  `DOCUMENTS.blend_modes.composite_layers`. Les modes paramétrés composaient
  des tableaux NumPy ; les autres utilisaient `QPainter`.
- La projection est mise en cache par tuile, mais le worker ne gère pas encore
  de transaction de stroke complète, de modèle de groupes, ni de cache de
  préfixes par calque. Le chemin normal GPU reste conservé pour la latence.
- `DOCUMENTS.blend_modes.composite_document` possède aussi un LRU d’images
  pleine taille. Il sert aux exports/miniatures et à des consommateurs
  historiques. Ce cache duplique la finalité de la projection pour l’UI et peut
  coûter jusqu’à 256 Mio.

Réponses opérationnelles :

- La composition pixel actuelle est dans `DOCUMENTS/blend_modes.py` : les modes
  Qt normaux composent via `QPainter`; les modes paramétrés lisent des tableaux
  NumPy région par région. L’UI appelait auparavant `composite_document` en
  synchronie ; la projection des blends passe maintenant par le worker pour les
  tuiles visibles. La fusion destructive et la miniature CSD restent des
  opérations ponctuelles en pleine image.
- L’UI capture des `QImage` indépendantes sur son thread, le worker ne touche
  qu’à ces snapshots CPU, puis un signal Qt ramène chaque résultat. Texture,
  FBO, création/destruction GL et `update()` du widget sont réservés au thread UI
  avec le contexte courant.
- Une modification pixel incrémente la révision de la tuile. Le cache de
  projection combine ces révisions avec visibilité, ordre, opacité, blend mode
  et ses paramètres. Un slider modifie donc les sorties visibles concernées ;
  le worker remplace les jobs en attente pour une même tuile et le canvas rejette
  les réponses d’une génération dépassée.
- La composition respecte toute la pile pour chaque tuile. Le raccourci « calque
  actif et deux voisins » n’est pas correct en général : alpha, clipping et les
  blends non commutatifs imposent de recomposer les calques sous-jacents jusqu’à
  la tuile de sortie. L’actif peut être réutilisé pour préserver sa texture
  source, mais pas omettre les dépendances.

### Audit du thread de projection demandé

- `Canvas.paintGL()` appelle `_ensure_projection()` pour les calques non normaux.
  Il n’y a pas de nombre fixe de compositions par stroke : chaque passage de
  rendu envoie uniquement les tuiles visibles dont la signature a changé. Les
  demandes en attente de la même tuile sont coalescées.
- L’ancien chemin ne faisait aucun appel ctypes de composition par frame : tout
  le travail était en Python/PySide6. CreativeCore ne possédait pas de
  compositeur de calques ; `BrushPaint::blendPixel` ne sert qu’au pinceau.
- `CORE/projection_worker.py` appelle maintenant `cs_projection_invalidate()`
  une fois par tuile et transmet un snapshot RGBA immuable de toute la pile pour
  cette tuile. La queue et la composition sont natives C++ ; un callback renvoie
  l’image CPU. Les jobs en attente se remplacent par tuile, et le canvas rejette
  les résultats de génération périmée.
- Les paramètres sliders traversent ctypes dans un tableau fixe de onze
  flottants par calque. Un test d’intégration compare les 16 modes à la référence
  Python. Les shaders GLSL du preview sont liés à leur widget/contexte et ne
  composent pas la pile ; le worker ne les réutilise pas.
- Le worker ne crée pas de texture OpenGL. Il retourne une `QImage`, ensuite
  consommée par Qt sur le thread UI, car aucun contexte GL partagé n’existe pour
  le worker. L’image précédente reste affichée jusqu’à l’arrivée du nouveau
  résultat, ce qui fournit un double tampon au niveau des tuiles.
- Undo/Redo restent synchrones ; un Undo pendant une transaction ouverte est
  différé jusqu’à sa clôture. Les tâches déjà lancées ne lisent que des snapshots
  copiés et leurs réponses sont invalidées après restauration. Les tuiles scratch
  sont chargées avant d’être envoyées au compositeur.
- Mesure Release/OpenMP sur cinq calques paramétrés, trajet natif incluant
  snapshots, queue et callback : 64 × 64 **4,70 ms → 0,32 ms (×14,6)**,
  128 × 128 **17,45 ms → 1,00 ms (×17,5)**, 256 × 256
  **67,23 ms → 3,83 ms (×17,5)** contre `composite_layers()`. Mesures médianes
  locales, sans rendu écran ; les performances varient avec le processeur.
  OpenMP est optionnel dans CMake : les builds sans OpenMP gardent le thread
  natif correct, mais pas cette accélération mesurée.

### Scratch et undo

- Le scratch stocke actuellement une tuile en PNG lossless, ce qui est simple,
  compact et testable. Les deltas undo sont déjà compressés séparément en ZIP
  avec des PNG par delta.
- Les écritures de tuiles et d’undo sont envoyées à un worker. La restauration
  d’une tuile se fait à la demande, mais le décodage PNG et la lecture disque
  sont synchrones au moment de la première demande.
- Le chemin scratch est configurable dans Performance. L’ancienne éviction
  parcourait les calques dans leur ordre et ne tenait pas compte des tuiles
  swappées comme présentes ; elle n’était donc pas un vrai LRU opérationnel.

## Doublons et choix de conservation

| Besoin | Mécanismes présents | Choix |
|---|---|---|
| Composite UI | LRU pleine image dans `blend_modes.py` et projection tuilée | Garder la projection tuilée pour l’affichage et la sélection de couleur quand elle est prête. Garder le composite pleine image uniquement pour export, thumbnail, fusion destructive et compatibilité. Le cache pleine image est conservé petit et évictable. |
| Historique disque | Deltas par tuiles en ZIP et scratch des pixels courants en PNG | Garder les deux : le premier est une transaction undo/redo immuable ; le second est un cache évictable de pixels courants. Ne jamais faire pointer l’undo vers une tuile scratch mutable. |
| Texture | Ancien cache texture plein-calque et textures par tuile | Garder les textures par tuile ; garder le chemin plein-calque uniquement comme compatibilité pour objets sans `TileStore`. |
| Buffer pinceau | `QImage` pleine et stockage tuilé | Garder le buffer plein uniquement comme adaptateur C++ actuel. Le remplacer après ajout d’une API C++ par tuile ; ne pas recopier l’engine au complet en Python. |

## Ordre recommandé

1. **Système de tiles — M/L.** Stabiliser `TileStore`, les révisions, les
   captures undo, les mutations legacy et le renderer 64 px. Le C++ reste
   momentanément derrière l’adaptateur pleine image.
2. **Thread de projection — L.** Capturer des snapshots immuables des tuiles sur
   l’UI, coalescer les jobs dans un worker CPU, rejeter les résultats périmés et
   remettre les résultats par signaux. GL reste exclusivement sur l’UI. Un
   stroke est validé par le mécanisme Undo existant, puis les révisions de ses
   tuiles déclenchent la projection.
3. **Cache composite — L/XL.** Garder un cache de sortie par tuile et une
   signature par calque/tuiles. Les changements de calque invalident la tuile
   correspondante et les sorties dépendantes au-dessus dans l’ordre de pile.
   Quand les groupes seront introduits, ils auront chacun un cache enfant
   versionné. Ne pas appliquer la règle « calque actif + deux voisins » à
   l’aveugle : alpha, clipping et modes non commutatifs peuvent dépendre de toute
   la pile sous-jacente.
4. **Scratch disk — M.** Évincer les tuiles CPU hors viewport selon LRU,
   privilégier les calques inactifs, écrire sans bloquer l’UI, vérifier la
   révision avant libération et recharger à la demande. Les snapshots undo restent
   autonomes et ne sont pas évincés avec les pixels vivants.

La dépendance stricte est **Tiles → Scratch**. La projection et son cache
dépendent également de tuiles stables ; le scratch peut être raccordé après le
cache. Les groupes sont un chantier de modèle de document distinct : ils
impliquent `document.py`, le dock calques, le format CSD, l’undo et la
composition ; il ne faut pas simuler un groupe avec une simple liste de calques.

## Fichiers concernés et rôle

| Fichier | Rôle / changement |
|---|---|
| `DOCUMENTS/tile_store.py` | Stockage sparse, dimensions de bord, révisions, accès/présence LRU, swap et rechargement. |
| `DOCUMENTS/layer.py` | Source tuilée autoritaire et adaptateur `QImage` temporaire ; notifications de pixels modifiés. |
| `DOCUMENTS/document.py` | Dimensions, ordre de pile et futur arbre de calques/groupes. |
| `CANVAS/tile_history.py` | Capture/restauration de deltas 64 px sans matérialiser le calque pour les actions dirty-only. |
| `CANVAS/canvas.py` | Transaction stroke, flush des écritures C++, projection asynchrone, aperçu du dernier résultat. |
| `CANVAS/gpu_renderer.py` | Texture par tuile, viewport, LRU GPU, contexte OpenGL UI uniquement. |
| `CORE/projection_worker.py` | Coalescence, snapshots, composition CPU et validation des résultats. |
| `CPP_CORE/src/projection_engine.cpp`, `CPP_CORE/src/projection_engine.h` | File native, snapshots et composition pixel asynchrone par tuile. |
| `CPP_CORE/include/creative_core_api.h`, `CPP_CORE/src/creative_core_api.cpp` | ABI ctypes de démarrage, arrêt, invalidation et callback. |
| `CPP_TEST/test_projection_engine.cpp`, `CPP_TEST/test_native_projection.py` | File C++ et équivalence des 16 modes native/Python. |
| `CORE/memory_manager.py` | Comptage, politique LRU hors viewport, swap worker et récupération à la demande. |
| `DOCUMENTS/blend_modes.py` | Composite régional/compatibilité et signatures des paramètres ; conserver la voie full-frame seulement pour opérations ponctuelles. |
| `UI/dialogs/preferences_dialog.py`, `UI/ui.py` | Dossier scratch et limite mémoire. |
| `UI/docks/layers_dock.py`, `UI/widgets/blend_preview.py` | Mutations de métadonnées, invalidation locale et feedback sliders. |
| `DOCUMENTS/format_csd.py`, `CANVAS/tile_history.py` | À modifier lors de l’introduction persistante des groupes ou d’un format de tiles sérialisé. |
| `CPP_CORE/include/creative_core_api.h`, `CPP_CORE/src/creative_core_api.cpp`, `CPP_CORE/src/brush_engine.cpp` | Ajouter plus tard origine/limites de tuile, halo de pinceau, annulation et stroke transactionnel sans exiger un buffer canvas complet. |
| `CPP_TEST/test_tile_store.py`, `CPP_TEST/test_tile_history.py`, `CPP_TEST/test_blend_modes.py` | Équivalence, bords, dirty rect, LRU/scratch, annulation et rendu périmé. |

## Risques à valider

- Une tuile de pinceau doit inclure un halo suffisant pour le rayon, le jitter,
  le blur et le smudge ; sinon les bords de tuile produisent des coutures.
- Les shaders/texture filtering peuvent faire apparaître des coutures entre
  textures indépendantes ; tester zooms fractionnaires et DPR élevé.
- Un résultat worker ancien ne doit jamais écraser une tuile plus récente ; les
  numéros de génération seuls ne suffisent pas si plusieurs révisions coexistent.
- Un changement de visibilité, opacité, ordre, blend mode, clipping ou texte doit
  invalider précisément toutes les tuiles affectées.
- Le scratch n’est pas une sauvegarde. Le CSD et la récupération crash restent
  propriétaires des données durables.
- Aucun objet OpenGL ne doit être créé, utilisé ou détruit hors du contexte UI
  courant.

## Complexité relative

| Système | Complexité | État initial |
|---|---:|---|
| Tiles | L | Partiellement présent ; compatibilité C++ pleine image et undo à corriger. |
| Thread de projection | L | Présent seulement pour la voie blend CPU ; transactions de stroke non asynchrones. |
| Scratch disk | M | Présent partiellement ; LRU et présence/rechargement renderer incorrects. |
| Cache composite | L/XL | Projection par tuile présente ; cache full-frame dupliqué et groupes absents. |

## Implémentation appliquée après l’audit

- `TileStore` sait maintenant considérer les tuiles scratch comme présentes,
  exposer leurs clés occupées, suivre les accès, recharger les pixels sur worker
  et restituer un composite à partir des tuiles en mémoire ou swappées.
- `CanvasGPURenderer` demande le chargement asynchrone d’une tuile scratch et
  crée sa texture uniquement après retour dans le thread UI.
- `Canvas` limite les projections aux tuiles du viewport, rejette les réponses
  périmées par tuile et ne fait plus composer une image pleine lors du sampling
  d’une couleur en mode blend.
- Le picker lit maintenant le pixel directement dans sa tuile en mode normal
  comme en mode blend ; si cette tuile est swappée, il attend son chargement
  asynchrone avant de reprendre le prélèvement. Il ne matérialise plus toute
  l’image du calque et ne bloque plus sur une lecture scratch.
- `TileHistory` capture et restaure les pixels dirty-only directement depuis
  `TileStore`. Les snapshots structurels historiques restent disponibles.
- `MemoryManager` évince la tuile résidente hors écran la moins récemment
  utilisée, en préservant le calque actif pendant un stroke. Il comptabilise
  également le cache de projection et élimine les composites hors viewport sous
  pression mémoire.
- Le LRU pleine image de `blend_modes.py` est conservé à un élément et 64 Mio
  pour les exports et appels de compatibilité ; il n’est plus le cache rendu du
  canvas.
- Vérification après modifications : **89 tests Python**, **2 tests C++ CTest**,
  compilation Python et création/fermeture du canvas natif avec Qt offscreen.
  Le lancement graphique Wayland de cette session a avorté pendant
  l’initialisation de `QApplication`, avant la création du canvas.

### Limites qui restent ouvertes

- Les pixels de sélection sont encore une image pleine ; leur migration en
  tuiles doit couvrir les outils de sélection et le format CSD.
- CreativeCore reçoit toujours un pointeur pleine image. Le cache du calque
  actif reste matérialisé pendant le stroke pour éviter une conversion par
  événement ; certaines opérations historiques hors stroke matérialisent encore
  le calque entier.
- L’annulation Undo et le calcul C++ d’un stroke ne sont pas encore exécutés
  comme une transaction de travail asynchrone ; seule la projection l’est.
- Les groupes de calques sont maintenant pris en charge par `Document`,
  `LayersDock`, CSD et Undo. Ils sont contigus et non imbriqués ; leur affichage
  reste compatible avec la liste plate existante. Le cache isolé est par tuile.
- Les lectures scratch sont asynchrones pour le rendu, la projection et le
  picker ; les autres consommateurs historiques qui demandent directement
  `layer.image` peuvent encore charger synchroniquement toutes les tuiles du
  calque.

### Compléments réalisés le 16 septembre 2026

- Le réglage `cpu/threads` est transmis au thread de projection natif et appliqué
  à OpenMP par tâche. Une valeur de préférence invalide revient à « Automatic ».
- `cpu/cache_mb` borne le cache des composites pleine image ; il ne représente
  pas un quota mémoire de toutes les allocations CPU. Le gestionnaire RAM reste
  responsable des tuiles, de l'historique et de l'éviction.
- La préférence de taille de tuile a été retirée des réglages éditables : le
  store, le rendu, la projection et Undo partagent actuellement la constante
  64 px. Faire varier cette taille sans migrer ensemble ces composants
  désalignerait les rectangles sales et les deltas historiques.
- Le chemin stylet répétait une copie pleine image : `paintGL()` libérait le
  cache du calque après chaque update, puis la prochaine lecture le
  rematérialisait ; les branches C++ réassignaient ensuite le buffer converti
  via le setter `Layer.image`, qui réécrivait le canvas dans les tuiles. Le
  buffer RGBA est désormais adopté comme cache mutable au début du stroke,
  conservé pendant les repaints et synchronisé par rectangle sale seulement.
  Le test de régression exécute 30 segments, constate zéro matérialisation
  supplémentaire, puis vérifie Undo/Redo pixel par pixel.
- Les icônes du rail suivent le réglage `interface/icon_size`; le clic droit
  peut prélever le composite selon `input/right_click_color_picker` (le clic
  droit reste réservé au zoom arrière dans l'outil Zoom).
- Compilation Release et suites automatisées après ces changements : build
  natif réussi, **89 tests Python** et **2 tests CTest** réussis. Le test
  graphique Wayland n'a pas dépassé l'initialisation Qt de la session ; aucune
  conclusion de stabilité GPU prolongée n'en est tirée.

### Compléments validés le 16 septembre 2026

- Le buffer QImage du calque actif reste maintenant en cache pendant tout le
  stroke. Les segments C++ évitent la réécriture pleine image dans le TileStore
  et ne synchronisent que le dirty rect. Le test de régression passe 30
  segments sans matérialisation supplémentaire et vérifie Undo/Redo. Un
  benchmark CPU local avec canvas 2048², pinceau 24 px et 300 segments a mesuré
  0,126 s au total, soit 0,42 ms par segment, synchronisation des tuiles
  comprise ; cette mesure synthétique ne décrit pas la latence d’une tablette
  physique.
- Les groupes contigus ont maintenant opacité, visibilité, composition isolée,
  cache de tuiles et conservation CSD/Undo. Des tests couvrent aussi ordre des
  calques, duplication, suppression et déplacement de groupes.
- `tablet/ignore_mouse_after_tablet` filtre les événements souris synthétiques
  durant 120 ms après un événement tablette. Le test vérifie ce filtre, son
  option de désactivation et le passage des événements souris natifs.
- Vérification finale : **95 tests Python**, **2/2 tests CTest**, `compileall`
  et démarrage/arrêt complet avec Wayland/OpenGL (code 0). C’est un smoke test,
  pas un essai longue durée.

### Points toujours ouverts

- La préférence de langue n’est pas appliquée à une couche de traduction ; les
  profils couleur P3/Adobe RGB et leur export ICC ne sont pas pris en charge.
  Les réglages de brush sont maintenant mémorisés par outil via QSettings.
- Le blend paramétré à l’écran reste en fallback CPU, les strokes restent
  synchrones et les textures sont transférées sur le thread UI. Le worker natif
  de projection ne crée pas de texture dans un contexte partagé.
- Un soak test interactif avec tablette réelle et un test prolongé multi-OS
  restent à effectuer.
