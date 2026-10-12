#include "fileIO.h"
#include "ctpl_stl.h"

#include "stb_image.h"
#include <iostream>
#include <fstream>
#include <cstring>

template <typename T1, typename T2>
void readArrayFromBin_singleThread(const std::string& filename, T2*& data, const uint_& fileOffset, const uint_& size, const uint_& dst, bool& overflow) {
	/*
		Descriptions: function executed by each thread. Load a chunk of data from a file.
		@filePath: full path to a file.
		@data: the array to be filled.
		@fileOffset: the offset to read from the file for this thread.
		@size: the size of the chunk to be read.
		@dst: the offset to write to the array for this thread.
	*/
	std::ifstream in(filename.c_str(), std::ios::binary);
	if (!in) { std::cout << "Error: readArrayFromBin_singleThread failure!" << std::endl; exit(1); }
	in.seekg(fileOffset * sizeof(T1));

	const bool sameType = std::is_same<T1, T2>::value;
	if (sameType) {
		in.read(reinterpret_cast<char*>(&data[dst]), size * sizeof(T1));
		for (uint_ i = 0; i < size; ++i) if (data[dst + i] == std::numeric_limits<T1>::max()) { overflow = true; break; }
	}
	else {
		T1 value;
		for (uint_ i = 0; i < size; ++i) {
			in.read(reinterpret_cast<char*>(&value), sizeof(T1));
			data[dst + i] = static_cast<T2>(value);
		}
	}
	in.close();
}

template <typename T1, typename T2>
void readArrayFromImg_singleThread(const T1* imgData, T2*& data, const uint_& srcOffset, const uint_& size, const uint_& dst, bool& overflow) {
	/*
		Descriptions: function executed by each thread. Copy/convert a chunk of
		decoded image data into the destination array.
		@imgData: decoded image buffer (1 channel, row-major).
		@data: the array to be filled.
		@srcOffset: the offset to read from the decoded buffer for this thread.
		@size: the size of the chunk to be copied.
		@dst: the offset to write to the array for this thread.
	*/
	const bool sameType = std::is_same<T1, T2>::value;
	if (sameType) {
		memcpy(&data[dst], &imgData[srcOffset], size * sizeof(T1));
		for (uint_ i = 0; i < size; ++i) if (data[dst + i] == std::numeric_limits<T1>::max()) { overflow = true; break; }
	}
	else {
		for (uint_ i = 0; i < size; ++i)
			data[dst + i] = static_cast<T2>(imgData[srcOffset + i]);
	}
}

template <typename T1, typename T2>
T2* readArrayFromBin2D_multiThread(const std::string& filename, const uint2& imgSize) {
	/*
		Read an array of numbers from binary file using multi threading
		@imgSize: x(height), y(width), z(depth)
	*/
	// Configure multi-threading parameters
	uint_ num_cores = std::thread::hardware_concurrency();
	if (num_cores > imgSize.x) num_cores = imgSize.x;
	ctpl::thread_pool tp(num_cores);
	uint_ slicePerThread = iDivUp(imgSize.x, num_cores);
	std::vector<char> overflowFlags(num_cores, 0);

	// Launch threads
	uint_ toSlice, readSize, offset;
	uint_ count = imgSize.x * imgSize.y;
	T2* numbers = new T2[count];

	for (uint_ i = 0; i < num_cores; i++) {
		uint_ idx = i;
		toSlice = std::min((i + 1) * slicePerThread, imgSize.x);
		readSize = (toSlice - i * slicePerThread) * imgSize.y;
		offset = i * slicePerThread * imgSize.y;
		tp.push(
			[&, idx, fileOffset = offset, size = readSize](const uint_&) -> void {
				bool overflow = false;
				readArrayFromBin_singleThread<T1, T2>(filename, numbers, fileOffset, size, fileOffset, overflow);
				if (overflow) overflowFlags[idx] = 1;
			});
		if (toSlice == imgSize.x) break;
	}
	tp.stop(true);

	std::cout << "Read in " << count << " numbers." << std::endl;
	for (char flag : overflowFlags) if (flag == 1) {
		printf("Error: Input data contains maximum value for value type T1, padded chunk will not have maximum value in the apron. Cast input to higher precision data type.\n");
		exit(1);
	}
	return numbers;
}
template uchar_* readArrayFromBin2D_multiThread<uchar_, uchar_>(const std::string& filename, const uint2& imgSize);
template ushort_* readArrayFromBin2D_multiThread<ushort_, ushort_>(const std::string& filename, const uint2& imgSize);
template int* readArrayFromBin2D_multiThread<int, int>(const std::string& filename, const uint2& imgSize);
template float* readArrayFromBin2D_multiThread<uchar_, float>(const std::string& filename, const uint2& imgSize);
template float* readArrayFromBin2D_multiThread<ushort_, float>(const std::string& filename, const uint2& imgSize);
template float* readArrayFromBin2D_multiThread<float, float>(const std::string& filename, const uint2& imgSize);
template int* readArrayFromBin2D_multiThread<uchar_, int>(const std::string& filename, const uint2& imgSize);
template int* readArrayFromBin2D_multiThread<ushort_, int>(const std::string& filename, const uint2& imgSize);
template ushort_* readArrayFromBin2D_multiThread<uchar_, ushort_>(const std::string& filename, const uint2& imgSize);

