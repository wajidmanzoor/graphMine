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

struct TimingRecord {
	double loadTime;
	double dev2hostTime;
	double host2devTime;
	double cubiComplexTime;
	double topoSortTime;
	double pathCountTime;

public:
	void reset() {
		loadTime		= 0.0;
		dev2hostTime	= 0.0;
		host2devTime	= 0.0;
		cubiComplexTime = 0.0;
		topoSortTime	= 0.0;
		pathCountTime	= 0.0;
	}

	void printTiming() {
		//printf("==== Timing ====: \n");
		//printf("Load time: %f millisecs\n", loadTime / 1000.0);
		//printf("Dev2Host+Host2Dev: %f secs\n", (dev2hostTime + host2devTime)/1000.0);
		printf("CubiComplex time: %f secs\n", cubiComplexTime / 1000.0);
		printf("TopoSort time: %f secs\n", topoSortTime / 1000.0);
		printf("PathCount time: %f secs\n", pathCountTime / 1000.0);
		//printf("GPU pipeline time: %f secs\n", (cubiComplexTime + topoSortTime + pathCountTime) / 1000.0);
	}
};

// ===== Phat multi-threading class =====
template <typename type>
class PH2D_multiThread {
public:
	PH2D_multiThread(bool, bool);

	~PH2D_multiThread() {
		reset();
	}

	void reset() {
		ind_sorted.clear();
		elements.clear();
		results.clear();

		// Delete buffer
		if (write2HDD && bndMatReduct) (void)std::remove("./bndredbuf.raw");
	}

	void initialize(const uint_& blockNum_, const uint_& bndmat_num_, const uint_& chunkNum_, const uint2& imgSizeX_) {
		/*
			Called at the beginning of every run
		*/
		if (!bndMatReduct) return;

		blockNum = blockNum_;
		bndmat_num = bndmat_num_;
		chunkNum = chunkNum_;
		imgSizeX = imgSizeX_;

		// Boundary relations in RAM
		// Pre-allocate memory space
		uint64_t totalElems = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		if (!write2HDD) elements.reserve(totalElems / 8);
		// Boundary relations in HDD
		else {
			file.close(); file.clear();
			file.open("F:/bndredbuf.raw", std::ios::binary | std::ios::in | std::ios::out);
			if (!file) {
				file.clear();
				file.open("F:/bndredbuf.raw", std::ios::binary | std::ios::out);   // creates it
				file.close();
				file.open("F:/bndredbuf.raw", std::ios::binary | std::ios::in | std::ios::out);
				if (!file) throw std::runtime_error("Failed to open file for writing");
			}

			file.seekp(0, std::ios::end);
			runBase_hddwrite = (uint64_t)file.tellp();

			uint_ header[5] = { chunkNum, blockNum, bndmat_num, imgSizeX.x, imgSizeX.y };
			file.seekp(runBase_hddwrite);
			file.write(reinterpret_cast<const char*>(header), sizeof(unsigned int) * 5);

			uint64_t chunkTotal = uint64_t(blockNum) * uint64_t(bndmat_num);
			const uint64_t totalBytes = uint64_t(chunkNum) * chunkTotal * (sizeof(ulonglong2) + sizeof(type) * 2 + sizeof(uchar2));
			std::cout << "Requiring " << totalBytes / 1073741824.0 << " GB" << std::endl;

			file.seekp(runBase_hddwrite + sizeof(unsigned int) * 5 + totalBytes - 1);
			file.write("", 1);

			offset_vals = runBase_hddwrite + sizeof(unsigned int) * 5 + uint64_t(chunkNum) * chunkTotal * sizeof(ulonglong2);
			offset_offsets = offset_vals + uint64_t(chunkNum) * chunkTotal * sizeof(type) * 2;
			chunkId = 0;
		}
	}

