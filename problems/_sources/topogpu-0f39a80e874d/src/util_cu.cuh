#pragma once
#include "util.h"
#include "cuda_runtime.h"
#include <vector>
#include <future>
#include <tuple>
#include "ctpl_stl.h"

#define maxChunkNum_h_	 64														// maximum allowed chunk number in h direction
#define maxChunkNum_d_	 120													// maximum allowed chunk number in d direction
#define PATHCNT_BUF_SIZE 32														// path count buffer size, HAS to be a multiple of 32 and less than 1024, this number is the same as thread number per block in path counting
#define BITS_PER_THREAD sizeof(unsigned int) * 8								// number of bits/critical cells per thread handles, uint_: 32, ull_ 64
#define PATHCNT_BUF_BITS PATHCNT_BUF_SIZE * BITS_PER_THREAD						// number of bits in path count buffer, the maximum number of critical cells with dim > 1 can be handled

inline __device__ uchar_ uintsub8_read(uint_ t, uchar_ pos) {
	/*
		This function subdivide a 32-bit integer into 8 consecutive 4-bit regions.
		@t: input unsigned integer
		@pos: from which subregion to read the value
	*/
	switch (pos) {
	case 0:
		return t & 15;
	case 1:
		return (t >> 4) & 15;
	case 2:
		return (t >> 8) & 15;
	case 3:
		return (t >> 12) & 15;
	case 4:
		return (t >> 16) & 15;
	case 5:
		return (t >> 20) & 15;
	case 6:
		return (t >> 24) & 15;
	case 7:
		return (t >> 28) & 15;
	}
}

inline __device__ void uintsub8_write(uint_& t, uchar_ pos, uchar_ v) {
	/*
		This function subdivide a 32-bit integer into 8 consecutive 4-bit regions.
		@t: input unsigned integer
		@pos: from which subregion to write the value
		@v: the value to put in
	*/
	switch (pos) {
	case 0:
		t = t & 4294967280;
		switch (v) {
		case 0: break;
		case 1: t = t | 1; break;
		case 2: t = t | 2; break;
		case 3: t = t | 3; break;
		case 10: t = t | 10; break;
		case 11: t = t | 11; break;
		}
		break;
	case 1:
		t = t & 4294967055;
		switch (v) {
		case 0: break;
		case 1: t = t | 16; break;
		case 2: t = t | 32; break;
		case 3: t = t | 48; break;
		case 10: t = t | 160; break;
		case 11: t = t | 176; break;
		}
		break;
	case 2:
		t = t & 4294963455;
		switch (v) {
		case 0: break;
		case 1: t = t | 256; break;
		case 2: t = t | 512; break;
		case 3: t = t | 768; break;
		case 10: t = t | 2560; break;
		case 11: t = t | 2816; break;
		}
		break;
	case 3:
		t = t & 4294905855;
		switch (v) {
		case 0: break;
		case 1: t = t | 4096; break;
		case 2: t = t | 8192; break;
		case 3: t = t | 12288; break;
		case 10: t = t | 40960; break;
		case 11: t = t | 45056; break;
		}
		break;
	case 4:
		t = t & 4293984255;
		switch (v) {
		case 0: break;
		case 1: t = t | 65536; break;
		case 2: t = t | 131072; break;
		case 3: t = t | 196608; break;
		case 10: t = t | 655360; break;
		case 11: t = t | 720896; break;
		}
		break;
	case 5:
		t = t & 4279238655;
		switch (v) {
		case 0: break;
		case 1: t = t | 1048576; break;
		case 2: t = t | 2097152; break;
		case 3: t = t | 3145728; break;
		case 10: t = t | 10485760; break;
		case 11: t = t | 11534336; break;
		}
		break;
	case 6:
		t = t & 4043309055;
		switch (v) {
		case 0: break;
		case 1: t = t | 16777216; break;
		case 2: t = t | 33554432; break;
		case 3: t = t | 50331648; break;
		case 10: t = t | 167772160; break;
		case 11: t = t | 184549376; break;
		}
		break;
	case 7:
		t = t & 268435455;
		switch (v) {
		case 0: break;
		case 1: t = t | 268435456; break;
		case 2: t = t | 536870912; break;
		case 3: t = t | 805306368; break;
		case 10: t = t | 2684354560; break;
		case 11: t = t | 2952790016; break;
		}
		break;
	}
}

// CUDA Runtime error messages
#ifdef __DRIVER_TYPES_H__
static const char* _cudaGetErrorEnum(cudaError_t error) {
	return cudaGetErrorName(error);
}
#endif

