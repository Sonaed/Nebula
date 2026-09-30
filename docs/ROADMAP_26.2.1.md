# Nebula 26.2.1 — continuité visuelle

## Objectif

Une tuile froide ne doit jamais donner l’impression que le document a disparu.
Le dernier rendu valide reste présent, le proxy/mipmap couvre les zones qui ne
sont pas encore prêtes, et la tuile exacte remplace cet aperçu uniquement après
son chargement réussi.

## Implémentation

- `TileCacheManager` classe les tuiles en `visible`, `recent`, `prefetch`,
  `active_group`, `cold` et `scratch`, sans posséder les pixels autoritaires ;
- la projection conserve un LRU de tuiles récemment vues au lieu de les vider
  dès la sortie du viewport ;
- le pan lent garde un halo réduit ; le pan rapide ajoute une bande dans la
  direction anticipée ; à faible zoom, le rendu réduit déjà disponible est
  favorisé plutôt que du travail spéculatif ;
- le cache de projection reste séparé des caches TileStore par calque, des
  caches isolés de groupe, des textures GPU et de l’undo ;
- le statut RAM expose les tuiles visibles, récentes, préchargées, froides,
  demandées et prêtes ;
- un indicateur discret apparaît lorsque des tuiles visibles attendent leur
  remplacement exact.

## Chemin de données

`scratch compressé → chargeur natif TileStore → texture GPU` est conservé pour
la relecture normale. Le chemin Python/QImage subsiste uniquement comme
adaptateur de présentation ou repli compatible ; il ne devient pas la source
de vérité des pixels.

## Validation

Les tests du gestionnaire couvrent halo lent, bande directionnelle, rétention
LRU et zoom réduit. Les tests TileStore couvrent chargement asynchrone,
réouverture d’une tuile froide, échec scratch et conservation des pixels.
