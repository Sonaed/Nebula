# Dessin, visibilité des calques et modes de fusion — 5 octobre 2026

Cette livraison améliore le dessin et le rendu des documents denses. Elle ne
constitue pas une certification de parité avec Photoshop : aucun benchmark
Photoshop sur cette machine n'a été effectué.

## Résultat sur le PSD fourni

Source lue sans sauvegarde ni export : `one_million_creature.psd`, 747 793 922
octets, 7200 × 5400 pixels, 43 calques et 3 groupes. Mesures CPU Qt offscreen,
OpenMP limité à 4 threads. Ce sont des temps de préparation, pas une mesure
écran/carte graphique ou de latence physique du stylet.

| Opération | Mesure |
| --- | ---: |
| Import éditable | 9,71–10,05 s |
| Miniatures de tous les calques | 91–93 ms |
| Première projection exacte, vue ajustée | 9,36–9,54 s |
| Masquer/afficher `Layer 40` : génération de l'aperçu | 79–286 ms |
| Même action : rendu exact, après génération de l'aperçu | 152–217 ms |
| Masquer/afficher `Group 3 copy` : génération de l'aperçu | 112–259 ms |
| Même action : première préparation de projection avant affichage | 195–201 ms supplémentaires |
| Même action : rendu exact, après génération de l'aperçu | 9,06–10,01 s |

Pour le grand calque `Group 3 copy`, génération de l'aperçu et première tranche
CPU totalisent **314–455 ms**. Le rendu exact reste coûteux, mais l'utilisateur
n'attend plus sa fin pour obtenir le retour visuel. Les empreintes des aperçus
masqué/visible sont différentes ; réafficher le calque restaure l'empreinte
initiale. Les quatre alternances de `Layer 40` donnent deux états reproductibles.

Les calques `Background` et `Layer 2` sont recouverts dans ce fichier : les
premiers essais sur eux ne montraient aucune différence visuelle. Ils ne servent
pas à prouver le retour visuel. Le diagnostic sur `Layer 2` montre néanmoins
qu'une recomposition inutile coûte encore environ 9–10 s ; une élimination plus
complète des calques occultés reste nécessaire.

Données : [calque supérieur](benchmarks/visibility-creature-2026-10-05.json),
[grand calque visible](benchmarks/visibility-creature-merged-layer-2026-10-05.json),
[diagnostic de calque recouvert](benchmarks/visibility-creature-large-layer-2026-10-05.json).

## Changements de rendu

- Aperçu temporaire de visibilité, limité à 768 pixels de côté et 96 Mio de cache.
  Le compositeur natif conserve les groupes et l'écrêtage. Réduire les sources
  avant fusion est une approximation : cet aperçu ne sert ni aux coups de
  pinceau, ni à la pipette, ni aux sauvegardes/exports.
- Publication atomique du rendu exact : l'aperçu disparaît lorsque toutes les
  tuiles visibles sont prêtes. Il est invalidé au dessin, au zoom rapproché,
  à l'annulation, aux modifications de contenu et au changement de document.
- Repli sur le chemin exact pour les masques, transformations, effets, objets
  texte/référence et sources sur disque temporaire. Ces cas ne bénéficient pas
  encore de l'aperçu rapide.
- Réutilisation des index de tuiles pendant les tranches de rendu ; suppression
  des requêtes natives de présence redondantes et des rescans du préfixe terminé.
- Exécution native de la pile par blocs de ligne ; calcul uniquement des
  contributions de fusion effectivement utilisées.

## Fusion : gains mesurés et dix modes supplémentaires

Microbenchmark reproductible : pile de 43 calques en 512 × 384, cinq mesures
après échauffement, médiane, mêmes pixels d'entrée. L'ancien algorithme est gelé
dans un oracle de test. Ce tableau compare Nebula avant/après, pas Photoshop.