#ifdef CUDA_DRIVER_API
// CUDA Driver API errors
static const char* _cudaGetErrorEnum(CUresult error) {
	static char unknown[] = "<unknown>";
	const char* ret = NULL;
	cuGetErrorName(error, &ret);
	return ret ? ret : unknown;
}
#endif

template <typename T>
void check(T result, char const* const func, const char* const file,
	int const line) {
	if (result) {
		fprintf(stderr, "CUDA error at %s:%d code=%d(%s) \"%s\" \n", file, line,
			static_cast<unsigned int>(result), _cudaGetErrorEnum(result), func);
		exit(EXIT_FAILURE);
	}
}
#define checkCudaErrors(val) check((val), #val, __FILE__, __LINE__)

// Beginning of GPU Architecture definitions
inline int _ConvertSMVer2Cores(int major, int minor) {
	// Defines for GPU Architecture types (using the SM version to determine
	// the # of cores per SM
	typedef struct {
		int SM;  // 0xMm (hexidecimal notation), M = SM Major version,
		// and m = SM minor version
		int Cores;
	} sSMtoCores;

	sSMtoCores nGpuArchCoresPerSM[] = {
		// Kepler
		{0x30,192}, {0x32,192}, {0x35,192}, {0x37,192},
		// Maxwell
		{0x50,128}, {0x52,128}, {0x53,128},
		// Pascal
		{0x60, 64}, {0x61,128}, {0x62,128},
		// Volta / Xavier / Turing
		{0x70, 64}, {0x72, 64}, {0x75, 64},
		// Ampere
		{0x80, 64},             // A100
		{0x86,128}, {0x87,128}, // GA10x, Orin
		// Ada Lovelace
		{0x89,128},             // RTX 40 series (e.g., 4080/4090)
		// Hopper
		{0x90,128},
		{-1,-1}
	};

	int index = 0;

	while (nGpuArchCoresPerSM[index].SM != -1) {
		if (nGpuArchCoresPerSM[index].SM == ((major << 4) + minor)) {
			return nGpuArchCoresPerSM[index].Cores;
		}

		index++;
	}

	// If we don't find the values, we default use the previous one
	// to run properly
	printf(
		"MapSMtoCores for SM %d.%d is undefined."
		"  Default to use %d Cores/SM\n",
		major, minor, nGpuArchCoresPerSM[index - 1].Cores);
	return nGpuArchCoresPerSM[index - 1].Cores;
}

// This function returns the best GPU (with maximum GFLOPS)
inline int gpuGetMaxGflopsDeviceId() {
	int current_device = 0, sm_per_multiproc = 0;
	int max_perf_device = 0;
	int device_count = 0;
	int devices_prohibited = 0;

	uint64_t max_compute_perf = 0;
	checkCudaErrors(cudaGetDeviceCount(&device_count));

	if (device_count == 0) {
		fprintf(stderr,
			"gpuGetMaxGflopsDeviceId() CUDA error:"
			" no devices supporting CUDA.\n");
		exit(EXIT_FAILURE);
	}

	// Find the best CUDA capable GPU device
	current_device = 0;

	while (current_device < device_count) {
		int computeMode = -1, major = 0, minor = 0;
		checkCudaErrors(cudaDeviceGetAttribute(&computeMode, cudaDevAttrComputeMode, current_device));
		checkCudaErrors(cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, current_device));
		checkCudaErrors(cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, current_device));

		// If this GPU is not running on Compute Mode prohibited,
		// then we can add it to the list
		if (computeMode != cudaComputeModeProhibited) {
			if (major == 9999 && minor == 9999) {
				sm_per_multiproc = 1;
			}
			else {
				sm_per_multiproc =
					_ConvertSMVer2Cores(major, minor);
			}
			int multiProcessorCount = 0, clockRate = 0;
			checkCudaErrors(cudaDeviceGetAttribute(&multiProcessorCount, cudaDevAttrMultiProcessorCount, current_device));
			checkCudaErrors(cudaDeviceGetAttribute(&clockRate, cudaDevAttrClockRate, current_device));
			uint64_t compute_perf = (uint64_t)multiProcessorCount * sm_per_multiproc * clockRate;

			if (compute_perf > max_compute_perf) {
				max_compute_perf = compute_perf;
				max_perf_device = current_device;
			}
		}
		else {
			devices_prohibited++;
		}

		++current_device;
	}

	if (devices_prohibited == device_count) {
		fprintf(stderr,
			"gpuGetMaxGflopsDeviceId() CUDA error:"
			" all devices have compute mode prohibited.\n");
		exit(EXIT_FAILURE);
	}

	return max_perf_device;
}

