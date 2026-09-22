# CreativeSystem Nebula

Application de dessin PySide6/Qt 6 avec Canvas OpenGL et moteur de brush C++.

## Outils

- `B` : pinceau
- `E` : gomme
- `I` : pipette composite
- `S` : smudge C++
- `F` : pot de peinture contigu
- `G` : dégradé linéaire interactif
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
Les frontières entre CreativeCore, les adaptateurs Python et l’interface sont
définies dans [`docs/ARCHITECTURE_BOUNDARIES.md`](docs/ARCHITECTURE_BOUNDARIES.md).
La correspondance fonctionnelle Atlas/Nebula, les limites d’import et les
stubs Atlas non repris sont décrits dans
[`docs/ATLAS_TO_NEBULA_MIGRATION.md`](docs/ATLAS_TO_NEBULA_MIGRATION.md).

La progression vers la version stable est suivie dans
[`ROADMAP_v1.0.md`](ROADMAP_v1.0.md). L'audit v0.3 reste conservé comme
référence historique dans [`ROADMAP_v0.3.md`](ROADMAP_v0.3.md).
