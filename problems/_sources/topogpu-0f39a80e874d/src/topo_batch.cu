#include "fileIO.h"
#include "ctpl_stl.h"
#include "topo_batch.cuh"
#include "morse_matching.cuh"
#include "morse_boundary.cuh"

#ifdef ENABLE_THRUST
/*
	Thrust headers for sorting
*/
#include <thrust/sort.h>
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#endif

template<typename type>
void TopoGPU2D_Batch<type>::proc_size() {
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
			float globalmem_total_GB = globalmem_perstream_GB * strmCnt * halfSize_ * 2;
			printf("Size of global memory per stream: %.3fGB\nTotal used global memory: %.3fGB\n", globalmem_perstream_GB, globalmem_total_GB);
		}
		// Output global memory usage in MB
		else {
			float globalmem_perstream_MB = globalmem_perstream * 1.0f / sqaure1024;
			float globalmem_total_MB = globalmem_perstream_MB * strmCnt * halfSize_ * 2;
			printf("Size of global memory per stream: %.3fMB\nTotal used global memory: %.3fMB\n", globalmem_perstream_MB, globalmem_total_MB);
		}
		printf("======================================================================\n");
	}
}
template void TopoGPU2D_Batch<uchar_>::proc_size();
template void TopoGPU2D_Batch<ushort_>::proc_size();
template void TopoGPU2D_Batch<int>::proc_size();
template void TopoGPU2D_Batch<float>::proc_size();

