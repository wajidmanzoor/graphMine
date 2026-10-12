#include "fileIO.h"
#include "ctpl_stl.h"
#include "topo.cuh"
#include "morse_matching.cuh"
#include "morse_boundary.cuh"

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
 
#ifdef ENABLE_THRUST
	/*
		Thrust headers for sorting
	*/
	#include <thrust/sort.h>
	#include <thrust/host_vector.h>
	#include <thrust/device_vector.h>
#endif

template<typename type>
void TopoGPU2D<type>::run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<type>& ph) {
	/*
		Entry function for running the algorithm. The input is a file path to the binary file containing the data.
	*/
	// Init min value for essential pair
	minValue = std::numeric_limits<float>::max();

	ushort_ chunkID = 0;
	int datatype = parse_input_type(datatype_);
#ifdef ENABLE_TIMING
	timing.reset();
#endif
	ph.initialize(blockNum, bndmat_num, chunkNum, imgSizeX);
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		uchar_ bufID = chunkID % strmCnt;
		uint2 chunkSize_chunk	= make_uint2(chunkSize_h[chunkID], chunkSize.y);
		uint2 chunkSizeX_chunk	= make_uint2(chunkSizeX_h[chunkID], chunkSizeX.y);
		
		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 0]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 0], timings[7 * bufID + 1]));
			timing.host2devTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
#endif
		}

		if (filename.size() > 4 && (filename.compare(filename.size() - 4, 4, ".jpg") == 0 || filename.compare(filename.size() - 4, 4, ".png") == 0))
			fetch_chunk2D_fromImage_multiThread(filename, datatype, chunkID, bufID, streams[bufID]);
		else fetch_chunk2D_fromFile_multiThread(filename, datatype, chunkID, bufID, streams[bufID]);
		
		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(events[bufID]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 2]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 3]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 4]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 5]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 2], timings[7 * bufID + 3]));
			timing.cubiComplexTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 3], timings[7 * bufID + 4]));
			timing.topoSortTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 4], timings[7 * bufID + 5]));
			timing.pathCountTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 5], timings[7 * bufID + 6]));
			timing.dev2hostTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
#endif
			ph.bndmat_collect(bndmat_vec_h[bufID], vals_vec_h[bufID], offsets_vec_h[bufID]);
		}

		// CUDA kernels call
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 2], streams[bufID]));
#endif
		procLowerStars_tile2D<type>(texObj_vec[bufID], chunkID, match_vec_d[bufID], crit_vec_d[bufID], chunkSize_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 3], streams[bufID]));
#endif
		topoSort_2D(chunkID, match_vec_d[bufID], crit_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 4], streams[bufID]));
#endif
		pathCount_2D(chunkID, match_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
		bitCheck_2D<type>(texObj_vec[bufID], chunkID, crit_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], bndmat_vec_d[bufID], vals_vec_d[bufID], offsets_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 5], streams[bufID]));
#endif

		// Device to host memory copies and device memory reset
		checkCudaErrors(cudaMemsetAsync(crit_vec_d[bufID], 0, PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(uchar_), streams[bufID]));
		if (ph.ifbndMatReduct()) {
			checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[bufID], bndmat_vec_d[bufID], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(vals_vec_h[bufID], vals_vec_d[bufID], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[bufID], offsets_vec_d[bufID], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, streams[bufID]));
		}
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 6], streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(ulonglong2), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(vals_vec_d[bufID], 0, 2 * blockNum * bndmat_num * sizeof(type), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(offsets_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(uchar2), streams[bufID]));
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(events[bufID], streams[bufID]));
#endif
	}
	// Synchronize and get partial results from the remaining streams
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
#ifdef ENABLE_TIMING
		float elapsedTime;
		checkCudaErrors(cudaEventSynchronize(events[chunkID % strmCnt]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 2]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 3]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 4]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 5]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 2], timings[7 * (chunkID % strmCnt) + 3]));
		timing.cubiComplexTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 3], timings[7 * (chunkID % strmCnt) + 4]));
		timing.topoSortTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 4], timings[7 * (chunkID % strmCnt) + 5]));
		timing.pathCountTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 5], timings[7 * (chunkID % strmCnt) + 6]));
		timing.dev2hostTime += elapsedTime;
#else
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
#endif
		ph.bndmat_collect(bndmat_vec_h[chunkID % strmCnt], vals_vec_h[chunkID % strmCnt], offsets_vec_h[chunkID % strmCnt]);
	}
	ph.set_minValue(minValue);
}
template void TopoGPU2D<uchar_>::run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<uchar_>& ph);
template void TopoGPU2D<ushort_>::run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<ushort_>& ph);
template void TopoGPU2D<int>::run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<int>& ph);
template void TopoGPU2D<float>::run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<float>& ph);

template<typename type>
void TopoGPU2D<type>::run_frmArr(type* src, PH2D_multiThread<type>& ph) {
	/*
		Descriptions: compute persistent homology chunk by chunk
		@src: the input source array
	*/
	// Init min value for essential pair
	minValue = std::numeric_limits<float>::max();

	ushort_ bufID;
	ushort_ chunkID = 0;
#ifdef ENABLE_TIMING
	timing.reset();
#endif
	ph.initialize(blockNum, bndmat_num, chunkNum, imgSizeX);
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		bufID = chunkID % strmCnt;
		uint2 chunkSize_chunk = make_uint2(chunkSize_h[chunkID], chunkSize.y);
		uint2 chunkSizeX_chunk = make_uint2(chunkSizeX_h[chunkID], chunkSizeX.y);

		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 0]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 0], timings[7 * bufID + 1]));
			timing.host2devTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
#endif
		}
		
		fetch_chunk2D_frmArr(src, chunkID, bufID, streams[bufID]);
		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(events[bufID]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 2]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 3]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 4]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 5]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 2], timings[7 * bufID + 3]));
			timing.cubiComplexTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 3], timings[7 * bufID + 4]));
			timing.topoSortTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 4], timings[7 * bufID + 5]));
			timing.pathCountTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 5], timings[7 * bufID + 6]));
			timing.dev2hostTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
#endif
			ph.bndmat_collect(bndmat_vec_h[bufID], vals_vec_h[bufID], offsets_vec_h[bufID]);
		}

		// CUDA kernels call
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 2], streams[bufID]));
#endif
		procLowerStars_tile2D<type>(texObj_vec[bufID], chunkID, match_vec_d[bufID], crit_vec_d[bufID], chunkSize_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 3], streams[bufID]));
#endif
		topoSort_2D(chunkID, match_vec_d[bufID], crit_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 4], streams[bufID]));
#endif
		pathCount_2D(chunkID, match_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
		bitCheck_2D<type>(texObj_vec[bufID], chunkID, crit_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], bndmat_vec_d[bufID], vals_vec_d[bufID], offsets_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 5], streams[bufID]));
#endif

		// Device to host memory copies and device memory reset
		checkCudaErrors(cudaMemsetAsync(crit_vec_d[bufID], 0, PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(uchar_), streams[bufID]));
		if (ph.ifbndMatReduct()) {
			checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[bufID], bndmat_vec_d[bufID], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(vals_vec_h[bufID], vals_vec_d[bufID], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[bufID], offsets_vec_d[bufID], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, streams[bufID]));
		}
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 6], streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(ulonglong2), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(vals_vec_d[bufID], 0, 2 * blockNum * bndmat_num * sizeof(type), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(offsets_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(uchar2), streams[bufID]));
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(events[bufID], streams[bufID]));
#endif
	}
	// Synchronize all streams and retrieve results
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
#ifdef ENABLE_TIMING
		float elapsedTime;
		checkCudaErrors(cudaEventSynchronize(events[chunkID % strmCnt]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 2]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 3]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 4]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 5]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 2], timings[7 * (chunkID % strmCnt) + 3]));
		timing.cubiComplexTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 3], timings[7 * (chunkID % strmCnt) + 4]));
		timing.topoSortTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 4], timings[7 * (chunkID % strmCnt) + 5]));
		timing.pathCountTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 5], timings[7 * (chunkID % strmCnt) + 6]));
		timing.dev2hostTime += elapsedTime;
#else
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
#endif
		ph.bndmat_collect(bndmat_vec_h[chunkID % strmCnt], vals_vec_h[chunkID % strmCnt], offsets_vec_h[chunkID % strmCnt]);
	}
	ph.set_minValue(minValue);
}
template void TopoGPU2D<uchar_>::run_frmArr(uchar_* src, PH2D_multiThread<uchar_>& ph);
template void TopoGPU2D<ushort_>::run_frmArr(ushort_* src, PH2D_multiThread<ushort_>& ph);
template void TopoGPU2D<int>::run_frmArr(int* src, PH2D_multiThread<int>& ph);
template void TopoGPU2D<float>::run_frmArr(float* src, PH2D_multiThread<float>& ph);

template<typename type>
void TopoGPU2D<type>::proc_size() {
	// Decide chunk number in h and d direction
	chunkNum = iDivUp(imgSize.x, chunkSize.x);
	// Assign block and chunk size in matching grid
	blockSizeX.x = 2 * blockSize.x + 1;
	blockSizeX.y = 2 * blockSize.y + 1;
	chunkSizeX.x = 2 * chunkSize.x + 1;
	chunkSizeX.y = 2 * chunkSize.y + 1;
	imgSizeX.x = 2 * imgSize.x + 1;
	imgSizeX.y = 2 * imgSize.y + 1;
	// Determine the number of CUDA streams
	strmCnt = (chunkNum <= 3) ? chunkNum : 3;
	// Decide number of blocks per chunk in matching grid
	blockNum = iDivUp(chunkSizeX.x - 1, blockSizeX.y - 1) * iDivUp(chunkSizeX.y - 1, blockSizeX.x - 1);

	// Verbose output for block and chunk information
	if (verbose) {
		printf("Chunk size: %d %d\nBlock size: %d %d\n", chunkSize.x, chunkSize.y, blockSize.x, blockSize.y);
		printf("Number of streams: %d\nNumber of blocks per chunk: %d\nTotal number of chunks: %d\n", strmCnt, blockNum, chunkNum);
		if ((imgSize.x - (chunkNum - 1) * chunkSize.x) % blockSize.y == 1) printf("Last block has height = 1\n");
		if (imgSize.y % blockSize.x == 1) printf("Last block has width = 1\n");
	}
	// Verbose output for memory consumption
	if (verbose) {
		uint_ sqaure1024 = 1024 * 1024;
		uint_ cubic1024 = 1024 * 1024 * 1024;
		uint_ globalmem_tex = PRODUCT2(chunkSize.x + 4, chunkSize.y + 2) * sizeof(type);
		uint_ globalmem_grid = PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(ushort_);
		uint_ globalmem_crit = PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(uchar_);
		uint_ globalmem_perstream = globalmem_tex + globalmem_grid + globalmem_crit;
		// Output global memory usage in GB
		if (globalmem_perstream >= cubic1024) {
			float globalmem_perstream_GB = globalmem_perstream * 1.0f / cubic1024;
			float globalmem_total_GB = globalmem_perstream_GB * strmCnt;
			printf("Size of global memory per stream: %.3fGB\nTotal used global memory: %.3fGB\n", globalmem_perstream_GB, globalmem_total_GB);
		}
		// Output global memory usage in MB
		else {
			float globalmem_perstream_MB = globalmem_perstream * 1.0f / sqaure1024;
			float globalmem_total_MB = globalmem_perstream_MB * strmCnt;
			printf("Size of global memory per stream: %.3fMB\nTotal used global memory: %.3fMB\n", globalmem_perstream_MB, globalmem_total_MB);
		}
		printf("======================================================================\n");
	}
}
template void TopoGPU2D<uchar_>::proc_size();
template void TopoGPU2D<ushort_>::proc_size();
template void TopoGPU2D<int>::proc_size();
template void TopoGPU2D<float>::proc_size();

