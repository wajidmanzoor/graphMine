#include "util_cu.cuh"
#include "morse_boundary.cuh"

#define PREDEFINED_MAXDIS_FROM_SOURCE 50									// Trade off between prefix sum length and atomic value swap

// Constant memory declaration
__constant__ uint_ maxDim_const[1];											// Maximum allowed dimension of the boundary matrix
__constant__ uint_ chunkNum_h_const[1];										// Number of chunks in the height
__constant__ uint_ bndmatSize_const[1];										// Maximum allowed size of the boundary matrix
__constant__ uint_ imgSizeX_xy_const[1];									// Expanded image slice size
__constant__ uint_ chunkSizeX_y_const[1];									// Expanded chunk width
__constant__ uint_ chunkSizeX_h_const[maxChunkNum_h_];						// Expanded chunk height
__constant__ uint_ chunkSizeX_d_const[maxChunkNum_d_];						// Expanded chunk depth
__constant__ ull_  chunkOffsetX_const[maxChunkNum_h_ * maxChunkNum_d_];		// Expanded chunk offsets

void upload2constant_topoSortKernel2D(
	uint_* chunkSizeX_y,
	uint_* chunkSizeX_h,
	const int	chunkNum
)
{
	/*
		This function uploads:
		- global_info:
			[0]: bndmat_num_d, size of the bndmat buffer assigned to each block
			[1]: matchgridSize_y_d, width of each matching grid = 2 * imgSize.y + 1
		- matchgridSize height: the height of the matching grid = 2 * chunkSize + 1
		- chunk offset: offset for each chunk to calculate global cell IDs.
		to constant memory.
	*/
	cudaMemcpyToSymbol(chunkSizeX_y_const, chunkSizeX_y, sizeof(uint_));
	cudaMemcpyToSymbol(chunkSizeX_h_const, chunkSizeX_h, chunkNum * sizeof(uint_));
}

void upload2constant_bitCheckKernel2D(
	uint_* bndmat_num,
	ull_* chunk_offset_h,
	uint_* maxDim2Compute,
	const int	chunkNum
)
{
	/*
		This function uploads:
		@imgSizeX:     expanded image width and expaned image slice size
		@bndmat_num:   maximum allowed number of critical pairs per GPU block
		@chunkOffsetX: offsets to the start of each expaneded chunk
		to constant memory.
	*/
	cudaMemcpyToSymbol(bndmatSize_const, bndmat_num, sizeof(uint_));
	cudaMemcpyToSymbol(maxDim_const, maxDim2Compute, sizeof(uint_));
	cudaMemcpyToSymbol(chunkOffsetX_const, chunk_offset_h, chunkNum * sizeof(ull_));
}

void upload2constant_topoSortKernel3D(
	uint3&		chunkSizeX,
	uint_*		chunkSizeX_h,
	uint_*		chunkSizeX_d,
	const uint_ chunkNum_h,
	const uint_ chunkNum_d
) {
	/*
		This function uploads:
		@imgSizeX_y:   width of the matching grid
		@chunkSizeX_h: height of the chunk matching grid
		@chunkSizeX_d: depth of the chunk matching grid
		to constant memory.
	*/
	cudaMemcpyToSymbol(chunkNum_h_const, &chunkNum_h, sizeof(uint_));
	cudaMemcpyToSymbol(chunkSizeX_y_const, &chunkSizeX.y, sizeof(uint_));
	cudaMemcpyToSymbol(chunkSizeX_h_const, chunkSizeX_h, chunkNum_h * sizeof(uint_));
	cudaMemcpyToSymbol(chunkSizeX_d_const, chunkSizeX_d, chunkNum_d * sizeof(uint_));
}

void upload2constant_bitCheckKernel3D(
	uint3&		imgSizeX,
	uint_*		bndmat_num,
	ull_*		chunkOffsetX,
	uint_*		maxDim2Compute,
	const uint_	chunkNum
) {
	/*
		This function uploads:
		@imgSizeX:     expanded image width and expaned image slice size
		@bndmat_num:   maximum allowed number of critical pairs per GPU block
		@chunkOffsetX: offsets to the start of each expaneded chunk
		to constant memory.
	*/
	uint_ slice_size = imgSizeX.x * imgSizeX.y;
	cudaMemcpyToSymbol(imgSizeX_xy_const, &slice_size, sizeof(uint_));
	cudaMemcpyToSymbol(bndmatSize_const, bndmat_num, sizeof(uint_));
	cudaMemcpyToSymbol(maxDim_const, maxDim2Compute, sizeof(uint_));
	cudaMemcpyToSymbol(chunkOffsetX_const, chunkOffsetX, chunkNum * sizeof(ull_));
}

inline __device__ uchar_ ucharsub4_read(uchar_ t, uchar_ pos) {
	/*
		This function subdivide a 8-bit unsigned char into 4 consecutive 2-bit regions.
		@t: input unsigned integer
		@pos: from which subregion to read the value
	*/
	switch (pos) {
	case 0:
		return t & 3;
	case 1:
		return (t >> 2) & 3;
	case 2:
		return (t >> 4) & 3;
	case 3:
		return (t >> 6) & 3;
	}
}

// Sub-divide integer into regions of consecutive 2 bits, so each integer holds 16 regions
/*inline*/ __device__ void divide_int2bits_write(uint_& t, uchar_ region, uchar_ v) {
	/*
		Write v to region of t
		@t: the integer to be subdivided
		@region: the region to be written
		@v: the value to be written [0, 3]
		Note: this function is exactly the same as "subdivide_int2bits_write" in morse_matching3D.cu
		CUDA requires routines to be compiled in the same unit, thus this function is copied here.
	*/
	switch (region) {
	case 0:
		t = t & 0xfffffffc;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x1; break;
		case 2: t = t | 0x2; break;
		case 3: t = t | 0x3; break;
		}
		break;
	case 1:
		t = t & 0xfffffff3;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x4; break;
		case 2: t = t | 0x8; break;
		case 3: t = t | 0xc; break;
		}
		break;
	case 2:
		t = t & 0xffffffcf;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x10; break;
		case 2: t = t | 0x20; break;
		case 3: t = t | 0x30; break;
		}
		break;
	case 3:
		t = t & 0xffffff3f;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x40; break;
		case 2: t = t | 0x80; break;
		case 3: t = t | 0xc0; break;
		}
		break;
	case 4:
		t = t & 0xfffffcff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x100; break;
		case 2: t = t | 0x200; break;
		case 3: t = t | 0x300; break;
		}
		break;
	case 5:
		t = t & 0xfffff3ff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x400; break;
		case 2: t = t | 0x800; break;
		case 3: t = t | 0xc00; break;
		}
		break;
	case 6:
		t = t & 0xffffcfff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x1000; break;
		case 2: t = t | 0x2000; break;
		case 3: t = t | 0x3000; break;
		}
		break;
	case 7:
		t = t & 0xffff3fff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x4000; break;
		case 2: t = t | 0x8000; break;
		case 3: t = t | 0xc000; break;
		}
		break;
	case 8:
		t = t & 0xfffcffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x10000; break;
		case 2: t = t | 0x20000; break;
		case 3: t = t | 0x30000; break;
		}
		break;
	case 9:
		t = t & 0xfff3ffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x40000; break;
		case 2: t = t | 0x80000; break;
		case 3: t = t | 0xc0000; break;
		}
		break;
	case 10:
		t = t & 0xffcfffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x100000; break;
		case 2: t = t | 0x200000; break;
		case 3: t = t | 0x300000; break;
		}
		break;
	case 11:
		t = t & 0xff3fffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x400000; break;
		case 2: t = t | 0x800000; break;
		case 3: t = t | 0xc00000; break;
		}
		break;
	}
}

/*inline*/ __device__ uchar_ divide_int2bits_read(uint_ t, uchar_ region) {
	/*
		Read region of t
		@t: the integer to be subdivided
		@region: the region to be read
		@return: the value of region [0, 3]
		Note: this function is exactly the same as "subdivide_int2bits_read" in morse_matching3D.cu
		CUDA requires routines to be compiled in the same unit, thus this function is copied here.
	*/
	switch (region) {
	case 0:
		return t & 0x3;
	case 1:
		return (t >> 2) & 0x3;
	case 2:
		return (t >> 4) & 0x3;
	case 3:
		return (t >> 6) & 0x3;
	case 4:
		return (t >> 8) & 0x3;
	case 5:
		return (t >> 10) & 0x3;
	case 6:
		return (t >> 12) & 0x3;
	case 7:
		return (t >> 14) & 0x3;
	case 8:
		return (t >> 16) & 0x3;
	case 9:
		return (t >> 18) & 0x3;
	case 10:
		return (t >> 20) & 0x3;
	case 11:
		return (t >> 22) & 0x3;
	default:
		printf("Error: divide_int2bits_read, unrecognized region\n");
		return 0;
	}
}

/*inline*/ __host__ __device__ uchar_ subdivide_short2bits_read(ushort_ t, uchar_ region) {
	/*
		Read region of t
		@t: the integer that is subdivided
		@region: the region to be read
		returns the value of the region [0, 2], 0: outgoing; 1: incoming; 2: no edge
		subdivide a short value to 8 consecutive 2 bits regions and use the frist 6 for 6 directions of cube
		Note: the write function is in "morse_matching3D.cu" file
	*/
	switch (region) {
	case 0:
		return t & 0x3;
	case 1:
		return (t >> 2) & 0x3;
	case 2:
		return (t >> 4) & 0x3;
	case 3:
		return (t >> 6) & 0x3;
	case 4:
		return (t >> 8) & 0x3;
	case 5:
		return (t >> 10) & 0x3;
	default:
		printf("Error: subdivide_short2bits_read, unrecognized region\n");
		return 0;
	}
}

__device__ void atomicAddShort(ushort_* address, ushort_ val) {

	uint_* base_address = (uint_*)((size_t)address & ~2);
	uint_ long_val = ((size_t)address & 2) ? ((uint_)val << 16) : val;
	atomicAdd(base_address, long_val);
}

__device__ unsigned short atomicSubShort(ushort_* address, ushort_ val) {

	uint_* base_address = (uint_*)((size_t)address & ~2);
	uint_ long_val = ((size_t)address & 2) ? ((uint_)val << 16) : val;
	uint_ long_old = atomicSub(base_address, long_val);
	return ((size_t)address & 2) ? (ushort_)(long_old >> 16) : (ushort_)(long_old & 0xffff);
}

inline __device__ void findsource2D(uchar_ offset, uint_& x, uint_& y) {
	/*
		Given the offset of a cell, find where its value comes from
		0: self, 1: top edge, 2: left edge, 3: right edge, 4: bottom edge
		5: topleft vert, 6: topright vert, 7: bottomleft vert, 8: bottomright vert
		@offset: uchar in range [0, 8] indicating the relative position
		@x: offset in x coord to the source cell
		@y: offset in y coord to the source cell
	*/
	switch (offset >> 3) {
	case 0: x = (x - 1) / 2;	y = (y - 1) / 2; break;
	case 1: x = (x - 1) / 2;	y = y / 2;		 break;
	case 2: x = x / 2;			y = (y - 1) / 2; break;
	case 3: x = (x - 2) / 2;	y = (y - 1) / 2; break;
	case 4: x = (x - 1) / 2;	y = (y - 2) / 2; break;
	case 5: x = x / 2;			y = y / 2;		 break;
	case 6: x = (x - 2) / 2;	y = y / 2;		 break;
	case 7: x = x / 2;			y = (y - 2) / 2; break;
	case 8: x = (x - 2) / 2;	y = (y - 2) / 2;
	}
}

