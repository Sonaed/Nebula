#include "thread_pool.h"
#include <atomic>
#include <cassert>
int main(){creative_core::ThreadPool p(2);std::atomic<int> n{0};for(int i=0;i<20;++i)p.enqueue([&]{++n;});p.stop();assert(n==20);return 0;}
