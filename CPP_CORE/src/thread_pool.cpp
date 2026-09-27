#include "thread_pool.h"
namespace creative_core {
ThreadPool::ThreadPool(unsigned n){if(!n){n=std::thread::hardware_concurrency();n=n>1?n-1:1;}for(unsigned i=0;i<n;++i)m_workers.emplace_back(&ThreadPool::run,this);}
ThreadPool::~ThreadPool(){stop();}
void ThreadPool::enqueue(std::function<void()> f){if(!f)return;{std::lock_guard l(m_mutex);if(m_stopping)return;m_jobs.push(std::move(f));}m_cv.notify_one();}
void ThreadPool::stop(){{std::lock_guard l(m_mutex);if(m_stopping)return;m_stopping=true;}m_cv.notify_all();for(auto& t:m_workers)if(t.joinable())t.join();}
void ThreadPool::run(){for(;;){std::function<void()> f;{std::unique_lock l(m_mutex);m_cv.wait(l,[&]{return m_stopping||!m_jobs.empty();});if(m_stopping&&m_jobs.empty())return;f=std::move(m_jobs.front());m_jobs.pop();}try{f();}catch(...){}}}
}
