# Nebula 26.4.0 — Dessin raster, performances et atelier

Date : 12 octobre 2026

## Moteur de pinceau (CreativeCore)

### Corrections

- **L'opacité du pinceau est enfin respectée.** Le tampon de trace était
  recomposé sur le pixel déjà peint après chaque dab : un trait à 40 %
  d'opacité qui se chevauchait montait à ~100 %. Le tampon conserve
  désormais la valeur de chaque pixel *avant* le trait et recompose toujours
  depuis cette origine (modèle Photoshop/Krita). Avec l'opacité à la
  pression, appuyer plus fort fonce la zone, mais un passage léger
  n'éclaircit jamais une zone déjà foncée.
- **Tampon creux par tuiles de 64 px.** Seule la zone peinte est allouée :
  un document 8K ne réserve plus 256 Mo de masque flottant à chaque trait.
- **Gomme.** Elle utilise maintenant la vraie pointe du pinceau (dureté,
  forme, texture, pointe bitmap, position sous-pixel) et le même tampon :
  une gomme dure efface net, une gomme à 50 % plafonne à 50 %. Avant, c'était
  toujours un cône flou aimanté sur la grille de pixels.
- **Anticrénelage des pointes dures.** Le profil de dureté tombait à zéro pile
  sur le rayon et coupait la moitié extérieure de l'anticrénelage : les
  pointes dures étaient ~0,5 px trop fines avec un bord extérieur crénelé.
- **Précision sous-pixel de bout en bout.** Les positions du stylet étaient
  arrondies au pixel entier avant d'atteindre le moteur (et à nouveau après
  le stabilisateur) : traits lents ou zoomés en escalier, bandes visibles sur
  les traits à la pression. Les coordonnées restent flottantes jusqu'au
  rasteriseur.
- **Le stabilisateur fonctionne.** Le réglage « Lissage » était remis à 0 au
  début de chaque trait par la synchronisation des réglages : il n'avait
  aucun effet. Il est aussi appliqué sur le chemin asynchrone (stylet avec
  toile GPU), qui l'ignorait.
- **Fin de trait stabilisée.** Au levé du stylet, le trait rattrape le point
  réel au lieu de s'arrêter là où le lissage traînait encore.
- **Un seul moteur de rendu.** Le chemin « GPU instancié » rendait sa propre
  approximation du pinceau (pas de tampon de trace, pas de courbe de
  pression, accumulation 8 bits, dabs doublés aux jointures) et la validait
  comme pixels finaux. Tous les traits passent maintenant par CreativeCore
  (threadé quand la toile GPU est active) : ce qu'on voit pendant le trait
  est exactement ce qui est enregistré.
- Le stabilisateur repart du point d'appui à chaque trait.

### Tests ajoutés

`CPP_TEST/test_brush_stroke_quality.py` (pilote de vrais évènements tablette) :
plafond d'opacité, opacité à la pression, gomme dure et gomme à 50 %,
précision sous-pixel, anticrénelage symétrique des pointes dures,
persistance du stabilisateur, fin de trait stabilisée.

## Interface

- Le panneau d'un module Existence (Pixel Art, Fusion) ne s'ouvre plus tout
  seul par-dessus Calques ni sur l'écran d'accueil : il rejoint le groupe
  masqué, accessible par Fenêtre ▸ Panneaux.
- Onglets de panneaux plats avec soulignement d'accent ; l'en-tête en
  majuscules répété sous chaque onglet est masqué quand le panneau est dans
  un groupe d'onglets (il revient quand le panneau est seul ou flottant).
- Barre d'onglets orpheline supprimée (trait parasite sous le menu
  « Fichier ») ; poignée fine pour le rail d'outils au lieu d'un titre « … ».
- Barre d'état : plus de badge « CreativeCore C++ » ni de compteurs
  RAM/GPU/tuiles en permanence. La mémoire s'affiche seule si elle dépasse le
  budget, ou toujours via Préférences ▸ Interface. Barre d'état masquée sur
  l'écran d'accueil (aucun document).
