# Changelog

## 26.4.0 — 12 octobre 2026

Cette version concentre Nebula sur le dessin et la peinture raster : un geste
fiable, une toile réactive et un atelier plus lisible sur les petits comme les
grands documents.

### Dessin et pinceaux

- Moteur de pinceau CreativeCore unifié : l’aperçu, le trait final et
  l’historique utilisent le même résultat.
- Tracé sous-pixel lissé à la souris et au stylet, fin de trait stabilisée,
  segments droits avec Maj+clic, courbe de pression éditable et aperçu de
  faible latence.
- Pinceaux plus expressifs : pression, inclinaison, vitesse, aléa déterministe,
  grain ancré à la feuille, peinture humide, gomme fidèle à la pointe et import
  de pinceaux Photoshop `.abr`.
- Symétrie radiale à 2, 4, 6, 8 ou 12 copies, avec centre repositionnable sur
  la toile.

### Documents lourds et performance

- Composition de pile native accélérée et catalogue étendu à 26 modes de
  fusion, conservés à l’import et à l’export PSD.
- Aperçu immédiat lors de la visibilité des calques, suivi d’une publication
  atomique du rendu exact.
- Fusion de calques native par tuiles, sélections sparse et opérations de
  peinture qui ne matérialisent plus inutilement une image de calque entière.
- Sur le PSD de référence de 714 Mio (7 200 × 5 400, 43 calques), les bascules
  de visibilité mesurées passent de 9–11 s à environ 0,16–0,21 s pour le rendu
  exact des cas couverts.

### Atelier et fiabilité

- Accueil, palette rapide, panneaux Pinceau/Couleur/Calques/Historique,
  recherche de commandes et barre d’options ont été simplifiés pour laisser la
  priorité à la toile.
- Historique renforcé : 2 880 actions de peinture, sélection, calques,
  masques, Undo/Redo et branches ont été vérifiées sans divergence.

Les détails fonctionnels, limites de qualification et résultats reproductibles
sont dans les [notes détaillées 26.4.0](docs/CHANGELOG_26.4.0.md) et les
[rapports de performance](docs/PERFORMANCE_DRAWING_BLEND_2026-10-05.md).

## 26.3.1

Qualification et fiabilisation du moteur et de l’atelier. Voir l’historique
Git et les documents de qualification associés.
