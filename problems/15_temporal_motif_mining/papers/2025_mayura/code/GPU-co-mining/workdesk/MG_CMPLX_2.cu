#include <stdio.h>
#include <cuda.h>

#include <thrust/device_ptr.h>
#include <thrust/scan.h>

#include "helpers.cuh"
#include "data.h"

using namespace corelib;
using namespace corelib::data;

typedef unsigned long long UINT64_T;

//const bool DEBUG = false;

//#define DEBUG_ACT(x) if (DEBUG) { x; }
#define WARP_BALANCING (true)
#define OFFLOADING (true)
#define FORCE_PRINTING_MATCHES (false)
#define DISPATCH_NO_MINE (false)
#define SAVE_MATCHES (false)
#define PRINT_OFFLOAD (false)
#define COND() ( (motif_ID == 6) && (EM[0] < 1000) )

#define STACKIO_SET_BIT0 (uint8_t(0xFF))
#define STACKIO_UNSET_BIT0 (uint8_t(0xFE))

#define LANE_ID (threadIdx.x & 31)

#define INTRA_WARP_SPLIT
// #define MULTI_OFFLOAD
constexpr bool do_probe_end = true;
// #define COMPLEX_BALANCING

#define DEBUG (false)
__device__ static void reduceEarlyIdx(const int *i_S, int &beg, int end, int i_g) {
  if (end == beg) { beg = end; return;}
  if (i_S[end - 1] <= i_g) {
    beg = end;
    return;
  } else if (i_S[beg] > i_g) {
    return;
  }

  // binary search the first value >= i_g, at this point i_S has at least 2 elements
  int p = 0;
  while (beg < end) {
    p = (beg + end) / 2;
    if (i_S[p] > i_g) {
      end = p;
    } else {
      beg = p + 1;
    }
  }
}

struct TContext {
  int stackbeg0 = 0, stackbeg1 = 0, stackbeg2 = 0;
  int stackend0 = 0, stackend1 = 0, stackend2 = 0;
  int m0 = 0, m1 = 0, m2 = 0, m3 = 0;

  int tl;

  unsigned char stackio;
  uint8_t level;
  int beg, end;

  int8_t motif_ID = 0;
  int i_g_2 = -1, i_g_3 = -1;
  uint8_t sibling_spawn_lvl_stack = 0;
};

__device__ static int firstLarger(int *arr, int beg, int end, int v) {
  while (beg < end) {
    int mid = (beg + end) / 2;
    if (arr[mid] <= v) {
      beg = mid + 1;
    } else {
      end = mid;
    }
  }
  return end;
}

__device__ static void probeEnd(const int *i_S, int beg, int &end, int tl, const TemporalEdge *Eg) {
  while (beg < end) {
    int mid = (beg + end) / 2;
    if (Eg[i_S[mid]].t <= tl) {
      beg = mid + 1;
    } else {
      end = mid;
    }
  }
}