inline __device__ void findsource3D(uchar_ offset, uint_& x, uint_& y, uint_& z) {
	/*
		Given the coordinate of a cell (x,y,z) in a chunk, find where this ce''s value originate from (i.e.
		find the top-dimension cell this cell belongs to).
		@offset: crit with lower 3 bits for actual critical information and upper 5 bits for offset information relative to the top-dimension cell
		@x, y, z: the coordinate of the target cell

		offset and corresponding cell
		0: self, top dimensional cell		7: front-top edge			14: bottom-right edge			21: front-bottom-left vertex
		1: front face						8: front-left edge          15: back-top edge 				22: front-bottom-right vertex
		2: left face 						9: front-right edge 	    16: back-left edge 				23: back-top-left vertex
		3: right face                       10: front-bottom edge 		17: back-right edge 			24: back-top-right vertex
		4: back face                        11: top-left edge 			18: back-bottom edge 			25: back-bottom-left vertex
		5: top face 					    12: top-right edge          19: front-top-left vertex 		26: back-bottom-right vertex
		6: bottom face                      13: bottom-left edge        20: front-top-right vertex
	*/
	offset >>= 3;
    switch (offset) {
    case 0:  x = (x - 1) >> 1;  y = (y - 1) >> 1;	z = (z - 1) >> 1;	break;
    case 1:  x = (x - 1) >> 1;  y = (y - 1) >> 1;	z =  z       >> 1;	break;
    case 2:  x =  x       >> 1; y = (y - 1) >> 1;	z = (z - 1) >> 1;	break;
    case 3:  x = (x - 2) >> 1;  y = (y - 1) >> 1;	z = (z - 1) >> 1;	break;
    case 4:  x = (x - 1) >> 1;  y = (y - 1) >> 1;	z = (z - 2) >> 1;	break;
    case 5:  x = (x - 1) >> 1;  y =  y       >> 1;	z = (z - 1) >> 1;   break;
    case 6:  x = (x - 1) >> 1;  y = (y - 2) >> 1;	z = (z - 1) >> 1;   break;
    case 7:  x = (x - 1) >> 1;  y =  y       >> 1;	z =  z       >> 1;  break;
    case 8:  x =  x       >> 1; y = (y - 1) >> 1;	z =  z       >> 1;	break;
    case 9:  x = (x - 2) >> 1;  y = (y - 1) >> 1;	z =  z       >> 1;	break;
    case 10: x = (x - 1) >> 1;  y = (y - 2) >> 1;	z =  z       >> 1;	break;
    case 11: x =  x       >> 1; y =  y       >> 1;	z = (z - 1) >> 1;	break;
    case 12: x = (x - 2) >> 1;  y =  y       >> 1;	z = (z - 1) >> 1;	break;
    case 13: x =  x       >> 1; y = (y - 2) >> 1;	z = (z - 1) >> 1;	break;
    case 14: x = (x - 2) >> 1;  y = (y - 2) >> 1;	z = (z - 1) >> 1;	break;
    case 15: x = (x - 1) >> 1;  y =  y       >> 1;	z = (z - 2) >> 1;	break;
    case 16: x =  x       >> 1; y = (y - 1) >> 1;	z = (z - 2) >> 1;	break;
    case 17: x = (x - 2) >> 1;  y = (y - 1) >> 1;	z = (z - 2) >> 1;	break;
    case 18: x = (x - 1) >> 1;  y = (y - 2) >> 1;	z = (z - 2) >> 1;	break;
    case 19: x =  x       >> 1; y =  y       >> 1;	z =  z       >> 1;	break;
    case 20: x = (x - 2) >> 1;  y =  y       >> 1;	z =  z       >> 1;	break;
    case 21: x =  x       >> 1; y = (y - 2) >> 1;	z =  z       >> 1;	break;
    case 22: x = (x - 2) >> 1;  y = (y - 2) >> 1;	z =  z       >> 1;	break;
    case 23: x =  x       >> 1; y =  y       >> 1;	z = (z - 2) >> 1;	break;
    case 24: x = (x - 2) >> 1;  y =  y       >> 1;	z = (z - 2) >> 1;	break;
    case 25: x =  x       >> 1; y = (y - 2) >> 1;	z = (z - 2) >> 1;	break;
    case 26: x = (x - 2) >> 1;  y = (y - 2) >> 1;	z = (z - 2) >> 1;	break;
    }
}

template <typename type, ushort_ gridH, ushort_ gridW, ushort_ gridSize>
__global__ void bitCheck_kernel2D(
	cudaTextureObject_t		img,
	const ushort_			chunkID,
	uchar_*					crit_global,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ulonglong2*				bndmat,
	type*					filtVals,
	uchar2*					offsets
)
{
	/*
		This function checks the path counting buffer from pathCount_kernel3D kernel. Each element in the buffer indicates the number
		of alternating paths from multiple source nodes to the current node. Note that the block layoaut of this kernel is the same as
		topoSort_kernel3D kernel. This means that a thread in this kernel will process lanes different from the previous kernel. Each
		thread will need to determine the source nodes itself.
		----- Inputs -----
		@img:			input chunk in the texture memory
		@chunkID:		id of the chunk
		@crit_global:	critical information (critical + cell offset) in the global memory
		@pathCntBuf:	the buffer for path counting in global memory. Each block has a buffer of size PATHCNT_BUF_SIZE * gridSize.
		@topoSrtBuf:	the global buffer for topological sorting in global memory directly from the previous kernel.
		----- Outputs -----
		@bndmat:		the boundary relations in global memory
		@filtVals:		the filtration values corresponding to the cells in bndmat
	*/

	// Shared memory declaration
	__shared__ uchar_		crit_shared[gridSize];									// critical mask in shared memory
	__shared__ uint_*		pathCnt;												// path count buffer pointer offset
	__shared__ ushort_*		buf_ptr[3];												// topo order buffer pointer offset
	__shared__ ulonglong2*	bnd;													// bndmat buffer pointer offset
	__shared__ type*		filt;													// filtration value pointer offset
	__shared__ uchar2*		cellOffset;												// Cell offsets pointer
	__shared__ uint_		global_base;
	__shared__ uint_		bndmat_atomic, buffSize_actual;							// global offset to the start of this block
	__shared__ ushort_		blockH_actual, blockW_actual, blockSize_actual;			// actual block size and critical cells number
	__shared__ uint_		blkOffsetX, blkOffsetY;									// block coordinates offset in the chunk and adapted chunk offset
	__shared__ ll_			chunkOffsetAdapted;

	// Register declaration
	uint_	offset, util;
	uint_	cell_id, crit_id, buff_id;
	ull_    cell_coord, crit_coord;
	uint_	ux, uy;
	ushort_ critNum, bndmat_pos, i;
	type	val;

	// Initialize shared memory
	if (threadIdx.x == 0) {
		offset				= blockIdx.x + blockIdx.y * gridDim.x;
		bndmat_atomic		= 0;
		// Initialize the buffer pointers
		// buffer pointer offset initialization
		pathCnt				= pathCntBuf + offset * gridSize * PATHCNT_BUF_SIZE;
		bnd					= bndmat + offset * bndmatSize_const[0];
		filt				= filtVals + offset * bndmatSize_const[0] * 2;
		cellOffset			= offsets + offset * bndmatSize_const[0];
		// path count buffer pointer offset initialization
		buf_ptr[0]			= topoSrtbuf + offset * gridSize * 4;
		buf_ptr[1]			= buf_ptr[0] + gridSize;
		buf_ptr[2]			= buf_ptr[1] + 2 * gridSize;
		// Find the actual size of the block
		blockH_actual		= buf_ptr[1][gridSize];
		blockW_actual		= buf_ptr[1][gridSize + 1];
		blockSize_actual	= buf_ptr[1][gridSize + 2];
		buffSize_actual		= blockSize_actual * PATHCNT_BUF_SIZE;
		// Find the global offset to the start of the block in the matching grid
		blkOffsetX			= blockIdx.x * gridW - blockIdx.x;
		blkOffsetY			= blockIdx.y * gridH - blockIdx.y;
		global_base			= blkOffsetX + blkOffsetY * chunkSizeX_y_const[0];
		chunkOffsetAdapted	= 1LL * chunkOffsetX_const[chunkID] - 1LL * 4 * chunkSizeX_y_const[0];
		blkOffsetY			+= 4;
	}
	__syncthreads();

	// Initialize critical mask in shared memory
	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		ux					= offset % blockW_actual;
		uy					= offset / blockW_actual * chunkSizeX_y_const[0];
		cell_coord			= global_base + ux + uy;
		crit_shared[offset] = crit_global[cell_coord];
		offset				= offset + blockDim.x;
	}
	__syncthreads();

	offset = threadIdx.x;
	while (offset < buffSize_actual) {
		util = pathCnt[offset];
		cell_id = buf_ptr[0][offset / PATHCNT_BUF_SIZE];
		if (util == 0 || (crit_shared[cell_id] & 7) == 0 || (crit_shared[cell_id] & 7) > maxDim_const[0]) { offset += blockDim.x; continue; }
		buff_id = offset % PATHCNT_BUF_SIZE;
		critNum = (buff_id >= gridSize) ? 0 : buf_ptr[2][buff_id];
		if (critNum == 0) break;
		// Retrieve the cell offset in the chunk
		ux = cell_id % blockW_actual + blkOffsetX;
		uy = cell_id / blockW_actual + blkOffsetY;
		cell_coord = ux + uy * chunkSizeX_y_const[0] + chunkOffsetAdapted;
		findsource2D(crit_shared[cell_id], ux, uy);
		val = tex2D<type>(img, ux + 1, uy);

		// Loop through each of the 32 bits in integer
#pragma unroll
		for (i = 0; i < critNum; i++) {
			if (util & 1u) {
				crit_id = buf_ptr[1][buff_id + i * PATHCNT_BUF_SIZE];

				// Reject duplicate boundary relations from border edges
				ux = crit_id % blockW_actual;
				uy = crit_id / blockW_actual;
				bndmat_pos = cell_id % blockW_actual;
				crit_coord = cell_id / blockW_actual;
				// Conditions to filter invalid boundary relations
				if (crit_id == cell_id ||
					((crit_shared[crit_id] & 7) - (crit_shared[cell_id] & 7)) != 1 ||
					(uy == 0 && crit_coord == 0 && (chunkID > 0 || blockIdx.y != 0)) ||		// if both cells have y = 0, only process the top most block in the top most chunk
					(ux == 0 && bndmat_pos == 0 && blockIdx.x != 0)							// if both cells have x = 0, only process the left most block
					)
				{
					util >>= 1; continue;
				}

				bndmat_pos = atomicAdd(&bndmat_atomic, 1);
				ux = crit_id % blockW_actual + blkOffsetX;
				uy = crit_id / blockW_actual + blkOffsetY;
				crit_coord = 1ULL * uy * chunkSizeX_y_const[0] + 1ULL * ux + chunkOffsetAdapted;

				findsource2D(crit_shared[crit_id], ux, uy);
				filt[bndmat_pos * 2] = tex2D<type>(img, ux + 1, uy);
				filt[bndmat_pos * 2 + 1] = val;
				// Store boundary relations in global memory
				bnd[bndmat_pos] = make_ulonglong2(crit_coord, cell_coord);
				// Store cell offsets in global memory
				cellOffset[bndmat_pos] = make_uchar2(crit_shared[crit_id] >> 3, crit_shared[cell_id] >> 3);
			}
			util >>= 1u;
		}
		offset += blockDim.x;
	}
}

