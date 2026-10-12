# Gros PSD : qualification du 4 octobre 2026

Fichier fourni : `one_million_creature.psd`, 747 793 922 octets (713,2 MiB),
7200 × 5400 pixels. Les 46 entrées Photoshop deviennent **43 calques et 3 groupes**,
dont 2 calques écrêtés. Aucun avertissement d’import sur ce document.
Le fichier source a été lu uniquement : aucune sauvegarde ni conversion sur place.

## Résultat mesuré

Mesures locales CPU, Qt offscreen, `OMP_NUM_THREADS=4`. Les valeurs ci-dessous
sont des observations du même scénario sur le même fichier, pas une promesse de
latence sur toute machine ni une mesure de fréquence d’affichage GPU.

| Opération | Avant | Après |
|---|---:|---:|
| Import de tous les calques éditables, sans profileur | 25,192 s | 10,483 s |
| Miniatures des 43 calques, sans profileur | 2,824 s | 0,094 s |
| Premier lot de 176 tuiles de l’aperçu, avec profileur | 1,512 s | 0,274 s |
| Lot de 176 tuiles à l’autre extrémité, avec profileur | 1,240 s | 0,157 s |

L’import a aussi été observé à 10,42–10,56 s dans les autres exécutions. Les
mesures instrumentées sont séparées des mesures sans profileur. L’aperçu intégré
est disponible en environ 0,6–0,9 s ; il reste affichable pendant l’import.

Dans le scénario d’affichage CPU final (fenêtre 1200 × 800), préparer la projection
complète à la taille de la fenêtre prend encore **15,66 s**, contre 18,82 s avant
la réutilisation de la classification du cache. Ce calcul suit l’import : il ne
faut pas confondre l’aperçu rapide avec l’achèvement du rendu de tous les calques.
Après cette préparation, le zoom à 100 % et le déplacement dans les zones déjà
calculées prennent respectivement 28,9 et 22,3 ms. Un nouveau calcul après modification
n’a pas nécessairement ces mêmes latences.

La mémoire résidente après import reste proche de **2,4 GiB**. Les pixels importés
occupent 2 470 025 216 octets dans 152 164 tuiles. Les optimisations ne prétendent
pas compresser cette représentation ni rendre son volume négligeable.

## Changements appliqués

- Transfert des pixels PSD directement dans le moteur C++, par lots bornés de
  tuiles : conversion RGBA/ARGB, découpage, décalages négatifs, limites du canevas
  et suppression des tuiles transparentes en un parcours. Les tableaux source
  restent inchangés. L’ancien chemin reste disponible avec une bibliothèque
  native plus ancienne.
- Les tuiles voisines d’un aperçu partagent le décodage de leurs lignes
  compressées. Les bandes regroupées sont limitées à quatre millions de pixels ;
  des régions distantes ne provoquent pas une décompression de tout leur intervalle.
- Miniatures calculées depuis les tuiles natives résidentes, sans recopier chaque
  tuile dans Python. Le chemin existant reste utilisé pour les tuiles sur disque.
- La demande du cache est réutilisée tant que le viewport et sa politique de
  préchargement ne changent pas. Les tuiles visibles restent prioritaires sur
  les tuiles spéculatives lors de l’éviction.

## Fidélité et validation

Les empreintes SHA-256 de toutes les tuiles de chacun des 43 calques, leur ordre,
nom, visibilité, opacité et mode de fusion sont **identiques avant/après**.
Le format des pixels est conservé ; seuls les RGB déjà ignorés par l’ancien
importeur sous un alpha nul sont canonicalisés à zéro.

Les huit nouveaux tests vérifient les pixels avec décalages et recadrage,
l’immuabilité des sources, les alphas faibles et nuls, les miniatures contre
l’ancien rendu, la lecture regroupée RAW/RLE/ZIP et l’invalidation du cache.
Les trois tests historiques de la politique de cache passent également.
Les 14 tests C++ passent. La suite Python finale comporte 632 tests :
623 réussis, 8 ignorés, et l’échec préexistant décrit ci-dessous (59,98 s).

La suite Python complète a révélé un défaut **préexistant** de traits asynchrones
très rapidement enchaînés (`test_fast_hatching_keeps_every_async_stroke_whole`).
Le même test échoue avec la bibliothèque native sauvegardée avant ces changements.
Ce défaut est distinct de l’import PSD et n’a pas été masqué ou supprimé du test.

## Reproduction

Depuis la racine de Nebula :

```sh
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python CPP_TEST/qualify_real_psd.py /chemin/vers/fichier.psd --output /tmp/psd-import.json
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python CPP_TEST/benchmark_psd_workspace.py /chemin/vers/fichier.psd --fingerprints --output /tmp/psd-workspace.json
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python -m unittest CPP_TEST.test_psd_large_paths CPP_TEST.test_psd_reader CPP_TEST.test_psd_parity
```

Données : [comparaison et empreintes](benchmarks/psd-creature-comparison-2026-10-04.json),
[qualification avant](benchmarks/psd-creature-profile-before-2026-10-04.json),
[qualification après](benchmarks/psd-creature-profile-after-2026-10-04.json),
[affichage](benchmarks/psd-creature-workspace-2026-10-04.json).
Les [profils avant](benchmarks/psd-creature-profile-before-2026-10-04.txt) et
[après](benchmarks/psd-creature-profile-after-2026-10-04.txt) montrent le déplacement
du coût dominant du transfert Python vers la décompression des canaux.

Redémarrer Nebula pour charger la bibliothèque C++ recompilée.