template<typename type>
void TopoGPU2D<type>::upload_info_2constant() {
	/*
		This function invokes sub-routines to upload information to constant memory for both kernels
	*/
	// Determine and upload chunk height for each chunk
	if (chunkNum > maxChunkNum_h_) { printf("Warning: chunk number in h direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }

	ull_* chunk_offset = new ull_[chunkNum];
	for (uint_ i = 0; i < chunkNum; i++) {
		chunkSize_h[i]	= ((i + 1) * chunkSize.x > imgSize.x) ? imgSize.x - i * chunkSize.x : chunkSize.x;
		chunkSizeX_h[i] = 2 * chunkSize_h[i] + 1;
		chunk_offset[i] = 1ULL * i * (chunkSizeX.x - 1) * chunkSizeX.y;
	}
	// Upload to constant memory in device
	upload2constant_matchingKernel2D(&imgSize.y, chunkSize_h, chunkNum);
	upload2constant_topoSortKernel2D(&chunkSizeX.y, chunkSizeX_h, chunkNum);
	upload2constant_bitCheckKernel2D(&bndmat_num, chunk_offset, &maxDim2Compute, chunkNum);
	// Free temporary host memory
	delete[] chunk_offset;
}
template void TopoGPU2D<uchar_>::upload_info_2constant();
template void TopoGPU2D<ushort_>::upload_info_2constant();
template void TopoGPU2D<int>::upload_info_2constant();
template void TopoGPU2D<float>::upload_info_2constant();


template<typename type>
void TopoGPU2D<type>::fetch_chunk2D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream) {
	/*
		Descriptions:
			Fetch chunk data from source data array. The chunk is taken
			as horizontal strip. The chunk has a halo of width 2 above
			and below. The host buffer has to be pinned.
		@src: source input data as array in host.
		@chunkID: ID of the chunk
		@bufID: ID of the buffer
	*/
#ifdef ENABLE_TIMING
	auto start = std::chrono::high_resolution_clock::now();
#endif
	uint_ rid_src_frm = (chunkID == 0) ? 0 : chunkID * chunkSize.x - 2;
	uint_ rid_src_to = ((chunkID + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (chunkID + 1) * chunkSize.x + 2;
	uint_ rid_dst_frm = (chunkID == 0) ? 2 : 0;
	const uint_ sliceSize_dst = chunkSize.y + 2;

	// fill chunk_vec_h[bufID] with max value of type
	std::fill_n(chunk_vec_h[bufID], PRODUCT2(chunkSize.x + 4, chunkSize.y + 2), std::numeric_limits<type>::max());
	// copy from src to chunk_vec_h[bufID]
	for (uint_ rid_iter = rid_src_frm; rid_iter < rid_src_to; rid_iter++) {
		type* src_row = src + rid_iter * chunkSize.y;
		type* dst_row = chunk_vec_h[bufID] + (rid_iter - rid_src_frm + rid_dst_frm) * sliceSize_dst + 1;
		for (uint_ i = 0; i < chunkSize.y; ++i) {
			type v = src_row[i];
			dst_row[i] = v;
			if (v < minValue) minValue = v;
		}
	}
#ifdef ENABLE_TIMING
	auto stop = std::chrono::high_resolution_clock::now();
	timing.loadTime += std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();
#endif

	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
#ifdef ENABLE_TIMING
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 0], stream));
#endif
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 1], stream));
}
template void TopoGPU2D<uchar_>::fetch_chunk2D_frmArr(uchar_* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream);
template void TopoGPU2D<ushort_>::fetch_chunk2D_frmArr(ushort_* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream);
template void TopoGPU2D<int>::fetch_chunk2D_frmArr(int* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream);
template void TopoGPU2D<float>::fetch_chunk2D_frmArr(float* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream);

template<typename type>
void TopoGPU2D<type>::fetch_chunk2D_fromImage_multiThread(
	const std::string&		path,
	int						datatype,	// 0: 8-bit (jpg/png), 1: 16-bit (png)
	ushort_					chunkID,
	uchar_					bufID,
	cudaStream_t&			stream
)
{
	/*
		Read a chunk of data from a .jpg/.png image to host memory with
		multi-threading (2D). Layout and halo convention matches
		fetch_chunk2D_frmArr / fetch_chunk2D_fromFile_multiThread.

		The image is decoded once (first call, or when 'path' changes) and
		cached in img_decoded_h; only the row copy/convert is parallelized.
	*/
#ifdef ENABLE_TIMING
	auto start = std::chrono::high_resolution_clock::now();
#endif

	// ---- Decode image once and cache it (JPEG/PNG cannot be row-seeked) ----
	if (img_decoded_h == nullptr || img_decoded_path != path || img_decoded_dt != datatype) {
		if (img_decoded_h) { stbi_image_free(img_decoded_h); img_decoded_h = nullptr; }

		int w = 0, h = 0, ch = 0;
		switch (datatype) {
		case 0: // 8-bit: jpg, 8-bit png -> force 1 channel (grayscale)
			img_decoded_h = stbi_load(path.c_str(), &w, &h, &ch, 1);
			break;
		case 1: // 16-bit: png only (jpg is always 8-bit)
			img_decoded_h = reinterpret_cast<void*>(stbi_load_16(path.c_str(), &w, &h, &ch, 1));
			break;
		default:
			std::cerr << "fetch_chunk2D_fromImage_multiThread: unsupported datatype!" << std::endl;
			exit(1);
		}
		if (!img_decoded_h) {
			std::cerr << "fetch_chunk2D_fromImage_multiThread: image load failure ("
				<< stbi_failure_reason() << ")" << std::endl;
			exit(1);
		}
		// Convention check: imgSize.x = #rows (height), imgSize.y = width
		if (static_cast<uint_>(h) != imgSize.x || static_cast<uint_>(w) != imgSize.y) {
			std::cerr << "fetch_chunk2D_fromImage_multiThread: image size ("
				<< h << " x " << w << ") does not match imgSize ("
				<< imgSize.x << " x " << imgSize.y << ")" << std::endl;
			exit(1);
		}
		img_decoded_path = path;
		img_decoded_dt = datatype;
	}

	// ---- Same geometry as fetch_chunk2D_fromFile_multiThread ----
	uint_ rid_src_frm = (chunkID == 0) ? 0 : chunkID * chunkSize.x - 2;
	uint_ rid_src_to = ((chunkID + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (chunkID + 1) * chunkSize.x + 2;
	uint_ rid_dst_frm = (chunkID == 0) ? 2 : 0;
	const uint_ rowSize_src = imgSize.y;			// image width
	const uint_ rowSize_dst = chunkSize.y + 2;		// chunk width (with halo)

	// ---- Configure multi-threading parameters (parallelize over rows) ----
	uint_ num_cores = std::thread::hardware_concurrency();
	uint_ rowsTotal = rid_src_to - rid_src_frm;
	if (num_cores == 0)	num_cores = 1;
	if (num_cores > rowsTotal) num_cores = rowsTotal;
	ctpl::thread_pool tp(num_cores);
	uint_ rowsPerThread = iDivUp(rowsTotal, num_cores);

	// Fill host chunk buffer with max value
	std::fill_n(chunk_vec_h[bufID], PRODUCT2(chunkSize.x + 4, chunkSize.y + 2), std::numeric_limits<type>::max());
	std::vector<type> localMins(num_cores, std::numeric_limits<type>::max());

	// ---- Launch threads ----
	for (uint_ i = 0; i < num_cores; ++i) {
		uint_ idx = i;
		uint_ this_src_frm = rid_src_frm + i * rowsPerThread;
		uint_ this_src_to = std::min(rid_src_frm + (i + 1) * rowsPerThread, rid_src_to);
		uint_ this_dst_frm = rid_dst_frm + i * rowsPerThread;
		if (this_src_frm >= this_src_to) continue;

		switch (datatype) {
		case 0: // 8-bit -> uchar_ source
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromImage_singleThread<uchar_, type>(
						static_cast<const uchar_*>(img_decoded_h),
						chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 1: // 16-bit -> ushort_ source
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromImage_singleThread<ushort_, type>(
						static_cast<const ushort_*>(img_decoded_h),
						chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		default:
			// unsupported datatype; handled at decode stage
			break;
		}
	}

	tp.stop(true);
	for (type localMin : localMins) if (localMin < minValue) minValue = localMin;
#ifdef ENABLE_TIMING
	auto stop = std::chrono::high_resolution_clock::now();
	timing.loadTime += std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();
#endif

	// ---- Copy from chunk_vec_h[bufID] to cuArr_vec[bufID] ----
	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
#ifdef ENABLE_TIMING
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 0], stream));
#endif
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 1], stream));
}

