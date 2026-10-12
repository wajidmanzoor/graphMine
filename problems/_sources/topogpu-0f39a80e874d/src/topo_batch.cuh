#pragma once

#include "util_cu.cuh"

#include <mutex>
#include <unordered_map>
#include "stb_image.h"

/*
	PHAT headers for boundary matrix reduction
	https://bitbucket.org/phat-code/phat/src/master/
*/
#include <phat/compute_persistence_pairs.h>
#include <phat/algorithms/twist_reduction.h>

template <typename type>
class PH2D_Batch_multiThread {
public:
	PH2D_Batch_multiThread(bool bndMatReduct_, ushort_ batchSize_) : bndMatReduct(bndMatReduct_), batchSize(batchSize_) {
		numCores = std::thread::hardware_concurrency();
		poolFiles.resize(std::max<uint_>(1u, std::min<uint_>(batchSize, numCores)));
		poolRange.resize(std::max<uint_>(1u, numCores));

		ind_sorted.resize(batchSize);
		elements.resize(batchSize);
		results.resize(batchSize);
		minValue.resize(batchSize);
	}

	~PH2D_Batch_multiThread() {
		free1D_vec_pin(batchSize, ind_sorted);
		elements.clear();
		results.clear();
		minValue.clear();
	}

	void reset() {
		free1D_vec_pin(batchSize, ind_sorted);
		for (uint_ i = 0; i < batchSize; i++) {
			elements[i].clear();
			results[i].clear();
		}	
	}

	void initialize(const uint_& blockNum_, const uint_& bndmat_num_, const uint_& chunkNum_, const ushort_& fileNum_, const uint2& imgSizeX_) {
		/*
			Called at the beginning of every run
		*/
		if (!bndMatReduct) return;

		blockNum	= blockNum_;
		bndmat_num	= bndmat_num_;
		chunkNum	= chunkNum_;
		imgSizeX	= imgSizeX_;
		fileNum		= fileNum_;

		// Boundary relations in RAM
		// Pre-allocate memory space
		uint64_t totalElems = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		for (uint_ i = 0; i < batchSize; i++) elements[i].reserve(totalElems / 8);
	}

	// Find top-cell that introduces the cell
	void findsource2D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y);
	// Collect boundary relations and filtration values
	void bndmat_collect(const ulonglong2* const bndmat_h, const type* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);
	// Boundary maatrix reduction
	void bndmat_reduction();
	// Compute crit ordering
	void sort_crit_by_values();
	void sort_crit_by_values_singleThread(const uint_ f);
	// Compute persistent homology
	void compute_ph();
	void compute_ph_singleFile(const uint_ f, const uint_ threadBudget);
	// Set minimum value
	void set_minValue(float, const uint_);

	// Print results
	void print_results();
	// Write results to file
	void write_results(const std::string& out_path, const uint_);
	// Return results
	float* return_results(const uint_);
	// Return pair number
	uint_ return_pairNum(const uint_);

	// Setup boundary matrix on one thread
	void setup_bndmat_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat,
		const ull_											startIdx,
		const ull_											endIdx,
		const uint_											fileIdx
	)
	{
		for (ull_ i = startIdx; i < endIdx; i++) {
			const ull_ idx = ind_sorted[fileIdx][i];
			auto it = elements[fileIdx].find(idx);
			auto& neighbors = it->second.second;
			if (neighbors.empty()) continue;

			for (ull_& v : neighbors) v = elements[fileIdx].at(v).first.order;
			std::sort(neighbors.begin(), neighbors.end());
			neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());

			// Decide cell dimension
			const uint_ y = idx / imgSizeX.y;
			const uint_ x = idx % imgSizeX.y;
			phat::dimension dim = (x & 1u) + (y & 1u);
			// Set boundary relations
			bndmat.set_dim(it->second.first.order, dim);
			bndmat.set_col(it->second.first.order, neighbors);
			neighbors.clear();
		}
	}

	// Gather non-trivial persistence pairs
	void gather_nontrivial_pairs_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat,
		const ull_											startIdx,
		const ull_											endIdx,
		const uint_											fileIdx
	)
	{
		std::vector<float> resLocal;
		resLocal.reserve((endIdx - startIdx) * 7);
		uint_ x1, y1, x2, y2, dim;

		for (ull_ i = startIdx; i < endIdx; i++) {
			if (bndmat.is_empty(i)) continue;

			ull_ birth = bndmat.get_max_index(i);
			auto& birthElem = elements[fileIdx][ind_sorted[fileIdx][birth]].first;
			auto& deathElem = elements[fileIdx][ind_sorted[fileIdx][i]].first;
			if (birthElem.value == deathElem.value) continue;

			ull_ birthIdx = ind_sorted[fileIdx][birth];
			ull_ deathIdx = ind_sorted[fileIdx][i];
			// Decide cell dimension
			y1 = birthIdx / imgSizeX.y;
			x1 = birthIdx % imgSizeX.y;
			dim = (x1 & 1u) + (y1 & 1u);

			findsource2D_h(birthIdx, birthElem.offset, x1, y1);
			findsource2D_h(deathIdx, deathElem.offset, x2, y2);

			resLocal.push_back(static_cast<float>(dim));
			resLocal.push_back(static_cast<float>(birthElem.value));
			resLocal.push_back(static_cast<float>(deathElem.value));
			resLocal.push_back(static_cast<float>(y1));
			resLocal.push_back(static_cast<float>(x1));
			resLocal.push_back(static_cast<float>(y2));
			resLocal.push_back(static_cast<float>(x2));
		}
		std::lock_guard<std::mutex> guard(mtx);
		results[fileIdx].insert(results[fileIdx].end(), resLocal.begin(), resLocal.end());
	}

	bool ifbndMatReduct() { return bndMatReduct; }

