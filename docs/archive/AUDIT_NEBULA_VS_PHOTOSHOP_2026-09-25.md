# Nebula — audit comparatif avec Photoshop

Date : 25 septembre 2026  
Périmètre : état réel du code Nebula et des tests natifs, comparé au flux de travail d’un logiciel de peinture/compositing professionnel. Photoshop est une référence d’ergonomie et de production, pas une cible de clonage intégral.

## Verdict

Nebula possède déjà un socle pertinent pour un éditeur raster : document par tuiles, historique natif, calques, groupes imbriqués, masques alpha, écrêtage, réglages non destructifs, transformations et rendu GPU hybride. Il n’est pas encore au niveau de confiance ni de réactivité attendu d’un outil professionnel au stylet.

La bonne prochaine marche n’est **pas** d’ajouter des centaines d’outils. Elle est de verrouiller le chemin critique : `stylet → aperçu → pixels de tuile → historique → composition`. Tant que ce trajet ne tient pas la cible de 8 ms sur les presets complexes, chaque nouvelle fonction augmente le risque de régression.

## Échelle

| Niveau | Sens |
|---|---|
| Prêt | utilisable et couvert par une base technique cohérente |
| Partiel | présent, mais avec limites connues ou chemin lent |
| Absent | à concevoir avant de promettre la fonction |

## Comparatif de capacité

| Domaine | Nebula aujourd’hui | Photoshop de référence | Niveau | Décision |
|---|---|---|---|---|
| Peinture raster | CreativeCore C++, pression, inclinaison, texture, mélange humide, clone, symétrie simple | moteur très optimisé, aperçu immédiat, écosystème de brosses | Partiel | priorité 1 : asynchronisme fiable des presets complexes |
| Réactivité stylet | mesures entrée→peinture et segments natifs, GPU pour pinceau rond simple | réponse visuelle constante, même avec documents lourds | Partiel | imposer 8 ms cible / 16 ms alerte / 40 ms échec |
| Calques raster | opacité, modes, verrous, couleur de calque, déplacement, duplication, fusion | calques, liaisons, options de fusion, effets, objets dynamiques | Partiel | consolider avant effets/objets dynamiques |
| Groupes | groupes imbriqués, repliage, opacité et visibilité | dossiers imbriqués, glisser-déposer libre, masques de groupe | Partiel | rendre le drag-and-drop sûr au sein des groupes |
| Masques de calque | masque alpha par tuiles, miniature liée, clic pour peindre le masque | masque de calque/groupe, sélection, déplacement/copie, densité/contour | Partiel | ajouter aperçu isolé, inversion, appliquer/désactiver, masque de groupe |
| Écrêtage | Alt-clic entre deux calques et indicateur | chaînes d’écrêtage, comportement de groupe complet | Partiel | tests de chaînes, groupes et modes de fusion |
| Réglages | courbes, niveaux, teinte/saturation et autres noyaux disponibles | large catalogue de réglages, masques et propriétés | Partiel | panneau Propriétés unifié et masques de réglage par défaut |
| Sélections | rectangle, ellipse, lasso, baguette, plage de couleurs, opérations et contour progressif | sélection d’objet, sujet, canaux, raffinage de contour | Partiel | corriger précision/feedback avant IA ou raffinage avancé |
| Transformations | affine, perspective, liquify, warp natifs | transformation non destructive, déformation avancée | Partiel | supprimer les artefacts GPU puis ajouter aperçu stable |
| Texte / vecteur | texte éditable et Bézier rasterisés au rendu | texte, formes, tracés, styles vectoriels éditables | Partiel | ne pas annoncer une compatibilité PSD vectorielle |
| Couleur | profils et conversions de base, sRGB opérationnel | CMJN/Lab, 8/16/32 bits, gestion couleur complète | Partiel | définir d’abord une politique sRGB 8 bits fiable |
| PSD | import/export raster, opacité, certaines structures et masques | format natif complet, Smart Objects, effets, texte, canaux | Partiel | jeux de vrais PSD + rapport de pertes explicite |
| Format Nebula | tuiles, compression, récupération, historique | PSD mature et résilient | Partiel | tests de coupure d’écriture, migration et fichiers corrompus |
| GPU | upload PBO, présentation, zoom/rotation/miroir, composition standard et pinceau simple | composition et aperçu complets GPU | Partiel | composition GPU par passes, sans wrapper PySide instable |
| Ressources | presets `.csbr`, catégories, dock ressources amorcé | bibliothèques cloud, pinceaux, motifs, formes, dégradés, palettes | Partiel | catalogue commun versionné : brush, gradient, palette, texture |
| Automatisation | raccourcis, actions UI | actions enregistrables, scripts, plugins | Absent | hors chemin critique |
| Smart Objects / filtres dynamiques / IA / vidéo / 3D | non visés aujourd’hui | disponibles selon les versions Photoshop | Absent | ne pas les planifier avant la v1 stable |

## État des fondations techniques

### Ce qui est sain

- CreativeCore est le moteur natif des pixels, tuiles, historique et de nombreuses opérations.
- Les tuiles évitent de matérialiser un document entier pour chaque petite modification.
- L’historique est stocké par deltas de tuiles, adapté aux gros documents.
- La projection complexe est déjà asynchrone côté natif et est présentée par le GPU.
- Les chemins GPU dangereux PySide ont été remplacés par des appels OpenGL natifs limités.
- La suite native passe : **11 tests sur 11** au moment de cet audit.

### Risques techniques actuels

