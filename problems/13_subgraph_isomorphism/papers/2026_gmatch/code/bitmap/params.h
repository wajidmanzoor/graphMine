#pragma once

// #define IDLE_CNT
// #define BALANCE_CNT

#define SHORT_CANDIDATE_SET

#define SYMMETRY_BREAKING

#ifdef SHORT_CANDIDATE_SET
#define BITMAP_SET_INTERSECTION
#define CandLen_t short
#else
#define CandLen_t int
#endif

#define LOCAL_WORK_STEALING

#define UNROLL_MIN 4
#define UNROLL_MAX 32

#define QVMAX 16

#define maxBlocks 1024
#define threadsPerBlock 256
#define warpsPerBlock (threadsPerBlock / 32)
#define warpNum (maxBlocks * warpsPerBlock)

#define memPoolBlockSize (32LL * QVMAX * sizeof(int))                 // # of bytes within a block
#ifdef GRAPHMINE_GMATCH_POOL_MIB
// GraphMine can share a GPU with model inference. Keep the artifact's original
// standalone default, but let the library bound its two eager BFS pools.
#define memPoolBlockNum (GRAPHMINE_GMATCH_POOL_MIB * 1024LL * 1024LL / memPoolBlockSize)
#else
#define memPoolBlockNum (1024LL * 1024LL * 5)                         // # of memory blocks within a mempool
#endif

#define FULL_MASK 0xffffffff
