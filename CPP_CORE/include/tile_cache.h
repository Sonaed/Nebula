#pragma once
#include <cstddef>
#include <list>
#include <mutex>
#include <unordered_map>
#include <vector>
namespace creative_core {
struct TileKey { uint64_t generation{}; int x{}, y{}; bool operator==(const TileKey& o) const { return generation==o.generation&&x==o.x&&y==o.y; } };
struct TileKeyHash { size_t operator()(const TileKey& k) const { return (size_t)(k.generation ^ (uint64_t(uint32_t(k.x))*2654435761u) ^ (uint64_t(uint32_t(k.y))*2246822519u)); } };
class TileCache {
 public:
  explicit TileCache(size_t limit=64*1024*1024): m_limit(limit) {}
  void setLimit(size_t bytes); size_t limit() const; size_t bytes() const;
  void put(TileKey key, std::vector<unsigned char> data);
  bool get(TileKey key, std::vector<unsigned char>& out);
  size_t evict();
 private:
  struct Entry { std::vector<unsigned char> data; std::list<TileKey>::iterator it; };
  mutable std::mutex m_mutex; size_t m_limit; size_t m_bytes{};
  std::list<TileKey> m_lru; std::unordered_map<TileKey,Entry,TileKeyHash> m_map;
};
}