template <typename T1, typename T2>
T2* readArrayFromImg2D_multiThread(const std::string& filename, const uint2& imgSize) {
	/*
		Read an array of numbers from a .jpg/.png image using multi threading.
		Decode is done once (sequential); the copy/convert is multi-threaded.
		@imgSize: x(height), y(width)
	*/
	// Decode the whole image once (forced to 1 channel / grayscale)
	int w = 0, h = 0, ch = 0;
	void* decoded = nullptr;
	if (sizeof(T1) == 1)       decoded = stbi_load(filename.c_str(), &w, &h, &ch, 1);
	else if (sizeof(T1) == 2)  decoded = reinterpret_cast<void*>(stbi_load_16(filename.c_str(), &w, &h, &ch, 1));
	else { std::cout << "Error: readArrayFromImg2D_multiThread: T1 must be uchar_ or ushort_ (images decode to 8/16-bit)!" << std::endl; exit(1); }

	if (!decoded) { std::cout << "Error: readArrayFromImg2D_multiThread: image load failure (" << stbi_failure_reason() << ")!" << std::endl; exit(1); }
	if (static_cast<uint_>(h) != imgSize.x || static_cast<uint_>(w) != imgSize.y) {
		std::cout << "Error: readArrayFromImg2D_multiThread: image size (" << h << " x " << w
			<< ") does not match imgSize (" << imgSize.x << " x " << imgSize.y << ")!" << std::endl;
		exit(1);
	}
	const T1* imgData = static_cast<const T1*>(decoded);

	// Configure multi-threading parameters
	uint_ num_cores = std::thread::hardware_concurrency();
	if (num_cores > imgSize.x) num_cores = imgSize.x;
	ctpl::thread_pool tp(num_cores);
	uint_ slicePerThread = iDivUp(imgSize.x, num_cores);
	std::vector<char> overflowFlags(num_cores, 0);

	// Launch threads
	uint_ toSlice, readSize, offset;
	uint_ count = imgSize.x * imgSize.y;
	T2* numbers = new T2[count];

	for (uint_ i = 0; i < num_cores; i++) {
		uint_ idx = i;
		toSlice = std::min((i + 1) * slicePerThread, imgSize.x);
		readSize = (toSlice - i * slicePerThread) * imgSize.y;
		offset = i * slicePerThread * imgSize.y;
		tp.push(
			[&, idx, srcOffset = offset, size = readSize](const uint_&) -> void {
				bool overflow = false;
				readArrayFromImg_singleThread<T1, T2>(imgData, numbers, srcOffset, size, srcOffset, overflow);
				if (overflow) overflowFlags[idx] = 1;
			});
		if (toSlice == imgSize.x) break;
	}
	tp.stop(true);

	stbi_image_free(decoded);

	//std::cout << "Read in " << count << " numbers." << std::endl;
	for (char flag : overflowFlags) if (flag == 1) {
		printf("Error: Input data contains maximum value for value type T1, padded chunk will not have maximum value in the apron. Cast input to higher precision data type.\n");
		exit(1);
	}
	return numbers;
}
template uchar_* readArrayFromImg2D_multiThread<uchar_, uchar_>(const std::string& filename, const uint2& imgSize);
template ushort_* readArrayFromImg2D_multiThread<uchar_, ushort_>(const std::string& filename, const uint2& imgSize);
template int* readArrayFromImg2D_multiThread<uchar_, int>(const std::string& filename, const uint2& imgSize);
template float* readArrayFromImg2D_multiThread<uchar_, float>(const std::string& filename, const uint2& imgSize);
template ushort_* readArrayFromImg2D_multiThread<ushort_, ushort_>(const std::string& filename, const uint2& imgSize);
template int* readArrayFromImg2D_multiThread<ushort_, int>(const std::string& filename, const uint2& imgSize);
template float* readArrayFromImg2D_multiThread<ushort_, float>(const std::string& filename, const uint2& imgSize);

