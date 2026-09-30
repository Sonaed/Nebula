# Nebula 26.2.0 — documents denses

Nebula 26.2.0 est une beta de production pour les documents lourds. Il ne
promet pas encore une consommation fixe pour toute pile PSD dense : la taille,
les calques, les profils et les effets restent déterminants.

## Livré

- les images RGBA de compatibilité sont rendues aux tuiles dès qu’une opération
  ou un stroke est synchronisé ;
- les pixels autoritaires restent dans les `TileStore` natifs, avec chargement
  à la demande des tuiles évincées ;
- les tuiles froides suivent une politique LRU hors viewport et sont écrites
  dans le scratch compressé ;
- les caches de projection et de groupes sont bornés et invalidés localement ;
- les groupes se composent isolément, avec cache par tuile ;
- la limite RAM et le dossier scratch sont configurables dans Préférences ;
- l’import PSD affiche dès le départ une estimation de son jeu de travail RAM,
  puis conserve cette information dans l’état d’import.

## Qualification requise avant finale

- PSD dense 8 000 px / 50 calques opaques ou translucides ;
- import annulé, scratch indisponible et réouverture de tuiles froides ;
- déplacement dans un document dense pendant un import encore actif ;
- mesure RSS et absence de fuite après fermeture du document.