__device__ static void dumpContext(
  int stackbeg0, int stackbeg1, int stackbeg2,
  int stackend0, int stackend1, int stackend2,
  int m0, int m1, int m2, int m3,

  int tl,
  unsigned char stackio,
  int level,
  int beg, int end, const int *i_S,

  // graph
  const TemporalEdge *Eg,
  const int *inEdgesV,
  const int *outEdgesV,
  const int *inEdgesR,
  const int *outEdgesR,

  // mem
  TContext *offload,
  int *offtop,
  int *offload_width,

  // co-mining
  int8_t motif_ID,
  int i_g_2, int i_g_3,
  uint8_t sibling_spawn_lvl_stack,
  const MotifEdgeInfoV1* minfo
  // int *width_analysis
) {
  // TODO: Should the sibling_spawn_lvl_stack be split up here?
  int width = 0;
  probeEnd(i_S, beg, end, tl, Eg);
  width = max(width, end - beg);
  auto stackiob = stackio;
  switch(level) {
    case 3:
      stackiob >>= 1;
      i_S = stackiob & 1 ? outEdgesV : inEdgesV;
      probeEnd(i_S, stackbeg2, stackend2, tl, Eg);
      width = max(width, stackend2 - stackbeg2);
    case 2:
      stackiob >>= 1;
      i_S = stackiob & 1 ? outEdgesV : inEdgesV;
      probeEnd(i_S, stackbeg1, stackend1, tl, Eg);
      width = max(width, stackend1 - stackbeg1);
    case 1:
      stackiob >>= 1;
      i_S = stackiob & 1 ? outEdgesV : inEdgesV;
      probeEnd(i_S, stackbeg0, stackend0, tl, Eg);
      width = max(width, stackend0 - stackbeg0);
  }

  if (width == 0 && sibling_spawn_lvl_stack == 0) return;

#ifdef MULTI_OFFLOAD
  int8_t last_sib_ID, sib_level;
  if (motif_ID == 1) {
    last_sib_ID = -1;
    sib_level = 0;
  } else {
    last_sib_ID = minfo[motif_ID * NUM_LEVELS + level].last_sib_ID;
    if (last_sib_ID < 0) {
      sib_level = -last_sib_ID;
      last_sib_ID = minfo[motif_ID * NUM_LEVELS + sib_level].last_sib_ID;
    } else {
      sib_level = level;
    }
  }

  // int num_offloads = 0, num_ignored_offloads = 0;
  while (true) {
    width = 0;
    width = (sib_level <= 0) ? max(width, stackend0 - stackbeg0) : width;
    width = (sib_level <= 1) ? max(width, stackend1 - stackbeg1) : width;
    width = (sib_level <= 2) ? max(width, stackend2 - stackbeg2) : width;
    width = max(width, end - beg);

    if (width != 0) {
      // ++num_offloads;
      int offpos = atomicAdd(offtop, 1);
      // Dump the context from beg-end to the point in the stack after the parent motif.
      offload[offpos].beg = beg;
      offload[offpos].end = end;
      offload[offpos].level = level;
      offload[offpos].stackio = stackio;
      offload[offpos].tl = tl;

      offload_width[offpos] = width;

      offload[offpos].stackbeg0 = (sib_level <= 0) ? stackbeg0 : 0;
      offload[offpos].stackend0 = (sib_level <= 0) ? stackend0 : 0;
      offload[offpos].stackbeg1 = (sib_level <= 1) ? stackbeg1 : 0;
      offload[offpos].stackend1 = (sib_level <= 1) ? stackend1 : 0;
      offload[offpos].stackbeg2 = (sib_level <= 2) ? stackbeg2 : 0;
      offload[offpos].stackend2 = (sib_level <= 2) ? stackend2 : 0;

      offload[offpos].m0 = m0;
      offload[offpos].m1 = m1;
      offload[offpos].m2 = m2;
      offload[offpos].m3 = m3;

      offload[offpos].motif_ID = motif_ID;
      // This context may or maynot be used, but we're supplying it anyway since zero-ing it out will cause divergence.
      offload[offpos].i_g_2 = i_g_2;
      offload[offpos].i_g_3 = i_g_3;
      // Zero out the sibling_spawn_lvl_stack since we are going explore the sibling and parents seperatly
      // TODO: Remove this since sibling_spawn_lvl_stack should already be zero.
      // TODO: Then, remove the sibling_spawn_lvl_stack from the context.
      offload[offpos].sibling_spawn_lvl_stack = 0;
    } else {
      // ++num_ignored_offloads;
    }

    // Now, zero out the variable necessary for the context.

    if (motif_ID == 1) {
      // We're at the root motif, no need to go further.
      break;
    }

    if (level > sib_level) {
      stackio >>= (level - sib_level);
      level = sib_level;

      stackbeg0 = (sib_level <= 0) ? 0 : stackbeg0;
      stackend0 = (sib_level <= 0) ? 0 : stackend0;
      stackbeg1 = (sib_level <= 1) ? 0 : stackbeg1;
      stackend1 = (sib_level <= 1) ? 0 : stackend1;
      stackbeg2 = (sib_level <= 2) ? 0 : stackbeg2;
      stackend2 = (sib_level <= 2) ? 0 : stackend2;
    }

    // Do we have more siblings?
    // If not, move up to the sibling level and move to next sibling.
    // Perform any necessary cleanup while moving up. (like zeroing out the stack)
    if ((motif_ID < last_sib_ID) && ((sibling_spawn_lvl_stack & 1)==1)) {
      ++motif_ID;

      stackio &= 0xFE;
      int i_g = (level == 2) ? i_g_2 : i_g_3;

      auto mi = minfo[motif_ID * NUM_LEVELS + level];
      if (mi.io >= 0) {
        int base = (mi.baseNode == 0) ? m0 :
                   (mi.baseNode == 1) ? m1 :
                   (mi.baseNode == 2) ? m2 : m3;

        beg = mi.arrR[base];
        end = mi.arrR[base + 1];
        i_S = mi.arrV;
      } else {
        int base0 = (mi.baseNode == 0) ? m0 :
                    (mi.baseNode == 1) ? m1 :
                    (mi.baseNode == 2) ? m2 : m3;

        int base1 = (mi.constraintNode == 0) ? m0 :
                    (mi.constraintNode == 1) ? m1 :
                    (mi.constraintNode == 2) ? m2 : m3;

        int beg0 = inEdgesR[base0];
        int end0 = inEdgesR[base0 + 1];
        int beg1 = outEdgesR[base1];
        int end1 = outEdgesR[base1 + 1];

        bool io = !((end0 - beg0) < (end1 - beg1));
        mi.io = io;
        beg = io ? beg1 : beg0;
        end = io ? end1 : end0;
        i_S = io ? outEdgesV : inEdgesV;
        io ? (mi.constraintNode = mi.baseNode) : 0;
      }
      stackio |= mi.io ? 1 : 0;

      reduceEarlyIdx(i_S, beg, end, i_g);
      if(do_probe_end) probeEnd(i_S, beg, end, tl, Eg);

      continue;
    }

    // No more siblings to check?
    // If so, go to parent.
    if (motif_ID == last_sib_ID || ((sibling_spawn_lvl_stack & 1) == 0) ) {
      
      motif_ID = minfo[motif_ID * NUM_LEVELS + level].parent_ID;
      --level;
      sibling_spawn_lvl_stack >>= 1;

      beg = (level == 0) ? stackbeg0 :
            (level == 1) ? stackbeg1 : stackbeg2;
      end = (level == 0) ? stackend0 :
            (level == 1) ? stackend1 : stackend2;

      stackio >>= 1;

      if (motif_ID != 1) {
        last_sib_ID = minfo[motif_ID * NUM_LEVELS + level].last_sib_ID;
        if (last_sib_ID < 0) {
          sib_level = -last_sib_ID;
          last_sib_ID = minfo[motif_ID * NUM_LEVELS + sib_level].last_sib_ID;
        } else {
          sib_level = level;
        }
      } else {
        last_sib_ID = -1;
        sib_level = 0;
      }

    }

  }
#else
  int offpos = atomicAdd(offtop, 1);

#define EXPAND_TO_SIBLING (true)
  if (width == 0 && sibling_spawn_lvl_stack != 0) {
    if (EXPAND_TO_SIBLING && (sibling_spawn_lvl_stack & 1)) {
      auto last_sib_ID = minfo[motif_ID * NUM_LEVELS + level].last_sib_ID;

      if (last_sib_ID < 0) {
        auto old_level = level;
        level = -last_sib_ID;
        last_sib_ID = minfo[motif_ID * NUM_LEVELS + level].last_sib_ID;
        stackio >>= (old_level - level);
      }

      if (motif_ID == last_sib_ID) {
        // This is the last sibling, cannot parallelize further.
        width = 1;
        // atomicAdd(width_analysis + 0, 1);
      } else {
        // Open up the next sibling.
        ++motif_ID;
        int i_g = (level == 2) ? i_g_2 : i_g_3;

        stackio &= 0xFE;
        auto mi = minfo[motif_ID * NUM_LEVELS + level];
        if (mi.io >= 0) {
          int base = (mi.baseNode == 0) ? m0 :
                     (mi.baseNode == 1) ? m1 :
                     (mi.baseNode == 2) ? m2 : m3;

          beg = mi.arrR[base];
          end = mi.arrR[base + 1];
          i_S = mi.arrV;
        } else {
          int base0 = (mi.baseNode == 0) ? m0 :
                      (mi.baseNode == 1) ? m1 :
                      (mi.baseNode == 2) ? m2 : m3;

          int base1 = (mi.constraintNode == 0) ? m0 :
                      (mi.constraintNode == 1) ? m1 :
                      (mi.constraintNode == 2) ? m2 : m3;

          int beg0 = inEdgesR[base0];
          int end0 = inEdgesR[base0 + 1];
          int beg1 = outEdgesR[base1];
          int end1 = outEdgesR[base1 + 1];

          bool io = !((end0 - beg0) < (end1 - beg1));
          mi.io = io;
          beg = io ? beg1 : beg0;
          end = io ? end1 : end0;
          i_S = io ? outEdgesV : inEdgesV;
          io ? (mi.constraintNode = mi.baseNode) : 0;
        }

        stackio |= mi.io ? 1 : 0;

        reduceEarlyIdx(i_S, beg, end, i_g);
        if(do_probe_end) probeEnd(i_S, beg, end, tl, Eg);

        width = max(0, end - beg);

        (width == 0) ? (width = 1) : 0;
      }
    } else {
      width = 1;
    }
  }

  // each thread
  offload[offpos].beg = beg;
  offload[offpos].end = end;
  offload[offpos].level = level;
  offload[offpos].stackio = stackio;
  offload[offpos].tl = tl;

  offload_width[offpos] = width;

  offload[offpos].stackbeg0 = stackbeg0;
  offload[offpos].stackend0 = stackend0;
  offload[offpos].stackbeg1 = stackbeg1;
  offload[offpos].stackend1 = stackend1;
  offload[offpos].stackbeg2 = stackbeg2;
  offload[offpos].stackend2 = stackend2;
  offload[offpos].m0 = m0;
  offload[offpos].m1 = m1;
  offload[offpos].m2 = m2;
  offload[offpos].m3 = m3;

  offload[offpos].motif_ID = motif_ID;
  offload[offpos].i_g_2 = i_g_2;
  offload[offpos].i_g_3 = i_g_3;
  offload[offpos].sibling_spawn_lvl_stack = sibling_spawn_lvl_stack;
#endif
}