template <ushort_ gridH, ushort_ gridW, ushort_ gridSize>
__launch_bounds__(PATHCNT_BUF_SIZE)
__global__ void pathCount_kernel2D(
	const ushort_					chunkID,
	const uchar_* __restrict__		match_global,
	uint_* __restrict__				pathCntBuf,
	ushort_* __restrict__			topoSrtbuf,
	const ushort_* __restrict__		chunkCritNum
)
{
	/*
		@pathCntBuf: buffer for path counting computation: blockNum x gridSize x PATHCNT_BUF_SIZE
		@bndmat: size of block_num * bndmat_num uint2 array. Used to record critical pair that has odd paths.
		@filt_vals: same size with bndmat type2 array. Use to store filtration values
	*/
	// Shared memory declaration
	__shared__ uint_*	pathCnt;														// path count buffer pointer offset
	__shared__ ushort_* buf_ptr[4];														// topo order buffer pointer offset
	__shared__ uint_    global_base;													// global offset to the start of this block
	__shared__ ushort_  blockH_actual, blockW_actual, blockSize_actual, critNum;		// actual block size and critical cells number
	// Declare variables using registers
	uchar_				match;
	uint_				cell_id, cell_coord, iter, util, offset = 0;

	// Initialize shared memory
	if (threadIdx.x == 0) {
		cell_id = blockIdx.x + blockIdx.y * gridDim.x;						// block offset
		critNum = chunkCritNum[cell_id];									// number of critical cells in the block
		// path count buffer pointer offset initialization
		buf_ptr[0] = topoSrtbuf + cell_id * gridSize * 4;
		buf_ptr[1] = buf_ptr[0] + gridSize;
		buf_ptr[2] = buf_ptr[1] + gridSize;
		buf_ptr[3] = buf_ptr[2] + gridSize;
		// Path counting buffer pointer initialization
		pathCnt = pathCntBuf + cell_id * gridSize * PATHCNT_BUF_SIZE;
		// Find the actual size of the block
		blockH_actual = buf_ptr[3][0];
		blockW_actual = buf_ptr[3][1];
		blockSize_actual = buf_ptr[3][2];
		// Find the global offset to the start of the block in the matching grid
		global_base = (blockIdx.y * gridH - blockIdx.y) * chunkSizeX_y_const[0] + blockIdx.x * gridW - blockIdx.x;
	}
	__syncthreads();

	// Lane pointer to avoid repeated index multiplies
	uint_* lane = pathCnt + threadIdx.x;
	// Lane pointer to avoid repeated index multiplies
	util = 1u;
	cell_coord = 0u;

	// Initialize pathCnt buffer
#pragma unroll
	for (iter = 0; iter < blockSize_actual; iter++) { lane[offset] = 0; offset += PATHCNT_BUF_SIZE; }
	__syncthreads();
	for (iter = 0; iter < BITS_PER_THREAD; iter++) {
		offset = threadIdx.x + iter * PATHCNT_BUF_SIZE;
		if (offset >= critNum) break;
		cell_id = buf_ptr[1][offset];
		lane[buf_ptr[2][cell_id] * PATHCNT_BUF_SIZE] = util;
		util <<= 1u;
		cell_coord++;
	}
	if (threadIdx.x < gridSize) buf_ptr[3][threadIdx.x] = (ushort_)cell_coord;
	__syncthreads();

	// Compute path counting (disparity)
	uint_* lane_iter = lane;
	for (iter = 0; iter < blockSize_actual; iter++, lane_iter += PATHCNT_BUF_SIZE) {
		// Get the cell id in topological order and retrieve its global offset in the matching grid
		cell_id = buf_ptr[0][iter];
		// slice (z), col (x), row (y)
		util = cell_id / blockW_actual;							 // y row
		offset = cell_id % blockW_actual;                           // x col
		// global address -> load match
		cell_coord = offset + util * chunkSizeX_y_const[0] + global_base;
		match = match_global[cell_coord];
		// accumulator
		cell_coord = *lane_iter;

		// Decide neighbors in x axis
		if (offset > 0 && ucharsub4_read(match, 3) == 1)					cell_coord ^= lane[buf_ptr[2][cell_id - 1] * PATHCNT_BUF_SIZE];
		if (offset + 1 < blockW_actual && ucharsub4_read(match, 1) == 1)	cell_coord ^= lane[buf_ptr[2][cell_id + 1] * PATHCNT_BUF_SIZE];
		// Decide neighbors in y axis
		if (util > 0 && ucharsub4_read(match, 0) == 1)						cell_coord ^= lane[buf_ptr[2][cell_id - blockW_actual] * PATHCNT_BUF_SIZE];
		if (util + 1 < blockH_actual && ucharsub4_read(match, 2) == 1)		cell_coord ^= lane[buf_ptr[2][cell_id + blockW_actual] * PATHCNT_BUF_SIZE];
		// Write the result to the buffer
		*lane_iter = cell_coord;
	}
	__syncthreads();

	// Carry the information to the next kernel
	if (threadIdx.x == 0) {
		buf_ptr[2][0] = blockH_actual;
		buf_ptr[2][1] = blockW_actual;
		buf_ptr[2][2] = blockSize_actual;
	}
}

