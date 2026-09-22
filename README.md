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

===================En Cours===================

Acceleration Nebula par GPU
Séparation des tache GPU / CPU 

L'upload GPU ne sera disponnible que lorsqu'il sera stable