inline const char* _ConvertSMVer2ArchName(int major, int minor) {
	// Defines for GPU Architecture types (using the SM version to determine
	// the GPU Arch name)
	typedef struct {
		int SM;  // 0xMm (hexidecimal notation), M = SM Major version,
		// and m = SM minor version
		const char* name;
	} sSMtoArchName;

	sSMtoArchName nGpuArchNameSM[] = {
		{0x30, "Kepler"},
		{0x32, "Kepler"},
		{0x35, "Kepler"},
		{0x37, "Kepler"},
		{0x50, "Maxwell"},
		{0x52, "Maxwell"},
		{0x53, "Maxwell"},
		{0x60, "Pascal"},
		{0x61, "Pascal"},
		{0x62, "Pascal"},
		{0x70, "Volta"},
		{0x72, "Xavier"},
		{0x75, "Turing"},
		{-1, "Graphics Device"} };

	int index = 0;

	while (nGpuArchNameSM[index].SM != -1) {
		if (nGpuArchNameSM[index].SM == ((major << 4) + minor)) {
			return nGpuArchNameSM[index].name;
		}

		index++;
	}

	// If we don't find the values, we default use the previous one
	// to run properly
	printf(
		"MapSMtoArchName for SM %d.%d is undefined."
		"  Default to use %s\n",
		major, minor, nGpuArchNameSM[index - 1].name);
	return nGpuArchNameSM[index - 1].name;
}
// end of GPU Architecture definitions

struct DeviceProp {
	int		devID;	// chosen device ID
	int		SM;		// # streaming multi-processor
	int		Tpb;	// max number of threads per block
	int		maxBx;	// max block dimension in x
	int		maxBy;	// max block dimension in y
	int		maxBz;	// max block dimension in z

	DeviceProp() : devID(-1), SM(0), Tpb(0), maxBx(0), maxBy(0), maxBz(0) {}

explicit DeviceProp(const cudaDeviceProp& prop, int devID_) :
		devID(	devID_),
		SM(		prop.multiProcessorCount),
		Tpb(	prop.maxThreadsPerBlock),
		maxBx(	prop.maxThreadsDim[0]),
		maxBy(	prop.maxThreadsDim[1]),
		maxBz(	prop.maxThreadsDim[2]) {}
};

void find_and_query_device(DeviceProp& prop, int device_idx = -1, bool debug = false, bool verbose =false);

/*
================================================================================
						          cudaArray
*/
template<typename type>
cudaArray* malloc_cudaArray2D(
	const int h,
	const int w
) {
	/*
		Allocate 2D cudaArray
	*/
	cudaArray* resArray;
	cudaChannelFormatDesc typeTex = cudaCreateChannelDesc<type>();
	checkCudaErrors(cudaMallocArray(&resArray, &typeTex, w, h));
	return resArray;
}

template<typename type>
std::vector<cudaArray*> malloc_cudaArray2D_vec(
	const int num,
	const int h,
	const int w
) {
	/*
		Allocate a vector of 2D cudaArray
	*/
	std::vector<cudaArray*> resArray_array(num);
	for (uint_ i = 0; i < num; i++) resArray_array[i] = malloc_cudaArray2D<type>(h, w);
	return resArray_array;
}

template<typename type>
cudaArray* malloc_cudaArray3D(
	const int h,
	const int w,
	const int d
) {
	/*
		Allocate 3D cudaArray
	*/
	cudaArray* resArray;
	cudaExtent cuext = make_cudaExtent(w, h, d);
	cudaChannelFormatDesc typeTex = cudaCreateChannelDesc<type>();
	checkCudaErrors(cudaMalloc3DArray(&resArray, &typeTex, cuext));
	return resArray;
}

template<typename type>
std::vector<cudaArray*> malloc_cudaArray3D_vec(
	const int num,
	const int h,
	const int w,
	const int d
) {
	/*
		Allocate an array of 3D cudaArray
	*/
	std::vector<cudaArray*> resArray_array(num);
	for (uint_ i = 0; i < num; i++) resArray_array[i] = malloc_cudaArray3D<type>(h, w, d);
	return resArray_array;
}

void free_cudaArray(cudaArray*& arr);
void free_cudaArray_vec(const int num, std::vector<cudaArray*>& arr);

/*
================================================================================
							cuda Texture Object
*/
cudaTextureObject_t create_cuTexObj(
	cudaArray* cuArr
);

std::vector<cudaTextureObject_t> create_cuTexObj_vec(
	const int num,
	std::vector<cudaArray*> cuArr
);

