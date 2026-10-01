#pragma once

#include <thrust/device_vector.h>
#include <thrust/host_vector.h>
#include <thrust/system/omp/execution_policy.h>

namespace tot {

// Memory space tags
struct host_memory {};
struct device_memory {};

template<typename T, typename MemorySpace>
struct VectorTrait;

template<typename T>
struct VectorTrait<T, host_memory> {
    using MemoryVector = thrust::host_vector<T>;
    static constexpr auto execution_policy() -> decltype(thrust::host)
    {
        return thrust::host;
    }
};

template<typename T>
struct VectorTrait<T, device_memory> {
    using MemoryVector = thrust::device_vector<T>;
    static constexpr auto execution_policy() -> decltype(thrust::device)
    {
        return thrust::device;
    }
};

template<typename T, typename MemorySpace>
using VectorType = typename VectorTrait<T, MemorySpace>::MemoryVector;

// Helper type trait to check if T is a thrust::device_vector
template<typename T>
struct is_device_vector: std::false_type {};

template<typename T, typename Alloc>
struct is_device_vector<thrust::device_vector<T, Alloc>>: std::true_type {};

// Function to get the execution policy based on vector type
template<typename Vector>
auto get_exec_policy()
{
    if constexpr (is_device_vector<Vector>::value) {
        return thrust::device;
    }
    else {
        return thrust::omp::par;
    }
}

template<typename T, typename MemorySpace>
using Vector = typename std::
    conditional<std::is_same_v<MemorySpace, host_memory>, thrust::host_vector<T>, thrust::device_vector<T>>::type;

template<typename MemorySpace>
auto constexpr select_execution_policy()
{
    if constexpr (std::is_same_v<MemorySpace, host_memory>) {
        printf("host omp parallel execution policy\n");
        return thrust::omp::par;
    }
    else {
        return thrust::device;
    }
}

}  // namespace tot