# Changelog — 22 septembre 2026 — Accélération GPU

## Résumé

Le rendu GPU est maintenant activé par défaut lorsque le contexte OpenGL 3.3 est disponible. CreativeCore/C++ reste la source de vérité pour les documents, l'historique, les filtres destructifs et les sauvegardes.

## Ajouté

- Composition des tuiles visibles en GPU pour les modes de fusion standards : Darken, Multiply, Color Burn, Lighten, Screen, Color Dodge, Overlay, Soft Light, Hard Light, Difference et Exclusion.
- Test OpenGL de parité pour ces modes de fusion : `CPP_TEST/smoke_gpu_compositor.py`.
- Pinceaux simples compatibles rendus en GPU avec retour sûr vers CreativeCore si nécessaire.
- Aperçu GPU pour zoom, déplacement, rotation, miroir et transformations de calque.
- Compteurs de diagnostic via `canvas.gpu_stats_snapshot()` : transferts, tuiles compositées, passes shader et replis.
- Blitter OpenGL interne (`CANVAS/gpu_safe_blitter.py`) afin de ne plus dépendre du blitter Qt/PySide instable sous Python 3.14.

## Corrigé

- Le canvas GPU fonctionne sans `CREATIVESYSTEM_ENABLE_UNSAFE_GPU_BLITTER=1`.
- Correction des artefacts visuels provoqués par `QOpenGLTextureBlitter` avec PySide 6.11 / Python 3.14.
- Correction de l'upload d'atlas GPU (`AtlasRect`).
- Une transformation avec seulement rotation ou déplacement est maintenant bien appliquée lors de la validation.
- La projection CPU C++ n'est plus lancée inutilement pour les documents composités entièrement par GPU.

## Repli et fiabilité

- Groupes, masques, clipping et paramètres avancés utilisent automatiquement la projection CreativeCore/C++ pour garantir le même rendu.
- Blur et Sharpen destructifs restent calculés par CreativeCore afin que le résultat sauvegardé et l'historique restent identiques sur toutes les machines.
- Si OpenGL 3.3 n'est pas disponible, Nebula utilise automatiquement le rendu CPU fiable.

## Validation

- 267 tests Python réussis, 1 ignoré.
- 11 tests C++ réussis.
- Parité OpenGL validée pour les 11 modes de fusion GPU standards.
- Démarrage vérifié avec : `python main.py`.

## Commits locaux principaux

- `0743cd8` — remplacement du blitter Qt instable par un shader OpenGL.
- `4eb6ea4` — suppression de la projection CPU redondante pendant la composition GPU.
- `e3c23c0` — aperçu GPU de rotation et déplacement.
- `f997375` — test de parité OpenGL des modes de fusion.