__global__ static void MotifMatching_Expand(
  int work,
  // graph
  const TemporalEdge *Eg, int numeg,
  const int *inEdgesV, const int *inEdgesR,
  const int *outEdgesV, const int *outEdgesR,
  const int *nodeFeature, const int *edgeFeature,

  // motif
  const MotifEdgeInfoV1 *minfo,

  // runtime
  int *yeild,
  int *source,
  TContext *offload,
  int *offtop,
  TContext *offloadn,
  int *offtopn,
  int *offload_width,

  int *chunk_offset,

  UINT64_T *gcount
) {
  int tid;
  if (LANE_ID == 0) tid = atomicAdd(source, 32);
  tid = __shfl_sync(0xffffffff, tid, 0);
  if (tid >= work) return;

  int stackbeg0 = 0, stackbeg1 = 0, stackbeg2 = 0;
  int stackend0 = 0, stackend1 = 0, stackend2 = 0;
  int m0 = 0, m1 = 0, m2 = 0, m3 = 0;

  unsigned char stackio = 0;
  int tl;
  int i_g = tid;
  int level = 0;
  int beg = 0, end = 0;
  const int *i_S = nullptr;

  clock_t timeup = 0;

  /* Co-mining Variables */
  int8_t motif_ID = 1;
  bool is_match = false, motif_changed = false;
  int i_g_2 = -1, i_g_3 = -1;
  uint8_t sibling_spawn_lvl_stack = 0;
  /*
  UINT64_T counts[NUM_MOTIFS];
  #pragma unroll
  for (int i = 0; i < NUM_MOTIFS; i++) counts[i] = 0;
  */
  UINT64_T count_1 = 0;
#if NUM_MOTIFS >= 2
  UINT64_T count_2 = 0;
#endif
#if NUM_MOTIFS >= 3
  UINT64_T count_3 = 0;
#endif
#if NUM_MOTIFS >= 4
  UINT64_T count_4 = 0;
#endif

  while (tid < work) { // valid block
    tid = (tid >> 5) + chunk_offset[LANE_ID];
    MotifEdgeInfoV1 mi;

    if (tid < work) {
      auto loc = firstLarger(offload_width, 0, *offtop, tid);
      int offset = loc ? tid - offload_width[loc - 1] : tid;

      // load context from loc
      level = offload[loc].level;
      tl = offload[loc].tl;
      stackio = offload[loc].stackio;

      beg = offload[loc].beg + offset;
      end = min(beg + 1, offload[loc].end);

      stackbeg0 = offload[loc].stackbeg0 + offset;
      stackbeg1 = offload[loc].stackbeg1 + offset;
      stackbeg2 = offload[loc].stackbeg2 + offset;
      stackend0 = min(stackbeg0 + 1, offload[loc].stackend0);
      stackend1 = min(stackbeg1 + 1, offload[loc].stackend1);
      stackend2 = min(stackbeg2 + 1, offload[loc].stackend2);
      m0 = offload[loc].m0;
      m1 = offload[loc].m1;
      m2 = offload[loc].m2;
      m3 = offload[loc].m3;

      motif_ID = offload[loc].motif_ID;
      i_g_2 = offload[loc].i_g_2;
      i_g_3 = offload[loc].i_g_3;
      sibling_spawn_lvl_stack = offset == 0 ? offload[loc].sibling_spawn_lvl_stack : 0;

      mi = minfo[motif_ID * NUM_LEVELS + level];
      mi.io = stackio & 1;
      i_S = mi.io ? outEdgesV : inEdgesV;
      if(mi.constraintNode >= 0) mi.constraintNode = mi.io ? mi.baseNode : mi.constraintNode;
    } else {
      end = beg = 0;
    }

    int loopCnt = 0;
    while (true) {
      i_g = numeg;
      int node;
      for (bool is_alive = beg < end; is_alive; is_alive &= ((++beg) < end)) {
        auto idx = i_S[beg];
        auto eg = Eg[idx];
        if (eg.t > tl) {
          end = beg;
          is_alive = false;
        }
        node = mi.io ? eg.v : eg.u;
        bool checked;
        if (mi.constraintNode < 0) {
          checked =    ( (mi.mappedNodes >= 4) ? (m3 != node) : true )
                    && ( (mi.mappedNodes >= 3) ? (m2 != node) : true )
                    && ( (mi.mappedNodes >= 2) ? ((m1 != node) && (m0 != node)) : true );
        } else {
          checked =    ((mi.constraintNode == 0) ? (m0 == node) : true)
                    && ((mi.constraintNode == 1) ? (m1 == node) : true)
                    && ((mi.constraintNode == 2) ? (m2 == node) : true)
                    && ((mi.constraintNode == 3) ? (m3 == node) : true);
        }

        if (is_alive && checked) {
            i_g = idx;
            is_alive = false;
        }
      }

      bool alive = (level || (i_g < numeg));

      bool next = i_g < numeg;

      if (next) {
        is_match = (level + 2 == mi.numem);
        motif_changed = false;

        {
          auto is_match_idx = is_match ? mi.count_IDX : 0;
          ( is_match_idx == 1 ) ? (count_1++) :
#if NUM_MOTIFS >= 2
          ( is_match_idx == 2 ) ? (count_2++) :
#endif
#if NUM_MOTIFS >= 3
          ( is_match_idx == 3 ) ? (count_3++) :
#endif
#if NUM_MOTIFS >= 4
          ( is_match_idx == 4 ) ? (count_4++) :
#endif
            0;
        }

        if (is_match && mi.child_ID_beg != 0) {
          // Save i_g to the stack
          (level == 1) ? i_g_2 = i_g : i_g_3 = i_g;

          sibling_spawn_lvl_stack <<= 1;
          sibling_spawn_lvl_stack |= 1;
          motif_ID = mi.child_ID_beg;
          motif_changed = true;
        }
        if (!is_match || motif_changed) {
          (mi.mappedNodes == 2) ? m2 = node :
          (mi.mappedNodes == 3) ? m3 = node : 0;

          {
            auto is_level_0 = level == 0;
            auto is_level_1 = level == 1;
            auto is_level_2 = level == 2;
            stackbeg0 = is_level_0 ? beg : stackbeg0;
            stackend0 = is_level_0 ? end : stackend0;
            stackbeg1 = is_level_1 ? beg : stackbeg1;
            stackend1 = is_level_1 ? end : stackend1;
            stackbeg2 = is_level_2 ? beg : stackbeg2;
            stackend2 = is_level_2 ? end : stackend2;
          }

          level++;

          stackio <<= 1;
          mi = minfo[motif_ID * NUM_LEVELS + level];
          if (mi.io >= 0) {
            int base = (mi.baseNode == 0) ? m0 :
                       (mi.baseNode == 1) ? m1 :
                       (mi.baseNode == 2) ? m2 : m3;

            beg = mi.arrR[base];
            end = mi.arrR[base + 1];
            i_S = mi.arrV;
          } else {
            int base0 = (mi.baseNode == 0) ? m0 :
                        (mi.baseNode == 1) ? m1 :
                        (mi.baseNode == 2) ? m2 : m3;

            int base1 = (mi.constraintNode == 0) ? m0 :
                        (mi.constraintNode == 1) ? m1 :
                        (mi.constraintNode == 2) ? m2 : m3;

            int beg0 = inEdgesR[base0];
            int end0 = inEdgesR[base0 + 1];
            int beg1 = outEdgesR[base1];
            int end1 = outEdgesR[base1 + 1];

            bool io = !((end0 - beg0) < (end1 - beg1));
            mi.io = io;
            beg = io ? beg1 : beg0;
            end = io ? end1 : end0;
            i_S = io ? outEdgesV : inEdgesV;
            io ? (mi.constraintNode = mi.baseNode) : 0;
          }
          stackio |= mi.io ? 1 : 0;

          reduceEarlyIdx(i_S, beg, end, i_g);
        }
      } else {

        if (level) {
          bool roll_back = true;
          if (mi.last_sib_ID > 0) {
            if ((sibling_spawn_lvl_stack & 1) && motif_ID < mi.last_sib_ID) {
              ++motif_ID;
              // Zero-out the last bit in stackio

              i_g = (level == 2) ? i_g_2 : i_g_3; // <- Hopefully this is never called
              // mi = minfo[motif_ID * NUM_LEVELS + level];
              // goto expand2;
              roll_back = false;

              stackio &= 0xFE;
              mi = minfo[motif_ID * NUM_LEVELS + level];
              if (mi.io >= 0) {
                int base = (mi.baseNode == 0) ? m0 :
                           (mi.baseNode == 1) ? m1 :
                           (mi.baseNode == 2) ? m2 : m3;

                beg = mi.arrR[base];
                end = mi.arrR[base + 1];
                i_S = mi.arrV;
              } else {
                int base0 = (mi.baseNode == 0) ? m0 :
                            (mi.baseNode == 1) ? m1 :
                            (mi.baseNode == 2) ? m2 : m3;

                int base1 = (mi.constraintNode == 0) ? m0 :
                            (mi.constraintNode == 1) ? m1 :
                            (mi.constraintNode == 2) ? m2 : m3;

                int beg0 = inEdgesR[base0];
                int end0 = inEdgesR[base0 + 1];
                int beg1 = outEdgesR[base1];
                int end1 = outEdgesR[base1 + 1];

                bool io = !((end0 - beg0) < (end1 - beg1));
                mi.io = io;
                beg = io ? beg1 : beg0;
                end = io ? end1 : end0;
                i_S = io ? outEdgesV : inEdgesV;
                io ? (mi.constraintNode = mi.baseNode) : 0;
              }
              stackio |= mi.io ? 1 : 0;
    
              reduceEarlyIdx(i_S, beg, end, i_g);
            } else {
              sibling_spawn_lvl_stack >>= 1;
              motif_ID = mi.parent_ID;
            }
          }
          if (roll_back) {
            level--;

            beg = (level == 0) ? stackbeg0 :
                  (level == 1) ? stackbeg1 : stackbeg2;
            end = (level == 0) ? stackend0 :
                  (level == 1) ? stackend1 : stackend2;

            stackio >>= 1;

            mi = minfo[motif_ID * NUM_LEVELS + level];
            mi.io = stackio & 1;
            i_S = mi.io ? outEdgesV : inEdgesV;
            if(mi.constraintNode >= 0) mi.constraintNode = mi.io ? mi.baseNode : mi.constraintNode;
          }
        }

      }

      if (loopCnt % 1024 == 0 && *yeild) {
        if (LANE_ID == 0) {
          timeup = clock() + 100000;
        }
        timeup = __shfl_sync(0xffffffff, timeup, 0);
      }

      if (loopCnt % 64 == 0 && timeup && __shfl_sync(0xffffffff, clock(), 0) > timeup) {
        break;
      }

      if (__any_sync(0xffffffff, alive) == 0) break;

      if (WARP_BALANCING && loopCnt > 20 && __any_sync(0xffffffff, !alive) /* is anyone not alive? */) { // the dead thread steal work from alive thread
        int voteAlive = __ballot_sync(0xffffffff, alive); // Who is alive?
        int r0e = __funnelshift_lc(voteAlive, voteAlive, 32 - LANE_ID);
        int l0i = __funnelshift_r(voteAlive, voteAlive, LANE_ID);
        r0e = __brev(r0e);
        l0i = __ffs(l0i) - 1;
        r0e = __ffs(r0e) - 1;

        int src = (threadIdx.x + l0i) & 31;

        beg = __shfl_sync(0xffffffff, beg, src);
        end = __shfl_sync(0xffffffff, end, src);
        level = __shfl_sync(0xffffffff, level, src);
        tl = __shfl_sync(0xffffffff, tl, src);
        stackio = __shfl_sync(0xffffffff, stackio, src);

        stackbeg0 = __shfl_sync(0xffffffff, stackbeg0, src);
        stackbeg1 = __shfl_sync(0xffffffff, stackbeg1, src);
        stackbeg2 = __shfl_sync(0xffffffff, stackbeg2, src);
        stackend0 = __shfl_sync(0xffffffff, stackend0, src);
        stackend1 = __shfl_sync(0xffffffff, stackend1, src);
        stackend2 = __shfl_sync(0xffffffff, stackend2, src);
        m0 = __shfl_sync(0xffffffff, m0, src);
        m1 = __shfl_sync(0xffffffff, m1, src);
        m2 = __shfl_sync(0xffffffff, m2, src);
        m3 = __shfl_sync(0xffffffff, m3, src);

        motif_ID = __shfl_sync(0xffffffff, motif_ID, src);
        i_g_2 = __shfl_sync(0xffffffff, i_g_2, src);
        i_g_3 = __shfl_sync(0xffffffff, i_g_3, src);
	      #ifdef INTRA_WARP_SPLIT
	      {
          auto src_SSLS = __shfl_sync(0xffffffff, sibling_spawn_lvl_stack, src);
          auto new_SSLS = (r0e>=8) ? 0 : (src_SSLS & (1 << r0e));
          int GS = l0i + r0e + 1;
          new_SSLS |= (GS < 8 ? (src_SSLS & (0xFF << GS)) : 0);
          sibling_spawn_lvl_stack = new_SSLS;
        }
	      #else
	      sibling_spawn_lvl_stack = LANE_ID == src ? sibling_spawn_lvl_stack : 0;
	      #endif
        
#ifdef COMPLEX_BALANCING
        int group_size = l0i + r0e + 1;
        if (group_size > 1) {
          int pow;
          {
            int hsb = 32 - __clz(group_size);
            int lsb = __ffs(group_size);
            pow = hsb + (hsb != lsb) - 1;
          }

          {
            auto diff = max(0, end - beg);
            diff = max(diff, stackend0 - stackbeg0);
            diff = max(diff, stackend1 - stackbeg1);
            diff = max(diff, stackend2 - stackbeg2);
            auto delta = max(1, diff >> pow);
            auto new_beg       = beg       + (r0e * delta);
            auto new_stackbeg0 = stackbeg0 + (r0e * delta);
            auto new_stackbeg1 = stackbeg1 + (r0e * delta);
            auto new_stackbeg2 = stackbeg2 + (r0e * delta);
            auto new_end       = min(end,       (( l0i == 0 ) ? end       : new_beg       + delta));
            auto new_stackend0 = min(stackend0, (( l0i == 0 ) ? stackend0 : new_stackbeg0 + delta));
            auto new_stackend1 = min(stackend1, (( l0i == 0 ) ? stackend1 : new_stackbeg1 + delta));
            auto new_stackend2 = min(stackend2, (( l0i == 0 ) ? stackend2 : new_stackbeg2 + delta));
            beg = new_beg;
            end = new_end;
            stackbeg0 = new_stackbeg0;
            stackbeg1 = new_stackbeg1;
            stackbeg2 = new_stackbeg2;
            stackend0 = new_stackend0;
            stackend1 = new_stackend1;
            stackend2 = new_stackend2;
          }
        }
#else
        beg += r0e;
        stackbeg0 += r0e;
        stackbeg1 += r0e;
        stackbeg2 += r0e;
        if (LANE_ID != src) {
          end = min(end, beg + 1);
          stackend0 = min(stackend0, stackbeg0 + 1);
          stackend1 = min(stackend1, stackbeg1 + 1);
          stackend2 = min(stackend2, stackbeg2 + 1);
        }
#endif

        mi = minfo[motif_ID * NUM_LEVELS + level];
        mi.io = stackio & 1;
        i_S = mi.io ? outEdgesV : inEdgesV;
        if(mi.constraintNode >= 0) mi.constraintNode = mi.io ? mi.baseNode : mi.constraintNode;

      }

      if (LANE_ID == 0) loopCnt++;
      loopCnt = __shfl_sync(0xffffffff, loopCnt, 0);
    }

    if (LANE_ID == 0) tid = atomicAdd(source, 32);
    tid = __shfl_sync(0xffffffff, tid, 0);
  } // end of outer loop

  #pragma unroll
  for (int offset = 16; offset > 0; offset >>= 1) {
    count_1 += __shfl_down_sync(0xffffffff, count_1, offset);
    #if NUM_MOTIFS >= 2
    count_2 += __shfl_down_sync(0xffffffff, count_2, offset);
    #endif
    #if NUM_MOTIFS >= 3
    count_3 += __shfl_down_sync(0xffffffff, count_3, offset);
    #endif
    #if NUM_MOTIFS >= 4
    count_4 += __shfl_down_sync(0xffffffff, count_4, offset);
    #endif
    /*
    #pragma unroll
    for (int i = 0; i < NUM_MOTIFS; i++) {
      counts[i] += __shfl_down_sync(0xffffffff, counts[i], offset);
    }
    */
  }

  if (LANE_ID == 0) {
    atomicAdd(gcount + 0, count_1);
    #if NUM_MOTIFS >= 2
    atomicAdd(gcount + 1, count_2);
    #endif
    #if NUM_MOTIFS >= 3
    atomicAdd(gcount + 2, count_3);
    #endif
    #if NUM_MOTIFS >= 4
    atomicAdd(gcount + 3, count_4);
    #endif
    /*
    #pragma unroll
    for (int i = 0; i < NUM_MOTIFS; i++) {
      atomicAdd(gcount + i, counts[i]);
    }
    */
  }

  // Flag to start the time-up counter.
  atomicAdd(yeild, 1);

  if ((level || (beg < end))) {
    dumpContext(
      stackbeg0, stackbeg1, stackbeg2,
      stackend0, stackend1, stackend2,
      m0, m1, m2, m3,

      tl,

      stackio, level, beg, end, i_S,

      Eg,
      inEdgesV,
      outEdgesV,
      inEdgesR,
      outEdgesR,

      offloadn,
      offtopn,
      offload_width,

      motif_ID,
      i_g_2, i_g_3,
      sibling_spawn_lvl_stack,
      minfo
    );
  }
}