void free_cuTexObj(cudaTextureObject_t& cuTexObj);
void free_cuTexObj_vec(const int num, std::vector<cudaTextureObject_t>& cuTexObj_arr);

/*
================================================================================
							memory transfer
*/
template<typename type>
cudaMemcpy3DParms create_3DCopyParms(
	cudaArray*& cuArr,
	type* data_h_,
	const int h,
	const int w,
	const int d,
	const int offset
) {
	/*
		Create parameters for 3D memory copy. Cuda does not provide routines like
		cudaMemcpyTo3DArray for 3D texture. Need to use cudaMemcpy3D.
	*/
	cudaMemcpy3DParms p = { 0 };
	p.srcPtr   = make_cudaPitchedPtr((void*)&data_h_[offset], w * sizeof(type), w, h);
	p.dstArray = cuArr;
	p.extent   = make_cudaExtent(w, h, d);
	p.kind     = cudaMemcpyHostToDevice;
	return p;
}

// ===================================================================
/* 1D or 1D array host memory allocation*/
template<typename type>
type* malloc1D_h_(const uint_ size) {
	type* data = (type*)malloc(size * sizeof(type));
	return data;
}

template<typename type>
std::vector<type*> malloc1D_vec_h_(const int num, const uint_ size) {
	std::vector<type*> arr(num);
	for (uint_ i = 0; i < num; i++) arr[i] = malloc1D_h_<type>(size);
	return arr;
}

template<typename type>
void free1D_vec_h_(const int num, std::vector<type*>& data) {
	for (uint_ i = 0; i < num; i++) free(data[i]);
	data.clear();
}

/* 1D or 1D array pinned host memory allocation*/
template<typename type>
type* malloc1D_pin_(const uint_ size) {
	type* data;
	checkCudaErrors(cudaMallocHost((void**)&data, size * sizeof(type)));
	return data;
}

template<typename type>
std::vector<type*> malloc1D_vec_pin_(const int num, const uint_ size) {
	std::vector<type*> arr(num);
	for (uint_ i = 0; i < num; i++) arr[i] = malloc1D_pin_<type>(size);
	return arr;
}

template<typename type>
void free1D_vec_pin(const int num, std::vector<type*>& data) {
	for (uint_ i = 0; i < num; i++) cudaFreeHost(data[i]);
	data.clear();
}

// ===================================================================
/* 1D or 1D array device memory allocation*/
template<typename type>
type* malloc1D_d_(const uint_ size) {
	type* data;
	checkCudaErrors(cudaMalloc((void**)&data, size * sizeof(type)));
	return data;
}

template<typename type>
std::vector<type*> malloc1D_vec_d_(const int num, const uint_ size) {
	std::vector<type*> arr(num);
	for (uint_ i = 0; i < num; i++) arr[i] = malloc1D_d_<type>(size);
	return arr;
}

template<typename type>
void free1D_vec_d_(const int num, std::vector<type*>& data) {
	for (uint_ i = 0; i < num; i++) checkCudaErrors(cudaFree(data[i]));
	data.clear();
}

// ===================================================================
/* CUDA streams and events creation and destruction*/
std::vector<cudaEvent_t> create_cudaEvent_vec(const int num);
std::vector<cudaEvent_t> create_cudaEventTiming_vec(const int num);
std::vector<cudaStream_t> create_cudaStream_vec(const int num);
void free_cudaEvent_vec(std::vector<cudaEvent_t>& cudaEvent_vec, const int num);
void free_cudaStream_vec(std::vector<cudaStream_t>& cudaStream_vec, const int num);


// ===================================================================
/* Auto - decide chunk size and block size */
template<typename type>
void choose_chunk_block_size2D(
	const uint2			imgSize,
	const DeviceProp& prop,
	uint2& chunkSize,
	uint2& blockSize,
	uint2				chunkSizeRef
);

template<typename type>
void choose_chunk_block_size(
	const uint3			imgSize,
	const DeviceProp&	prop,
	uint3&				chunkSize,
	uint3&				blockSize,
	uint3				chunkSizeRef
);

// <index, <value, offset, oder>> of a critical cell
template<typename type>
struct Element {
	type	value;
	uchar_	offset;
	ull_	order;
};

template <typename Fn>
inline void pool_run(ctpl::thread_pool& pool, uint_ n, Fn&& fn) {
	std::vector<std::future<void>> futs;
	futs.reserve(n);
	for (uint_ i = 0; i < n; ++i)
		futs.push_back(pool.push([&fn, i](int) { fn(i); }));
	for (auto& f : futs) f.get();          // rethrows exceptions, waits for completion
}