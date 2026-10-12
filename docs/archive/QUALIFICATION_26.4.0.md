# Qualification Nebula 26.4.0

Date : 30 septembre 2026

## Résultat automatisé

| Domaine | Résultat |
| --- | --- |
| Suite Python | 520 réussites, 8 tests ignorés, 0 échec |
| Build CreativeCore | Compilation complète réussie |
| Suite C++ | 14 réussites, 0 échec |
| Retouche 26.4 | clone aligné/non-aligné, options de calque et suppression d’objet couverts |
| Transformations | sérialisation perspective, warp et liquify couverte |
| Masques | persistance du masque vectoriel et de son état lié/délié couverte |
| Scripting | permissions, journal, annulation et traitement par lot couverts |

Les messages « Erreur ouverture/sauvegarde » vus durant la suite Python sont
les diagnostics attendus des tests d’archives volontairement invalides ; ils
ne correspondent à aucun échec de test.

## Implémentations 26.4

- Retouche sur calque dédié, rééditable, avec opacité et mode de fusion.
- Transformations complexes enregistrées dans le document Nebula pour audit et
  reprise ; les pixels restent la représentation rendue actuelle.
- Métadonnées de masques vectoriels et liaison masque/calque préservées dans le
  format Nebula.
- Cache de tuiles, prélecture, télémétrie UI/CPU/GPU et métriques d’import sont
  disponibles dans le moteur et ses diagnostics.
- Import PSD/PSB hiérarchique, calques de réglage, masques, groupes, effets et
  rapport de limitations à l’import/export restent couverts par la suite.
- `nebula.script.v1` reste une façade sans fenêtre, pointeur natif ni accès
  direct au système de fichiers. L’exécution et les extensions appartiennent à
  Existence/StarDust ; aucune infrastructure de plugin native Nebula n’est
  présente.

## Gates matériels et release à valider sur la station cible

Ces contrôles ne peuvent pas être attestés par une exécution automatisée dans
cet environnement ; ils doivent être réalisés avant diffusion générale :

- installation depuis l’archive GitHub `v26.3.1`, puis installation propre de
  la candidate 26.4.0 ;
- import/export de plusieurs PSD réels, dont le PSD dense 8K et le fichier
  client ;
- session GPU de 30 à 60 minutes (zoom/pan, peinture, groupes, undo/redo,
  sauvegarde, fermeture/réouverture) ;
- mesure RSS et mémoire GPU après plusieurs ouvertures/fermetures ;
- interruption pendant import, export et calcul sur stockage réellement
  indisponible.

La release ne doit être déclarée « production » qu’après ces gates matériels.