1. Le pinceau complexe s’exécute encore depuis le chemin d’entrée UI. Texture, dispersion, humide, clone, symétrie et dynamiques peuvent donc dépasser le budget de frame.
2. Les documents avec groupes, masques, écrêtage ou réglages sont composés exactement sur CPU puis affichés par GPU. C’est correct visuellement, mais pas encore une composition GPU complète.
3. Les masques nouvellement éditables doivent recevoir des tests d’historique, d’écrêtage et de sauvegarde, surtout après un long trait.
4. La conversion d’une image de compatibilité en image complète reste coûteuse pour certains outils. Aucun chemin ne doit la déclencher à chaque dab.
5. Les tests Python dépendent encore du dossier de presets utilisateur ; ils doivent pouvoir tourner dans un répertoire de données temporaire et isolé.

## Ce que Photoshop fixe comme référence UX

- Un masque sélectionné est un vrai support de peinture : noir masque, blanc révèle, gris atténue ; la miniature distincte indique clairement la cible active. [Adobe : modifier un masque de calque](https://helpx.adobe.com/photoshop/using/editing-layer-masks.html)
- Les groupes sont des dossiers repliables et peuvent être imbriqués par glisser-déposer. [Adobe : groupes de calques](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/get-started-layers/organize-layers-with-layer-groups.html)
- L’écrêtage repose sur le calque de base, peut contenir plusieurs calques contigus et se crée notamment par Alt/Option-clic entre deux calques. [Adobe : masques d’écrêtage](https://helpx.adobe.com/ca/photoshop/using/revealing-layers-clipping-masks.html)
- Les réglages sont non destructifs et se contrôlent depuis un panneau de propriétés ; Photoshop propose un catalogue plus large que Nebula aujourd’hui. [Adobe : calques de réglage](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/color-adjustment-fill-layers/work-with-adjustment-and-fill-layers.html)

## Feuille de route recommandée

### Palier A — rendre le dessin professionnel (bloquant)

1. **Worker natif de pinceau complexe**
   - une file FIFO de segments par trait ;
   - un état de pinceau isolé et clonable dans CreativeCore ;
   - sortie par régions de tuiles terminées, jamais par image complète ;
   - annulation sûre à la fin d’un trait ou d’un changement de document ;
   - un seul commit d’historique lorsque le worker confirme la fin.

2. **Aperçu immédiat réconcilié**
   - aperçu GPU approximatif pour la réactivité visuelle ;
   - résultat CreativeCore exact remplace uniquement les tuiles concernées ;
   - contrôle de divergence : comparaison de patch sur les presets représentatifs.

3. **Banc de mesure réel**
   - journal local par preset : p50/p95/max pour entrée→aperçu, calcul de dab, upload et frame ;
   - protocole : document 8k, 20 calques, masque + groupe, 5 presets, 60 secondes chacun ;
   - objectif : p95 sous 8 ms ; avertissement à 16 ms ; correction obligatoire à 40 ms.

**Critère de sortie :** un trait complexe continu ne fige jamais la fenêtre, l’Undo restaure exactement le trait, et le résultat est identique avec GPU activé ou désactivé.

### Palier B — composition complète et exacte

1. Conserver CreativeCore comme oracle de parité par tuile.
2. Ajouter des passes GPU explicitement séparées : calque → masque → chaîne d’écrêtage → groupe → réglage → fusion.
3. Ne basculer un type de document vers le GPU que lorsqu’un test de parité pixel-à-pixel existe contre l’oracle CPU.
4. Garder un fallback CPU automatique et visible dans les diagnostics, pas dans le rendu utilisateur.

Ordre conseillé : masques simples, chaînes d’écrêtage, groupes normaux, réglages, modes de fusion complexes, puis groupes imbriqués avec réglages.

**Critère de sortie :** lors d’un panoramique/zoom sur un document lourd avec groupes et masques, le GPU compose les tuiles visibles sans recalcul CPU synchrone sur le thread UI.

### Palier C — solidité documentaire

1. Fixtures PSD réelles : raster, groupes, masques, écrêtages, réglages, texte, éléments non supportés.
2. Rapport d’import : ce qui a été conservé, rasterisé ou ignoré.
3. Écriture atomique Nebula, simulation de coupure, récupération et migrations versionnées.
4. Tests : source CSD/Atlas/PSD jamais modifiée par une conversion.

### Palier D — UX de production

1. Dock Calques : drag-and-drop au sein des groupes, masques de groupe, aperçu isolé de masque, appliquer/désactiver/inverser un masque.
2. Dock Ressources : aperçus asynchrones, import/export par type, recherche, catégories repliables, gradients/palettes/textures.
3. Sélections : overlay stable, transformations sans artefact, raccourcis et retour d’état clair.
4. Accessibilité stylet : cibles de 32–36 px minimum et aucune action essentielle cachée uniquement dans un menu.

## Ce qu’il ne faut pas faire maintenant

- Ajouter IA, Smart Objects, vidéo, 3D ou un catalogue massif de filtres.
- Promettre une compatibilité PSD complète.
- Forcer tous les documents sur le GPU sans tests de parité.
- Optimiser par des copies d’images complètes ou en bloquant le thread UI.
- Masquer les limitations derrière un fallback silencieux.

## Prochaine tâche unique recommandée

**Construire le worker C++ de pinceau par tuiles avec protocole de performance.**

C’est le multiplicateur principal : il améliore le stylet, les gros pinceaux, le mélange humide, les filtres localisés et la sensation générale du logiciel. La composition GPU complète vient juste après, sur une base de tests de parité.