private:
	bool					bndMatReduct;

	ushort_					fileNum;
	ushort_					batchSize;
	uint_					blockNum;
	uint_					bndmat_num;
	uint_					chunkNum;
	uchar_					numCores;
	uint2					imgSizeX;
	std::mutex				mtx;

	std::vector<ull_*>						ind_sorted;
	std::vector<std::unordered_map<ull_, std::pair<Element<type>, std::vector<ull_>>>> elements;
	// Persistent homology results
	std::vector<float>						minValue;
	std::vector<std::vector<float>>			results;

	ctpl::thread_pool		poolFiles;
	ctpl::thread_pool		poolRange;
};

template <typename type>
class TopoGPU2D_Batch {
public:
	TopoGPU2D_Batch(
		ushort_		batchSize_,
		uint2		imgSize_,
		uint_		bndmat_num_,
		uint2		blockSize_ = uint2{ 0, 0 },
		int			deviceID = -1,
		bool		debug_ = false,
		bool		verbose_ = false
	) :
		batchSize(batchSize_), imgSize(imgSize_), blockSize(blockSize_), bndmat_num(bndmat_num_),
		img_decoded_h((batchSize_ + 1) / 2, nullptr), img_decoded_path((batchSize_ + 1) / 2), img_decoded_dt((batchSize_ + 1) / 2, -1), debug(debug_), verbose(verbose_)
	{
		halfSize_ = (ushort_)((batchSize + 1) / 2);
		// Choose GPU device
		find_and_query_device(prop, deviceID, debug, verbose);
		// Decide chunk and block sizes
		choose_chunk_block_size2D<type>(imgSize, prop, chunkSize, blockSize, make_uint2(0, 0));
		chunkSize_atCreation = chunkSize;
		proc_size();
		maxDim2Compute = 2;

		// printf("Chunk size: %d %d\n", chunkSize.x, chunkSize.y);
		// printf("Block Size: %d %d\n", blockSize.x, blockSize.y);

		// Allocate host memory
		chunk_vec_h				= malloc1D_vec_pin_<type>(strmCnt * halfSize_, PRODUCT2(chunkSize.x + 4, chunkSize.y + 2));
		bndmat_vec_h			= malloc1D_vec_pin_<ulonglong2>(strmCnt * halfSize_, blockNum * bndmat_num);
		vals_vec_h				= malloc1D_vec_pin_<type>(strmCnt * halfSize_, 2 * blockNum * bndmat_num);
		offsets_vec_h			= malloc1D_vec_pin_<uchar2>(strmCnt * halfSize_, blockNum * bndmat_num);
		chunkSize_h				= malloc1D_h_<uint_>(chunkNum);
		chunkSizeX_h			= malloc1D_h_<uint_>(chunkNum);
		// Allocate device memory
		cuArr_vec				= malloc_cudaArray2D_vec<type>(strmCnt * halfSize_, chunkSize.x + 4, chunkSize.y + 2);
		texObj_vec				= create_cuTexObj_vec(strmCnt * halfSize_, cuArr_vec);
		match_vec_d				= malloc1D_vec_d_<uchar_>(strmCnt * halfSize_, chunkSizeX.x * chunkSizeX.y);
		crit_vec_d				= malloc1D_vec_d_<uchar_>(strmCnt * halfSize_, chunkSizeX.x * chunkSizeX.y);
		morsBoundbuf_vec_d		= malloc1D_vec_d_<ushort_>(strmCnt * halfSize_, blockNum * blockSizeX.x * blockSizeX.y * 4);
		pathCountbuf_vec_d		= malloc1D_vec_d_<uint_>(strmCnt * halfSize_, blockNum * blockSizeX.x * blockSizeX.y * PATHCNT_BUF_SIZE);
		chunkCritNum_vec_d		= malloc1D_vec_d_<ushort_>(strmCnt * halfSize_, blockNum);
		bndmat_vec_d			= malloc1D_vec_d_<ulonglong2>(strmCnt * halfSize_, blockNum * bndmat_num);
		vals_vec_d				= malloc1D_vec_d_<type>(strmCnt * halfSize_, 2 * blockNum * bndmat_num);
		offsets_vec_d			= malloc1D_vec_d_<uchar2>(strmCnt * halfSize_, blockNum * bndmat_num);
		// Create CUDA streams
		streams = create_cudaStream_vec(strmCnt * halfSize_);
		events = create_cudaEvent_vec(2 * strmCnt * halfSize_);

		// Upload information to constant memory
		upload_info_2constant();

		poolFiles.resize(std::max<uint_>(1u, std::min<uint_>(halfSize_, std::thread::hardware_concurrency())));
		poolRows.resize(std::max<uint_>(1u, std::thread::hardware_concurrency()));

		phs_[0] = std::make_unique<PH2D_Batch_multiThread<type>>(true, halfSize_);
		phs_[1] = std::make_unique<PH2D_Batch_multiThread<type>>(true, halfSize_);
	}

