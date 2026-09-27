# Matrice de validation manuelle Nebula

## Validation utilisateur — 22 septembre 2026

Le parcours ci-dessous a été exécuté et validé manuellement par l’utilisateur
dans l’application : peinture souris/stylet, outils, Undo/Redo,
enregistrement/réouverture et contrôle visuel du canvas. Cette validation
confirme le comportement de la configuration graphique et du périphérique
réels utilisés. La matrice reste conservée comme protocole reproductible pour
toute nouvelle machine, pilote graphique ou tablette.

Cette fiche complète les tests automatisés. Elle doit être exécutée avec une
session graphique réelle et un périphérique de pointage disponible.

## Environnement

- Date, distribution et version du pilote graphique :
- Session : Wayland / X11
- Qt / PySide6 :
- GPU et version OpenGL :
- Tablette et pilote :
- Résolution d’écran et facteur d’échelle :

## Parcours principal

| Parcours | Souris | Stylet | Résultat | Notes |
| --- | --- | --- | --- | --- |
| Nouveau document, pinceau, gomme | ☐ | ☐ | ☐ | |
| Pression et inclinaison visibles dans le trait | — | ☐ | ☐ | |
| Main, zoom, rotation et molette | ☐ | ☐ | ☐ | |
| Gradient, remplissage, formes | ☐ | ☐ | ☐ | |
| Sélection, déplacement et transformation | ☐ | ☐ | ☐ | |
| Alpha Lock, clipping et fusion | ☐ | ☐ | ☐ | |
| Undo/Redo pendant et après chaque outil | ☐ | ☐ | ☐ | |
| Enregistrement puis réouverture `.nebula` / `.nbl` | ☐ | — | ☐ | |

## Vérifications graphiques

- [ ] Canvas damier distinct du fond de l’application.
- [ ] Aucun décalage entre le curseur et la pointe du stylet.
- [ ] Aucun retard perceptible du trait après les événements tablette.
- [ ] Redimensionnement de fenêtre sans perte de pixels.
- [ ] Dirty rects corrects sur les quatre bords du canvas.
- [ ] Rendu OpenGL puis mode CPU/hors écran contrôlés séparément.

## Critères de sortie

Le parcours est accepté si aucun crash reproductible n’apparaît, si chaque
opération conserve ses pixels après Undo/Redo et si le document rouvert est
pixel-identique au document enregistré. Toute anomalie doit préciser le pilote,
le backend, l’outil, le type de pointeur et les dimensions de la toile.

L’environnement d’automatisation actuel valide le mode hors écran ; le backend
Wayland/OpenGL doit encore être confirmé sur la session graphique interactive.