__global__ static void MotifMatching_dispatch(
  int work, int delta,
  // graph
  const TemporalEdge *Eg, int numeg,
  const int *inEdgesV, const int *inEdgesR,
  const int *outEdgesV, const int *outEdgesR,
  const int *nodeFeature, const int *edgeFeature,

  // motif
  const MotifEdgeInfoV1 *minfo,

  int *yeild,
  int *source,
  TContext *offload,
  int *offtop,
  int *offtopn,
  int *offload_width,

  // runtime
  UINT64_T *gcount
  ) {
  int tid;
  if (LANE_ID == 0) tid = atomicAdd(source, 32);
  tid = __shfl_sync(0xffffffff, tid, 0);
  if (tid >= work) return;

  int stackbeg0 = 0, stackbeg1 = 0, stackbeg2 = 0;
  int stackend0 = 0, stackend1 = 0, stackend2 = 0;
  int m0 = 0, m1 = 0, m2 = 0, m3 = 0;

  unsigned char stackio = 0;
  int tl;
  int i_g = tid;
  int level = 0;
  int beg = 0, end = 0;
  const int *i_S = nullptr;
  /* Co-mining Variables */
  int8_t motif_ID = 1;
  bool is_match = false, motif_changed = false;
  /*
  UINT64_T counts[NUM_MOTIFS];
  #pragma unroll
  for (int i = 0; i < NUM_MOTIFS; i++) counts[i] = 0;
  */
  UINT64_T count_1 = 0;
#if NUM_MOTIFS >= 2
  UINT64_T count_2 = 0;
#endif
#if NUM_MOTIFS >= 3
  UINT64_T count_3 = 0;
#endif
#if NUM_MOTIFS >= 4
  UINT64_T count_4 = 0;
#endif
  int i_g_2 = -1, i_g_3 = -1;
  uint8_t sibling_spawn_lvl_stack = 0;

  clock_t timeup = 0;

  while (tid < work) { // valid block
    tid += LANE_ID;

    bool fcheck = tid < work && (Eg[tid].u != Eg[tid].v);
    MotifEdgeInfoV1 mi;

    if (fcheck) {
      m0 = Eg[tid].u;
      m1 = Eg[tid].v;
      tl = Eg[tid].t + delta;

      i_g = tid;
      mi = minfo[motif_ID * NUM_LEVELS + level];
      stackio <<= 1;
      if (mi.io >= 0) {
        int base = (mi.baseNode == 0) ? m0 :
                   (mi.baseNode == 1) ? m1 :
                   (mi.baseNode == 2) ? m2 : m3;

        beg = mi.arrR[base];
        end = mi.arrR[base + 1];
        i_S = mi.arrV;
      } else {
        int base0 = (mi.baseNode == 0) ? m0 :
                    (mi.baseNode == 1) ? m1 :
                    (mi.baseNode == 2) ? m2 : m3;
        int base1 = (mi.constraintNode == 0) ? m0 :
                    (mi.constraintNode == 1) ? m1 :
                    (mi.constraintNode == 2) ? m2 : m3;

        int beg0 = inEdgesR[base0];
        int end0 = inEdgesR[base0 + 1];
        int beg1 = outEdgesR[base1];
        int end1 = outEdgesR[base1 + 1];

        bool io = !((end0 - beg0) < (end1 - beg1));
        mi.io = io;
        beg = io ? beg1 : beg0;
        end = io ? end1 : end0;
        i_S = io ? outEdgesV : inEdgesV;
        io ? (mi.constraintNode = mi.baseNode) : 0;
      }
      stackio |= mi.io ? 1 : 0;

      reduceEarlyIdx(i_S, beg, end, i_g);
    } else {
      end = beg;
    }
    
    if(DISPATCH_NO_MINE) {
      break;
    }

    int loopCnt = 0;
    sibling_spawn_lvl_stack = 0;
    while (true) {
      i_g = numeg;
      int node;

      for (bool is_alive = beg < end; is_alive; is_alive &= ((++beg) < end)) {
        auto idx = i_S[beg];
        auto eg = Eg[idx];
        if (eg.t > tl) {
          end = beg;
          is_alive = false;
        }
        node = mi.io ? eg.v : eg.u;
        bool checked;
        if (mi.constraintNode < 0) {
          checked =    ( (mi.mappedNodes >= 4) ? (m3 != node) : true )
                    && ( (mi.mappedNodes >= 3) ? (m2 != node) : true )
                    && ( (mi.mappedNodes >= 2) ? ((m1 != node) && (m0 != node)) : true );
        } else {
          checked =    ((mi.constraintNode == 0) ? (m0 == node) : true)
                    && ((mi.constraintNode == 1) ? (m1 == node) : true)
                    && ((mi.constraintNode == 2) ? (m2 == node) : true)
                    && ((mi.constraintNode == 3) ? (m3 == node) : true);
        }

        if (is_alive && checked) {
            i_g = idx;
            is_alive = false;
        }
      }

      bool alive = (level || (i_g < numeg));

      bool next = i_g < numeg;

      if (next) {
        is_match = (level + 2 == mi.numem);
        motif_changed = false;

        {
          auto is_match_idx = is_match ? mi.count_IDX : 0;
          ( is_match_idx == 1 ) ? (count_1++) :
#if NUM_MOTIFS >= 2
          ( is_match_idx == 2 ) ? (count_2++) :
#endif
#if NUM_MOTIFS >= 3
          ( is_match_idx == 3 ) ? (count_3++) :
#endif
#if NUM_MOTIFS >= 4
          ( is_match_idx == 4 ) ? (count_4++) :
#endif
            0;
          // (is_match_idx != 0) ? counts[is_match_idx - 1]++ : 0;
        }

        if (is_match && mi.child_ID_beg != 0) {
          // Save i_g to the stack
          (level == 1) ? i_g_2 = i_g : i_g_3 = i_g;

          sibling_spawn_lvl_stack <<= 1;
          sibling_spawn_lvl_stack |= 1;
          motif_ID = mi.child_ID_beg;
          motif_changed = true;
        }
        if (!is_match || motif_changed) {
          (mi.mappedNodes == 2) ? m2 = node :
          (mi.mappedNodes == 3) ? m3 = node : 0;

          {
            auto is_level_0 = level == 0;
            auto is_level_1 = level == 1;
            auto is_level_2 = level == 2;
            stackbeg0 = is_level_0 ? beg : stackbeg0;
            stackend0 = is_level_0 ? end : stackend0;
            stackbeg1 = is_level_1 ? beg : stackbeg1;
            stackend1 = is_level_1 ? end : stackend1;
            stackbeg2 = is_level_2 ? beg : stackbeg2;
            stackend2 = is_level_2 ? end : stackend2;
          }

          level++;

          stackio <<= 1;
          mi = minfo[motif_ID * NUM_LEVELS + level];
          if (mi.io >= 0) {
            int base = (mi.baseNode == 0) ? m0 :
                       (mi.baseNode == 1) ? m1 :
                       (mi.baseNode == 2) ? m2 : m3;

            beg = mi.arrR[base];
            end = mi.arrR[base + 1];
            i_S = mi.arrV;
          } else {
            int base0 = (mi.baseNode == 0) ? m0 :
                        (mi.baseNode == 1) ? m1 :
                        (mi.baseNode == 2) ? m2 : m3;

            int base1 = (mi.constraintNode == 0) ? m0 :
                        (mi.constraintNode == 1) ? m1 :
                        (mi.constraintNode == 2) ? m2 : m3;

            int beg0 = inEdgesR[base0];
            int end0 = inEdgesR[base0 + 1];
            int beg1 = outEdgesR[base1];
            int end1 = outEdgesR[base1 + 1];

            bool io = !((end0 - beg0) < (end1 - beg1));
            mi.io = io;
            beg = io ? beg1 : beg0;
            end = io ? end1 : end0;
            i_S = io ? outEdgesV : inEdgesV;
            io ? (mi.constraintNode = mi.baseNode) : 0;
          }
          stackio |= mi.io ? 1 : 0;

          reduceEarlyIdx(i_S, beg, end, i_g);
        }
      } else {

        if (level) {
          bool roll_back = true;
          if (mi.last_sib_ID > 0) {
            if ((sibling_spawn_lvl_stack & 1) && motif_ID < mi.last_sib_ID) {
              ++motif_ID;
              // Zero-out the last bit in stackio

              i_g = (level == 2) ? i_g_2 : i_g_3;

              // mi = minfo[motif_ID * NUM_LEVELS + level]; Happens right after expand.
              // goto expand;
              roll_back = false;

              stackio &= 0xFE;
              // NOTE: beg and end are re-calculated at the same-level for the sibling motif.
              // TODO: Is it possible & better if we cache the range instead?
              mi = minfo[motif_ID * NUM_LEVELS + level];
              if (mi.io >= 0) {
                int base = (mi.baseNode == 0) ? m0 :
                           (mi.baseNode == 1) ? m1 :
                           (mi.baseNode == 2) ? m2 : m3;

                beg = mi.arrR[base];
                end = mi.arrR[base + 1];
                i_S = mi.arrV;
              } else {
                int base0 = (mi.baseNode == 0) ? m0 :
                            (mi.baseNode == 1) ? m1 :
                            (mi.baseNode == 2) ? m2 : m3;

                int base1 = (mi.constraintNode == 0) ? m0 :
                            (mi.constraintNode == 1) ? m1 :
                            (mi.constraintNode == 2) ? m2 : m3;

                int beg0 = inEdgesR[base0];
                int end0 = inEdgesR[base0 + 1];
                int beg1 = outEdgesR[base1];
                int end1 = outEdgesR[base1 + 1];

                bool io = !((end0 - beg0) < (end1 - beg1));
                mi.io = io;
                beg = io ? beg1 : beg0;
                end = io ? end1 : end0;
                i_S = io ? outEdgesV : inEdgesV;
                io ? (mi.constraintNode = mi.baseNode) : 0;
              }
              // TODO: Replace this with BITWISE AND to set/unset the last bit.
              stackio |= mi.io ? 1 : 0;
    
              reduceEarlyIdx(i_S, beg, end, i_g);
            } else {
              sibling_spawn_lvl_stack >>= 1;
              motif_ID = mi.parent_ID;
            }
          }
          if (roll_back) {
            level--;

            beg = (level == 0) ? stackbeg0 :
                  (level == 1) ? stackbeg1 : stackbeg2;
            end = (level == 0) ? stackend0 :
                  (level == 1) ? stackend1 : stackend2;

            stackio >>= 1;

            mi = minfo[motif_ID * NUM_LEVELS + level];
            mi.io = stackio & 1;
            i_S = mi.io ? outEdgesV : inEdgesV;
            if(mi.constraintNode >= 0) mi.constraintNode = mi.io ? mi.baseNode : mi.constraintNode;
          }
        }

      }

      if (OFFLOADING && loopCnt % 1024 == 0 && *yeild) {
        if (LANE_ID == 0) {
          timeup = clock() + 100000;
        }
        timeup = __shfl_sync(0xffffffff, timeup, 0);
      }

      if (OFFLOADING && loopCnt % 64 == 0 && timeup && __shfl_sync(0xffffffff, clock(), 0) > timeup) {
        break;
      }

      if (__any_sync(0xffffffff, alive) == 0) break;

      if (WARP_BALANCING && loopCnt > 20 && __any_sync(0xffffffff, !alive)) { // the dead thread steal work from alive thread
        //printf("TID %3i :: Alive: %i\n", tid, alive);
        int voteAlive = __ballot_sync(0xffffffff, alive);
        int r0e = __funnelshift_lc(voteAlive, voteAlive, 32 - LANE_ID);
        int l0i = __funnelshift_r(voteAlive, voteAlive, LANE_ID);
        r0e = __brev(r0e);
        l0i = __ffs(l0i) - 1;
        r0e = __ffs(r0e) - 1;

        int src = (threadIdx.x + l0i) & 31;

        beg = __shfl_sync(0xffffffff, beg, src);
        end = __shfl_sync(0xffffffff, end, src);
        level = __shfl_sync(0xffffffff, level, src);
        tl = __shfl_sync(0xffffffff, tl, src);
        stackio = __shfl_sync(0xffffffff, stackio, src);

        stackbeg0 = __shfl_sync(0xffffffff, stackbeg0, src);
        stackbeg1 = __shfl_sync(0xffffffff, stackbeg1, src);
        stackbeg2 = __shfl_sync(0xffffffff, stackbeg2, src);
        stackend0 = __shfl_sync(0xffffffff, stackend0, src);
        stackend1 = __shfl_sync(0xffffffff, stackend1, src);
        stackend2 = __shfl_sync(0xffffffff, stackend2, src);
        m0 = __shfl_sync(0xffffffff, m0, src);
        m1 = __shfl_sync(0xffffffff, m1, src);
        m2 = __shfl_sync(0xffffffff, m2, src);
        m3 = __shfl_sync(0xffffffff, m3, src);

        motif_ID = __shfl_sync(0xffffffff, motif_ID, src);
        i_g_2 = __shfl_sync(0xffffffff, i_g_2, src);
        i_g_3 = __shfl_sync(0xffffffff, i_g_3, src);
	      #ifdef INTRA_WARP_SPLIT
	      {
          auto src_SSLS = __shfl_sync(0xffffffff, sibling_spawn_lvl_stack, src);
          auto new_SSLS = (r0e>=8) ? 0 : (src_SSLS & (1 << r0e));
          int GS = l0i + r0e + 1;
          new_SSLS |= (GS < 8 ? (src_SSLS & (0xFF << GS)) : 0);
          sibling_spawn_lvl_stack = new_SSLS;
        }
	      #else
	      sibling_spawn_lvl_stack = LANE_ID == src ? sibling_spawn_lvl_stack : 0;
	      #endif

#ifdef COMPLEX_BALANCING
        int group_size = l0i + r0e + 1;
        if (group_size > 1) {
          int pow;
          {
            int hsb = 32 - __clz(group_size);
            int lsb = __ffs(group_size);
            pow = hsb + (hsb != lsb) - 1;
          }

          {
            auto diff = max(0, end - beg);
            diff = max(diff, stackend0 - stackbeg0);
            diff = max(diff, stackend1 - stackbeg1);
            diff = max(diff, stackend2 - stackbeg2);
            auto delta = max(1, diff >> pow);
            auto new_beg       = beg       + (r0e * delta);
            auto new_stackbeg0 = stackbeg0 + (r0e * delta);
            auto new_stackbeg1 = stackbeg1 + (r0e * delta);
            auto new_stackbeg2 = stackbeg2 + (r0e * delta);
            auto new_end       = min(end,       (( l0i == 0 ) ? end       : new_beg       + delta));
            auto new_stackend0 = min(stackend0, (( l0i == 0 ) ? stackend0 : new_stackbeg0 + delta));
            auto new_stackend1 = min(stackend1, (( l0i == 0 ) ? stackend1 : new_stackbeg1 + delta));
            auto new_stackend2 = min(stackend2, (( l0i == 0 ) ? stackend2 : new_stackbeg2 + delta));
            beg = new_beg;
            end = new_end;
            stackbeg0 = new_stackbeg0;
            stackbeg1 = new_stackbeg1;
            stackbeg2 = new_stackbeg2;
            stackend0 = new_stackend0;
            stackend1 = new_stackend1;
            stackend2 = new_stackend2;
          }
        }
#else
        beg += r0e;
        stackbeg0 += r0e;
        stackbeg1 += r0e;
        stackbeg2 += r0e;
        if (LANE_ID != src) {
          end = min(end, beg + 1);
          stackend0 = min(stackend0, stackbeg0 + 1);
          stackend1 = min(stackend1, stackbeg1 + 1);
          stackend2 = min(stackend2, stackbeg2 + 1);
        }
#endif
        mi = minfo[motif_ID * NUM_LEVELS + level];
        mi.io = stackio & 1;
        i_S = mi.io ? outEdgesV : inEdgesV;
        if(mi.constraintNode >= 0) mi.constraintNode = mi.io ? mi.baseNode : mi.constraintNode;

      }

      if (LANE_ID == 0) loopCnt++;
      loopCnt = __shfl_sync(0xffffffff, loopCnt, 0);
    }

    if (LANE_ID == 0) tid = atomicAdd(source, 32);
    tid = __shfl_sync(0xffffffff, tid, 0);
  } // end of outer loop

  #pragma unroll
  for (int offset = 16; offset > 0; offset >>= 1) {
    count_1 += __shfl_down_sync(0xffffffff, count_1, offset);
    #if NUM_MOTIFS >= 2
    count_2 += __shfl_down_sync(0xffffffff, count_2, offset);
    #endif
    #if NUM_MOTIFS >= 3
    count_3 += __shfl_down_sync(0xffffffff, count_3, offset);
    #endif
    #if NUM_MOTIFS >= 4
    count_4 += __shfl_down_sync(0xffffffff, count_4, offset);
    #endif
    /*
    #pragma unroll
    for (int i = 0; i < NUM_MOTIFS; i++) {
      counts[i] += __shfl_down_sync(0xffffffff, counts[i], offset);
    }
    */
  }

  if (LANE_ID == 0) {
    atomicAdd(gcount + 0, count_1);
    #if NUM_MOTIFS >= 2
    atomicAdd(gcount + 1, count_2);
    #endif
    #if NUM_MOTIFS >= 3
    atomicAdd(gcount + 2, count_3);
    #endif
    #if NUM_MOTIFS >= 4
    atomicAdd(gcount + 3, count_4);
    #endif
    /*
    #pragma unroll
    for (int i = 0; i < NUM_MOTIFS; i++) {
      atomicAdd(gcount + i, counts[i]);
    }
    */
  }

  atomicAdd(yeild, 1);

  if ((level || (beg < end))) {
    dumpContext(
      stackbeg0, stackbeg1, stackbeg2,
      stackend0, stackend1, stackend2,
      m0, m1, m2, m3,

      tl,

      stackio, level, beg, end, i_S,

      Eg,
      inEdgesV,
      outEdgesV,
      inEdgesR,
      outEdgesR,

      offload,
      offtop,
      offload_width,

      motif_ID,
      i_g_2, i_g_3,
      sibling_spawn_lvl_stack,
      minfo
    );
  }
}