template<typename type>
void TopoGPU2D<type>::fetch_chunk2D_fromFile_multiThread(
	const std::string&	path,
	int					datatype,
	ushort_				chunkID,
	uchar_				bufID,
	cudaStream_t& stream
)
{
	/*
		Read a chunk of data from disk to host memory with multi-threading (2D).
		Layout and halo convention matches fetch_chunk2D_frmArr.
	*/
#ifdef ENABLE_TIMING
	auto start = std::chrono::high_resolution_clock::now();
#endif

	// Same geometry as fetch_chunk2D_frmArr
	uint_ rid_src_frm = (chunkID == 0) ? 0 : chunkID * chunkSize.x - 2;
	uint_ rid_src_to = ((chunkID + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (chunkID + 1) * chunkSize.x + 2;
	uint_ rid_dst_frm = (chunkID == 0) ? 2 : 0;
	const uint_ rowSize_src = imgSize.y;			// image width
	const uint_ rowSize_dst = chunkSize.y + 2;		// chunk width (with halo)

	// Configure multi-threading parameters (parallelize over rows)
	uint_ num_cores = std::thread::hardware_concurrency();
	uint_ rowsTotal = rid_src_to - rid_src_frm;
	if (num_cores == 0)	num_cores = 1;
	if (num_cores > rowsTotal) num_cores = rowsTotal;
	ctpl::thread_pool tp(num_cores);
	uint_ rowsPerThread = iDivUp(rowsTotal, num_cores);

	// Fill host chunk buffer with max value
	std::fill_n(chunk_vec_h[bufID], PRODUCT2(chunkSize.x + 4, chunkSize.y + 2), std::numeric_limits<type>::max());
	std::vector<type> localMins(num_cores, std::numeric_limits<type>::max());

	// Launch threads
	for (uint_ i = 0; i < num_cores; ++i) {
		uint_ idx = i;
		uint_ this_src_frm = rid_src_frm + i * rowsPerThread;
		uint_ this_src_to = std::min(rid_src_frm + (i + 1) * rowsPerThread, rid_src_to);
		uint_ this_dst_frm = rid_dst_frm + i * rowsPerThread;
		if (this_src_frm >= this_src_to) continue;

		switch (datatype) {
		case 0: // uchar_
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromFile_singleThread<uchar_, type>(
						path, chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 1: // ushort_
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromFile_singleThread<ushort_, type>(
						path, chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 2: // int
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromFile_singleThread<int, type>(
						path, chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 3: // float
			tp.push(
				[&, idx,
				rid_src_frm = this_src_frm,
				rid_src_to = this_src_to,
				rid_dst_frm = this_dst_frm,
				rowSize_src = rowSize_src,
				rowSize_dst = rowSize_dst](const uint_&) {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk2D_fromFile_singleThread<float, type>(
						path, chunk_vec_h[bufID], localMin,
						rid_src_frm, rid_src_to, rid_dst_frm, rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		default:
			// unsupported datatype; you can add error handling if desired
			break;
		}
	}

	tp.stop(true);
	for (type localMin : localMins) if (localMin < minValue) minValue = localMin;
#ifdef ENABLE_TIMING
	auto stop = std::chrono::high_resolution_clock::now();
	timing.loadTime += std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();
#endif

	// Copy from chunk_vec_h[bufID] to cuArr_vec[bufID]
	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
#ifdef ENABLE_TIMING
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 0], stream));
#endif
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 1], stream));
}

template <typename type>
void TopoGPU2D<type>::configure(uint2 imgSize_, uint_ maxDim) {
	maxDim2Compute = std::min(std::max((uint_)1, maxDim), (uint_)2);

	// Decide chunk and block sizes
	if ((imgSize_.x ^ imgSize.x) | (imgSize_.y ^ imgSize.y)) {
		if (imgSize_.y > chunkSize_atCreation.y) { printf("New image width > max allowed width ...\n"); exit(1); }

		imgSize = imgSize_;
		choose_chunk_block_size2D<type>(imgSize, prop, chunkSize, blockSize, chunkSize_atCreation);
		proc_size();
	}

	// Upload information to constant memory
	upload_info_2constant();
}
template void TopoGPU2D<uchar_>::configure(uint2 imgSize_, uint_ maxDim);
template void TopoGPU2D<ushort_>::configure(uint2 imgSize_, uint_ maxDim);
template void TopoGPU2D<int>::configure(uint2 imgSize_, uint_ maxDim);
template void TopoGPU2D<float>::configure(uint2 imgSize_, uint_ maxDim);

template <typename type>
void TopoGPU3D<type>::run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<type>& ph) {
	/*
		Entry function for running the algorithm. The input is a file path to the binary file containing the data.
	*/
	// Init min value for essential pair
	minValue = std::numeric_limits<float>::max();

	ushort_ chunkID = 0;
	int datatype = parse_input_type(datatype_);
#ifdef ENABLE_TIMING
	timing.reset();
#endif
	ph.initialize(blockNum, bndmat_num, chunkNum, imgSizeX);
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		uchar_ bufID = chunkID % strmCnt;
		uint3 chunkSize_chunk = make_uint3(chunkSize_h[chunkID % chunkNum_h], chunkSize.y, chunkSize_d[int(chunkID / chunkNum_h)]);
		uint3 chunkSizeX_chunk = make_uint3(chunkSizeX_h[chunkID % chunkNum_h], chunkSizeX.y, chunkSizeX_d[int(chunkID / chunkNum_h)]);

		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 0]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 0], timings[7 * bufID + 1]));
			timing.host2devTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
#endif
		}
		fetch_chunk3D_fromFile_multiThread(filename, datatype, chunkID, bufID, streams[bufID]);

		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(events[bufID]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 2]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 3]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 4]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 5]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 2], timings[7 * bufID + 3]));
			timing.cubiComplexTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 3], timings[7 * bufID + 4]));
			timing.topoSortTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 4], timings[7 * bufID + 5]));
			timing.pathCountTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 5], timings[7 * bufID + 6]));
			timing.dev2hostTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
#endif
			ph.bndmat_collect(bndmat_vec_h[bufID], vals_vec_h[bufID], offsets_vec_h[bufID]);
		}
		// CUDA kernels call
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 2], streams[bufID]));
#endif
		procLowerStars_tile3D<type>(texObj_vec[bufID], chunkID, match_vec_d[bufID], crit_vec_d[bufID], chunkSize_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 3], streams[bufID]));
#endif
		topoSort_3D(chunkID, match_vec_d[bufID], crit_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 4], streams[bufID]));
#endif
		pathCount_3D(chunkID, match_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
		bitCheck_3D<type>(texObj_vec[bufID], chunkID, crit_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], bndmat_vec_d[bufID], vals_vec_d[bufID], offsets_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 5], streams[bufID]));
#endif
		// Device to host memory copies and device memory reset
		checkCudaErrors(cudaMemsetAsync(crit_vec_d[bufID], 0, chunkSizeX.x * chunkSizeX.y * chunkSizeX.z * sizeof(uchar_), streams[bufID]));
		if (ph.ifbndMatReduct()) {
			checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[bufID], bndmat_vec_d[bufID], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(vals_vec_h[bufID], vals_vec_d[bufID], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[bufID], offsets_vec_d[bufID], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, streams[bufID]));
		}
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 6], streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(ulonglong2), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(vals_vec_d[bufID], 0, 2 * blockNum * bndmat_num * sizeof(type), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(offsets_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(uchar2), streams[bufID]));
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(events[bufID], streams[bufID]));
#endif
	}
	// Synchronize and get partial results from the remaining streams
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
#ifdef ENABLE_TIMING
		float elapsedTime;
		checkCudaErrors(cudaEventSynchronize(events[chunkID % strmCnt]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 2]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 3]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 4]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 5]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 2], timings[7 * (chunkID % strmCnt) + 3]));
		timing.cubiComplexTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 3], timings[7 * (chunkID % strmCnt) + 4]));
		timing.topoSortTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 4], timings[7 * (chunkID % strmCnt) + 5]));
		timing.pathCountTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 5], timings[7 * (chunkID % strmCnt) + 6]));
		timing.dev2hostTime += elapsedTime;
#else
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
#endif
		ph.bndmat_collect(bndmat_vec_h[chunkID % strmCnt], vals_vec_h[chunkID % strmCnt], offsets_vec_h[chunkID % strmCnt]);
	}
	ph.set_minValue(minValue);
}
template void TopoGPU3D<uchar_>::run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<uchar_>& ph);
template void TopoGPU3D<ushort_>::run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<ushort_>& ph);
template void TopoGPU3D<int>::run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<int>& ph);
template void TopoGPU3D<float>::run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<float>& ph);

template <typename type>
void TopoGPU3D<type>::run_frmArr(type* src, PH3D_multiThread<type>& ph) {
	/*
		Entry function for running the algorithm. The input needs to be already in the RAM.
	*/
	// Init min value for essential pair
	minValue = std::numeric_limits<float>::max();

	uchar_  bufID;
	ushort_ chunkID = 0;
#ifdef ENABLE_TIMING
	timing.reset();
#endif
	ph.initialize(blockNum, bndmat_num, chunkNum, imgSizeX);
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		bufID = chunkID % strmCnt;
		uint3 chunkSize_chunk = make_uint3(chunkSize_h[chunkID % chunkNum_h], chunkSize.y, chunkSize_d[int(chunkID / chunkNum_h)]);
		uint3 chunkSizeX_chunk = make_uint3(chunkSizeX_h[chunkID % chunkNum_h], chunkSizeX.y, chunkSizeX_d[int(chunkID / chunkNum_h)]);

		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 0]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 0], timings[7 * bufID + 1]));
			timing.host2devTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 1]));
#endif
		}
		fetch_chunk3D_frmArr(src, chunkID, bufID, streams[bufID]);

		if (chunkID >= strmCnt) {
#ifdef ENABLE_TIMING
			float elapsedTime;
			checkCudaErrors(cudaEventSynchronize(events[bufID]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 2]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 3]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 4]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 5]));
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 2], timings[7 * bufID + 3]));
			timing.cubiComplexTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 3], timings[7 * bufID + 4]));
			timing.topoSortTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 4], timings[7 * bufID + 5]));
			timing.pathCountTime += elapsedTime;
			checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * bufID + 5], timings[7 * bufID + 6]));
			timing.dev2hostTime += elapsedTime;
#else
			checkCudaErrors(cudaEventSynchronize(timings[7 * bufID + 6]));
#endif
			ph.bndmat_collect(bndmat_vec_h[bufID], vals_vec_h[bufID], offsets_vec_h[bufID]);
		}
		// CUDA kernels call
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 2], streams[bufID]));
#endif
		procLowerStars_tile3D<type>(texObj_vec[bufID], chunkID, match_vec_d[bufID], crit_vec_d[bufID], chunkSize_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 3], streams[bufID]));