template <ushort_ gridH, ushort_ gridW, ushort_ gridSize>
__global__ void topoSort_kernel2D(
	const ushort_		chunkID,
	uchar_*				match_global,
	uchar_*				crit_mask,
	ushort_*			topoSrtbuf,
	ushort_*			chunkCritNum
)
{
	/*
	Descriptions:
		This version does not use shared memory for src or order array.
	template parameters
		@gridH: blockSizeX.x, expanded block height
		@gridW: blockSizeX.y, expanded block width
		@gridSize: gridH x gridW
	argument parameters
		@chunkID: ID of the current chunk
		@match_global: input graph data
		@crit_mask: same size as match_global. Marks the critical nodes as dim + 1, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
		@topoSrtbuf  : buffer for topological order computation: blockNum x gridSize x 4
		buf_ptr[0][X]: buf_ptr[0][X] appears in the X position in the topological order
		topoOrder1[X]:			topoOrder1[X] has to appear before X.
		buf_ptr[1][X]: this pointer is not used any more and replaced by topoOrder1. (for familiarity reasons)
		buf_ptr[2][X]: the number of nodes with distance X from src node. buf_ptr[2][5] = 2 means 2 nodes
			with distance 5 from respective src nodes. A pre-fix sum is run on buf_ptr[2] later. Suppose
			buf_ptr[2] is: [2, 3, 2]. Pre-fix sum results in [2, 5, 7]. This result is later used to get
			the exact topo order of each node.
		buf_ptr[3][X]: the distance of node X from its src node.
		buf_ptr[4][X]: the index of src node for node X.
	*/
	// Shared memory allocation
	__shared__ uchar_   tile[gridSize];													// Tile of matching grid in the shared memory
	__shared__ ushort_* buf_ptr[4];														// Pointers to the global memory buffer
	__shared__ ushort_	pre[gridSize];													// The direct predecessor of each node in the tile
	__shared__ uint_    flag[3];														// 0: topo order exit flag, 1: furthest node distance, 2: #critical cells with dim >=1
	__shared__ uint_	blockH_actual, blockW_actual, blockSize_actual, global_base;

	// Register declaration
	uint_ offset, father, grandfather, util, deg0;

	if (threadIdx.x == 0) {
		offset = blockIdx.y * gridH - blockIdx.y;
		blockH_actual = min(offset + gridH, chunkSizeX_h_const[chunkID]) - offset;
		grandfather = blockIdx.x * gridW - blockIdx.x;
		blockW_actual = min(grandfather + gridW, chunkSizeX_y_const[0]) - grandfather;
		blockSize_actual = blockH_actual * blockW_actual;
		global_base = grandfather + offset * chunkSizeX_y_const[0];
		// Initialize flags
		flag[1] = min(PREDEFINED_MAXDIS_FROM_SOURCE, blockSize_actual - 1);			// empirical initial value
		flag[2] = 0;														// critical cell counter
		// path count buffer pointer offset initialization
		buf_ptr[0] = topoSrtbuf + (blockIdx.x + blockIdx.y * gridDim.x) * gridSize * 4;
		buf_ptr[1] = buf_ptr[0] + gridSize;
		buf_ptr[2] = buf_ptr[1] + gridSize;
		buf_ptr[3] = buf_ptr[2] + gridSize;
	}
	__syncthreads();

	// Initialize path count counter buffer
	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		tile[offset] = match_global[global_base + offset % blockW_actual + offset / blockW_actual * chunkSizeX_y_const[0]];
		// Initialize buffer
		pre[offset] = USHRT_MAX;														// order array
		buf_ptr[2][offset] = gridSize;													// distance of each node from src at current round
		buf_ptr[3][offset] = offset;													// src array
		offset += blockDim.x;
	}
	__syncthreads();

	deg0 = gridSize;
	do {
		__syncthreads();																// This barrier is crucial as incomplete thread could possibly escape the loop if thread 0 set flag[0] to 0 first
		if (threadIdx.x == 0) flag[0] = 0;
		__syncthreads();
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			buf_ptr[1][offset] = 0;
			if (pre[offset] != USHRT_MAX) { offset = offset + blockDim.x; continue; }
			// Subdivide util into 8 4-bits regions: 0->node.x, 1->node.y, 2->node.z, 3->node.w, 4->dirs.x, 5->dirs.y, 6->dirs.z, 7->dirs.w
			util = 0;
			father = offset % blockW_actual;			// px
			if (father > 0) grandfather = 1 - ucharsub4_read(tile[offset - 1], 1); else grandfather = 2;
			uintsub8_write(util, 3, grandfather);
			if (father + 1 < blockW_actual) grandfather = 1 - ucharsub4_read(tile[offset + 1], 3); else grandfather = 2;
			uintsub8_write(util, 1, grandfather);
			father = offset / blockW_actual;			// py
			if (father > 0) grandfather = 1 - ucharsub4_read(tile[offset - blockW_actual], 2); else grandfather = 2;
			uintsub8_write(util, 0, grandfather);
			if (father + 1 < blockH_actual) grandfather = 1 - ucharsub4_read(tile[offset + blockW_actual], 0); else grandfather = 2;
			uintsub8_write(util, 2, grandfather);
			if (uintsub8_read(util, 0) == 1) uintsub8_write(util, 4, 1);
			if (uintsub8_read(util, 1) == 1) uintsub8_write(util, 5, 1);
			if (uintsub8_read(util, 2) == 1) uintsub8_write(util, 6, 1);
			if (uintsub8_read(util, 3) == 1) uintsub8_write(util, 7, 1);

			if (uintsub8_read(util, 0) == 1 && uintsub8_read(util, 1) == 1) {
				if (ucharsub4_read(tile[offset + 1], 0) == 1 && ucharsub4_read(tile[offset + 1 - blockW_actual], 3) == 1) uintsub8_write(util, 4, 0);
				else if (ucharsub4_read(tile[offset - blockW_actual], 1) == 1 && ucharsub4_read(tile[offset + 1 - blockW_actual], 2) == 1) uintsub8_write(util, 5, 0);
			}
			if (uintsub8_read(util, 1) == 1 && uintsub8_read(util, 2) == 1) {
				if (ucharsub4_read(tile[offset + 1], 2) == 1 && ucharsub4_read(tile[offset + 1 + blockW_actual], 3) == 1) uintsub8_write(util, 6, 0);
				else if (ucharsub4_read(tile[offset + blockW_actual], 1) == 1 && ucharsub4_read(tile[offset + 1 + blockW_actual], 0) == 1) uintsub8_write(util, 5, 0);
			}
			if (uintsub8_read(util, 2) == 1 && uintsub8_read(util, 3) == 1) {
				if (ucharsub4_read(tile[offset - 1], 2) == 1 && ucharsub4_read(tile[offset - 1 + blockW_actual], 1) == 1) uintsub8_write(util, 6, 0);
				else if (ucharsub4_read(tile[offset + blockW_actual], 3) == 1 && ucharsub4_read(tile[offset - 1 + blockW_actual], 0) == 1) uintsub8_write(util, 7, 0);
			}
			if (uintsub8_read(util, 3) == 1 && uintsub8_read(util, 0) == 1) {
				if (ucharsub4_read(tile[offset - 1], 0) == 1 && ucharsub4_read(tile[offset - 1 - blockW_actual], 1) == 1) uintsub8_write(util, 4, 0);
				else if (ucharsub4_read(tile[offset - blockW_actual], 3) == 1 && ucharsub4_read(tile[offset - 1 - blockW_actual], 2) == 1) uintsub8_write(util, 7, 0);
			}
			father = uintsub8_read(util, 4) + uintsub8_read(util, 5) + uintsub8_read(util, 6) + uintsub8_read(util, 7);
			if (father == 0) pre[offset] = deg0;
			else if (father == 1) {
				if (uintsub8_read(util, 4) == 1) pre[offset] = offset - blockW_actual;				// dirs.x == 1
				else if (uintsub8_read(util, 5) == 1) pre[offset] = offset + 1;						// dirs.y == 1
				else if (uintsub8_read(util, 6) == 1) pre[offset] = offset + blockW_actual;			// dirs.z == 1
				else pre[offset] = offset - 1;																	// dirs.w == 1
				buf_ptr[3][offset] = pre[offset];
				buf_ptr[2][offset]++;
			}
			offset = offset + blockDim.x;
		}
		__syncthreads();

		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[3][offset] < gridSize) {
				father = buf_ptr[3][offset];
				grandfather = pre[father];
				while (grandfather < gridSize) {
					buf_ptr[2][offset]++;
					father = grandfather;
					grandfather = pre[grandfather];
				}
				if (grandfather == USHRT_MAX) { buf_ptr[3][offset] = father; flag[0] = 1; }
				else {
					buf_ptr[3][offset] = grandfather;
					tile[offset] = 170;
					buf_ptr[2][offset] -= gridSize;
					atomicAddShort(&buf_ptr[1][buf_ptr[2][offset]], 1);
				}
			}
			offset = offset + blockDim.x;
		}
		__syncthreads();

		// Find the length of buf_ptr[1] that needs to be scanned
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[1][offset] > 0 && offset > flag[1]) atomicMax(&flag[1], offset);
			offset = offset + blockDim.x;
		}
		__syncthreads();

		/*
			Parallel Prefix-Sum (Reference: https://people.cs.vt.edu/yongcao/teaching/cs5234/spring2013/slides/Lecture10.pdf)
		*/
		father = 1;	// Reuse variable for stride
		// ===== Reduction Step =====
		while (father <= (flag[1] + 1) / 2) {
			offset = threadIdx.x;
			util = (offset + 1) * father * 2 - 1;
			while (util < flag[1] + 1) {
				buf_ptr[1][util] += buf_ptr[1][util - father];
				offset = offset + blockDim.x;
				util = (offset + 1) * father * 2 - 1;
			}
			father *= 2;
			__syncthreads();
		}
		// ===== Post Scan Step =====
		father /= 2;
		while (father > 0) {
			offset = threadIdx.x;
			util = (offset + 1) * father * 2 - 1;
			while (util + father < flag[1] + 1) {
				buf_ptr[1][util + father] += buf_ptr[1][util];
				offset = offset + blockDim.x;
				util = (offset + 1) * father * 2 - 1;
			}
			father /= 2;
			__syncthreads();
		}
		father = buf_ptr[1][flag[1]];
		__syncthreads();

		// Assign topological order for current round
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[2][offset] < gridSize) {
				buf_ptr[0][atomicSubShort(&buf_ptr[1][buf_ptr[2][offset]], 1) - 1 + deg0 - gridSize] = offset;
				buf_ptr[2][offset] += gridSize;
			}
			offset = offset + blockDim.x;
		}
		__syncthreads();
		deg0 += father;
		__syncthreads();
	} while (flag[0] == 1);

	/*
		COMPUTING HOMOLOGY AND PERSISTENT HOMOLOGY USING ITERATED MORSE DECOMPOSITION
		PAWE L D LOTKO AND HUBERT WAGNER
		https://arxiv.org/pdf/1210.1429.pdf
		Algorithm 4
	*/
	// Compute morse paths
	// Collect indices of all critical cells with dim >= 1 and put them into buf_ptr[1].
	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		// Reorder topo order to buf_ptr[2] s.t. X is at position buf_ptr[2][X] in the topological order
		buf_ptr[2][buf_ptr[0][offset]] = offset;
		father = global_base + offset % blockW_actual + offset / blockW_actual * chunkSizeX_y_const[0];
		if ((crit_mask[father] & 7) > 1) buf_ptr[1][atomicAdd(&flag[2], 1)] = offset;
		offset = offset + blockDim.x;
	}
	__syncthreads();
	if (threadIdx.x == 0) {
		if (flag[2] > PATHCNT_BUF_BITS) { printf("Error: required buffer %d >= %d, increase PATHCNT_BUF_SIZE\n", flag[2], PATHCNT_BUF_BITS); return; }
		chunkCritNum[blockIdx.x + blockIdx.y * gridDim.x] = flag[2];
		buf_ptr[3][0] = blockH_actual;
		buf_ptr[3][1] = blockW_actual;
		buf_ptr[3][2] = blockSize_actual;
	}
}