- Calques : icônes Phosphor au lieu de symboles Unicode illisibles, en-tête
  « CALQUES » redondant retiré, suppression mise à part, modes de fusion en
  français.
- Couleur : pastilles avant/arrière-plan redessinées (les libellés « ⇄ » et
  « D/W » chevauchaient la pastille), aperçu en double retiré, sections
  « Couleurs récentes » et « Palette » vides repliées.
- Préférences : entièrement en français, 7 pages au lieu de 12, et retrait
  des réglages qui n'avaient aucun effet (langue, infobulles, confirmation de
  sortie, gestion des couleurs, repli CPU, copies de récupération).
- Menus : « Exporter » rejoint Fichier (le menu Image ne contenait que
  cela), Calque et Affichage regroupés, menu Outils dans l'ordre du rail,
  libellés harmonisés, raccourci du mode focus dans la colonne des
  raccourcis, doublon « Afficher les Ressources » retiré (raccourci
  Ctrl+Maj+R conservé), espace « Default » affiché « Par défaut ».
- `LAYOUT_VERSION` passe à 6 : l'agencement par défaut est réappliqué une
  fois au premier lancement (les espaces de travail enregistrés par
  l'utilisateur sont conservés).

## Qualification

| Domaine | Résultat |
| --- | --- |
| Suite Python | 579 tests, 0 échec (6 ignorés) |
| Suite C++ | 14/14 |

À recompiler sur la station : `cmake --build build_cpp_native -j` (les
corrections du moteur sont dans `CPP_CORE/`).

## Presets de pinceau (révision 3)

- Les gommes (Eraser Soft/Hard/Pencil/Airbrush) effacent aussi depuis l'outil
  Pinceau ; avant, elles peignaient en noir.
- Blender et Smudge déplacent la peinture existante au lieu de déposer la
  couleur.
- Changer de preset conserve la couleur choisie (chaque preset la remplaçait,
  souvent par du noir).
- Pointes procédurales refaites (bruit lissé) : Spray en gouttelettes,
  Dry Brush en poils qui suivent le trait, grain réel pour Crayon, Craie et
  Fusain. Fini le moiré et les rayures « code-barres ».
- Glow en mode Écran (il était en Produit et assombrissait).
- Marker à ton constant, Concept Block à 60 px, Stipple en points nets.
- Catégories lisibles (Esquisse, Encrage, Peinture…), Ctrl+Alt+1-4 pointent
  vers Pencil HB, Ink Pen, Oil Round, Charcoal.
- Mise à niveau automatique des presets d'usine ; les presets personnels ne
  sont pas modifiés.

## Finition « pro » des panneaux pinceau

- Presets de pinceau : une seule liste lisible à toutes les largeurs,
  vignettes rendues avec la vraie pointe de chaque preset (trait clair, gomme
  et mélangeur montrés sur un fond coloré), en-têtes de catégorie pleine
  largeur, noms complets. Barre d'actions réduite à Nouveau / Réglages / « … »
  (toutes les autres actions dans le menu). Textes entièrement en français.
- Panneau Pinceau : libellés français (Pointe et forme, Dynamique, Flux…),
  valeurs normalisées affichées en %, angles en °, aperçu lisible.
- Réglages du pinceau : mêmes unités, plus de champs à 3 décimales, onglets
  renommés, bouton « Fermer ».

## Passe « niveau pro » : panneaux, outils, code

### Interface
- Couleur : la roue occupe toute la largeur, curseurs TSV/TSL/RVB toujours
  visibles dessous, palette de départ de 16 couleurs ; palette et couleurs
  récentes en grille, conservées entre les sessions (clic droit : retirer).
- Calques : 4 actions sur la barre (nouveau, masque, groupe, supprimer) ; le
  reste (dupliquer, dégrouper, verrous, masque…) dans le menu « … ».
- Pinceaux d'usine renommés en français (Crayon HB, Stylo encre, Rond doux,
  Aérographe doux, Gomme douce…). Les noms anglais et les anciens noms
  restent reconnus ; les fichiers déjà installés sont renommés au lancement,
  les presets personnels ne sont pas touchés.

