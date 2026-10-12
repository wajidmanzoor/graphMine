#include "util_cu.cuh"

#include "device_launch_parameters.h"

void find_and_query_device(DeviceProp& prop, int device_idx, bool debug, bool verbose) {
	/*
	Description: choose best device for computation
	@device_idx: use -1 to let the program choose for you, or choose manually
	*/
	int devID;
	int device_count;
	checkCudaErrors(cudaGetDeviceCount(&device_count));
	if (device_count == 0) {
		printf("CUDA error: no devices supporting CUDA.\n");
		exit(1);
	}
	else {
		if (device_idx > device_count - 1) {
			printf("GPU device request %d is not a valid.\n", device_idx);
			exit(1);
		}
		devID = (device_idx == -1) ? gpuGetMaxGflopsDeviceId() : device_idx;
		if (device_idx == -1) {
			if (verbose) printf("Automatically choosing best device %d\n", devID);
		}
		else {
			if (verbose) printf("Manually choosing device %d\n", devID);
		}
		int major = 0, minor = 0;
		checkCudaErrors(cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, devID));
		checkCudaErrors(cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, devID));

		int supportsCoopLaunch = 0;
		cudaDeviceGetAttribute(&supportsCoopLaunch, cudaDevAttrCooperativeLaunch, devID);
		if (!supportsCoopLaunch) {
			printf("Chosen device des not support cooperative launches\n");
			exit(1);
		}
		checkCudaErrors(cudaSetDevice(devID));

		cudaDeviceProp properties;
		cudaGetDeviceProperties(&properties, devID);
		prop = DeviceProp(properties, devID);

		if (debug) {
			printf("%d CUDA capable GPU device(s) detected.\n", device_count);
			printf("GPU Device %d: \"%s\" with compute capability %d.%d\n", devID, _ConvertSMVer2ArchName(major, minor), major, minor);
			printf("Device %d has %d streaming multiprocessors\n", devID, properties.multiProcessorCount);
		}
	}
}

/*
================================================================================
								  cudaArray
*/
void free_cudaArray(cudaArray*& arr) { checkCudaErrors(cudaFreeArray(arr)); }
void free_cudaArray_vec(const int num, std::vector<cudaArray*>& arr) { for (int i = 0; i < num; i++) free_cudaArray(arr[i]); arr.clear(); }

/*
================================================================================
							cuda Texture Object
*/
cudaTextureObject_t create_cuTexObj(cudaArray* cuArr) {
	cudaTextureDesc texDesc;
	memset(&texDesc, 0, sizeof(cudaTextureDesc));
	texDesc.normalizedCoords = false;
	texDesc.filterMode       = cudaFilterModePoint;
	texDesc.addressMode[0]   = cudaAddressModeBorder;
	texDesc.addressMode[1]   = cudaAddressModeBorder;
	texDesc.addressMode[2]   = cudaAddressModeBorder;
	texDesc.readMode         = cudaReadModeElementType;

	cudaResourceDesc texRsrc;
	memset(&texRsrc, 0, sizeof(cudaResourceDesc));
	texRsrc.resType          = cudaResourceTypeArray;
	texRsrc.res.array.array  = cuArr;

	cudaTextureObject_t texSrc;
	checkCudaErrors(cudaCreateTextureObject(&texSrc, &texRsrc, &texDesc, NULL));
	return texSrc;
}

std::vector<cudaTextureObject_t> create_cuTexObj_vec(const int num, std::vector<cudaArray*> cuArr) {
	std::vector<cudaTextureObject_t> texSrc_arr(num);
	for (int i = 0; i < num; i++) texSrc_arr[i] = create_cuTexObj(cuArr[i]);
	return texSrc_arr;
}

void free_cuTexObj(cudaTextureObject_t& cuTexObj) { checkCudaErrors(cudaDestroyTextureObject(cuTexObj)); }
void free_cuTexObj_vec(const int num, std::vector<cudaTextureObject_t>& cuTexObj_arr) { 
	for (int i = 0; i < num; i++) checkCudaErrors(cudaDestroyTextureObject(cuTexObj_arr[i]));
	cuTexObj_arr.clear();
}

/*
================================================================================
			CUDA streams and events creation and destruction
*/
std::vector<cudaEvent_t> create_cudaEvent_vec(const int num) {
	std::vector<cudaEvent_t> arr(num);
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaEventCreateWithFlags(&arr[i], cudaEventBlockingSync | cudaEventDisableTiming));
	return arr;
}

std::vector<cudaEvent_t> create_cudaEventTiming_vec(const int num) {
	std::vector<cudaEvent_t> arr(num);
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaEventCreateWithFlags(&arr[i], cudaEventDefault));
	return arr;
}

