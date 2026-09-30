# Qualification Nebula 26.3.0

## Périmètre livré

- sélection document, combinaison replace/add/subtract/intersect/difference,
  contours, contraction, expansion, feather, sélection par couleur et alpha ;
- sélections nommées enregistrées dans le flux tuilé natif ;
- retouche et remplissage contraints par sélection, historique et masques ;
- transformation, perspective, warp et liquify par les outils existants ;
- masques alpha tuilés de calques et de groupes, groupes et invalidation localisée ;
- API `nebula.script.v1` sans exposition Qt/native, avec autorisations de
  lecture, modification, sauvegarde et export séparées ;
- ressources partagées versionnées, hachées, avec dépendances, validation
  d’intégrité à l’import de bundle et retour arrière par empreinte ;
- import PSD, projection tuilée et cache qualifiés par les campagnes 26.2.2.

## Vérifications automatisées exécutées

Le 29 septembre 2026, les tests Python ciblés sélection/format/API/resources,
retouche, transformations, masques de groupe et PSD ont passé (98 tests,
cinq scénarios dépendants de fixtures optionnelles ignorés) ainsi que les 13 tests C++
CreativeCore. Les tests couvrent
la réouverture des sélections nommées, les permissions de scripts, les erreurs
de manifeste et l’intégrité des ressources.

Le scénario viewport CPU a été rejoué : les six scénarios pan/retour/zoom
produisent tous une image prête, avec 694 cache hits visibles et 111 hits de
préchargement. Le rapport machine est
[`viewport-behavior-26.3.0.json`](benchmarks/viewport-behavior-26.3.0.json).
Les formes de sélection 512px ont mesuré 0,389 ms (rectangle), 3,430 ms
(ellipse) et 3,455 ms (lasso), médiane de trois exécutions.

Le PSD réel `one_million_creature.psd` (714 MiB, 7200 × 5400) a été rejoué :
aperçu en 0,826 s, première zone visible en 1,083 s, tuile froide en 0,809 s
et import éditable complet en 26,357 s. Le RSS est passé de 68,1 MiB à
2 501,5 MiB pendant l’import puis revenu à 76,6 MiB après fermeture et trim.
Le rapport est [`one-million-creature-26.3.0.json`](benchmarks/one-million-creature-26.3.0.json).

Un smoke OpenGL exécuté sur la station a confirmé l’initialisation GPU, un
stroke instancié (31 instances), la lecture de pixels et undo/redo. Le démarrage
complet a aussi confirmé `gpu_ready=True`, des PBO actifs et une fermeture propre.

## Limite de qualification matérielle

La session interactive GPU de 30 à 60 minutes sur la station cible reste un
gate matériel manuel : elle doit confirmer l’absence de fuite GPU, de texture
manquante et de dégradation progressive. Elle ne peut pas être attestée par un
environnement automatisé sans la station graphique cible.
