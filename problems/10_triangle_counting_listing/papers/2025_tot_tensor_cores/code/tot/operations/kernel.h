#pragma once

#include <cuda.h>
#include <mma.h>

namespace tot {

__device__ __forceinline__ void load_hugebmp(BMP256 result, const unsigned long long* bitmaps, int idx)
{
    result[0] = __ldg(&bitmaps[idx * 4]);
    result[1] = __ldg(&bitmaps[idx * 4 + 1]);
    result[2] = __ldg(&bitmaps[idx * 4 + 2]);
    result[3] = __ldg(&bitmaps[idx * 4 + 3]);
}

template<typename IndexType, typename BitmapType, typename SumType>
__global__ void tot_kernel(const IndexType* __restrict__ A_positions,
                           const BitmapType* __restrict__ A_bitmaps,
                           const IndexType* __restrict__ B_positions,
                           const BitmapType* __restrict__ B_bitmaps,
                           IndexType num_unique_C_tiles,
                           const IndexType* __restrict__ tile_offsets,
                           const IndexType* __restrict__ M_positions,
                           SumType* C_sums)
{
    const IndexType wid     = threadIdx.x / WARP_SIZE;
    const IndexType lid     = threadIdx.x % WARP_SIZE;
    const IndexType bid     = blockIdx.x;
    const auto      tile_id = bid * WARPS_BLOCK + wid;

    if (tile_id >= num_unique_C_tiles) {
        return;
    }
    const IndexType tile_begin = tile_offsets[tile_id];
    const IndexType tile_end   = tile_offsets[min(tile_id + 1, num_unique_C_tiles)];

    nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16, half, nvcuda::wmma::row_major> a_frag;
    nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16, half, nvcuda::wmma::col_major> b_frag;
    nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16, half>                       acc_frag;

    nvcuda::wmma::fill_fragment(acc_frag, 0.0f);

    BMP256 A_bmp256, B_bmp256;

    int A_base_idx = lid / 4 * 16 + lid % 4 * 2;
    int B_base_idx = lid / 4 + lid % 4 * 32;

    int A_idx, B_idx;

#pragma unroll
    for (int i = tile_begin; i < tile_end; i++) {
        nvcuda::wmma::fill_fragment(a_frag, 0.0f);
        nvcuda::wmma::fill_fragment(b_frag, 0.0f);

        // We get the uint64 bmp for the tiles of A and B
        A_idx = __ldg(&A_positions[i]);
        B_idx = __ldg(&B_positions[i]);
        load_hugebmp(A_bmp256, A_bitmaps, A_idx);
        // if (A_idx >= num_unique_C_tiles) {
        //     assert(0 && "A_idx out of bound");
        // }
        // if (B_idx >= num_unique_C_tiles) {
        //     assert(0 && "B_idx out of bound");
        // }
        load_hugebmp(B_bmp256, B_bitmaps, B_idx);

#pragma unroll
        for (int j = 0; j < 4; j++) {
            const int  A_dst_idx  = A_base_idx + A_frag_offsets[j];
            const int  B_dst_idx  = B_base_idx + A_frag_offsets[j];
            const int  A_part_idx = A_dst_idx / 64;
            const int  A_bit_idx  = A_dst_idx % 64;
            const int  B_part_idx = B_dst_idx / 64;
            const int  B_bit_idx  = B_dst_idx % 64;
            const auto A_bmp64    = A_bmp256[A_part_idx];
            const auto B_bmp64    = B_bmp256[B_part_idx];

            a_frag.x[2 * j]     = (A_bmp64 & (BitmapType(1) << A_bit_idx)) > 0;
            a_frag.x[2 * j + 1] = (A_bmp64 & (BitmapType(2) << A_bit_idx)) > 0;
            b_frag.x[2 * j]     = (B_bmp64 & (BitmapType(1) << B_bit_idx)) > 0;
            b_frag.x[2 * j + 1] = (B_bmp64 & (BitmapType(1) << (B_bit_idx + 16))) > 0;
        }
        __syncwarp();
        nvcuda::wmma::mma_sync(acc_frag, a_frag, b_frag, acc_frag);
    }
    half2 acc_registers[4];

    const auto M_idx = __ldg(&M_positions[tile_id]);
    load_hugebmp(A_bmp256, A_bitmaps, M_idx);

#pragma unroll
    for (int i = 0; i < 4; i++) {
        const int  A_dst_idx  = A_base_idx + A_frag_offsets[i];
        const int  M_part_idx = A_dst_idx / 64;
        const int  M_bit_idx  = A_dst_idx % 64;
        const auto M_bmp64    = A_bmp256[M_part_idx];
        acc_registers[i].x    = (M_bmp64 & (BitmapType(1) << M_bit_idx)) > 0 ? acc_frag.x[i * 2] : half(0);
        acc_registers[i].y    = (M_bmp64 & (BitmapType(2) << M_bit_idx)) > 0 ? acc_frag.x[i * 2 + 1] : half(0);
    }

    //********************************
    // warp-level reduction on tensor core
    //********************************
    // 1-row X B
    nvcuda::wmma::fill_fragment(a_frag, 1);
    nvcuda::wmma::fill_fragment(b_frag, 0);
    nvcuda::wmma::fill_fragment(acc_frag, 0);
    // the left-half matrix is filled
#pragma unroll
    for (int i = 0; i < 4; i++) {
        b_frag.x[2 * i]     = __float2half(acc_registers[i].x);
        b_frag.x[2 * i + 1] = __float2half(acc_registers[i].y);
    }

    nvcuda::wmma::mma_sync(acc_frag, a_frag, b_frag, acc_frag);
    // A x 1-col
    nvcuda::wmma::fill_fragment(a_frag, 0.0);
    nvcuda::wmma::fill_fragment(b_frag, 1.0);

#pragma unroll
    for (int i = 0; i < 8; i++) {
        a_frag.x[i] = acc_frag.x[i];
    }
    nvcuda::wmma::fill_fragment(acc_frag, 0);
    nvcuda::wmma::mma_sync(acc_frag, a_frag, b_frag, acc_frag);

    if (lid == 0) {
        // C_sums[wid] = __half2float(acc_frag.x[0]);
        C_sums[tile_id] = static_cast<SumType>(__half2float(acc_frag.x[0]));
    }
}
}  // namespace tot