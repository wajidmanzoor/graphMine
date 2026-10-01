#pragma once

namespace tot {

/**
 * @brief Dividy x by y and round up.
 */
constexpr __host__ __device__ __forceinline__ int div_up(int x, int y)
{
    return (x + y - 1) / y;
}

}  // namespace tot