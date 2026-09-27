#pragma once
// SUPPRIMÉ — code mort.
//
// TileCache (LRU C++) n'a jamais eu le moindre appelant : ni dans le C++,
// ni dans l'ABI creative_core_api. Le cache de tuiles réel est
// NativeTileStore (tile_store.h) côté C++ et MemoryManager (CORE/
// memory_manager.py) côté Python, qui gèrent résidence, révisions,
// LRU et swap disque.
//
// Garder deux systèmes de tuiles entretenait l'illusion d'un cache C++
// actif et constituait une source de divergence.
//
// Ce fichier et tile_cache.cpp / CPP_TEST/test_tile_cache.cpp peuvent
// être supprimés du disque : plus rien n'y fait référence.
