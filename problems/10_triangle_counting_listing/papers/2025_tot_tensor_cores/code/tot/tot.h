#pragma once
// clang-format off
// Core includes
#include "common/types.h"
#include "common/macros.h"
#include "common/memory.h"
#include "common/constants.h"
#include "common/arithmetic.h"


// Utilities
#include "utils/timer.h"
#include "utils/option.h"
#include "utils/functors.h"
#include "utils/csr_helpers.h"


// Matrix formats
#include "formats/bitcsr.h"
#include "formats/bitcoo.h"
#include "formats/coo.h"
#include "formats/csr.h"




// Utilities - IO
#include "utils/io/mmio.h"
#include "utils/io/read.h"


// Operations
#include "operations/kernel.h"
#include "operations/triangle_count.h"
#include "operations/convert.h"
#include "operations/triangle_count_cpu.h"



namespace tot {
// Version information
constexpr int VERSION_MAJOR = 0;
constexpr int VERSION_MINOR = 1;
constexpr int VERSION_PATCH = 0;


}  // namespace tot