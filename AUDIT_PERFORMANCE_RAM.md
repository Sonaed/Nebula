# Audit performances et mémoire — CreativeSystem v1.0

## Portée et méthode

Audit statique des chemins Qt, du rendu OpenGL, de CreativeCore, de l’historique et des préférences. Vérifications dynamiques : tests Python, CTest et inspection des métriques de transfert déjà exposées par `CanvasGPURenderer`. Les temps n’ont pas été profilés sur plusieurs tailles de documents ou cartes graphiques ; les constats ci-dessous décrivent donc les coûts présents dans le code, pas un benchmark matériel.

## Résultats performances

### Rendus et signaux

- Les appels `QWidget.update()` du canvas sont nombreux pendant les interactions, mais `update()` est différé et Qt fusionne les demandes avant le prochain paint. Aucun appel `repaint()` bloquant n’est utilisé dans les chemins applicatifs. Les invalidations répétées d’un même événement n’entraînent donc pas nécessairement autant de frames ; les doubles `update()` restent du travail inutile à nettoyer au fil des changements fonctionnels.
- Les sites d’invalidation les plus denses sont `Canvas.keyPressEvent()` (20 branches/appels), `mouseMoveEvent()` (11), `mouseReleaseEvent()` (10), `tabletEvent()` (9) et `mousePressEvent()` (5). Ce sont surtout des actions conditionnelles distinctes ; vérifier une trace de paint par événement serait nécessaire avant de les fusionner davantage.
- Les sliders blend regroupent déjà les demandes preview avec un timer 16 ms et reportent le rendu complet canvas au relâchement. Les changements de paramètres passent par un signal vers `CreativeSystemUI`, puis mettent à jour l’état du calque et l’uniform preview ; l’historique est groupé au début/à la fin de l’édition.
- Les contrôles de toolbar ont des connexions directes vers les setters C++ de la brosse ; le signal `brush_settings_changed` resynchronise plusieurs vues. Ce chemin n’appelle pas de recomposition complète du document à chaque valeur, mais les widgets destinataires pourraient être regroupés dans un unique slot si la toolbar s’agrandit.
- Le parcours blend est `NumericSlider.valueChanged → LayersDock.blend_parameter_changed → CreativeSystemUI._set_active_blend_parameter`; les valeurs sont appliquées au calque et à la preview. Les signaux début/fin groupent l’historique, et seul le signal de fin déclenche l’invalidation canvas. Le parcours brosse utilise `brush_settings_changed` pour garder panneau et toolbar synchronisés.
- Les préférences lues à chaque frame ou événement ont été mises en cache dans `Canvas` : GPU, fond, comportement du zoom, aperçu du curseur et pression tablette. La modification de préférence met à jour ces valeurs et invalide le canvas quand nécessaire.

### Transferts GPU et synchronisations

- `CanvasGPURenderer.sync_layer()` compare `QImage.cacheKey()` et la taille : une image inchangée ne remonte pas au GPU. Après modification, le rectangle marqué sale est transféré via `glTexSubImage2D`; un changement de taille entraîne un upload complet.
- Les textures GPU sont des RGBA plein format par calque ; leur coût estimé est `largeur × hauteur × 4`. Ce n’est pas une mesure du driver (alignement, allocations internes ou autres clients GPU).
- Aucun `glFinish`, `glReadPixels`, `QOpenGLFramebufferObject.toImage()`, `repaint()` ou boucle d’attente active n’a été trouvé dans les chemins applicatifs parcourus. La preview blend rend sur un FBO borné à 256×256.
- La preview réécrivait deux uniforms de sampler à chaque frame ; ils sont désormais définis à la compilation/sélection du shader. Les sliders ne touchent qu’aux uniforms modifiés.

### Travail synchrone sur le thread UI

- Ouverture, sauvegarde/export d’image, écriture CSD et récupération autosave effectuent encore lecture, compression et écriture sur le thread UI (`CORE/application.py`). Les grands fichiers peuvent bloquer l’interface. Le correctif adapté est de déplacer l’I/O et la compression vers un worker puis de remettre le résultat à l’UI par signal ; ce changement implique une gestion d’erreur/progression et n’a pas été introduit dans cet audit mémoire.
- Le rendu blend CPU est déclenché dans `Canvas.paintGL()` quand le document contient un mode non normal, une rotation de vue ou un retournement. `DOCUMENTS/blend_modes.py` utilise NumPy vectorisé et QPainter, pas une boucle Python pixel par pixel. Le cache de composition conserve au plus deux résultats et 256 MB ; une image plus grande n’est pas mise en cache. Un cache hit renvoie maintenant une copie QImage partageant les pixels (copy-on-write) au lieu d’une copie profonde.
- `TileHistory.commit()` copie/compare les tuiles modifiées côté UI. Les gestes simples capturent les deltas via `dirty_only`; les opérations structurelles peuvent encore prendre des images complètes avant/après. `undo` d’une étape déchargée lit et décompresse ses tuiles à la demande, ce qui peut ajouter une latence ponctuelle.
- La brosse passe par CreativeCore C++ quand disponible. Le fallback Python rasterise les segments avec des boucles d’échantillons ; il reste un chemin CPU coûteux pour les configurations où CreativeCore n’est pas chargé. La composition NumPy est déjà vectorisée ; aucun port C++ supplémentaire n’est justifié sans profil montrant ce chemin comme dominant.

## Gestion RAM ajoutée

- Préférence **Performance → Application RAM limit (MB)**, plage 256–65536 MB, valeur initiale 2048 MB.
- Indicateur permanent en barre d’état : RSS courant du processus / budget et estimation VRAM des textures du renderer. L’infobulle détaille images de calques/sélection, historique, cache de composition et textures GPU.
- Échantillonnage toutes les 1,5 s. Au dépassement du budget, le cache de compositions recalculables est vidé ; les anciens deltas de tuiles undo sont sérialisés en PNG dans un répertoire temporaire par un worker. Les étapes sont relues à la demande par undo/redo. Si la pression reste critique après le swap et dépasse 115 % du budget, l’historique est réduit à la moitié de sa capacité configurée, en gardant au moins une étape.
- Les textures GPU ne sont pas détruites au seul motif que le RSS dépasse la limite : cela provoquerait des reuploads immédiats et n’abaisserait pas la RAM système. Leur consommation est estimée séparément.

## Limite d’architecture à traiter séparément

Les calques sont des `QImage` contiguës de la taille entière du document. Le renderer et les outils lisent/écrivent directement ces images. Il n’existe pas de fournisseur de pixels paginé par tuiles ni de mécanisme qui remplace les régions hors écran par des pages disque. Les pixels autoritaires des calques ne sont donc pas déchargés par ce gestionnaire ; le swap porte sur les deltas undo déjà organisés en tuiles. Un vrai swap des pixels hors écran demande une refonte tile-backed du modèle de calque et des API CreativeCore, du renderer, des filtres, de la composition, de la sauvegarde et de l’historique. Le budget est une cible de pression, pas une garantie absolue lorsque les calques actifs seuls dépassent cette valeur.

## Changements vérifiés

- Cache de composition : copies profondes supprimées sur cache hit.
- Réglages consultés dans les événements de rendu/tablette : mise en cache dans `Canvas` et actualisation immédiate par le slot de préférences.
- Historique : sérialisation/réhydratation des deltas undo, suppression de fichiers swap lors du reset, de la troncature de branche ou de l’éviction.
- Tests : tests Python et CTest exécutés après les changements ; le test ajouté vérifie undo/redo d’une étape déchargée.