#endif
		topoSort_3D(chunkID, match_vec_d[bufID], crit_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 4], streams[bufID]));
#endif
		pathCount_3D(chunkID, match_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], chunkCritNum_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
		bitCheck_3D<type>(texObj_vec[bufID], chunkID, crit_vec_d[bufID], pathCountbuf_vec_d[bufID], morsBoundbuf_vec_d[bufID], bndmat_vec_d[bufID], vals_vec_d[bufID], offsets_vec_d[bufID], chunkSizeX_chunk, blockSize, blockSizeX, streams[bufID]);
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 5], streams[bufID]));
#endif
		// Device to host memory copies and device memory reset
		checkCudaErrors(cudaMemsetAsync(crit_vec_d[bufID], 0, chunkSizeX.x * chunkSizeX.y * chunkSizeX.z * sizeof(uchar_), streams[bufID]));
		if (ph.ifbndMatReduct()) {
			checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[bufID], bndmat_vec_d[bufID], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(vals_vec_h[bufID], vals_vec_d[bufID], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, streams[bufID]));
			checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[bufID], offsets_vec_d[bufID], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, streams[bufID]));
		}
		checkCudaErrors(cudaEventRecord(timings[7 * bufID + 6], streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(ulonglong2), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(vals_vec_d[bufID], 0, 2 * blockNum * bndmat_num * sizeof(type), streams[bufID]));
		checkCudaErrors(cudaMemsetAsync(offsets_vec_d[bufID], 0, blockNum * bndmat_num * sizeof(uchar2), streams[bufID]));
#ifdef ENABLE_TIMING
		checkCudaErrors(cudaEventRecord(events[bufID], streams[bufID]));
#endif
	}
	// Synchronize and get partial results from the remaining streams
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
#ifdef ENABLE_TIMING
		float elapsedTime;
		checkCudaErrors(cudaEventSynchronize(events[chunkID % strmCnt]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 2]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 3]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 4]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 5]));
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 2], timings[7 * (chunkID % strmCnt) + 3]));
		timing.cubiComplexTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 3], timings[7 * (chunkID % strmCnt) + 4]));
		timing.topoSortTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 4], timings[7 * (chunkID % strmCnt) + 5]));
		timing.pathCountTime += elapsedTime;
		checkCudaErrors(cudaEventElapsedTime(&elapsedTime, timings[7 * (chunkID % strmCnt) + 5], timings[7 * (chunkID % strmCnt) + 6]));
		timing.dev2hostTime += elapsedTime;
#else
		checkCudaErrors(cudaEventSynchronize(timings[7 * (chunkID % strmCnt) + 6]));
#endif
		ph.bndmat_collect(bndmat_vec_h[chunkID % strmCnt], vals_vec_h[chunkID % strmCnt], offsets_vec_h[chunkID % strmCnt]);
	}
	ph.set_minValue(minValue);
}
template void TopoGPU3D<uchar_>::run_frmArr(uchar_* src, PH3D_multiThread<uchar_>& ph);
template void TopoGPU3D<ushort_>::run_frmArr(ushort_* src, PH3D_multiThread<ushort_>& ph);
template void TopoGPU3D<int>::run_frmArr(int* src, PH3D_multiThread<int>& ph);
template void TopoGPU3D<float>::run_frmArr(float* src, PH3D_multiThread<float>& ph);

template <typename type>
void TopoGPU3D<type>::configure(uint3 imgSize_, uint_ maxDim) {
	maxDim2Compute	= std::min(std::max((uint_)1, maxDim), (uint_)3);

	// Decide chunk and block sizes
	if ((imgSize_.x ^ imgSize.x) | (imgSize_.y ^ imgSize.y) | (imgSize_.z ^ imgSize.z)) {
		if (imgSize_.y > chunkSize_atCreation.y) { printf("New image width > max allowed width ...\n"); exit(1); }

		imgSize	= imgSize_;
		choose_chunk_block_size<type>(imgSize, prop, chunkSize, blockSize, chunkSize_atCreation);
		proc_size();
	}
	
	// Upload information to constant memory
	upload_info_2constant();
	// Initialize cuda 3D copy parameters
	for (uint_ i = 0; i < strmCnt; i++) cpyParams_vec[i] = create_3DCopyParms<type>(cuArr_vec[i], chunk_vec_h[i], chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4, 0);
}
template void TopoGPU3D<uchar_>::configure(uint3 imgSize_, uint_ maxDim);
template void TopoGPU3D<ushort_>::configure(uint3 imgSize_, uint_ maxDim);
template void TopoGPU3D<int>::configure(uint3 imgSize_, uint_ maxDim);
template void TopoGPU3D<float>::configure(uint3 imgSize_, uint_ maxDim);