| Mode | Ancien | Nouveau | Gain |
| --- | ---: | ---: | ---: |
| Normal | 437,0 ms | 67,4 ms | ×6,49 |
| Produit | 570,2 ms | 94,9 ms | ×6,01 |
| Superposition | 607,5 ms | 96,9 ms | ×6,27 |
| Incrustation | 426,9 ms | 96,9 ms | ×4,40 |
| Couleur | 802,2 ms | 203,8 ms | ×3,94 |

Les images de ce benchmark sont identiques octet par octet. Le test natif
contrôle aussi 256 piles aléatoires avec groupes imbriqués, masques, écrêtages,
réglages, opacités et paramètres, ainsi que les chemins parallèles.
[Sortie brute](benchmarks/blend-native-2026-10-05.txt).

Le catalogue passe de 16 à **26 modes** : ajout de Densité linéaire − (Ajout),
Densité linéaire +, Lumière vive, Lumière linéaire, Lumière ponctuelle, Mélange
maximal, Couleur plus foncée, Couleur plus claire, Soustraction et Division.
Les identifiants sont partagés entre le moteur, l'interface et les formats.
L'import PSD conserve désormais ces modes au lieu de les remplacer par des
approximations ; l'export écrit leurs véritables codes PSD. Fusionner les
calques les utilise également.

