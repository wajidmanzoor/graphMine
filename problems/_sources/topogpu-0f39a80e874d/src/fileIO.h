#pragma once

#include "util.h"
#include <string>

// Read an array of numbers from binary file, multi thread version
template <typename T1, typename T2>
T2* readArrayFromBin2D_multiThread(
	const std::string&	filename,
	const uint2&		imgSize
);

template <typename T1, typename T2>
T2* readArrayFromBin_multiThread(
	const std::string&	filename,
	const uint3&		imgSize
);

template <typename T1, typename T2>
T2* readArrayFromImg2D_multiThread(
	const std::string&	filename,
	const uint2&		imgSize
);

// Single thread reading from image file (jpg/png etc. that is compressed with coding), used with multi thread reading
template <typename T1, typename T2>
void fetch_chunk2D_fromImage_singleThread(
	const T1*			imgData,
	T2*&				data,
	T2&					localMin,
	const uint_&		rid_src_frm,
	const uint_&		rid_src_to,
	const uint_&		rid_dst_frm,
	const uint_&		rowSize_src,
	const uint_&		rowSize_dst
);

// Single thread chunk reading from binary file, used with multi thread reading
template <typename T1, typename T2>
void fetch_chunk2D_fromFile_singleThread(
    const std::string& filename,
    T2*&               data,
    T2&                localMin,
    const uint_&       rid_src_frm,
    const uint_&       rid_src_to,
    const uint_&       rid_dst_frm,
    const uint_&       rowSize_src,
    const uint_&       rowSize_dst
);

template <typename T1, typename T2>
void fetch_chunk3D_fromFile_singleThread(
	const std::string&	filename,
	T2*&				data,
	T2&					localMin,
	const uint_&		did_src_frm,
	const uint_&		did_src_to,
	const uint_&		hid_src_frm,
	const uint_&		hid_src_to,
	const uint_&		did_dst_frm,
	const uint_&		hid_dst_frm,
	const uint_&		sliceSize_src,
	const uint_&		sliceSize_dst,
	const uint_&		rowSize_src,
	const uint_&		rowSize_dst
);