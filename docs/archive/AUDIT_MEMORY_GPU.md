# Audit mémoire et textures GPU

## 1. Cache LRU des tuiles

Le moteur de projection possède déjà une file de jobs et des snapshots de tuiles, mais pas de cache LRU persistant. Ajouter côté C++ `TileCache` (`unordered_map<TileKey,Entry>` + `list<TileKey>`), avec taille maximale en octets configurable depuis Préférences > Performance. L’éviction appelle le scratch disk existant; les tuiles compressées doivent être libérées avant l’écriture disque.

Ordre : cache LRU, compression RAM, puis intégration scratch. Risque principal : ne jamais évincer une tuile verrouillée par un stroke, undo ou upload GPU.

## 2. Compression RAM LZ4

LZ4 est adapté aux tuiles RGBA8888 par sa faible latence. Stocker en entrée un en-tête (dimensions, stride, format, taille brute, taille compressée, checksum) puis le bloc LZ4. Mesurer le ratio sur tuiles réelles; les aplats se compressent fortement, le bruit peu. Décompression à la demande avant composition ou upload.

La dépendance doit être optionnelle : fallback tuile brute si LZ4 absent. Ne jamais compresser une tuile active.

## 3. Texture atlas

Les petites textures doivent être inventoriées dans `gpu_renderer.py`, les brush tips dans `CPP_CORE/src/brush_engine.cpp`/assets. Un atlas shelf avec padding d’un pixel et table UV (`id -> rect normalisé`) réduit les binds. Les shaders reçoivent la table UV ou des UV déjà remappées. Les textures dynamiques et les FBO ne sont pas candidates.

## 4. Compression GPU

BC4/BC7 nécessitent une extension de compression disponible et une implémentation de transcodage. Les textures de calques inactives peuvent être candidates après plusieurs frames sans modification, mais la compression est bloquante si faite sur le thread UI. Prévoir une file de projection et conservation de la version non compressée pour réactivation. Gain théorique BC4 ~4x; BC7 dépend du format et du driver, donc mesure obligatoire avant activation.

## Ordre recommandé

1. `TileCache` LRU en C++.
2. Compression RAM LZ4 branchée au cache.
3. Atlas des brush tips/icons statiques.
4. Compression BC4/BC7 expérimentale, activée seulement après détection d’extension et benchmark qualité/VRAM.

## État dans le dépôt (audit 2026-09-16)

- `DOCUMENTS/tile_store.py` possède déjà un magasin sparse, accès/versions et scratch asynchrone; son `_last_access` constitue une base LRU, mais la structure demandée `unordered_map/list` C++ n'existe pas encore.
- `CORE/memory_manager.py` orchestre la limite RAM et l'éviction scratch; il doit déléguer la décision d'éviction au cache C++ pour éviter deux politiques concurrentes.
- `CANVAS/gpu_renderer.py` gère les textures par tuile et les uploads PBO; aucun atlas ni BC4/BC7 n'est actuellement actif.
- Les brush tips sont produits par `CPP_CORE/src/brush_tip.cpp` et les icônes UI par les docks Qt; ils ne partagent pas encore un gestionnaire d'atlas.

Implémentation recommandée : créer `CPP_CORE/include/tile_cache.h` et `CPP_CORE/src/tile_cache.cpp`, exposer des fonctions ctypes de capacité/accès/éviction, puis adapter `DOCUMENTS/tile_store.py`. Ajouter LZ4 en dépendance optionnelle CMake et conserver le scratch PNG comme format de compatibilité. L'atlas doit être ajouté ensuite dans `CANVAS/gpu_renderer.py`; BC4/BC7 reste conditionnel aux extensions du driver et à un benchmark réel.
