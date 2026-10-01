#pragma once

namespace tot {

template<typename IndexType, typename... Args>
struct IsSelfLoop {
    template<typename TupleType>
    __host__ __device__ bool operator()(const TupleType& edge)
    {
        return thrust::get<0>(edge) == thrust::get<1>(edge);
    }
};

// Functor to check if a value is non-negative
struct IsNonNegative {
    __host__ __device__ bool operator()(int x)
    {
        return x >= 0;
    }
};

template<typename T>
struct is_N {
    T N_;

    __host__ __device__ is_N(T n):
        N_(n) {}

    __host__ __device__ bool operator()(const T& index) const
    {
        return index == N_;
    }
};

// Functor for filling row_indices from csr_input.row_pointers
template<typename IndexType>
struct FillRowIndices {
    const IndexType* row_pointers;
    IndexType*       row_indices;

    explicit FillRowIndices(const IndexType* _row_pointers, IndexType* _row_indices):
        row_pointers(_row_pointers), row_indices(_row_indices)
    {
    }

    __host__ __device__ void operator()(const IndexType row) const
    {
        for (IndexType i = row_pointers[row]; i < row_pointers[row + 1]; ++i) {
            row_indices[i] = row;
        }
    }
};

// Struct for calculating the offset based on tile index.
template<typename IndexType, typename BitmapType>
struct COOIndices {
    const BitmapType ncols;
    explicit COOIndices(BitmapType num_cols):
        ncols(num_cols) {}

    __host__ __device__ thrust::tuple<IndexType, IndexType> operator()(BitmapType tileIndex) const
    {
        IndexType row = static_cast<IndexType>(tileIndex / ncols);
        IndexType col = static_cast<IndexType>(tileIndex % ncols);
        return thrust::make_tuple(row, col);
    }
};

// Struct for locating the tile index and position within a tile.
template<typename BitmapType>
struct LocateTile256 {
    const BitmapType ncols;
    explicit LocateTile256(BitmapType num_cols):
        ncols(num_cols) {}

    __host__ __device__ thrust::tuple<BitmapType, BitmapType>
                        operator()(const thrust::tuple<BitmapType, BitmapType>& indices) const
    {
        const BitmapType row        = thrust::get<0>(indices);
        const BitmapType col        = thrust::get<1>(indices);
        BitmapType       tile_index = (row / FRAG_DIM) * ncols + (col / FRAG_DIM);
        BitmapType       position   = (row % FRAG_DIM) * FRAG_DIM + (col % FRAG_DIM);

        return thrust::make_tuple(tile_index, position);
    }
};

template<typename BitmapType>
struct CombineToBMP256 {
    BitmapType* bitmaps;
    explicit CombineToBMP256(BitmapType* bitmaps_):
        bitmaps(bitmaps_) {}

    __host__ __device__ void operator()(const thrust::tuple<BitmapType, BitmapType>& tup)
    {
        auto tile_idx   = thrust::get<0>(tup);
        auto pos        = thrust::get<1>(tup);
        auto seg_idx    = pos / 64;
        auto bit_idx    = pos % 64;
        auto global_idx = tile_idx * 4 + seg_idx;
        atomicOr((unsigned long long int*)&bitmaps[global_idx], 1ULL << bit_idx);
    }
};

template<typename IndexType, typename BitmapType>
struct BmpPopcount {
    __device__ IndexType operator()(BitmapType bmp64)
    {
        return (IndexType)__popcll(bmp64);
    }
};

template<typename IndexType, typename BitmapType>
struct try_mxm_huge {
    const BitmapType *      tileA_, *tileB_;
    constexpr static size_t bmp_dim = sizeof(BitmapType);
    try_mxm_huge(const BitmapType* tileA, const BitmapType* tileB):
        tileA_(tileA), tileB_(tileB) {}

    __host__ __device__ bool operator()(const IndexType& a, const IndexType& b)
    {
        BitmapType A[4] = {tileA_[4 * a], tileA_[4 * a + 1], tileA_[4 * a + 2], tileA_[4 * a + 3]};
        BitmapType B[4] = {tileB_[4 * b], tileB_[4 * b + 1], tileB_[4 * b + 2], tileB_[4 * b + 3]};

        BitmapType a_mask_base = 0x0001000100010001;

        BitmapType b_mask_base = 0x000000000000ffff;

        IndexType result = 0;

        for (int i = 0; i < 16; ++i) {
            const int b_seg        = i / 4;
            const int b_row_in_seg = i % 4;

            const BitmapType a_mask = a_mask_base << (i % 16);

            const BitmapType b_mask  = b_mask_base << (b_row_in_seg * 16);
            const BitmapType b_bmp16 = B[b_seg] & b_mask;

            for (int j = 0; j < 4; ++j) {
                result |= ((A[j] & a_mask) && b_bmp16);
            }
            if (result)
                break;
        }
        return result;
    }
};

template<typename IndexType>
struct binary_search_index {
    const IndexType *rows, *cols;
    IndexType        num_elements;

    binary_search_index(const IndexType* _rows, const IndexType* _cols, IndexType _num_elements):
        rows(_rows), cols(_cols), num_elements(_num_elements)
    {
    }

    __host__ __device__ IndexType operator()(const thrust::tuple<IndexType, IndexType>& new_elem) const
    {
        IndexType target_row = thrust::get<0>(new_elem);
        IndexType target_col = thrust::get<1>(new_elem);

        IndexType left = 0, right = num_elements - 1, found = -1;
        while (left <= right) {
            IndexType mid = left + (right - left) / 2;

            if (rows[mid] == target_row && cols[mid] == target_col) {
                return mid;
            }
            if (rows[mid] < target_row || (rows[mid] == target_row && cols[mid] < target_col)) {
                left = mid + 1;
            }
            else {
                right = mid - 1;
            }
        }
        return IndexType(-1);
    }
};

template<typename IndexType>
struct expand_mask {
    const IndexType* offset;
    const IndexType* mask;
    IndexType*       expanded_mask;
    expand_mask(const IndexType* _offset, const IndexType* _mask, IndexType* _expanded_mask):
        offset(_offset), mask(_mask), expanded_mask(_expanded_mask)
    {
    }

    __host__ __device__ void operator()(const IndexType& index) const
    {
        for (auto i = offset[index]; i < offset[index + 1]; ++i) {
            expanded_mask[i] = mask[index];
        }
    }
};
// Functor to check if an edge is in the strictly upper triangular portion
struct IsUpperTriangular {
    __host__ __device__ bool operator()(const thrust::tuple<int, int>& edge)
    {
        return thrust::get<0>(edge) < thrust::get<1>(edge);  // source < target
    }
};
}  // namespace tot