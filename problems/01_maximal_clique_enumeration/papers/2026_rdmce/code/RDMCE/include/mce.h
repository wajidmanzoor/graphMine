#pragma once
#include "common.cuh"
#include "graph.h"
#include <functional>

enum class MceAlgorithm
{
  BKPivot,
  BKFixedMemPivotLn,
  BKFixedMemPivotBit,
  MCEEND, // end of enumeration
  BKFixedMem,
  BKFixedMemPivot,
  BKFixedMemBit,
};

inline const char *MceAlgorithmNames[] = {
    "BKPivot",
    "BKFixedMemPivotLn",
    "BKFixedMemPivotBit",
    "MCEEND", // end of enumeration
    "BKFixedMem",
    "BKFixedMemPivot",
    "BKFixedMemBit",
};

class MceSolver
{
public:
  MceSolver(Graph &g) : g_(g), mce_count_(0) {}
  void Solve(MceAlgorithm algo = MceAlgorithm::BKPivot);
  acc_t mce_count_;

private:
  Timer timer_, debug_timer_;
  void BKPivot(vlist_t &R, vlist_t &P, vlist_t &X,
               std::function<void(vlist_t &, vlist_t &, vlist_t &)> callback = nullptr,
               size_t bound = 64);
  void BKFixedMem(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKFixedMemPivot(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKFixedMemPivotLn(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKFixedMemBit(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKFixedMemPivotBit(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKFixedMemPivotBit2(vlist_t &R, vlist_t &P, vlist_t &X);
  void BKMixed(vlist_t &R, vlist_t &P, vlist_t &X);
  vlist_t Partition(const vlist_t &P, const vlist_t &X);

  inline void IncrementMceCount()
  {
    if (++mce_count_ % 10000000 == 0)
    {
      std::cout << "Mce count: " << mce_count_ << "  time: "
                << timer_.ElapsedSinceStart() << "s" << std::endl;
    }
  }
  Graph &g_;
};
