# Qualification utilisateur Nebula 26.2.2

## Automatisé

Le scénario viewport CPU reproductible utilise un document 8K sparse et
enchaîne pan lent, pan rapide, inversion, zoom avant/arrière et retour à une
zone récente. Il produit `docs/benchmarks/viewport-behavior-26.2.2.json`.

Résultat de la qualification locale : toutes les projections de viewport ont
atteint un état prêt ; le retour récent n’a déclenché aucune demande additionnelle
de tuile, et les compteurs de cache enregistrent les réutilisations visibles et
de préchargement. Les tests TileStore couvrent séparément scratch indisponible,
échec d’écriture, fichier scratch corrompu et rechargement asynchrone.

## PSD réel — one_million_creature.psd

Le fichier fourni (714 MiB, 7200 × 5400) a été ouvert en lecture seule. Le
rapport complet est `docs/benchmarks/one-million-creature-26.2.2.json` :

| Mesure | Résultat |
| --- | ---: |
| Aperçu intégré | 0,604 s |
| Première zone visible (176 tuiles) | 1,047 s |
| Zone froide distante (176 tuiles) | 0,807 s |
| Import éditable | 23,749 s |
| Calques / groupes / clipping | 43 / 3 / 2 |
| Avertissements d’import | aucun |
| RSS avant / après import | 68,2 / 2 649,8 MiB |
| RSS après fermeture et libération | 76,6 MiB |

Cette mesure a également corrigé le chemin **Fermer le document** : les
TileStores natifs et caches de groupes sont maintenant libérés explicitement,
puis l’allocateur Linux est compacté lorsque disponible. Le RSS ne reste donc
pas artificiellement élevé après un PSD dense fermé.

## À réaliser sur station utilisateur/GPU

Ces contrôles ne peuvent pas être déduits d’un test headless :

- session GPU active de 30–60 minutes avec suivi RSS et mémoire GPU ;
- vrai PSD dense 8K/50 calques et plusieurs PSD clients ;
- perception de fluidité, changement de calque/groupe pendant chargement,
  fermeture après utilisation prolongée du scratch.

Le protocole est de relever `Canvas.performance_stats_snapshot()` et
`Canvas.gpu_stats_snapshot()` avant/après chaque session, puis de comparer RSS
après fermeture à la ligne de base. Une zone restée vide constitue un échec ;
un proxy, un mipmap ou une projection antérieure pendant un chargement est le
comportement attendu.
