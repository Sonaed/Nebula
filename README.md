# CreativeSystem Nebula
Made with ai until I become better at coding 
Application de dessin PySide6/Qt 6 avec Canvas OpenGL et moteur de brush C++.

<img width="2555" height="1430" alt="image" src="https://github.com/user-attachments/assets/71306f37-b3eb-48cf-967c-11c60c161338" />


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

Actuellement l'accélération à l'air de marcher, teste réel en cours.
Refonte du dock Layers en cours aussi

Existence et Atlas auront des updates avant nebula le temps de validé les modifications effectué 
  -Atlas First
  -Extistence Second
  -Retour a nebula quand les teste terrain sont réussi

  -----------------------------------------------------
  Grosse Update sur la totalité de l'application