template<ushort_ gridH, ushort_ gridW, ushort_ gridD, ushort_ gridSize>
__global__ void topoSort_kernel3D(
	const ushort_	chunkID,
	ushort_*		match_global,
	uchar_*			crit_global,
	ushort_*		buf,
	ushort_*		chunkCritNum
)
{
	/*
	Descriptions:
		This function computes topological sorting of the matching grid for a block
	Template parameters:
		@gridH: blockSizeX.x, expanded block height
		@gridW: blockSizeX.y, expanded block width
		@gridD: blockSizeX.z, expanded block depth
		@gridSize: gridH * gridW * gridD
	Argument parameters:
		@chunkID:      ID of the chunk to be processed
		@match_global: the matching grid in global memory for the entire chunk
		@crit_global:  same size as grid. Marks the critical nodes as dim + 1, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
		@buf:          buffer for morse boundary computation, has a size of blockNum x gridSize x 4 for each chunk
			- buf_ptr[0]: buf_ptr[0][X] is in the X-th place in the topological order
			- buf_ptr[1]: buf_ptr[1][X] is the number of nodes with distance X from their respective source nodes. buf_ptr[1][5] = 3
						  means there are 3 nodes with distance 5 from their source nodes. Prefix-sum is later run on buf_ptr[1].
						  Suppose buf_ptr[1] = [2, 3, 2, 1]. Prefix-sum result is [2, 5, 7, 8]. This result is used to get the final
						  topological order for each node.
			- buf_ptr[2]: buf_ptr[2][X] is the distance from node X to its source node.
			- buf_ptr[3]: buf_ptr[3][X] is the index of source node for node X.
		@chunkCritNum: global buffer stores the number of critical cells in each GPU blocks of a chunk
	*/

	// Shared memory allocation
	__shared__ ushort_  tile[gridSize];						// Tile of the matching grid in shared memory
	__shared__ ushort_* buf_ptr[4];							// Pointers to the global memory buffer
	__shared__ ushort_  pre[gridSize];						// The direct predecessor of each node in the tile
	__shared__ uint_    flag[3];							// Flag 0: topoSort loop exit condition; Flag 1: furthest node distance for prefix sum; Flag 2: #critical cells with dim >=1
	__shared__ uint_    blockH_actual, blockW_actual, blockD_actual, blockSlice_actual, blockSize_actual, global_base, chunkSizeX_xy_actual;

	// Declare variables using registers
	uint_ offset, father, grandfather, util, deg0;

	if (threadIdx.x == 0) {
		// Find the actual size of the block and global offset to the start of the block in the matching grid
		offset = blockIdx.y * gridH - blockIdx.y;
		blockH_actual = min(offset + gridH, chunkSizeX_h_const[chunkID % chunkNum_h_const[0]]) - offset;
		father = blockIdx.z * gridD - blockIdx.z;
		blockD_actual = min(father + gridD, chunkSizeX_d_const[chunkID / chunkNum_h_const[0]]) - father;
		grandfather = blockIdx.x * gridW - blockIdx.x;
		blockW_actual = min(grandfather + gridW, chunkSizeX_y_const[0]) - grandfather;
		blockSlice_actual = blockH_actual * blockW_actual;
		blockSize_actual = blockSlice_actual * blockD_actual;
		chunkSizeX_xy_actual = chunkSizeX_h_const[chunkID % chunkNum_h_const[0]] * chunkSizeX_y_const[0];
		father *= chunkSizeX_xy_actual;
		offset *= chunkSizeX_y_const[0];
		global_base = father + offset + grandfather;
		// Initialize flags
		flag[1] = min(PREDEFINED_MAXDIS_FROM_SOURCE, blockSize_actual - 1);					// The length of the array prefix sum operates on
		flag[2] = 0;
		// Point the buffer pointers to the start of each section in buf
		father = gridDim.x * gridDim.y * blockIdx.z + gridDim.x * blockIdx.y + blockIdx.x;
		buf_ptr[0] = buf + father * gridSize * 4;
		buf_ptr[1] = buf_ptr[0] + gridSize;
		buf_ptr[2] = buf_ptr[1] + gridSize;
		buf_ptr[3] = buf_ptr[2] + gridSize;
	}
	__syncthreads();

	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		// Copy match grid to shared memory
		father = offset / blockSlice_actual;
		grandfather = offset / blockW_actual - father * blockH_actual;
		deg0 = offset % blockW_actual;
		father *= chunkSizeX_xy_actual;
		grandfather *= chunkSizeX_y_const[0];
		tile[offset] = match_global[global_base + father + grandfather + deg0];
		// Initialize buffer
		pre[offset] = USHRT_MAX;															// Initial direct predecessor is undefined
		buf_ptr[2][offset] = gridSize;														// Initial distance from source nodes is the size of the whole grid
		buf_ptr[3][offset] = offset;														// Initial source node is itself

		offset += blockDim.x;
	}
	__syncthreads();

	// ===== Parallel topo sort =====
	deg0 = gridSize;
	do {
		__syncthreads();																	// This barrier prevents threads that still in the last loop from exiting the loop when thread 0 reaches to the next loop faster
		if (threadIdx.x == 0) flag[0] = 0;
		__syncthreads();
		// Stage 1: determine the direct predecessor of each node
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			buf_ptr[1][offset] = 0;
			if (pre[offset] != USHRT_MAX) { offset += blockDim.x; continue; }
			// util will be divided into 2 sections: sec 1 represents the matching of the cell in 6 directions (refer to manual)
			// sec 2 represents if a direction still has incoming dependency after reasoning
			util = 0;
			father = offset % blockW_actual;												// x coordinate of the cell
			if (father > 0) grandfather = 1 - subdivide_short2bits_read(tile[offset - 1], 2); else grandfather = 2;
			divide_int2bits_write(util, 1, grandfather);
			if (father + 1 < blockW_actual) grandfather = 1 - subdivide_short2bits_read(tile[offset + 1], 1); else grandfather = 2;
			divide_int2bits_write(util, 2, grandfather);
			father = offset / blockSlice_actual;											// z coordinate of the cell
			if (father > 0) grandfather = 1 - subdivide_short2bits_read(tile[offset - blockSlice_actual], 3); else grandfather = 2;
			divide_int2bits_write(util, 0, grandfather);
			if (father + 1 < blockD_actual) grandfather = 1 - subdivide_short2bits_read(tile[offset + blockSlice_actual], 0); else grandfather = 2;
			divide_int2bits_write(util, 3, grandfather);
			father = offset / blockW_actual - father * blockH_actual;						// y coordinate of the cell
			if (father > 0) grandfather = 1 - subdivide_short2bits_read(tile[offset - blockW_actual], 5); else grandfather = 2;
			divide_int2bits_write(util, 4, grandfather);
			if (father + 1 < blockH_actual) grandfather = 1 - subdivide_short2bits_read(tile[offset + blockW_actual], 4); else grandfather = 2;
			divide_int2bits_write(util, 5, grandfather);
			// Populate sec 2 of util with information from sec 1
			if (divide_int2bits_read(util, 0) == 1) divide_int2bits_write(util, 6, 1);
			if (divide_int2bits_read(util, 1) == 1) divide_int2bits_write(util, 7, 1);
			if (divide_int2bits_read(util, 2) == 1) divide_int2bits_write(util, 8, 1);
			if (divide_int2bits_read(util, 3) == 1) divide_int2bits_write(util, 9, 1);
			if (divide_int2bits_read(util, 4) == 1) divide_int2bits_write(util, 10, 1);
			if (divide_int2bits_read(util, 5) == 1) divide_int2bits_write(util, 11, 1);
			// Dependency reasoning, refer to manuscrips for details
			// Plane parallel to x-z plane
			if (divide_int2bits_read(util, 1) == 1 && divide_int2bits_read(util, 3) == 1) {
				if (subdivide_short2bits_read(tile[offset - 1], 3) == 1 && subdivide_short2bits_read(tile[offset + blockSlice_actual - 1], 2) == 1) divide_int2bits_write(util, 9, 0);
				else if (subdivide_short2bits_read(tile[offset + blockSlice_actual], 1) == 1 && subdivide_short2bits_read(tile[offset + blockSlice_actual - 1], 0) == 1) divide_int2bits_write(util, 7, 0);
			}
			if (divide_int2bits_read(util, 2) == 1 && divide_int2bits_read(util, 3) == 1) {
				if (subdivide_short2bits_read(tile[offset + 1], 3) == 1 && subdivide_short2bits_read(tile[offset + blockSlice_actual + 1], 1) == 1) divide_int2bits_write(util, 9, 0);
				else if (subdivide_short2bits_read(tile[offset + blockSlice_actual], 2) == 1 && subdivide_short2bits_read(tile[offset + blockSlice_actual + 1], 0) == 1) divide_int2bits_write(util, 8, 0);
			}
			if (divide_int2bits_read(util, 0) == 1 && divide_int2bits_read(util, 1) == 1) {
				if (subdivide_short2bits_read(tile[offset - 1], 0) == 1 && subdivide_short2bits_read(tile[offset - blockSlice_actual - 1], 2) == 1) divide_int2bits_write(util, 6, 0);
				else if (subdivide_short2bits_read(tile[offset - blockSlice_actual], 1) == 1 && subdivide_short2bits_read(tile[offset - blockSlice_actual - 1], 3) == 1) divide_int2bits_write(util, 7, 0);
			}
			if (divide_int2bits_read(util, 0) == 1 && divide_int2bits_read(util, 2) == 1) {
				if (subdivide_short2bits_read(tile[offset + 1], 0) == 1 && subdivide_short2bits_read(tile[offset - blockSlice_actual + 1], 1) == 1) divide_int2bits_write(util, 6, 0);
				else if (subdivide_short2bits_read(tile[offset - blockSlice_actual], 2) == 1 && subdivide_short2bits_read(tile[offset - blockSlice_actual + 1], 3) == 1) divide_int2bits_write(util, 8, 0);
			}
			// Plane parallel to x-y plane
			if (divide_int2bits_read(util, 1) == 1 && divide_int2bits_read(util, 4) == 1) {
				if (subdivide_short2bits_read(tile[offset - 1], 4) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual - 1], 2) == 1) divide_int2bits_write(util, 10, 0);
				else if (subdivide_short2bits_read(tile[offset - blockW_actual], 1) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual - 1], 5) == 1) divide_int2bits_write(util, 7, 0);
			}
			if (divide_int2bits_read(util, 2) == 1 && divide_int2bits_read(util, 4) == 1) {
				if (subdivide_short2bits_read(tile[offset + 1], 4) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual + 1], 1) == 1) divide_int2bits_write(util, 10, 0);
				else if (subdivide_short2bits_read(tile[offset - blockW_actual], 2) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual + 1], 5) == 1) divide_int2bits_write(util, 8, 0);
			}
			if (divide_int2bits_read(util, 1) == 1 && divide_int2bits_read(util, 5) == 1) {
				if (subdivide_short2bits_read(tile[offset - 1], 5) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual - 1], 2) == 1) divide_int2bits_write(util, 11, 0);
				else if (subdivide_short2bits_read(tile[offset + blockW_actual], 1) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual - 1], 4) == 1) divide_int2bits_write(util, 7, 0);
			}
			if (divide_int2bits_read(util, 2) == 1 && divide_int2bits_read(util, 5) == 1) {
				if (subdivide_short2bits_read(tile[offset + 1], 5) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual + 1], 1) == 1) divide_int2bits_write(util, 11, 0);
				else if (subdivide_short2bits_read(tile[offset + blockW_actual], 2) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual + 1], 4) == 1) divide_int2bits_write(util, 8, 0);
			}
			// Plane parallel to y-z plane
			if (divide_int2bits_read(util, 0) == 1 && divide_int2bits_read(util, 4) == 1) {
				if (subdivide_short2bits_read(tile[offset - blockW_actual], 0) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual - blockSlice_actual], 5) == 1) divide_int2bits_write(util, 6, 0);
				else if (subdivide_short2bits_read(tile[offset - blockSlice_actual], 4) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual - blockSlice_actual], 3) == 1) divide_int2bits_write(util, 10, 0);
			}
			if (divide_int2bits_read(util, 0) == 1 && divide_int2bits_read(util, 5) == 1) {
				if (subdivide_short2bits_read(tile[offset + blockW_actual], 0) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual - blockSlice_actual], 4) == 1) divide_int2bits_write(util, 6, 0);
				else if (subdivide_short2bits_read(tile[offset - blockSlice_actual], 5) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual - blockSlice_actual], 3) == 1) divide_int2bits_write(util, 11, 0);
			}
			if (divide_int2bits_read(util, 3) == 1 && divide_int2bits_read(util, 4) == 1) {
				if (subdivide_short2bits_read(tile[offset - blockW_actual], 3) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual + blockSlice_actual], 5) == 1) divide_int2bits_write(util, 9, 0);
				else if (subdivide_short2bits_read(tile[offset + blockSlice_actual], 4) == 1 && subdivide_short2bits_read(tile[offset - blockW_actual + blockSlice_actual], 0) == 1) divide_int2bits_write(util, 10, 0);
			}
			if (divide_int2bits_read(util, 3) == 1 && divide_int2bits_read(util, 5) == 1) {
				if (subdivide_short2bits_read(tile[offset + blockW_actual], 3) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual + blockSlice_actual], 4) == 1) divide_int2bits_write(util, 9, 0);
				else if (subdivide_short2bits_read(tile[offset + blockSlice_actual], 5) == 1 && subdivide_short2bits_read(tile[offset + blockW_actual + blockSlice_actual], 0) == 1) divide_int2bits_write(util, 11, 0);
			}
			// Decide the number of incoming edges for the cell
			father = divide_int2bits_read(util, 6) + divide_int2bits_read(util, 7) + divide_int2bits_read(util, 8) + divide_int2bits_read(util, 9) + divide_int2bits_read(util, 10) + divide_int2bits_read(util, 11);
			if (father == 0) pre[offset] = deg0;
			else if (father == 1) {
				if (divide_int2bits_read(util, 6)) pre[offset] = offset - blockSlice_actual;
				else if (divide_int2bits_read(util, 7)) pre[offset] = offset - 1;
				else if (divide_int2bits_read(util, 8)) pre[offset] = offset + 1;
				else if (divide_int2bits_read(util, 9)) pre[offset] = offset + blockSlice_actual;
				else if (divide_int2bits_read(util, 10)) pre[offset] = offset - blockW_actual;
				else pre[offset] = offset + blockW_actual;
				buf_ptr[2][offset]++;
				buf_ptr[3][offset] = pre[offset];
			}
			offset += blockDim.x;
		}
		__syncthreads();

		// Stage 2: delete the nodes that can trace back to a source node with no dependency (degree 0)
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[3][offset] < gridSize) {
				father = buf_ptr[3][offset];
				grandfather = pre[father];
				while (grandfather < gridSize) {
					buf_ptr[2][offset]++;
					father = grandfather;
					grandfather = pre[grandfather];
				}
				// Cannot trace to a degree 0 source node
				if (grandfather == USHRT_MAX) {
					buf_ptr[3][offset] = father; flag[0] = 1;
				}
				// Successfully trace to a degree 0 source node
				else {
					buf_ptr[3][offset] = grandfather;
					tile[offset] = 2730;
					buf_ptr[2][offset] -= gridSize;
					atomicAddShort(&buf_ptr[1][buf_ptr[2][offset]], 1);
				}
			}
			offset += blockDim.x;
		}
		__syncthreads();

		// Find the length of buf_ptr[1] that needs to be scanned
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[1][offset] > 0 && offset > flag[1]) atomicMax(&flag[1], offset);
			offset += blockDim.x;
		}
		__syncthreads();

		/*
			Parallel Prefix-Sum (reference: https://people.cs.vt.edu/yongcao/teaching/cs5234/spring2013/slides/Lecture10.pdf)
		*/
		father = 1;																					// Reuse variable for stride
		// ===== Reduction Step =====
		while (father <= (flag[1] + 1) / 2) {
			offset = threadIdx.x;
			util = (offset + 1) * father * 2 - 1;
			while (util < flag[1] + 1) {
				buf_ptr[1][util] += buf_ptr[1][util - father];
				offset = offset + blockDim.x;
				util = (offset + 1) * father * 2 - 1;
			}
			father *= 2;
			__syncthreads();
		}
		// ===== Post Scan Step =====
		father /= 2;
		while (father > 0) {
			offset = threadIdx.x;
			util = (offset + 1) * father * 2 - 1;
			while (util + father < flag[1] + 1) {
				buf_ptr[1][util + father] += buf_ptr[1][util];
				offset = offset + blockDim.x;
				util = (offset + 1) * father * 2 - 1;
			}
			father /= 2;
			__syncthreads();
		}
		father = buf_ptr[1][flag[1]];
		__syncthreads();

		// Assign topological order for the current iteration
		offset = threadIdx.x;
		while (offset < blockSize_actual) {
			if (buf_ptr[2][offset] < gridSize) {
				buf_ptr[0][atomicSubShort(&buf_ptr[1][buf_ptr[2][offset]], 1) - 1 + deg0 - gridSize] = offset;
				buf_ptr[2][offset] += gridSize;
			}
			offset += blockDim.x;
		}
		__syncthreads();
		deg0 += father;
		__syncthreads();
	} while (flag[0] != 0);

	// Collect indices of all critical cells with dim >= 1 and put them into buf_ptr[1].
	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		// Reorder topo order and store in buf_ptr[2] s.t. X is at position buf_ptr[2][X] in the topological order
		buf_ptr[2][buf_ptr[0][offset]] = offset;
		// Gather the indices of critical cells and store in buf_ptr[1]
		father = offset / blockSlice_actual;
		grandfather = offset / blockW_actual - father * blockH_actual;
		deg0 = offset % blockW_actual;
		father *= chunkSizeX_xy_actual;
		grandfather *= chunkSizeX_y_const[0];
		util = global_base + father + grandfather + deg0;
		if ((crit_global[util] & 7) > 1) buf_ptr[1][atomicAdd(&flag[2], 1)] = offset;
		offset += blockDim.x;
	}
	__syncthreads();
	if (threadIdx.x == 0) {
		if (flag[2] > PATHCNT_BUF_BITS) { printf("Error: required buffer %u not satisfied, increase 'PATHCNT_BUF_SIZE'\n", flag[2]); return; }
		father = gridDim.x * gridDim.y * blockIdx.z + gridDim.x * blockIdx.y + blockIdx.x;
		chunkCritNum[father] = flag[2];
		buf_ptr[3][0] = blockH_actual;
		buf_ptr[3][1] = blockW_actual;
		buf_ptr[3][2] = blockD_actual;
		buf_ptr[3][3] = blockSlice_actual;
		buf_ptr[3][4] = blockSize_actual;
	}
}