std::vector<cudaStream_t> create_cudaStream_vec(const int num) {
	std::vector<cudaStream_t> arr(num);
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaStreamCreate(&arr[i]));
	return arr;
}

void free_cudaEvent_vec(std::vector<cudaEvent_t>& cudaEvent_vec, const int num) {
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaEventDestroy(cudaEvent_vec[i]));
	cudaEvent_vec.clear();
}

void free_cudaStream_vec(std::vector<cudaStream_t>& cudaStream_vec, const int num) {
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaStreamDestroy(cudaStream_vec[i]));
	cudaStream_vec.clear();
}

/*
================================================================================
				Auto-decide chunk size and block size
*/

bool validate_chunkSize2D(
	uint2 imgSize,
	uint2 chunkSize,
	uint2 blockSize,
	bool  verbose = false
)
{
	if (chunkSize.x % blockSize.x == 1 || chunkSize.y % blockSize.y == 1 || (imgSize.x % chunkSize.x) % blockSize.x == 1) {
		if (verbose) printf("Error: chunk and block size combination results in 1 voxel width block\n");
		return false;
	}
	return true;
}

bool validate_chunkSize(
	uint3 imgSize,
	uint3 chunkSize,
	uint3 blockSize,
	bool  verbose = false
)
{
	if (chunkSize.x % blockSize.x == 1 || chunkSize.y % blockSize.y == 1 || chunkSize.z % blockSize.z == 1
		|| (imgSize.x % chunkSize.x) % blockSize.x == 1 || (imgSize.z % chunkSize.z) % blockSize.z == 1) {
		if (verbose) printf("Error: chunk and block size combination results in 1 voxel width block\n");
		return false;
	}
	return true;
}

inline uint_ next_pow2_ceil(uint_ x) {
	if (x <= 1u) return 1u;
	--x;
	for (uint_ s = 1u; s < sizeof(uint_) * 8u; s <<= 1) x |= (x >> s);
	return ++x;
}

template<typename type>
void choose_chunk_block_size2D(
	const uint2			imgSize,		// {height, width}
	const DeviceProp&	prop,
	uint2&				chunkSize,		// {height, width}
	uint2&				blockSize,		// {width (x), height (y)}; nonzero on entry = forced
	uint2				chunkSizeRef
)
{
	auto ceil_div = [](uint_ a, uint_ b) -> uint_ { return (a + b - 1u) / b; };

	const uint_ H = imgSize.x, W = imgSize.y;
	const uint_ targetBlocks = 6u * prop.SM;
	const uint_ cx_base = min(H, 2048u);
	const uint_ cx_cap = (chunkSizeRef.x > 0u && chunkSizeRef.x < cx_base) ? chunkSizeRef.x : cx_base;
	const uint_ cx_min = min(128u, H);
	const ull_  BYTES_LIMIT = 32ull << 20;

	const uint_ sizes[4] = { 4u, 8u, 16u, 32u };            // block dims: never 1

	// a forced block dim of 1 is never accepted -> treat as unset
	const uint_ forceX = (blockSize.x == 1u) ? 0u : blockSize.x;
	const uint_ forceY = (blockSize.y == 1u) ? 0u : blockSize.y;

	// score = (uneven, blockDiff, smallBlock, misalign, ~vol) ¡X smaller is better, lexicographic
	using Score = std::tuple<ull_, ull_, ull_, ull_, ull_>;
	Score best{ ~0ull, ~0ull, ~0ull, ~0ull, ~0ull };
	chunkSize = uint2{ 0u, 0u };
	uint2 bestBlock{ 0u, 0u };

	// Evaluate one candidate: first N-1 chunks have height cx, last chunk takes the remainder
	auto eval = [&](const uint_ cx, const uint_ bx, const uint_ by, const bool ignoreRange) {
		const uint_ threads = bx * by;
		if (threads > 1024u || threads > prop.Tpb) return;
		if (cx < 2u) return;                                          // no chunk of height 1
		if (!ignoreRange && (cx < cx_min || cx > cx_cap)) return;

		const uint_ n = ceil_div(H, cx);
		const uint_ lastH = H - (n - 1u) * cx;                        // 1..cx
		if (lastH < 2u) return;                                       // last chunk must not be height 1
		const ull_ uneven = cx - lastH;                               // 0 when H divides evenly

		const uint2 candChunk{ cx, W }, candBlock{ bx, by };
		if ((ull_)cx * W * sizeof(type) > BYTES_LIMIT) return;
		if (!validate_chunkSize2D(imgSize, candChunk, candBlock)) return;

		const ull_ bpc = (ull_)ceil_div(W, bx) * ceil_div(cx, by);
		const ull_ diff = (bpc > targetBlocks) ? (bpc - targetBlocks) : (targetBlocks - bpc);
		const ull_ smallBlk = (threads <= 128u) ? 1ull : 0ull;
		const ull_ misalign = (ull_)((cx % by) != 0u) + (ull_)((W % bx) != 0u);
		const ull_ vol = (ull_)cx * W;

		Score s{ uneven, diff, smallBlk, misalign, ~vol };
		if (s < best) { best = s; chunkSize = candChunk; bestBlock = candBlock; }
		};

	// Pass 1 (preferred): chunk heights that are multiples of the block height, within [cx_min, cx_cap]
	for (uint_ by : sizes) {
		if (forceY && by != forceY) continue;
		for (uint_ bx : sizes) {
			if (forceX && bx != forceX) continue;
			for (uint_ cx = by; cx <= cx_cap; cx += by) eval(cx, bx, by, false);
		}
	}

	// Pass 2 (relaxed): any chunk height 2..H, no range limits, non-multiples allowed (misalign penalised)
	if (chunkSize.x == 0u) {
		for (uint_ by : sizes) {
			if (forceY && by != forceY) continue;
			for (uint_ bx : sizes) {
				if (forceX && bx != forceX) continue;
				for (uint_ cx = H; cx >= 2u; --cx) eval(cx, bx, by, true);
			}
		}
	}

	// Pass 3: hard fallback (single chunk; only reachable if validate rejects everything)
	if (chunkSize.x == 0u) {
		chunkSize.x = H; chunkSize.y = W;
		bestBlock = uint2{ forceX ? forceX : 4u, forceY ? forceY : 4u };

		if (chunkSize.x && chunkSize.y && bestBlock.x && bestBlock.y &&
			(chunkSize.x % bestBlock.y == 1u || chunkSize.y % bestBlock.x == 1u ||
				imgSize.x % chunkSize.x == 1u))
			printf("Fatal error 2D: partial block of side length 1 detected, please manually set block size\n");
	}
	blockSize = bestBlock;
}
template void choose_chunk_block_size2D<uchar_>(const uint2, const DeviceProp&, uint2&, uint2&, uint2);
template void choose_chunk_block_size2D<ushort_>(const uint2, const DeviceProp&, uint2&, uint2&, uint2);
template void choose_chunk_block_size2D<int>(const uint2, const DeviceProp&, uint2&, uint2&, uint2);
template void choose_chunk_block_size2D<float>(const uint2, const DeviceProp&, uint2&, uint2&, uint2);