template<typename type>
void TopoGPU2D_Batch<type>::upload_info_2constant() {
	/*
		This function invokes sub-routines to upload information to constant memory for both kernels
	*/
	// Determine and upload chunk height for each chunk
	if (chunkNum > maxChunkNum_h_) { printf("Warning: chunk number in h direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }

	ull_* chunk_offset = new ull_[chunkNum];
	for (uint_ i = 0; i < chunkNum; i++) {
		chunkSize_h[i] = ((i + 1) * chunkSize.x > imgSize.x) ? imgSize.x - i * chunkSize.x : chunkSize.x;
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
template void TopoGPU2D_Batch<uchar_>::upload_info_2constant();
template void TopoGPU2D_Batch<ushort_>::upload_info_2constant();
template void TopoGPU2D_Batch<int>::upload_info_2constant();
template void TopoGPU2D_Batch<float>::upload_info_2constant();

template<typename type>
void TopoGPU2D_Batch<type>::fetch_chunk2D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream) {
	/*
		Descriptions:
			Fetch chunk data from source data array. The chunk is taken
			as horizontal strip. The chunk has a halo of width 2 above
			and below. The host buffer has to be pinned.
		@src: source input data as array in host.
		@chunkID: ID of the chunk
		@bufID: ID of the buffer
	*/
	uint_ rid_src_frm = (chunkID == 0) ? 0 : chunkID * chunkSize.x - 2;
	uint_ rid_src_to = ((chunkID + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (chunkID + 1) * chunkSize.x + 2;
	uint_ rid_dst_frm = (chunkID == 0) ? 2 : 0;
	const uint_ sliceSize_dst = chunkSize.y + 2;

	// fill chunk_vec_h[bufID] with max value of type
	fill_halo(chunk_vec_h[bufID], rid_dst_frm, rid_dst_frm + (rid_src_to - rid_src_frm));
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

	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(events[2 * bufID + 0], stream));
}
template void TopoGPU2D_Batch<uchar_>::fetch_chunk2D_frmArr(uchar_* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
template void TopoGPU2D_Batch<ushort_>::fetch_chunk2D_frmArr(ushort_* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
template void TopoGPU2D_Batch<int>::fetch_chunk2D_frmArr(int* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
template void TopoGPU2D_Batch<float>::fetch_chunk2D_frmArr(float* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);

template<typename type>
void TopoGPU2D_Batch<type>::fetch_chunk2D_fromImage_multiThread(
	const std::string& path,
	int						datatype,	// 0: 8-bit (jpg/png), 1: 16-bit (png)
	ushort_					chunkID,
	ushort_					bufID,
	const uint_				fileIdx,
	float&					minValue,
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

	// ---- Decode image once and cache it (JPEG/PNG cannot be row-seeked) ----
	if (img_decoded_h[fileIdx] == nullptr || img_decoded_path[fileIdx] != path || img_decoded_dt[fileIdx] != datatype) {
		if (img_decoded_h[fileIdx]) { stbi_image_free(img_decoded_h[fileIdx]); img_decoded_h[fileIdx] = nullptr; }

		int w = 0, h = 0, ch = 0;
		switch (datatype) {
		case 0: // 8-bit: jpg, 8-bit png -> force 1 channel (grayscale)
			img_decoded_h[fileIdx] = stbi_load(path.c_str(), &w, &h, &ch, 1);
			break;
		case 1: // 16-bit: png only (jpg is always 8-bit)
			img_decoded_h[fileIdx] = reinterpret_cast<void*>(stbi_load_16(path.c_str(), &w, &h, &ch, 1));
			break;
		default:
			std::cerr << "fetch_chunk2D_fromImage_multiThread: unsupported datatype!" << std::endl;
			exit(1);
		}
		if (!img_decoded_h[fileIdx]) {
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
		img_decoded_path[fileIdx]	= path;
		img_decoded_dt[fileIdx]		= datatype;
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
	uint_ rowsPerThread = iDivUp(rowsTotal, num_cores);

	// Fill host chunk buffer with max value
	fill_halo(chunk_vec_h[bufID], rid_dst_frm, rid_dst_frm + (rid_src_to - rid_src_frm));
	std::vector<type> localMins(num_cores, std::numeric_limits<type>::max());

	// ---- Launch threads ----
	pool_run(poolRows, num_cores, [&](uint_ i) {
		const uint_ idx = i;
		const uint_ this_src_frm = rid_src_frm + i * rowsPerThread;
		const uint_ this_src_to = std::min(rid_src_frm + (i + 1) * rowsPerThread, rid_src_to);
		const uint_ this_dst_frm = rid_dst_frm + i * rowsPerThread;
		if (this_src_frm >= this_src_to) return;

		type localMin = std::numeric_limits<type>::max();
		switch (datatype) {
		case 0: fetch_chunk2D_fromImage_singleThread<uchar_, type>(static_cast<const uchar_*>(img_decoded_h[fileIdx]), chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		case 1: fetch_chunk2D_fromImage_singleThread<ushort_, type>(static_cast<const ushort_*>(img_decoded_h[fileIdx]), chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		default: break;
		}
		localMins[idx] = localMin;
		});

	for (type localMin : localMins) if (localMin < minValue) minValue = localMin;

	// ---- Copy from chunk_vec_h[bufID] to cuArr_vec[bufID] ----
	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(events[2 * bufID + 0], stream));
}

template<typename type>
void TopoGPU2D_Batch<type>::fetch_chunk2D_fromFile_multiThread(
	const std::string& path,
	int					datatype,
	ushort_				chunkID,
	ushort_				bufID,
	float&				minValue,
	cudaStream_t& stream
)
{
	/*
		Read a chunk of data from disk to host memory with multi-threading (2D).
		Layout and halo convention matches fetch_chunk2D_frmArr.
	*/

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
	uint_ rowsPerThread = iDivUp(rowsTotal, num_cores);

	// Fill host chunk buffer with max value
	fill_halo(chunk_vec_h[bufID], rid_dst_frm, rid_dst_frm + (rid_src_to - rid_src_frm));
	std::vector<type> localMins(num_cores, std::numeric_limits<type>::max());

	// Launch threads
	pool_run(poolRows, num_cores, [&](uint_ i) {
		const uint_ idx = i;
		const uint_ this_src_frm = rid_src_frm + i * rowsPerThread;
		const uint_ this_src_to = std::min(rid_src_frm + (i + 1) * rowsPerThread, rid_src_to);
		const uint_ this_dst_frm = rid_dst_frm + i * rowsPerThread;
		if (this_src_frm >= this_src_to) return;

		type localMin = std::numeric_limits<type>::max();
		switch (datatype) {
		case 0: fetch_chunk2D_fromFile_singleThread<uchar_, type>(path, chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		case 1: fetch_chunk2D_fromFile_singleThread<ushort_, type>(path, chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		case 2: fetch_chunk2D_fromFile_singleThread<int, type>(path, chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		case 3: fetch_chunk2D_fromFile_singleThread<float, type>(path, chunk_vec_h[bufID], localMin, this_src_frm, this_src_to, this_dst_frm, rowSize_src, rowSize_dst); break;
		default: break;
		}
		localMins[idx] = localMin;
		});

	for (type localMin : localMins) if (localMin < minValue) minValue = localMin;

	// Copy from chunk_vec_h[bufID] to cuArr_vec[bufID]
	ull_ srcPitch = (chunkSize.y + 2) * sizeof(type);
	checkCudaErrors(cudaMemcpy2DToArrayAsync(
		cuArr_vec[bufID],
		0, 0,
		&chunk_vec_h[bufID][0],
		srcPitch,
		srcPitch,
		(chunkSize.x + 4),
		cudaMemcpyHostToDevice,
		stream));
	checkCudaErrors(cudaEventRecord(events[2 * bufID + 0], stream));
}

template<typename type>
void TopoGPU2D_Batch<type>::run_frmArr(type* src, PH2D_Batch_multiThread<type>& ph, ushort_ fileNum) {
	/*
		Descriptions: compute persistent homology chunk by chunk
		@src: the input source array
	*/

	if (fileNum > halfSize_) { printf("Error: fileNum (%u) > halfSize (%u)\n", (uint_)fileNum, (uint_)halfSize_); return; }
	const ull_ imgElems = 1ULL * imgSize.x * imgSize.y;
	std::vector<float> minVals(fileNum, std::numeric_limits<float>::max());

	ph.initialize(blockNum, bndmat_num, chunkNum, fileNum, imgSizeX);

	// Helper: harvest results of the previous use of slot s for file f
	auto collect = [&](uint_ f, uint_ s) {
		checkCudaErrors(cudaEventSynchronize(events[2 * s + 1]));
		ph.bndmat_collect(bndmat_vec_h[s], vals_vec_h[s], offsets_vec_h[s], f);
		};

	ushort_ chunkID = 0;
	for (; chunkID < chunkNum; chunkID++) {
		const ushort_ bufID = chunkID % strmCnt;
		const uint2 chunkSize_chunk = make_uint2(chunkSize_h[chunkID], chunkSize.y);
		const uint2 chunkSizeX_chunk = make_uint2(chunkSizeX_h[chunkID], chunkSizeX.y);

		// ---- Fetch this chunk of every file (H2D copies overlap across streams) ----
		pool_run(poolFiles, fileNum, [&](uint_ f) {
			const uint_ s = slot(f, bufID);
			if (chunkID >= strmCnt) checkCudaErrors(cudaEventSynchronize(events[2 * s + 0]));
			fetch_chunk2D_frmArr(src + f * imgElems, chunkID, (ushort_)s, minVals[f], streams[s]);
			});

		// ---- Harvest previous round of these slots (CPU work, parallel over files) ----
		if (chunkID >= strmCnt) pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });

		// ---- Launch GPU pipeline for every file ----
		for (ushort_ f = 0; f < fileNum; f++) {
			const uint_ s = slot(f, bufID);
			cudaStream_t& st = streams[s];
			procLowerStars_tile2D<type>(texObj_vec[s], chunkID, match_vec_d[s], crit_vec_d[s], chunkSize_chunk, blockSize, blockSizeX, st);
			topoSort_2D(chunkID, match_vec_d[s], crit_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			pathCount_2D(chunkID, match_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			bitCheck_2D<type>(texObj_vec[s], chunkID, crit_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], bndmat_vec_d[s], vals_vec_d[s], offsets_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);

			checkCudaErrors(cudaMemsetAsync(crit_vec_d[s], 0, PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(uchar_), st));
			if (ph.ifbndMatReduct()) {
				checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[s], bndmat_vec_d[s], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(vals_vec_h[s], vals_vec_d[s], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[s], offsets_vec_d[s], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, st));
			}
			checkCudaErrors(cudaEventRecord(events[2 * s + 1], st));	// results in host memory after this
			checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[s], 0, blockNum * bndmat_num * sizeof(ulonglong2), st));
			checkCudaErrors(cudaMemsetAsync(vals_vec_d[s], 0, 2 * blockNum * bndmat_num * sizeof(type), st));
			checkCudaErrors(cudaMemsetAsync(offsets_vec_d[s], 0, blockNum * bndmat_num * sizeof(uchar2), st));
		}
	}

	// ---- Drain: harvest the last strmCnt rounds ----
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
		const ushort_ bufID = chunkID % strmCnt;
		pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });
	}
	for (ushort_ f = 0; f < fileNum; f++) ph.set_minValue(minVals[f], f);
}
template void TopoGPU2D_Batch<uchar_>::	run_frmArr(uchar_* src,		PH2D_Batch_multiThread<uchar_>& ph,		ushort_ fileNum);
template void TopoGPU2D_Batch<ushort_>::run_frmArr(ushort_* src,	PH2D_Batch_multiThread<ushort_>& ph,	ushort_ fileNum);
template void TopoGPU2D_Batch<int>::	run_frmArr(int* src,	PH2D_Batch_multiThread<int>& ph,			ushort_ fileNum);
template void TopoGPU2D_Batch<float>::	run_frmArr(float* src,	PH2D_Batch_multiThread<float>& ph,			ushort_ fileNum);

template<typename type>
void TopoGPU2D_Batch<type>::run_frmFile(
	const std::vector<std::string>&		filenames,
	const std::string&					datatype_,
	PH2D_Batch_multiThread<type>&		ph,
	ushort_								fileNum
) {
	/*
		Process `fileNum` same-sized files (binary or jpg/png), chunk by chunk, all files in parallel.
		Slot s = file * strmCnt + bufID (see run_frmArr).
	*/
	if (fileNum > halfSize_ || fileNum > filenames.size()) { printf("Error: fileNum (%u) > halfSize (%u) or > filenames.size() (%zu)\n", (uint_)fileNum, (uint_)halfSize_, filenames.size()); return; }
	const int datatype = parse_input_type(datatype_);
	std::vector<float> minVals(fileNum, std::numeric_limits<float>::max());

	auto isImage = [](const std::string& fn) {
		const size_t dot = fn.find_last_of('.');
		if (dot == std::string::npos) return false;
		std::string ext = fn.substr(dot);
		std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return (char)std::tolower(c); });
		return ext == ".jpg" || ext == ".jpeg" || ext == ".png";
		};
	auto collect = [&](uint_ f, uint_ s) {
		checkCudaErrors(cudaEventSynchronize(events[2 * s + 1]));
		ph.bndmat_collect(bndmat_vec_h[s], vals_vec_h[s], offsets_vec_h[s], f);
		};

	ph.initialize(blockNum, bndmat_num, chunkNum, fileNum, imgSizeX);

	ushort_ chunkID = 0;
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		const ushort_ bufID = chunkID % strmCnt;
		const uint2 chunkSize_chunk = make_uint2(chunkSize_h[chunkID], chunkSize.y);
		const uint2 chunkSizeX_chunk = make_uint2(chunkSizeX_h[chunkID], chunkSizeX.y);

		// ---- Fetch this chunk of every file (parallel over files; row-parallel inside on poolRows) ----
		pool_run(poolFiles, fileNum, [&](uint_ f) {
			const uint_ s = slot(f, bufID);
			if (chunkID >= strmCnt) checkCudaErrors(cudaEventSynchronize(events[2 * s + 0]));
			if (isImage(filenames[f]))
				fetch_chunk2D_fromImage_multiThread(filenames[f], datatype, chunkID, (ushort_)s, f, minVals[f], streams[s]);
			else
				fetch_chunk2D_fromFile_multiThread(filenames[f], datatype, chunkID, (ushort_)s, minVals[f], streams[s]);
			});

		// ---- Harvest previous round of these slots ----
		if (chunkID >= strmCnt)
			pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });

		// ---- Launch GPU pipeline for every file ----
		for (ushort_ f = 0; f < fileNum; f++) {
			const uint_ s = slot(f, bufID);
			cudaStream_t& st = streams[s];
			procLowerStars_tile2D<type>(texObj_vec[s], chunkID, match_vec_d[s], crit_vec_d[s], chunkSize_chunk, blockSize, blockSizeX, st);
			topoSort_2D(chunkID, match_vec_d[s], crit_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			pathCount_2D(chunkID, match_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			bitCheck_2D<type>(texObj_vec[s], chunkID, crit_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], bndmat_vec_d[s], vals_vec_d[s], offsets_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);

			checkCudaErrors(cudaMemsetAsync(crit_vec_d[s], 0, PRODUCT2(chunkSizeX.x, chunkSizeX.y) * sizeof(uchar_), st));
			if (ph.ifbndMatReduct()) {
				checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[s], bndmat_vec_d[s], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(vals_vec_h[s], vals_vec_d[s], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[s], offsets_vec_d[s], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, st));
			}
			checkCudaErrors(cudaEventRecord(events[2 * s + 1], st));
			checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[s], 0, blockNum * bndmat_num * sizeof(ulonglong2), st));
			checkCudaErrors(cudaMemsetAsync(vals_vec_d[s], 0, 2 * blockNum * bndmat_num * sizeof(type), st));
			checkCudaErrors(cudaMemsetAsync(offsets_vec_d[s], 0, blockNum * bndmat_num * sizeof(uchar2), st));
		}
	}

	// ---- Drain ----
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
		const ushort_ bufID = chunkID % strmCnt;
		pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });
	}
	for (ushort_ f = 0; f < fileNum; f++) ph.set_minValue(minVals[f], f);
}
template void TopoGPU2D_Batch<uchar_>::run_frmFile(const std::vector<std::string>&, const std::string&, PH2D_Batch_multiThread<uchar_>&, ushort_);
template void TopoGPU2D_Batch<ushort_>::run_frmFile(const std::vector<std::string>&, const std::string&, PH2D_Batch_multiThread<ushort_>&, ushort_);
template void TopoGPU2D_Batch<int>::run_frmFile(const std::vector<std::string>&, const std::string&, PH2D_Batch_multiThread<int>&, ushort_);
template void TopoGPU2D_Batch<float>::run_frmFile(const std::vector<std::string>&, const std::string&, PH2D_Batch_multiThread<float>&, ushort_);


