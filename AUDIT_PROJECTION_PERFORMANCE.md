# Audit du thread de projection

## Conclusion

Le worker ne bloquait pas sur OpenGL : `ProjectionEngine` ne crée, ne lie et
n’attend aucun contexte graphique. Les pixels sont composés en CPU ; le
callback Python copie le résultat dans un `QImage`, puis le thread UI s’occupe
de l’upload GPU.

Le bridge ctypes seul n’explique pas le gain limité. Une mesure sur 20 000
appels au setter natif a donné **0,62 µs/appel**. Un appel
`cs_projection_invalidate()` mesuré avec un calque minimal a pris **13,46 µs**,
mais ce temps inclut la création du travail, sa copie et sa mise en file C++.
Le coût isolé d’un appel `invalidate` ne se déduit donc pas de cette valeur.

Le goulot avéré était la file native : elle n’avait qu’un seul thread de
composition. OpenMP pouvait paralléliser les lignes d’une grande tuile, mais
les tuiles distinctes restaient traitées l’une après l’autre.

## Changements appliqués

- Un pool natif traite des tuiles indépendantes en parallèle. Le réglage CPU
  configure le nombre de workers actifs, jusqu’à 16. Pour une requête limitée à
  une tuile, OpenMP garde un chemin de parallélisation par lignes.
- `cs_projection_invalidate_batch()` et `_NativeTile` envoient un lot de tuiles
  dans un seul appel ctypes. `ProjectionWorker.request()` utilise ce chemin
  lorsque la bibliothèque le fournit et conserve le fallback ancien ABI.
- Les paramètres et poids de mélange d’un calque sont normalisés une seule
  fois à la soumission, au lieu d’être copiés, vérifiés et clampés pour chaque
  pixel.
- Aucun contexte OpenGL partagé n’a été ajouté : le worker n’effectue aucun
  appel OpenGL. Le partage de contexte ne réduirait pas le temps de composition
  mesuré et compliquerait la propriété des ressources Qt.

## Mesures avant et après

Le benchmark reproductible est `python CPP_TEST/benchmark_projection.py
--tiles 256 --layers 5`. Il compose 256 tuiles de 64 × 64 px, chacune avec cinq
calques. Chaque valeur est la moyenne de trois passages. « Par tuile » envoie
une requête unitaire à la fois ; « batch » envoie les 256 tuiles dans une
requête. Les valeurs sont le temps de bout en bout, copies d’entrée et retours
Qt compris.

| Threads | Par tuile avant | Par tuile après | Gain | Batch avant | Batch après | Gain |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 347,3 ms | 351,1 ms | 0,99× | 376,0 ms | 368,9 ms | 1,02× |
| 4 | 120,4 ms | 100,7 ms | 1,20× | 132,0 ms | 125,6 ms | 1,05× |
| 8 | 138,2 ms | 64,0 ms | 2,16× | 92,6 ms | 75,7 ms | 1,22× |

Avant correspond à la file à worker unique ; après correspond au pool natif.
La variabilité entre 4 et 8 threads montre que ce résultat dépend du scheduler
et de la machine. Le gain ×10 de bout en bout n’est **pas atteint ni confirmé**.
La valeur antérieure de ×14,6 à ×17,5 portait sur un autre benchmark du noyau de
composition, sans le même coût d’orchestration complet.

Sur le build actuel, le temps passé dans les appels de soumission à 8 threads
était de 51,2 ms en requêtes unitaires et 24,3 ms en batch. Le batch libère donc
plus tôt le thread appelant, même si son temps total jusqu’à la fin des 256
compositions était supérieur dans ce scénario. Le benchmark inclut les copies
CPU et la copie des résultats Python ; ce n’est pas une mesure d’une interaction
tablette réelle.

## Vérifications

- Tests natifs des 16 modes de fusion et du batch : passés.
- Suite Python : **96 tests réussis**.
- CTest : **2/2 réussis**.
- `compileall` Python : réussi.
- Smoke test de l’application complète en Wayland/OpenGL : fermeture normale,
  code de sortie 0.

## Limites restantes

- La soumission copie encore les pixels CPU avant leur composition. Les
  transferts d’entrée et la copie QImage du callback restent inclus dans le
  temps bout en bout.
- Les mesures ne couvrent pas une tablette physique ni un soak test prolongé.
- Les performances à 4/8 threads varient selon le nombre de tuiles visibles et
  le CPU. Refaire le benchmark sur les machines cibles avant de fixer une
  valeur par défaut.