template<typename type>
void choose_chunk_block_size(
	const uint3			imgSize,		// {x, y, z}
	const DeviceProp&	prop,
	uint3&				chunkSize,		// {x, y, z}; chunked along x and z, y = full
	uint3&				blockSize,		// {x, y, z}; nonzero on entry = forced; same axes as chunk
	uint3				chunkSizeRef
)
{
	auto ceil_div = [](uint_ a, uint_ b) -> uint_ { return (a + b - 1u) / b; };

	const uint_ X = imgSize.x, Y = imgSize.y, Z = imgSize.z;
	const uint_ targetBlocks = 6u * prop.SM;
	const uint_ cx_base = min(X, 64u);
	const uint_ cz_base = min(Z, 32u);
	const uint_ cx_cap  = (chunkSizeRef.x > 0u && chunkSizeRef.x < cx_base) ? chunkSizeRef.x : cx_base;
	const uint_ cz_cap  = (chunkSizeRef.z > 0u && chunkSizeRef.z < cz_base) ? chunkSizeRef.z : cz_base;
	const uint_ cx_min  = min(4u, X);
	const uint_ cz_min  = min(4u, Z);
	const ull_  BYTES_LIMIT = 32ull << 20;

	// Block dims: never 1. Per-axis caps as in the original (kernel template instantiations).
	const uint_ sizes[5] = { 2u, 4u, 8u, 16u, 32u };
	const uint_ BXCAP = 16u, BYCAP = 8u, BZCAP = 8u;

	// a forced block dim of 1 is never accepted -> treat as unset
	const uint_ forceX = (blockSize.x == 1u) ? 0u : blockSize.x;
	const uint_ forceY = (blockSize.y == 1u) ? 0u : blockSize.y;
	const uint_ forceZ = (blockSize.z == 1u) ? 0u : blockSize.z;

	// score = (uneven, blockDiff, smallBlock, misalign, ~vol) ¡X smaller is better, lexicographic
	using Score = std::tuple<ull_, ull_, ull_, ull_, ull_>;
	Score best{ ~0ull, ~0ull, ~0ull, ~0ull, ~0ull };
	chunkSize = uint3{ 0u, 0u, 0u };
	uint3 bestBlock{ 0u, 0u, 0u };

	auto blockOK = [&](uint_ bx, uint_ by, uint_ bz) -> bool {
		if (forceX && bx != forceX) return false;
		if (forceY && by != forceY) return false;
		if (forceZ && bz != forceZ) return false;
		if (bx > BXCAP || by > BYCAP || bz > BZCAP) return false;
		const uint_ threads = bx * by * bz;
		return threads <= 1024u && threads <= prop.Tpb;
	};

	// Evaluate one candidate: first chunks along x/z have size cx/cz, the last ones take the remainder
	auto eval = [&](uint_ cx, uint_ cz, uint_ bx, uint_ by, uint_ bz, bool ignoreRange) {
		if (cx < 2u || cz < 2u) return;                                  // no chunk dim of 1
		if (!ignoreRange && (cx < cx_min || cx > cx_cap || cz < cz_min || cz > cz_cap)) return;

		const uint_ nx = ceil_div(X, cx), nz = ceil_div(Z, cz);
		const uint_ lastX = X - (nx - 1u) * cx;                          // 1..cx
		const uint_ lastZ = Z - (nz - 1u) * cz;                          // 1..cz
		if (lastX < 2u || lastZ < 2u) return;                            // last chunk must not be 1
		const ull_ uneven = (ull_)(cx - lastX) + (ull_)(cz - lastZ);     // 0 when both divide evenly

		const uint3 candChunk{ cx, Y, cz }, candBlock{ bx, by, bz };
		if ((ull_)cx * Y * cz * sizeof(type) > BYTES_LIMIT) return;
		if (!validate_chunkSize(imgSize, candChunk, candBlock)) return;

		const uint_ threads = bx * by * bz;
		const ull_ bpc      = (ull_)ceil_div(cx, bx) * ceil_div(Y, by) * ceil_div(cz, bz);
		const ull_ diff     = (bpc > targetBlocks) ? (bpc - targetBlocks) : (targetBlocks - bpc);
		const ull_ smallBlk = (threads <= 128u) ? 1ull : 0ull;
		const ull_ misalign = (ull_)((cx % bx) != 0u) + (ull_)((Y % by) != 0u) + (ull_)((cz % bz) != 0u);
		const ull_ vol      = (ull_)cx * Y * cz;

		Score s{ uneven, diff, smallBlk, misalign, ~vol };
		if (s < best) { best = s; chunkSize = candChunk; bestBlock = candBlock; }
	};

	// Pass 1 (preferred): chunk x/z sizes that are multiples of the block x/z, within [min, cap]
	for (uint_ bz : sizes) for (uint_ by : sizes) for (uint_ bx : sizes) {
		if (!blockOK(bx, by, bz)) continue;
		for (uint_ cx = bx; cx <= cx_cap; cx += bx)
			for (uint_ cz = bz; cz <= cz_cap; cz += bz)
				eval(cx, cz, bx, by, bz, false);
	}

	// Pass 2 (relaxed): any sizes 2..X / 2..Z, no range limits, non-multiples allowed (penalised)
	if (chunkSize.x == 0u) {
		for (uint_ bz : sizes) for (uint_ by : sizes) for (uint_ bx : sizes) {
			if (!blockOK(bx, by, bz)) continue;
			for (uint_ cx = X; cx >= 2u; --cx)
				for (uint_ cz = Z; cz >= 2u; --cz)
					eval(cx, cz, bx, by, bz, true);
		}
	}

	// Pass 3: hard fallback (whole volume; only reachable if validate rejects everything)
	if (chunkSize.x == 0u) {
		chunkSize = uint3{ X, Y, Z };
		bestBlock = uint3{ forceX ? forceX : 4u, forceY ? forceY : 4u, forceZ ? forceZ : 4u };

		if (chunkSize.x && chunkSize.y && chunkSize.z && bestBlock.x && bestBlock.y && bestBlock.z &&
			(chunkSize.x % bestBlock.x == 1u || chunkSize.y % bestBlock.y == 1u || chunkSize.z % bestBlock.z == 1u ||
				imgSize.x % chunkSize.x == 1u || imgSize.z % chunkSize.z == 1u))
			printf("Fatal error 3D: partial block of side length 1 detected, please manually set block size\n");
	}
	blockSize = bestBlock;
}
template void choose_chunk_block_size<uchar_>(const uint3, const DeviceProp&, uint3&, uint3&, uint3);
template void choose_chunk_block_size<ushort_>(const uint3, const DeviceProp&, uint3&, uint3&, uint3);
template void choose_chunk_block_size<int>(const uint3, const DeviceProp&, uint3&, uint3&, uint3);
template void choose_chunk_block_size<float>(const uint3, const DeviceProp&, uint3&, uint3&, uint3);