template<typename type>
void TopoGPU2D_Batch<type>::fill_halo(type* buf, uint_ rowFrom, uint_ rowTo) const {
	const type  mx = std::numeric_limits<type>::max();
	const uint_ rows = chunkSize.x + 4;
	const uint_ cols = chunkSize.y + 2;
	// rows above the data
	std::fill_n(buf, (size_t)rowFrom * cols, mx);
	// rows below the data
	std::fill_n(buf + (size_t)rowTo * cols, (size_t)(rows - rowTo) * cols, mx);
	// left/right apron on data rows
	for (uint_ r = rowFrom; r < rowTo; ++r) {
		buf[(size_t)r * cols] = mx;
		buf[(size_t)r * cols + cols - 1] = mx;
	}
}

template<typename type>
void PH2D_Batch_multiThread<type>::findsource2D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y) {
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

template void PH2D_Batch_multiThread<uchar_>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_Batch_multiThread<ushort_>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_Batch_multiThread<int>::findsource2D_h(ull_, uchar_, uint_&, uint_&);
template void PH2D_Batch_multiThread<float>::findsource2D_h(ull_, uchar_, uint_&, uint_&);

template<typename type>
void PH2D_Batch_multiThread<type>::bndmat_collect(
	const ulonglong2* const		bndmat_h,
	const type* const			vals_h,
	const uchar2* const			offsets_h,
	const uint_					fileIdx
)
{
	/*
		Collect boundary relation pairs and corresponding filtration values from device memory
	*/
	if (!bndMatReduct) return;

	for (uint_ i = 0; i < blockNum; ++i) {
		const ull_	 ind1 = 1ULL * i * bndmat_num;
		ulonglong2	 pair = bndmat_h[ind1];
		uchar2     offset = offsets_h[ind1];

		uint_ j = 0;
		while (pair.x | pair.y) {
			const ull_ ind2 = 2ULL * ind1 + 2ULL * j;

			// pair.x: insert-or-append with one hash lookup
			auto rx = elements[fileIdx].emplace(pair.x, std::pair<Element<type>, std::vector<ull_>>{});
			auto& mx = rx.first->second;
			if (rx.second) {                               // newly created
				mx.first = { vals_h[ind2], offset.x, 0 };
				mx.second.reserve(4);                      // tune initial capacity
			}
			mx.second.push_back(pair.y);

			// pair.y: initialize once (no push_back ever)
			auto ry = elements[fileIdx].emplace(pair.y, std::pair<Element<type>, std::vector<ull_>>{});
			if (ry.second) {
				ry.first->second.first = { vals_h[ind2 + 1], offset.y, 0 };
			}

			if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
			pair = bndmat_h[ind1 + j];
			offset = offsets_h[ind1 + j];
		}
	}
}
template void PH2D_Batch_multiThread<uchar_>::bndmat_collect(const ulonglong2* const bndmat_h, const uchar_* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);
template void PH2D_Batch_multiThread<ushort_>::bndmat_collect(const ulonglong2* const bndmat_h, const ushort_* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);
template void PH2D_Batch_multiThread<int>::bndmat_collect(const ulonglong2* const bndmat_h, const int* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);
template void PH2D_Batch_multiThread<float>::bndmat_collect(const ulonglong2* const bndmat_h, const float* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);

template<typename type>
void PH2D_Batch_multiThread<type>::bndmat_reduction() {
	/*
		Boundary matrix reduction on CPU
		return time in milli-seconds
	*/
	if (!bndMatReduct) return;
	sort_crit_by_values();
	compute_ph();
}
template void PH2D_Batch_multiThread<uchar_>::bndmat_reduction();
template void PH2D_Batch_multiThread<ushort_>::bndmat_reduction();
template void PH2D_Batch_multiThread<int>::bndmat_reduction();
template void PH2D_Batch_multiThread<float>::bndmat_reduction();

template<typename type>
void PH2D_Batch_multiThread<type>::sort_crit_by_values() {
	pool_run(poolFiles, fileNum, [&](uint_ f) { sort_crit_by_values_singleThread(f); });
}
template void PH2D_Batch_multiThread<uchar_>::sort_crit_by_values();
template void PH2D_Batch_multiThread<ushort_>::sort_crit_by_values();
template void PH2D_Batch_multiThread<int>::sort_crit_by_values();
template void PH2D_Batch_multiThread<float>::sort_crit_by_values();

template<typename type>
void PH2D_Batch_multiThread<type>::sort_crit_by_values_singleThread(const uint_ f) {
	auto& elem				= elements[f];
	auto& ind				= ind_sorted[f];
	const ull_ critNum		= elem.size();
	if (critNum == 0) { ind = nullptr; return; }
	ind = malloc1D_pin_<ull_>(critNum);

#ifdef ENABLE_THRUST
	uint_ cnt = 0;
	type* val_h = malloc1D_pin_<type>(critNum);
	for (auto& e : elem) { ind[cnt] = e.first; val_h[cnt++] = e.second.first.value; }

	cudaStream_t stream;
	checkCudaErrors(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking));
	ull_* ind_d = nullptr; type* val_d = nullptr;
	checkCudaErrors(cudaMallocAsync(&ind_d, critNum * sizeof(ull_), stream));   // stream-ordered: no device-wide sync
	checkCudaErrors(cudaMallocAsync(&val_d, critNum * sizeof(type), stream));
	checkCudaErrors(cudaMemcpyAsync(ind_d, ind, critNum * sizeof(ull_), cudaMemcpyHostToDevice, stream));
	checkCudaErrors(cudaMemcpyAsync(val_d, val_h, critNum * sizeof(type), cudaMemcpyHostToDevice, stream));

	thrust::sort_by_key(thrust::cuda::par_nosync.on(stream),
		thrust::device_pointer_cast(val_d), thrust::device_pointer_cast(val_d) + critNum,
		thrust::device_pointer_cast(ind_d));

	checkCudaErrors(cudaMemcpyAsync(ind, ind_d, critNum * sizeof(ull_), cudaMemcpyDeviceToHost, stream));
	checkCudaErrors(cudaFreeAsync(ind_d, stream));
	checkCudaErrors(cudaFreeAsync(val_d, stream));
	checkCudaErrors(cudaStreamSynchronize(stream));
	checkCudaErrors(cudaStreamDestroy(stream));
	cudaFreeHost(val_h);
#else
	std::vector<std::pair<type, ull_>> tmp;
	tmp.reserve(critNum);
	for (auto& e : elem) tmp.emplace_back(e.second.first.value, e.first);
	std::sort(tmp.begin(), tmp.end(), [](auto& a, auto& b) { return a.first < b.first; });
	for (ull_ i = 0; i < critNum; ++i) ind[i] = tmp[i].second;
#endif 
	for (ull_ i = 0; i < critNum; ++i) elem[ind[i]].first.order = i;
}

template<typename type>
void PH2D_Batch_multiThread<type>::compute_ph() {
	const uint_ outer = std::max<uint_>(1u, std::min<uint_>(fileNum, numCores));
	const uint_ inner = std::max<uint_>(1u, numCores / outer);        // threads each file may use
	pool_run(poolFiles, fileNum, [&](uint_ f) { compute_ph_singleFile(f, inner); });
}
template void PH2D_Batch_multiThread<uchar_>::compute_ph();
template void PH2D_Batch_multiThread<ushort_>::compute_ph();
template void PH2D_Batch_multiThread<int>::compute_ph();
template void PH2D_Batch_multiThread<float>::compute_ph();

