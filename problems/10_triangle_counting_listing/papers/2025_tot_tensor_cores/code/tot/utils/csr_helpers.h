#pragma once

#include <thrust/adjacent_difference.h>
#include <thrust/binary_search.h>
#include <thrust/device_vector.h>
#include <thrust/logical.h>
#include <thrust/transform_reduce.h>

namespace tot {

template<typename Vector>
void get_row_lengths_from_pointers(Vector& rowlen, const Vector& rowptr)
{
    using IndexType = typename Vector::value_type;
    thrust::transform(rowptr.begin() + 1, rowptr.end(), rowptr.begin(), rowlen.begin(), thrust::minus<IndexType>());
}

template<typename Vector>
void get_row_pointers_from_indices(Vector& row_pointers, const Vector& row_indices)
{
    using IndexType = typename Vector::value_type;
    auto policy     = get_exec_policy<Vector>();

    ASSERT(thrust::is_sorted(policy, row_indices.begin(), row_indices.end()) && "row_indices must be sorted");

    thrust::lower_bound(policy,
                        row_indices.begin(),
                        row_indices.end(),
                        thrust::counting_iterator<IndexType>(0),
                        thrust::counting_iterator<IndexType>(row_pointers.size()),
                        row_pointers.begin());
}

template<typename Vector>
void get_row_indices_from_pointers(Vector& row_indices, const Vector& row_pointers)
{
    using IndexType   = typename Vector::value_type;
    auto       policy = get_exec_policy<Vector>();
    const auto nrow   = row_pointers.size() - 1;

    thrust::for_each(policy,
                     thrust::counting_iterator<IndexType>(0),
                     thrust::counting_iterator<IndexType>(nrow),
                     FillRowIndices<IndexType>(thrust::raw_pointer_cast(row_pointers.data()),
                                               thrust::raw_pointer_cast(row_indices.data())));
}

template<typename Vector>
void sort_columns_per_row(Vector& row_indices, Vector& column_indices)
{
    thrust::sort_by_key(column_indices.begin(), column_indices.end(), row_indices.begin());
    thrust::stable_sort_by_key(row_indices.begin(), row_indices.end(), column_indices.begin());
}

template<typename IndexVector, typename ValueVector>
void sort_columns_per_row(IndexVector& row_indices, IndexVector& column_indices, ValueVector& values)
{
    // sort columns per row
    thrust::sort_by_key(column_indices.begin(),
                        column_indices.end(),
                        thrust::make_zip_iterator(thrust::make_tuple(row_indices.begin(), values.begin())));
    thrust::stable_sort_by_key(row_indices.begin(),
                               row_indices.end(),
                               thrust::make_zip_iterator(thrust::make_tuple(column_indices.begin(), values.begin())));
}

}  // namespace tot