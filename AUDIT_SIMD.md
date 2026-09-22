# Audit SIMD CreativeCore

## Priorité

| Zone | Potentiel | Décision |
|---|---:|---|
| `cs_image_restore_alpha_rect` (alpha lock) | élevé, boucle indépendante par pixel | **implémenté** AVX2 (8 pixels), SSE4/SSSE3 (4), scalaire |
| `brush_engine.cpp` dab principal | très élevé, mais branches (format, clone, modes) | spécialiser ensuite le chemin Normal opaque; pas de vectorisation aveugle |
| `projection_engine.cpp` composition | élevé pour Normal/source-over | kernel SIMD par mode, après validation du prémultiplié et des dirty tiles |
| `brush_wet.cpp::sampleCanvasColor` | moyen | pré-calculer le masque circulaire puis vectoriser les accumulations float; `sqrt` et formats restent les coûts dominants |

## Runtime et fallback

`creative_simd::backend()` utilise `__builtin_cpu_supports` (AVX2 puis SSE4.1). Les noyaux sont compilés dans une unité séparée avec `-mavx2 -mssse3`; les autres fichiers CreativeCore restent portables. Chaque noyau est sélectionné à l'exécution et possède une boucle scalaire de terminaison. L'API `cs_simd_backend()` permet d'afficher le backend actif et de diagnostiquer la machine.

## Mesure

Le test CTest `CreativeCoreSimdTests` vérifie la conservation RGB, le rectangle partiel et les largeurs non multiples de 8. Il imprime le backend détecté. Cette optimisation concerne l'alpha lock; elle ne permet pas à elle seule de garantir un facteur x4–x8 sur tout le brush engine. Les gains globaux nécessitent les kernels spécialisés du tableau ci-dessus, mesurés séparément sur des strokes représentatifs.