template<ushort_ gridH, ushort_ gridW, ushort_ gridD, ushort_ gridSize>
__launch_bounds__(PATHCNT_BUF_SIZE)
__global__ void pathCount_kernel3D(
	const ushort_                  chunkID,
	const ushort_* __restrict__    match_global,
	uint_*         __restrict__    pathCntBuf,
	ushort_*       __restrict__    topoSrtbuf,
	const ushort_* __restrict__    chunkCritNum
)
{
	/*
		COMPUTING HOMOLOGY AND PERSISTENT HOMOLOGY USING ITERATED MORSE DECOMPOSITION
		PAWE L D LOTKO AND HUBERT WAGNER
		https://arxiv.org/pdf/1210.1429.pdf
		Algorithm 4

		Algorithm 4 is adapted and optimized for GPU programming in the following way:
		Each block will have PATHCNT_BUF_SIZE threads, which is a multiple of 32 and equal of less than 1024.
		Each block will have a buffer of size PATHCNT_BUF_SIZE * gridSize. The buffer is organized in consecutive
		sections of size PATHCNT_BUF_SIZE in the topological order. So the first section of PATHCNT_BUF_SIZE
		unsigned ints belong to the first cell in the topological order. [This means the maximum number of critical
		cells from which alternating paths originate this cell can track is sizeof(unsigned int) * 8 * PATHCNT_BUF_SIZE.]
		There are a total of gridSize sections. In each section, each of the thread will have their own lane of 1 unsigned int.
		As unsigned int has 32 bits, each thread will be computing path counting for 32 different cells with each using one
		bit for disparity (odd or even). The thread chooses cells in topological order in a strided way such that consecutive
		addresses are accessed by threads in a warp.

		@match_global: the Morse matching grid in global memory
		@pathCntBuf:   the buffer for path counting in global memory. Each block has a buffer of size PATHCNT_BUF_SIZE * gridSize.
		@topoSrtBuf:   the global buffer for topological sorting in global memory directly from the previous kernel.
		@chunkCritNum: the number of critical cells in each block of the current chunk

		Definitions of the parameters for path counting buffer
		@PATHCNT_BUF_SIZE: the size of the buffer for path counting in each block

	*/

	// Shared memory for the current block
	__shared__ uint_*	pathCnt;															// Pointer to the global memory buffer for path counting
	__shared__ ushort_* buf_ptr[4];															// Pointers to the global memory buffer for topological sorting
	__shared__ uint_    global_base, chunkSizeX_xy_actual;
	__shared__ ushort_  blockH_actual, blockW_actual, blockD_actual, blockSlice_actual, blockSize_actual, critNum;
	// Declare variables using registers
	ushort_				match;
	uint_				cell_id, cell_coord, iter, offset, util;

	// Initialize shared memory
	if (threadIdx.x == 0) {
		cell_id = gridDim.x * gridDim.y * blockIdx.z + gridDim.x * blockIdx.y + blockIdx.x;	// block offset
		critNum = chunkCritNum[cell_id];													// number of critical cells in the block
		// Topological sorting buffer pointers initialization
		buf_ptr[0] = topoSrtbuf + cell_id * gridSize * 4;
		buf_ptr[1] = buf_ptr[0] + gridSize;
		buf_ptr[2] = buf_ptr[1] + gridSize;
		buf_ptr[3] = buf_ptr[2] + gridSize;
		// Path counting buffer pointer initialization
		pathCnt = pathCntBuf + cell_id * gridSize * PATHCNT_BUF_SIZE;
		// Find the actual size of the block
		blockH_actual			= buf_ptr[3][0];
		blockW_actual			= buf_ptr[3][1];
		blockD_actual			= buf_ptr[3][2];
		blockSlice_actual		= buf_ptr[3][3];
		blockSize_actual		= buf_ptr[3][4];
		chunkSizeX_xy_actual	= chunkSizeX_h_const[chunkID % chunkNum_h_const[0]] * chunkSizeX_y_const[0];
		// Find the global offset to the start of the block in the matching grid
		cell_id		= blockIdx.x * gridW - blockIdx.x;										// x offsets of the block grid
		offset		= (blockIdx.y * gridH - blockIdx.y) * chunkSizeX_y_const[0];			// y offsets of the block grid											
		cell_coord	= (blockIdx.z * gridD - blockIdx.z) * chunkSizeX_xy_actual;				// z offsets of the block grid											
		global_base = cell_coord + offset + cell_id;
	}
	__syncthreads();

	// Lane pointer to avoid repeated index multiplies
	uint_* lane = pathCnt + threadIdx.x;
	// Lane pointer to avoid repeated index multiplies
	util = 1u;
	cell_coord = 0u;

	// Initialize pathCnt buffer
#pragma unroll
	offset = 0;
	for (iter = 0; iter < blockSize_actual; iter++) { lane[offset] = 0; offset += PATHCNT_BUF_SIZE; }
	for (iter = 0; iter < BITS_PER_THREAD; iter++) {
		offset = threadIdx.x + iter * PATHCNT_BUF_SIZE;
		if (offset >= critNum) break;
		cell_id = buf_ptr[1][offset];
		lane[buf_ptr[2][cell_id] * PATHCNT_BUF_SIZE] = util;
		util <<= 1u;
		cell_coord++;
	}
	if (threadIdx.x < gridSize) buf_ptr[3][threadIdx.x] = (ushort_)cell_coord;
	__syncthreads();

	// Compute path counting (disparity)
	uint_* lane_iter = lane;
	for (iter = 0; iter < blockSize_actual; iter++, lane_iter += PATHCNT_BUF_SIZE) {
		// Get the cell id in topological order and retrieve its global offset in the matching grid
		cell_id		= buf_ptr[0][iter];
		// slice (z), col (x), row (y)
		util		= cell_id / blockSlice_actual;						 // z slice
		offset		= cell_id % blockW_actual;                           // x col
		uint_ row	= cell_id / blockW_actual - util * blockH_actual;    // y row
		// global address -> load match
		uint_ addr = offset + util * chunkSizeX_xy_actual + row * chunkSizeX_y_const[0] + global_base;
		match = match_global[addr];
		// accumulator
		cell_coord = *lane_iter;

		// Decide neighbors in x axis
		if (offset > 0 && subdivide_short2bits_read(match, 1) == 1)					cell_coord ^= lane[buf_ptr[2][cell_id - 1] * PATHCNT_BUF_SIZE];
		if (offset + 1 < blockW_actual && subdivide_short2bits_read(match, 2) == 1)	cell_coord ^= lane[buf_ptr[2][cell_id + 1] * PATHCNT_BUF_SIZE];
		// Decide neighbors in z axis
		if (util > 0 && subdivide_short2bits_read(match, 0) == 1)					cell_coord ^= lane[buf_ptr[2][cell_id - blockSlice_actual] * PATHCNT_BUF_SIZE];
		if (util + 1 < blockD_actual && subdivide_short2bits_read(match, 3) == 1)	cell_coord ^= lane[buf_ptr[2][cell_id + blockSlice_actual] * PATHCNT_BUF_SIZE];
		// Decide neighbors in y axis
		if (row > 0 && subdivide_short2bits_read(match, 4) == 1)					cell_coord ^= lane[buf_ptr[2][cell_id - blockW_actual] * PATHCNT_BUF_SIZE];
		if (row + 1 < blockH_actual && subdivide_short2bits_read(match, 5) == 1)	cell_coord ^= lane[buf_ptr[2][cell_id + blockW_actual] * PATHCNT_BUF_SIZE];
		// Write the result to the buffer
		*lane_iter = cell_coord;
	}
	__syncthreads();

	// Carry the information to the next kernel
	if (threadIdx.x == 0) {
		buf_ptr[2][0] = blockH_actual;
		buf_ptr[2][1] = blockW_actual;
		buf_ptr[2][2] = blockD_actual;
		buf_ptr[2][3] = blockSlice_actual;
		buf_ptr[2][4] = blockSize_actual;
	}
}


