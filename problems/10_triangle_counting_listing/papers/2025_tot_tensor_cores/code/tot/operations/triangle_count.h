#pragma once

#include <thrust/copy.h>
#include <thrust/device_ptr.h>
#include <thrust/device_vector.h>
#include <thrust/fill.h>
#include <thrust/functional.h>
#include <thrust/gather.h>
#include <thrust/iterator/constant_iterator.h>
#include <thrust/iterator/counting_iterator.h>
#include <thrust/iterator/permutation_iterator.h>
#include <thrust/iterator/transform_iterator.h>
#include <thrust/iterator/zip_iterator.h>
#include <thrust/scan.h>
#include <thrust/scatter.h>
#include <thrust/transform.h>

namespace tot {

template<typename BitMat>
size_t count_triangles_on_tensors(const BitMat& A_bmp, const BitMat& B_bmp, const BitMat& M_bmp)
{
    if (A_bmp.num_entries == 0 || B_bmp.num_entries == 0) {
        printf("Empty matrix multiplication input. Exiting...\n");
        return 0;
    }

    using IndexType   = typename BitMat::index_type;
    using BitmapType  = typename BitMat::bitmap_type;
    using MemorySpace = typename BitMat::memory_space;
    using PosType     = typename BitMat::index_type;
    auto exec         = select_execution_policy<MemorySpace>();

    Vector<IndexType, MemorySpace> A_row_pointers(A_bmp.num_rows + 1);
    // Vector<IndexType, MemorySpace> B_row_indices(B_bmp.num_tiles);
    // Vector<IndexType, MemorySpace> M_row_indices(M_bmp.num_tiles);

    get_row_pointers_from_indices(A_row_pointers, A_bmp.row_indices);

    const auto& B_row_pointers = A_row_pointers;
    const auto& M_row_pointers = A_row_pointers;

    //<< Step 1. Reduce by Key: B's COO rowidx -> B's Row Len
    Vector<PosType, MemorySpace> B_row_lengths(B_bmp.num_rows);

    thrust::transform(exec,
                      B_row_pointers.begin() + 1,
                      B_row_pointers.end(),
                      B_row_pointers.begin(),
                      B_row_lengths.begin(),
                      thrust::minus<PosType>());
    // Step 2. Gather
    Vector<PosType, MemorySpace> segment_lengths(A_bmp.num_tiles);
    //    Vector<IndexType, MemorySpace> segment_lengths(A_bmp.num_entries);
    thrust::gather(
        exec, A_bmp.column_indices.begin(), A_bmp.column_indices.end(), B_row_lengths.begin(), segment_lengths.begin());

    // Free B_row_lengths as it's no longer needed
    B_row_lengths.clear();
    B_row_lengths.shrink_to_fit();

    // Vector<IndexType, MemorySpace> output_offset(A_bmp.num_entries + 1);
    Vector<PosType, MemorySpace> output_offset(A_bmp.num_tiles + 1);

    // Step 3. Expand
    // Step 3.1 - exclusive scan
    thrust::inclusive_scan(exec, segment_lengths.begin(), segment_lengths.end(), output_offset.begin() + 1);
    const PosType total_mm_count = output_offset[A_bmp.num_tiles];

    if (total_mm_count < 0 || total_mm_count > std::numeric_limits<PosType>::max()) {
        throw std::runtime_error("total_mm_count exceeds maximum value representable by PosType");
    }
    if (total_mm_count == 0) {
        printf("Empty matrix multiplication result. Exiting...\n");
        return 0;
    }
    // std::cout << "total_mm_count " << total_mm_count << std::endl;

    // Step 3.2 - gather
    // Vector<IndexType, MemorySpace> A_positions(total_mm_count);
    // Vector<IndexType, MemorySpace> B_positions(total_mm_count);
    Vector<PosType, MemorySpace> A_positions(total_mm_count);
    Vector<PosType, MemorySpace> B_positions(total_mm_count);

    thrust::scatter_if(exec,
                       thrust::counting_iterator<IndexType>(0),
                       thrust::counting_iterator<IndexType>(A_bmp.num_tiles),
                       output_offset.begin(),
                       segment_lengths.begin(),
                       A_positions.begin());

    thrust::inclusive_scan(
        exec, A_positions.begin(), A_positions.end(), A_positions.begin(), thrust::maximum<PosType>());

    thrust::fill(exec, B_positions.begin(), B_positions.end(), 1);

    thrust::scatter_if(exec,
                       thrust::make_permutation_iterator(B_row_pointers.begin(), A_bmp.column_indices.begin()),
                       thrust::make_permutation_iterator(B_row_pointers.begin(), A_bmp.column_indices.begin())
                           + A_bmp.num_tiles,
                       output_offset.begin(),
                       segment_lengths.begin(),
                       B_positions.begin());

    thrust::inclusive_scan_by_key(
        exec, A_positions.begin(), A_positions.end(), B_positions.begin(), B_positions.begin());

    // Free vectors that are no longer needed
    segment_lengths.clear();
    segment_lengths.shrink_to_fit();
    // B_bmp.row_pointers.clear();
    // B_bmp.row_pointers.shrink_to_fit();
    output_offset.clear();
    output_offset.shrink_to_fit();

    //>> filter out the zero product use lightweight computation
    // print_vec(A_positions, "A_positions", 64);
    // print_vec(B_positions, "B_positions", 64);

    Vector<bool, MemorySpace> valid_mm(total_mm_count);

    thrust::transform(exec,
                      A_positions.begin(),
                      A_positions.end(),
                      B_positions.begin(),
                      valid_mm.begin(),
                      try_mxm_huge<PosType, BitmapType>(thrust::raw_pointer_cast(A_bmp.bitmaps.data()),
                                                        thrust::raw_pointer_cast(B_bmp.bitmaps.data())));

    // remove if valid_mm is false
    auto positions_end =
        thrust::remove_if(exec,
                          thrust::make_zip_iterator(thrust::make_tuple(A_positions.begin(), B_positions.begin())),
                          thrust::make_zip_iterator(thrust::make_tuple(A_positions.end(), B_positions.end())),
                          valid_mm.begin(),
                          thrust::logical_not<bool>());

    valid_mm.clear();
    valid_mm.shrink_to_fit();

    const auto valid_mm_count =
        positions_end - thrust::make_zip_iterator(thrust::make_tuple(A_positions.begin(), B_positions.begin()));

    // const auto valid_mm_count = total_mm_count;
    //    std::cout << "valid_mm_count " << valid_mm_count << std::endl;

    A_positions.resize(valid_mm_count);
    B_positions.resize(valid_mm_count);

    //>> creating a task list with entries that point to the tuples of A and B,
    Vector<PosType, MemorySpace> C_row_indices(valid_mm_count);
    Vector<PosType, MemorySpace> C_col_indices(valid_mm_count);

    thrust::gather(exec, A_positions.begin(), A_positions.end(), A_bmp.row_indices.begin(), C_row_indices.begin());
    thrust::gather(
        exec, B_positions.begin(), B_positions.end(), B_bmp.column_indices.begin(), C_col_indices.begin());

    Vector<PosType, MemorySpace> sorted_indices(valid_mm_count);
    thrust::sequence(sorted_indices.begin(), sorted_indices.end());

    thrust::stable_sort_by_key(
        exec,
        thrust::make_zip_iterator(thrust::make_tuple(C_row_indices.begin(), C_col_indices.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(C_row_indices.end(), C_col_indices.end())),
        sorted_indices.begin());

    // Rearrange gather location to include the sort by (I,J) info
    Vector<PosType, MemorySpace> A_positions_sorted(valid_mm_count);
    Vector<PosType, MemorySpace> B_positions_sorted(valid_mm_count);

    thrust::gather(exec, sorted_indices.begin(), sorted_indices.end(), A_positions.begin(), A_positions_sorted.begin());
    thrust::gather(exec, sorted_indices.begin(), sorted_indices.end(), B_positions.begin(), B_positions_sorted.begin());

    // Free vectors that are no longer needed
    A_positions.clear();
    A_positions.shrink_to_fit();
    B_positions.clear();
    B_positions.shrink_to_fit();
    sorted_indices.clear();
    sorted_indices.shrink_to_fit();

    // C_row and C_col now contain many duplicated elements (i.e., indices
    // of C tiles), as multiple AxB tiles might contribute to the same C
    // tile we shrink the duplication, such that only unique indices of C
    // tiles are kept. This is for intersection with the mask matrix
    Vector<PosType, MemorySpace> C_unique_offset(valid_mm_count + 1);
    Vector<PosType, MemorySpace> C_unique_rows(valid_mm_count);
    Vector<PosType, MemorySpace> C_unique_cols(valid_mm_count);
    Vector<PosType, MemorySpace> C_unique_counts(valid_mm_count);

    // C_unique counts
    auto [unique_indices_iterators, C_unique_counts_end] = thrust::reduce_by_key(
        exec,
        thrust::make_zip_iterator(thrust::make_tuple(C_row_indices.begin(), C_col_indices.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(C_row_indices.end(), C_col_indices.end())),
        thrust::make_constant_iterator(1),
        thrust::make_zip_iterator(thrust::make_tuple(C_unique_rows.begin(), C_unique_cols.begin())),
        C_unique_counts.begin());

    // Free C_row_indices and C_col_indices as they're no longer needed
    C_row_indices.clear();
    C_row_indices.shrink_to_fit();
    C_col_indices.clear();
    C_col_indices.shrink_to_fit();

    const auto num_unique_C_tiles = thrust::distance(C_unique_counts.begin(), C_unique_counts_end);
    //  Unique Offset
    C_unique_counts.resize(num_unique_C_tiles);
    C_unique_rows.resize(num_unique_C_tiles);
    C_unique_cols.resize(num_unique_C_tiles);
    C_unique_offset.resize(num_unique_C_tiles + 1);
    // C_unique_offset[i+1] - C_unique_offset[i] indicates the number of
    // repeated C_{i} tile
    thrust::inclusive_scan(exec, C_unique_counts.begin(), C_unique_counts.end(), C_unique_offset.begin() + 1);

    // Match C with the mask matrix A -- matrix intersection
    // output: get the  position of matched A tile,
    // if not matched, return -1
    Vector<PosType, MemorySpace> mask_positions(num_unique_C_tiles);

    thrust::transform(exec,
                      thrust::make_zip_iterator(thrust::make_tuple(C_unique_rows.begin(), C_unique_cols.begin())),
                      thrust::make_zip_iterator(thrust::make_tuple(C_unique_rows.end(), C_unique_cols.end())),
                      mask_positions.begin(),
                      binary_search_index<IndexType>(thrust::raw_pointer_cast(M_bmp.row_indices.data()),
                                                     thrust::raw_pointer_cast(M_bmp.column_indices.data()),
                                                     M_bmp.row_indices.size()));

    // Free C_unique_rows and C_unique_cols as they're no longer needed
    C_unique_rows.clear();
    C_unique_rows.shrink_to_fit();
    C_unique_cols.clear();
    C_unique_cols.shrink_to_fit();
    C_col_indices.clear();
    C_col_indices.shrink_to_fit();

    Vector<PosType, MemorySpace> expanded_mask(valid_mm_count);
    // mask_positions + offset -> expanded mask

    thrust::for_each(exec,
                     thrust::counting_iterator<PosType>(0),
                     thrust::counting_iterator<PosType>(num_unique_C_tiles),
                     expand_mask<PosType>(thrust::raw_pointer_cast(C_unique_offset.data()),
                                          thrust::raw_pointer_cast(mask_positions.data()),
                                          thrust::raw_pointer_cast(expanded_mask.data())));
    // clean A & B indices
    const auto AB_positions_end = thrust::remove_if(
        thrust::make_zip_iterator(thrust::make_tuple(A_positions_sorted.begin(), B_positions_sorted.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(A_positions_sorted.end(), B_positions_sorted.end())),
        expanded_mask.begin(),
        is_N<PosType>(-1));

    const auto num_AB_positions =
        AB_positions_end
        - thrust::make_zip_iterator(thrust::make_tuple(A_positions_sorted.begin(), B_positions_sorted.begin()));
    A_positions_sorted.resize(num_AB_positions);
    B_positions_sorted.resize(num_AB_positions);
    // clean C tiles
    auto C_unique_end = thrust::remove_if(
        thrust::make_zip_iterator(thrust::make_tuple(C_unique_counts.begin(), mask_positions.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(C_unique_counts.end(), mask_positions.end())),
        mask_positions.begin(),
        is_N<PosType>(-1));

    const PosType num_masked_C_tiles =
        C_unique_end - thrust::make_zip_iterator(thrust::make_tuple(C_unique_counts.begin(), mask_positions.begin()));

    C_unique_offset.resize(num_masked_C_tiles + 1);
    C_unique_counts.resize(num_masked_C_tiles);
    mask_positions.resize(num_masked_C_tiles);

    thrust::inclusive_scan(exec, C_unique_counts.begin(), C_unique_counts.end(), C_unique_offset.begin() + 1);
    //********************
    //** counting kernel
    //*******************

    // mask_positions.clear();
    // mask_positions.shrink_to_fit();

    auto raw_C_offset       = thrust::raw_pointer_cast(C_unique_offset.data());
    auto raw_A_positions    = thrust::raw_pointer_cast(A_positions_sorted.data());
    auto raw_B_positions    = thrust::raw_pointer_cast(B_positions_sorted.data());
    auto raw_mask_positions = thrust::raw_pointer_cast(mask_positions.data());

    auto raw_A_tiles = thrust::raw_pointer_cast(A_bmp.bitmaps.data());
    auto raw_B_tiles = thrust::raw_pointer_cast(B_bmp.bitmaps.data());

    // std::cout << "---------counting kernel---------" << std::endl;
    thrust::device_vector<size_t> C_sums;

    int gridDim3, blockDim3;

    C_sums.resize(num_masked_C_tiles);
    gridDim3  = div_up(num_masked_C_tiles, WARPS_BLOCK);
    blockDim3 = WARP_SIZE * WARPS_BLOCK;

    auto raw_C_sums = thrust::raw_pointer_cast(C_sums.data());

    CUDATimer my_timer;
    my_timer.start();
    tot_kernel<<<gridDim3, blockDim3>>>(raw_A_positions,
                                        raw_A_tiles,
                                        raw_B_positions,
                                        raw_B_tiles,
                                        num_masked_C_tiles,
                                        raw_C_offset,
                                        raw_mask_positions,
                                        raw_C_sums);

    my_timer.stop();
    printf("[Kernel] time: %lf ms\n", my_timer.elapsed());

    CHECK_CUDA(cudaPeekAtLastError());
    CHECK_CUDA(cudaDeviceSynchronize());
    size_t sum = thrust::reduce(C_sums.begin(), C_sums.end());

    return sum;
}
}  // namespace tot
