# CreativeSystem Nebula — direction produit et intégration d’Atlas

Dernière révision : 21 septembre 2026

## Décision produit

Nebula devient l’unique application de dessin. Atlas n’est pas maintenu comme
second logiciel généraliste : ses apports utiles sont évalués et intégrés dans
Nebula, sans importer ses prototypes inachevés. Le dépôt Atlas reste une
référence consultable pendant la transition.

## État réel des deux bases

### Nebula

- Interface PySide6/Qt avec docks, préférences et gestion de documents.
- Moteur de brosse natif C++ exposé à l’interface Python ; l’application refuse
  explicitement de peindre si le bridge natif ne peut pas être chargé.
- Calques clairsemés découpés en tuiles de 64 × 64 px ; le stockage résident,
  les révisions, l’accès LRU et les opérations batch sont maintenant dans
  `NativeTileStore` C++. Scratch, callbacks Qt et une partie de l’éviction restent
  orchestrés par l’adaptateur Python.
- Le modèle structurel document/calques est maintenant possédé par CreativeCore
  et reflété dans les objets Qt ; l’orchestration Undo/Redo, plusieurs gestes
  interactifs et une partie de l’éviction restent à centraliser.
- Les opérations raster affines (translation, échelle, rotation et déplacement
  du masque) et les primitives du masque de sélection sont maintenant natives ;
  les gestes, previews et transactions Undo restent pilotés par Python/Qt.

### Atlas alpha 0.1

- Interface GTK4 native Linux/Wayland et moteur C++ séparé de l’interface.
- TileStore, éviction vers scratch et abstractions de calques en C++.
- Présentateur GPU expérimental et désactivé par défaut ; sa propre
  documentation relève des défauts d’échelle, de composition et de
  superposition de l’interface.
- Plusieurs outils visibles ne sont pas implémentés, certaines opérations ne
  sont pas annulables et l’interface n’utilise pas le modèle de calques du
  moteur.

Les deux bases n’ont donc pas encore des usages artistiques assez distincts
pour justifier deux applications.

## Apports retenus

1. **Scratch sur stockage persistant par défaut.** `/tmp` peut être un tmpfs et
   ne pas réduire la pression mémoire. Nebula crée désormais son répertoire
   temporaire dans `$XDG_CACHE_HOME/creativesystem/scratch`, ou dans
   `~/.cache/creativesystem/scratch`, puis utilise le dossier temporaire système
   seulement en dernier recours. Un emplacement sélectionné dans les
   préférences reste prioritaire pour les tuiles.
2. **Conserver le TileStore éprouvé de Nebula.** Il possède déjà l’éviction LRU,
   les lectures asynchrones, les révisions et l’historique déporté. Le TileStore
   Atlas ne le remplace pas.
3. **Réutiliser les principes, pas le rendu expérimental.** La séparation
   « moteur calcule, interface présente » reste une cible utile. Le chemin GPU
   d’Atlas n’est pas transplanté, car son audit signale des défauts visuels
   bloquants.
4. **Ne migrer un outil qu’avec son cycle complet.** Entrées souris et tablette,
   aperçu, validation, annulation/rétablissement, sauvegarde et rechargement
   doivent être vérifiés ensemble.

## Format natif Nebula

Les nouveaux documents sont enregistrés dans le format binaire versionné
Nebula, sous l’extension longue `.nebula` ou l’alias court `.nbl`. Ce n’est pas
un ZIP renommé : le fichier contient une signature et une version, des
métadonnées UTF-8, puis des enregistrements de tuiles RGBA compressés et
contrôlés par CRC. Les tuiles sont traitées séparément pour éviter de construire
un deuxième tampon géant pendant la sauvegarde.

### Spécification binaire, version 1

Tous les entiers des en-têtes sont little-endian. La structure de fichier est :

1. En-tête fixe `<4sHHII` : signature `NEBL`, version majeure `1`, indicateurs
   réservés à `0`, taille des métadonnées et nombre d’enregistrements.
2. Métadonnées JSON UTF-8 compactes, avec dimensions, DPI, calques, groupes,
   sélection, images de référence, textes et table des tuiles.
3. Pour chaque tuile, en-tête `<4sIQQI` : type `TILE`, identifiant, taille brute,
   taille compressée, CRC-32 du contenu brut ; il est suivi d’un bloc compressé
   par `qCompress` (taille brute préfixée sur 4 octets, puis flux zlib).

Les tuiles sont des pixels RGBA 8 bits, rangées sans padding additionnel. Les
tuiles absentes d’un calque restent absentes dans le fichier. Les limites de
taille du manifeste, du nombre d’enregistrements et des blocs sont contrôlées à
la lecture ; la sauvegarde se fait dans un fichier temporaire puis est publiée
par remplacement atomique dans le codec C++ `CPP_CORE/src/nebula_serialization.cpp`.
Python transmet une tuile à la fois et assemble les métadonnées document ; il
ne compresse ni n’écrit directement l’enveloppe du fichier. Toute évolution
incompatible doit incrémenter la version majeure ; les anciens `.csd` passent
par l’importeur ZIP séparé.

Les `.csd` existants restent ouvrables comme documents historiques. Ils sont
importés en lecture seule au niveau du format : **Enregistrer** les oriente vers
une nouvelle sauvegarde `.nebula` / `.nbl`, sans écraser le fichier source.
Les projets `.atlas` v2/v3 sont également importés en lecture seule par le
lecteur C++ dédié ; leurs pixels et propriétés de calque sont convertis vers
Nebula. Les limites (masques éditables, vue sauvegardée, auteur) sont listées
dans [`ATLAS_TO_NEBULA_MIGRATION.md`](ATLAS_TO_NEBULA_MIGRATION.md).
Les fichiers PNG/JPEG/TIFF/BMP restent des exports aplatis et ne remplacent pas
le document éditable.

## Direction visuelle

Le thème Nebula emploie un bleu nuit profond, une lumière violette diffuse,
quelques étoiles discrètes et des accents cyan/or. La décoration est surtout
visible sur l’accueil et les panneaux ; le canvas garde son damier et ses
couleurs neutres pour ne pas fausser le jugement de l’œuvre.

Les couleurs partagées sont dans `UI/theme/palette.py`, les widgets communs
dans `UI/theme/dark.qss`, et le champ stellaire déterministe de l’accueil dans
`UI/home/home_page.py`.

## Suite de la convergence

- Tester le scratch sous forte pression mémoire, notamment les erreurs disque
  plein et la restauration des tuiles évincées.
- Réduire les copies d’image complète dans la composition, les transformations
  et les autres parcours d’édition.
- Déplacer progressivement les opérations document/calques encore en Python
  vers une API C++ stable, accompagnée de tests de parité.
- Garder PySide6/Python pour les docks et l’expérience visuelle, sans y
  dupliquer la logique de l’engine.
- La couverture fonctionnelle de l’application Atlas alpha retenue est
  raccordée à Nebula ; les extensions non opérationnelles sont documentées
  comme hors périmètre. L’importeur doit encore être essayé sur des fichiers
  `.atlas` réels en plus des fixtures versionnées.
- Le transfert complet de la logique applicative Python vers le cœur C++ reste
  un chantier distinct et non terminé.

## Vérifications

- Python : `python -m unittest discover -s CPP_TEST -p 'test_*.py'`
- C++ : `ctest --test-dir build_cpp_native --output-on-failure`
- UI : lancement Qt hors écran et capture de l’écran d’accueil Nebula.