template<typename type, ushort_ gridH, ushort_ gridW, ushort_ gridD, ushort_ gridSize>
__global__ void bitCheck_kernel3D(
	cudaTextureObject_t		img,
	const ushort_			chunkID,
	uchar_*					crit_global,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ulonglong2*				bndmat,
	type*					filtVals,
	uchar2*					offsets
)
{
	/*
		This function checks the path counting buffer from pathCount_kernel3D kernel. Each element in the buffer indicates the number
		of alternating paths from multiple source nodes to the current node. Note that the block layoaut of this kernel is the same as
		topoSort_kernel3D kernel. This means that a thread in this kernel will process lanes different from the previous kernel. Each
		thread will need to determine the source nodes itself.
		----- Inputs -----
		@img:			input chunk in the texture memory
		@chunkID:		id of the chunk
		@crit_global:	critical information (critical + cell offset) in the global memory
		@pathCntBuf:	the buffer for path counting in global memory. Each block has a buffer of size PATHCNT_BUF_SIZE * gridSize.
		@topoSrtBuf:	the global buffer for topological sorting in global memory directly from the previous kernel.
		----- Outputs -----
		@bndmat:		the boundary relations in global memory
		@filtVals:		the filtration values corresponding to the cells in bndmat
	*/

	// Shared memory declaration
	__shared__ uchar_		crit_shared[gridSize];													// Critical information for the block
	__shared__ uint_*		pathCnt;																// Path counting buffer pointer
	__shared__ ushort_*		buf_ptr[3];																// Topological sorting buffer pointers
	__shared__ ulonglong2*	bnd;																	// Boundary matrix pointer
	__shared__ type*		filt;																	// Filtration values pointer
	__shared__ uchar2*		cellOffset;																// Cell offsets pointer
	__shared__ uint_		global_base;
	__shared__ uint_		bndmat_atomic, buffSize_actual;
	__shared__ ushort_		blockH_actual, blockW_actual, blockSlice_actual, blockSize_actual;
	__shared__ uint_		blkOffsetX, blkOffsetY, blkOffsetZ, chunkSizeX_xy_actual;
	__shared__ ll_			chunkOffsetAdapted;

	// Register declaration
	uint_	offset, util;
	uint_	cell_id, crit_id, buff_id;
	ull_	cell_coord, crit_coord;
	uint_	ux, uy, uz;
	uint_	critNum, bndmat_pos, i;
	type	val;

	// Initialize shared memory
	if (threadIdx.x == 0) {
		offset = gridDim.x * gridDim.y * blockIdx.z + gridDim.x * blockIdx.y + blockIdx.x;		// block offset
		bndmat_atomic = 0;																		// Initialize the mutex
		// Initialize the buffer pointers
		pathCnt		= pathCntBuf + offset * gridSize * PATHCNT_BUF_SIZE;
		bnd			= bndmat + offset * bndmatSize_const[0];
		filt		= filtVals + offset * bndmatSize_const[0] * 2;
		cellOffset	= offsets + offset * bndmatSize_const[0];
		// Topological sorting buffer pointers initialization
		buf_ptr[0]	= topoSrtbuf + offset * gridSize * 4;
		buf_ptr[1]	= buf_ptr[0] + gridSize;
		buf_ptr[2]	= buf_ptr[1] + 2 * gridSize;												// This is buf_ptr[3] in the previous 2 kernels
		// Find the actual size of the block
		blockH_actual		= buf_ptr[1][gridSize];												// The auxiliary information is stored in buf_ptr[2]
		blockW_actual		= buf_ptr[1][gridSize + 1];
		blockSlice_actual	= buf_ptr[1][gridSize + 3];
		blockSize_actual	= buf_ptr[1][gridSize + 4];
		chunkSizeX_xy_actual = chunkSizeX_h_const[chunkID % chunkNum_h_const[0]] * chunkSizeX_y_const[0];
		buffSize_actual		= blockSize_actual * PATHCNT_BUF_SIZE;
		// Find the global offset to the start of the block in the matching grid
		ux = blockIdx.x * gridW - blockIdx.x;													// x offsets of the block grid
		uy = blockIdx.y * gridH - blockIdx.y;
		uy *= chunkSizeX_y_const[0];															// y offsets of the block grid
		uz = blockIdx.z * gridD - blockIdx.z;
		uz *= chunkSizeX_xy_actual;																// z offsets of the block grid
		global_base = uz + uy + ux;
		blkOffsetX = blockIdx.x * gridW - blockIdx.x + 2;										// adapted x offset of block in the chunk
		blkOffsetY = blockIdx.y * gridH - blockIdx.y + 4;										// adapted y offset of block in the chunk
		blkOffsetZ = blockIdx.z * gridD - blockIdx.z + 4;										// adapted z offset of block in the chunk
		chunkOffsetAdapted = 1LL * chunkOffsetX_const[chunkID] - 1LL * 4 * (imgSizeX_xy_const[0] + chunkSizeX_y_const[0]) - 2;
	}
	__syncthreads();

	// Initialize critical information in shared memory
	offset = threadIdx.x;
	while (offset < blockSize_actual) {
		uz = offset / blockSlice_actual;														// z coordinate of the cell in the block
		uy = offset / blockW_actual - uz * blockH_actual;										// y coordinate of the cell in the block
		ux = offset % blockW_actual;															// x coordinate of the cell in the block
		uz *= chunkSizeX_xy_actual;																// z offset in the block
		uy *= chunkSizeX_y_const[0];															// y offset in the block
		cell_coord = global_base + uz + uy + ux;												// cell offset in the chunk
		crit_shared[offset] = crit_global[cell_coord];
		offset += blockDim.x;
	}
	__syncthreads();

	offset = threadIdx.x;
	while (offset < buffSize_actual) {
		util = pathCnt[offset];																	// get the buffer lane content
		cell_id = buf_ptr[0][offset / PATHCNT_BUF_SIZE];										// which cell this PATHCNT_BUF_SIZE buffer section belongs to
		if (util == 0 || (crit_shared[cell_id] & 7) == 0 || (crit_shared[cell_id] & 7) > maxDim_const[0])
		{ offset += blockDim.x; continue; }														// no odd path to this cell or this cell is not criical
		buff_id = offset % PATHCNT_BUF_SIZE;													// which buffer lane in this section
		critNum = (buff_id >= gridSize) ? 0u : buf_ptr[2][buff_id];								// how many critical cells this lane handles
		if (critNum == 0) break;
		// Retrieve the cell offset in the chunk
		uz = cell_id / blockSlice_actual;
		uy = cell_id / blockW_actual - uz * blockH_actual + blkOffsetY;
		ux = cell_id % blockW_actual + blkOffsetX;
		uz += blkOffsetZ;
		cell_coord = 1ULL * uz * imgSizeX_xy_const[0] + 1ULL * uy * chunkSizeX_y_const[0] + ux + chunkOffsetAdapted;
		findsource3D(crit_shared[cell_id], ux, uy, uz);
		val = tex3D<type>(img, ux, uy, uz);

		// Loop through each bit in the lane content
#pragma unroll
		for (i = 0; i < critNum; i++) {
			if (util & 1u) {																		// odd number of alternating paths
				crit_id = buf_ptr[1][buff_id + i * PATHCNT_BUF_SIZE];								// which critical cell cell_id has odd paths to

				// Reject duplicate boundary relations from border faces and edges
				crit_coord	= cell_id / blockW_actual - (cell_id / blockSlice_actual) * blockH_actual;
				ux			= crit_id / blockW_actual - (crit_id / blockSlice_actual) * blockH_actual;
				bndmat_pos	= blockSize_actual / blockSlice_actual - 1;
				uy			= cell_id % blockW_actual;
				uz			= crit_id % blockW_actual;
				// Conditions to filter invalid boundary relations
				if (	crit_id == cell_id ||																											// cell indices should be different
					((	crit_shared[crit_id] & 7) - (crit_shared[cell_id] & 7)) != 1 ||																	// crit indices - cell indices should be 1

					(	crit_id < blockSlice_actual && cell_id < blockSlice_actual && (chunkID >= chunkNum_h_const[0] || blockIdx.z != 0)) ||			// if both cells have z = 0, only process the front most block in the front most chunk, skip the rest
					(	ux == 0 && crit_coord == 0	&& (chunkID % chunkNum_h_const[0] != 0 || blockIdx.y != 0)) ||										// if both cells have y = 0, only process the top most block in the top most chunk, skip the rest
					(	uz == 0 && uy == 0 && blockIdx.x != 0) ||																						// if both cells have x = 0, only process the left most block

					// Remove duplicate relations from edges 1, 2, 9, 10 (vertical edges in front and back faces)
					(	uz == 0 && uy == 0 && crit_id / blockSlice_actual == bndmat_pos && cell_id / blockSlice_actual == bndmat_pos && blockIdx.x != 0 ) ||
					(	uz == 0 && uy == 0 && crit_id < blockSlice_actual && cell_id < blockSlice_actual && (chunkID >= chunkNum_h_const[0] || blockIdx.z != 0)) ||
					(	uz == blockW_actual - 1 && uy == blockW_actual - 1 && crit_id < blockSlice_actual && cell_id < blockSlice_actual && (chunkID >= chunkNum_h_const[0] || blockIdx.z != 0)) ||

					// Remove duplicate relations from edges 0, 3, 8, 11 (horizontal edges in front and back faces)
					(	ux == 0 && crit_coord == 0 && crit_id / blockSlice_actual == bndmat_pos && cell_id / blockSlice_actual == bndmat_pos && (chunkID % chunkNum_h_const[0] != 0 || blockIdx.y != 0)) ||
					(	ux == 0 && crit_coord == 0 && crit_id < blockSlice_actual && cell_id < blockSlice_actual && (chunkID >= chunkNum_h_const[0] || blockIdx.z != 0)) ||
					(	ux == blockH_actual - 1 && crit_coord == blockH_actual - 1 && crit_id < blockSlice_actual && cell_id < blockSlice_actual && (chunkID >= chunkNum_h_const[0] || blockIdx.z != 0)) ||

					// Remove duplicate relations from edges 4, 5, 6, 7 (depth direction edges in top and bottom faces)
					(	uz == 0 && uy == 0 && ux == blockH_actual - 1 && crit_coord == blockH_actual - 1 && blockIdx.x != 0) ||
					(	uz == 0 && uy == 0 && ux == 0 && crit_coord == 0 && (chunkID % chunkNum_h_const[0] != 0 || blockIdx.y != 0)) ||
					(	uz == blockW_actual - 1 && uy == blockW_actual - 1 && ux == 0 && crit_coord == 0 && (chunkID % chunkNum_h_const[0] != 0 || blockIdx.y != 0))
				)
				{
					util >>= 1; continue;
				}

				bndmat_pos = atomicAdd(&bndmat_atomic, 1);
				uz = crit_id / blockSlice_actual;
				uy = crit_id / blockW_actual - uz * blockH_actual + blkOffsetY;
				ux = crit_id % blockW_actual + blkOffsetX;
				uz += blkOffsetZ;
				crit_coord = 1ULL * uz * imgSizeX_xy_const[0] + 1ULL * uy * chunkSizeX_y_const[0] + ux + chunkOffsetAdapted;

				findsource3D(crit_shared[crit_id], ux, uy, uz);
				filt[(bndmat_pos << 1)    ]	= tex3D<type>(img, ux, uy, uz);
				filt[(bndmat_pos << 1) + 1]	= val;
				// Store boundary relations in global memory
				bnd[bndmat_pos]				= make_ulonglong2(crit_coord, cell_coord);
				// Store cell offsets in global memory
				cellOffset[bndmat_pos]		= make_uchar2(crit_shared[crit_id] >> 3, crit_shared[cell_id] >> 3);
			}
			util >>= 1u;
		}
		offset += blockDim.x;
	}
}

