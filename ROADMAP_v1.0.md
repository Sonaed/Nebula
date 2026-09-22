# CreativeSystem — Roadmap vers la v1.0

## Point de départ — 16 septembre 2026

Le projet conserve son numéro applicatif `0.2.0` pendant le développement.
Cette roadmap décrit le travail nécessaire avant une version stable `1.0.0` ;
elle ne signifie pas que le logiciel est déjà en version 1.0.

Les étapes 1 à 10 de [`ROADMAP_v0.3.md`](ROADMAP_v0.3.md) sont terminées. Le
socle actuel comprend le moteur de brush C++ sans fallback Python de production, les outils
raster, la sélection, les transformations et le crop, les modes de fusion, les
assistants, Clone Stamp, texte et références non destructifs, Blur/Sharpen,
Bézier, ainsi que le shell avec workspaces et toolbar configurable.

La suite vise la stabilité au quotidien, la cohérence des documents et la
préparation d’une distribution utilisable hors de l’environnement de
développement.

## Jalons

### 1. Validation de stabilité — en cours

- Rejouer les workflows principaux : créer, peindre, annuler/rétablir,
  enregistrer, fermer et rouvrir un document.
- La matrice de validation manuelle est maintenue dans
  [`docs/MANUAL_VALIDATION_NEBULA.md`](docs/MANUAL_VALIDATION_NEBULA.md) ; le
  mode hors écran est validé, tandis que Wayland/OpenGL reste à reproduire sur
  une session graphique interactive.
- Vérifier les outils au stylet et à la souris, Alpha Lock, Smudge, Clone Stamp,
  sélection, transformation et objets non destructifs.
- Tester le rendu GPU sur les pilotes disponibles, les dirty rects aux bords du
  canvas, le redimensionnement et le fallback CPU quand OpenGL est indisponible.
- Recueillir des mesures reproductibles de temps de trait, mémoire et octets
  transférés pour plusieurs tailles de canvas.
- Critère de sortie : aucun crash reproductible sur les workflows essentiels ;
  toute limitation GPU connue dispose d’un fallback fonctionnel.

### 2. Fiabilité des documents et récupération

- Rendre l’enregistrement CSD atomique afin qu’une interruption ne remplace pas
  un fichier valide par une archive incomplète.
- Établir les migrations explicites des anciens manifests et presets, avec des
  fixtures couvrant chaque version prise en charge.
- Valider archives tronquées, champs malformés, images absentes et dimensions
  incompatibles sans fermer l’application.
- Ajouter une stratégie d’autosauvegarde et de récupération après fermeture
  inattendue, avec une interface claire pour reprendre ou ignorer une session.
- Critère de sortie : les documents valides restent ouvrables après migration ;
  une sauvegarde interrompue laisse le précédent fichier intact.

### 3. Cohérence de l’édition et de l’historique

- Vérifier que chaque opération utilisateur produit une transaction Undo/Redo
  cohérente, y compris outils, calques, sélection, transformation, texte et
  références.
- Compléter les cas limites de locks, Alpha Lock, clipping et fusion de calques.
- Uniformiser les règles d’écriture dans le masque de sélection pour chaque
  outil raster.
- Critère de sortie : tests de round-trip Undo/Redo pour les familles
  d’opérations et aucun changement hors sélection ou hors dirty rect attendu.

### 4. Composition avancée des calques

- Concevoir groupes de calques et opérations de regroupement/dégroupement.
- Ajouter masques de calque éditables et définir leur comportement avec les
  blend modes et le clipping. Le socle est maintenant en place : masque alpha
  sparse natif, composition C++ et persistance Nebula ; il reste à exposer la
  création/édition de masque dans le dock et à couvrir le geste manuel.
- Comparer le rendu CPU et GPU pour les modes, groupes et transparences ; le
  rendu CPU de référence est désormais CreativeCore, le GPU restant un chemin
  de présentation contrôlé par l’interface.
- Critère de sortie : persistance CSD versionnée et rendu CPU/GPU de référence
  avec résultats concordants.

### 5. Outils et transformations

- Compléter la transformation de sélection et préciser les comportements de
  rotation, mise à l’échelle, miroir et crop sur pixels et objets.
- Vérifier les poignées et previews sur différentes résolutions et facteurs
  d’échelle d’écran.
- Harmoniser les commandes de transformation et l’historique entre souris et
  tablette.
- Critère de sortie : preview annulable, commit unique dans l’historique et
  résultat conservé après sauvegarde/réouverture.

### 6. Brush Engine et presets

- Rassembler les réglages dans un dock cohérent et ajouter une preview de trait
  représentative du brush actif.
- Compléter les presets : recherche, catégories, favoris, import/export et
  validation de schéma.
- Documenter les paramètres indisponibles selon le backend et vérifier la
  parité utile entre les presets et le moteur C++ de référence.
- Critère de sortie : preset importé/exporté sans perte des paramètres pris en
  charge et rendu prévisible après changement de backend.

### 7. Shell, préférences et ergonomie

- Vérifier persistance et restauration des workspaces, docks, toolbar et
  raccourcis sur fermeture et redémarrage.
- Donner aux préférences des pages actives plutôt que des catégories
  informatives seulement ; enregistrer quels réglages sont appliqués sans
  redémarrage.
- Revoir les commandes de menu et les raccourcis pour éviter les actions
  inaccessibles ou contradictoires.
- Critère de sortie : réglages persistants, raccourcis avec retours de conflit et
  navigation clavier vérifiée sur les flux usuels.

### 8. Préparation de la version stable

- Définir les plateformes, versions Qt/PySide6 et exigences OpenGL supportées.
- Automatiser une installation propre, les tests et le lancement depuis une
  distribution construite.
- Rédiger le guide de démarrage, les formats pris en charge, les limites connues
  et les notes de migration.
- Mettre à jour `VERSION` à `1.0.0` uniquement après validation des critères
  précédents et préparer les artefacts de distribution.
- Critère de sortie : installation reproductible, tests verts et procédure de
  retour à une version précédente documentée.

## Règles de validation

Pour chaque jalon concerné :

1. Lancer `python -m unittest discover -s CPP_TEST -p 'test_*.py'` depuis la
   racine du projet.
2. Lancer `cmake --build build_cpp_native -j2` puis
   `ctest --test-dir build_cpp_native --output-on-failure`.
3. Vérifier les symboles publics de `CreativeCoreBridge` après toute évolution
   du bridge C.
4. Garder `main.py` pour les essais manuels ; préciser le pilote, la résolution
   et le périphérique d’entrée lors d’une validation graphique.
5. Mettre à jour ce fichier à chaque jalon, en notant ce qui a été vérifié et ce
   qui reste à tester.

## Reprise

Commencer par le jalon 1 : établir une fiche de tests manuels sur la machine
cible et comparer les mesures GPU/C++ avec la référence native. Ensuite traiter
la fiabilité CSD et la récupération avant d’ajouter les groupes et masques.

L’ancienne roadmap reste conservée ici :
[`ROADMAP_v0.3.md`](ROADMAP_v0.3.md).