	~TopoGPU2D_Batch() {
		if (pending_.valid()) pending_.get();
		// Release host memory
		free1D_vec_pin(strmCnt * halfSize_, chunk_vec_h);
		free1D_vec_pin(strmCnt * halfSize_, bndmat_vec_h);
		free1D_vec_pin(strmCnt * halfSize_, vals_vec_h);
		free1D_vec_pin(strmCnt * halfSize_, offsets_vec_h);
		free(chunkSize_h);
		free(chunkSizeX_h);

		// Release device memory
		free_cuTexObj_vec(strmCnt * halfSize_, texObj_vec);
		free_cudaArray_vec(strmCnt * halfSize_, cuArr_vec);
		free1D_vec_d_(strmCnt * halfSize_, match_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, crit_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, morsBoundbuf_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, pathCountbuf_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, chunkCritNum_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, bndmat_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, vals_vec_d);
		free1D_vec_d_(strmCnt * halfSize_, offsets_vec_d);
		// Destroy streams
		free_cudaStream_vec(streams, strmCnt * halfSize_);
		free_cudaEvent_vec(events, 2 * strmCnt * halfSize_);

		for (auto& p : img_decoded_h) { if (p) { stbi_image_free(p); p = nullptr; } }
	}

	// Preprocessing functions
	void proc_size();
	void upload_info_2constant();
	// Data fetch function
	void fetch_chunk2D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
	void fetch_chunk2D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
	void fetch_chunk2D_fromImage_multiThread(const std::string& path, int datatype, ushort_	chunkID, ushort_ bufID, const uint_	fileIdx, float& minValue, cudaStream_t& stream);
	// Main algorithm
	void run_frmArr(type* src, PH2D_Batch_multiThread<type>& ph, ushort_ fileNum);
	void run_frmFile(const std::vector<std::string>& filenames, const std::string& datatype_, PH2D_Batch_multiThread<type>& ph, ushort_	fileNum);

	inline uint_ slot(uint_ f, uint_ bufID) const { return f * strmCnt + bufID; }
	void fill_halo(type* buf, uint_ rowFrom, uint_ rowTo) const;

	// Debug functions
	uint2 return_blockDims() { return blockSize; }
	uint2 return_chunkDims() { return chunkSize; }

	void compute(const std::vector<std::string>& filenames, const std::string& datatype) {
		const uint_ n = (uint_)std::min<size_t>(filenames.size(), batchSize);
		const uint_ n1 = std::min<uint_>(n, halfSize_), n2 = n - n1;
		std::vector<std::string> part1(filenames.begin(), filenames.begin() + n1);
		std::vector<std::string> part2(filenames.begin() + n1, filenames.begin() + n);
		compute_impl(n1, n2,
			[&]() { run_frmFile(part1, datatype, *phs_[0], (ushort_)n1); },
			[&]() { run_frmFile(part2, datatype, *phs_[1], (ushort_)n2); });
	}
	void compute(type* src, ushort_ fileNum) {
		const uint_ n = std::min<uint_>(fileNum, batchSize);
		const uint_ n1 = std::min<uint_>(n, halfSize_), n2 = n - n1;
		const ull_ imgElems = 1ULL * imgSize.x * imgSize.y;
		compute_impl(n1, n2,
			[&]() { run_frmArr(src, *phs_[0], (ushort_)n1); },
			[&]() { run_frmArr(src + n1 * imgElems, *phs_[1], (ushort_)n2); });
	}