### Fonctionnalités
- Palette rapide au clic droit sur la toile : roue, taille, opacité,
  couleurs récentes et pinceaux favoris (Préférences ▸ Stylet et pinceau
  pour revenir à la pipette ; Alt+clic reste la pipette).
- Raccourcis de peinture standard : [ / ] taille, 1…0 opacité, X inverser
  les couleurs, D noir/blanc. Ajoutés à l'aide F1.

### Stabilité
- Correction : Sélection ▸ Depuis la transparence du calque plantait
  (format de pixels refusé par le noyau natif).
- Test de stress : les 95 actions des menus déclenchées trois fois, avec
  traits, outils et presets intercalés, puis 60 annuler/rétablir :
  0 exception.

### Code mort retiré
- ~600 lignes de fonctions jamais appelées, 3 modules jamais importés,
  ~250 lignes de presets historiques remplacés par des alias, imports
  inutilisés. La palette contextuelle, écrite mais jamais branchée, a été
  réécrite et activée.
- Racine du projet nettoyée : audits et roadmaps rangés dans docs/archive/,
  scripts de test isolés, profils et images de debug supprimés.

| Suite Python | 588 tests, 0 échec (6 ignorés) |
| --- | --- |

## Sensation « pro » : tracé, toile, barre d'options

- Tracé courbe : les échantillons du stylet sont reliés par une courbe de
  Catmull-Rom (sous-segments de ≤ 3 px) au lieu de segments droits. Un geste
  rapide ne dessine plus de ligne brisée. Coût : un échantillon de retard
  (~5 ms à 200 Hz) ; une ligne droite reste exactement droite.
- Toile : damier de transparence clair (jetons du thème, ignorés jusque-là
  au profit d'un gris très sombre), ombre portée et liseré autour du
  document.
- Barre d'options : la liste « Presets… » devient une puce montrant
  l'aperçu et le nom du pinceau actif, avec un menu (favoris puis
  catégories, chaque pinceau avec son aperçu). L'espace de travail affiche
  son nom au lieu de « Espace… ».
- Correction : le nom du preset est enregistré avant la notification de
  changement de réglages (les panneaux lisaient l'ancien nom).

## Pinceau et réactivité : niveau pro

### Nouvelles fonctions
- Édition ▸ Courbe de pression du stylet… : courbe globale éditable (points
  à glisser, double-clic pour ajouter, clic droit pour retirer), modèles
  (Linéaire, Doux, Très doux, Ferme, Courbe en S), zone d'essai qui montre la
  position du stylet sur la courbe en direct. Spline monotone : la réponse
  ne redescend jamais entre deux points.
- Grain papier : la texture des crayons, du fusain, de la craie et du Conté
  est fixée à la feuille (plus répétée dans chaque touche) et appliquée au
  trait entier. Modèle « hauteur » : une touche légère ne marque que les
  fibres en relief, appuyer comble le grain. Nouveau réglage natif
  textureCanvasSpace (presets révision 4).
- Tracé courbe à la souris aussi (même interpolation que le stylet).

### Corrections
- Hachures rapides : poser le stylet juste après l'avoir levé annulait la
  fin du trait précédent (rendu asynchrone interrompu). Le trait précédent
  est désormais terminé avant le suivant.
- Bandes claires régulières dans les traits à variation de luminosité : la
  couleur du tampon de trace changeait à chaque touche et recolorait toute
  la zone. Couleur fixée par trait (sauf dégradé le long du trait).
- Chaque trait rejouait la même séquence « aléatoire » (dispersion, taille,
  rotation) : deux traits identiques semblaient tamponnés. Graine renouvelée
  à chaque trait.

### Démarrage
- 2,0 s → 1,5 s jusqu'à l'écran d'accueil : installation des presets une
  seule fois par processus, lecture JSON mise en cache, aperçus du panneau
  Presets rendus à sa première ouverture.

| Suite Python | 595 tests, 0 échec (6 ignorés) |
| --- | --- |
| Suite C++ | 14/14 |

À recompiler sur la station : `cmake --build build_cpp_native -j`.

## Pinceaux Photoshop (.abr) et peinture humide

### Import .abr
- Lecture des fichiers .abr modernes (versions 6, 7, 9 et 10, tous les
  Photoshop depuis CS) : pointes échantillonnées (RLE), motifs de texture
  (gris / RVB), et descripteur des presets.
- Conversion : nom, taille, espacement, angle, rondeur, dureté (pointes
  calculées), pression sur taille / opacité / flux avec minimums,
  variation de taille et d'angle, direction, dispersion, texture (fixée à la
  feuille sauf « texture par pointe »), profondeur et échelle du motif.
