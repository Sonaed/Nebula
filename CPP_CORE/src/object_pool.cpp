#include "object_pool.h"
#include <cstdlib>
namespace creative_core {
ObjectPool::~ObjectPool(){for(void* p:m_free)std::free(p);}
void* ObjectPool::allocate(size_t n){if(n>m_block)return std::malloc(n);std::lock_guard l(m_mutex);if(m_free.empty())return std::malloc(m_block);void* p=m_free.back();m_free.pop_back();return p;}
void ObjectPool::deallocate(void* p,size_t n)noexcept{if(!p)return;if(n>m_block){std::free(p);return;}std::lock_guard l(m_mutex);m_free.push_back(p);}
}
