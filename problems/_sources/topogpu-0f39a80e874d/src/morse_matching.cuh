#pragma once

void upload2constant_matchingKernel2D(
	uint_* imgSize_y_h,
	uint_* chunkSize_h,
	const int				num_chunks
);

void upload2constant_matchingKernel3D(
	uint_*					imgSize_y,
	uint_*					chunkSize_h,
	uint_*					chunkSize_d,
	const uint_				chunkNum_h,
	const uint_				chunkNum_d
);


template <typename type>
__host__ void procLowerStars_tile2D(
	cudaTextureObject_t& chunk,
	const uchar_			chunkID,
	uchar_* match,
	uchar_* crit_mask,
	const uint2				chunkSize,
	const uint2				blockSize,
	const uint2				blockSizeX,
	cudaStream_t& stream
);

template<typename type>
__host__ void procLowerStars_tile3D(
	cudaTextureObject_t&	chunk,
	const ushort_			chunkID,
	ushort_*				match,
	uchar_*					crit,
	const uint3				chunkSize,
	const uint3				blockSize,
	const uint3				blockSizeX,
	cudaStream_t&			stream
);