	// Find top-cell that introduces the cell
	void findsource2D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y);
	// Collect boundary relations and filtration values
	void bndmat_collect(const ulonglong2* const bndmat_h, const type* const vals_h, const uchar2* const offsets_h);
	// Boundary maatrix reduction
	double bndmat_reduction();
	// Compute crit ordering
	void sort_crit_by_values();
	// Compute persistent homology
	void compute_ph();
	// Set minimum value
	void set_minValue(float);
	// Gather non-trivial persistence pairs
	void gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);

	// Print results
	void print_results(bool details);
	// Write results to file
	void write_results(const std::string& out_path);
	// Return results
	float* return_results();
	// Return pair number
	uint_ return_pairNum();

	// Accumulate crit-order correspondence on one thread
	void critSort_singleThread(const ull_ startIdx, const ull_ endIdx)
	{
		for (ull_ i = startIdx; i < endIdx; i++)
			elements[ind_sorted[i]].first.order = i;
	}

	// Setup boundary matrix on one thread
	void setup_bndmat_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>& bndmat,
		const ull_											startIdx,
		const ull_											endIdx
	)
	{
		for (ull_ i = startIdx; i < endIdx; i++) {
			const ull_ idx = ind_sorted[i];
			auto it = elements.find(idx);
			auto& neighbors = it->second.second;
			if (neighbors.empty()) continue;

			for (ull_& v : neighbors) v = elements[v].first.order;
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
		const ull_											endIdx
	)
	{
		std::vector<float> resLocal;
		resLocal.reserve((endIdx - startIdx) * 7);
		uint_ x1, y1, x2, y2, dim;

		for (ull_ i = startIdx; i < endIdx; i++) {
			if (bndmat.is_empty(i)) continue;

			ull_ birth = bndmat.get_max_index(i);
			auto& birthElem = elements[ind_sorted[birth]].first;
			auto& deathElem = elements[ind_sorted[i]].first;
			if (birthElem.value == deathElem.value) continue;

			ull_ birthIdx = ind_sorted[birth];
			ull_ deathIdx = ind_sorted[i];
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
		results.insert(results.end(), resLocal.begin(), resLocal.end());
	}

	bool ifbndMatReduct() { return bndMatReduct; }

private:
	bool					bndMatReduct;
	bool					write2HDD;

	uint_					blockNum;
	uint_					bndmat_num;
	uint_					chunkNum;
	uchar_					numCores;
	uint2					imgSizeX;
	std::mutex				mtx;

	// Boundary relation in HDD
	std::ofstream			file;
	ushort_					chunkId;
	uint64_t				offset_vals;
	uint64_t				offset_offsets;
	uint64_t				runBase_hddwrite;

	std::vector<ull_>		ind_sorted;
	std::unordered_map<ull_, std::pair<Element<type>, std::vector<ull_>>> elements;
	// Persistent homology results
	float					minValue;
	std::vector<float>		results;
};

template <typename type>
class PH3D_multiThread {
public:
	PH3D_multiThread(bool, bool);

	~PH3D_multiThread() {
		reset();
	}

	void reset() {
		ind_sorted.clear();
		elements.clear();
		results.clear();
		
		// Delete buffer
		if (write2HDD && bndMatReduct) (void)std::remove("./bndredbuf.raw");
	}

	void initialize(const uint_& blockNum_, const uint_& bndmat_num_, const uint_& chunkNum_, const uint3& imgSizeX_) {
		/*
			Called at the beginning of every run
		*/
		if (!bndMatReduct) return;

		blockNum	= blockNum_;
		bndmat_num	= bndmat_num_;
		chunkNum    = chunkNum_;
		imgSizeX	= imgSizeX_;

		// Boundary relations in RAM
		// Pre-allocate memory space
		uint64_t totalElems = uint64_t(blockNum) * uint64_t(bndmat_num) * uint64_t(chunkNum);
		if (!write2HDD) elements.reserve(totalElems / 8);
		// Boundary relations in HDD
		else {
			file.close(); file.clear();
			file.open("./bndredbuf.raw", std::ios::binary | std::ios::in | std::ios::out);
			if (!file) {
				file.clear();
				file.open("./bndredbuf.raw", std::ios::binary | std::ios::out);   // creates it
				file.close();
				file.open("./bndredbuf.raw", std::ios::binary | std::ios::in | std::ios::out);
				if (!file) throw std::runtime_error("Failed to open file for writing");
			}

			file.seekp(0, std::ios::end);
			runBase_hddwrite = (uint64_t)file.tellp();

			uint_ header[6] = { chunkNum, blockNum, bndmat_num, imgSizeX.x, imgSizeX.y, imgSizeX.z };
			file.seekp(runBase_hddwrite);
			file.write(reinterpret_cast<const char*>(header), sizeof(unsigned int) * 6);

			uint64_t chunkTotal = uint64_t(blockNum) * uint64_t(bndmat_num);
			const uint64_t totalBytes = uint64_t(chunkNum) * chunkTotal * (sizeof(ulonglong2) + sizeof(type) * 2 + sizeof(uchar2));
			std::cout << "Requiring " << totalBytes / 1073741824.0 << " GB" << std::endl;

			file.seekp(runBase_hddwrite + sizeof(unsigned int) * 6 + totalBytes - 1);
			file.write("", 1);

			offset_vals = runBase_hddwrite + sizeof(unsigned int) * 6 + uint64_t(chunkNum) * chunkTotal * sizeof(ulonglong2);
			offset_offsets = offset_vals + uint64_t(chunkNum) * chunkTotal * sizeof(type) * 2;
			chunkId = 0;
		}
	}

	// Find top-cell that introduces the cell
	void findsource3D_h(ull_ idx, uchar_ offset, uint_& x, uint_& y, uint_& z);
	// Collect boundary relations and filtration values
	void bndmat_collect(const ulonglong2* const bndmat_h, const type* const vals_h, const uchar2* const offsets_h);
	// Boundary maatrix reduction
	double bndmat_reduction();
	// Compute crit ordering
	void sort_crit_by_values();
	// Compute persistent homology
	void compute_ph();
	// Set minimum value
	void set_minValue(float);
	// Gather non-trivial persistence pairs
	void gather_nontrivial_pairs(phat::boundary_matrix<phat::bit_tree_pivot_column>&);

	// Print results
	void print_results(bool details);
	// Write results to file
	void write_results(const std::string& out_path);
	// Return results
	float* return_results();
	// Return pair number
	uint_ return_pairNum();

	// Accumulate crit-order correspondence on one thread
	void critSort_singleThread(const ull_ startIdx, const ull_ endIdx)
	{
		for (ull_ i = startIdx; i < endIdx; i++)
			elements[ind_sorted[i]].first.order = i;
	}

	// Setup boundary matrix on one thread
	void setup_bndmat_SingleThread(
		phat::boundary_matrix<phat::bit_tree_pivot_column>&	bndmat,
		const ull_											startIdx,
		const ull_											endIdx
	)
	{
		const uint_ planeSize = imgSizeX.x * imgSizeX.y;
		for (ull_ i = startIdx; i < endIdx; i++) {
			const ull_ idx = ind_sorted[i];
			auto it = elements.find(idx);
			auto& neighbors = it->second.second;
			if (neighbors.empty()) continue;

			for (ull_& v : neighbors) v = elements[v].first.order;
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
		phat::boundary_matrix<phat::bit_tree_pivot_column>&	bndmat,
		const ull_											startIdx,
		const ull_											endIdx
	)
	{
		std::vector<float> resLocal;
		resLocal.reserve((endIdx - startIdx) * 9);
		const uint_ planeSize = imgSizeX.x * imgSizeX.y;
		uint_ x1, y1, z1, x2, y2, z2, dim;

		for (ull_ i = startIdx; i < endIdx; i++) {
			if (bndmat.is_empty(i)) continue;

			ull_ birth		= bndmat.get_max_index(i);
			auto& birthElem = elements[ind_sorted[birth]].first;
			auto& deathElem = elements[ind_sorted[i]].first;
			if (birthElem.value == deathElem.value) continue;

			ull_ birthIdx	= ind_sorted[birth];
			ull_ deathIdx	= ind_sorted[i];
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
		results.insert(results.end(), resLocal.begin(), resLocal.end());
	}

	bool ifbndMatReduct() { return bndMatReduct; }

private:
	bool					bndMatReduct;
	bool					write2HDD;

	uint_					blockNum;
	uint_					bndmat_num;
	uint_					chunkNum;
	uchar_					numCores;
	uint3					imgSizeX;
	std::mutex				mtx;

	// Boundary relation in HDD
	std::ofstream			file;
	ushort_					chunkId;
	uint64_t				offset_vals;
	uint64_t				offset_offsets;
	uint64_t				runBase_hddwrite;

	std::vector<ull_>		ind_sorted;
	std::unordered_map<ull_, std::pair<Element<type>, std::vector<ull_>>> elements;
	// Persistent homology results
	float					minValue;
	std::vector<float>		results;
};

template <typename type>
class TopoGPU2D {
public:
	TopoGPU2D(
		uint2		imgSize_,
		uint_		bndmat_num_,
		uint2		blockSize_ = uint2{ 0, 0 },
		int			deviceID = -1,
		bool		debug_ = false,
		bool		verbose_ = false
	) :
		imgSize(imgSize_), blockSize(blockSize_), bndmat_num(bndmat_num_), img_decoded_h(nullptr), img_decoded_dt(-1), debug(debug_), verbose(verbose_) {
		// Choose GPU device
		find_and_query_device(prop, deviceID, debug, verbose);
		// Decide chunk and block sizes
		choose_chunk_block_size2D<type>(imgSize, prop, chunkSize, blockSize, make_uint2(0, 0));
		chunkSize_atCreation = chunkSize;
		proc_size();

		// printf("Chunk size: %d %d\n", chunkSize.x, chunkSize.y);
		// printf("Block Size: %d %d\n", blockSize.x, blockSize.y);

		// Allocate host memory
		chunk_vec_h			= malloc1D_vec_pin_<type>(strmCnt, PRODUCT2(chunkSize.x + 4, chunkSize.y + 2));
		bndmat_vec_h		= malloc1D_vec_pin_<ulonglong2>(strmCnt, blockNum * bndmat_num);
		vals_vec_h			= malloc1D_vec_pin_<type>(strmCnt, 2 * blockNum * bndmat_num);
		offsets_vec_h		= malloc1D_vec_pin_<uchar2>(strmCnt, blockNum * bndmat_num);
		chunkSize_h			= malloc1D_h_<uint_>(chunkNum);
		chunkSizeX_h		= malloc1D_h_<uint_>(chunkNum);
		// Allocate device memory
		cuArr_vec			= malloc_cudaArray2D_vec<type>(strmCnt, chunkSize.x + 4, chunkSize.y + 2);
		texObj_vec			= create_cuTexObj_vec(strmCnt, cuArr_vec);
		match_vec_d			= malloc1D_vec_d_<uchar_>(strmCnt, chunkSizeX.x * chunkSizeX.y);
		crit_vec_d			= malloc1D_vec_d_<uchar_>(strmCnt, chunkSizeX.x * chunkSizeX.y);
		morsBoundbuf_vec_d	= malloc1D_vec_d_<ushort_>(strmCnt, blockNum * blockSizeX.x * blockSizeX.y * 4);
		pathCountbuf_vec_d	= malloc1D_vec_d_<uint_>(strmCnt, blockNum * blockSizeX.x * blockSizeX.y * PATHCNT_BUF_SIZE);
		chunkCritNum_vec_d	= malloc1D_vec_d_<ushort_>(strmCnt, blockNum);
		bndmat_vec_d		= malloc1D_vec_d_<ulonglong2>(strmCnt, blockNum * bndmat_num);
		vals_vec_d			= malloc1D_vec_d_<type>(strmCnt, 2 * blockNum * bndmat_num);
		offsets_vec_d		= malloc1D_vec_d_<uchar2>(strmCnt, blockNum * bndmat_num);
		// Create CUDA events and streams
		events				= create_cudaEvent_vec(strmCnt);
		timings				= create_cudaEventTiming_vec(7 * strmCnt);
		streams				= create_cudaStream_vec(strmCnt);
	}

	~TopoGPU2D() {
		// Release host memory
		free1D_vec_pin(strmCnt, chunk_vec_h);
		free1D_vec_pin(strmCnt, bndmat_vec_h);
		free1D_vec_pin(strmCnt, vals_vec_h);
		free1D_vec_pin(strmCnt, offsets_vec_h);
		free(chunkSize_h);
		free(chunkSizeX_h);

		// Release device memory
		free_cuTexObj_vec(strmCnt, texObj_vec);
		free_cudaArray_vec(strmCnt, cuArr_vec);
		free1D_vec_d_(strmCnt, match_vec_d);
		free1D_vec_d_(strmCnt, crit_vec_d);
		free1D_vec_d_(strmCnt, morsBoundbuf_vec_d);
		free1D_vec_d_(strmCnt, pathCountbuf_vec_d);
		free1D_vec_d_(strmCnt, chunkCritNum_vec_d);
		free1D_vec_d_(strmCnt, bndmat_vec_d);
		free1D_vec_d_(strmCnt, vals_vec_d);
		free1D_vec_d_(strmCnt, offsets_vec_d);
		// Destroy events and streams
		free_cudaEvent_vec(events, strmCnt);
		free_cudaEvent_vec(timings, 7 * strmCnt);
		free_cudaStream_vec(streams, strmCnt);

		if (img_decoded_h) { stbi_image_free(img_decoded_h); img_decoded_h = nullptr; }
	}

	// Set image size and chunk size
	void configure(uint2 imgSize_, uint_ maxDim = 2);
	// Preprocessing functions
	void proc_size();
	void upload_info_2constant();
	// Data fetch function
	void fetch_chunk2D_frmArr(type* src, ushort_ chunkID, ushort_ bufID, cudaStream_t& stream);
	void fetch_chunk2D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
	void fetch_chunk2D_fromImage_multiThread(const std::string& path, int datatype, ushort_	chunkID, uchar_	bufID, cudaStream_t& stream);
	// Main algorithm
	void run_frmArr(type* src, PH2D_multiThread<type>& ph);
	void run_frmFile(const std::string& filename, const std::string& datatype_, PH2D_multiThread<type>& ph);

	// Timing functions
	double get_loadTime() { return timing.loadTime; }
	double get_dev2hostTime() { return timing.dev2hostTime; }
	double get_host2devTime() { return timing.host2devTime; }
	double get_cubiComplexTime() { return timing.cubiComplexTime; }
	double get_topoSortTime() { return timing.topoSortTime; }
	double get_pathCountTime() { return timing.pathCountTime; }
	void printDetailedTiming() { timing.printTiming(); }

	// Debug functions
	uint2 return_blockDims() { return blockSize; }
	uint2 return_chunkDims() { return chunkSize; }

private:
	// Basic parameters
	DeviceProp								prop;							// properties of the chosen device
	bool									debug;							// run the program in debug mode
	bool									verbose;						// output program information
	int										num_sms;
	ushort_									strmCnt;
	uint2									imgSize;						// Height and width of the input
	uint2									imgSizeX;						// (2 x imgSize.x + 1), (2 x imgSize.y + 1), (2 x imgSize.z + 1)
	uint_									blockNum;
	uint2									blockSize;
	uint2									blockSizeX;						// 2 x blockSize + 1
	uint_									chunkNum;						// total number of chunks in the input
	uint2									chunkSizeX;						// (2 x chunkSize.x + 1), (2 x imgSize.y + 1), (2 x chunkSize.z + 1)
	uint_									maxDim2Compute;					// maximum dimension to compute persistent homology
	TimingRecord							timing;							// timing record
	// Basic parameters: Hyper-parameters
	uint2									chunkSize;						// Suggested chunk size EXCLUDING halo/apron
	uint2									chunkSize_atCreation;			// Chunk size determined at creation, used for batch mode
	uint_									bndmat_num;						// Size of buffer each block uses to store critical pairs. Smaller size could cause FAILURE!
	float									minValue;						// Minimum value from input for essential persistence pair
	// Coded input (jpg/png etc.) use
	void*									img_decoded_h;
	std::string								img_decoded_path;
	int										img_decoded_dt;

	// Host Memory
	std::vector<type*>						chunk_vec_h;					// host memory for input chunks
	std::vector<ulonglong2*>				bndmat_vec_h;					// host memory for boundary matrix used in topo order
	std::vector<type*>						vals_vec_h;						// host memory for critical pair filtration values
	std::vector<uchar2*>					offsets_vec_h;					// host memory for cell offsets
	// Host memory utility to upload to constant memory
	uint_*									chunkSize_h;					// actual chunk height for each chunk, width remains the same
	uint_*									chunkSizeX_h;					// grid chunk height for each chunk, 2 * chunk_size + 1

	// Device memory
	std::vector<cudaArray*>					cuArr_vec;						// device memory for input chunks
	std::vector<cudaTextureObject_t>		texObj_vec;						// cuda texture object binded with cuArr
	std::vector<uchar_*>					match_vec_d;					// device memory for matching grid
	std::vector<uchar_*>					crit_vec_d;						// device memory for critical cell mask
	std::vector<ushort_*>					morsBoundbuf_vec_d;				// device memory for topological order computation buffer
	std::vector<uint_*>						pathCountbuf_vec_d;				// device memory for path counting computation buffer
	std::vector<ushort_*>					chunkCritNum_vec_d;				// device memory to store number of critical cells for each block in each chunk
	std::vector<ulonglong2*>				bndmat_vec_d;					// device memory for boundary matrix used in topo order
	std::vector<type*>						vals_vec_d;						// device memory for critical pair filtration values
	std::vector<uchar2*>					offsets_vec_d;					// device memory for cell offsets

	// CUDA streams and events
	std::vector<cudaEvent_t>				events;							// events for synchronization
	std::vector<cudaEvent_t>				timings;						// events to record detailed timing
	std::vector<cudaStream_t>				streams;						// CUDA streams
};

template <typename type>
class TopoGPU3D {
public:
	TopoGPU3D(
		uint3		imgSize_,
		uint_		bndmat_num_,
		uint3		blockSize_  = uint3{ 0, 0, 0 },
		int			deviceID	= -1,
		bool		debug_		= false,
		bool		verbose_	= false
	) :
		imgSize(imgSize_), blockSize(blockSize_), bndmat_num(bndmat_num_), debug(debug_), verbose(verbose_) {
		// Choose GPU device
		find_and_query_device(prop, deviceID, debug, verbose);
		// Decide chunk and block sizes
		choose_chunk_block_size<type>(imgSize, prop, chunkSize, blockSize, make_uint3(0, 0, 0));
		chunkSize_atCreation = chunkSize;
		proc_size();

		// printf("Chunk size: %d %d %d\n", chunkSize.x, chunkSize.y, chunkSize.z);
		// printf("Block Size: %d %d %d\n", blockSize.x, blockSize.y, blockSize.z);

		// Allocate host memory
		chunk_vec_h			= malloc1D_vec_pin_<type>		(strmCnt, PRODUCT3(chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4));
		bndmat_vec_h		= malloc1D_vec_pin_<ulonglong2>	(strmCnt, blockNum * bndmat_num);
		vals_vec_h			= malloc1D_vec_pin_<type>		(strmCnt, 2 * blockNum * bndmat_num);
		offsets_vec_h		= malloc1D_vec_pin_<uchar2>		(strmCnt, blockNum * bndmat_num);
		chunkSize_h			= malloc1D_h_<uint_>			(chunkNum_h);
		chunkSize_d			= malloc1D_h_<uint_>			(chunkNum_d);
		chunkSizeX_h		= malloc1D_h_<uint_>			(chunkNum_h);
		chunkSizeX_d		= malloc1D_h_<uint_>			(chunkNum_d);
		// Allocate device memory
		cuArr_vec			= malloc_cudaArray3D_vec<type>	(strmCnt, chunkSize.x + 4, chunkSize.y + 2, chunkSize.z + 4);
		texObj_vec			= create_cuTexObj_vec			(strmCnt, cuArr_vec);
		match_vec_d			= malloc1D_vec_d_<ushort_>		(strmCnt, chunkSizeX.x * chunkSizeX.y * chunkSizeX.z);
		crit_vec_d			= malloc1D_vec_d_<uchar_>		(strmCnt, chunkSizeX.x * chunkSizeX.y * chunkSizeX.z);
		morsBoundbuf_vec_d  = malloc1D_vec_d_<ushort_>		(strmCnt, blockNum * blockSizeX.x * blockSizeX.y * blockSizeX.z * 4);
		pathCountbuf_vec_d  = malloc1D_vec_d_<uint_>		(strmCnt, blockNum * blockSizeX.x * blockSizeX.y * blockSizeX.z * PATHCNT_BUF_SIZE);
		chunkCritNum_vec_d  = malloc1D_vec_d_<ushort_>		(strmCnt, blockNum);
		bndmat_vec_d        = malloc1D_vec_d_<ulonglong2>	(strmCnt, blockNum * bndmat_num);
		vals_vec_d 			= malloc1D_vec_d_<type>			(strmCnt, 2 * blockNum * bndmat_num);
		offsets_vec_d		= malloc1D_vec_d_<uchar2>		(strmCnt, blockNum * bndmat_num);
		// Create CUDA events and streams
		events				= create_cudaEvent_vec(strmCnt);
		timings				= create_cudaEventTiming_vec(7 * strmCnt);
		streams				= create_cudaStream_vec(strmCnt);
		cpyParams_vec.assign(strmCnt, cudaMemcpy3DParms{});
	}

	~TopoGPU3D() {
		clear();
	}

	void clear() {
		cpyParams_vec.clear();
		// Release host memory
		free1D_vec_pin(strmCnt, chunk_vec_h);
		free1D_vec_pin(strmCnt, bndmat_vec_h);
		free1D_vec_pin(strmCnt, vals_vec_h);
		free1D_vec_pin(strmCnt, offsets_vec_h);
		free(chunkSize_h);
		free(chunkSize_d);
		free(chunkSizeX_h);
		free(chunkSizeX_d);
		// Release device memory
		free_cuTexObj_vec(strmCnt, texObj_vec);
		free_cudaArray_vec(strmCnt, cuArr_vec);
		free1D_vec_d_(strmCnt, match_vec_d);
		free1D_vec_d_(strmCnt, crit_vec_d);
		free1D_vec_d_(strmCnt, morsBoundbuf_vec_d);
		free1D_vec_d_(strmCnt, pathCountbuf_vec_d);
		free1D_vec_d_(strmCnt, chunkCritNum_vec_d);
		free1D_vec_d_(strmCnt, bndmat_vec_d);
		free1D_vec_d_(strmCnt, vals_vec_d);
		free1D_vec_d_(strmCnt, offsets_vec_d);
		// Destroy events and streams
		free_cudaEvent_vec(events, strmCnt);
		free_cudaEvent_vec(timings, 7 * strmCnt);
		free_cudaStream_vec(streams, strmCnt);
	}

	// Set image size and chunk size
	void configure(uint3 imgSize_, uint_ maxDim = 3);
	// Preprocessing functions
	void proc_size();
	void upload_info_2constant();
	// Data fetch function
	void fetch_chunk3D_frmArr(type* src, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
	void fetch_chunk3D_fromFile_multiThread(const std::string& path, int datatype, ushort_ chunkID, uchar_ bufID, cudaStream_t& stream);
	// Main algorithm
	void run_frmArr(type* src, PH3D_multiThread<type>& ph);
	void run_frmFile(const std::string& filename, const std::string& datatype_, PH3D_multiThread<type>& ph);

	// Timing functions
	double get_loadTime()			{ return timing.loadTime; }
	double get_dev2hostTime()		{ return timing.dev2hostTime; }
	double get_host2devTime()		{ return timing.host2devTime; }
	double get_cubiComplexTime()	{ return timing.cubiComplexTime; }
	double get_topoSortTime()		{ return timing.topoSortTime; }
	double get_pathCountTime()		{ return timing.pathCountTime; }
	void printDetailedTiming()		{ timing.printTiming(); }

	// Debug functions
	uint3 return_blockDims() { return blockSize; }
	uint3 return_chunkDims() { return chunkSize; }

private:
	// Basic parameters
	DeviceProp							prop;						// properties of the chosen device
	bool								debug;						// run the program in debug mode
	bool								verbose;					// output program information
	ushort_								strmCnt;					// number of CUDA streams
	uint3								imgSize;					// Height, width and depth of the input chunk
	uint3                               imgSizeX;                   // (2 x imgSize.x + 1), (2 x imgSize.y + 1), (2 x imgSize.z + 1)
	uint3								chunkSizeX;					// (2 x chunkSize.x + 1), (2 x imgSize.y + 1), (2 x chunkSize.z + 1)
	uint3								blockSize;					// size of block
	uint3								blockSizeX;					// grid size of block
	uint_								blockNum;					// number of blocks per chunk
	uint_								chunkNum_h;					// number of chunks divided in h direction
	uint_								chunkNum_d;					// number of chunks divided in d direction
	uint_								chunkNum;					// total number of chunks in the input
	uint_								maxDim2Compute;				// maximum dimension to compute persistent homology
	std::vector<cudaMemcpy3DParms>		cpyParams_vec;				// parameters for cudaMemcpy3D
	TimingRecord                        timing;                     // timing record
	// Basic parameters: Hyper-parameters
	uint3								chunkSize;					// Suggested chunk size EXCLUDING halo/apron
	uint3								chunkSize_atCreation;		// Chunk size determined at creation, used for batch mode
	uint_								bndmat_num;					// Size of buffer each block uses to store critical pairs. Smaller size could cause FAILURE!
	float								minValue;					// Minimum value from input for essential persistence pair

	// Host Memory
	std::vector<type*>					chunk_vec_h;				// host memory for input chunks
	std::vector<ulonglong2*>			bndmat_vec_h;				// host memory for critical pair indices in the original volume
	std::vector<type*>					vals_vec_h;					// host memory for critical pair filtration values
	std::vector<uchar2*>				offsets_vec_h;				// host memory for cell offsets
	// Host memory utility to upload to constant memory
	uint_*								chunkSize_h;				// actual chunk height for each chunk, width remains the same
	uint_*								chunkSize_d;				// actual chunk depth for each chunk, width remains the same
	uint_*								chunkSizeX_h;				// grid chunk height for each chunk, 2 * chunk height + 1
	uint_*								chunkSizeX_d;				// grid chunk depth for each chunk, 2 * chunk depth + 1
	
	// Device memory
	std::vector<cudaArray*>				cuArr_vec;					// device memory for input chunks
	std::vector<cudaTextureObject_t>	texObj_vec;					// cuda texture object binded with cuArr
	std::vector<ushort_*>				match_vec_d;				// device memory for matching grid
	std::vector<uchar_*>				crit_vec_d;					// device memory for critical cell mask
	std::vector<ushort_*>				morsBoundbuf_vec_d;			// buffer in device memory for computing Morse boundaries
	std::vector<uint_*>					pathCountbuf_vec_d;			// device memory for path counting computation buffer
	std::vector<ushort_*>				chunkCritNum_vec_d;			// device memory to store number of critical cells for each block in each chunk
	std::vector<ulonglong2*>			bndmat_vec_d;				// device memory for critical pair indices in the original volume
	std::vector<type*>					vals_vec_d;					// device memory for critical pair filtration values
	std::vector<uchar2*>				offsets_vec_d;				// device memory for cell offsets

	// CUDA streams and events
	std::vector<cudaEvent_t>			events;						// events for synchronization
	std::vector<cudaEvent_t>			timings;					// events to record detailed timing
	std::vector<cudaStream_t>			streams;					// CUDA streams
};