	// Results of the last compute(): fileIdx in [0, fileNum()), 7 floats per pair
	uint_  fileNum() const { return partNum_[0] + partNum_[1]; }
	uint_  pairNum(uint_ fileIdx) { return fileIdx < partNum_[0] ? phs_[0]->return_pairNum(fileIdx) : phs_[1]->return_pairNum(fileIdx - partNum_[0]); }
	float* result(uint_ fileIdx) { return fileIdx < partNum_[0] ? phs_[0]->return_results(fileIdx) : phs_[1]->return_results(fileIdx - partNum_[0]); }
	// Free results of the last compute()
	void reset() { phs_[0]->reset(); phs_[1]->reset(); partNum_[0] = partNum_[1] = 0; }

private:
	// Basic parameters
	DeviceProp										prop;							// properties of the chosen device
	bool											debug;							// run the program in debug mode
	bool											verbose;						// output program information
	int												num_sms;
	ushort_											strmCnt;
	ushort_											batchSize;
	uint2											imgSize;						// Height and width of the input
	uint2											imgSizeX;						// (2 x imgSize.x + 1), (2 x imgSize.y + 1), (2 x imgSize.z + 1)
	uint_											blockNum;
	uint2											blockSize;
	uint2											blockSizeX;						// 2 x blockSize + 1
	uint_											chunkNum;						// total number of chunks in the input
	uint2											chunkSizeX;						// (2 x chunkSize.x + 1), (2 x imgSize.y + 1), (2 x chunkSize.z + 1)
	uint_											maxDim2Compute;					// maximum dimension to compute persistent homology
	// Basic parameters: Hyper-parameters
	uint2											chunkSize;						// Suggested chunk size EXCLUDING halo/apron
	uint2											chunkSize_atCreation;			// Chunk size determined at creation, used for batch mode
	uint_											bndmat_num;						// Size of buffer each block uses to store critical pairs. Smaller size could cause FAILURE!
	// Coded input (jpg/png etc.) use
	std::vector<void*>								img_decoded_h;
	std::vector<std::string>						img_decoded_path;
	std::vector<int>								img_decoded_dt;

	// Host Memory
	std::vector<type*>								chunk_vec_h;					// host memory for input chunks
	std::vector<ulonglong2*>						bndmat_vec_h;					// host memory for boundary matrix used in topo order
	std::vector<type*>								vals_vec_h;						// host memory for critical pair filtration values
	std::vector<uchar2*>							offsets_vec_h;					// host memory for cell offsets
	// Host memory utility to upload to constant memory
	uint_*											chunkSize_h;					// actual chunk height for each chunk, width remains the same
	uint_*											chunkSizeX_h;					// grid chunk height for each chunk, 2 * chunk_size + 1

	// Device memory
	std::vector<cudaArray*>							cuArr_vec;						// device memory for input chunks
	std::vector<cudaTextureObject_t>				texObj_vec;						// cuda texture object binded with cuArr
	std::vector<uchar_*>							match_vec_d;					// device memory for matching grid
	std::vector<uchar_*>							crit_vec_d;						// device memory for critical cell mask
	std::vector<ushort_*>							morsBoundbuf_vec_d;				// device memory for topological order computation buffer
	std::vector<uint_*>								pathCountbuf_vec_d;				// device memory for path counting computation buffer
	std::vector<ushort_*>							chunkCritNum_vec_d;				// device memory to store number of critical cells for each block in each chunk
	std::vector<ulonglong2*>						bndmat_vec_d;					// device memory for boundary matrix used in topo order
	std::vector<type*>								vals_vec_d;						// device memory for critical pair filtration values
	std::vector<uchar2*>							offsets_vec_d;					// device memory for cell offsets

	// CUDA streams
	std::vector<cudaStream_t>						streams;						// CUDA streams
	std::vector<cudaEvent_t>						events;

	ctpl::thread_pool								poolFiles;						// per-file fetch / collect
	ctpl::thread_pool								poolRows;						// row-parallel fill inside fetch_*_multiThread

	ushort_											halfSize_;						// ceil(batchSize/2): capacity of each half
	std::unique_ptr<PH2D_Batch_multiThread<type>>	phs_[2];						// one reducer per half
	uint_											partNum_[2] = { 0, 0 };			// files in each half for the last compute()
	std::future<void>								pending_;

	template <typename Run1, typename Run2>
	void compute_impl(uint_ n1, uint_ n2, Run1&& run1, Run2&& run2) {
		reset();
		partNum_[0] = n1; partNum_[1] = n2;
		if (n1 == 0) return;

		run1();                                                                       // GPU part 1
		pending_ = std::async(std::launch::async, [this]() { phs_[0]->bndmat_reduction(); });   // CPU part 1 ...
		if (n2 > 0) run2();                                                           // ... overlaps GPU part 2
		pending_.get();
		if (n2 > 0) phs_[1]->bndmat_reduction();                                      // CPU part 2
	}
};