- Non convertis, et signalés dans le rapport d'import : double pointe,
  dynamique de couleur. Les .abr de Photoshop 7 et antérieurs sont refusés
  avec un message clair.
- Panneau Presets ▸ Importer (filtre .abr) ou glisser-déposer un .abr sur
  la fenêtre. Chaque fichier crée sa catégorie « Importé — <nom> » ; les
  noms en double sont numérotés.
- Vérifié sur trois packs réels (v6, v9, v10) : 55 pinceaux, 2,5 s.
- La fenêtre accepte aussi le glisser-déposer de documents et d'images.

### Peinture humide
- Nouveau rendu pixel par pixel pour les pinceaux humides et l'estompe :
  la peinture réelle est traînée depuis la touche précédente (le détail est
  conservé), le pigment du réservoir s'y mélange, la dilution réduit
  l'opacité, et la transparence est respectée (plus de blanc inventé sur
  un calque vide).
- Taux de pigment exprimés par quart de diamètre parcouru : l'espacement
  ne change plus la sensation (un espacement serré rendait le trait opaque
  et sans mélange).
- Textures : échantillonnage bilinéaire (plus de blocs carrés sur les
  motifs agrandis) ; les micro-motifs de moins de 16 px restent nets.

| Suite Python | 600 tests, 0 échec (6 ignorés) |
| --- | --- |
| Suite C++ | 14/14 |

À recompiler sur la station : `cmake --build build_cpp_native -j`.

## Double pointe et colorisation

### Double pointe (dual brush)
- Moteur natif : une seconde pointe (image ou ronde) est tamponnée le long du
  même tracé, avec sa taille (relative à la pointe principale), son
  espacement, sa dispersion et son nombre ; la pointe principale n'apparaît
  que là où la seconde a encré. Huit modes de fusion comme Photoshop :
  Produit, Obscurcir, Densité couleur +, Densité linéaire +, Incrustation,
  Densité couleur −, Mélange maximal, Hauteur linéaire.
- Réglable sur n'importe quel pinceau : section « Double pointe » du panneau
  Pinceau et des réglages complets.
- Import .abr : la double pointe et son mode de fusion sont maintenant
  convertis (les brosses Rutkowski / MB retrouvent leurs bords cassés), ainsi
  que la dynamique de couleur (teinte, saturation, luminosité).

### Pot de peinture pour la colorisation
- Barre d'options : tolérance, « Suivre tous les calques » (la zone suit
  l'encrage visible, la couleur va sur le calque actif — aplats sur un
  calque séparé), « Fermer les trous » (jusqu'à 20 px, sans fuite) et
  « Étendre » (la couleur passe sous le trait, pas de liseré blanc).
  Réglages mémorisés ; par défaut 24 / oui / 2 px / 1 px.
- Remplissage natif (CreativeCore) : transformée de distance pour fermer les
  trous, expansion géodésique pour rejoindre le bord du trait.

### Divers
- Libellés restés en anglais traduits dans les réglages du pinceau.

| Suite Python | 605 tests, 0 échec (6 ignorés) |
| --- | --- |
| Suite C++ | 14/14 |

À recompiler sur la station : `cmake --build build_cpp_native -j`.

## Outils de peintre

- Remplissage au lasso (Maj+F, groupe Remplissage) : la forme dessinée est
  remplie avec la couleur active, anticrénelée, limitée à la sélection,
  respecte le verrou alpha, annulable.
- Masque rapide (Sélection ▸ Masque rapide, touche Q) : peindre la
  sélection avec n'importe quel outil (pinceaux texturés, gomme, seau,
  lasso, dégradé). La sélection en cours est chargée dans le masque ; Q à
  nouveau la valide. La couleur du pinceau est restaurée.