// ---------------------------------

static UINT64_T TMotifMatchingGPUImpl(

             int numBlocksA, int numBlocksB, int sizeBlock,

             int work, int delta,
             // graph
             const TemporalEdge *Eg, int numeg,
             const int *inEdgesV, const int *inEdgesR, const int *outEdgesV, const int *outEdgesR,
             const int *nodeFeature, const int *edgeFeature,
             // motif
             const MotifEdgeInfoV1 *minfo, int numem,

             // runtime mem
             int *yeild,
             int *source,
             TContext *offload,
             int *offtop,
             TContext *offloadn,
             int *offtopn,
             int *offload_width,

             UINT64_T *gcount
                          ) {
  int* results_d = nullptr;
  UINT64_T* results_count_d = nullptr;
  constexpr auto NUM_BYTES_RESULTS = (sizeof(int) * MAX_NUM_EDGES) * 33234451;
  int SIZE_WIDTH_ANALYSIS = 5;
  int width_analysis_H[2 * SIZE_WIDTH_ANALYSIS + 1], *width_analysis_D = nullptr;
  cudaError_t err;
  // std::cout << "dipatch::<<<" << numBlocksA << ", " << sizeBlock << ">>>" << std::endl;
  // std::cout << "Expand::<<<" << numBlocksB << ", " << sizeBlock << ">>>" << std::endl;
  MotifMatching_dispatch <<< numBlocksA, sizeBlock >>>(

    work, delta,
    Eg, numeg,
    inEdgesV, inEdgesR, outEdgesV, outEdgesR,
    nodeFeature, edgeFeature,

    minfo - NUM_LEVELS,

    yeild,
    source,
    offload,
    offtop,
    offtopn,
    offload_width,

    gcount
  );
  err = cudaGetLastError();

  if ( err != cudaSuccess ) {
      printf("CUDA Error: %s\n", cudaGetErrorString(err));
      exit(-1);
  }

  int offload_loop = 0;

  // Copy and check counts
  UINT64_T count_arr_h[NUM_MOTIFS] = {0};
  int chunk_offset_h[32];
  int *chunk_offset = nullptr;

  int offload_cnt = 0;
  gpuErrchk(cudaMemcpy(&offload_cnt, offtop, sizeof(int), cudaMemcpyDeviceToHost));

  if (offload_cnt > 0) {
    gpuErrchk(cudaMalloc(&chunk_offset, sizeof(int) * 32));
    gpuErrchk(cudaMemset(chunk_offset, 0, sizeof(int) * 32));
  }

  while (offload_cnt > 0) {
    // printf("Offload %i: offload_cnt: %i\n", offload_loop++, offload_cnt);
    int t = 0;
    gpuErrchk(cudaMemcpy(source, &t, sizeof(int), cudaMemcpyHostToDevice));
    gpuErrchk(cudaMemcpy(yeild, &t, sizeof(int), cudaMemcpyHostToDevice));
    gpuErrchk(cudaMemcpy(offtopn, &t, sizeof(int), cudaMemcpyHostToDevice));
    gpuErrchk(cudaMemcpy(offtop, &offload_cnt, sizeof(int), cudaMemcpyHostToDevice));

    // prefix sum
    thrust::device_ptr<int> dev_ptr(offload_width);

    auto sump = thrust::inclusive_scan(dev_ptr, dev_ptr + offload_cnt, dev_ptr);
    auto sum = *(sump - 1);
    for (int i = 0; i < 32; i++) {
      chunk_offset_h[i] = i * (sum / 32 + (sum % 32 != 0));
    }
    gpuErrchk(cudaMemcpy(chunk_offset, &chunk_offset_h, sizeof(int) * 32, cudaMemcpyHostToDevice));

    MotifMatching_Expand <<< numBlocksB, sizeBlock >>> (sum,
      Eg, numeg,
      inEdgesV, inEdgesR, outEdgesV, outEdgesR,
      nodeFeature, edgeFeature,

      minfo - NUM_LEVELS,

      yeild,
      source,
      offload,
      offtop,
      offloadn,
      offtopn,
      offload_width,

      chunk_offset,

      gcount
    );

    err = cudaGetLastError();

    if ( err != cudaSuccess ) {
        printf("CUDA Error: %s\n", cudaGetErrorString(err));
        exit(-1);
    }

    auto old_offload_cnt = offload_cnt;
    gpuErrchk(cudaMemcpy(&offload_cnt, offtopn, sizeof(int), cudaMemcpyDeviceToHost));
    auto temp = offloadn;
    offloadn = offload;
    offload = temp;
    if (offload_cnt > 0) {
      gpuErrchk(cudaMemset(offloadn, 0, sizeof(TContext) * old_offload_cnt));
    }

  }

  cudaDeviceSynchronize();

  if (chunk_offset != nullptr) {
    gpuErrchk(cudaFree(chunk_offset));
  }


  if (width_analysis_D != nullptr) {
    gpuErrchk(cudaFree(width_analysis_D));
  }
  return 0;
}

