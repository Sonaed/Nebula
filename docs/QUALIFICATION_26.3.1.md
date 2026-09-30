# Qualification Nebula 26.3.1

## Périmètre

- suppression de `object_pool` et `tile_cache`, anciennes structures C++ sans
  référence CMake, ABI ou appel de production ;
- cycle de vie scratch redémarrable entre fermetures de documents ;
- isolation des doublures de tests Qt/Core/Documents ;
- tests Existence exécutables sans socket Unix dans les environnements isolés.

## Résultats

La suite Python complète passe : **513 tests**, **0 échec**, avec **8 skips**
attendus lorsque le rendu GPU ou les sockets Unix ne sont pas disponibles.

Les cibles C++ CreativeCore couvrent le moteur, les filtres, l'historique, les
tuiles, le rendu et les noyaux PSD. La configuration de test doit être générée
avec `-DBUILD_CPP_TESTS=ON` sur un répertoire de build accessible en écriture.

## Architecture des plugins

La recherche de chargeurs dynamiques, de dossiers `plugins`, de manifestes et
d'importations d'extensions ne révèle aucun système de plugin Nebula. Les
chargements dynamiques présents sont limités à CreativeCore, OpenGL et libc.
Les plugins et ressources publiables relèvent d'Existence.
