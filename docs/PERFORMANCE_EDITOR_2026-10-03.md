# Qualification des opérations d’édition — 3 octobre 2026

Les corrections sont appliquées au code Python et au moteur C++ local, recompilé
avec succès. Redémarrer Nebula pour charger la nouvelle bibliothèque native.
Les nombres du compte rendu distant de Claude ne sont pas repris comme mesures
locales : sa configuration et son scénario diffèrent.

## Protocole

`CPP_TEST/benchmark_editor_actions.py` mesure un document de 8000 × 6000 pixels,
12 calques avec chacun une zone colorée de 3000 × 4600 pixels, un zoom de 20 %,
un pinceau de 48 px et 120 événements par trait. Un trait chauffe le moteur.
Les valeurs sont les médianes de trois répétitions, sauf le contour de sélection.
Les opérations de sélection et de calques repartent du même état par annulation.
Les couleurs, positions et opérations sont identiques avant et après.

Python 3.14.7, Linux, Qt en mode offscreen, `OMP_NUM_THREADS=4`, rendu CPU.
La référence a été rejouée dans une copie isolée des fichiers et de la bibliothèque
native sauvegardés avant les modifications. Les deux mesures finales ont été
exécutées successivement, sans suite de tests simultanée. Ce sont des latences
d’opérations, pas des mesures de fluidité GPU ni de latence d’une tablette réelle.

## Résultats locaux

Temps en millisecondes ; une valeur plus basse est préférable.

| Opération | Avant | Après |
|---|---:|---:|
| Mouvement du pinceau (médiane) | 2.44 | 2.25 |
| Mouvement du pinceau (p95) | 3.91 | 3.67 |
| Relâchement du trait | 27.51 | 26.44 |
| Annuler le trait | 18.35 | 7.86 |
| Rétablir le trait | 14.00 | 4.50 |
| Sélection rectangulaire : opération | 377.91 | 146.21 |
| Sélection rectangulaire : annuler | 182.50 | 7.25 |
| Sélection rectangulaire : rétablir | 328.73 | 10.61 |
| Sélection au lasso : opération | 1345.44 | 265.74 |
| Sélection au lasso : annuler | 308.34 | 10.96 |
| Sélection au lasso : rétablir | 445.98 | 13.28 |
| Contour progressif 20 px : opération | 1084.77 | 321.93 |
| Contour progressif 20 px : annuler | 341.57 | 11.77 |
| Contour progressif 20 px : rétablir | 395.14 | 11.24 |
| Inverser la sélection : opération | 1299.99 | 274.19 |
| Inverser la sélection : annuler | 1009.37 | 42.95 |
| Inverser la sélection : rétablir | 1601.11 | 52.52 |
| Tout sélectionner : opération | 1535.39 | 213.78 |
| Tout sélectionner : annuler | 1117.63 | 16.04 |
| Tout sélectionner : rétablir | 1240.94 | 15.52 |
| Désélectionner : opération | 680.54 | 134.06 |
| Désélectionner : annuler | 1571.69 | 91.62 |
| Désélectionner : rétablir | 875.24 | 39.08 |
| Baguette, calque actif : opération | 2729.82 | 1562.26 |
| Baguette, calque actif : annuler | 1104.72 | 37.18 |
| Baguette, calque actif : rétablir | 1514.27 | 54.76 |
| Baguette, tous les calques : opération | 3032.05 | 1758.10 |
| Baguette, tous les calques : annuler | 5574.63 | 60.77 |
| Baguette, tous les calques : rétablir | 913.71 | 39.84 |
| Contours de sélection (une mesure) | 802.84 | 119.44 |
| Ajouter un calque : opération | 38.69 | 0.59 |
| Ajouter un calque : annuler | 82.80 | 0.28 |
| Ajouter un calque : rétablir | 119.38 | 0.27 |
| Dupliquer un calque : opération | 131.89 | 105.27 |
| Dupliquer un calque : annuler | 159.46 | 1.55 |
| Dupliquer un calque : rétablir | 222.52 | 28.88 |
| Déplacer un calque : opération | 40.02 | 0.68 |
| Déplacer un calque : annuler | 80.44 | 0.29 |
| Déplacer un calque : rétablir | 119.31 | 0.26 |
| Fusionner avec le calque inférieur : opération | 547.88 | 547.29 |
| Fusionner avec le calque inférieur : annuler | 328.58 | 58.30 |
| Fusionner avec le calque inférieur : rétablir | 333.78 | 33.14 |