struct GPUWorkerDYN : public GPUWorker {
  // Execution Mem
  UINT64_T *count_d;

  int *yeild_d;
  int *source_d;
  TContext *offload_d, *offloadn_d;
  int *offtop, *offtopn;
  int *offload_width_d;

  GPUWorkerDYN(int gpu, int sizeBlock = 96);
  UINT64_T run() override;
  virtual void take(MineJob &job) override;
  void update_job() override;
  ~GPUWorkerDYN() override;

};

GPUWorkerDYN::GPUWorkerDYN(int gpu, int sizeBlock) : GPUWorker("DYN", gpu, sizeBlock) {
  gpuErrchk(cudaSetDevice(gpu_));
  if (NUM_MOTIFS > 5) {
    printf("NUM_MOTIFS > 5 is not supported\n");
    exit(-1);
  }
  gpuErrchk(cudaMalloc(&count_d, sizeof(UINT64_T) * NUM_MOTIFS));
  gpuErrchk(cudaMemset(count_d, 0, sizeof(UINT64_T) * NUM_MOTIFS));

  gpuErrchk(cudaMalloc(&yeild_d, sizeof(int)));
  gpuErrchk(cudaMemset(yeild_d, 0, sizeof(int)));
  gpuErrchk(cudaMalloc(&source_d, sizeof(int)));
  gpuErrchk(cudaMemset(source_d, 0, sizeof(int)));
  gpuErrchk(cudaMalloc(&offtop, sizeof(int)));
  gpuErrchk(cudaMalloc(&offtopn, sizeof(int)));
  gpuErrchk(cudaMemset(offtop, 0, sizeof(int)));
  gpuErrchk(cudaMemset(offtopn, 0, sizeof(int)));

  #ifdef MULTI_OFFLOAD
  constexpr size_t multiplier = MOTIF_GROUP_SIZE;
  #else
  constexpr size_t multiplier = 1;
  #endif
  constexpr size_t offload_size = 2092 * 96 * multiplier;

  gpuErrchk(cudaMalloc(&offload_width_d, offload_size * sizeof(int)));
  gpuErrchk(cudaMemset(offload_width_d, 0, offload_size * sizeof(int)));
  gpuErrchk(cudaMalloc(&offload_d, offload_size * sizeof(TContext)));
  gpuErrchk(cudaMemset(offload_d, 0, offload_size * sizeof(TContext)));
  gpuErrchk(cudaMalloc(&offloadn_d, offload_size * sizeof(TContext)));
  gpuErrchk(cudaMemset(offloadn_d, 0, offload_size * sizeof(TContext)));

}

