#pragma once

#include <thrust/unique.h>

namespace tot {

template<typename CSR, typename COO>
void convert_coo_to_csr(CSR& csr, const COO& coo)
{
    csr.resize(coo.num_rows, coo.num_cols, coo.num_entries);
    get_row_pointers_from_indices(csr.row_pointers, coo.row_indices);

    thrust::copy(coo.column_indices.begin(), coo.column_indices.end(), csr.column_indices.begin());
    thrust::copy(coo.values.begin(), coo.values.end(), csr.values.begin());
}

template<typename CSR, typename COO>
void convert_csr_to_coo(COO& coo, const CSR& csr)
{
    coo.resize(csr.num_rows, csr.num_cols, csr.num_entries);
    get_row_indices_from_pointers(coo.row_indices, csr.row_pointers);
    thrust::copy(csr.column_indices.begin(), csr.column_indices.end(), coo.column_indices.begin());
    thrust::copy(csr.values.begin(), csr.values.end(), coo.values.begin());

    sort_columns_per_row(coo.row_indices, coo.column_indices, coo.values);
}

template<typename COO, typename BitmapCOO>
void convert_coo2bmp(COO mat_input, BitmapCOO& mat_output)
{
    using IndexType    = typename BitmapCOO::index_type;
    using BitmapType   = typename BitmapCOO::bitmap_type;
    using InValueType  = typename COO::value_type;
    using OutValueType = typename BitmapCOO::value_type;

    constexpr auto num_bmp64 = BitmapCOO::bmp64_count;
    // Use thrust::device directly for simplicity and readability.

    auto       exec      = thrust::device;
    const auto nnz       = mat_input.num_entries;
    const auto nrow      = mat_input.num_rows;
    const auto ncol      = mat_input.num_cols;
    const auto nrow_tile = div_up(nrow, FRAG_DIM);
    const auto ncol_tile = div_up(ncol, FRAG_DIM);
    ASSERT(nrow_tile * ncol_tile < std::numeric_limits<BitmapType>::max()
           && "BitmapType is not large enough to represent the number of tiles");

    thrust::sort_by_key(mat_input.column_indices.begin(),
                        mat_input.column_indices.end(),
                        thrust::make_zip_iterator(thrust::make_tuple(mat_input.row_indices.begin(), mat_input.values.begin())));
    thrust::stable_sort_by_key(
        mat_input.row_indices.begin(),
        mat_input.row_indices.end(),
        thrust::make_zip_iterator(thrust::make_tuple(mat_input.column_indices.begin(), mat_input.values.begin())));

    thrust::device_vector<BitmapType> tile_indices(nnz);
    thrust::device_vector<BitmapType> pos_in_tile(nnz);

    // Calculate tile indices and pos_in_tiles with a single pass.

    thrust::transform(
        exec,
        thrust::make_zip_iterator(thrust::make_tuple(mat_input.row_indices.begin(), mat_input.column_indices.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(mat_input.row_indices.end(), mat_input.column_indices.end())),
        thrust::make_zip_iterator(thrust::make_tuple(tile_indices.begin(), pos_in_tile.begin())),
        LocateTile256<BitmapType>(ncol_tile));

    // print_vec(tile_indices, "tile_indices: ");
    // print_vec(pos_in_tile, "pos_in_tile: ");

    // Sort based on tile indices. This operation affects the original matrices
    // in-place.
    //! due to this step, we have to utilize a vector of row_indices
    thrust::stable_sort_by_key(
        exec,
        tile_indices.begin(),
        tile_indices.end(),
        thrust::make_zip_iterator(thrust::make_tuple(
            mat_input.row_indices.begin(), mat_input.column_indices.begin(), mat_input.values.begin(), pos_in_tile.begin())));

    // Perform reduction by key in-place where possible.
    // Using Thrust's reduce_by_key to compact and aggregate bitmap
    // pos_in_tiles.
    thrust::device_vector<BitmapType> unique_tile_indices = tile_indices;
    auto                              tile_indices_end    = thrust::unique(exec, unique_tile_indices.begin(), unique_tile_indices.end());
    auto                              num_tiles           = tile_indices_end - unique_tile_indices.begin();
    unique_tile_indices.erase(tile_indices_end, unique_tile_indices.end());

    thrust::device_vector<BitmapType> bitmaps(num_tiles * num_bmp64);
    thrust::device_vector<BitmapType> tile_positions(nnz);

    thrust::lower_bound(unique_tile_indices.begin(),
                        unique_tile_indices.end(),
                        tile_indices.begin(),
                        tile_indices.end(),
                        tile_positions.begin());

    thrust::for_each(exec,
                     thrust::make_zip_iterator(thrust::make_tuple(tile_positions.begin(), pos_in_tile.begin())),
                     thrust::make_zip_iterator(thrust::make_tuple(tile_positions.end(), pos_in_tile.end())),
                     CombineToBMP256<BitmapType>(thrust::raw_pointer_cast(bitmaps.data())));

    // free vector
    tile_indices.resize(0);
    tile_positions.resize(0);
    pos_in_tile.resize(0);
    tile_indices.shrink_to_fit();
    tile_positions.shrink_to_fit();
    pos_in_tile.shrink_to_fit();

    // mat_input.row_indices.resize(num_tiles);
    // mat_input.row_indices.shrink_to_fit();
    // Setup output matrix dimensions based on FRAG_DIM.
    mat_output.resize(nrow_tile, ncol_tile, nnz, num_tiles);

    // Transform tile indices to row and column indices for the output matrix.
    thrust::transform(
        exec,
        unique_tile_indices.begin(),
        unique_tile_indices.end(),
        thrust::make_zip_iterator(thrust::make_tuple(mat_output.row_indices.begin(), mat_output.column_indices.begin())),
        COOIndices<IndexType, BitmapType>(ncol_tile));

    // Copying values and computing bmp_offsets is already efficient.
    mat_output.values = std::move(mat_input.values);

    thrust::transform(
        exec, bitmaps.begin(), bitmaps.end(), mat_output.tile_offsets.begin(), BmpPopcount<IndexType, BitmapType>());

    // Convert bit counts to offsets for the bitmap.
    thrust::exclusive_scan(
        exec, mat_output.tile_offsets.begin(), mat_output.tile_offsets.end(), mat_output.tile_offsets.begin(), 0);

    // Copy the final bitmap values to the output matrix.
    mat_output.bitmaps = std::move(bitmaps);
}

template<typename COO>
void convert_undirected(COO& A)
{
    using IndexType   = typename COO::index_type;
    using ValueType   = typename COO::value_type;
    using MemorySpace = typename COO::memory_space;
    auto exec         = select_execution_policy<MemorySpace>();

    CooMatrix<IndexType, ValueType, MemorySpace> A_undirected;

    // Create a temporary matrix 'temp' to hold concatenated A and At
    A_undirected.resize(A.num_rows, A.num_cols, A.num_entries * 2);

    thrust::copy(exec, A.row_indices.begin(), A.row_indices.end(), A_undirected.row_indices.begin());
    thrust::copy(
        exec, A.column_indices.begin(), A.column_indices.end(), A_undirected.row_indices.begin() + A.num_entries);

    thrust::copy(exec, A.column_indices.begin(), A.column_indices.end(), A_undirected.column_indices.begin());
    thrust::copy(exec, A.row_indices.begin(), A.row_indices.end(), A_undirected.column_indices.begin() + A.num_entries);

    thrust::copy(exec, A.values.begin(), A.values.end(), A_undirected.values.begin());
    thrust::copy(exec, A.values.begin(), A.values.end(), A_undirected.values.begin() + A.num_entries);

    auto zip_begin_A_undirected = thrust::make_zip_iterator(thrust::make_tuple(
        A_undirected.row_indices.begin(), A_undirected.column_indices.begin(), A_undirected.values.begin()));

    // Sort entries
    thrust::sort(exec, zip_begin_A_undirected, zip_begin_A_undirected + A_undirected.num_entries);
    // Remove duplicate entries

    auto unique_end = thrust::unique(exec, zip_begin_A_undirected, zip_begin_A_undirected + A_undirected.num_entries);
    // A_undirected.row_indices.erase(unique_end,
    // A_undirected.row_indices.end());
    auto new_end = thrust::remove_if(exec, zip_begin_A_undirected, unique_end, IsSelfLoop<IndexType>());

    int new_size = new_end - zip_begin_A_undirected;

    A_undirected.resize(A_undirected.num_rows, A_undirected.num_cols, new_size);

    sort_columns_per_row(A_undirected.row_indices, A_undirected.column_indices, A_undirected.values);

    A = A_undirected;
}

template<typename COO>
void extract_upper_triangular(COO& A)
{
    // auto L = A;
    COO L = A;

    auto new_end = thrust::copy_if(
        thrust::make_zip_iterator(thrust::make_tuple(A.row_indices.begin(), A.column_indices.begin())),
        thrust::make_zip_iterator(thrust::make_tuple(A.row_indices.end(), A.column_indices.end())),
        thrust::make_zip_iterator(thrust::make_tuple(L.row_indices.begin(), L.column_indices.begin())),
        IsUpperTriangular());

    size_t new_size = thrust::distance(
        thrust::make_zip_iterator(thrust::make_tuple(L.row_indices.begin(), L.column_indices.begin())),
        new_end);

    L.resize(A.num_rows, A.num_cols, new_size);

    A = L;
}

}  // namespace tot