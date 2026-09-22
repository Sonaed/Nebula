#pragma once
#include <cstddef>
#include <memory>
#include <mutex>
#include <vector>
namespace creative_core {
class ObjectPool {
 public: explicit ObjectPool(size_t block=256):m_block(block){} ~ObjectPool();
  void* allocate(size_t n); void deallocate(void* p,size_t n) noexcept;
 private: size_t m_block; std::mutex m_mutex; std::vector<void*> m_free;
};
}
