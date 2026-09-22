# Audit GPU — mipmaps et occlusion culling

## Mipmaps

Les textures de calques et de tuiles sont créées dans `CANVAS/gpu_renderer.py`.
Elles avaient un seul niveau et utilisaient le filtrage linéaire. Le renderer
alloue maintenant la chaîne complète de niveaux, appelle `generateMipMaps()`
après chaque upload complet ou partiel, puis utilise le filtre
`LinearMipMapLinear` à la minification.

Pour les rectangles dirty, `glTexSubImage2D` met à jour le niveau de base puis
`glGenerateMipmap` reconstruit la chaîne. OpenGL ne met pas à jour seulement la
zone correspondante de chaque niveau inférieur avec cet appel : la chaîne
entière est régénérée. La texture gagne environ un tiers de mémoire pour une
chaîne complète ; la régénération répétée peut aussi coûter du temps GPU pendant
un stroke. Les compteurs `mipmap_generations` permettent de suivre ce coût.

## Occlusion culling

Le renderer examine la pile du haut vers le bas et calcule la couverture par
tuile du document. Une tuile masque les calques inférieurs seulement si elle est
entièrement opaque, résidente, en mode `normal`, sans paramètres de fusion,
avec opacité de calque à 1 et sans clipping. Le culling saute les tuiles
recouvertes dans les calques tuilés ; un calque non tuilé n’est sauté que si
toute la grille du document est couverte.

Les résultats alpha sont mis en cache selon la révision de tuile et recalculés
après une modification. Une tuile scratch non résidente est considérée comme
inconnue et ne masque donc jamais un calque. Les modes de fusion non-Normal,
l’opacité partielle, les paramètres de fusion et les transformations ne
participent pas à l’occlusion. C’est volontairement prudent pour ne pas
supprimer de contenu visible.

## Fichiers modifiés

- `CANVAS/gpu_renderer.py` : allocation des chaînes mipmap, régénération après
  upload, analyse alpha mise en cache, calcul de couverture et saut des tuiles
  occluses.
- `CANVAS/canvas.py` : commit des buffers image avant le calcul top-down et
  transmission des tuiles couvertes au renderer.
- `CPP_TEST/test_gpu_dirty_tracking.py` : tests du nombre de niveaux, de la
  transparence, du mode Multiply et de l’opacité partielle.

## Vérifications

- `python -m unittest discover -s CPP_TEST -v` — 99 tests réussis.
- Smoke test Wayland/OpenGL 4.6 : 130 textures initiales et 130 générations
  mipmap, canvas GPU actif, fermeture propre.
- Test OpenGL d’un upload dirty rect de 4×5 : 80 octets transférés par PBO et
  une nouvelle génération mipmap.
- Les cas d’occlusion sont testés unitairement ; le document de démarrage du
  smoke test n’avait pas de tuile opaque superposée, donc le compteur de tuiles
  réellement écartées y est resté à zéro.