template<typename type>
void PH2D_Batch_multiThread<type>::compute_ph_singleFile(const uint_ f, const uint_ threadBudget) {
	const ull_ critNum = elements[f].size();
	if (critNum == 0) return;

	phat::boundary_matrix<phat::bit_tree_pivot_column> boundary_matrix;
	boundary_matrix.set_num_cols(critNum);

	// ---- Setup boundary matrix (inner pool) ----
	const uint_ cores = (uint_)std::min<ull_>(threadBudget, critNum);
	const ull_  range = iDivUp(critNum, (ull_)cores);
	pool_run(poolRange, cores, [&](uint_ i) {
		const ull_ s = 1ULL * i * range, e = std::min<ull_>(s + range, critNum);
		setup_bndmat_SingleThread(boundary_matrix, s, e, f);
		});

	// ---- Reduction (PHAT is single-threaded) ----
	phat::persistence_pairs pairs;
	phat::compute_persistence_pairs<phat::twist_reduction>(pairs, boundary_matrix);

	// ---- Gather non-trivial pairs (inner pool; mutex in _SingleThread protects results[f]) ----
	{
		const ull_  colNum = boundary_matrix.get_num_cols();
		const uint_ cores = (uint_)std::min<ull_>(threadBudget, colNum);
		const ull_  range = iDivUp(colNum, (ull_)cores);
		results[f].reserve((colNum + 1) * 7);
		pool_run(poolRange, cores, [&](uint_ i) {
			const ull_ s = 1ULL * i * range, e = std::min<ull_>(s + range, colNum);
			gather_nontrivial_pairs_SingleThread(boundary_matrix, s, e, f);
			});
	}

	// ---- Essential pair ----
	auto& res = results[f];
	res.push_back(0.f);
	res.push_back(static_cast<float>(minValue[f]));
	res.push_back(std::numeric_limits<float>::infinity());
	res.push_back(0.f); res.push_back(0.f); res.push_back(0.f); res.push_back(0.f);
}

template<typename type>
void PH2D_Batch_multiThread<type>::set_minValue(float v, const uint_ fileIdx) {
	minValue[fileIdx] = v;
}
template void PH2D_Batch_multiThread<uchar_>::set_minValue(float, const uint_);
template void PH2D_Batch_multiThread<ushort_>::set_minValue(float, const uint_);
template void PH2D_Batch_multiThread<int>::set_minValue(float, const uint_);
template void PH2D_Batch_multiThread<float>::set_minValue(float, const uint_);

template<typename type>
void PH2D_Batch_multiThread<type>::print_results() {
	for (uint_ f = 0; f < fileNum; f++) {
		const uint_ rowNum = results[f].size() / 7;
		printf("Persistence results: %d persistence pair(s)\n", rowNum);
	}
}
template void PH2D_Batch_multiThread<uchar_>::print_results();
template void PH2D_Batch_multiThread<ushort_>::print_results();
template void PH2D_Batch_multiThread<int>::print_results();
template void PH2D_Batch_multiThread<float>::print_results();

template<typename type>
void PH2D_Batch_multiThread<type>::write_results(const std::string& out_path, const uint_ fileIdx) {
	std::ofstream out(out_path, std::ios::out | std::ios::trunc);
	if (!out) { std::cout << "Can't write to file..." << std::endl; return; }

	out << std::setprecision(6);
	const uint_ rowNum = results[fileIdx].size() / 7;
	uint_ idx = 0;
	for (uint_ r = 0; r < rowNum; r++) {
		out << results[fileIdx][idx] << ' ' << results[fileIdx][idx + 1] << ' ' << results[fileIdx][idx + 2] << ' '
			<< results[fileIdx][idx + 3] << ' ' << results[fileIdx][idx + 4] << ' ' << results[fileIdx][idx + 5] << ' '
			<< results[fileIdx][idx + 6] << '\n';
		idx += 7;
	}
	out.close();
}
template void PH2D_Batch_multiThread<uchar_>::write_results(const std::string&, const uint_);
template void PH2D_Batch_multiThread<ushort_>::write_results(const std::string&, const uint_);
template void PH2D_Batch_multiThread<int>::write_results(const std::string&, const uint_);
template void PH2D_Batch_multiThread<float>::write_results(const std::string&, const uint_);

template<typename type>
float* PH2D_Batch_multiThread<type>::return_results(const uint_ fileIdx) {
	return results[fileIdx].data();
}
template float* PH2D_Batch_multiThread<uchar_>::return_results(const uint_);
template float* PH2D_Batch_multiThread<ushort_>::return_results(const uint_);
template float* PH2D_Batch_multiThread<int>::return_results(const uint_);
template float* PH2D_Batch_multiThread<float>::return_results(const uint_);

template<typename type>
uint_ PH2D_Batch_multiThread<type>::return_pairNum(const uint_ fileIdx) {
	return results[fileIdx].size() / 7;
}
template uint_ PH2D_Batch_multiThread<uchar_>::return_pairNum(const uint_);
template uint_ PH2D_Batch_multiThread<ushort_>::return_pairNum(const uint_);
template uint_ PH2D_Batch_multiThread<int>::return_pairNum(const uint_);
template uint_ PH2D_Batch_multiThread<float>::return_pairNum(const uint_);

template<typename type>
void TopoGPU3D_Batch<type>::proc_size() {
	// Decide chunk number in h and d direction
	chunkNum_h		= iDivUp(imgSize.x, chunkSize.x);
	chunkNum_d		= iDivUp(imgSize.z, chunkSize.z);
	chunkNum		= chunkNum_h * chunkNum_d;
	if (chunkNum > 65536) { printf("Error: Total number of chunks exceed 65536.\n"); exit(1); }
	// Assign block and chunk size in matching grid
	blockSizeX.x	= 2 * blockSize.x + 1;
	blockSizeX.y	= 2 * blockSize.y + 1;
	blockSizeX.z	= 2 * blockSize.z + 1;
	chunkSizeX.x	= 2 * chunkSize.x + 1;
	chunkSizeX.y	= 2 * chunkSize.y + 1;
	chunkSizeX.z	= 2 * chunkSize.z + 1;
	imgSizeX.x		= 2 * imgSize.x + 1;
	imgSizeX.y		= 2 * imgSize.y + 1;
	imgSizeX.z		= 2 * imgSize.z + 1;
	// Determine the number of CUDA streams
	strmCnt			= (chunkNum <= 3) ? chunkNum : 3;
	// Decide number of blocks per chunk in matching grid
	blockNum		= iDivUp(chunkSizeX.x - 1, blockSizeX.x - 1) * iDivUp(chunkSizeX.y - 1, blockSizeX.y - 1) * iDivUp(chunkSizeX.z - 1, blockSizeX.z - 1);

	if (verbose) {
		printf("Chunk size: %d %d %d\nBlock size: %d %d %d\n", chunkSize.x, chunkSize.y, chunkSize.z, blockSize.x, blockSize.y, blockSize.z);
		printf("Number of streams: %d\nNumber of blocks per chunk: %d\nTotal number of chunks: %d\n", strmCnt, blockNum, chunkNum);
		if ((imgSize.x - (chunkNum_h - 1) * chunkSize.x) % blockSize.x == 1) printf("Last block has height = 1\n");
		if ((imgSize.z - (chunkNum_d - 1) * chunkSize.z) % blockSize.z == 1) printf("Last block has depth = 1\n");
		if (imgSize.y % blockSize.y == 1) printf("Last block has width = 1\n");
	}
	if (verbose) {
		uint_ sqaure1024				= 1024 * 1024;
		uint_ cubic1024					= 1024 * 1024 * 1024;
		uint_ globalmem_tex				= PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4) * sizeof(type);
		uint_ globalmem_grid			= PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(ushort_);
		uint_ globalmem_crit			= PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(uchar_);
		uint_ globalmem_morsbound		= PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * blockNum * 4 * sizeof(ushort_);
		uint_ globalmem_pathcount		= PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * blockNum * PATHCNT_BUF_SIZE * sizeof(uint_);
		uint_ globalmem_chunkcritnum	= blockNum * sizeof(ushort_);
		uint_ globalmem_bndmat			= blockNum * bndmat_num * sizeof(ulonglong2);
		uint_ globalmem_vals			= 2 * blockNum * bndmat_num * sizeof(type);
		uint_ globalmem_offsets			= blockNum * bndmat_num * sizeof(uchar2);
		uint_ globalmem_perstream		= globalmem_tex + globalmem_grid + globalmem_crit + globalmem_morsbound + globalmem_pathcount + globalmem_chunkcritnum + globalmem_bndmat + globalmem_vals + globalmem_offsets;
		if (globalmem_perstream >= cubic1024) {
			float globalmem_perstream_GB = globalmem_perstream * 1.0f / cubic1024;
			float globalmem_total_GB = globalmem_perstream_GB * strmCnt * halfSize_ * 2;
			printf("Size of global memory per stream: %.3fGB\nTotal used global memory: %.3fGB\n", globalmem_perstream_GB, globalmem_total_GB);
		}
		else {
			float globalmem_perstream_MB = globalmem_perstream * 1.0f / sqaure1024;
			float globalmem_total_MB = globalmem_perstream_MB * strmCnt * halfSize_ * 2;
			printf("Size of global memory per stream: %.3fMB\nTotal used global memory: %.3fMB\n", globalmem_perstream_MB, globalmem_total_MB);
		}
		printf("======================================================================\n");
	}
}
template void TopoGPU3D_Batch<uchar_>::proc_size();
template void TopoGPU3D_Batch<ushort_>::proc_size();
template void TopoGPU3D_Batch<int>::proc_size();
template void TopoGPU3D_Batch<float>::proc_size();

