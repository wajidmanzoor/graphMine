#pragma once

namespace tot {

constexpr uint32_t BALLOT_MASK   = 0xffffffff;
constexpr int      WARP_SIZE     = 32;
constexpr int      WARPS_BLOCK   = 8;                        // warps per block
constexpr int      THREADS_BLOCK = WARPS_BLOCK * WARP_SIZE;  // threads per block
constexpr int      WMMA_M        = 16;
constexpr int      WMMA_N        = 16;
constexpr int      WMMA_K        = 16;
constexpr int      FRAG_DIM      = 16;
constexpr int      FRAG_SIZE     = 256;
constexpr int      NUM_BMP64     = 4;  // one huge bitmap is 4 small bitmaps

__constant__ int A_frag_offsets[4] = {0, 128, 8, 136};
__constant__ int B_frag_offsets[4] = {0, 8, 128, 136};

}  // namespace tot