__host__ void  topoSort_2D(
	const ushort_			chunkID,
	uchar_* match,
	uchar_* crit,
	ushort_* topoSrtbuf,
	ushort_* chunkCritNum,
	const uint2& chunkSizeX,
	const uint2& blockSize,
	const uint2& blockSizeX,
	cudaStream_t& stream
)
{
	// define block size
	dim3 block(std::min((uint_)iDivUp((uint_)PRODUCT2(blockSizeX.x, blockSizeX.y), (uint_)32) * 32, (uint_)1024));
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.y - 1));

#define MAP(b)        ( (2 * (b)) + 1 )
#define AREA(bx,by)   ( MAP(bx) * MAP(by) )

#define GEN_CASE(BX,BY)     \
  case ((BX)*10 + (BY)):	\
	topoSort_kernel2D<MAP(BY), MAP(BX), AREA(BX,BY)><<<grid, block, 0, stream>>>(chunkID, match, crit, topoSrtbuf, chunkCritNum); break;

#define GEN_Y(BX) GEN_CASE(BX,2) GEN_CASE(BX,4) GEN_CASE(BX,8) GEN_CASE(BX,16) GEN_CASE(BX,32)
	// lauch kernel
	switch (static_cast<int>(blockSize.x) * 10 + static_cast<int>(blockSize.y)) {
		GEN_Y(2) GEN_Y(4) GEN_Y(8) GEN_Y(16) GEN_Y(32)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_CASE
#undef AREA
#undef MAP
}

__host__ void pathCount_2D(
	const ushort_			chunkID,
	uchar_* match,
	uint_* pathCntBuf,
	ushort_* topoSrtbuf,
	ushort_* chunkCritNum,
	const					uint2& chunkSizeX,
	const					uint2& blockSize,
	const					uint2& blockSizeX,
	cudaStream_t& stream
)
{
	// define block size
	dim3 block(PATHCNT_BUF_SIZE);
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.y - 1));

#define MAP(b)        ( (2 * (b)) + 1 )
#define AREA(bx,by)   ( MAP(bx) * MAP(by) )

#define GEN_CASE(BX,BY)     \
  case ((BX)*10 + (BY)):	\
	pathCount_kernel2D<MAP(BY), MAP(BX), AREA(BX,BY)><<<grid, block, 0, stream>>>(chunkID, match, pathCntBuf, topoSrtbuf, chunkCritNum); break;

#define GEN_Y(BX) GEN_CASE(BX,2) GEN_CASE(BX,4) GEN_CASE(BX,8) GEN_CASE(BX,16) GEN_CASE(BX,32)
	// lauch kernel
	switch (static_cast<int>(blockSize.x) * 10 + static_cast<int>(blockSize.y)) {
		GEN_Y(2) GEN_Y(4) GEN_Y(8) GEN_Y(16) GEN_Y(32)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_CASE
#undef AREA
#undef MAP
}

template <typename type>
__host__ void  bitCheck_2D(
	cudaTextureObject_t& chunk,
	const ushort_			chunkID,
	uchar_* crit,
	uint_* pathCntBuf,
	ushort_* topoSrtbuf,
	ulonglong2* bndmat,
	type* filtVals,
	uchar2* offsets,
	const					uint2& chunkSizeX,
	const					uint2& blockSize,
	const					uint2& blockSizeX,
	cudaStream_t& stream
)
{
	// define block size
	dim3 block(std::min((uint_)iDivUp((uint_)PRODUCT2(blockSizeX.x, blockSizeX.y), (uint_)32) * 32, (uint_)1024));
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.y - 1));

#define MAP(b)        ( (2 * (b)) + 1 )
#define AREA(bx,by)   ( MAP(bx) * MAP(by) )

#define GEN_CASE(BX,BY)     \
  case ((BX)*10 + (BY)):	\
	bitCheck_kernel2D<type, MAP(BY), MAP(BX), AREA(BX,BY)><<<grid, block, 0, stream>>>(chunk, chunkID, crit, pathCntBuf, topoSrtbuf, bndmat, filtVals, offsets); break;

#define GEN_Y(BX) GEN_CASE(BX,2) GEN_CASE(BX,4) GEN_CASE(BX,8) GEN_CASE(BX,16) GEN_CASE(BX,32)
	// lauch kernel
	switch (static_cast<int>(blockSize.x) * 10 + static_cast<int>(blockSize.y)) {
		GEN_Y(2) GEN_Y(4) GEN_Y(8) GEN_Y(16) GEN_Y(32)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_CASE
#undef AREA
#undef MAP
}
template __host__ void bitCheck_2D<int>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, int*, uchar2*, const uint2&, const uint2&, const uint2&, cudaStream_t&);
template __host__ void bitCheck_2D<float>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, float*, uchar2*, const uint2&, const uint2&, const uint2&, cudaStream_t&);
template __host__ void bitCheck_2D<uchar_>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, uchar_*, uchar2*, const uint2&, const uint2&, const uint2&, cudaStream_t&);
template __host__ void bitCheck_2D<ushort_>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, ushort_*, uchar2*, const uint2&, const uint2&, const uint2&, cudaStream_t&);

__host__ void topoSort_3D(
	const ushort_			chunkID,
	ushort_*				match,
	uchar_*					crit,
	ushort_*				topoSrtbuf,
	ushort_*				chunkCritNum,
	const					uint3& chunkSizeX,
	const					uint3& blockSize,
	const					uint3& blockSizeX,
	cudaStream_t&			stream
)
{
	// define block size
	dim3 block(std::min((uint_)iDivUp((uint_)PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z), (uint_)32) * 32, (uint_)1024));
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.y - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.z - 1, blockSizeX.z - 1));

#define MAP(b) ((2*(b)) + 1)
#define VOL(bx,by,bz) (MAP(bx) * MAP(by) * MAP(bz))

#define GEN_CASE(BX,BY,BZ)         \
  case ((BX)*100 + (BY)*10 + (BZ)): \
	topoSort_kernel3D<MAP(BX), MAP(BY), MAP(BZ), VOL(BX,BY,BZ)><<<grid, block, 0, stream>>>(chunkID, match, crit, topoSrtbuf, chunkCritNum); break;

#define GEN_Z(BX,BY) GEN_CASE(BX,BY,2) GEN_CASE(BX,BY,4) GEN_CASE(BX,BY,8)
#define GEN_Y(BX)    GEN_Z(BX,2)      GEN_Z(BX,4)      GEN_Z(BX,8)
	// lauch kernel
	switch (int(blockSize.x) * 100 + int(blockSize.y) * 10 + int(blockSize.z)) {
		GEN_Y(2)  GEN_Y(4)  GEN_Y(8)  GEN_Y(16)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_Z
#undef GEN_CASE
#undef VOL
#undef MAP
}

__host__ void pathCount_3D(
	const ushort_			chunkID,
	ushort_*				match,
	uint_*					pathCntBuf,
	ushort_*				topoSrtbuf,
	ushort_*				chunkCritNum,
	const					uint3& chunkSizeX,
	const					uint3& blockSize,
	const					uint3& blockSizeX,
	cudaStream_t&			stream
)
{
	// define block size
	dim3 block(PATHCNT_BUF_SIZE);
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.y - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.z - 1, blockSizeX.z - 1));

#define MAP(b) ((2*(b)) + 1)
#define VOL(bx,by,bz) (MAP(bx) * MAP(by) * MAP(bz))

#define GEN_CASE(BX,BY,BZ)         \
  case ((BX)*100 + (BY)*10 + (BZ)): \
	pathCount_kernel3D<MAP(BX), MAP(BY), MAP(BZ), VOL(BX,BY,BZ)><<<grid, block, 0, stream>>>(chunkID, match, pathCntBuf, topoSrtbuf, chunkCritNum); break;

#define GEN_Z(BX,BY) GEN_CASE(BX,BY,2) GEN_CASE(BX,BY,4) GEN_CASE(BX,BY,8)
#define GEN_Y(BX)    GEN_Z(BX,2)      GEN_Z(BX,4)      GEN_Z(BX,8)
	// lauch kernel
	switch (int(blockSize.x) * 100 + int(blockSize.y) * 10 + int(blockSize.z)) {
		GEN_Y(2)  GEN_Y(4)  GEN_Y(8)  GEN_Y(16)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_Z
#undef GEN_CASE
#undef VOL
#undef MAP
}

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
) {
	// define block size
	dim3 block(std::min((uint_)iDivUp((uint_)PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z), (uint_)32) * 32, (uint_)1024));
	// define grid size
	dim3 grid(iDivUp(chunkSizeX.y - 1, blockSizeX.y - 1), iDivUp(chunkSizeX.x - 1, blockSizeX.x - 1), iDivUp(chunkSizeX.z - 1, blockSizeX.z - 1));

#define MAP(b) ((2*(b)) + 1)
#define VOL(bx,by,bz) (MAP(bx) * MAP(by) * MAP(bz))

#define GEN_CASE(BX,BY,BZ)         \
  case ((BX)*100 + (BY)*10 + (BZ)): \
	bitCheck_kernel3D<type, MAP(BX), MAP(BY), MAP(BZ), VOL(BX,BY,BZ)><<<grid, block, 0, stream>>>(img, chunkID, crit, pathCntBuf, topoSrtbuf, bndmat, filtVals, offsets); break;

#define GEN_Z(BX,BY) GEN_CASE(BX,BY,2) GEN_CASE(BX,BY,4) GEN_CASE(BX,BY,8)
#define GEN_Y(BX)    GEN_Z(BX,2)      GEN_Z(BX,4)      GEN_Z(BX,8)
	// lauch kernel
	switch (int(blockSize.x) * 100 + int(blockSize.y) * 10 + int(blockSize.z)) {
		GEN_Y(2)  GEN_Y(4)  GEN_Y(8)  GEN_Y(16)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef GEN_Y
#undef GEN_Z
#undef GEN_CASE
#undef VOL
#undef MAP
}
template __host__ void bitCheck_3D<uchar_>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, uchar_*, uchar2*, const uint3&, const uint3&, const uint3&, cudaStream_t&);
template __host__ void bitCheck_3D<ushort_>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, ushort_*, uchar2*, const uint3&, const uint3&, const uint3&, cudaStream_t&);
template __host__ void bitCheck_3D<int>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, int*, uchar2*, const uint3&, const uint3&, const uint3&, cudaStream_t&);
template __host__ void bitCheck_3D<float>(cudaTextureObject_t&, const ushort_, uchar_*, uint_*, ushort_*, ulonglong2*, float*, uchar2*, const uint3&, const uint3&, const uint3&, cudaStream_t&);