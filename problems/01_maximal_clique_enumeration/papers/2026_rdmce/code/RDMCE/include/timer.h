#pragma once
#include <chrono>
#include <ctime>

class Timer
{
private:
  std::chrono::high_resolution_clock::time_point start_t, end_t;
  std::chrono::duration<double> total_time = std::chrono::duration<double>::zero();

public:
  Timer() = default;
  void Start()
  {
    total_time = std::chrono::duration<double>::zero();
    start_t = std::chrono::high_resolution_clock::now();
  }

  void ReStart()
  {
    start_t = std::chrono::high_resolution_clock::now();
  }
  void Stop()
  {
    end_t = std::chrono::high_resolution_clock::now();
    total_time += end_t - start_t;
  }
  double Elapsed()
  {
    return total_time.count();
  }

  double ElapsedSinceStart()
  {
    auto now = std::chrono::high_resolution_clock::now();
    return std::chrono::duration_cast<std::chrono::duration<double>>(now - start_t).count();
  }
};