#pragma once
#include <condition_variable>
#include <functional>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>
namespace creative_core {
class ThreadPool {
 public:
  explicit ThreadPool(unsigned n=0); ~ThreadPool();
  void enqueue(std::function<void()> task);
  void stop(); unsigned size() const { return (unsigned)m_workers.size(); }
 private: void run(); std::vector<std::thread> m_workers; std::queue<std::function<void()>> m_jobs; mutable std::mutex m_mutex; std::condition_variable m_cv; bool m_stopping=false;
};
}
