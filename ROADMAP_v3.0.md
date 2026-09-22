# CreativeSystem — Roadmap vers la v3.0

## Objectif

La v3.0 poursuit l’évolution du rendu et du moteur de peinture. Les fonctions
et chantiers antérieurs restent suivis dans [`ROADMAP_v2.0.md`](ROADMAP_v2.0.md).
Cette version clarifie notamment l’architecture réelle des stamps avant toute
tentative de rendu instancié.

## Rendu des stamps et instancing

- [x] Auditer le trajet d’un stamp jusqu’à l’affichage GPU.
- [x] Confirmer que les stamps ne génèrent pas un drawcall GPU chacun : dans
  `CPP_CORE/src/brush_engine.cpp`, chaque dab est composé pixel par pixel dans
  le `QImage` du calque.
- [x] Confirmer qu’OpenGL affiche ensuite les textures des calques avec un blit
  par tuile visible, via `CANVAS/gpu_renderer.py`.
- [x] Implémenter un rendu de stamps instancié sur FBO GPU pour les brushes
  ronds simples et les gommes : buffer d’instances, soumission par lots,
  aperçu FBO et lecture de la zone dirty à la fin du stroke. Les cas avancés
  repassent automatiquement par CreativeCore.
- [x] Ajouter un benchmark reproductible et mesurer le temps CPU de strokes
  représentatifs ainsi que le nombre de dabs estimé ; le brush ne génère aucun
  drawcall GPU par stamp dans l’architecture actuelle.
- [x] Mesurer après implémentation : un stroke souris de 150 px produit 42
  instances en 1 drawcall et 19 604 octets de readback. Le smoke test dédié
  valide aussi le cycle Undo/Redo.

### Mesure de référence

Benchmark lancé avec `python CPP_TEST/benchmark_stroke_rendering.py` sur un
canvas de 800 × 600, CreativeCore via ctypes, 7 échantillons après échauffement.
Le temps mesuré couvre la préparation de l’appel ctypes et la rasterisation C++
du stroke ; il exclut la distribution des événements Qt et la composition GPU.

| Stroke | Appels natifs | Dabs estimés | Médiane CPU | P95 CPU | Drawcalls GPU par dab |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fin dense, taille 8, espacement 0,10 | 240 | 3 923 | 16,260 ms | 16,394 ms | 0 |
| Diagonale moyenne, taille 24, espacement 0,15 | 160 | 479 | 13,188 ms | 13,218 ms | 0 |
| Ligne large, taille 64, espacement 0,20 | 120 | 240 | 39,160 ms | 39,208 ms | 0 |

Le chemin instancié est disponible pour les brushes éligibles. Les strokes
avancés restent mesurés par le tableau CPU ci-dessus.

### Constat d’architecture

Un vrai rendu instancié ne consiste pas à batcher des appels GPU par stamp déjà
présents : ces appels n’existent pas actuellement. Il nécessite une nouvelle
architecture GPU pour la composition des dabs. La v3.0 fournit une mesure de
référence CPU et une mesure OpenGL instanciée reproductible.

## Références

- [`AUDIT_GPU_RENDERING_TRANSFERS.md`](AUDIT_GPU_RENDERING_TRANSFERS.md) — audit
  rendu instancié et transferts GPU.
- [`ROADMAP_v2.0.md`](ROADMAP_v2.0.md) — état des chantiers et fonctionnalités
  précédents.

## SIMD restant — chantier obligatoire

- [ ] **Kernel SIMD 2 — composition projection_engine.cpp** : kernels séparés Normal, Multiply, Screen et Overlay, AVX2 8 pixels, SSE4 4 pixels, fallback scalaire, validation pixel-perfect avant activation.
- [ ] **Kernel SIMD 3 — brush_wet.cpp sampleCanvasColor** : pré-calcul du masque circulaire, accumulation SIMD RGBA8888, AVX2/SSE4/fallback scalaire, validation pixel-perfect avant activation.