template <typename type>
void TopoGPU3D<type>::fetch_chunk3D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream) {
	/*
		Read a chunk of data from the disk to the host memory with multi-threading
	*/
#ifdef ENABLE_TIMING
	auto start = std::chrono::high_resolution_clock::now();
#endif
	uint_ hid = chunkID % chunkNum_h;															// height id
	uint_ did = chunkID / chunkNum_h;															// depth id
	uint_ hid_src_frm = (hid == 0) ? 0 : hid * chunkSize.x - 2;
	uint_ did_src_frm = (did == 0) ? 0 : did * chunkSize.z - 2;
	uint_ hid_src_to = ((hid + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (hid + 1) * chunkSize.x + 2;
	uint_ did_src_to = ((did + 1) * chunkSize.z + 2 > imgSize.z) ? imgSize.z : (did + 1) * chunkSize.z + 2;
	uint_ hid_dst_frm = (hid == 0) ? 2 : 0;
	uint_ did_dst_frm = (did == 0) ? 2 : 0;
	const uint_ sliceSize_src = imgSize.x * imgSize.y;
	const uint_ sliceSize_dst = (chunkSize.x + 4) * (chunkSize.y + 2);

	// Configure multi-threading parameters
	uint_ num_cores = std::thread::hardware_concurrency();
	if (num_cores > did_src_to - did_src_frm) num_cores = did_src_to - did_src_frm;
	ctpl::thread_pool tp(num_cores);
	uint_ slicePerThread = iDivUp(did_src_to - did_src_frm, num_cores);
	// fill chunk_vec_h[bufID] with max value of type
	std::fill_n(chunk_vec_h[bufID], PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4), std::numeric_limits<type>::max());
	std::vector<type> localMins(num_cores);

	// Launch threads
	uint_ toSlice;
	for (uint_ i = 0; i < num_cores; i++) {
		uint_ idx	= i;
		toSlice		= std::min(did_src_frm + (i + 1) * slicePerThread, did_src_to);
		switch (datatype) {
		case 0:
			tp.push(
				[&, idx, did_src_frm = did_src_frm + i * slicePerThread, did_src_to = toSlice,
				hid_src_frm = hid_src_frm, hid_src_to = hid_src_to,
				did_dst_frm = did_dst_frm + i * slicePerThread, hid_dst_frm = hid_dst_frm,
				sliceSize_src = sliceSize_src, sliceSize_dst = sliceSize_dst,
				rowSize_src = imgSize.y, rowSize_dst = chunkSize.y + 2](const uint_&) -> void {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk3D_fromFile_singleThread<uchar_, type>(
						path, chunk_vec_h[bufID], localMin,
						did_src_frm, did_src_to,
						hid_src_frm, hid_src_to,
						did_dst_frm, hid_dst_frm,
						sliceSize_src, sliceSize_dst,
						rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 1:
			tp.push(
				[&, idx, did_src_frm = did_src_frm + i * slicePerThread, did_src_to = toSlice,
				hid_src_frm = hid_src_frm, hid_src_to = hid_src_to,
				did_dst_frm = did_dst_frm + i * slicePerThread, hid_dst_frm = hid_dst_frm,
				sliceSize_src = sliceSize_src, sliceSize_dst = sliceSize_dst,
				rowSize_src = imgSize.y, rowSize_dst = chunkSize.y + 2](const uint_&) -> void {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk3D_fromFile_singleThread<ushort_, type>(
						path, chunk_vec_h[bufID], localMin,
						did_src_frm, did_src_to, 
						hid_src_frm, hid_src_to,
						did_dst_frm, hid_dst_frm,
						sliceSize_src, sliceSize_dst,
						rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 2:
			tp.push(
				[&, idx, did_src_frm = did_src_frm + i * slicePerThread, did_src_to = toSlice,
				hid_src_frm = hid_src_frm, hid_src_to = hid_src_to,
				did_dst_frm = did_dst_frm + i * slicePerThread, hid_dst_frm = hid_dst_frm,
				sliceSize_src = sliceSize_src, sliceSize_dst = sliceSize_dst,
				rowSize_src = imgSize.y, rowSize_dst = chunkSize.y + 2](const uint_&) -> void {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk3D_fromFile_singleThread<int, type>(
						path, chunk_vec_h[bufID], localMin,
						did_src_frm, did_src_to,
						hid_src_frm, hid_src_to,
						did_dst_frm, hid_dst_frm,
						sliceSize_src, sliceSize_dst,
						rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				}); break;
		case 3:
			tp.push(
				[&, idx, did_src_frm = did_src_frm + i * slicePerThread, did_src_to = toSlice,
				hid_src_frm = hid_src_frm, hid_src_to = hid_src_to,
				did_dst_frm = did_dst_frm + i * slicePerThread, hid_dst_frm = hid_dst_frm,
				sliceSize_src = sliceSize_src, sliceSize_dst = sliceSize_dst,
				rowSize_src = imgSize.y, rowSize_dst = chunkSize.y + 2](const uint_&) -> void {
					type localMin = std::numeric_limits<type>::max();
					fetch_chunk3D_fromFile_singleThread<float, type>(
						path, chunk_vec_h[bufID], localMin,
						did_src_frm, did_src_to,
						hid_src_frm, hid_src_to,
						did_dst_frm, hid_dst_frm,
						sliceSize_src, sliceSize_dst,
						rowSize_src, rowSize_dst);
					localMins[idx] = localMin;
				});
		}
	}
	tp.stop(true);
	for (type localMin : localMins) if (localMin < minValue) minValue = localMin;
#ifdef ENABLE_TIMING
	auto stop = std::chrono::high_resolution_clock::now();
	timing.loadTime += std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();

	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 0], stream));
#endif
	// copy from chunk_vec_h[bufID] to cuArr_vec[bufID]
	checkCudaErrors(cudaMemcpy3DAsync(&cpyParams_vec[bufID], stream));
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 1], stream));
}

template<typename type>
void TopoGPU3D<type>::fetch_chunk3D_frmArr(type* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream) {
#ifdef ENABLE_TIMING
	auto start = std::chrono::high_resolution_clock::now();
#endif
	uint_ hid					= chunkID % chunkNum_h;											// height id
	uint_ did					= chunkID / chunkNum_h;											// depth id
	uint_ hid_src_frm			= (hid == 0) ? 0 : hid * chunkSize.x - 2;
	uint_ did_src_frm			= (did == 0) ? 0 : did * chunkSize.z - 2;
	uint_ hid_src_to			= ((hid + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (hid + 1) * chunkSize.x + 2;
	uint_ did_src_to			= ((did + 1) * chunkSize.z + 2 > imgSize.z) ? imgSize.z : (did + 1) * chunkSize.z + 2;
	uint_ hid_dst_frm			= (hid == 0) ? 2 : 0;
	uint_ did_dst_frm			= (did == 0) ? 2 : 0;
	const uint_ sliceSize_src	= imgSize.x * imgSize.y;
	const uint_ sliceSize_dst	= (chunkSize.x + 4) * (chunkSize.y + 2);

	uint_ globalOffset_src;
	uint_ globalOffset_dst;
	// fill chunk_vec_h[bufID] with max value of type
	std::fill_n(chunk_vec_h[bufID], PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4), std::numeric_limits<type>::max());
	// copy from src to chunk_vec_h[bufID]
	for (uint_ did_iter = did_src_frm; did_iter < did_src_to; did_iter++) {

		globalOffset_src = did_iter * sliceSize_src + hid_src_frm * imgSize.y;
		globalOffset_dst = (did_iter - did_src_frm + did_dst_frm) * sliceSize_dst + hid_dst_frm * (chunkSize.y + 2) + 1;
		for (uint_ hid_iter = hid_src_frm; hid_iter < hid_src_to; hid_iter++) {

			type* dst_row = chunk_vec_h[bufID] + globalOffset_dst;
			type* src_row = src + globalOffset_src;
			for (uint_ i = 0; i < imgSize.y; ++i) {
				type v		= src_row[i];
				dst_row[i]	= v;
				if (v < minValue) minValue = v;
			}
			globalOffset_src += imgSize.y;
			globalOffset_dst += chunkSize.y + 2;
		}
	}
#ifdef ENABLE_TIMING
	auto stop = std::chrono::high_resolution_clock::now();
	timing.loadTime += std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();

	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 0], stream));
#endif
	// copy from chunk_vec_h[bufID] to cuArr_vec[bufID]
	checkCudaErrors(cudaMemcpy3DAsync(&cpyParams_vec[bufID], stream));
	checkCudaErrors(cudaEventRecord(timings[7 * bufID + 1], stream));
}
template void TopoGPU3D<uchar_>::fetch_chunk3D_frmArr(uchar_* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
template void TopoGPU3D<ushort_>::fetch_chunk3D_frmArr(ushort_* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
template void TopoGPU3D<int>::fetch_chunk3D_frmArr(int* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
template void TopoGPU3D<float>::fetch_chunk3D_frmArr(float* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);

template<typename type>
void TopoGPU3D<type>::proc_size() {
	// Decide chunk number in h and d direction
	chunkNum_h	 = iDivUp(imgSize.x, chunkSize.x);
	chunkNum_d	 = iDivUp(imgSize.z, chunkSize.z);
	chunkNum	 = chunkNum_h * chunkNum_d;
	if (chunkNum > 65536) { printf("Error: Total number of chunks exceed 65536.\n"); exit(1); }
	// Assign block and chunk size in matching grid
	blockSizeX.x = 2 * blockSize.x + 1;
	blockSizeX.y = 2 * blockSize.y + 1;
	blockSizeX.z = 2 * blockSize.z + 1;
	chunkSizeX.x = 2 * chunkSize.x + 1;
	chunkSizeX.y = 2 * chunkSize.y + 1;
	chunkSizeX.z = 2 * chunkSize.z + 1;
	imgSizeX.x	 = 2 * imgSize.x + 1;
	imgSizeX.y	 = 2 * imgSize.y + 1;
	imgSizeX.z	 = 2 * imgSize.z + 1;
	// Determine the number of CUDA streams
	strmCnt      = (chunkNum <= 3) ? chunkNum : 3;
	// Decide number of blocks per chunk in matching grid
	blockNum     = iDivUp(chunkSizeX.x - 1, blockSizeX.x - 1) * iDivUp(chunkSizeX.y - 1, blockSizeX.y - 1) * iDivUp(chunkSizeX.z - 1, blockSizeX.z - 1);
	// Verbose output for block and chunk information
	if (verbose) {
		printf("Chunk size: %d %d %d\nBlock size: %d %d %d\n", chunkSize.x, chunkSize.y, chunkSize.z, blockSize.x, blockSize.y, blockSize.z);
		printf("Number of streams: %d\nNumber of blocks per chunk: %d\nTotal number of chunks: %d\n", strmCnt, blockNum, chunkNum);
		if ((imgSize.x - (chunkNum_h - 1) * chunkSize.x) % blockSize.x == 1) printf("Last block has height = 1\n");
		if ((imgSize.z - (chunkNum_d - 1) * chunkSize.z) % blockSize.z == 1) printf("Last block has depth = 1\n");
		if (imgSize.y % blockSize.y == 1) printf("Last block has width = 1\n");
	}
	// Verbose output for memory consumption
	if (verbose) {
		uint_ sqaure1024			 = 1024 * 1024;
		uint_ cubic1024				 = 1024 * 1024 * 1024;
		uint_ globalmem_tex			 = PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4) * sizeof(type);
		uint_ globalmem_grid		 = PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(ushort_);
		uint_ globalmem_crit		 = PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(uchar_);
		uint_ globalmem_morsbound	 = PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * blockNum * 4 * sizeof(ushort_);
		uint_ globalmem_pathcount    = PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * blockNum * PATHCNT_BUF_SIZE * sizeof(uint_);
		uint_ globalmem_chunkcritnum = blockNum * sizeof(ushort_);
		uint_ globalmem_bndmat		 = blockNum * bndmat_num * sizeof(ulonglong2);
		uint_ globalmem_vals		 = 2 * blockNum * bndmat_num * sizeof(type);
		uint_ globalmem_offsets      = blockNum * bndmat_num * sizeof(uchar2);
		uint_ globalmem_perstream    = globalmem_tex + globalmem_grid + globalmem_crit + globalmem_morsbound + globalmem_pathcount + globalmem_chunkcritnum + globalmem_bndmat + globalmem_vals + globalmem_offsets;
		// Output global memory usage in GB
		if (globalmem_perstream >= cubic1024) {
			float globalmem_perstream_GB = globalmem_perstream * 1.0f / cubic1024;
			float globalmem_total_GB     = globalmem_perstream_GB * strmCnt;
			printf("Size of global memory per stream: %.3fGB\nTotal used global memory: %.3fGB\n", globalmem_perstream_GB, globalmem_total_GB);
		}
		// Output global memory usage in MB
		else {
			float globalmem_perstream_MB = globalmem_perstream * 1.0f / sqaure1024;
			float globalmem_total_MB     = globalmem_perstream_MB * strmCnt;
			printf("Size of global memory per stream: %.3fMB\nTotal used global memory: %.3fMB\n", globalmem_perstream_MB, globalmem_total_MB);
		}
		printf("======================================================================\n");
	}
}
template void TopoGPU3D<uchar_>::proc_size();
template void TopoGPU3D<ushort_>::proc_size();
template void TopoGPU3D<int>::proc_size();
template void TopoGPU3D<float>::proc_size();

template<typename type>
void TopoGPU3D<type>::upload_info_2constant() {
	/*
		This function invokes sub-routines to upload information to constant memory for both kernels
	*/
	// Determine and upload chunk height and depth for each chunk
	if (chunkNum_h > maxChunkNum_h_) { printf("Warning: chunk number in h direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }
	if (chunkNum_d > maxChunkNum_d_) { printf("Warning: chunk number in d direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }
	ull_* chunk_offset = new ull_[chunkNum];
	// Determine chunk height
	for (size_t i = 0; i < chunkNum_h; i++) {
		chunkSize_h[i]  = ((i + 1) * chunkSize.x > imgSize.x) ? imgSize.x - i * chunkSize.x : chunkSize.x;
		chunkSizeX_h[i] = 2 * chunkSize_h[i] + 1;
	}
	// Determine chunk depth
	for (size_t i = 0; i < chunkNum_d; i++) {
		chunkSize_d[i]  = ((i + 1) * chunkSize.z > imgSize.z) ? imgSize.z - i * chunkSize.z : chunkSize.z;
		chunkSizeX_d[i] = 2 * chunkSize_d[i] + 1;
	}
	// Determine chunk offset, chunks are organized from top to bottom and then from front to back
	for (size_t i = 0; i < chunkNum; i++) {
		uint_ hid		= i % chunkNum_h;											// height id
		uint_ did		= i / chunkNum_h;											// depth id
		chunk_offset[i] = 1ULL * did * (2 * imgSize.x + 1) * chunkSizeX.y * (chunkSizeX.z - 1) + 1ULL * hid * (chunkSizeX.x - 1) * chunkSizeX.y;
	}
	// Upload to constant memory in device
	upload2constant_matchingKernel3D(&imgSize.y, chunkSize_h, chunkSize_d, chunkNum_h, chunkNum_d);
	upload2constant_topoSortKernel3D(chunkSizeX, chunkSizeX_h, chunkSizeX_d, chunkNum_h, chunkNum_d);
	upload2constant_bitCheckKernel3D(imgSizeX, &bndmat_num, chunk_offset, &maxDim2Compute, chunkNum);
	// Free temporary host memory
	delete[] chunk_offset;
}
template void TopoGPU3D<uchar_>::upload_info_2constant();
template void TopoGPU3D<ushort_>::upload_info_2constant();
template void TopoGPU3D<int>::upload_info_2constant();
template void TopoGPU3D<float>::upload_info_2constant();

// ===== Function Definitions for PH3D_multiThread =====
template<typename type>
PH2D_multiThread<type>::PH2D_multiThread(bool bndMatReduct_, bool write2HDD_) {
	bndMatReduct = bndMatReduct_;
	write2HDD = write2HDD_;
	numCores = std::thread::hardware_concurrency();
}
template PH2D_multiThread<uchar_>::PH2D_multiThread(bool, bool);
template PH2D_multiThread<ushort_>::PH2D_multiThread(bool, bool);
template PH2D_multiThread<int>::PH2D_multiThread(bool, bool);
template PH2D_multiThread<float>::PH2D_multiThread(bool, bool);

template<typename type>
void PH2D_multiThread<type>::findsource2D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y) {
	/*
		Given a cell index `idx` on the 2D doubled grid (size imgSizeX.x กั imgSizeX.y),
		and an offset in {1..8}, move to one of its 8 neighbors, then map to the
		downsampled coordinates via (coord - 1) >> 1.
		Offset encoding (dx, dy) on the full 2D grid:
		  1: ( 0, +1)
		  2: (+1,  0)
		  3: (-1,  0)
		  4: ( 0, -1)
		  5: (+1, +1)
		  6: (-1, +1)
		  7: (+1, -1)
		  8: (-1, -1)
	*/
	switch (offset) {
	case 1: idx = idx + imgSizeX.y;           break; // (0, +1)
	case 2: idx = idx + 1;                    break; // (+1, 0)
	case 3: idx = idx - 1;                    break; // (-1, 0)
	case 4: idx = idx - imgSizeX.y;           break; // (0, -1)
	case 5: idx = idx + imgSizeX.y + 1;       break; // (+1, +1)
	case 6: idx = idx + imgSizeX.y - 1;       break; // (-1, +1)
	case 7: idx = idx - imgSizeX.y + 1;       break; // (+1, -1)
	case 8: idx = idx - imgSizeX.y - 1;       break; // (-1, -1)
	default: break; // leave idx unchanged if offset is out of range
	}

	// Convert linear index back to doubled-grid coordinates
	y = static_cast<uint_>(idx / imgSizeX.y);
	x = static_cast<uint_>(idx % imgSizeX.y);

	// Map from doubled grid (2n+1) back to original grid
	x = (x - 1u) >> 1;
	y = (y - 1u) >> 1;
}

template void PH2D_multiThread<uchar_>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_multiThread<ushort_>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_multiThread<int>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_multiThread<float>::findsource2D_h(ull_, uchar_, uint_&, uint_&);

template<typename type>
void PH2D_multiThread<type>::bndmat_collect(
	const ulonglong2* const		bndmat_h,
	const type* const			vals_h,
	const uchar2* const			offsets_h
)
{
	/*
		Collect boundary relation pairs and corresponding filtration values from device memory
	*/
	if (!bndMatReduct) return;
	// Boundary relation in RAM
	if (!write2HDD) {
		for (uint_ i = 0; i < blockNum; ++i) {
			const ull_	 ind1 = 1ULL * i * bndmat_num;
			ulonglong2	 pair = bndmat_h[ind1];
			uchar2     offset = offsets_h[ind1];

			uint_ j = 0;
			while (pair.x | pair.y) {
				const ull_ ind2 = 2ULL * ind1 + 2ULL * j;

				// pair.x: insert-or-append with one hash lookup
				auto rx = elements.emplace(pair.x, std::pair<Element<type>, std::vector<ull_>>{});
				auto& mx = rx.first->second;
				if (rx.second) {                               // newly created
					mx.first = { vals_h[ind2], offset.x, 0 };
					mx.second.reserve(4);                      // tune initial capacity
				}
				mx.second.push_back(pair.y);

				// pair.y: initialize once (no push_back ever)
				auto ry = elements.emplace(pair.y, std::pair<Element<type>, std::vector<ull_>>{});
				if (ry.second) {
					ry.first->second.first = { vals_h[ind2 + 1], offset.y, 0 };
				}

				if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
				pair = bndmat_h[ind1 + j];
				offset = offsets_h[ind1 + j];
			}
		}
	}
	// Boundary relation in HDD
	else {
		uint64_t file_loc;
		const uint64_t chunkTotal = 1ULL * blockNum * bndmat_num;
		const uint64_t size_bytes_bnd = chunkTotal * sizeof(ulonglong2);
		const uint64_t size_bytes_val = chunkTotal * sizeof(type) * 2;
		const uint64_t size_bytes_off = chunkTotal * sizeof(uchar2);

		// ---- Write bndmat ----
		file_loc = runBase_hddwrite + sizeof(unsigned int) * 5ULL + 1ULL * chunkId * size_bytes_bnd;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(bndmat_h), size_bytes_bnd);
		// ---- Write values ----
		file_loc = offset_vals + 1ULL * chunkId * size_bytes_val;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(vals_h), size_bytes_val);
		// ---- Write offsets ----
		file_loc = offset_offsets + 1ULL * chunkId * size_bytes_off;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(offsets_h), size_bytes_off);
		file.flush();
		chunkId++;
		if (chunkId == chunkNum) file.close();
	}
}
template void PH2D_multiThread<uchar_>::bndmat_collect(const ulonglong2* const bndmat_h, const uchar_* const vals_h, const uchar2* const offsets_h);
template void PH2D_multiThread<ushort_>::bndmat_collect(const ulonglong2* const bndmat_h, const ushort_* const vals_h, const uchar2* const offsets_h);
template void PH2D_multiThread<int>::bndmat_collect(const ulonglong2* const bndmat_h, const int* const vals_h, const uchar2* const offsets_h);
template void PH2D_multiThread<float>::bndmat_collect(const ulonglong2* const bndmat_h, const float* const vals_h, const uchar2* const offsets_h);

template<typename type>
void PH2D_multiThread<type>::sort_crit_by_values() {
	const ull_ critNum = elements.size();
#ifdef ENABLE_THRUST
	std::vector<type>  val_h;
	ind_sorted.reserve(critNum);
	val_h.reserve(critNum);
	for (auto& e : elements) {
		ind_sorted.push_back(e.first);
		val_h.push_back(e.second.first.value);
	}
	thrust::device_vector<ull_> ind_d = ind_sorted;
	thrust::device_vector<type>	val_d = val_h;
	val_h.clear();
	thrust::sort_by_key(val_d.begin(), val_d.end(), ind_d.begin());
	thrust::copy(ind_d.begin(), ind_d.end(), ind_sorted.begin());
#else
	std::vector<std::pair<type, ull_>> tmp;
	tmp.reserve(critNum);
	for (auto& e : elements) tmp.emplace_back(e.second.first.value, e.first);
	std::sort(tmp.begin(), tmp.end(), [](auto& a, auto& b) { return a.first < b.first; });
	for (ull_ i = 0; i < critNum; i++) ind_sorted.push_back(tmp[i].second);
#endif

	// Establish crit index <-> ordering correspondence
	uchar_	actualCores = (numCores > critNum) ? critNum : numCores;
	ull_	rangePerThread = iDivUp(critNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, critNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				critSort_singleThread(startIdx, endIdx);
			});
	}
	tp.stop(true);
}
template void PH2D_multiThread<uchar_>::sort_crit_by_values();
template void PH2D_multiThread<ushort_>::sort_crit_by_values();
template void PH2D_multiThread<int>::sort_crit_by_values();
template void PH2D_multiThread<float>::sort_crit_by_values();

