#include "tile_cache.h"
namespace creative_core {
void TileCache::setLimit(size_t b){std::lock_guard l(m_mutex);m_limit=b;while(m_bytes>m_limit&&!m_lru.empty()){auto k=m_lru.back();m_lru.pop_back();auto i=m_map.find(k);if(i!=m_map.end()){m_bytes-=i->second.data.size();m_map.erase(i);}}}
size_t TileCache::limit()const{std::lock_guard l(m_mutex);return m_limit;} size_t TileCache::bytes()const{std::lock_guard l(m_mutex);return m_bytes;}
void TileCache::put(TileKey k,std::vector<unsigned char> d){std::lock_guard l(m_mutex);auto i=m_map.find(k);if(i!=m_map.end()){m_bytes-=i->second.data.size();m_lru.erase(i->second.it);m_map.erase(i);}m_lru.push_front(k);m_bytes+=d.size();m_map.emplace(k,Entry{std::move(d),m_lru.begin()});while(m_bytes>m_limit&&!m_lru.empty()){auto z=m_lru.back();m_lru.pop_back();auto j=m_map.find(z);if(j!=m_map.end()){m_bytes-=j->second.data.size();m_map.erase(j);}}}
bool TileCache::get(TileKey k,std::vector<unsigned char>& out){std::lock_guard l(m_mutex);auto i=m_map.find(k);if(i==m_map.end())return false;m_lru.erase(i->second.it);m_lru.push_front(k);i->second.it=m_lru.begin();out=i->second.data;return true;} size_t TileCache::evict(){std::lock_guard l(m_mutex);size_t n=0;while(m_bytes>m_limit&&!m_lru.empty()){auto k=m_lru.back();m_lru.pop_back();auto i=m_map.find(k);if(i!=m_map.end()){m_bytes-=i->second.data.size();m_map.erase(i);++n;}}return n;}
}
