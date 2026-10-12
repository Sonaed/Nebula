Next Update: 
Je suis en train de pousser nebula a fond afin de voir les endroit qui peuvent causer des bug et ralentissement ainsi que les manque fonctionnel ou optimisation UI
la Version 26.4.x Sera une Update Majeur 

Un petit Aperçu:
<img width="2558" height="1428" alt="image" src="https://github.com/user-attachments/assets/d96656e2-9b76-4798-9893-052e7faa8206" />



# CreativeSystem Nebula

Application de dessin PySide6/Qt 6 avec Canvas OpenGL et moteur de brush C++.


## Atelier — évolution du 1er octobre 2026

Accueil et interface graphite, formats de toile avec aperçu, barre de pinceau
compacte et restauration fiable des panneaux. L’onglet **Historique** permet de
revenir à une étape par clic ou au clavier. **Dégradé (G)** propose désormais
linéaire, radial et angulaire, deux couleurs, inversion, répétition et opacité,
avec sélection progressive et annulation du geste.

La préparation CPU du rendu GPU limite l’occlusion aux tuiles visibles et
réutilise les index natifs inchangés. Le développement RAW/photo reste dans Nova.
Voir le [compte rendu et les aperçus](docs/NEXT_STEP_2026-10-01.md) pour les
mesures, les tests et les limites de qualification.

## Dessin et fusion — 5 octobre 2026

26 modes de fusion, import/export PSD sans substitution pour les dix nouveaux
modes, hachures rapides préservées et aperçu de visibilité sur les grands
documents. Le moteur de fusion gagne ×3,9 à ×6,5 sur les piles mesurées.
Le rendu exact des grands calques reste plus lent que l'aperçu : voir les
[mesures sur le PSD fourni et les limites](docs/PERFORMANCE_DRAWING_BLEND_2026-10-05.md).

## Outils

- `B` : pinceau
- `E` : gomme
- `I` : pipette composite
- `S` : smudge C++
- `F` : pot de peinture contigu
- `G` : dégradé linéaire, radial ou angulaire interactif
- `L` : ligne avec le brush actif
- `R` : rectangle avec le brush actif
- `O` : ellipse avec le brush actif
- `M` : déplacement de calque
- `T` : transformation
- `Espace` : déplacement de la vue
- `H` : outil Main
- `Z` : outil Zoom (clic gauche avant, clic droit arrière; molette également)
- `Maj+R` : rotation de vue par glisser

Les assistants Règle, Ellipse et Perspective à un point sont disponibles dans
le menu **Affichage**. Ils affichent un guide et contraignent les traits du
brush; Maj+clic place le point de fuite de la perspective. Les guides eux-mêmes
restent non destructifs.

## Construction et tests

Installez les dépendances Python avec `python -m pip install -r requirements.txt`.
Les modes de fusion paramétrables sont calculés par CreativeCore ; NumPy n’est
pas requis par le chemin de production.

```bash
cmake -S . -B build_cpp_native -DCMAKE_BUILD_TYPE=Release
cmake --build build_cpp_native -j2
ctest --test-dir build_cpp_native --output-on-failure
python -m unittest discover -s CPP_TEST -p 'test_*.py'
```

Le moteur de dessin et les mutations raster exigent CreativeCore : aucun moteur
Python de secours ne peut modifier le document. PySide6 reste l’adaptateur
d’interface, d’événements et de présentation ; le panneau **BRUSH ENGINE** et
les presets écrivent dans le même état canonique que le Canvas.

La projection native utilise OpenMP si le build l'a activé. La préférence
**CPU → Worker threads** choisit le nombre de threads (`Automatic`, ou une
valeur fixe) ; une ancienne valeur invalide est ignorée et revient en mode
automatique. **Image cache limit** ne borne que le cache composite de
compatibilité, tandis que **Performance → RAM limit** pilote l'éviction des
tuiles et de l'historique. Les tuiles sont fixes à 64 × 64 px pour garder
l'alignement du rendu et de Undo. Les CSD ZIP restent importables. Les projets
Atlas `.atlas` v2/v3 sont aussi importés en lecture seule ; enregistre-les
ensuite en `.nebula` / `.nbl` pour les conserver dans Nebula. Les sources
historiques ne sont jamais écrasées.

La composition native renvoie encore des pixels CPU. Les appels OpenGL et les
textures Qt restent sur le thread UI afin de respecter le contexte du
`QOpenGLWidget`; le transfert vers une texture partagée attend une conception
et une validation de contexte partagé. Les groupes de calques sont pris en
charge ; en revanche, le traitement du stroke lui-même n’est pas encore
entièrement asynchrone.

Les documents modifiables sont enregistrés en `.nebula` (ou `.nbl`). Ce format
est binaire, versionné, tuilé, zlib et contrôlé par CRC ; ce n’est pas une
archive renommée. Les anciens `.csd` ZIP sont encore importables, mais une
sauvegarde les convertit vers le format Nebula sans écraser la source.

La décision produit, la spécification du format et les apports retenus d’Atlas
sont détaillés dans [`docs/NEBULA_PRODUCT_AND_ENGINE.md`](docs/NEBULA_PRODUCT_AND_ENGINE.md).

