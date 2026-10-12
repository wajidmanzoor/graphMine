// Scheduler plugin for OpenMP
//
// Critical Note: It is **very important** that we do not accidentally nest
// parallel regions in OpenMP, because this will result in duplicate worker
// IDs (each team gets assigned their own sequential worker IDs from 0 to
// omp_get_num_threads() - 1). Therefore, we always check whether we are
// already inside a parallel region before creating one. If we are already
// inside one, tasks will just make use of the existing threads in the team.
//

#ifndef PARLAY_INTERNAL_SCHEDULER_PLUGINS_OMP_H_
#define PARLAY_INTERNAL_SCHEDULER_PLUGINS_OMP_H_

#include <iostream>
#include <omp.h>

namespace parlay {

// IWYU pragma: private, include "../../parallel.h"

inline size_t num_workers() {
  std::cout << "Max Threads from num_workers: " << omp_get_max_threads() << std::endl;
  return omp_get_max_threads();
}

inline size_t worker_id() {
  return omp_get_thread_num();
}


template <class F>
inline void parallel_for(size_t start, size_t end, F f, long granularity, bool) {

  // If we are not yet in a parallel region, start one
  if (omp_get_num_threads() == 1 && omp_get_max_threads() > 1) {
    std::cout << "Max Threads: " << omp_get_max_threads() << std::endl;
    #pragma omp parallel
    {
      #pragma omp single
      {
        if (granularity == 0) {
          #pragma omp taskloop untied
          for (size_t i = start; i < end; i++) {
            f(i);
          }
        }
        else {
          #pragma omp taskloop untied grainsize(granularity)
          for (size_t i = start; i < end; i++) {
            f(i);
          }
        }
      }  // omp single
    }  // omp parallel
  }
  // Already inside a parallel region, avoid creating nested one (see comment at top)
  else {
    std::cout << "Max Threads: " << omp_get_max_threads() << std::endl;
    if (granularity == 0) {
      #pragma omp taskloop untied
      for (size_t i = start; i < end; i++) {
        f(i);
      }
    }
    else {
      #pragma omp taskloop untied grainsize(granularity)
      for (size_t i = start; i < end; i++) {
        f(i);
      }
    }
  }
}

template <typename Lf, typename Rf>
inline void par_do(Lf left, Rf right, bool) {
  std::cout << "Printing from par_do function." << std::endl;
  // If we are not yet in a parallel region, start one
  if (omp_get_num_threads() == 1 && omp_get_max_threads() > 1) {
    #pragma omp parallel
    {
      #pragma omp single
      {
        #pragma omp task untied
        { left(); }
        #pragma omp task untied
        { right(); }
        #pragma omp taskwait
      }  // omp single
    }  // omp parallel
  }
  // Already inside a parallel region, avoid creating nested one (see comment at top)
  else {
    std::cout << "Max Threads: " << omp_get_max_threads() << std::endl;
    #pragma omp task untied
    { left(); }
    #pragma omp task untied
    { right(); }
    #pragma omp taskwait
  }
}

}  // namespace parlay

#endif  // PARLAY_INTERNAL_SCHEDULER_PLUGINS_OMP_H_
