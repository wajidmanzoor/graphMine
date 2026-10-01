#pragma once

#include <cstdint>
#include <cuda_bf16.h>
#include <cuda_fp16.h>

namespace tot {

using uint8_t = unsigned char;
using bmp64_t = unsigned long long int;
using half    = __half;
using half2   = __half2;
using bf16    = __nv_bfloat16;
using bf16x2  = __nv_bfloat162;
using BMP256  = bmp64_t[4];

union Bitmap256_U {
    bmp64_t  bmp64[4];
    uint32_t bmp32[8];
};

enum class BMP_SIZE { BMP64,
                      BMP256 };

struct __align__(16) half8
{
    half2 x, y, z, w;
};

}  // namespace tot