- Pipette moyennée : Pixel, 3×3, 5×5, 11×11, 31×31 (barre d'options ;
  s'applique aussi à Alt+clic). 3×3 par défaut.
- Navigateur (Fenêtre ▸ Panneaux) : vue d'ensemble en direct, cadre de la
  zone visible (y compris rotation), clic / glisser pour se déplacer,
  molette et curseur pour zoomer.
- Harmonies de couleurs (complémentaire, analogue, triade, complémentaires
  divisées, tétrade) avec variantes claires et foncées ; masque de gamme
  sur la roue (les teintes hors masque sont assombries et inaccessibles),
  recentrable sur la teinte actuelle.
- Mélangeur (Fenêtre ▸ Panneaux) : palette de mélange où la couleur se
  mélange réellement, clic droit ou Alt+clic pour la reprendre ; conservée
  entre les sessions.
- Instantanés (panneau Historique) : mémoriser l'état de tous les calques et
  y revenir à tout moment ; revenir est une étape annulable.
- Mode tuile (Affichage ▸ Mode tuile, touche W) : affichage 3×3, les
  touches qui franchissent un bord continuent du côté opposé (tous les
  types de pinceaux, double pointe comprise) — motifs sans raccord.

| Suite Python | 612 tests, 0 échec (6 ignorés) |
| --- | --- |
| Suite C++ | 14/14 |

À recompiler sur la station : `cmake --build build_cpp_native -j`.

## Masques de dossier

- Les dossiers acceptent un masque, comme dans Photoshop : sélectionner la
  ligne du dossier puis le bouton Masque (ou clic droit ▸ Masque de dossier).
  Le masque s'affiche à côté de l'icône du dossier ; un clic dessus le rend
  actif pour la peinture (noir masque, blanc révèle). Tous les pinceaux, la
  gomme et le remplissage au lasso fonctionnent dessus.
- Désactiver (croix rouge sur la miniature), inverser et supprimer sont
  disponibles ; « Appliquer » est refusé comme dans Photoshop.
- Annuler/rétablir couvre l'ajout, la peinture, l'inversion et la
  suppression. Correction au passage : une annulation structurelle
  reconstruisait les dossiers et perdait leur imbrication et leur masque.
- PSD : les masques de dossier sont désormais importés (ils étaient
  ignorés avec un avertissement) et exportés.
- Remplissage au lasso : en mode masque, il peint le masque (en niveaux de
  gris) au lieu des pixels du calque.
- Palette clic droit : un clic droit pendant qu'elle est ouverte la ferme
  sans la rouvrir ; corrige l'avertissement Wayland « Creating a popup with
  a parent … which does not match the current topmost grabbing popup ».

## Grandes toiles et code mort

- Navigateur : la miniature n'est plus un rendu complet de l'image (3,9 s sur
  une toile 8000×6000, à chaque modification) mais un rendu réduit, mis à
  jour seulement sur les tuiles modifiées (~0,1 s).
- Instantanés : tuiles occupées compressées, partagées entre instantanés
  quand elles n'ont pas changé ; masques de calque et de dossier inclus.
  8000×6000 / 12 calques : 4,8 Mo au lieu d'environ 2,3 Go (plantage
  mémoire). Restauration : 0,06 s au lieu de 4,5 s.
- Remplissage au lasso : ne matérialise plus le calque entier.
- Cache de composition : tient compte des masques de dossier.
- Supprimé : CORE/scripting.py et TOOLS/retouch_tool.py (retouche photo,
  jamais branchés), anciens enrobages native_flood_fill*.
