# Nebula — validation de parité fonctionnelle

Ce protocole sépare les validations automatisables des essais qui nécessitent
un écran, une tablette et des fichiers de production.

## Réglages et transformation

- [ ] Créer un calque de réglage Courbes, modifier trois points et annuler/rétablir.
- [ ] Vérifier Niveaux (noir, blanc, gamma et sortie) sur une image 16 bits exportée.
- [ ] Vérifier Teinte/Saturation/Luminosité sur une photo et sur une peinture.
- [ ] Tester perspective quatre coins, warp et liquify sur un calque dupliqué.
- [ ] Vérifier que les réglages restent non destructifs après sauvegarde/rechargement.

## PSD et couleur

- [ ] Ouvrir un PSD multicouche avec transparence, groupes, modes de fusion et effets.
- [ ] Comparer les positions, opacités et effets avec Photoshop/Krita.
- [ ] Ouvrir un fichier avec profil ICC intégré et vérifier le profil affiché.
- [ ] Convertir sRGB ↔ Adobe RGB/Display P3 et comparer un nuancier de référence.

## Ressources et retouche

- [ ] Importer/exporter une bibliothèque de brushes, textures, motifs, gradients,
  palettes, styles et profils ICC.
- [ ] Tester sélection par couleur, expansion, contraction, contour progressif,
  baguette et lasso sur des images à fort contraste.
- [ ] Tester clone, correcteur, remplissage sensible au contenu et retouche locale.

## Longue durée

- [ ] Session de 60 minutes avec au moins 1000 traits et changement fréquent de calque.
- [ ] Document 8192×8192, 20 calques, zooms 25–800 %, sauvegardes répétées.
- [ ] Vérifier RSS, absence de fuite GPU, récupération autosave et intégrité du PSD/Nebula.
