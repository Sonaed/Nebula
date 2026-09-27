# Nebula — audit de stabilité

Date : 24 septembre 2026

## Résumé

Le noyau natif C++ est valide et le démarrage de l’application est stable en mode CPU. En revanche, la version installée de PySide6 avec CPython 3.14 rend le chemin Qt/OpenGL dangereux : il peut provoquer une fermeture native sans message (`SIGSEGV`). Le GPU est donc désactivé automatiquement sur cette combinaison afin de garantir la sauvegarde et le travail de dessin.

Le point le plus important avant de déclarer une version stable est de rendre la campagne de tests Python réellement reproductible. Elle contient des tests pertinents pour le stylet, l’historique, les outils et les calques, mais 56 d’entre eux ne peuvent actuellement pas démarrer dans un profil non inscriptible car la bibliothèque de presets utilise un chemin utilisateur codé en dur.

## Résultats vérifiés

| Contrôle | Résultat | Observation |
|---|---:|---|
| Tests C++ (`ctest`) | 11 / 11 réussis | stockage de tuiles, historique, groupes, cache, projection et SIMD |
| Démarrage applicatif CPU | réussi | création du canvas, chargement de plusieurs presets et fermeture normale |
| GPU sur PySide6 + Python 3.14 | bloqué volontairement | évite un `SIGSEGV` dans `QtOpenGL` / Shiboken |
| Tests Python complets | non validables | 288 lancés : 56 erreurs de profil de presets, 4 échecs distincts, 4 ignorés |
| Documents CSD / sauvegarde atomique | couverts par tests | les scénarios de fichiers abîmés et d’échec d’écriture sont présents et passent |
| Import Atlas | couvert par tests de fixtures | vrais fichiers Atlas reportés, conformément à la décision produit |

## Bloquants avant une version stable

### 1. GPU indisponible avec le runtime actuel

**Impact : élevé.** Le chemin GPU est bien présent dans le code, mais il ne doit pas être activé avec PySide6 6.11 et CPython 3.14 : le binding QtOpenGL segfault dans du code natif avant qu’une erreur Python puisse être interceptée.

**État actuel :** GPU hybride qualifié et actif : transfert des tuiles, présentation, zoom, rotation et miroir sont exécutés sur GPU. La composition shader des calques standards et le pinceau instancié rond utilisent désormais le chargeur OpenGL natif sûr, sans le wrapper PySide6 `QOpenGLFunctions_3_3_Core` responsable du crash. Les documents complexes conservent volontairement la projection CreativeCore exacte.

**Qualification effectuée :** la RTX 2060 et OpenGL 4.6 NVIDIA ont été vérifiés après réparation des périphériques NVIDIA manquants. Une session Nebula de 18 secondes avec GPU actif s’est terminée normalement, avec uploads PBO et rendu de tuiles confirmés. Le GPU est donc réactivé par défaut, sans les deux sous-chemins QtOpenGL instables.

**À faire :** remplacer les wrappers PySide6 restants de composition et de stroke par une implémentation native avant de réactiver leurs shaders.

### 2. La campagne de tests UI/canvas n’est pas isolée

**Impact : élevé.** `BrushPresetManager` cible toujours `~/.local/share/CreativeSystem/brush_presets` au lieu d’un emplacement configurable. Si ce dossier est non inscriptible, la création d’un Canvas échoue, et 56 tests échouent avant d’atteindre leur assertion.

**Conséquence :** la couverture existante pour souris, stylet, Undo/Redo, verrous, sélection, transformation et UI ne donne pas encore un feu vert de livraison reproductible.

**À faire :** rendre le répertoire de données conforme à `XDG_DATA_HOME` et injectable dans les tests. Chaque test doit recevoir un profil temporaire, sans toucher aux presets réels de l’utilisateur.

### 3. Régression de la règle d’architecture C++

**Impact : moyen à élevé.** `test_architecture_boundaries` échoue et relève :

- `DOCUMENTS/format_psd.py` utilise `.copy()` ;
- `DOCUMENTS/tile_store.py` utilise `QPainter`.

Ce n’est pas nécessairement un bug visuel, mais cela contredit le garde-fou qui interdit les opérations raster Python dans le document et les outils. Il faut soit déplacer ces opérations derrière une API native, soit préciser et documenter une exception limitée à l’import/export.

## Défauts de qualité confirmés

### Test de palette fragile

`test_ui_colors_are_palette_tokens` échoue uniquement parce qu’il attend une ligne précise de `tools_dock.py` (611) alors que le code est à la ligne 619. Le test doit vérifier la règle de style, pas un numéro de ligne. Il ne révèle pas une panne UI visible, mais il casse inutilement la validation.

### Tests du connecteur Existence non exécutables dans le bac à sable

Les deux tests socket Unix échouent ici car le processus n’a pas le droit de créer son socket dans l’environnement isolé. À relancer sur la machine normale ou à modifier pour utiliser un dossier temporaire autorisé. Ce résultat ne permet pas de conclure à un défaut du connecteur.

## Zones à risque à tester manuellement après correction de la campagne

1. **Pinceau et stylet** : trait lent, trait très rapide, pression, inclinaison, gomme, grande taille, bord du canvas, changement de preset pendant un trait.
2. **Historique** : Undo/Redo après pinceau, remplissage, transformation, sélection, Alpha Lock, verrou de calque et suppression/merge de calques.
3. **Calques** : glisser-déposer, groupes repliés, écrêtage Alt-clic, masque, opacité, modes de fusion et renommage direct.
4. **Documents** : sauvegarder, fermer, rouvrir, écraser, interrompre une sauvegarde, ouvrir un fichier corrompu et vérifier que la source reste intacte.
5. **CPU/GPU** : avec le runtime actuel, vérifier exclusivement le CPU. La parité CPU/GPU doit être validée seulement sur un environnement GPU stable.

## Priorités recommandées

1. Corriger l’isolation du répertoire de presets et remettre la suite Python au vert.
2. Décider officiellement quelles exceptions raster Python sont admises pour l’import/export, ou les transférer dans CreativeCore.
3. Stabiliser un environnement GPU compatible puis valider strokes, transformations et composition sur matériel réel.
4. Exécuter la matrice manuelle ci-dessus et convertir chaque anomalie trouvée en test automatisé.

## Conclusion de livraison

Nebula est utilisable en **CPU sécurisé**, mais ne doit pas encore être annoncé comme entièrement validé ni comme accéléré GPU sur la configuration actuelle. Les documents CSD et le cœur C++ disposent d’une base de tests solide ; la priorité est maintenant la fiabilité de la validation UI/canvas et la qualification du runtime graphique.
