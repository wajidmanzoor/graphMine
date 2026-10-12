#pragma once

#include "cuda_runtime.h"

void upload2constant_topoSortKernel2D(
	uint_*					chunkSizeX_y,
	uint_*					chunkSizeX_h,
	const int				chunkNum
) ;

void upload2constant_bitCheckKernel2D(
	uint_*					bndmat_num,
	ull_*					chunk_offset_h,
	uint_*					maxDim2Compute,
	const int				chunkNum
);

void upload2constant_topoSortKernel3D(
	uint3&					chunkSizeX,
	uint_*					chunkSizeX_h,
	uint_*					chunkSizeX_d,
	const uint_				chunkNum_h,
	const uint_				chunkNum_d
);

void upload2constant_bitCheckKernel3D(
	uint3&					imgSizeX,
	uint_*					bndmat_num,
	ull_*					chunkOffsetX,
	uint_*					maxDim2Compute,
	const uint_				chunkNum
);


__host__ void  topoSort_2D(
	const ushort_			chunkID,
	uchar_*					match,
	uchar_*					crit,
	ushort_*				topoSrtbuf,
	ushort_*				chunkCritNum,
	const uint2&			chunkSizeX,
	const uint2&			blockSize,
	const uint2&			blockSizeX,
	cudaStream_t&			stream
);

__host__ void pathCount_2D(
	const ushort_			chunkID,
	uchar_*					match,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ushort_*				chunkCritNum,
	const					uint2& chunkSizeX,
	const					uint2& blockSize,
	const					uint2& blockSizeX,
	cudaStream_t&			stream
);

template <typename type>
__host__ void  bitCheck_2D(
	cudaTextureObject_t&	chunk,
	const ushort_			chunkID,
	uchar_*					crit,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ulonglong2*				bndmat,
	type*					filtVals,
	uchar2*					offsets,
	const					uint2& chunkSizeX,
	const					uint2& blockSize,
	const					uint2& blockSizeX,
	cudaStream_t&			stream
);

__host__ void topoSort_3D(
	const ushort_			chunkID,
	ushort_*				match,
	uchar_*					crit,
	ushort_*				buf,
	ushort_*				chunkCritNum,
	const uint3&			chunkSizeX,
	const uint3&			blockSize,
	const uint3&			blockSizeX,
	cudaStream_t&			stream
);

__host__ void pathCount_3D(
	const ushort_			chunkID,
	ushort_*				match,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ushort_*				chunkCritNum,
	const uint3&			chunkSizeX,
	const uint3&			blockSize,
	const uint3&			blockSizeX,
	cudaStream_t&			stream
);

template <typename type>
__host__ void bitCheck_3D(
	cudaTextureObject_t&	img,
	const ushort_			chunkID,
	uchar_*					crit,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ulonglong2*				bndmat,
	type*					filtVals,
	uchar2*					offsets,
	const uint3&			chunkSizeX,
	const uint3&			blockSize,
	const uint3&			blockSizeX,
	cudaStream_t&			stream
);

// Read 2bit region of an unsigned short type
__host__ __device__ uchar_ subdivide_short2bits_read(ushort_ t, uchar_ region);