template <typename T1, typename T2>
T2* readArrayFromBin_multiThread(const std::string& filename, const uint3& imgSize) {
	/*
		Read an array of numbers from binary file using multi threading
		@imgSize: x(height), y(width), z(depth)
	*/
	// Configure multi-threading parameters
	uint_ num_cores = std::thread::hardware_concurrency();
	if (num_cores > imgSize.z) num_cores = imgSize.z;
	ctpl::thread_pool tp(num_cores);
	uint_ slicePerThread = iDivUp(imgSize.z, num_cores);
	std::vector<char> overflowFlags(num_cores, 0);

	// Launch threads
	uint_ toSlice, readSize, offset;
	uint_ sliceSize = imgSize.x * imgSize.y;
	uint_ count  = imgSize.x * imgSize.y * imgSize.z;
	T2* numbers  = new T2[count];

	for (uint_ i = 0; i < num_cores; i++) {
		uint_ idx	= i;
		toSlice		= std::min((i + 1) * slicePerThread, imgSize.z);
		readSize	= (toSlice - i * slicePerThread) * sliceSize;
		offset		= i * slicePerThread * sliceSize;
		tp.push(
			[&, idx, fileOffset = offset, size = readSize](const uint_&) -> void {
				bool overflow = false;
				readArrayFromBin_singleThread<T1, T2>(filename, numbers, fileOffset, size, fileOffset, overflow);
				if (overflow) overflowFlags[idx] = 1;
		});
		if (toSlice == imgSize.z) break;
	}
	tp.stop(true);

	std::cout << "Read in " << count << " numbers." << std::endl;
	for (char flag: overflowFlags) if (flag == 1) {
		printf("Error: Input data contains maximum value for value type T1, padded chunk will not have maximum value in the apron. Cast input to higher precision data type.\n");
		exit(1);
	}
	return numbers;
}
template uchar_* readArrayFromBin_multiThread<uchar_, uchar_>(const std::string& filename, const uint3& imgSize);
template ushort_* readArrayFromBin_multiThread<ushort_, ushort_>(const std::string& filename, const uint3& imgSize);
template int* readArrayFromBin_multiThread<int, int>(const std::string& filename, const uint3& imgSize);
template float* readArrayFromBin_multiThread<uchar_, float>(const std::string& filename, const uint3& imgSize);
template float* readArrayFromBin_multiThread<ushort_, float>(const std::string& filename, const uint3& imgSize);
template float* readArrayFromBin_multiThread<float, float>(const std::string& filename, const uint3& imgSize);
template int* readArrayFromBin_multiThread<uchar_, int>(const std::string& filename, const uint3& imgSize);
template int* readArrayFromBin_multiThread<ushort_, int>(const std::string& filename, const uint3& imgSize);
template ushort_* readArrayFromBin_multiThread<uchar_, ushort_>(const std::string& filename, const uint3& imgSize);