template <typename type>
class PH3D_Batch_multiThread {
public:
	PH3D_Batch_multiThread(bool bndMatReduct_, ushort_ batchSize_) : bndMatReduct(bndMatReduct_), batchSize(batchSize_) {
		numCores = std::thread::hardware_concurrency();
		poolFiles.resize(std::max<uint_>(1u, std::min<uint_>(batchSize, numCores)));
		poolRange.resize(std::max<uint_>(1u, numCores));

		ind_sorted.resize(batchSize);
		elements.resize(batchSize);
		results.resize(batchSize);
		minValue.resize(batchSize);
	}

	~PH3D_Batch_multiThread() {
		free1D_vec_pin(batchSize, ind_sorted);
		elements.clear();
		results.clear();
		minValue.clear();
	}

	void reset() {
		free1D_vec_pin(batchSize, ind_sorted);
		for (uint_ i = 0; i < batchSize; i++) {
			elements[i].clear();
			results[i].clear();
		}
	}

	void initialize(const uint_& blockNum_, const uint_& bndmat_num_, const uint_& chunkNum_, const ushort_& fileNum_, const uint3& imgSizeX_) {
		if (!bndMatReduct) return;

		blockNum = blockNum_;
		bndmat_num = bndmat_num_;
		chunkNum = chunkNum_;
		imgSizeX = imgSizeX_;
		fileNum = fileNum_;

		uint64_t totalElems = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		for (uint_ i = 0; i < batchSize; i++) elements[i].reserve(totalElems / 8);
	}

	// Find top-cell that introduces the cell
	void findsource3D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y, uint_& z);
	// Collect boundary relations and filtration values
	void bndmat_collect(const ulonglong2* const bndmat_h, const type* const vals_h, const uchar2* const offsets_h, const uint_ fileIdx);
	// Boundary matrix reduction
	void bndmat_reduction();
	// Compute crit ordering
	void sort_crit_by_values();
	void sort_crit_by_values_singleThread(const uint_ f);
	// Compute persistent homology
	void compute_ph();
	void compute_ph_singleFile(const uint_ f, const uint_ threadBudget);
	// Set minimum value
	void set_minValue(float, const uint_);

	// Print results
	void print_results();
	// Write results to file
	void write_results(const std::string& out_path, const uint_);
	// Return results (9 floats per pair)
	float* return_results(const uint_);
	// Return pair number
	uint_ return_pairNum(const uint_);

	// Setup boundary matrix on one thread
	void setup_bndmat_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat,
		const ull_											startIdx,
		const ull_											endIdx,
		const uint_											fileIdx
	)
	{
		const uint_ planeSize = imgSizeX.x * imgSizeX.y;
		for (ull_ i = startIdx; i < endIdx; i++) {
			const ull_ idx = ind_sorted[fileIdx][i];
			auto it = elements[fileIdx].find(idx);
			auto& neighbors = it->second.second;
			if (neighbors.empty()) continue;

			for (ull_& v : neighbors) v = elements[fileIdx].at(v).first.order;
			std::sort(neighbors.begin(), neighbors.end());
			neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());

			// Decide cell dimension
			const uint_ z = idx / planeSize;
			const uint_ y = idx / imgSizeX.y - z * imgSizeX.x;
			const uint_ x = idx % imgSizeX.y;
			phat::dimension dim = (x & 1u) + (y & 1u) + (z & 1u);
			// Set boundary relations
			bndmat.set_dim(it->second.first.order, dim);
			bndmat.set_col(it->second.first.order, neighbors);
			neighbors.clear();
		}
	}

	// Gather non-trivial persistence pairs
	void gather_nontrivial_pairs_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat,
		const ull_											startIdx,
		const ull_											endIdx,
		const uint_											fileIdx
	)
	{
		std::vector<float> resLocal;
		resLocal.reserve((endIdx - startIdx) * 9);
		const uint_ planeSize = imgSizeX.x * imgSizeX.y;
		uint_ x1, y1, z1, x2, y2, z2, dim;

		for (ull_ i = startIdx; i < endIdx; i++) {
			if (bndmat.is_empty(i)) continue;

			ull_ birth = bndmat.get_max_index(i);
			auto& birthElem = elements[fileIdx][ind_sorted[fileIdx][birth]].first;
			auto& deathElem = elements[fileIdx][ind_sorted[fileIdx][i]].first;
			if (birthElem.value == deathElem.value) continue;

			ull_ birthIdx = ind_sorted[fileIdx][birth];
			ull_ deathIdx = ind_sorted[fileIdx][i];
			// Decide cell dimension
			z1 = birthIdx / planeSize;
			y1 = birthIdx / imgSizeX.y - z1 * imgSizeX.x;
			x1 = birthIdx % imgSizeX.y;
			dim = (x1 & 1u) + (y1 & 1u) + (z1 & 1u);

			findsource3D_h(birthIdx, birthElem.offset, x1, y1, z1);
			findsource3D_h(deathIdx, deathElem.offset, x2, y2, z2);

			resLocal.push_back(static_cast<float>(dim));
			resLocal.push_back(static_cast<float>(birthElem.value));
			resLocal.push_back(static_cast<float>(deathElem.value));
			resLocal.push_back(static_cast<float>(z1));
			resLocal.push_back(static_cast<float>(y1));
			resLocal.push_back(static_cast<float>(x1));
			resLocal.push_back(static_cast<float>(z2));
			resLocal.push_back(static_cast<float>(y2));
			resLocal.push_back(static_cast<float>(x2));
		}
		std::lock_guard<std::mutex> guard(mtx);
		results[fileIdx].insert(results[fileIdx].end(), resLocal.begin(), resLocal.end());
	}

	bool ifbndMatReduct() { return bndMatReduct; }