template<typename type>
void TopoGPU3D_Batch<type>::upload_info_2constant() {
	if (chunkNum_h > maxChunkNum_h_) { printf("Warning: chunk number in h direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }
	if (chunkNum_d > maxChunkNum_d_) { printf("Warning: chunk number in d direction exceeds the max allowed chunk number, increase chunk size\n"); exit(1); }
	ull_* chunk_offset = new ull_[chunkNum];
	// Determine chunk height
	for (size_t i = 0; i < chunkNum_h; i++) {
		chunkSize_h[i] = ((i + 1) * chunkSize.x > imgSize.x) ? imgSize.x - i * chunkSize.x : chunkSize.x;
		chunkSizeX_h[i] = 2 * chunkSize_h[i] + 1;
	}
	// Determine chunk depth
	for (size_t i = 0; i < chunkNum_d; i++) {
		chunkSize_d[i] = ((i + 1) * chunkSize.z > imgSize.z) ? imgSize.z - i * chunkSize.z : chunkSize.z;
		chunkSizeX_d[i] = 2 * chunkSize_d[i] + 1;
	}
	// Determine chunk offset, chunks are organized from top to bottom and then from front to back
	for (size_t i = 0; i < chunkNum; i++) {
		uint_ hid = i % chunkNum_h;
		uint_ did = i / chunkNum_h;
		chunk_offset[i] = 1ULL * did * (2 * imgSize.x + 1) * chunkSizeX.y * (chunkSizeX.z - 1) + 1ULL * hid * (chunkSizeX.x - 1) * chunkSizeX.y;
	}
	// Upload to constant memory in device
	upload2constant_matchingKernel3D(&imgSize.y, chunkSize_h, chunkSize_d, chunkNum_h, chunkNum_d);
	upload2constant_topoSortKernel3D(chunkSizeX, chunkSizeX_h, chunkSizeX_d, chunkNum_h, chunkNum_d);
	upload2constant_bitCheckKernel3D(imgSizeX, &bndmat_num, chunk_offset, &maxDim2Compute, chunkNum);
	delete[] chunk_offset;
}
template void TopoGPU3D_Batch<uchar_>::upload_info_2constant();
template void TopoGPU3D_Batch<ushort_>::upload_info_2constant();
template void TopoGPU3D_Batch<int>::upload_info_2constant();
template void TopoGPU3D_Batch<float>::upload_info_2constant();

template<typename type>
void TopoGPU3D_Batch<type>::fill_halo(type* buf, uint_ sliceFrom, uint_ sliceTo, uint_ rowFrom, uint_ rowTo) const {
	/*
		Buffer layout: [depth = chunkSize.z + 4][height = chunkSize.x + 4][width = chunkSize.y + 2].
		Data is written to slices [sliceFrom, sliceTo), rows [rowFrom, rowTo), cols [1, chunkSize.y].
		Everything else is set to max.
	*/
	const type  mx			= std::numeric_limits<type>::max();
	const uint_ slices		= chunkSize.z + 4;
	const uint_ rows		= chunkSize.x + 4;
	const uint_ cols		= chunkSize.y + 2;
	const size_t sliceSize	= (size_t)rows * cols;
	// slices before / after the data
	std::fill_n(buf, (size_t)sliceFrom * sliceSize, mx);
	std::fill_n(buf + (size_t)sliceTo * sliceSize, (size_t)(slices - sliceTo) * sliceSize, mx);
	// inside data slices
	for (uint_ s = sliceFrom; s < sliceTo; ++s) {
		type* sl = buf + (size_t)s * sliceSize;
		std::fill_n(sl, (size_t)rowFrom * cols, mx);                                  // rows above
		std::fill_n(sl + (size_t)rowTo * cols, (size_t)(rows - rowTo) * cols, mx);    // rows below
		for (uint_ r = rowFrom; r < rowTo; ++r) {                                     // left/right apron
			sl[(size_t)r * cols] = mx;
			sl[(size_t)r * cols + cols - 1] = mx;
		}
	}
}

template<typename type>
void TopoGPU3D_Batch<type>::fetch_chunk3D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream) {
	/*
		Fetch chunk data from a source array (one volume). Halo of 2 above/below in h and d, 1 left/right in w.
	*/
	const uint_ hid				= chunkID % chunkNum_h;
	const uint_ did				= chunkID / chunkNum_h;
	const uint_ hid_src_frm		= (hid == 0) ? 0 : hid * chunkSize.x - 2;
	const uint_ did_src_frm		= (did == 0) ? 0 : did * chunkSize.z - 2;
	const uint_ hid_src_to		= ((hid + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (hid + 1) * chunkSize.x + 2;
	const uint_ did_src_to		= ((did + 1) * chunkSize.z + 2 > imgSize.z) ? imgSize.z : (did + 1) * chunkSize.z + 2;
	const uint_ hid_dst_frm		= (hid == 0) ? 2 : 0;
	const uint_ did_dst_frm		= (did == 0) ? 2 : 0;
	const size_t sliceSize_src	= (size_t)imgSize.x * imgSize.y;
	const size_t sliceSize_dst	= (size_t)(chunkSize.x + 4) * (chunkSize.y + 2);

	fill_halo(chunk_vec_h[bufID],
		did_dst_frm, did_dst_frm + (did_src_to - did_src_frm),
		hid_dst_frm, hid_dst_frm + (hid_src_to - hid_src_frm));

	type localMin = std::numeric_limits<type>::max();
	for (uint_ did_iter = did_src_frm; did_iter < did_src_to; did_iter++) {
		size_t off_src = did_iter * sliceSize_src + (size_t)hid_src_frm * imgSize.y;
		size_t off_dst = (did_iter - did_src_frm + did_dst_frm) * sliceSize_dst + (size_t)hid_dst_frm * (chunkSize.y + 2) + 1;
		for (uint_ hid_iter = hid_src_frm; hid_iter < hid_src_to; hid_iter++) {
			const type* src_row = src + off_src;
			type* dst_row = chunk_vec_h[bufID] + off_dst;
			for (uint_ i = 0; i < imgSize.y; ++i) {
				const type v = src_row[i];
				dst_row[i] = v;
				if (v < localMin) localMin = v;
			}
			off_src += imgSize.y;
			off_dst += chunkSize.y + 2;
		}
	}
	if ((float)localMin < minValue) minValue = (float)localMin;

	checkCudaErrors(cudaMemcpy3DAsync(&cpyParams_vec[bufID], stream));
	checkCudaErrors(cudaEventRecord(events[2 * bufID + 0], stream));
}
template void TopoGPU3D_Batch<uchar_>::fetch_chunk3D_frmArr(uchar_*, ushort_, ushort_, float&, cudaStream_t&);
template void TopoGPU3D_Batch<ushort_>::fetch_chunk3D_frmArr(ushort_*, ushort_, ushort_, float&, cudaStream_t&);
template void TopoGPU3D_Batch<int>::fetch_chunk3D_frmArr(int*, ushort_, ushort_, float&, cudaStream_t&);
template void TopoGPU3D_Batch<float>::fetch_chunk3D_frmArr(float*, ushort_, ushort_, float&, cudaStream_t&);

template<typename type>
void TopoGPU3D_Batch<type>::fetch_chunk3D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream) {
	/*
		Read a chunk of data from a raw binary volume on disk, parallel over depth slices (poolRows).
	*/
	const uint_ hid				= chunkID % chunkNum_h;
	const uint_ did				= chunkID / chunkNum_h;
	const uint_ hid_src_frm		= (hid == 0) ? 0 : hid * chunkSize.x - 2;
	const uint_ did_src_frm		= (did == 0) ? 0 : did * chunkSize.z - 2;
	const uint_ hid_src_to		= ((hid + 1) * chunkSize.x + 2 > imgSize.x) ? imgSize.x : (hid + 1) * chunkSize.x + 2;
	const uint_ did_src_to		= ((did + 1) * chunkSize.z + 2 > imgSize.z) ? imgSize.z : (did + 1) * chunkSize.z + 2;
	const uint_ hid_dst_frm		= (hid == 0) ? 2 : 0;
	const uint_ did_dst_frm		= (did == 0) ? 2 : 0;
	const uint_ sliceSize_src	= imgSize.x * imgSize.y;
	const uint_ sliceSize_dst	= (chunkSize.x + 4) * (chunkSize.y + 2);
	const uint_ rowSize_src		= imgSize.y;
	const uint_ rowSize_dst		= chunkSize.y + 2;

	// Configure multi-threading parameters (parallelize over depth slices)
	uint_ num_cores		= std::thread::hardware_concurrency();
	uint_ slicesTotal	= did_src_to - did_src_frm;
	if (num_cores == 0) num_cores = 1;
	if (num_cores > slicesTotal) num_cores = slicesTotal;
	const uint_ slicePerThread = iDivUp(slicesTotal, num_cores);

	fill_halo(chunk_vec_h[bufID],
		did_dst_frm, did_dst_frm + slicesTotal,
		hid_dst_frm, hid_dst_frm + (hid_src_to - hid_src_frm));
	std::vector<type> localMins(num_cores, std::numeric_limits<type>::max());

	pool_run(poolRows, num_cores, [&](uint_ i) {
		const uint_ this_did_frm = did_src_frm + i * slicePerThread;
		const uint_ this_did_to = std::min(did_src_frm + (i + 1) * slicePerThread, did_src_to);
		const uint_ this_dst_frm = did_dst_frm + i * slicePerThread;
		if (this_did_frm >= this_did_to) return;

		type localMin = std::numeric_limits<type>::max();
		switch (datatype) {
		case 0: fetch_chunk3D_fromFile_singleThread<uchar_, type>(path, chunk_vec_h[bufID], localMin, this_did_frm, this_did_to, hid_src_frm, hid_src_to, this_dst_frm, hid_dst_frm, sliceSize_src, sliceSize_dst, rowSize_src, rowSize_dst); break;
		case 1: fetch_chunk3D_fromFile_singleThread<ushort_, type>(path, chunk_vec_h[bufID], localMin, this_did_frm, this_did_to, hid_src_frm, hid_src_to, this_dst_frm, hid_dst_frm, sliceSize_src, sliceSize_dst, rowSize_src, rowSize_dst); break;
		case 2: fetch_chunk3D_fromFile_singleThread<int, type>(path, chunk_vec_h[bufID], localMin, this_did_frm, this_did_to, hid_src_frm, hid_src_to, this_dst_frm, hid_dst_frm, sliceSize_src, sliceSize_dst, rowSize_src, rowSize_dst); break;
		case 3: fetch_chunk3D_fromFile_singleThread<float, type>(path, chunk_vec_h[bufID], localMin, this_did_frm, this_did_to, hid_src_frm, hid_src_to, this_dst_frm, hid_dst_frm, sliceSize_src, sliceSize_dst, rowSize_src, rowSize_dst); break;
		default: break;
		}
		localMins[i] = localMin;
		});

	for (type localMin : localMins) if ((float)localMin < minValue) minValue = (float)localMin;

	checkCudaErrors(cudaMemcpy3DAsync(&cpyParams_vec[bufID], stream));
	checkCudaErrors(cudaEventRecord(events[2 * bufID + 0], stream));
}

template<typename type>
void TopoGPU3D_Batch<type>::run_frmArr(type* src, PH3D_Batch_multiThread<type>& ph, ushort_ fileNum) {
	/*
		Process `fileNum` same-sized volumes stored contiguously in src: [fileNum][x][y][z-major as in file].
		Slot s = file * strmCnt + bufID.
	*/
	if (fileNum > halfSize_) { printf("Error: fileNum (%u) > halfSize (%u)\n", (uint_)fileNum, (uint_)halfSize_); return; }
	const ull_ imgElems = 1ULL * imgSize.x * imgSize.y * imgSize.z;
	std::vector<float> minVals(fileNum, std::numeric_limits<float>::max());

	ph.initialize(blockNum, bndmat_num, chunkNum, fileNum, imgSizeX);

	auto collect = [&](uint_ f, uint_ s) {
		checkCudaErrors(cudaEventSynchronize(events[2 * s + 1]));
		ph.bndmat_collect(bndmat_vec_h[s], vals_vec_h[s], offsets_vec_h[s], f);
		};

	ushort_ chunkID = 0;
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		const ushort_ bufID = chunkID % strmCnt;
		const uint3 chunkSize_chunk = make_uint3(chunkSize_h[chunkID % chunkNum_h], chunkSize.y, chunkSize_d[chunkID / chunkNum_h]);
		const uint3 chunkSizeX_chunk = make_uint3(chunkSizeX_h[chunkID % chunkNum_h], chunkSizeX.y, chunkSizeX_d[chunkID / chunkNum_h]);

		// ---- Fetch this chunk of every file ----
		pool_run(poolFiles, fileNum, [&](uint_ f) {
			const uint_ s = slot(f, bufID);
			if (chunkID >= strmCnt) checkCudaErrors(cudaEventSynchronize(events[2 * s + 0]));
			fetch_chunk3D_frmArr(src + f * imgElems, chunkID, (ushort_)s, minVals[f], streams[s]);
			});

		// ---- Harvest previous round of these slots ----
		if (chunkID >= strmCnt) pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });

		// ---- Launch GPU pipeline for every file ----
		for (ushort_ f = 0; f < fileNum; f++) {
			const uint_ s = slot(f, bufID);
			cudaStream_t& st = streams[s];
			procLowerStars_tile3D<type>(texObj_vec[s], chunkID, match_vec_d[s], crit_vec_d[s], chunkSize_chunk, blockSize, blockSizeX, st);
			topoSort_3D(chunkID, match_vec_d[s], crit_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			pathCount_3D(chunkID, match_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			bitCheck_3D<type>(texObj_vec[s], chunkID, crit_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], bndmat_vec_d[s], vals_vec_d[s], offsets_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);

			checkCudaErrors(cudaMemsetAsync(crit_vec_d[s], 0, PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(uchar_), st));
			if (ph.ifbndMatReduct()) {
				checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[s], bndmat_vec_d[s], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(vals_vec_h[s], vals_vec_d[s], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[s], offsets_vec_d[s], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, st));
			}
			checkCudaErrors(cudaEventRecord(events[2 * s + 1], st));
			checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[s], 0, blockNum * bndmat_num * sizeof(ulonglong2), st));
			checkCudaErrors(cudaMemsetAsync(vals_vec_d[s], 0, 2 * blockNum * bndmat_num * sizeof(type), st));
			checkCudaErrors(cudaMemsetAsync(offsets_vec_d[s], 0, blockNum * bndmat_num * sizeof(uchar2), st));
		}
	}

	// ---- Drain ----
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
		const ushort_ bufID = chunkID % strmCnt;
		pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });
	}
	for (ushort_ f = 0; f < fileNum; f++) ph.set_minValue(minVals[f], f);
}
template void TopoGPU3D_Batch<uchar_>::run_frmArr(uchar_*, PH3D_Batch_multiThread<uchar_>&, ushort_);
template void TopoGPU3D_Batch<ushort_>::run_frmArr(ushort_*, PH3D_Batch_multiThread<ushort_>&, ushort_);
template void TopoGPU3D_Batch<int>::run_frmArr(int*, PH3D_Batch_multiThread<int>&, ushort_);
template void TopoGPU3D_Batch<float>::run_frmArr(float*, PH3D_Batch_multiThread<float>&, ushort_);