template <typename T1, typename T2>
void fetch_chunk2D_fromImage_singleThread(
	const T1*				imgData,		// decoded image, 1 channel, row-major
	T2*&					data,
	T2&						localMin,
	const uint_&			rid_src_frm,
	const uint_&			rid_src_to,
	const uint_&			rid_dst_frm,
	const uint_&			rowSize_src,
	const uint_&			rowSize_dst
)
{
	/*
		Copy a 2D chunk of data from a decoded image buffer.
		@rid_src_frm:  first row index to be read (inclusive)
		@rid_src_to:   last row index to be read (exclusive)
		@rid_dst_frm:  first row index to be written in destination
		@rowSize_src:  row length in the source image (width)
		@rowSize_dst:  row length in the destination chunk buffer (chunk width + halo)
	*/
	T2 val;
	for (uint_ rid_iter = rid_src_frm; rid_iter < rid_src_to; ++rid_iter) {
		// 64-bit offsets: avoids the 32-bit overflow present in the file version
		const ull_ globalOffset_src = static_cast<ull_>(rid_iter) * rowSize_src;
		const ull_ globalOffset_dst =
			static_cast<ull_>(rid_iter - rid_src_frm + rid_dst_frm) * rowSize_dst + 1;

		for (uint_ i = 0; i < rowSize_src; ++i) {
			val = static_cast<T2>(imgData[globalOffset_src + i]);
			// Keep the apron sentinel invariant of the original T1==T2 branch
			if (val == std::numeric_limits<T2>::max()) {
				printf("Error: Input data contains maximum value for value type T2, "
					"padded chunk will not have maximum value in the apron. "
					"Cast input to higher precision data type.\n");
				exit(1);
			}
			data[globalOffset_dst + i] = val;
			if (val < localMin) localMin = val;
		}
	}
}
template void fetch_chunk2D_fromImage_singleThread<uchar_, uchar_>(const uchar_*, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<uchar_, ushort_>(const uchar_*, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<uchar_, int>(const uchar_*, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<uchar_, float>(const uchar_*, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<ushort_, uchar_>(const ushort_*, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<ushort_, ushort_>(const ushort_*, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<ushort_, int>(const ushort_*, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromImage_singleThread<ushort_, float>(const ushort_*, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);

template <typename T1, typename T2>
void fetch_chunk2D_fromFile_singleThread(
	const std::string& filename,
	T2*& data,
	T2& localMin,
	const uint_& rid_src_frm,
	const uint_& rid_src_to,
	const uint_& rid_dst_frm,
	const uint_& rowSize_src,
	const uint_& rowSize_dst
)
{
	/*
		Read a 2D chunk of data from a binary file.

		@rid_src_frm:  first row index to be read (inclusive)
		@rid_src_to:   last row index to be read (exclusive)
		@rid_dst_frm:  first row index to be written in destination
		@rowSize_src:  row length in the source image (width)
		@rowSize_dst:  row length in the destination chunk buffer (chunk width + halo)
	*/
	std::ifstream inFile(filename, std::ios::in | std::ios::binary);
	if (!inFile) {
		std::cerr << "fetch_chunk2D_fromFile_singleThread: file open failure!" << std::endl;
		exit(1);
	}

	T2    val;
	uint_ i;
	uint_ globalOffset_src;
	uint_ globalOffset_dst;

	// Target data type is the same as the input data type
	if (std::is_same<T1, T2>::value) {
		for (uint_ rid_iter = rid_src_frm; rid_iter < rid_src_to; ++rid_iter) {
			globalOffset_src = rid_iter * rowSize_src;
			globalOffset_dst = (rid_iter - rid_src_frm + rid_dst_frm) * rowSize_dst + 1;

			inFile.seekg(static_cast<std::streamoff>(globalOffset_src) * sizeof(T2));
			inFile.read(reinterpret_cast<char*>(&data[globalOffset_dst]),
				static_cast<std::streamsize>(rowSize_src * sizeof(T2)));

			// Check input data and track local minimum
			for (i = 0; i < rowSize_src; ++i) {
				val = data[globalOffset_dst + i];
				if (val == std::numeric_limits<T2>::max()) {
					printf("Error: Input data contains maximum value for value type T2, "
						"padded chunk will not have maximum value in the apron. "
						"Cast input to higher precision data type.\n");
					exit(1);
				}
				if (val < localMin) localMin = val;
			}
		}
	}
	// Target data type is different than the input data type
	else {
		T1* numbers = new T1[rowSize_src];
		for (uint_ rid_iter = rid_src_frm; rid_iter < rid_src_to; ++rid_iter) {
			globalOffset_src = rid_iter * rowSize_src;
			globalOffset_dst = (rid_iter - rid_src_frm + rid_dst_frm) * rowSize_dst + 1;

			inFile.seekg(static_cast<std::streamoff>(globalOffset_src) * sizeof(T1));
			inFile.read(reinterpret_cast<char*>(numbers),
				static_cast<std::streamsize>(rowSize_src * sizeof(T1)));

			// Convert data from T1 to T2
			for (i = 0; i < rowSize_src; ++i) {
				val = static_cast<T2>(numbers[i]);
				data[globalOffset_dst + i] = val;
				if (val < localMin) localMin = val;
			}
		}
		delete[] numbers;
	}

	inFile.close();
}
template void fetch_chunk2D_fromFile_singleThread<uchar_, int>(const std::string&, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<uchar_, uchar_>(const std::string&, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<uchar_, ushort_>(const std::string&, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<uchar_, float>(const std::string&, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<ushort_, int>(const std::string&, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<ushort_, uchar_>(const std::string&, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<ushort_, ushort_>(const std::string&, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<ushort_, float>(const std::string&, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<int, int>(const std::string&, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<int, uchar_>(const std::string&, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<int, ushort_>(const std::string&, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<int, float>(const std::string&, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<float, int>(const std::string&, int*&, int&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<float, uchar_>(const std::string&, uchar_*&, uchar_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<float, ushort_>(const std::string&, ushort_*&, ushort_&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);
template void fetch_chunk2D_fromFile_singleThread<float, float>(const std::string&, float*&, float&, const uint_&, const uint_&, const uint_&, const uint_&, const uint_&);

template <typename T1, typename T2>
void fetch_chunk3D_fromFile_singleThread(
	const std::string&	filename,
	T2*&				data,
	T2&					localMin,
	const uint_&		did_src_frm,
	const uint_&		did_src_to,
	const uint_&		hid_src_frm,
	const uint_& 		hid_src_to,
	const uint_&		did_dst_frm,
	const uint_&		hid_dst_frm,
	const uint_&		sliceSize_src,
	const uint_&		sliceSize_dst,
	const uint_&		rowSize_src,
	const uint_&		rowSize_dst
)
{
	/*
		Read a chunk of data from a binary file. This function works with "fetch_chunk3D_fromFile_multiThread"
		@did_src_frm:	the depth index of the first slice to be read
		@did_src_to:	the depth index of the last slice to be read (excluded)
		@hid_src_frm:	the height index of the first row to be read
		@hid_src_to:	the height index of the last row to be read (excluded)
		@did_dst_frm:	the depth index of the first slice to be written
		@hid_dst_frm:	the height index of the first row to be written
		@sliceSize_src: the size of a slice in the source array
		@sliceSize_dst: the size of a slice in the destination array
		@rowSize_src:	the size of a row in the source array
		@rowSize_dst:	the size of a row in the destination array
	*/
	std::ifstream inFile(filename, std::ios::in | std::ios::binary);
	if (!inFile) { std::cerr << "readArrayFromBin: failure!" << std::endl; exit(1); }
	
	T2 val;
	uint_ i;
	uint_ globalOffset_src;
	uint_ globalOffset_dst;
	// Target data type is the same as the input data type
	if (std::is_same<T1, T2>::value) {
		for (uint_ did_iter = did_src_frm; did_iter < did_src_to; did_iter++) {
			globalOffset_src = did_iter * sliceSize_src + hid_src_frm * rowSize_src;
			globalOffset_dst = (did_iter - did_src_frm + did_dst_frm) * sliceSize_dst + hid_dst_frm * rowSize_dst + 1;
			for (uint_ hid_iter = hid_src_frm; hid_iter < hid_src_to; hid_iter++) {
				inFile.seekg(globalOffset_src * sizeof(T2));
				inFile.read(reinterpret_cast<char*>(&data[globalOffset_dst]), rowSize_src * sizeof(T2));
				// check input data for maximum value
				for (i = 0; i < rowSize_src; i++) {
					val = data[globalOffset_dst + i];
					if (val == std::numeric_limits<T2>::max()) {
						printf("Error: Input data contains maximum value for value type T1, padded chunk will not have maximum value in the apron. Cast input to higher precision data type.\n");
						exit(1);
					}
					if (val < localMin) localMin = val;
				}
				globalOffset_src += rowSize_src;
				globalOffset_dst += rowSize_dst;
			}
		}
	}
	// Target data type is different than the input data type
	else {
		T1* numbers = new T1[rowSize_src];
		for (uint_ did_iter = did_src_frm; did_iter < did_src_to; did_iter++) {
			globalOffset_src = did_iter * sliceSize_src + hid_src_frm * rowSize_src;
			globalOffset_dst = (did_iter - did_src_frm + did_dst_frm) * sliceSize_dst + hid_dst_frm * rowSize_dst + 1;
			for (uint_ hid_iter = hid_src_frm; hid_iter < hid_src_to; hid_iter++) {
				inFile.seekg(globalOffset_src * sizeof(T1));
				inFile.read(reinterpret_cast<char*>(numbers), rowSize_src * sizeof(T1));
				// Convert data from T1 to T2
				for (i = 0; i < rowSize_src; i++) {
					val = static_cast<T2>(numbers[i]);
					data[globalOffset_dst + i] = val;
					if (val < localMin) localMin = val;
				}
				globalOffset_src += rowSize_src;
				globalOffset_dst += rowSize_dst;
			}
		} 
		delete[] numbers;
	}
	inFile.close();
}
template void fetch_chunk3D_fromFile_singleThread<uchar_, int>(const std::string& filename, int*& data, int& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<uchar_, uchar_>(const std::string& filename, uchar_*& data, uchar_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<uchar_, ushort_>(const std::string& filename, ushort_*& data, ushort_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<uchar_, float>(const std::string& filename, float*& data, float& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<ushort_, int>(const std::string& filename, int*& data, int& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<ushort_, uchar_>(const std::string& filename, uchar_*& data, uchar_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<ushort_, ushort_>(const std::string& filename, ushort_*& data, ushort_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<ushort_, float>(const std::string& filename, float*& data, float& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<int, int>(const std::string& filename, int*& data, int& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<int, uchar_>(const std::string& filename, uchar_*& data, uchar_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<int, ushort_>(const std::string& filename, ushort_*& data, ushort_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<int, float>(const std::string& filename, float*& data, float& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<float, int>(const std::string& filename, int*& data, int& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<float, uchar_>(const std::string& filename, uchar_*& data, uchar_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<float, ushort_>(const std::string& filename, ushort_*& data, ushort_& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);
template void fetch_chunk3D_fromFile_singleThread<float, float>(const std::string& filename, float*& data, float& localMin, const uint_& did_src_frm, const uint_& did_src_to, const uint_& hid_src_frm, const uint_& hid_src_to, const uint_& did_dst_frm, const uint_& hid_dst_frm, const uint_& sliceSize_src, const uint_& sliceSize_dst, const uint_& rowSize_src, const uint_& rowSize_dst);