private:
	bool								bndMatReduct;

	ushort_								fileNum;
	ushort_								batchSize;
	uint_								blockNum;
	uint_								bndmat_num;
	uint_								chunkNum;
	uchar_								numCores;
	uint3								imgSizeX;
	std::mutex							mtx;

	std::vector<ull_*>					ind_sorted;
	std::vector<std::unordered_map<ull_, std::pair<Element<type>, std::vector<ull_>>>> elements;
	// Persistent homology results
	std::vector<float>					minValue;
	std::vector<std::vector<float>>		results;

	ctpl::thread_pool					poolFiles;
	ctpl::thread_pool					poolRange;
};

template <typename type>
class TopoGPU3D_Batch {
public:
	TopoGPU3D_Batch(
		ushort_		batchSize_,
		uint3		imgSize_,
		uint_		bndmat_num_,
		uint3		blockSize_ = uint3{ 0, 0, 0 },
		int			deviceID = -1,
		bool		debug_ = false,
		bool		verbose_ = false
	) :
		batchSize(batchSize_), imgSize(imgSize_), blockSize(blockSize_), bndmat_num(bndmat_num_), debug(debug_), verbose(verbose_)
	{
		halfSize_ = (ushort_)((batchSize + 1) / 2);
		// Choose GPU device
		find_and_query_device(prop, deviceID, debug, verbose);
		// Decide chunk and block sizes
		choose_chunk_block_size<type>(imgSize, prop, chunkSize, blockSize, make_uint3(0, 0, 0));
		chunkSize_atCreation = chunkSize;
		proc_size();
		maxDim2Compute = 3;

		const uint_ S = strmCnt * halfSize_;
		// Allocate host memory
		chunk_vec_h = malloc1D_vec_pin_<type>(S, PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4));
		bndmat_vec_h = malloc1D_vec_pin_<ulonglong2>(S, blockNum * bndmat_num);
		vals_vec_h = malloc1D_vec_pin_<type>(S, 2 * blockNum * bndmat_num);
		offsets_vec_h = malloc1D_vec_pin_<uchar2>(S, blockNum * bndmat_num);
		chunkSize_h = malloc1D_h_<uint_>(chunkNum_h);
		chunkSize_d = malloc1D_h_<uint_>(chunkNum_d);
		chunkSizeX_h = malloc1D_h_<uint_>(chunkNum_h);
		chunkSizeX_d = malloc1D_h_<uint_>(chunkNum_d);
		// Allocate device memory
		cuArr_vec = malloc_cudaArray3D_vec<type>(S, chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4);
		texObj_vec = create_cuTexObj_vec(S, cuArr_vec);
		match_vec_d = malloc1D_vec_d_<ushort_>(S, PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z));
		crit_vec_d = malloc1D_vec_d_<uchar_>(S, PRODUCT3(chunkSizeX.x, chunkSizeX.y, chunkSizeX.z));
		morsBoundbuf_vec_d = malloc1D_vec_d_<ushort_>(S, blockNum * PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * 4);
		pathCountbuf_vec_d = malloc1D_vec_d_<uint_>(S, blockNum * PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * PATHCNT_BUF_SIZE);
		chunkCritNum_vec_d = malloc1D_vec_d_<ushort_>(S, blockNum);
		bndmat_vec_d = malloc1D_vec_d_<ulonglong2>(S, blockNum * bndmat_num);
		vals_vec_d = malloc1D_vec_d_<type>(S, 2 * blockNum * bndmat_num);
		offsets_vec_d = malloc1D_vec_d_<uchar2>(S, blockNum * bndmat_num);
		// Create CUDA streams / events
		streams = create_cudaStream_vec(S);
		events = create_cudaEvent_vec(2 * S);
		// 3D copy parameters, one per slot
		cpyParams_vec.assign(S, cudaMemcpy3DParms{});
		for (uint_ i = 0; i < S; i++)
			cpyParams_vec[i] = create_3DCopyParms<type>(cuArr_vec[i], chunk_vec_h[i], chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4, 0);

		// Upload information to constant memory
		upload_info_2constant();

		poolFiles.resize(std::max<uint_>(1u, std::min<uint_>(halfSize_, std::thread::hardware_concurrency())));
		poolRows.resize(std::max<uint_>(1u, std::thread::hardware_concurrency()));

		phs_[0] = std::make_unique<PH3D_Batch_multiThread<type>>(true, halfSize_);
		phs_[1] = std::make_unique<PH3D_Batch_multiThread<type>>(true, halfSize_);
	}

	~TopoGPU3D_Batch() {
		if (pending_.valid()) pending_.get();
		const uint_ S = strmCnt * halfSize_;
		cpyParams_vec.clear();
		// Release host memory
		free1D_vec_pin(S, chunk_vec_h);
		free1D_vec_pin(S, bndmat_vec_h);
		free1D_vec_pin(S, vals_vec_h);
		free1D_vec_pin(S, offsets_vec_h);
		free(chunkSize_h);
		free(chunkSize_d);
		free(chunkSizeX_h);
		free(chunkSizeX_d);
		// Release device memory
		free_cuTexObj_vec(S, texObj_vec);
		free_cudaArray_vec(S, cuArr_vec);
		free1D_vec_d_(S, match_vec_d);
		free1D_vec_d_(S, crit_vec_d);
		free1D_vec_d_(S, morsBoundbuf_vec_d);
		free1D_vec_d_(S, pathCountbuf_vec_d);
		free1D_vec_d_(S, chunkCritNum_vec_d);
		free1D_vec_d_(S, bndmat_vec_d);
		free1D_vec_d_(S, vals_vec_d);
		free1D_vec_d_(S, offsets_vec_d);
		// Destroy streams / events
		free_cudaStream_vec(streams, S);
		free_cudaEvent_vec(events, 2 * S);
	}

	// Preprocessing functions
	void proc_size();
	void upload_info_2constant();
	// Data fetch function
	void fetch_chunk3D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
	void fetch_chunk3D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, ushort_ bufID, float& minValue, cudaStream_t& stream);
	// Main algorithm
	void run_frmArr(type* src, PH3D_Batch_multiThread<type>& ph, ushort_ fileNum);
	void run_frmFile(const std::vector<std::string>& filenames, const std::string& datatype_, PH3D_Batch_multiThread<type>& ph, ushort_ fileNum);

	inline uint_ slot(uint_ f, uint_ bufID) const { return f * strmCnt + bufID; }
	void fill_halo(type* buf, uint_ sliceFrom, uint_ sliceTo, uint_ rowFrom, uint_ rowTo) const;

	// Debug functions
	uint3 return_blockDims() { return blockSize; }
	uint3 return_chunkDims() { return chunkSize; }

	void compute(const std::vector<std::string>& filenames, const std::string& datatype) {
		const uint_ n = (uint_)std::min<size_t>(filenames.size(), batchSize);
		const uint_ n1 = std::min<uint_>(n, halfSize_), n2 = n - n1;
		std::vector<std::string> part1(filenames.begin(), filenames.begin() + n1);
		std::vector<std::string> part2(filenames.begin() + n1, filenames.begin() + n);
		compute_impl(n1, n2,
			[&]() { run_frmFile(part1, datatype, *phs_[0], (ushort_)n1); },
			[&]() { run_frmFile(part2, datatype, *phs_[1], (ushort_)n2); });
	}
	void compute(type* src, ushort_ fileNum) {
		const uint_ n = std::min<uint_>(fileNum, batchSize);
		const uint_ n1 = std::min<uint_>(n, halfSize_), n2 = n - n1;
		const ull_ imgElems = 1ULL * imgSize.x * imgSize.y * imgSize.z;
		compute_impl(n1, n2,
			[&]() { run_frmArr(src, *phs_[0], (ushort_)n1); },
			[&]() { run_frmArr(src + n1 * imgElems, *phs_[1], (ushort_)n2); });
	}

	// Results of the last compute(): fileIdx in [0, fileNum()), 9 floats per pair
	uint_  fileNum() const { return partNum_[0] + partNum_[1]; }
	uint_  pairNum(uint_ fileIdx) { return fileIdx < partNum_[0] ? phs_[0]->return_pairNum(fileIdx) : phs_[1]->return_pairNum(fileIdx - partNum_[0]); }
	float* result(uint_ fileIdx) { return fileIdx < partNum_[0] ? phs_[0]->return_results(fileIdx) : phs_[1]->return_results(fileIdx - partNum_[0]); }
	// Free results of the last compute()
	void reset() { phs_[0]->reset(); phs_[1]->reset(); partNum_[0] = partNum_[1] = 0; }