Les opérations ajoutées suivent les
[descriptions Adobe des modes de fusion](https://helpx.adobe.com/photoshop/desktop/repair-retouch/adjust-light-tone/blending-mode-descriptions.html).
Les tests indépendants couvrent les pixels avec alpha/opacité et les paramètres,
ainsi que l'aller-retour PSD. Cela ne garantit pas l'identité avec toutes les
options Photoshop : modes HSL historiques, profils, remplissage distinct de
l'opacité, groupes pass-through et profondeurs supérieures à 8 bits demandent
encore une qualification spécifique. Le mode Dissoudre reste absent.

## Fiabilité du stylet

Un nouveau trait ne détruit plus le worker terminant le précédent. Les samples
sont conservés dans l'ordre, puis rejoués par petites tranches, avec le calque,
la couleur et la transformation de vue capturés au départ du trait. Chaque
trait conserve sa propre entrée d'annulation. Les callbacks périmés sont
rejetés au changement de document.

Les sources résidentes sont figées par références de tuiles et maintenues en vie
jusqu'à l'arrêt du worker. Les événements de déplacement ne matérialisent plus
inutilement l'image entière du calque. La symétrie utilise le chemin synchrone
correct pour éviter que des snapshots concurrents écrasent leurs intersections.

## Vérification et reproduction

Validation finale : **667 tests Python exécutés, 659 réussis et 8 ignorés**,
**15/15 tests natifs réussis**, plus les 3 tests fonctionnels du cache de tuiles
non collectés par unittest. Aucun échec restant dans ces suites.

Les tests ciblés couvrent les hachures rapides, couleurs semi-transparentes,
annulations/rétablissements séparés, changement de calque/document, symétrie,
durée de vie des buffers, cache d'aperçu, mémoire bornée et lecture scratch
non bloquante. Les 26 variantes de shaders d'aperçu passent la compilation et
l'édition de liens GLSL ; leur rendu sur le GPU réel reste à qualifier.

```bash
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python -m unittest discover -s CPP_TEST -p 'test_*.py'
ctest --test-dir build_cpp_native --output-on-failure
OMP_NUM_THREADS=4 build_cpp_native/CreativeCoreStackCompositorTests --benchmark
QT_QPA_PLATFORM=offscreen OMP_NUM_THREADS=4 python CPP_TEST/benchmark_psd_workspace.py \
  /run/media/deanos/Stockage/one_million_creature.psd --visibility \
  --layer-name 'Group 3 copy' --visibility-cycles 1 --output /tmp/visibility.json
```

Le moteur natif a été reconstruit dans `build_cpp_native`. Redémarrer Nebula
est nécessaire si une instance utilisait déjà l'ancienne bibliothèque.

## Visibilité PSD — qualification du 11 octobre 2026

Le test a été rejoué sur `one_million_creature.psd` (7 200 × 5 400, 43 calques,
714 Mio). La visibilité ne vide plus toutes les projections : le moteur identifie
en natif les tuiles définitivement couvertes par un calque opaque normal et ne
recompose que les pixels qui peuvent réellement changer.

| Action | Ancien rendu exact | Nouveau rendu exact |
| --- | ---: | ---: |
| Calque entièrement couvert (`Layer 2`) | 9–10 s | 0,20–0,21 s |
| Groupe lourd (`Group 3`) | 9–11 s | 0,18–0,19 s |
| Calque visible de premier plan (`Layer 40`) | 9–10 s | 0,16–0,21 s |

Le clic de visibilité du groupe prend environ 0,47–0,53 s sur cette machine,
puis l'aperçu reste disponible pour les changements étendus pendant que le
rendu exact termine. Les cas de faible surface passent directement au rendu
exact, ce qui évite de fabriquer un aperçu temporaire inutile.

## Sélection sparse 8K — qualification du 11 octobre 2026

Sur une toile 8 000 × 6 000 de 12 calques, un clic de baguette magique dans
une tuile absente du calque actif passe d'environ **1 557 ms à 110 ms**. Une
tuile absente est connue comme entièrement transparente : le résultat contigu
est donc exactement la sélection de toute la toile et ne nécessite plus une
inondation de 48 millions de pixels. Les opérations Ajouter, Soustraire et
Intersection conservent leurs sémantiques usuelles.

Le réglage « échantillonner tous les calques » conserve le chemin de
composition complet : le résultat dépend alors réellement des calques sous et
sur le calque actif, et ne peut pas être déduit de la seule tuile sparse.
## Fusion sparse native — qualification du 11 octobre 2026

La fusion de deux calques raster standards ne repasse plus chaque tuile par
l’adaptateur d’image de l’interface. CreativeCore compose les tuiles résidentes
du calque supérieur directement dans le stockage natif du calque inférieur,
puis Nebula ne met à jour que les métadonnées de cache. Les modes standard,
l’opacité et l’annulation restent sur le même chemin de rendu Qt vérifié.

Sur le scénario CPU 8 000 × 6 000 à 12 calques, `merge_down` est passé
d’environ **590 ms à 422 ms**. Pour une pile dense de 8 000 tuiles opaques,
le chemin direct prend **125 ms** contre **463 ms** pour le chemin de
compatibilité tuile par tuile. Les 12 modes standard sont comparés pixel à
pixel au rendu Qt de référence ; le test natif confirme aussi que le calque
supérieur reste intact, y compris après une écriture ultérieure sur le calque
fusionné. Les modes avancés et les calques écrêtés continuent de prendre leur
chemin de composition complet, requis par leurs dépendances.


## Symétrie radiale sur toile 8K — 11 octobre 2026

Un trait radial ne doit jamais publier le rectangle qui englobe toutes ses
copies : à quatre directions opposées, ce rectangle couvre presque toute une
toile 8K, même si chaque dab ne touche que quelques tuiles. Le moteur publie
désormais chaque région de copie séparément dans le TileStore et dans le rendu.

Mesure CPU offscreen, toile 8000 × 6000, pinceau de 32 px, 15 mouvements :

| Copies | Médiane mouvement | Fin du trait |
| ---: | ---: | ---: |
| 1 | 1,57 ms | 6,27 ms |
| 4 | 5,27 ms | 9,66 ms |
| 8 | 9,65 ms | 17,63 ms |
| 12 | 15,66 ms | 25,81 ms |

Avant cette correction, quatre copies forçaient environ 700 ms par mouvement,
car chaque publication copiait le rectangle englobant de toutes les copies.

## Intégrité d’historique — stress-test du 11 octobre 2026

Le scénario déterministe `fuzz_undo_redo.py --seeds 24 --steps 120 --branch`
a exécuté **2 880 actions** : peinture, sélections, masques de calques et de
groupes, ajout/duplication/suppression/fusion/déplacement de calques, opacité,
groupes, Undo, Redo et création de branches d’historique. Les pixels, masques,
structure de calques et sélection ont été comparés après chaque restauration :
**24 exécutions sur 24 réussies**, sans divergence.
