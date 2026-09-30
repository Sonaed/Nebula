# Qualification Nebula 26.2.0

Date : 2026-09-29

## Résultat

**Beta de production qualifiée pour le chemin tuilé, le budget mémoire et les
dégradations testées.** La qualification ne transforme pas un PSD dense en
document léger : un calque RGBA plein format coûte toujours largeur × hauteur
× 4 octets, valeur affichée avant import.

## Contrôles automatisés

| Domaine | Résultat |
| --- | --- |
| En-tête PSD et budget sans décodage | validé |
| Profils Prudent / Équilibré / Performance | validés |
| Tuiles froides : écriture scratch, relecture asynchrone et LRU | validé |
| Scratch plein/inaccessible/corrompu | tuile conservée, erreur explicite, validé |
| Annulation PSD et fichier tronqué | validé |
| Document 8K sparse, PSD/PSB et réouverture native | validé |
| Build CreativeCore et tests natifs | validé |
| Démarrage CPU/headless | validé |

Le benchmark collecte maintenant RSS avant import, après fermeture, après
réouverture, nombre de tuiles résidentes et nombre de tuiles scratch. Un
smoke reproductible est archivé dans `docs/benchmarks/qualification-smoke-26.2.json`.
Le benchmark dense `8k-50-dense` reste la porte de sortie : il doit être
rejoué sur une station disposant d’au moins 16 GiB libres et suffisamment de
scratch local, sans confondre son pic RSS avec une fuite persistante.

## Comportement en pression mémoire

1. Nebula invalide les caches de projection et de groupes.
2. Les tuiles hors viewport sont sélectionnées en LRU.
3. Une écriture scratch réussie rend la tuile froide ; elle est rechargée à la
   demande. Une écriture échouée laisse la tuile résidente et le document intact.
4. L’historique n’est réduit qu’après les tuiles et ses propres swaps.

## Limites connues

- Les mesures de fréquence d’image et le test GPU matériel restent dépendants
  de la station graphique cible ; le test headless valide le repli CPU.
- La durée d’une session de 30–60 minutes et le PSD dense réel doivent être
  observés sur cette même station avant d’apposer le label « final ».