template<typename type>
void TopoGPU3D_Batch<type>::run_frmFile(
	const std::vector<std::string>& filenames,
	const std::string& datatype_,
	PH3D_Batch_multiThread<type>& ph,
	ushort_								fileNum
) {
	if (fileNum > halfSize_ || fileNum > filenames.size()) { printf("Error: fileNum (%u) > halfSize (%u) or > filenames.size() (%zu)\n", (uint_)fileNum, (uint_)halfSize_, filenames.size()); return; }
	const int datatype = parse_input_type(datatype_);
	std::vector<float> minVals(fileNum, std::numeric_limits<float>::max());

	auto collect = [&](uint_ f, uint_ s) {
		checkCudaErrors(cudaEventSynchronize(events[2 * s + 1]));
		ph.bndmat_collect(bndmat_vec_h[s], vals_vec_h[s], offsets_vec_h[s], f);
		};

	ph.initialize(blockNum, bndmat_num, chunkNum, fileNum, imgSizeX);

	ushort_ chunkID = 0;
	for (; chunkID < chunkNum; chunkID++) {
		if (verbose) printf("--- Processing chunk: %u (%u)\n", chunkID, chunkNum);
		const ushort_ bufID = chunkID % strmCnt;
		const uint3 chunkSize_chunk = make_uint3(chunkSize_h[chunkID % chunkNum_h], chunkSize.y, chunkSize_d[chunkID / chunkNum_h]);
		const uint3 chunkSizeX_chunk = make_uint3(chunkSizeX_h[chunkID % chunkNum_h], chunkSizeX.y, chunkSizeX_d[chunkID / chunkNum_h]);

		// ---- Fetch this chunk of every file ----
		pool_run(poolFiles, fileNum, [&](uint_ f) {
			const uint_ s = slot(f, bufID);
			if (chunkID >= strmCnt) checkCudaErrors(cudaEventSynchronize(events[2 * s + 0]));
			fetch_chunk3D_fromFile_multiThread(filenames[f], datatype, chunkID, (ushort_)s, minVals[f], streams[s]);
			});

		// ---- Harvest previous round of these slots ----
		if (chunkID >= strmCnt) pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });

		// ---- Launch GPU pipeline for every file ----
		for (ushort_ f = 0; f < fileNum; f++) {
			const uint_ s = slot(f, bufID);
			cudaStream_t& st = streams[s];
			procLowerStars_tile3D<type>(texObj_vec[s], chunkID, match_vec_d[s], crit_vec_d[s], chunkSize_chunk, blockSize, blockSizeX, st);
			topoSort_3D(chunkID, match_vec_d[s], crit_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			pathCount_3D(chunkID, match_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], chunkCritNum_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);
			bitCheck_3D<type>(texObj_vec[s], chunkID, crit_vec_d[s], pathCountbuf_vec_d[s], morsBoundbuf_vec_d[s], bndmat_vec_d[s], vals_vec_d[s], offsets_vec_d[s], chunkSizeX_chunk, blockSize, blockSizeX, st);

			checkCudaErrors(cudaMemsetAsync(crit_vec_d[s], 0, PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z) * sizeof(uchar_), st));
			if (ph.ifbndMatReduct()) {
				checkCudaErrors(cudaMemcpyAsync(bndmat_vec_h[s], bndmat_vec_d[s], blockNum * bndmat_num * sizeof(ulonglong2), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(vals_vec_h[s], vals_vec_d[s], 2 * blockNum * bndmat_num * sizeof(type), cudaMemcpyDeviceToHost, st));
				checkCudaErrors(cudaMemcpyAsync(offsets_vec_h[s], offsets_vec_d[s], blockNum * bndmat_num * sizeof(uchar2), cudaMemcpyDeviceToHost, st));
			}
			checkCudaErrors(cudaEventRecord(events[2 * s + 1], st));
			checkCudaErrors(cudaMemsetAsync(bndmat_vec_d[s], 0, blockNum * bndmat_num * sizeof(ulonglong2), st));
			checkCudaErrors(cudaMemsetAsync(vals_vec_d[s], 0, 2 * blockNum * bndmat_num * sizeof(type), st));
			checkCudaErrors(cudaMemsetAsync(offsets_vec_d[s], 0, blockNum * bndmat_num * sizeof(uchar2), st));
		}
	}

	// ---- Drain ----
	for (; chunkID < chunkNum + strmCnt; chunkID++) {
		const ushort_ bufID = chunkID % strmCnt;
		pool_run(poolFiles, fileNum, [&](uint_ f) { collect(f, slot(f, bufID)); });
	}
	for (ushort_ f = 0; f < fileNum; f++) ph.set_minValue(minVals[f], f);
}
template void TopoGPU3D_Batch<uchar_>::run_frmFile(const std::vector<std::string>&, const std::string&, PH3D_Batch_multiThread<uchar_>&, ushort_);
template void TopoGPU3D_Batch<ushort_>::run_frmFile(const std::vector<std::string>&, const std::string&, PH3D_Batch_multiThread<ushort_>&, ushort_);
template void TopoGPU3D_Batch<int>::run_frmFile(const std::vector<std::string>&, const std::string&, PH3D_Batch_multiThread<int>&, ushort_);
template void TopoGPU3D_Batch<float>::run_frmFile(const std::vector<std::string>&, const std::string&, PH3D_Batch_multiThread<float>&, ushort_);