template<typename type>
void PH2D_multiThread<type>::compute_ph() {
	const ull_ critNum = elements.size();
	// Create boundary matrix
	phat::boundary_matrix<phat::bit_tree_pivot_column> boundary_matrix;
	//std::cout << critNum << " columns in boundary matrix" << std::endl;
	boundary_matrix.set_num_cols(critNum);
	// Configure multi-threading parameters
	uchar_ actualCores = (numCores > critNum) ? critNum : numCores;
	ull_   rangePerThread = iDivUp(critNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, critNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				setup_bndmat_SingleThread(boundary_matrix, startIdx, endIdx);
			});
	}
	tp.stop(true);

	// Compute persistence pairs
	phat::persistence_pairs pairs;
	phat::compute_persistence_pairs< phat::twist_reduction >(pairs, boundary_matrix);

	// Gather non-trivial pairs
	gather_nontrivial_pairs(boundary_matrix);
}
template void PH2D_multiThread<uchar_>::compute_ph();
template void PH2D_multiThread<ushort_>::compute_ph();
template void PH2D_multiThread<int>::compute_ph();
template void PH2D_multiThread<float>::compute_ph();

template<typename type>
void PH2D_multiThread<type>::set_minValue(float v) {
	minValue = v;
}
template void PH2D_multiThread<uchar_>::set_minValue(float);
template void PH2D_multiThread<ushort_>::set_minValue(float);
template void PH2D_multiThread<int>::set_minValue(float);
template void PH2D_multiThread<float>::set_minValue(float);

template<typename type>
void PH2D_multiThread<type>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat) {
	const ull_ colNum = bndmat.get_num_cols();
	results.reserve((colNum + 1) * 7);
	// Configure multi-threading parameters
	uchar_	actualCores = (numCores > colNum) ? colNum : numCores;
	ull_	rangePerThread = iDivUp(colNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, (ull_)colNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				gather_nontrivial_pairs_SingleThread(bndmat, startIdx, endIdx);
			});
	}
	tp.stop(true);

	// Insert essential pair
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(minValue));
	results.push_back(static_cast<float>(std::numeric_limits<float>::infinity()));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
}
template void PH2D_multiThread<uchar_>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH2D_multiThread<ushort_>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH2D_multiThread<int>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH2D_multiThread<float>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);

