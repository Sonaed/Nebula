# Refonte UX de Nebula — 26/09/2026

Objectif : rendre Nebula aussi agréable qu'Atlas / StarDust sans toucher au moteur.

## Ce qui change
- **Rail d'outils groupé** : 9 cases (Peinture, Gomme, Remplissage, Formes, Texte, Sélection,
  Déplacer/Transformer, Pipette, Vue) au lieu de 25 boutons. Clic droit ou appui long : variantes.
  La case retient la dernière variante utilisée.
- **Une seule barre d'options contextuelle** : outil actif, puis Preset / Taille / Opacité / Flux pour
  les outils de peinture, options de sélection pour les sélections, Valider/Annuler pour Transformer,
  une aide courte pour les autres. À droite : espace de travail + recherche.
- **Recherche de commandes (Ctrl+K)** : toutes les actions des menus, panneaux et espaces de travail,
  avec correspondance approximative et commandes récentes en premier.
- **Raccourcis (F1)** : aide-mémoire généré depuis les vraies actions.
- **Mode focus (Tab sur le canvas)** : masque tous les panneaux et la barre, restaure exactement l'état.
- **Agencement calme** : deux groupes à droite — [Couleur · Presets · Ressources · Assistants] et
  [Calques · Réglages · Fusion] — au lieu de sept onglets empilés.
- **Espaces de travail** : Peinture, Dessin, Retouche, Minimal (sélecteur dans la barre d'options).
- **Barre d'état** : aide de l'outil, taille du document et nombre de calques, moteur, zoom cliquable.
- **Français partout**, entrées de menu en double masquées, outils Sélection/Déplacer/Transformer
  ajoutés au menu Outils.
- **Thème** : les gris « Krita » des calques / roue / courbes sont remplacés par les bleus Nebula ;
  cibles plus grandes pour le stylet ; texte 12 px par défaut (le mode compact reste disponible).

## Migration (automatique, une fois)
`interface/layout_version = 2` : l'ancienne session et les espaces intégrés v1 (Painting, Drawing,
Minimal, Default) sont remplacés par le nouvel agencement. Les espaces que tu as créés toi-même sont
conservés. `interface/readable_migrated` : le mode compact est désactivé une fois.

## Revenir en arrière
Les fichiers d'origine sont dans `_backup_avant_refonte_ux/`.
