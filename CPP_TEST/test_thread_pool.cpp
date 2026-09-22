#include "thread_pool.h"
#include "object_pool.h"
#include <atomic>
#include <cassert>
int main(){creative_core::ThreadPool p(2);std::atomic<int> n{0};for(int i=0;i<20;++i)p.enqueue([&]{++n;});p.stop();assert(n==20);creative_core::ObjectPool a(64);void* x=a.allocate(32);a.deallocate(x,32);void* y=a.allocate(32);assert(x==y);a.deallocate(y,32);return 0;}