// ===== PH3D_Batch_multiThread =====
template<typename type>
void PH3D_Batch_multiThread<type>::findsource3D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y, uint_& z) {
	const uint_ sliceSize = imgSizeX.x * imgSizeX.y;
	switch (offset) {
	case 1:  idx = idx + sliceSize; break;
	case 2:  idx = idx + 1; break;
	case 3:  idx = idx - 1; break;
	case 4:  idx = idx - sliceSize; break;
	case 5:  idx = idx + imgSizeX.y; break;
	case 6:  idx = idx - imgSizeX.y; break;
	case 7:  idx = idx + imgSizeX.y + sliceSize; break;
	case 8:  idx = idx + sliceSize + 1; break;
	case 9:  idx = idx + sliceSize - 1; break;
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
	default: break;
	}
	z = static_cast<uint_>(idx / sliceSize);
	y = static_cast<uint_>(idx / imgSizeX.y - (ull_)z * imgSizeX.x);
	x = static_cast<uint_>(idx % imgSizeX.y);
	x = (x - 1u) >> 1;
	y = (y - 1u) >> 1;
	z = (z - 1u) >> 1;
}
template void PH3D_Batch_multiThread<uchar_>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_Batch_multiThread<ushort_>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_Batch_multiThread<int>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);
template void PH3D_Batch_multiThread<float>::findsource3D_h(ull_, uchar_, uint_&, uint_&, uint_&);

template<typename type>
void PH3D_Batch_multiThread<type>::bndmat_collect(
	const ulonglong2* const		bndmat_h,
	const type* const			vals_h,
	const uchar2* const			offsets_h,
	const uint_					fileIdx
)
{
	if (!bndMatReduct) return;

	for (uint_ i = 0; i < blockNum; ++i) {
		const ull_ ind1 = 1ULL * i * bndmat_num;
		ulonglong2 pair = bndmat_h[ind1];
		uchar2   offset = offsets_h[ind1];

		uint_ j = 0;
		while (pair.x | pair.y) {
			const ull_ ind2 = 2ULL * ind1 + 2ULL * j;

			auto rx = elements[fileIdx].emplace(pair.x, std::pair<Element<type>, std::vector<ull_>>{});
			auto& mx = rx.first->second;
			if (rx.second) {
				mx.first = { vals_h[ind2], offset.x, 0 };
				mx.second.reserve(8);
			}
			mx.second.push_back(pair.y);

			auto ry = elements[fileIdx].emplace(pair.y, std::pair<Element<type>, std::vector<ull_>>{});
			if (ry.second) {
				ry.first->second.first = { vals_h[ind2 + 1], offset.y, 0 };
			}

			if (++j >= bndmat_num) { printf("Error: boundary matrix buffer limit reached...\n"); exit(1); }
			pair = bndmat_h[ind1 + j];
			offset = offsets_h[ind1 + j];
		}
	}
}
template void PH3D_Batch_multiThread<uchar_>::bndmat_collect(const ulonglong2* const, const uchar_* const, const uchar2* const, const uint_);
template void PH3D_Batch_multiThread<ushort_>::bndmat_collect(const ulonglong2* const, const ushort_* const, const uchar2* const, const uint_);
template void PH3D_Batch_multiThread<int>::bndmat_collect(const ulonglong2* const, const int* const, const uchar2* const, const uint_);
template void PH3D_Batch_multiThread<float>::bndmat_collect(const ulonglong2* const, const float* const, const uchar2* const, const uint_);

template<typename type>
void PH3D_Batch_multiThread<type>::bndmat_reduction() {
	if (!bndMatReduct) return;
	sort_crit_by_values();
	compute_ph();
}
template void PH3D_Batch_multiThread<uchar_>::bndmat_reduction();
template void PH3D_Batch_multiThread<ushort_>::bndmat_reduction();
template void PH3D_Batch_multiThread<int>::bndmat_reduction();
template void PH3D_Batch_multiThread<float>::bndmat_reduction();