## Documents denses et mémoire — 26.2.0

Dans **Préférences → Performance**, choisissez un profil RAM : **Prudent**
(35 % de la RAM physique), **Équilibré** (60 %), **Performance** (75 %) ou
**Manuel** pour conserver une limite explicite en MiB. À dépassement, Nebula
libère les caches de projection puis évince les tuiles froides hors viewport
vers le dossier scratch configuré. Une tuile évincée est rechargée à la demande.

Avant tout import PSD/PSB, Nebula affiche un budget de travail estimé et le
coût d’un calque RGBA plein format. Cette estimation décrit les buffers de
l’import progressif, non la RAM finale d’une pile de calques dense. Conservez
un scratch local avec de l’espace libre : en cas d’échec d’écriture, la tuile
reste résidente et le document n’est pas remplacé par des pixels vides.
Le protocole et les limites de qualification sont dans
[`docs/ROADMAP_26.2.0.md`](docs/ROADMAP_26.2.0.md).

## Continuité pendant un rechargement — 26.2.1

Nebula conserve les projections récemment visibles pendant un déplacement et
les remplace seulement quand les tuiles exactes sont prêtes. Le cache distingue
les tuiles visibles, récentes, préchargées et froides ; le pan lent utilise un
halo, le pan rapide précharge une bande directionnelle, et le zoom réduit
favorise le rendu d’ensemble déjà disponible. Un indicateur discret signale un
chargement, sans remplacer la zone par du vide. Les métriques de cette politique
sont accessibles dans l’infobulle RAM. Voir
[`docs/ROADMAP_26.2.1.md`](docs/ROADMAP_26.2.1.md).

La qualification comportementale 26.2.2 et son scénario de viewport sont
documentés dans [`docs/QUALIFICATION_26.2.2.md`](docs/QUALIFICATION_26.2.2.md).

## Nebula 26.3.0 — édition avancée et automatisation

La 26.3 ajoute les sélections combinables et enregistrables, leur persistance
tuilée dans le format natif, les outils de sélection/transformations/masks et
une API de scripts publique `nebula.script.v1` à permissions explicites. Les
ressources partagées transportent désormais version, empreinte de contenu et
dépendances vérifiables. Le périmètre, les scénarios et les limites de
qualification sont consignés dans [`docs/QUALIFICATION_26.3.0.md`](docs/QUALIFICATION_26.3.0.md).
La fermeture d’un document libère ses TileStores natifs et caches de groupes ;
sur Linux, Nebula demande ensuite au système de restituer les pages libérées
afin que le RSS redevienne lisible après un import dense.
Les frontières entre CreativeCore, les adaptateurs Python et l’interface sont
définies dans [`docs/ARCHITECTURE_BOUNDARIES.md`](docs/ARCHITECTURE_BOUNDARIES.md).
La correspondance fonctionnelle Atlas/Nebula, les limites d’import et les
stubs Atlas non repris sont décrits dans
[`docs/ATLAS_TO_NEBULA_MIGRATION.md`](docs/ATLAS_TO_NEBULA_MIGRATION.md).

## Nebula 26.4.0 — dessin raster professionnel

Nebula 26.4.0 fait progresser l’atelier vers un usage de dessin et de peinture
raster exigeant : moteur de pinceau unifié, tracé sous-pixel lissé, gomme fidèle
à la pointe, courbe de pression, dynamiques de stylet, textures ancrées à la
toile et import de pinceaux Photoshop `.abr`. La symétrie radiale propose 2 à
12 copies et un centre librement positionnable.

Sur les documents lourds, le compositeur de calques et les opérations par tuiles
ont été renforcés : bascule de visibilité immédiate, fusion native de calques,
sélections sparse et historique robuste. Les modes de fusion sont étendus à 26
modes et l’interface se concentre sur la toile, les pinceaux, les calques et
l’historique. Les détails et mesures sont dans le
[changelog 26.4.0](docs/CHANGELOG_26.4.0.md).

## Nebula 26.3.1 — qualification et fiabilisation

La 26.3.1 supprime les anciennes structures C++ non reliées au moteur,
fiabilise le redémarrage du dispatcher scratch après fermeture de document et
isole les doublures de tests. Les tests Existence se placent automatiquement
en mode hors-ligne lorsque les sockets Unix sont interdits par l’environnement.
Nebula ne charge aucun plugin : les ressources et extensions restent sous la
responsabilité d’Existence.

La progression vers la version stable est suivie dans
[`ROADMAP_v1.0.md`](docs/archive/ROADMAP_v1.0.md). L'audit v0.3 reste conservé comme
référence historique dans [`ROADMAP_v0.3.md`](docs/archive/ROADMAP_v0.3.md).

Les mesures CPU 8K et les corrections d’historique/sélection du 3 octobre sont
détaillées dans [le rapport de qualification](docs/PERFORMANCE_EDITOR_2026-10-03.md).

La [qualification du PSD réel de 714 Mo](docs/PERFORMANCE_PSD_CREATURE_2026-10-04.md)
détaille les optimisations de chargement, miniatures et cache du 4 octobre.