GPUWorkerDYN::~GPUWorkerDYN() {
  gpuErrchk(cudaSetDevice(gpu_));
  gpuErrchk(cudaFree(count_d));
  gpuErrchk(cudaFree(yeild_d));
  gpuErrchk(cudaFree(source_d));
  gpuErrchk(cudaFree(offload_d));
  gpuErrchk(cudaFree(offloadn_d));
  gpuErrchk(cudaFree(offtop));
  gpuErrchk(cudaFree(offtopn));
  gpuErrchk(cudaFree(offload_width_d));

}

UINT64_T GPUWorkerDYN::run() {
  // Report Constants
  // printf("DEBUG: %i\n", DEBUG);
  std::cout << "FORCE_PRINTING_MATCHES: " << FORCE_PRINTING_MATCHES
            << "\nWARP_BALANCING: " << WARP_BALANCING
            << "\nDISPATCH_NO_MINE: " << DISPATCH_NO_MINE
            << "\nOFFLOADING: " << OFFLOADING
            << "\nSAVE_MATCHES: " << SAVE_MATCHES
            << "\nmatch_count_idx: " << match_count_idx
            << "\nPRINT_OFFLOAD: " << PRINT_OFFLOAD
            << "\n-----------------"
            << "\nNUM_MOTIFS: " << NUM_MOTIFS
            << "\nMOTIF_GROUP_SIZE: " << MOTIF_GROUP_SIZE
            << "\nMAX_NUM_EDGES: " << MAX_NUM_EDGES
            << "\nNUM_LEVELS: " << NUM_LEVELS
            << std::endl;
  gpuErrchk(cudaSetDevice(gpu_));
  // Get device properties
  cudaDeviceProp deviceProp;
  cudaGetDeviceProperties(&deviceProp, gpu_);

  int maxBlocksPerSM;
  cudaOccupancyMaxActiveBlocksPerMultiprocessor(&maxBlocksPerSM, MotifMatching_dispatch, sizeBlock_, 0);
  auto numBlocksA = maxBlocksPerSM * deviceProp.multiProcessorCount;

  cudaOccupancyMaxActiveBlocksPerMultiprocessor(&maxBlocksPerSM, MotifMatching_Expand, sizeBlock_, 0);
  auto numBlocksB = maxBlocksPerSM * deviceProp.multiProcessorCount;


  auto &dd = job_->data;

  count_ = TMotifMatchingGPUImpl(
      numBlocksA, numBlocksB, sizeBlock_,

      job_->end, job_->delta,

      dd->Eg_d, dd->graphNumEdges,
      dd->inEdgesV_d, dd->inEdgesR_d, dd->outEdgesV_d, dd->outEdgesR_d,
      dd->nodefeatures_d, dd->edgefeatures_d,

      dd->minfo(), dd->motifNumEdges,

      yeild_d,
      source_d,
      offload_d,
      offtop,
      offloadn_d,
      offtopn,
      offload_width_d,

      count_d
  );

  UINT64_T count_h[NUM_MOTIFS];
  gpuErrchk(cudaMemcpy(count_h, count_d, sizeof(UINT64_T) * NUM_MOTIFS, cudaMemcpyDeviceToHost));
  printf("GPU Count:");
  for(int motif=0; motif<NUM_MOTIFS; ++motif) {
    if (motif != 0) {
      printf(",");
    }
    printf(" %llu", count_h[motif]);
  }
  printf("\n");
  printf("Done printing the count.\n");
  std::fflush(stdout);
  // gpuErrchk(cudaFree(count_arr_D));
  count_ = count_h[0];

  return count_;
}

void GPUWorkerDYN::update_job() {
  job_->beg = job_->end;
}

void GPUWorkerDYN::take(MineJob &job) {
  gpuErrchk(cudaSetDevice(gpu_));
  GPUWorker::take(job);

  gpuErrchk(cudaMemset(yeild_d, 0, sizeof(int)));
  gpuErrchk(cudaMemset(offtop, 0, sizeof(int)))
  gpuErrchk(cudaMemset(offtopn, 0, sizeof(int)))
  gpuErrchk(cudaMemcpy(source_d, &(job_->beg), sizeof(int), cudaMemcpyHostToDevice))
}

extern "C" {
  GPUWorker *getWorker(int gpu);
}

GPUWorker *getWorker(int gpu) {
  return new GPUWorkerDYN(gpu);
}