private:
	// Basic parameters
	DeviceProp										prop;						// properties of the chosen device
	bool											debug;						// run the program in debug mode
	bool											verbose;					// output program information
	ushort_											strmCnt;					// number of CUDA streams per file
	ushort_											batchSize;
	uint3											imgSize;					// Height, width and depth of the input
	uint3											imgSizeX;					// 2 x imgSize + 1
	uint3											chunkSizeX;					// 2 x chunkSize + 1
	uint3											blockSize;					// size of block
	uint3											blockSizeX;					// grid size of block
	uint_											blockNum;					// number of blocks per chunk
	uint_											chunkNum_h;					// number of chunks divided in h direction
	uint_											chunkNum_d;					// number of chunks divided in d direction
	uint_											chunkNum;					// total number of chunks in the input
	uint_											maxDim2Compute;				// maximum dimension to compute persistent homology
	std::vector<cudaMemcpy3DParms>					cpyParams_vec;				// parameters for cudaMemcpy3D, one per slot
	// Basic parameters: Hyper-parameters
	uint3											chunkSize;					// Suggested chunk size EXCLUDING halo/apron
	uint3											chunkSize_atCreation;		// Chunk size determined at creation
	uint_											bndmat_num;					// Size of buffer each block uses to store critical pairs

	// Host Memory
	std::vector<type*>								chunk_vec_h;				// host memory for input chunks
	std::vector<ulonglong2*>						bndmat_vec_h;				// host memory for critical pair indices
	std::vector<type*>								vals_vec_h;					// host memory for critical pair filtration values
	std::vector<uchar2*>							offsets_vec_h;				// host memory for cell offsets
	// Host memory utility to upload to constant memory
	uint_*											chunkSize_h;				// actual chunk height for each chunk
	uint_*											chunkSize_d;				// actual chunk depth for each chunk
	uint_*											chunkSizeX_h;				// grid chunk height, 2 * chunk height + 1
	uint_*											chunkSizeX_d;				// grid chunk depth, 2 * chunk depth + 1

	// Device memory
	std::vector<cudaArray*>							cuArr_vec;					// device memory for input chunks
	std::vector<cudaTextureObject_t>				texObj_vec;					// cuda texture object binded with cuArr
	std::vector<ushort_*>							match_vec_d;				// device memory for matching grid
	std::vector<uchar_*>							crit_vec_d;					// device memory for critical cell mask
	std::vector<ushort_*>							morsBoundbuf_vec_d;			// buffer for computing Morse boundaries
	std::vector<uint_*>								pathCountbuf_vec_d;			// device memory for path counting
	std::vector<ushort_*>							chunkCritNum_vec_d;			// number of critical cells per block
	std::vector<ulonglong2*>						bndmat_vec_d;				// device memory for critical pair indices
	std::vector<type*>								vals_vec_d;					// device memory for critical pair filtration values
	std::vector<uchar2*>							offsets_vec_d;				// device memory for cell offsets

	// CUDA streams and events
	std::vector<cudaStream_t>						streams;
	std::vector<cudaEvent_t>						events;						// 2 per slot: [2s] H2D done, [2s+1] D2H done

	ctpl::thread_pool								poolFiles;					// per-file fetch / collect
	ctpl::thread_pool								poolRows;					// slice-parallel fill inside fetch_*_multiThread

	ushort_											halfSize_;					// ceil(batchSize/2): capacity of each half
	std::unique_ptr<PH3D_Batch_multiThread<type>>	phs_[2];					// one reducer per half
	uint_											partNum_[2] = { 0, 0 };		// files in each half for the last compute()
	std::future<void>								pending_;

	template <typename Run1, typename Run2>
	void compute_impl(uint_ n1, uint_ n2, Run1&& run1, Run2&& run2) {
		reset();
		partNum_[0] = n1; partNum_[1] = n2;
		if (n1 == 0) return;

		run1();                                                                                 // GPU part 1
		pending_ = std::async(std::launch::async, [this]() { phs_[0]->bndmat_reduction(); });   // CPU part 1 ...
		if (n2 > 0) run2();                                                                     // ... overlaps GPU part 2
		pending_.get();
		if (n2 > 0) phs_[1]->bndmat_reduction();                                                // CPU part 2
	}
};