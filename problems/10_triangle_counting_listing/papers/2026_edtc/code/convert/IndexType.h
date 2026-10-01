#ifndef __INDEXTYPE_H__
#define __INDEXTYPE_H__

#ifdef EDGE_8
    using edge_type = uint8_t;
    using hash_type = uint16_t;
    using iedge_type = int8_t;
    #define hash_move 8
#elif EDGE_16
    using edge_type = uint16_t;
    using hash_type = uint32_t;
    using iedge_type = int16_t;
    #define hash_move 16
#else
    using edge_type = uint32_t;
    using hash_type = uint64_t;
    using iedge_type = int32_t;
    #define hash_move 32
#endif
#ifdef OFFSET_8
    using offset_type = uint8_t;
    using ioffset_type = int8_t;
#elif OFFSET_16
    using offset_type = uint16_t;
    using ioffset_type = int16_t;
#elif OFFSET_32
    using offset_type = uint32_t;
    using ioffset_type = int32_t;
#else
    using offset_type = uint64_t;
    using ioffset_type = int64_t;
#endif

// #ifdef START1
//     #define offfset 1
// #else 
//     #define offfset 0
// #endif
    

#endif