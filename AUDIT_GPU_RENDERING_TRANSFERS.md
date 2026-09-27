# Audit rendu instancié et transferts GPU

## 1. Rendu instancié des stamps

### Architecture observée

Un dab n'est pas envoyé à OpenGL. `CPP_CORE/src/brush_engine.cpp` crée le masque du dab, puis mélange ses pixels directement dans le `QImage` du calque. `CANVAS/canvas.py` invalide ensuite l'image et les tuiles touchées. `CANVAS/gpu_renderer.py` téléverse ces pixels dans des textures et affiche les textures avec `QOpenGLTextureBlitter`.

Il n'y a donc actuellement **aucun drawcall OpenGL par stamp**. Le coût d'affichage est plutôt un blit par tuile visible et par calque. Mesure du smoke test sur le document de démarrage : 130 textures/tuiles initiales, 1 920 000 octets téléversés ; 520 à 780 blits comptés pendant 4 à 6 frames. Ce nombre varie avec le nombre de frames et de tuiles visibles.

### Option d'architecture pour de vrais stamps instanciés

Le brush engine devrait écrire les paramètres de chaque dab dans un buffer d'instances puis rendre les quads dans un FBO de calque via un shader. Un format compact possible est 24 octets par instance : `vec2 position` (8), `float size` (4), `float opacity` (4), `float rotation` (4), `float padding` (4). La couleur et la texture de pointe peuvent rester des données communes au stroke. Un VBO/SSBO dynamique alimenterait un `glDrawArraysInstanced` par lot.

Pour N dabs, cela viserait N appels de dessin à environ `ceil(N / capacité_du_lot)` appels, généralement un appel par stroke/lot. Ce gain de drawcalls ne s'applique pas au code actuel : le travail dominant est l'écriture/blend CPU par pixel dans `brush_engine.cpp`, et le contenu du calque reste autoritaire en RAM. Le porter au GPU demande de définir la synchronisation de l'historique undo, du readback ou un stockage GPU autoritaire. Il faut également préserver les modes de fusion, textures de brush, clone, gomme, pression, jitter et dirty tiles. Je n'ai donc pas introduit un renderer de stamps qui dupliquerait le résultat CPU.

## 2. PBO double buffer

### Chemins CPU→GPU relevés

- Création initiale des textures de calque/tile dans `_create_texture`.
- Upload partiel d'un rectangle modifié dans `sync_layer`.
- Après chargement scratch, `sync_tile` attend la résidence CPU de la tuile puis appelle `_create_texture`; son transfert est donc couvert par le même upload PBO.
- `QOpenGLTextureBlitter.blit` est un rendu GPU→GPU, sans upload CPU.

Les tuiles scratch sont lues en arrière-plan, mais leur upload texture se produit ensuite dans le contexte OpenGL du thread UI. La double ring PBO réduit la dépendance à la durée de vie d'un pointeur client et permet au driver de différer le transfert texture. Chaque emplacement réalloue son stockage avant mapping (orphaning) pour éviter de réutiliser une zone encore consommée par le GPU.

### Mesure dans le contexte OpenGL

Smoke test Wayland / OpenGL 4.6 :

- création initiale : 130/130 uploads passés par PBO, 1 920 000 octets ;
- upload dirty rect de 4×5 pixels : 1 upload partiel PBO de 80 octets, avec 80 octets de staging CPU ;
- les blits comptés sont restés indépendants des uploads (520–780 sur les runs observés).

Avant le changement, l'upload initial Qt et le `glTexSubImage2D` sur pointeur CPU étaient synchrones du point de vue de la soumission. Les mesures ci-dessus vérifient le chemin pris et le volume de données, pas la durée d'exécution GPU. Le staging QImage et le memcpy vers le PBO restent synchrones côté CPU ; PBO ne supprime pas ce coût et aucun `glFinish`/readback bloquant n'est ajouté. Le driver peut aussi sérialiser certains transferts selon sa mémoire et sa charge.

## Fichiers

- `CANVAS/gpu_renderer.py` : ring de deux `PixelUnpackBuffer`, upload PBO des textures complètes et patches, fallback client-memory si les PBO ne sont pas disponibles, destruction dans le contexte courant, compteurs de transfert et blits.
- `CANVAS/canvas.py` : source des invalidations et du commit des zones modifiées ; aucun changement requis pour garder l'upload PBO compatible.
- `CPP_CORE/src/brush_engine.cpp` : production et blend CPU des dabs ; point de départ d'un futur renderer instancié, qui demanderait un projet séparé.

## Vérification

- `python -m compileall -q CANVAS/gpu_renderer.py`
- `python -m unittest CPP_TEST.test_gpu_dirty_tracking -v` — 2 tests réussis.
- Smoke test OpenGL Wayland — canvas GPU actif, uploads PBO complets et dirty rect observés, fermeture propre.
