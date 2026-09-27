# Frontières d’architecture Nebula

## Règle principale

CreativeCore/C++ possède les pixels, les tuiles, la rasterisation, la
composition, les transformations, la géométrie d’outils, les codecs Nebula et
le curseur d’historique. Python/PySide6 possède l’interface, les événements Qt,
les docks, les adaptateurs de signaux et la présentation.

## Autorisé côté Python

- convertir un événement souris/tablette en coordonnées document ;
- transmettre des paramètres et des buffers à l’ABI C++ ;
- maintenir les objets Qt miroir nécessaires aux docks ;
- encoder une image déjà produite par le moteur pour un export UI ;
- assembler les métadonnées Nebula et afficher les erreurs ;
- dessiner les overlays, previews et éléments purement visuels de l’interface.

## Interdit côté Python

- modifier les pixels d’un calque avec `QPainter`, `QImage.fill()` ou des
  boucles pixelaires de production ;
- implémenter un fallback de brush, de composition ou de sélection ;
- posséder une carte de tuiles, une politique d’éviction ou un historique
  pixel indépendant de CreativeCore ;
- dupliquer la règle géométrique d’un outil déjà exposée par l’ABI native.

## Compatibilités conservées

Les lecteurs CSD, Atlas et CSLZ sont des chemins d’import/récupération isolés.
Ils ne sont pas des moteurs d’édition actifs et ne doivent jamais devenir une
source de vérité concurrente. Les références Qt de test et les benchmarks
legacy restent hors production.

## Garde-fous

`CPP_TEST/test_architecture_boundaries.py` interdit le retour de `QPainter`,
`QImage.copy()` ou `.copy()` dans les adaptateurs `DOCUMENTS` et `TOOLS`.
Toute nouvelle exception doit être un adaptateur de durée de vie explicitement
justifié et remplacé par une primitive native dès que possible.
