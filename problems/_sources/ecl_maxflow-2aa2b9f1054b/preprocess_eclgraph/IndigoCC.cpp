/*
This file is part of the Indigo3 benchmark suite version 1.0.

BSD 3-Clause License

Copyright (c) 2024, Yiqian Liu, Noushin Azami, Avery Vanausdal, and Martin Burtscher

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

URL: The latest version of the Indigo3 benchmark suite is available at https://github.com/burtscher/Indigo3Suite/.

Publication: This work is described in detail in the following paper.
Yiqian Liu, Noushin Azami, Avery Vanausdal, and Martin Burtscher. "Indigo3: A Parallel Graph Analytics Benchmark Suite for Exploring Implementation Styles and Common Bugs." ACM Transactions on Parallel Computing. May 2024. https://doi.org/10.1145/3665251
*/

#include <algorithm>
#include <set>
#include <sys/time.h>
#include <limits>
#include <thread>
#include <atomic>

typedef int data_type;
typedef std::atomic<data_type> shared_t;
typedef std::atomic<bool> flag_t;

template <typename T>
static inline T atomicMin(T* addr, T val)
{
  T oldv = ((std::atomic<T>*)addr)->load();
  while (oldv > val && !(((std::atomic<T>*)addr)->compare_exchange_weak(oldv, val))) {}
  return oldv;
}

template <typename T>
static inline T atomicMax(T* addr, T val)
{
  T oldv = ((std::atomic<T>*)addr)->load();
  while (oldv < val && !(((std::atomic<T>*)addr)->compare_exchange_weak(oldv, val))) {}
  return oldv;
}

template <typename T>
static inline T atomicMin(std::atomic<T>* addr, T val)
{
  T oldv = addr->load();
  while (oldv > val && !(addr->compare_exchange_weak(oldv, val))) {}
  return oldv;
}

template <typename T>
static inline T atomicMax(std::atomic<T>* addr, T val)
{
  T oldv = addr->load();
  while (oldv < val && !(addr->compare_exchange_weak(oldv, val))) {}
  return oldv;
}


static void init(shared_t* const label, const int size)
{
  // initialize arrays
  for (int v = 0; v < size; v++) {
    label[v] = v;
  }
}

static void cc(const ECLgraph g, shared_t* const label, flag_t& goagain, const int threadID, const int threadCount)
{
  const int N = g.nodes;
  const int begNode = threadID * (long)N / threadCount;
  const int endNode = (threadID + 1) * (long)N / threadCount;
  for (int v = begNode; v < endNode; v++) {
    const int beg = g.nindex[v];
    const int end = g.nindex[v + 1];
    const data_type new_label = label[v];
    bool updated = false;

    for (int i = beg; i < end; i++) {
      const int dst = g.nlist[i];
      if (atomicMin(&label[dst], new_label) > new_label) {
        updated = true;
      }
    }

    if (updated) {
      goagain = 1;
    }
  }
}

static double CPUcc_vertex(const ECLgraph g, data_type* const label_orig, const int threadCount)
{
  shared_t* label = (shared_t*)label_orig;
  std::thread threadHandles[threadCount];

  init(label, g.nodes);

  timeval start, end;
  gettimeofday(&start, NULL);

  // iterate until no more changes
  flag_t goagain;
  int iter = 0;
  do {
    iter++;
    goagain = 0;

    for (int i = 0; i < threadCount; ++i) {
      threadHandles[i] = std::thread(cc, g, label, std::ref(goagain), i, threadCount);
    }
    for (int i = 0; i < threadCount; ++i) {
      threadHandles[i].join();
    }

  } while (goagain);

  gettimeofday(&end, NULL);
  double runtime = end.tv_sec + end.tv_usec / 1000000.0 - start.tv_sec - start.tv_usec / 1000000.0;
  printf("iterations: %d\n", iter);

  return runtime;
}