Les gains principaux concernent les sélections et l’historique. Le relâchement
du trait (27,51 → 26,44 ms) et la fusion elle-même (547,88 → 547,29 ms) sont
pratiquement inchangés dans ce scénario. La baguette sur tous les calques reste
coûteuse (1,76 s) : il faut encore calculer la projection et parcourir les pixels.
Aucun gain significatif n’est revendiqué pour ces petites variations de mesure.

## Corrections

- Historique : ne plus désérialiser les deux images de chaque tuile de peinture
  lorsqu’on cherche seulement les changements de sélection ; restauration native
  des calques, lecture du seul côté nécessaire des sélections.
- Sélections : image vide allouée à la demande, cache de sauvegarde en tuiles publié
  à la demande, blocs d’historique de 512 px. Les formes, contours, anticrénelage
  et filtres travaillent sur leur zone utile. Les tuiles du format enregistré
  restent inchangées.
- Pont natif : les entrées en lecture seule ne détachent plus implicitement les
  images Qt partagées. Les réglages scalaires du pinceau évitent une copie complète.
- Branches d’historique : une nouvelle édition après annulation ne réutilise plus
  les métadonnées structurelles abandonnées. Les masques des groupes et calques
  sont conservés pendant les changements de structure.
- Dossiers : déplacement d’un bloc dans le bon sens, passage autour des groupes
  voisins, restauration des groupes imbriqués et correspondance de leurs indices
  natifs après reconstruction et suppression.
- Peinture sous sélection : interpolation des pixels avant/après tenant compte
  de l’alpha, y compris pour la gomme ; les pixels effacés ne réapparaissent plus.
- Dégradés : regroupement des mouvements rapides, calcul obligatoire de la position
  finale au relâchement, annulation du travail en attente lors d’une annulation,
  fermeture ou changement de document.

L’échantillonnage du lissage souris/tablette n’a pas été réduit de 3 à 6 pixels.
Les gains ne reposent pas sur cette réduction de précision proposée dans l’extrait.

## Vérification

Les tests de régression comparent les pixels : formes et opérations de sélection,
filtres aux bords, arrondi de l’anticrénelage, gomme sous sélection et dégradé.
Le test aléatoire vérifie pixels, masques, propriétés et groupes après chaque
annulation/rétablissement : 36 séquences, 3 360 actions, dont 24 séquences avec
annulation et nouvelle branche. Toutes passent. Un sous-ensemble déterministe
est intégré à la suite Python pour les prochaines modifications.
Suite Python complète : **623 tests, succès, 8 ignorés** (62,64 s).
Suite C++ : **14/14 réussis** (10,83 s).
Les assertions des tests C++ restent actives dans les builds Release.

## Reproduction

Depuis la racine de Nebula :

```sh
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python CPP_TEST/benchmark_editor_actions.py --output /tmp/editor.json
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python CPP_TEST/fuzz_undo_redo.py --seeds 24 --steps 100 --branch
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python -m unittest discover -s CPP_TEST -p 'test_*.py'
cmake --build build_cpp_native -j 4
ctest --test-dir build_cpp_native --output-on-failure
```

Données brutes : [avant](benchmarks/editor-before-2026-10-03.json),
[après](benchmarks/editor-after-2026-10-03.json),
[stress](benchmarks/editor-stress-2026-10-03.json).

Un [profil cumulatif après correction](benchmarks/editor-profile-after-2026-10-03.txt)
a également été enregistré avec `python -m cProfile` et une répétition du scénario.
Ses durées incluent l’instrumentation et ne servent pas au tableau comparatif.