template<typename type>
void PH3D_Batch_multiThread<type>::sort_crit_by_values() {
	pool_run(poolFiles, fileNum, [&](uint_ f) { sort_crit_by_values_singleThread(f); });
}
template void PH3D_Batch_multiThread<uchar_>::sort_crit_by_values();
template void PH3D_Batch_multiThread<ushort_>::sort_crit_by_values();
template void PH3D_Batch_multiThread<int>::sort_crit_by_values();
template void PH3D_Batch_multiThread<float>::sort_crit_by_values();

template<typename type>
void PH3D_Batch_multiThread<type>::sort_crit_by_values_singleThread(const uint_ f) {
	auto& elem = elements[f];
	auto& ind = ind_sorted[f];
	const ull_ critNum = elem.size();
	if (critNum == 0) { ind = nullptr; return; }
	ind = malloc1D_pin_<ull_>(critNum);

#ifdef ENABLE_THRUST
	uint_ cnt = 0;
	type* val_h = malloc1D_pin_<type>(critNum);
	for (auto& e : elem) { ind[cnt] = e.first; val_h[cnt++] = e.second.first.value; }

	cudaStream_t stream;
	checkCudaErrors(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking));
	ull_* ind_d = nullptr; type* val_d = nullptr;
	checkCudaErrors(cudaMallocAsync(&ind_d, critNum * sizeof(ull_), stream));
	checkCudaErrors(cudaMallocAsync(&val_d, critNum * sizeof(type), stream));
	checkCudaErrors(cudaMemcpyAsync(ind_d, ind, critNum * sizeof(ull_), cudaMemcpyHostToDevice, stream));
	checkCudaErrors(cudaMemcpyAsync(val_d, val_h, critNum * sizeof(type), cudaMemcpyHostToDevice, stream));

	thrust::sort_by_key(thrust::cuda::par_nosync.on(stream),
		thrust::device_pointer_cast(val_d), thrust::device_pointer_cast(val_d) + critNum,
		thrust::device_pointer_cast(ind_d));

	checkCudaErrors(cudaMemcpyAsync(ind, ind_d, critNum * sizeof(ull_), cudaMemcpyDeviceToHost, stream));
	checkCudaErrors(cudaFreeAsync(ind_d, stream));
	checkCudaErrors(cudaFreeAsync(val_d, stream));
	checkCudaErrors(cudaStreamSynchronize(stream));
	checkCudaErrors(cudaStreamDestroy(stream));
	cudaFreeHost(val_h);
#else
	std::vector<std::pair<type, ull_>> tmp;
	tmp.reserve(critNum);
	for (auto& e : elem) tmp.emplace_back(e.second.first.value, e.first);
	std::sort(tmp.begin(), tmp.end(), [](auto& a, auto& b) { return a.first < b.first; });
	for (ull_ i = 0; i < critNum; ++i) ind[i] = tmp[i].second;
#endif
	for (ull_ i = 0; i < critNum; ++i) elem[ind[i]].first.order = i;
}

template<typename type>
void PH3D_Batch_multiThread<type>::compute_ph() {
	const uint_ outer = std::max<uint_>(1u, std::min<uint_>(fileNum, numCores));
	const uint_ inner = std::max<uint_>(1u, numCores / outer);
	pool_run(poolFiles, fileNum, [&](uint_ f) { compute_ph_singleFile(f, inner); });
}
template void PH3D_Batch_multiThread<uchar_>::compute_ph();
template void PH3D_Batch_multiThread<ushort_>::compute_ph();
template void PH3D_Batch_multiThread<int>::compute_ph();
template void PH3D_Batch_multiThread<float>::compute_ph();

template<typename type>
void PH3D_Batch_multiThread<type>::compute_ph_singleFile(const uint_ f, const uint_ threadBudget) {
	const ull_ critNum = elements[f].size();
	if (critNum == 0) return;

	phat::boundary_matrix<phat::bit_tree_pivot_column> boundary_matrix;
	boundary_matrix.set_num_cols(critNum);

	// ---- Setup boundary matrix ----
	{
		const uint_ cores = (uint_)std::min<ull_>(threadBudget, critNum);
		const ull_  range = iDivUp(critNum, (ull_)cores);
		pool_run(poolRange, cores, [&](uint_ i) {
			const ull_ s = 1ULL * i * range, e = std::min<ull_>(s + range, critNum);
			setup_bndmat_SingleThread(boundary_matrix, s, e, f);
			});
	}

	// ---- Reduction (PHAT is single-threaded) ----
	phat::persistence_pairs pairs;
	phat::compute_persistence_pairs<phat::twist_reduction>(pairs, boundary_matrix);

	// ---- Gather non-trivial pairs ----
	{
		const ull_  colNum = boundary_matrix.get_num_cols();
		const uint_ cores = (uint_)std::min<ull_>(threadBudget, colNum);
		const ull_  range = iDivUp(colNum, (ull_)cores);
		results[f].reserve((colNum + 1) * 9);
		pool_run(poolRange, cores, [&](uint_ i) {
			const ull_ s = 1ULL * i * range, e = std::min<ull_>(s + range, colNum);
			gather_nontrivial_pairs_SingleThread(boundary_matrix, s, e, f);
			});
	}

	// ---- Essential pair ----
	auto& res = results[f];
	res.push_back(0.f);
	res.push_back(static_cast<float>(minValue[f]));
	res.push_back(std::numeric_limits<float>::infinity());
	for (int k = 0; k < 6; ++k) res.push_back(0.f);
}

template<typename type>
void PH3D_Batch_multiThread<type>::set_minValue(float v, const uint_ fileIdx) {
	minValue[fileIdx] = v;
}
template void PH3D_Batch_multiThread<uchar_>::set_minValue(float, const uint_);
template void PH3D_Batch_multiThread<ushort_>::set_minValue(float, const uint_);
template void PH3D_Batch_multiThread<int>::set_minValue(float, const uint_);
template void PH3D_Batch_multiThread<float>::set_minValue(float, const uint_);

template<typename type>
void PH3D_Batch_multiThread<type>::print_results() {
	for (uint_ f = 0; f < fileNum; f++) {
		const uint_ rowNum = results[f].size() / 9;
		printf("Persistence results: %d persistence pair(s)\n", rowNum);
	}
}
template void PH3D_Batch_multiThread<uchar_>::print_results();
template void PH3D_Batch_multiThread<ushort_>::print_results();
template void PH3D_Batch_multiThread<int>::print_results();
template void PH3D_Batch_multiThread<float>::print_results();

template<typename type>
void PH3D_Batch_multiThread<type>::write_results(const std::string& out_path, const uint_ fileIdx) {
	std::ofstream out(out_path, std::ios::out | std::ios::trunc);
	if (!out) { std::cout << "Can't write to file..." << std::endl; return; }

	out << std::setprecision(6);
	const auto& r = results[fileIdx];
	const uint_ rowNum = r.size() / 9;
	uint_ idx = 0;
	for (uint_ row = 0; row < rowNum; row++) {
		out << r[idx] << ' ' << r[idx + 1] << ' ' << r[idx + 2] << ' '
			<< r[idx + 3] << ' ' << r[idx + 4] << ' ' << r[idx + 5] << ' '
			<< r[idx + 6] << ' ' << r[idx + 7] << ' ' << r[idx + 8] << '\n';
		idx += 9;
	}
	out.close();
}
template void PH3D_Batch_multiThread<uchar_>::write_results(const std::string&, const uint_);
template void PH3D_Batch_multiThread<ushort_>::write_results(const std::string&, const uint_);
template void PH3D_Batch_multiThread<int>::write_results(const std::string&, const uint_);
template void PH3D_Batch_multiThread<float>::write_results(const std::string&, const uint_);

template<typename type>
float* PH3D_Batch_multiThread<type>::return_results(const uint_ fileIdx) {
	return results[fileIdx].data();
}
template float* PH3D_Batch_multiThread<uchar_>::return_results(const uint_);
template float* PH3D_Batch_multiThread<ushort_>::return_results(const uint_);
template float* PH3D_Batch_multiThread<int>::return_results(const uint_);
template float* PH3D_Batch_multiThread<float>::return_results(const uint_);

template<typename type>
uint_ PH3D_Batch_multiThread<type>::return_pairNum(const uint_ fileIdx) {
	return results[fileIdx].size() / 9;
}
template uint_ PH3D_Batch_multiThread<uchar_>::return_pairNum(const uint_);
template uint_ PH3D_Batch_multiThread<ushort_>::return_pairNum(const uint_);
template uint_ PH3D_Batch_multiThread<int>::return_pairNum(const uint_);
template uint_ PH3D_Batch_multiThread<float>::return_pairNum(const uint_);