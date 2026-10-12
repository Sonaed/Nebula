# Préparation du rendu GPU — 1 octobre 2026

Le calcul d’occlusion du rendu GPU est maintenant limité aux tuiles visibles.
Une toile dense de grande taille ne provoque donc plus une lecture de tous ses
pixels lors du premier affichage d’une petite partie du document. Les index de
tuiles natives restent réutilisables d’une image à l’autre tant que leur compteur
de mutation ne change pas ; un trait ne relit que les index des calques modifiés.

Le rendu reste conservateur pour les masques actifs : un calque opaque dont le
masque peut révéler le dessous ne fait plus disparaître les calques inférieurs.
Le cache distingue également deux magasins de pixels successifs d’un même calque.

## Mesure reproductible

```sh
python3 CPP_TEST/benchmark_gpu_viewport.py --size 4096 --layers 3 --repeats 30
```

Le scénario utilise trois calques natifs denses de 4096 × 4096 pixels, soit
4 096 tuiles de 64 pixels par calque. La vue contient 192 tuiles (1024 × 768).
Les cinq passages à froid recréent le renderer ; les autres scénarios utilisent
30 images. Les résultats ci-dessous sont les médianes locales de préparation CPU
du rendu GPU, comprenant l’indexation native et le calcul d’occlusion.

| Scénario | Avant | Après | Gain |
| --- | ---: | ---: | ---: |
| Préparation à froid | 643,48 ms | 36,30 ms | ×17,73 |
| Image inchangée | 6,16 ms | 0,166 ms | ×37,10 |
| Modification d’une tuile | 8,54 ms | 2,04 ms | ×4,19 |
| Déplacement de la vue | 6,32 ms | 2,27 ms | ×2,79 |

Sur les 30 images inchangées, les lectures natives d’index passent de 90 à 0.
La lecture des pixels à froid passe de 12 288 à 576 tuiles par image. Pendant
les déplacements, les nouvelles tuiles exposées sont inspectées à la demande.

Les [résultats bruts](benchmarks/gpu-viewport-next-step.json) conservent les
compteurs, la version Python et la plateforme. Cette mesure n’inclut ni les
appels de dessin OpenGL, ni la latence du stylet, ni la composition des modes
de fusion complexes ; elle ne constitue pas une mesure de FPS de l’application.

## Vérification

74 tests ciblés réussissent avec Qt offscreen : préparation du viewport,
instantanés GPU, régions modifiées, alpha et publication de la projection.
Les régressions couvrent les limites du document, les déplacements, une tuile
modifiée hors écran, les masques, le remplacement du magasin, les mutations
natives, les lectures scratch en cours, l’ancien bridge et la libération des
références sans contexte OpenGL.

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest \
  CPP_TEST.test_gpu_viewport_preparation CPP_TEST.test_gpu_frame_snapshot \
  CPP_TEST.test_gpu_dirty_tracking CPP_TEST.test_gpu_alpha_edges \
  CPP_TEST.test_projection_presentation -q
```