template<typename type>
double PH2D_multiThread<type>::bndmat_reduction() {
	/*
		Boundary matrix reduction on CPU
		return time in milli-seconds
	*/
	if (!bndMatReduct) return (double)0.0;
	auto start = std::chrono::high_resolution_clock::now();

	// Boundary relation in HDD
	if (write2HDD) {
		std::ifstream infile("./bndredbuf.raw", std::ios::binary);
		if (!infile) throw std::runtime_error("Failed to open file for reading");
		infile.read(reinterpret_cast<char*>(&chunkNum), sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&blockNum), sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&bndmat_num), sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&imgSizeX.x), sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&imgSizeX.y), sizeof(unsigned int));

		const uint64_t totalSize = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		elements.reserve(totalSize / 8);
		std::vector<uint2>	bndmat_out(totalSize);
		std::vector<type>	vals_out(totalSize * 2);
		std::vector<uchar2> offsets_out(totalSize);

		infile.read(reinterpret_cast<char*>(bndmat_out.data()), totalSize * sizeof(uint2));
		infile.read(reinterpret_cast<char*>(vals_out.data()), totalSize * sizeof(type) * 2);
		infile.read(reinterpret_cast<char*>(offsets_out.data()), totalSize * sizeof(uchar2));
		infile.close();

		for (uint_ cid = 0; cid < chunkNum; cid++) {
			uint2* bndmat_h = bndmat_out.data() + cid * uint64_t(bndmat_num) * uint64_t(blockNum);
			type* vals_h = vals_out.data() + cid * uint64_t(bndmat_num) * uint64_t(blockNum) * 2;
			uchar2* offsets_h = offsets_out.data() + cid * uint64_t(bndmat_num) * uint64_t(blockNum);

			for (uint_ i = 0; i < blockNum; i++) {
				uint_ j = 0;
				uint2	pair = bndmat_h[i * bndmat_num];
				uchar2	offsetPair = offsets_h[i * bndmat_num];
				while (pair.x | pair.y) {
					auto& ex = elements[pair.x];
					ex.first = { vals_h[2 * i * bndmat_num + 2 * j], offsetPair.x, 0 };
					ex.second.push_back(pair.y);
					elements[pair.y].first = { vals_h[2 * i * bndmat_num + 2 * j + 1], offsetPair.y, 0 };
					if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
					pair = bndmat_h[i * bndmat_num + j];
					offsetPair = offsets_h[i * bndmat_num + j];
				}
			}
		}
	}
	sort_crit_by_values();
	compute_ph();
	auto stop = std::chrono::high_resolution_clock::now();
	return std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0;
}
template double PH2D_multiThread<uchar_>::bndmat_reduction();
template double PH2D_multiThread<ushort_>::bndmat_reduction();
template double PH2D_multiThread<int>::bndmat_reduction();
template double PH2D_multiThread<float>::bndmat_reduction();

template<typename type>
void PH2D_multiThread<type>::print_results(bool details) {
	const uint_ rowNum = results.size() / 7;
	if (details)
		for (uint_ i = 0; i < rowNum; i++)
			std::cout << "Dim: " << (uint_)results[i * 7] << " Birth: " << results[i * 7 + 1] << " Death: " << results[i * 7 + 2] <<
			"  --  " << results[i * 7 + 3] << " " << results[i * 7 + 4] << " " << results[i * 7 + 5] << " "
			<< results[i * 7 + 6] << std::endl;
	printf("Persistence results: %d persistence pair(s)\n", rowNum);
}
template void PH2D_multiThread<uchar_>::print_results(bool details);
template void PH2D_multiThread<ushort_>::print_results(bool details);
template void PH2D_multiThread<int>::print_results(bool details);
template void PH2D_multiThread<float>::print_results(bool details);

template<typename type>
void PH2D_multiThread<type>::write_results(const std::string& out_path) {
	std::ofstream out(out_path, std::ios::out | std::ios::trunc);
	if (!out) { std::cout << "Can't write to file..." << std::endl; return; }

	out << std::setprecision(6);
	const uint_ rowNum = results.size() / 7;
	uint_ idx = 0;
	for (uint_ r = 0; r < rowNum; r++) {
		out << results[idx] << ' ' << results[idx + 1] << ' ' << results[idx + 2] << ' '
			<< results[idx + 3] << ' ' << results[idx + 4] << ' ' << results[idx + 5] << ' '
			<< results[idx + 6] << '\n';
		idx += 7;
	}
	out.close();
}
template void PH2D_multiThread<uchar_>::write_results(const std::string&);
template void PH2D_multiThread<ushort_>::write_results(const std::string&);
template void PH2D_multiThread<int>::write_results(const std::string&);
template void PH2D_multiThread<float>::write_results(const std::string&);

template<typename type>
float* PH2D_multiThread<type>::return_results() {
	return results.data();
}
template float* PH2D_multiThread<uchar_>::return_results();
template float* PH2D_multiThread<ushort_>::return_results();
template float* PH2D_multiThread<int>::return_results();
template float* PH2D_multiThread<float>::return_results();

template<typename type>
uint_ PH2D_multiThread<type>::return_pairNum() {
	return results.size() / 7;
}
template uint_ PH2D_multiThread<uchar_>::return_pairNum();
template uint_ PH2D_multiThread<ushort_>::return_pairNum();
template uint_ PH2D_multiThread<int>::return_pairNum();
template uint_ PH2D_multiThread<float>::return_pairNum();

template<typename type>
PH3D_multiThread<type>::PH3D_multiThread(bool bndMatReduct_, bool write2HDD_) {
	bndMatReduct	= bndMatReduct_;
	write2HDD		= write2HDD_;
	numCores		= std::thread::hardware_concurrency();
}
template PH3D_multiThread<uchar_>::PH3D_multiThread(bool, bool);
template PH3D_multiThread<ushort_>::PH3D_multiThread(bool, bool);
template PH3D_multiThread<int>::PH3D_multiThread(bool, bool);
template PH3D_multiThread<float>::PH3D_multiThread(bool, bool);

template<typename type>
void PH3D_multiThread<type>::findsource3D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y, uint_& z) {
	const uint_ sliceSize = imgSizeX.x * imgSizeX.y;
	switch (offset) {
	case 1: idx = idx + sliceSize; break;
	case 2: idx = idx + 1; break;
	case 3: idx = idx - 1; break;
	case 4: idx = idx - sliceSize; break;
	case 5: idx = idx + imgSizeX.y; break;
	case 6: idx = idx - imgSizeX.y; break;
	case 7: idx = idx + imgSizeX.y + sliceSize; break;
	case 8: idx = idx + sliceSize + 1; break;
	case 9: idx = idx + sliceSize - 1; break;
	case 10: idx = idx - imgSizeX.y + sliceSize; break;
	case 11: idx = idx + imgSizeX.y + 1; break;
	case 12: idx = idx + imgSizeX.y - 1; break;
	case 13: idx = idx - imgSizeX.y + 1; break;
	case 14: idx = idx - imgSizeX.y - 1; break;
	case 15: idx = idx + imgSizeX.y - sliceSize; break;
	case 16: idx = idx - sliceSize + 1; break;
	case 17: idx = idx - sliceSize - 1; break;
	case 18: idx = idx - imgSizeX.y - sliceSize; break;
	case 19: idx = idx + sliceSize + imgSizeX.y + 1; break;
	case 20: idx = idx + sliceSize + imgSizeX.y - 1; break;
	case 21: idx = idx + sliceSize - imgSizeX.y + 1; break;
	case 22: idx = idx + sliceSize - imgSizeX.y - 1; break;
	case 23: idx = idx - sliceSize + imgSizeX.y + 1; break;
	case 24: idx = idx - sliceSize + imgSizeX.y - 1; break;
	case 25: idx = idx - sliceSize - imgSizeX.y + 1; break;
	case 26: idx = idx - sliceSize - imgSizeX.y - 1; break;	
	}
	z = idx / sliceSize;
	y = idx / imgSizeX.y - z * imgSizeX.x;
	x = idx % imgSizeX.y;
	x = (x - 1) >> 1;
	y = (y - 1) >> 1;
	z = (z - 1) >> 1;
}
template void PH3D_multiThread<uchar_>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_multiThread<ushort_>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_multiThread<int>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_multiThread<float>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);

template<typename type>
void PH3D_multiThread<type>::bndmat_collect(
	const ulonglong2*	const bndmat_h,
	const type*			const vals_h,
	const uchar2*		const offsets_h
)
{
	/*
		Collect boundary relation pairs and corresponding filtration values from device memory
	*/
	if (!bndMatReduct) return;
	// Boundary relation in RAM
	if (!write2HDD) {
		for (uint_ i = 0; i < blockNum; ++i) {
			const ull_ ind1 = 1ULL * i * bndmat_num;
			ulonglong2 pair = bndmat_h[ind1];
			uchar2     offset = offsets_h[ind1];

			uint_ j = 0;
			while (pair.x | pair.y) {
				const ull_ ind2 = 2ULL * ind1 + 2ULL * j;

				// pair.x: insert-or-append with one hash lookup
				auto rx = elements.emplace(pair.x, std::pair<Element<type>, std::vector<ull_>>{});
				auto& mx = rx.first->second;
				if (rx.second) {                               // newly created
					mx.first = { vals_h[ind2], offset.x, 0 };
					mx.second.reserve(8);                      // tune initial capacity
				}
				mx.second.push_back(pair.y);

				// pair.y: initialize once (no push_back ever)
				auto ry = elements.emplace(pair.y, std::pair<Element<type>, std::vector<ull_>>{});
				if (ry.second) {
					ry.first->second.first = { vals_h[ind2 + 1], offset.y, 0 };
				}

				if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
				pair = bndmat_h[ind1 + j];
				offset = offsets_h[ind1 + j];
			}
		}
	}
	// Boundary relation in HDD
	else {
		uint64_t file_loc;
		const uint64_t chunkTotal = 1ULL * blockNum * bndmat_num;
		const uint64_t size_bytes_bnd = chunkTotal * sizeof(ulonglong2);
		const uint64_t size_bytes_val = chunkTotal * sizeof(type) * 2;
		const uint64_t size_bytes_off = chunkTotal * sizeof(uchar2);

		// ---- Write bndmat ----
		file_loc = runBase_hddwrite + sizeof(unsigned int) * 6ULL + 1ULL * chunkId * size_bytes_bnd;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(bndmat_h), size_bytes_bnd);
		// ---- Write values ----
		file_loc = offset_vals + 1ULL * chunkId * size_bytes_val;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(vals_h), size_bytes_val);
		// ---- Write offsets ----
		file_loc = offset_offsets + 1ULL * chunkId * size_bytes_off;
		file.seekp(file_loc);
		file.write(reinterpret_cast<const char*>(offsets_h), size_bytes_off);
		file.flush();
		chunkId++;
		if (chunkId == chunkNum) file.close();
	}
}
template void PH3D_multiThread<uchar_>::bndmat_collect	(const ulonglong2* const bndmat_h, const uchar_* const vals_h, const uchar2* const offsets_h);
template void PH3D_multiThread<ushort_>::bndmat_collect	(const ulonglong2* const bndmat_h, const ushort_* const vals_h, const uchar2* const offsets_h);
template void PH3D_multiThread<int>::bndmat_collect		(const ulonglong2* const bndmat_h, const int* const vals_h, const uchar2* const offsets_h);
template void PH3D_multiThread<float>::bndmat_collect		(const ulonglong2* const bndmat_h, const float* const vals_h, const uchar2* const offsets_h);

template<typename type>
void PH3D_multiThread<type>::sort_crit_by_values() {
	const ull_ critNum = elements.size();
#ifdef ENABLE_THRUST
	std::vector<type>  val_h;
	ind_sorted.reserve(critNum);
	val_h.reserve(critNum);
	for (auto& e : elements) {
		ind_sorted.push_back(e.first);
		val_h.push_back(e.second.first.value);
	}
	thrust::device_vector<ull_> ind_d = ind_sorted;
	thrust::device_vector<type>	val_d = val_h;
	val_h.clear();
	thrust::sort_by_key(val_d.begin(), val_d.end(), ind_d.begin());
	thrust::copy(ind_d.begin(), ind_d.end(), ind_sorted.begin());
#else
	std::vector<std::pair<type, ull_>> tmp;
	tmp.reserve(critNum);
	for (auto& e : elements) tmp.emplace_back(e.second.first.value, e.first);
	std::sort(tmp.begin(), tmp.end(), [](auto& a, auto& b) { return a.first < b.first; });
	for (ull_ i = 0; i < critNum; i++) ind_sorted.push_back(tmp[i].second);
#endif

	// Establish crit index <-> ordering correspondence
	uchar_	actualCores		= (numCores > critNum) ? critNum : numCores;
	ull_	rangePerThread	= iDivUp(critNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, critNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				critSort_singleThread(startIdx, endIdx);
			});
	}
	tp.stop(true);
}
template void PH3D_multiThread<uchar_>::sort_crit_by_values();
template void PH3D_multiThread<ushort_>::sort_crit_by_values();
template void PH3D_multiThread<int>::sort_crit_by_values();
template void PH3D_multiThread<float>::sort_crit_by_values();

template<typename type>
void PH3D_multiThread<type>::compute_ph() {
	const ull_ critNum = elements.size();
	// Create boundary matrix
	phat::boundary_matrix<phat::bit_tree_pivot_column> boundary_matrix;
	//std::cout << critNum << " columns in boundary matrix" << std::endl;
	boundary_matrix.set_num_cols(critNum);
	// Configure multi-threading parameters
	uchar_ actualCores		= (numCores > critNum) ? critNum : numCores;
	ull_   rangePerThread	= iDivUp(critNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, critNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				setup_bndmat_SingleThread(boundary_matrix, startIdx, endIdx);
			});
	}
	tp.stop(true);

	// Compute persistence pairs
	phat::persistence_pairs pairs;
	phat::compute_persistence_pairs< phat::twist_reduction >(pairs, boundary_matrix);

	// Gather non-trivial pairs
	gather_nontrivial_pairs(boundary_matrix);
}
template void PH3D_multiThread<uchar_>::compute_ph();
template void PH3D_multiThread<ushort_>::compute_ph();
template void PH3D_multiThread<int>::compute_ph();
template void PH3D_multiThread<float>::compute_ph();

template<typename type>
void PH3D_multiThread<type>::set_minValue(float v) {
	minValue = v;
}
template void PH3D_multiThread<uchar_>::set_minValue(float);
template void PH3D_multiThread<ushort_>::set_minValue(float);
template void PH3D_multiThread<int>::set_minValue(float);
template void PH3D_multiThread<float>::set_minValue(float);

template<typename type>
void PH3D_multiThread<type>::gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat) {
	const ull_ colNum		= bndmat.get_num_cols();
	results.reserve((colNum + 1) * 9);
	// Configure multi-threading parameters
	uchar_	actualCores		= (numCores > colNum) ? colNum : numCores;
	ull_	rangePerThread	= iDivUp(colNum, (ull_)actualCores);
	ctpl::thread_pool tp(actualCores);
	ull_ startIdx, endIdx;
	for (uint_ i = 0; i < actualCores; i++) {
		startIdx = 1ULL * i * rangePerThread;
		endIdx = std::min(1ULL * (i + 1) * rangePerThread, (ull_)colNum);
		tp.push(
			[&, startIdx = startIdx, endIdx = endIdx](const uint_&) -> void {
				gather_nontrivial_pairs_SingleThread(bndmat, startIdx, endIdx);
			});
	}
	tp.stop(true);

	// Insert essential pair
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(minValue));
	results.push_back(static_cast<float>(std::numeric_limits<float>::infinity()));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
	results.push_back(static_cast<float>(0));
}
template void PH3D_multiThread<uchar_>::	gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH3D_multiThread<ushort_>::	gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH3D_multiThread<int>::		gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);
template void PH3D_multiThread<float>::	gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);

template<typename type>
double PH3D_multiThread<type>::bndmat_reduction() {
	/*
		Boundary matrix reduction on CPU
		return time in milli-seconds
	*/
	if (!bndMatReduct) return (double)0.0;
	auto start = std::chrono::high_resolution_clock::now();

	// Boundary relation in HDD
	if (write2HDD) {
		std::ifstream infile("./bndredbuf.raw", std::ios::binary);
		if (!infile) throw std::runtime_error("Failed to open file for reading");
		infile.read(reinterpret_cast<char*>(&chunkNum),		sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&blockNum),		sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&bndmat_num),	sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&imgSizeX.x),	sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&imgSizeX.y),	sizeof(unsigned int));
		infile.read(reinterpret_cast<char*>(&imgSizeX.z),	sizeof(unsigned int));

		const uint64_t totalSize = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		elements.reserve(totalSize / 8);
		std::vector<uint2>	bndmat_out(totalSize);
		std::vector<type>	vals_out(totalSize * 2);
		std::vector<uchar2> offsets_out(totalSize);

		infile.read(reinterpret_cast<char*>(bndmat_out.data()),		totalSize * sizeof(uint2));
		infile.read(reinterpret_cast<char*>(vals_out.data()),		totalSize * sizeof(type) * 2);
		infile.read(reinterpret_cast<char*>(offsets_out.data()),	totalSize * sizeof(uchar2));
		infile.close();

		for (uint_ cid = 0; cid < chunkNum; cid++) {
			uint2*	bndmat_h	= bndmat_out.data()		+ cid * uint64_t(bndmat_num) * uint64_t(blockNum);
			type*	vals_h		= vals_out.data()		+ cid * uint64_t(bndmat_num) * uint64_t(blockNum) * 2;
			uchar2* offsets_h	= offsets_out.data()	+ cid * uint64_t(bndmat_num) * uint64_t(blockNum);

			for (uint_ i = 0; i < blockNum; i++) {
				uint_ j = 0;
				uint2	pair		= bndmat_h[i * bndmat_num];
				uchar2	offsetPair	= offsets_h[i * bndmat_num];
				while (pair.x | pair.y) {
					auto& ex = elements[pair.x];
					ex.first = { vals_h[2 * i * bndmat_num + 2 * j], offsetPair.x, 0 };
					ex.second.push_back(pair.y);
					elements[pair.y].first = { vals_h[2 * i * bndmat_num + 2 * j + 1], offsetPair.y, 0 };
					if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
					pair = bndmat_h[i * bndmat_num + j];
					offsetPair = offsets_h[i * bndmat_num + j];
				}
			}
		}
	}
	sort_crit_by_values();
	compute_ph();
	auto stop = std::chrono::high_resolution_clock::now();
	return std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0;
}
template double PH3D_multiThread<uchar_>::bndmat_reduction();
template double PH3D_multiThread<ushort_>::bndmat_reduction();
template double PH3D_multiThread<int>::bndmat_reduction();
template double PH3D_multiThread<float>::bndmat_reduction();

template<typename type>
void PH3D_multiThread<type>::print_results(bool details) {
	const uint_ rowNum = results.size() / 9;
	if (details)
		for (uint_ i = 0; i < rowNum; i++)
			std::cout << "Dim: " << (uint_)results[i * 9] << " Birth: " << results[i * 9 + 1] << " Death: " << results[i * 9 + 2] <<
			"  --  " << results[i * 9 + 3] << " " << results[i * 9 + 4] << " " << results[i * 9 + 5] << " "
			<< results[i * 9 + 6] << " " << results[i * 9 + 7] << " " << results[i * 9 + 8] << std::endl;
	printf("Persistence results: %d persistence pair(s)\n", rowNum);
}
template void PH3D_multiThread<uchar_>::print_results(bool details);
template void PH3D_multiThread<ushort_>::print_results(bool details);
template void PH3D_multiThread<int>::print_results(bool details);
template void PH3D_multiThread<float>::print_results(bool details);

template<typename type>
void PH3D_multiThread<type>::write_results(const std::string& out_path) {
	std::ofstream out(out_path, std::ios::out | std::ios::trunc);
	if (!out) { std::cout << "Can't write to file..." << std::endl; return; }

	out << std::setprecision(6);
	const uint_ rowNum = results.size() / 9;
	uint_ idx = 0;
	for (uint_ r = 0; r < rowNum; r++) {
		out << results[idx]		<< ' ' << results[idx + 1] << ' ' << results[idx + 2] << ' '
			<< results[idx + 3] << ' ' << results[idx + 4] << ' ' << results[idx + 5] << ' '
			<< results[idx + 6] << ' ' << results[idx + 7] << ' ' << results[idx + 8] << '\n';
		idx += 9;
	}
	out.close();
}
template void PH3D_multiThread<uchar_>::write_results(const std::string&);
template void PH3D_multiThread<ushort_>::write_results(const std::string&);
template void PH3D_multiThread<int>::write_results(const std::string&);
template void PH3D_multiThread<float>::write_results(const std::string&);

template<typename type>
float* PH3D_multiThread<type>::return_results() {
	return results.data();
}
template float* PH3D_multiThread<uchar_>::return_results();
template float* PH3D_multiThread<ushort_>::return_results();
template float* PH3D_multiThread<int>::return_results();
template float* PH3D_multiThread<float>::return_results();

template<typename type>
uint_ PH3D_multiThread<type>::return_pairNum() {
	return results.size() / 9;
}
template uint_ PH3D_multiThread<uchar_>::return_pairNum();
template uint_ PH3D_multiThread<ushort_>::return_pairNum();
template uint_ PH3D_multiThread<int>::return_pairNum();
template uint_ PH3D_multiThread<float>::return_pairNum();