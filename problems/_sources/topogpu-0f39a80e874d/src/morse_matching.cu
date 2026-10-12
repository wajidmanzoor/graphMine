#include "util_cu.cuh"
#include "morse_matching.cuh"

// Constant memory declaration
__constant__ uint_ chunkNum_h_const[1];							// number of chunks in height
__constant__ uint_ imgSize_y_const[1];							// input image width
__constant__ uint_ chunkSize_h_const[maxChunkNum_h_];			// height of each chunk
__constant__ uint_ chunkSize_d_const[maxChunkNum_d_];			// depth of each chunk

// Write to cubicle offset section (high 5 bits) of crit_mask
#define writeCubi(t, v) (t = t | (v << 3))
// Write to critical mask section (low 3 bits) of crit_mask
#define writeCrit(t, v) ((t) |= (v))

__device__ uint_ blockDimXSetting_map2_continuousindex[33] = {
	/* Initialize a global array blockDimXSetting_map2_continuousindex of size 33 with 0 except for the following indices:
		blockDim.x. Note the chunkSize.x (chunk height) is reversed in blockDim.x (block width).
		2, 4, 8, 16, 32
	*/
	0, 0, 0, 0, 1, 0, 0, 0,
	2, 0, 0, 0, 0, 0, 0, 0,
	3, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 0, 0, 0, 0, 0, 0, 4
};

__device__ uint_ blockDimSetting_map2_continuousindex[169] = {
	/* Initialize a global array blockDimSetting_map2_continuousindex of size 169 with 0 except for the following indices:
		blockDim.y * 10 + blockDim.x. Note the chunkSize.x and .y are reversed in blockDim.x and .y.
		22, 42, 62, 82, 102, 122, 142, 162
		24, 44, 64, 84, 104, 124, 144, 164
		26, 46, 66, 86, 106, 126, 146, 166
		28, 48, 68, 88, 108, 128, 148, 168
	*/
	0, 0, 0,  0, 0,  0, 0,  0, 0,  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 0,  0, 1,  0, 2,  0, 3,  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 4,  0, 5,  0, 6,  0, 7,  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 8,  0, 9,  0, 10, 0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 12, 0, 13, 0, 14, 0, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 16, 0, 17, 0, 18, 0, 19, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 20, 0, 21, 0, 22, 0, 23, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 24, 0, 25, 0, 26, 0, 27, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 28, 0, 29, 0, 30, 0, 31
};

__device__ int cube_offsetX_array[5][9] = {
	/*
		Offset to 9 cells around the pixel
		0: pixel itself; 1: top edge; 2: left edge; 3: right edge; 4: bottom edge;
		5: top left vertex; 6: top right vertex; 7: bottom left vertex; 8: bottom right vertex
	*/
	// Dimx = 2, offset_x = 5
	{0, -5, -1, 1, 5, -6, -4, 4, 6},
	// Dimx = 4,  offset_x = 9
	{ 0, -9, -1,  1,  9, -10, -8,  8, 10 },
	// Dimx = 8,  offset_x = 17
	{ 0, -17, -1,  1, 17, -18, -16, 16, 18 },
	// Dimx = 16, offset_x = 33
	{ 0, -33, -1,  1, 33, -34, -32, 32, 34 },
	// Dimx = 32, offset_x = 65
	{ 0, -65, -1,  1, 65, -66, -64, 64, 66 }
};

__device__ int cube_offset_array[32][27] = {
	/*
		Offset to 26 cells around the voxel
		0: cube itself; 1: front face; 2: left face; 3: right face; 4: back face; 5: top face; 6: bottom face
		7: front top edge; 8: front left edge; 9: front right edge; 10: front bottom edge; 11: top left edge; 12: top right edge;
		13: bottom left edge; 14: bottom right edge; 15: back top edge; 16: back left edge; 17: back right edge; 18: back bottom edge;
		19: front top left corner; 20: front top right corner; 21: front bottom left corner; 22: front bottom right corner;
		23: back top left corner; 24: back top right corner; 25: back bottom left corner; 26: back bottom right corner
	*/
	// Dimx = 2, Dimy = 2, offset_y = 5, offset_z = 25
	{0, -25, -1, 1, 25, -5, 5, -30, -26, -24, -20, -6, -4, 4, 6, 20, 24, 26, 30, -31, -29, -21, -19, 19, 21, 29, 31},
	// Dimx = 4, Dimy = 2, offset_y = 9, offset_z = 45
	{0, -45, -1, 1, 45, -9, 9, -54, -46, -44, -36, -10, -8, 8, 10, 36, 44, 46, 54, -55, -53, -37, -35, 35, 37, 53, 55},
	// Dimx = 6, Dimy = 2, offset_y = 13, offset_z = 65
	{0, -65, -1, 1, 65, -13, 13, -78, -66, -64, -52, -14, -12, 12, 14, 52, 64, 66, 78, -79, -77, -53, -51, 51, 53, 77, 79},
	// Dimx = 8, Dimy = 2, offset_y = 17, offset_z = 85
	{0, -85, -1, 1, 85, -17, 17, -102, -86, -84, -68, -18, -16, 16, 18, 68, 84, 86, 102, -103, -101, -69, -67, 67, 69, 101, 103},

	// Dimx = 2, Dimy = 4, offset_y = 5, offset_z = 45
	{0, -45, -1, 1, 45, -5, 5, -50, -46, -44, -40, -6, -4, 4, 6, 40, 44, 46, 50, -51, -49, -41, -39, 39, 41, 49, 51},
	// Dimx = 4, Dimy = 4, offset_y = 9, offset_z = 81
	{0, -81, -1, 1, 81, -9, 9, -90, -82, -80, -72, -10, -8, 8, 10, 72, 80, 82, 90, -91, -89, -73, -71, 71, 73, 89, 91},
	// Dimx = 6, Dimy = 4, offset_y = 13, offset_z = 117
	{0, -117, -1, 1, 117, -13, 13, -130, -118, -116, -104, -14, -12, 12, 14, 104, 116, 118, 130, -131, -129, -105, -103, 103, 105, 129, 131},
	// Dimx = 8, Dimy = 4, offset_y = 17, offset_z = 153
	{0, -153, -1, 1, 153, -17, 17, -170, -154, -152, -136, -18, -16, 16, 18, 136, 152, 154, 170, -171, -169, -137, -135, 135, 137, 169, 171},

	// Dimx = 2, Dimy = 6, offset_y = 5, offset_z = 65
	{0, -65, -1, 1, 65, -5, 5, -70, -66, -64, -60, -6, -4, 4, 6, 60, 64, 66, 70, -71, -69, -61, -59, 59, 61, 69, 71},
	// Dimx = 4, Dimy = 6, offset_y = 9, offset_z = 117
	{0, -117, -1, 1, 117, -9, 9, -126, -118, -116, -108, -10, -8, 8, 10, 108, 116, 118, 126, -127, -125, -109, -107, 107, 109, 125, 127},
	// Dimx = 6, Dimy = 6, offset_y = 13, offset_z = 169
	{0, -169, -1, 1, 169, -13, 13, -182, -170, -168, -156, -14, -12, 12, 14, 156, 168, 170, 182, -183, -181, -157, -155, 155, 157, 181, 183},
	// Dimx = 8, Dimy = 6, offset_y = 17, offset_z = 221
	{0, -221, -1, 1, 221, -17, 17, -238, -222, -220, -204, -18, -16, 16, 18, 204, 220, 222, 238, -239, -237, -205, -203, 203, 205, 237, 239},

	// Dimx = 2, Dimy = 8, offset_y = 5, offset_z = 85
	{0, -85, -1, 1, 85, -5, 5, -90, -86, -84, -80, -6, -4, 4, 6, 80, 84, 86, 90, -91, -89, -81, -79, 79, 81, 89, 91},
	// Dimx = 4, Dimy = 8, offset_y = 9, offset_z = 153
	{0, -153, -1, 1, 153, -9, 9, -162, -154, -152, -144, -10, -8, 8, 10, 144, 152, 154, 162, -163, -161, -145, -143, 143, 145, 161, 163},
	// Dimx = 6, Dimy = 8, offset_y = 13, offset_z = 221
	{0, -221, -1, 1, 221, -13, 13, -234, -222, -220, -208, -14, -12, 12, 14, 208, 220, 222, 234, -235, -233, -209, -207, 207, 209, 233, 235},
	// Dimx = 8, Dimy = 8, offset_y = 17, offset_z = 289
	{0, -289, -1, 1, 289, -17, 17, -306, -290, -288, -272, -18, -16, 16, 18, 272, 288, 290, 306, -307, -305, -273, -271, 271, 273, 305, 307},

	// Dimx = 2, Dimy = 10, offset_y = 5, offset_z = 105
	{0, -105, -1, 1, 105, -5, 5, -110, -106, -104, -100, -6, -4, 4, 6, 100, 104, 106, 110, -111, -109, -101, -99, 99, 101, 109, 111},
	// Dimx = 4, Dimy = 10, offset_y = 9, offset_z = 189
	{0, -189, -1, 1, 189, -9, 9, -198, -190, -188, -180, -10, -8, 8, 10, 180, 188, 190, 198, -199, -197, -181, -179, 179, 181, 197, 199},
	// Dimx = 6, Dimy = 10, offset_y = 13, offset_z = 273
	{0, -273, -1, 1, 273, -13, 13, -286, -274, -272, -260, -14, -12, 12, 14, 260, 272, 274, 286, -287, -285, -261, -259, 259, 261, 285, 287},
	// Dimx = 8, Dimy = 10, offset_y = 17, offset_z = 357
	{0, -357, -1, 1, 357, -17, 17, -374, -358, -356, -340, -18, -16, 16, 18, 340, 356, 358, 374, -375, -373, -341, -339, 339, 341, 373, 375},

	// Dimx = 2, Dimy = 12, offset_y = 5, offset_z = 125
	{0, -125, -1, 1, 125, -5, 5, -130, -126, -124, -120, -6, -4, 4, 6, 120, 124, 126, 130, -131, -129, -121, -119, 119, 121, 129, 131},
	// Dimx = 4, Dimy = 12, offset_y = 9, offset_z = 225
	{0, -225, -1, 1, 225, -9, 9, -234, -226, -224, -216, -10, -8, 8, 10, 216, 224, 226, 234, -235, -233, -217, -215, 215, 217, 233, 235},
	// Dimx = 6, Dimy = 12, offset_y = 13, offset_z = 325
	{0, -325, -1, 1, 325, -13, 13, -338, -326, -324, -312, -14, -12, 12, 14, 312, 324, 326, 338, -339, -337, -313, -311, 311, 313, 337, 339},
	// Dimx = 8, Dimy = 12, offset_y = 17, offset_z = 425
	{0, -425, -1, 1, 425, -17, 17, -442, -426, -424, -408, -18, -16, 16, 18, 408, 424, 426, 442, -443, -441, -409, -407, 407, 409, 441, 443},

	// Dimx = 2, Dimy = 14, offset_y = 5, offset_z = 145
	{0, -145, -1, 1, 145, -5, 5, -150, -146, -144, -140, -6, -4, 4, 6, 140, 144, 146, 150, -151, -149, -141, -139, 139, 141, 149, 151},
	// Dimx = 4, Dimy = 14, offset_y = 9, offset_z = 261
	{0, -261, -1, 1, 261, -9, 9, -270, -262, -260, -252, -10, -8, 8, 10, 252, 260, 262, 270, -271, -269, -253, -251, 251, 253, 269, 271},
	// Dimx = 6, Dimy = 14, offset_y = 13, offset_z = 377
	{0, -377, -1, 1, 377, -13, 13, -390, -378, -376, -364, -14, -12, 12, 14, 364, 376, 378, 390, -391, -389, -365, -363, 363, 365, 389, 391},
	// Dimx = 8, Dimy = 14, offset_y = 17, offset_z = 493
	{0, -493, -1, 1, 493, -17, 17, -510, -494, -492, -476, -18, -16, 16, 18, 476, 492, 494, 510, -511, -509, -477, -475, 475, 477, 509, 511},

	// Dimx = 2, Dimy = 16, offset_y = 5, offset_z = 165
	{0, -165, -1, 1, 165, -5, 5, -170, -166, -164, -160, -6, -4, 4, 6, 160, 164, 166, 170, -171, -169, -161, -159, 159, 161, 169, 171},
	// Dimx = 4, Dimy = 16, offset_y = 9, offset_z = 297
	{0, -297, -1, 1, 297, -9, 9, -306, -298, -296, -288, -10, -8, 8, 10, 288, 296, 298, 306, -307, -305, -289, -287, 287, 289, 305, 307},
	// Dimx = 6, Dimy = 16, offset_y = 13, offset_z = 429
	{0, -429, -1, 1, 429, -13, 13, -442, -430, -428, -416, -14, -12, 12, 14, 416, 428, 430, 442, -443, -441, -417, -415, 415, 417, 441, 443},
	// Dimx = 8, Dimy = 16, offset_y = 17, offset_z = 561
	{0, -561, -1, 1, 561, -17, 17, -578, -562, -560, -544, -18, -16, 16, 18, 544, 560, 562, 578, -579, -577, -545, -543, 543, 545, 577, 579}
};

// Find index of the cube based on blockDim settings and offset
#define cube_offsetX(blockDimXSetting, coord, offset) (coord + cube_offsetX_array[blockDimXSetting_map2_continuousindex[blockDimXSetting]][offset])
#define cube_offset(blockDimSetting, coord, offset)  (coord + cube_offset_array[blockDimSetting_map2_continuousindex[blockDimSetting]][offset])

// ===================================================================
inline __device__ uchar_ subdivide_int8bits_read(uint_ t, uchar_ pos) {
	/*
		Subdivide a 32-bit unsigned integer into 4 consecutive 8-bit regions.
		@t:   input 32-bit unsigned integer
		@pos: which 8-bit region to read (0..3)
	*/
	switch (pos) {
	case 0: return  t & 0xFFu;
	case 1: return (t >> 8) & 0xFFu;
	case 2: return (t >> 16) & 0xFFu;
	case 3: return (t >> 24) & 0xFFu;
	}
	return 0;
}

inline __device__ void subdivide_int8bits_write(uint_& t, uchar_ pos, uchar_ v) {
	/*
		Subdivide a 32-bit unsigned integer into 4 consecutive 8-bit regions.
		@t:   in/out 32-bit unsigned integer
		@pos: which 8-bit region to write (0..3)
		@v:   8-bit value to store in that region
	*/
	uint_ shift = static_cast<uint_>(pos) * 8u;
	uint_ mask = ~(0xFFu << shift);          // clear the target 8 bits
	t = (t & mask) | (static_cast<uint_>(v) << shift);
}

inline __device__ void subdivide_int8bits_increase(uint_& t, uchar_ pos) {
	/*
		Increase the value in the selected 8-bit region by 1 (wraps modulo 256).
		@t:   in/out 32-bit unsigned integer
		@pos: which 8-bit region to modify (0..3)
	*/
	uchar_ v = subdivide_int8bits_read(t, pos);
	v = static_cast<uchar_>(v + 1);   // wraps naturally in 8 bits
	subdivide_int8bits_write(t, pos, v);
}

inline __device__ void subdivide_int8bits_decrease(uint_& t, uchar_ pos) {
	/*
		Decrease the value in the selected 8-bit region by 1 (wraps modulo 256).
		@t:   in/out 32-bit unsigned integer
		@pos: which 8-bit region to modify (0..3)
	*/
	uchar_ v = subdivide_int8bits_read(t, pos);
	v = static_cast<uchar_>(v - 1);   // wraps naturally in 8 bits
	subdivide_int8bits_write(t, pos, v);
}

inline __device__ void ucharsub4_write0(uchar_& t, uchar_ pos) {
	/*
		This function subdivide a 8-bit unsigned char into 4 consecutive 2-bit regions.
		@t: input unsigned char
		@pos: from which subregion to read the value. x->0, y->1, z->2, w->3
	*/
	switch (pos) {
	case 0: t = t & 252; break;
	case 1: t = t & 243; break;
	case 2: t = t & 207; break;
	case 3: t = t & 63;
	}
}

inline __device__ void ucharsub4_write1(uchar_& t, uchar_ pos) {
	/*
		This function subdivide a 8-bit unsigned char into 4 consecutive 2-bit regions.
		@t: input unsigned char
		@pos: from which subregion to read the value. x->0, y->1, z->2, w->3
	*/
	switch (pos) {
	case 0: t = t & 252; t = t | 1; break;
	case 1: t = t & 243; t = t | 4; break;
	case 2: t = t & 207; t = t | 16; break;
	case 3: t = t & 63; t = t | 64;
	}
}

// Sub-divide integer into regions of consecutive 3 bits, so each integer holds 10 regions
inline __device__ void subdivide_int3bits_write(uint_& t, uchar_ region, uchar_ v) {
	/*
		Write v to region of t
		@t: the integer to be subdivided
		@region: the region to be written
		@v: the value to be written [0, 5]
	*/
	switch (region) {
	case 0:
		t = t & 0xfffffff8;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x1; break;
		case 2: t = t | 0x2; break;
		case 3: t = t | 0x3; break;
		case 4: t = t | 0x4; break;
		case 5: t = t | 0x5; break;
		}
		break;
	case 1:
		t = t & 0xffffffc7;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x8; break;
		case 2: t = t | 0x10; break;
		case 3: t = t | 0x18; break;
		case 4: t = t | 0x20; break;
		case 5: t = t | 0x28; break;
		}
		break;
	case 2:
		t = t & 0xfffffe3f;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x40; break;
		case 2: t = t | 0x80; break;
		case 3: t = t | 0xc0; break;
		case 4: t = t | 0x100; break;
		case 5: t = t | 0x140; break;
		}
		break;
	case 3:
		t = t & 0xfffff1ff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x200; break;
		case 2: t = t | 0x400; break;
		case 3: t = t | 0x600; break;
		case 4: t = t | 0x800; break;
		case 5: t = t | 0xa00; break;
		}
		break;
	case 4:
		t = t & 0xffff8fff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x1000; break;
		case 2: t = t | 0x2000; break;
		case 3: t = t | 0x3000; break;
		case 4: t = t | 0x4000; break;
		case 5: t = t | 0x5000; break;
		}
		break;
	case 5:
		t = t & 0xfffc7fff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x8000; break;
		case 2: t = t | 0x10000; break;
		case 3: t = t | 0x18000; break;
		case 4: t = t | 0x20000; break;
		case 5: t = t | 0x28000; break;
		}
		break;
	case 6:
		t = t & 0xffe3ffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x40000; break;
		case 2: t = t | 0x80000; break;
		case 3: t = t | 0xc0000; break;
		case 4: t = t | 0x100000; break;
		case 5: t = t | 0x140000; break;
		}
		break;
	case 7:
		t = t & 0xff1fffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x200000; break;
		case 2: t = t | 0x400000; break;
		case 3: t = t | 0x600000; break;
		case 4: t = t | 0x800000; break;
		case 5: t = t | 0xa00000; break;
		}
		break;
	case 8:
		t = t & 0xf8ffffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x1000000; break;
		case 2: t = t | 0x2000000; break;
		case 3: t = t | 0x3000000; break;
		case 4: t = t | 0x4000000; break;
		case 5: t = t | 0x5000000; break;
		}
		break;
	case 9:
		t = t & 0xc7ffffff;
		switch (v) {
		case 0: break;
		case 1: t = t | 0x8000000; break;
		case 2: t = t | 0x10000000; break;
		case 3: t = t | 0x18000000; break;
		case 4: t = t | 0x20000000; break;
		case 5: t = t | 0x28000000; break;
		}
		break;
	}
}

inline __device__ uchar_ subdivide_int3bits_read(uint_ t, uchar_ region) {
	/*
		Read region of t
		@t: the integer that is subdivided
		@region: the region to be read
		returns the value of the region [0, 5]
	*/
	switch (region) {
	case 0:
		return t & 0x7;
	case 1:
		return (t >> 3) & 0x7;
	case 2:
		return (t >> 6) & 0x7;
	case 3:
		return (t >> 9) & 0x7;
	case 4:
		return (t >> 12) & 0x7;
	case 5:
		return (t >> 15) & 0x7;
	case 6:
		return (t >> 18) & 0x7;
	case 7:
		return (t >> 21) & 0x7;
	case 8:
		return (t >> 24) & 0x7;
	case 9:
		return (t >> 27) & 0x7;
	default:
		printf("Error: subdivide_int3bits_read, unrecognized region\n");
		return 0;
	}
}

inline __device__ void subdivide_int2bits_write24to27bits(uint_& t, uchar_ v) {
	t = t & 0xffffff;
	switch (v) {
	case 0: break;
	case 1: t = t | 0x1000000; break;
	case 2: t = t | 0x2000000; break;
	case 3: t = t | 0x3000000; break;
	case 4: t = t | 0x4000000; break;
	case 5: t = t | 0x5000000; break;
	case 6: t = t | 0x6000000; break;
	case 7: t = t | 0x7000000; break;
	case 8: t = t | 0x8000000; break;
	case 9: t = t | 0x9000000; break;
	case 10: t = t | 0xa000000; break;
	case 11: t = t | 0xb000000; break;
	case 12: t = t | 0xc000000; break;
	case 13: t = t | 0xd000000; break;
	case 14: t = t | 0xe000000; break;
	case 15: t = t | 0xf000000; break;
	}
}

// =================================================================================================
inline __host__ __device__ void subdivide_short2bits_write0(ushort_& t, uchar_ region) {
	/*
		Write 0 to region of t
		@t: the integer to be subdivided
		@region: the region to be written
		subdivide a short value to 8 consecutive 2 bits regions and use the frist 6 for 6 directions of cube
	*/
	switch (region) {
	case 0: t = t & 0xffc; break;
	case 1: t = t & 0xff3; break;
	case 2: t = t & 0xfcf; break;
	case 3: t = t & 0xf3f; break;
	case 4: t = t & 0xcff; break;
	case 5: t = t & 0x3ff;
	}
}

inline __device__ void subdivide_short2bits_write1(ushort_& t, uchar_ region) {
	/*
		Write 1 to region of t
		@t: the integer to be subdivided
		@region: the region to be written
		subdivide a short value to 8 consecutive 2 bits regions and use the frist 6 for 6 directions of cube
		Note: the read function is in "morse_boundary3D.cu" file
	*/
	switch (region) {
	case 0: t = t & 0xffc; t = t | 0x1; break;
	case 1: t = t & 0xff3; t = t | 0x4; break;
	case 2: t = t & 0xfcf; t = t | 0x10; break;
	case 3: t = t & 0xf3f; t = t | 0x40; break;
	case 4: t = t & 0xcff; t = t | 0x100; break;
	case 5: t = t & 0x3ff; t = t | 0x400;
	}
}

void upload2constant_matchingKernel2D(uint_* imgSize_y_h, uint_* chunkSize_h, const int num_chunks) {
	/*
		This function uploads:
		- chunkSize information: the height of the chunk
		- imgSize: img.width
		to constant memory.
	*/
	cudaMemcpyToSymbol(imgSize_y_const, imgSize_y_h, sizeof(uint_));
	cudaMemcpyToSymbol(chunkSize_h_const, chunkSize_h, num_chunks * sizeof(uint_));
}

void upload2constant_matchingKernel3D(
	uint_*				imgSize_y,
	uint_*				chunkSize_h,
	uint_*				chunkSize_d,
	const uint_			chunkNum_h,
	const uint_			chunkNum_d
) {
	/*
		This function uploads:
		@imgSize_y:   width of the input image
		@chunkSize_h: the height of each chunk
		@chunkSize_d: the depth of each chunk
		to constant memory.
	*/
	cudaMemcpyToSymbol(chunkNum_h_const, &chunkNum_h, sizeof(uint_));
	cudaMemcpyToSymbol(imgSize_y_const, imgSize_y, sizeof(uint_));
	cudaMemcpyToSymbol(chunkSize_h_const, chunkSize_h, chunkNum_h * sizeof(uint_));
	cudaMemcpyToSymbol(chunkSize_d_const, chunkSize_d, chunkNum_d * sizeof(uint_));
}

#define LAST_X          (threadIdx.x == blockDim.x - 1)
#define LAST_Y          (threadIdx.y == blockDim.y - 1)
#define LAST_Z          (threadIdx.z == blockDim.z - 1)
#define NOT_FIRST_BLK_X (blockIdx.x > 0)
#define NOT_LAST_BLK_X  (blockIdx.x < gridDim.x - 1)
#define STRIDE_Y        (imgSize_y_const[0] * 2u + 1u)

template<typename type, uint_ blkDimXSetting>
__global__ void procLowerStars_voxFace_kernel2D(
	cudaTextureObject_t		chunk,
	const uchar_			chunkID,
	uchar_* match_global,
	uchar_* crit_global
)
{
	/*
	Descriptions:
		This function implements Vanessa's ProcessLowerStars algorithm in paper
		(https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=5766002&tag=1). The
		pixels/voxels are treated as 2-cells (faces). The function isolates the
		0-cells and 1-cells at border and performs morse matching with only 0-
		and 1-cells. Each pixel processes the cells in its L(x). The function
		requires inputs with 2-pixel width halo above and below it.

		@img: input pixels/voxels grid
		@chunkID: the id of the current chunk
		@match_global: cubical complex with size (2 * chunk.height + 1, 2 * chunk.width + 1)
		@crit_global : same size as match_global, dim + 1 marks critical cell, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
	*/
	// Assign a thread to each pixel/voxel
	// Assign a thread to each pixel/voxel
	uint_ px = blockDim.x * blockIdx.x + threadIdx.x;																			// px
	uint_ py = blockDim.y * blockIdx.y + threadIdx.y;																			// py
	uint_ pw = (blockDim.x * 2 + 1) * (blockDim.y * 2 + 1);

	// Shared memory allocation
	extern __shared__ int		shared_buf[];
	uchar_* match_shared = (uchar_*)shared_buf;
	uchar_* crit_shared = (uchar_*)&match_shared[pw];
	// Initialize crit_shared
	uint_ pos = threadIdx.y * blockDim.x + threadIdx.x;
	while (pos < pw) {
		crit_shared[pos] = 0;
		pos = pos + blockDim.x * blockDim.y;
	}
	__syncthreads();

	// Determine if pixel is out of range
	if (px >= imgSize_y_const[0] || py >= chunkSize_h_const[chunkID]) return;

	type value;
	uint_ marker, helper = 0;

	// ===== Handle Upperbound of the Chunk =====
	if (py == 0) {
		marker = 0;
		// Decide lower star of immediate upper voxel L(x) with total ordering enforced
		value = tex2D<type>(chunk, px + 1, 1);																													// center pixel
		// Decide ownership of 1-cells
		if (value < tex2D<type>(chunk, px, 1))		uintsub8_write(marker, 1, 1);																			// left pixel
		if (value <= tex2D<type>(chunk, px + 2, 1))	uintsub8_write(marker, 2, 1);																			// right pixel
		if (value <= tex2D<type>(chunk, px + 1, 2))	uintsub8_write(marker, 3, 1);																			// bottome pixel
		//  Decide ownership of 0-cells
		if (uintsub8_read(marker, 1) && uintsub8_read(marker, 3) && value <= tex2D<type>(chunk, px, 2))		uintsub8_write(marker, 6, 1);
		if (uintsub8_read(marker, 2) && uintsub8_read(marker, 3) && value <= tex2D<type>(chunk, px + 2, 2)) uintsub8_write(marker, 7, 1);

		// Initialize cells 3, 6 and 7 if they are in L(x)
		pw = px * 2 + 1;
		if (uintsub8_read(marker, 3)) { match_global[pw] = 17;     writeCubi(crit_global[pw], 4); }															// bottom edge, index is 3 in grid, 4 in crit_global
		if (uintsub8_read(marker, 6)) { match_global[pw - 1] = 85; writeCubi(crit_global[pw - 1], 7); }														// bottom left vert, index is 6 in grid, 7 in crit_global
		if (uintsub8_read(marker, 7)) { match_global[pw + 1] = 85; writeCubi(crit_global[pw + 1], 8); }														// botoom right vert, index is 7 in grid, 8 in crit_global

		// Isolate boundary cells
		// 4-strata vertices (in between 4 blocks) should not be matched
		if (uintsub8_read(marker, 6) && threadIdx.x == 0 && NOT_FIRST_BLK_X) { uintsub8_write(marker, 6, 2); crit_global[pw - 1] |= 1; } // border bottom-left cell
		if (uintsub8_read(marker, 7) && threadIdx.x + 1 == blockDim.x && NOT_LAST_BLK_X) { uintsub8_write(marker, 7, 2); crit_global[pw + 1] |= 1; } // border bottom-right cell

		// Simplified 1-dim morse matching (boundary morse matching)
		if (uintsub8_read(marker, 3)) {
			if (uintsub8_read(marker, 6) == 1) {
				ucharsub4_write1(match_global[pw], 3);
				ucharsub4_write0(match_global[pw - 1], 1);
				if (uintsub8_read(marker, 7) == 1) crit_global[pw + 1] |= 1;
			}
			else if (uintsub8_read(marker, 7) == 1) {
				ucharsub4_write1(match_global[pw], 1);
				ucharsub4_write0(match_global[pw + 1], 3);
			}
			else crit_global[pw] |= 2;
		}
	}
	// ===== Handle Lowerbound of the Chunk =====
	if (py + 1 == chunkSize_h_const[chunkID]) {
		marker = 0;
		// Decide lower star of immediate lower voxel L(x) with total ordering enforced
		value = tex2D<type>(chunk, px + 1, chunkSize_h_const[chunkID] + 2);																							// center pixel
		// Decide ownership of 1-cells
		if (value < tex2D<type>(chunk, px + 1, chunkSize_h_const[chunkID] + 1)) uintsub8_write(marker, 0, 1);													// top pixel
		if (value < tex2D<type>(chunk, px, chunkSize_h_const[chunkID] + 2))		uintsub8_write(marker, 1, 1);													// left pixel
		if (value <= tex2D<type>(chunk, px + 2, chunkSize_h_const[chunkID] + 2)) uintsub8_write(marker, 2, 1);													// right pixel
		// Decide ownership of 0-cells
		if (uintsub8_read(marker, 0) && uintsub8_read(marker, 1) && value < tex2D<type>(chunk, px, chunkSize_h_const[chunkID] + 1))		uintsub8_write(marker, 4, 1);// top-left
		if (uintsub8_read(marker, 0) && uintsub8_read(marker, 2) && value < tex2D<type>(chunk, px + 2, chunkSize_h_const[chunkID] + 1)) uintsub8_write(marker, 5, 1);// top-right

		// Initialize cells 0, 4 and 5 if they are in L(x)
		pw = (2 * chunkSize_h_const[chunkID]) * STRIDE_Y + px * 2 + 1;
		if (uintsub8_read(marker, 0)) { match_global[pw] = 17;     writeCubi(crit_global[pw], 1); }													// top edge, index is 0 in grid, 1 in crit_global
		if (uintsub8_read(marker, 4)) { match_global[pw - 1] = 85; writeCubi(crit_global[pw - 1], 5); }												// top left vert, index is 4 in grid, 5 in crit_global
		if (uintsub8_read(marker, 5)) { match_global[pw + 1] = 85; writeCubi(crit_global[pw + 1], 6); }												// top right vert, index is 5 in grid, 6 in crit_global

		// Isolate boundary cells
		// 4-strata vertices (in between 4 blocks) should not be matched
		if (uintsub8_read(marker, 4) && threadIdx.x == 0 && NOT_FIRST_BLK_X) { uintsub8_write(marker, 4, 2); crit_global[pw - 1] |= 1; }// border top-left cell, should not be matched
		if (uintsub8_read(marker, 5) && threadIdx.x + 1 == blockDim.x && NOT_LAST_BLK_X) { uintsub8_write(marker, 5, 2); crit_global[pw + 1] |= 1; }// border top-right cell

		// Simplified 1-dim morse matching (boundary morse matching)
		if (uintsub8_read(marker, 0)) {
			if (uintsub8_read(marker, 4) == 1) {
				ucharsub4_write1(match_global[pw], 3);
				ucharsub4_write0(match_global[pw - 1], 1);
				if (uintsub8_read(marker, 5) == 1) crit_global[pw + 1] |= 1;
			}
			else if (uintsub8_read(marker, 5) == 1) {
				ucharsub4_write1(match_global[pw], 1);
				ucharsub4_write0(match_global[pw + 1], 3);
			}
			else crit_global[pw] |= 2;
		}
	}

	marker = 0;
	// Decide lower star of voxel L(x) with total ordering enforced
	value = tex2D<type>(chunk, px + 1, py + 2);																									// center pixel
	// Decide ownership of 1-cells
	if (value < tex2D<type>(chunk, px + 1, py + 1))		uintsub8_write(marker, 0, 1);														// top pixel
	if (value < tex2D<type>(chunk, px, py + 2))			uintsub8_write(marker, 1, 1);														// left pixel
	if (value <= tex2D<type>(chunk, px + 2, py + 2))		uintsub8_write(marker, 2, 1);														// right pixel
	if (value <= tex2D<type>(chunk, px + 1, py + 3))		uintsub8_write(marker, 3, 1);														// bottom pixel
	// Decide ownership of 0-cells
	if (uintsub8_read(marker, 0) && uintsub8_read(marker, 1) && value < tex2D<type>(chunk, px, py + 1))			uintsub8_write(marker, 4, 1);	// top-left
	if (uintsub8_read(marker, 0) && uintsub8_read(marker, 2) && value < tex2D<type>(chunk, px + 2, py + 1))		uintsub8_write(marker, 5, 1);	// top-right
	if (uintsub8_read(marker, 1) && uintsub8_read(marker, 3) && value <= tex2D<type>(chunk, px, py + 3))		uintsub8_write(marker, 6, 1);	// bottom-left
	if (uintsub8_read(marker, 2) && uintsub8_read(marker, 3) && value <= tex2D<type>(chunk, px + 2, py + 3))	uintsub8_write(marker, 7, 1);	// bottom-right

	// Re-init coordinates to the matching grid: middle, upper middle, and lower middle
	uint_& coord = py;
	coord = (threadIdx.y * 2 + 1) * (blockDim.x * 2 + 1) + threadIdx.x * 2 + 1;

	// Initialize cells in own L(x) (avoid race conditions)
	match_shared[coord] = 0;
	// 1-cells
	if (uintsub8_read(marker, 0)) { match_shared[cube_offsetX(blkDimXSetting, coord, 1)] = 17;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 1)], 1); }
	if (uintsub8_read(marker, 1)) { match_shared[cube_offsetX(blkDimXSetting, coord, 2)] = 68;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 2)], 2); }
	if (uintsub8_read(marker, 2)) { match_shared[cube_offsetX(blkDimXSetting, coord, 3)] = 68;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 3)], 3); }
	if (uintsub8_read(marker, 3)) { match_shared[cube_offsetX(blkDimXSetting, coord, 4)] = 17;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 4)], 4); }
	// 0-cells
	if (uintsub8_read(marker, 4)) { match_shared[cube_offsetX(blkDimXSetting, coord, 5)] = 85;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 5)], 5); }
	if (uintsub8_read(marker, 5)) { match_shared[cube_offsetX(blkDimXSetting, coord, 6)] = 85;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 6)], 6); }
	if (uintsub8_read(marker, 6)) { match_shared[cube_offsetX(blkDimXSetting, coord, 7)] = 85;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 7)], 7); }
	if (uintsub8_read(marker, 7)) { match_shared[cube_offsetX(blkDimXSetting, coord, 8)] = 85;	writeCubi(crit_shared[cube_offsetX(blkDimXSetting, coord, 8)], 8); }

	// Stop boundary cells from crossing boundary
	if (threadIdx.y == 0 && uintsub8_read(marker, 0)) {													// top border
		subdivide_int8bits_write(helper, 0, 1);
		// Mark boundary vertices
		if (uintsub8_read(marker, 4)) uintsub8_write(marker, 4, 10);
		if (uintsub8_read(marker, 5)) uintsub8_write(marker, 5, 10);
	}
	if (threadIdx.x == 0 && uintsub8_read(marker, 1) && NOT_FIRST_BLK_X) {								// left border
		subdivide_int8bits_write(helper, 1, 1);
		// Mark boundary vertices
		if (uintsub8_read(marker, 4) > 0) uintsub8_write(marker, 4, 10);
		if (uintsub8_read(marker, 6) > 0) uintsub8_write(marker, 6, 10);
	}
	if (threadIdx.x + 1 == blockDim.x && uintsub8_read(marker, 2) && NOT_LAST_BLK_X) {		// right border
		subdivide_int8bits_write(helper, 2, 1);
		// Mark boundary vertices
		if (uintsub8_read(marker, 5) > 0) uintsub8_write(marker, 5, 10);
		if (uintsub8_read(marker, 7) > 0) uintsub8_write(marker, 7, 10);
	}
	// Bottom border has 2 cases. 1: bottom border of a block; 2: bottom border of a chunk if that chunk is not bottom chunk as we chunk only vertically
	pos = blockDim.y * blockIdx.y + threadIdx.y + 1;
	if ((threadIdx.y + 1 == blockDim.y || pos == chunkSize_h_const[chunkID]) && uintsub8_read(marker, 3)) {	// bottom border
		subdivide_int8bits_write(helper, 3, 1);
		// Mark boundary vertices
		if (uintsub8_read(marker, 6) > 0) uintsub8_write(marker, 6, 10);
		if (uintsub8_read(marker, 7) > 0) uintsub8_write(marker, 7, 10);
	}
	// 4-strata vertices (in between 4 blocks) should not be matched
	if (uintsub8_read(marker, 4) && subdivide_int8bits_read(helper, 0) && subdivide_int8bits_read(helper, 1)) { uintsub8_write(marker, 4, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 5)] |= 1; }	// top-left corner
	if (uintsub8_read(marker, 5) && subdivide_int8bits_read(helper, 0) && subdivide_int8bits_read(helper, 2)) { uintsub8_write(marker, 5, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 6)] |= 1; }	// top-right corner
	if (uintsub8_read(marker, 6) && subdivide_int8bits_read(helper, 1) && subdivide_int8bits_read(helper, 3)) { uintsub8_write(marker, 6, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 7)] |= 1; }	// bottom-left corner
	if (uintsub8_read(marker, 7) && subdivide_int8bits_read(helper, 2) && subdivide_int8bits_read(helper, 3)) { uintsub8_write(marker, 7, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 8)] |= 1; }	// bottom-right corner

	// 1-dim morse matching (boundary morse matching)
#pragma unroll
	for (pos = 0; pos < 4; pos++) {
		if (subdivide_int8bits_read(helper, pos)) {
			switch (pos) {
			case 0:
				if (uintsub8_read(marker, 4) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 1)], 3); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 5)], 1);
					uintsub8_write(marker, 4, 3); uintsub8_write(marker, 0, 3);
				}
				else if (uintsub8_read(marker, 5) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 1)], 1); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 6)], 3);
					uintsub8_write(marker, 5, 3); uintsub8_write(marker, 0, 3);
				}
				else { uintsub8_write(marker, 0, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 1)] |= 2; }	// edge is critical
				break;
			case 1:
				if (uintsub8_read(marker, 4) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 2)], 0); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 5)], 2);
					uintsub8_write(marker, 4, 3); uintsub8_write(marker, 1, 3);
				}
				else if (uintsub8_read(marker, 6) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 2)], 2); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 7)], 0);
					uintsub8_write(marker, 6, 3); uintsub8_write(marker, 1, 3);
				}
				else { uintsub8_write(marker, 1, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 2)] |= 2; } // edge is critical
				break;
			case 2:
				if (uintsub8_read(marker, 5) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 3)], 0); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 6)], 2);
					uintsub8_write(marker, 5, 3); uintsub8_write(marker, 2, 3);
				}
				else if (uintsub8_read(marker, 7) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 3)], 2); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 8)], 0);
					uintsub8_write(marker, 7, 3); uintsub8_write(marker, 2, 3);
				}
				else { uintsub8_write(marker, 2, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 3)] |= 2; }	// edge is critical
				break;
			case 3:
				if (uintsub8_read(marker, 6) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 4)], 3); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 7)], 1);
					uintsub8_write(marker, 6, 3); uintsub8_write(marker, 3, 3);
				}
				else if (uintsub8_read(marker, 7) == 10) {
					ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 4)], 1); ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 8)], 3);
					uintsub8_write(marker, 7, 3); uintsub8_write(marker, 3, 3);
				}
				else { uintsub8_write(marker, 3, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 4)] |= 2; }		// edge is critical
			}
		}
	}
	// Mark all vertices in L(x) at border but not matched as critical
	if (uintsub8_read(marker, 4) == 10) { uintsub8_write(marker, 4, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 5)] |= 1; }
	if (uintsub8_read(marker, 5) == 10) { uintsub8_write(marker, 5, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 6)] |= 1; }
	if (uintsub8_read(marker, 6) == 10) { uintsub8_write(marker, 6, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 7)] |= 1; }
	if (uintsub8_read(marker, 7) == 10) { uintsub8_write(marker, 7, 2); crit_shared[cube_offsetX(blkDimXSetting, coord, 8)] |= 1; }

	// Find morse matching																											// 2-cell self IS critical
	helper = 0;
	for (pos = 0; pos < 4; pos++) if (uintsub8_read(marker, pos) == 1) break;
	if (pos < 4) {
		// Match the edge to the 2-cell (self)
		switch (pos) {
		case 0:
			ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 0)], 0);
			ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 1)], 2);
			if (uintsub8_read(marker, 4) == 1 && uintsub8_read(marker, 1) == 1) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
			if (uintsub8_read(marker, 5) == 1 && uintsub8_read(marker, 2) == 1) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
			break;
		case 1:
			ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 0)], 3);
			ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 2)], 1);
			if (uintsub8_read(marker, 4) == 1 && uintsub8_read(marker, 0) == 1) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
			if (uintsub8_read(marker, 6) == 1 && uintsub8_read(marker, 3) == 1) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
			break;
		case 2:
			ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 0)], 1);
			ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 3)], 3);
			if (uintsub8_read(marker, 5) == 1 && uintsub8_read(marker, 0) == 1) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
			if (uintsub8_read(marker, 7) == 1 && uintsub8_read(marker, 3) == 1) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
			break;
		case 3:
			ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 0)], 2);
			ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 4)], 0);
			if (uintsub8_read(marker, 6) == 1 && uintsub8_read(marker, 1) == 1) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
			if (uintsub8_read(marker, 7) == 1 && uintsub8_read(marker, 2) == 1) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
			break;
		default:
			printf("Morse matching error: edge -> face matching contains 0-cells!\n");
		}
		uintsub8_write(marker, pos++, 3);
		for (; pos < 4; pos++) if (uintsub8_read(marker, pos) == 1) { uintsub8_write(marker, pos, 10); subdivide_int8bits_increase(helper, 0); }

		// Process elements in PQ0 (helper - region 0) and PQ1 (helper - region 1)
		// This part goes into Vanessa's algo loops
		while (subdivide_int8bits_read(helper, 0) > 0 || subdivide_int8bits_read(helper, 1) > 0) {
			// Process elements in PQ1
			while (subdivide_int8bits_read(helper, 1) > 0) {
				for (pos = 4; pos < 8; pos++) if (uintsub8_read(marker, pos) == 11) break;
				subdivide_int8bits_decrease(helper, 1);
				switch (pos) {
				case 4:
					if (uintsub8_read(marker, 0) == 10) subdivide_int8bits_write(helper, 2, 0); else if (uintsub8_read(marker, 1) == 10) subdivide_int8bits_write(helper, 2, 1); else subdivide_int8bits_write(helper, 2, 9); break;
				case 5:
					if (uintsub8_read(marker, 0) == 10) subdivide_int8bits_write(helper, 2, 0); else if (uintsub8_read(marker, 2) == 10) subdivide_int8bits_write(helper, 2, 2); else subdivide_int8bits_write(helper, 2, 9); break;
				case 6:
					if (uintsub8_read(marker, 1) == 10) subdivide_int8bits_write(helper, 2, 1); else if (uintsub8_read(marker, 3) == 10) subdivide_int8bits_write(helper, 2, 3); else subdivide_int8bits_write(helper, 2, 9); break;
				case 7:
					if (uintsub8_read(marker, 2) == 10) subdivide_int8bits_write(helper, 2, 2); else if (uintsub8_read(marker, 3) == 10) subdivide_int8bits_write(helper, 2, 3); else subdivide_int8bits_write(helper, 2, 9); break;
				default:
					printf("Morse matching error: PQ1 has 1-cells!\n");
				}
				if (subdivide_int8bits_read(helper, 2) == 9) { uintsub8_write(marker, pos, 10); subdivide_int8bits_increase(helper, 0); }
				else {
					uintsub8_write(marker, subdivide_int8bits_read(helper, 2), 3);
					uintsub8_write(marker, pos, 3);
					subdivide_int8bits_decrease(helper, 0);

					switch (subdivide_int8bits_read(helper, 2)) {
					case 0:
						if (pos == 4) {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 1)], 3);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 5)], 1);
							if (uintsub8_read(marker, 5) == 1) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
						}
						else {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 1)], 1);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 6)], 3);
							if (uintsub8_read(marker, 4) == 1) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
						}
						break;
					case 1:
						if (pos == 4) {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 2)], 0);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 5)], 2);
							if (uintsub8_read(marker, 6) == 1) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
						}
						else {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 2)], 2);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 7)], 0);
							if (uintsub8_read(marker, 4) == 1) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
						}
						break;
					case 2:
						if (pos == 5) {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 3)], 0);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 6)], 2);
							if (uintsub8_read(marker, 7) == 1) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
						}
						else {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 3)], 2);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 8)], 0);
							if (uintsub8_read(marker, 5) == 1) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
						}
						break;
					case 3:
						if (pos == 6) {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 4)], 3);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 7)], 1);
							if (uintsub8_read(marker, 7) == 1) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
						}
						else {
							ucharsub4_write1(match_shared[cube_offsetX(blkDimXSetting, coord, 4)], 1);
							ucharsub4_write0(match_shared[cube_offsetX(blkDimXSetting, coord, 8)], 3);
							if (uintsub8_read(marker, 6) == 1) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
						}
						break;
					default:
						printf("Morse matching error: pair(alpha) has 0-cells\n");
					}
				}
			}
			// Process elements in PQ0
			if (subdivide_int8bits_read(helper, 0) > 0) {
				for (pos = 0; pos < 8; pos++) if (uintsub8_read(marker, pos) == 10) break;
				subdivide_int8bits_decrease(helper, 0);
				switch (pos) {
				case 0:
					uintsub8_write(marker, 0, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 1)] |= 2;
					if (uintsub8_read(marker, 4) == 1 && uintsub8_read(marker, 1) == 10) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
					if (uintsub8_read(marker, 5) == 1 && uintsub8_read(marker, 2) == 10) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
					break;
				case 1:
					uintsub8_write(marker, 1, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 2)] |= 2;
					if (uintsub8_read(marker, 4) == 1 && uintsub8_read(marker, 0) == 10) { uintsub8_write(marker, 4, 11); subdivide_int8bits_increase(helper, 1); }
					if (uintsub8_read(marker, 6) == 1 && uintsub8_read(marker, 3) == 10) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
					break;
				case 2:
					uintsub8_write(marker, 2, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 3)] |= 2;
					if (uintsub8_read(marker, 5) == 1 && uintsub8_read(marker, 0) == 10) { uintsub8_write(marker, 5, 11); subdivide_int8bits_increase(helper, 1); }
					if (uintsub8_read(marker, 7) == 1 && uintsub8_read(marker, 3) == 10) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
					break;
				case 3:
					uintsub8_write(marker, 3, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 4)] |= 2;
					if (uintsub8_read(marker, 6) == 1 && uintsub8_read(marker, 1) == 10) { uintsub8_write(marker, 6, 11); subdivide_int8bits_increase(helper, 1); }
					if (uintsub8_read(marker, 7) == 1 && uintsub8_read(marker, 2) == 10) { uintsub8_write(marker, 7, 11); subdivide_int8bits_increase(helper, 1); }
					break;
				case 4:
					uintsub8_write(marker, 4, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 5)] |= 1;
					break;
				case 5:
					uintsub8_write(marker, 5, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 6)] |= 1;
					break;
				case 6:
					uintsub8_write(marker, 6, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 7)] |= 1;
					break;
				case 7:
					uintsub8_write(marker, 7, 2);
					crit_shared[cube_offsetX(blkDimXSetting, coord, 8)] |= 1;
				}
			}
		}
	}
	else crit_shared[coord] |= 3;								// 2-cell self IS critical

	// Copy from shared memory to global memory
	pos = ((blockDim.y * blockIdx.y + threadIdx.y) * 2 + 1) * STRIDE_Y + (blockDim.x * blockIdx.x + threadIdx.x) * 2 + 1;
	px = pos - STRIDE_Y;
	pw = pos + STRIDE_Y;

	match_global[pos] = match_shared[coord];
	crit_global[pos] = crit_shared[coord];
	if (uintsub8_read(marker, 1) > 0) { match_global[pos - 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 2)]; crit_global[pos - 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 2)]; }
	if (uintsub8_read(marker, 2) > 0) { match_global[pos + 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 3)]; crit_global[pos + 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 3)]; }
	if (uintsub8_read(marker, 0) > 0) { match_global[px] = match_shared[cube_offsetX(blkDimXSetting, coord, 1)]; crit_global[px] = crit_shared[cube_offsetX(blkDimXSetting, coord, 1)]; }
	if (uintsub8_read(marker, 4) > 0) { match_global[px - 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 5)]; crit_global[px - 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 5)]; }
	if (uintsub8_read(marker, 5) > 0) { match_global[px + 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 6)]; crit_global[px + 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 6)]; }
	if (uintsub8_read(marker, 3) > 0) { match_global[pw] = match_shared[cube_offsetX(blkDimXSetting, coord, 4)]; crit_global[pw] = crit_shared[cube_offsetX(blkDimXSetting, coord, 4)]; }
	if (uintsub8_read(marker, 6) > 0) { match_global[pw - 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 7)]; crit_global[pw - 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 7)]; }
	if (uintsub8_read(marker, 7) > 0) { match_global[pw + 1] = match_shared[cube_offsetX(blkDimXSetting, coord, 8)]; crit_global[pw + 1] = crit_shared[cube_offsetX(blkDimXSetting, coord, 8)]; }
}

template<typename type, uint_ blkDimSetting>
__global__ void procLowerStars_voxFace_kernel3D(
	cudaTextureObject_t		chunk,
	const ushort_			chunkID,
	ushort_* __restrict__	match_global,
	uchar_*  __restrict__	crit_global
)
{
	/*
	Descriptions:
		This function implements Vanessa's ProcessLowerStars algorithm in paper
		(https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=5766002&tag=1). The
		pixels/voxels are treated as 3-cells (cubes). The function isolates the
		0-, 1-, 2-cells at border and performs morse matching. Each thread processes
		the cells in its L(x). The function requires inputs with 2-vox width halo
		in both sides of h and d directions and 1-vox width halo in both sides of
		w direction.

		@chunk: input chunk
		@chunkID: the id of the current chunk
		@match_global: cubical complex with size chunkSizeX
		@crit_global: same size as match_global, dim + 1 marks critical cell, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
	*/
	// Assign a thread to each voxel in the chunk
	uint_ px = blockIdx.x * blockDim.x + threadIdx.x;
	uint_ py = blockIdx.y * blockDim.y + threadIdx.y;
	uint_ pz = blockIdx.z * blockDim.z + threadIdx.z;
	uint_ pw = (blockDim.x * 2u + 1u) * (blockDim.y * 2u + 1u) * (blockDim.z * 2u + 1u);
	// Allocate shared memory
	extern __shared__ uchar_	sharedMem[];
	ushort_* match_shared	=	reinterpret_cast<ushort_*>(sharedMem);
	uchar_* crit_shared		=	reinterpret_cast<uchar_*>((reinterpret_cast<uintptr_t>(match_shared + pw) + 1u) & ~uintptr_t(1));
	__shared__ uint_			chunkSizeH, chunkSizeD;
	// Initialize crit_shared
	uint_ pos = threadIdx.z * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x;
	if (pos == 0) {
		chunkSizeH = chunkSize_h_const[chunkID % chunkNum_h_const[0]];
		chunkSizeD = chunkSize_d_const[chunkID / chunkNum_h_const[0]];
	}
	while (pos < pw) {
		crit_shared[pos] = 0;
		pos += blockDim.x * blockDim.y * blockDim.z;
	}
	__syncthreads();

	// Determine if voxel out of range
	if (px >= imgSize_y_const[0] || py >= chunkSizeH || pz >= chunkSizeD) return;

	/* Meaning of marker values :
	0: cell not belong to current 3-cell
	1: cell belong to current 3-cell but not processed
	2: cell is critical
	3: cell is matched
	4: cell is in PQ0 (Vanessa's algo) (corresponds to 10 in Topo2D)
	5: cell is in PQ1 (Vanessa's algo) (corresponds to 11 in Topo2D)
	*/
	uint_ marker_vert;					// marker for 8 vertices from v0 to v7 and the first 2 edges e0 and e1
	uint_ marker_edge;					// marker for the last 10 edges from e2 to e11
	uint_ marker_face;					// marker for the 6 faces from f0 to f5
	type value;

	// ===== Border Handling =====
	// Chunk upper border handling
	if (py == 0) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of imediate upper voxel L(x) with total ordering enforced
		value = tex3D<type>(chunk, px + 1, 1, pz + 2);															// load value of immediate upper voxel
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px + 1, 1, pz + 1))  subdivide_int3bits_write(marker_face, 0, 1);		// front face
		if (value < tex3D<type>(chunk, px, 1, pz + 2)) 	    subdivide_int3bits_write(marker_face, 1, 1);		// left face
		if (value <= tex3D<type>(chunk, px + 2, 1, pz + 2)) subdivide_int3bits_write(marker_face, 2, 1);		// right face
		if (value <= tex3D<type>(chunk, px + 1, 1, pz + 3)) subdivide_int3bits_write(marker_face, 3, 1);		// back face
		if (value <= tex3D<type>(chunk, px + 1, 2, pz + 2)) subdivide_int3bits_write(marker_face, 5, 1);		// bottom face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, 1, pz + 1))	   subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, 1, pz + 1))   subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 5) && value < tex3D<type>(chunk, px + 1, 2, pz + 1))   subdivide_int3bits_write(marker_edge, 1, 1);		// front-bottom edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, 2, pz + 2))	   subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, 2, pz + 2))  subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px, 1, pz + 3))	   subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px + 2, 1, pz + 3))  subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 1, 2, pz + 3))  subdivide_int3bits_write(marker_edge, 9, 1);		// back-bottom edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 4) && value < tex3D<type>(chunk, px, 2, pz + 1))		  subdivide_int3bits_write(marker_vert, 2, 1); 	// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 5) && value < tex3D<type>(chunk, px + 2, 2, pz + 1))   subdivide_int3bits_write(marker_vert, 3, 1); 	// front-bottom-right vertex
		if (subdivide_int3bits_read(marker_edge, 4) && subdivide_int3bits_read(marker_edge, 7) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px, 2, pz + 3))	  subdivide_int3bits_write(marker_vert, 6, 1); 	// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 5) && subdivide_int3bits_read(marker_edge, 8) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px + 2, 2, pz + 3))  subdivide_int3bits_write(marker_vert, 7, 1); 	// back-bottom-right vertex

		pos = (STRIDE_Y) * (chunkSizeH * 2 + 1);
		// Coordinate of top face of the current thread in the global grid
		pw = pos * (pz * 2 + 1) + px * 2 + 1;
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		// 2-cell
		if (subdivide_int3bits_read(marker_face, 5)) { match_global[pw] = 0x500;			writeCubi(crit_global[pw], 6); }				// top-face of current voxel (not immediate upper voxel)
		// 1-cells
		if (subdivide_int3bits_read(marker_edge, 1)) { match_global[pw - pos] = 0x541;		writeCubi(crit_global[pw - pos], 10); }			// front-top edge	
		if (subdivide_int3bits_read(marker_edge, 4)) { match_global[pw - 1] = 0x514;		writeCubi(crit_global[pw - 1], 13); }			// top-left edge
		if (subdivide_int3bits_read(marker_edge, 5)) { match_global[pw + 1] = 0x514;		writeCubi(crit_global[pw + 1], 14); }			// top-right edge
		if (subdivide_int3bits_read(marker_edge, 9)) { match_global[pw + pos] = 0x541;		writeCubi(crit_global[pw + pos], 18); }			// back-top edge
		// 0-cells
		if (subdivide_int3bits_read(marker_vert, 2)) { match_global[pw - pos - 1] = 0x555;  writeCubi(crit_global[pw - pos - 1], 21); }		// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 3)) { match_global[pw - pos + 1] = 0x555;  writeCubi(crit_global[pw - pos + 1], 22); }		// front-top-right vertex
		if (subdivide_int3bits_read(marker_vert, 6)) { match_global[pw + pos - 1] = 0x555;  writeCubi(crit_global[pw + pos - 1], 25); }		// back-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 7)) { match_global[pw + pos + 1] = 0x555;  writeCubi(crit_global[pw + pos + 1], 26); }		// back-top-right vertex

		// Decide 4-strata edges
		if (threadIdx.z == 0 && subdivide_int3bits_read(marker_edge, 1)) {																	// front-bottom | front-top edge
			subdivide_int3bits_write(marker_edge, 1, 2); writeCrit(crit_global[pw - pos], 2);
		}
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_edge, 4)) {												// bottom-left | top-left edge
			subdivide_int3bits_write(marker_edge, 4, 2); writeCrit(crit_global[pw - 1], 2);
		}
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_edge, 5)) {															// bottom-right | top-right edge
			subdivide_int3bits_write(marker_edge, 5, 2); writeCrit(crit_global[pw + 1], 2);
		}
		if ((LAST_Z || pz == chunkSizeD - 1) && subdivide_int3bits_read(marker_edge, 9)) {													// back-bottom | back-top edge
			subdivide_int3bits_write(marker_edge, 9, 2); writeCrit(crit_global[pw + pos], 2);
		}
		// Match bottom face to one of the edges
		if (subdivide_int3bits_read(marker_face, 5)) {
			if (subdivide_int3bits_read(marker_edge, 1) == 1) {
				subdivide_int3bits_write(marker_edge, 1, 3); subdivide_short2bits_write1(match_global[pw], 0); subdivide_short2bits_write0(match_global[pw - pos], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 4) == 1) {
				subdivide_int3bits_write(marker_edge, 4, 3); subdivide_short2bits_write1(match_global[pw], 1); subdivide_short2bits_write0(match_global[pw - 1], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 5) == 1) {
				subdivide_int3bits_write(marker_edge, 5, 3); subdivide_short2bits_write1(match_global[pw], 2); subdivide_short2bits_write0(match_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 1) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_short2bits_write1(match_global[pw], 3); subdivide_short2bits_write0(match_global[pw + pos], 0);
			}
			else writeCrit(crit_global[pw], 3);
		}
		// Re-match eligible 4-strata edges to vertices
		// Collect vertices strata information before making changes to the edges
		if (subdivide_int3bits_read(marker_vert, 2)) subdivide_int3bits_write(marker_face, 6, (subdivide_int3bits_read(marker_edge, 1) == 2) + (subdivide_int3bits_read(marker_edge, 4) == 2));
		if (subdivide_int3bits_read(marker_vert, 3)) subdivide_int3bits_write(marker_face, 7, (subdivide_int3bits_read(marker_edge, 1) == 2) + (subdivide_int3bits_read(marker_edge, 5) == 2));
		if (subdivide_int3bits_read(marker_vert, 6)) subdivide_int3bits_write(marker_face, 8, (subdivide_int3bits_read(marker_edge, 4) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2));
		if (subdivide_int3bits_read(marker_vert, 7)) subdivide_int3bits_write(marker_face, 9, (subdivide_int3bits_read(marker_edge, 5) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2));
		// Match 4-strata edges to vertices
		if (subdivide_int3bits_read(marker_face, 6) == 2) { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 6) == 1) {
			if (subdivide_int3bits_read(marker_edge, 1) == 2) {
				subdivide_int3bits_write(marker_edge, 1, 3);  subdivide_int3bits_write(marker_vert, 2, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 2); subdivide_short2bits_write1(match_global[pw - pos], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 4) == 2) {
				subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 3); subdivide_short2bits_write1(match_global[pw - 1], 0);
			}
			else { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 7) == 2) { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 7) == 1) {
			if (subdivide_int3bits_read(marker_edge, 1) == 2) {
				subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 1); subdivide_short2bits_write1(match_global[pw - pos], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 5) == 2) {
				subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 3); subdivide_short2bits_write1(match_global[pw + 1], 0);
			}
			else { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 8) == 2) { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 8) == 1) {
			if (subdivide_int3bits_read(marker_edge, 4) == 2) {
				subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 0); subdivide_short2bits_write1(match_global[pw - 1], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1);
			}
			else { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 9) == 2) { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 9) == 1) {
			if (subdivide_int3bits_read(marker_edge, 5) == 2) {
				subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 0); subdivide_short2bits_write1(match_global[pw + 1], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2);
			}
			else { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		}

		// Match non-4-strata edges to non-4-starta vertices, only bottom-left, bottom-right, back-bottom edges are included, as front-bottom edge either has been matched or is 4-strata
		if (subdivide_int3bits_read(marker_edge, 4) == 1) {
			if (subdivide_int3bits_read(marker_vert, 2) == 1) { subdivide_int3bits_write(marker_vert, 2, 3); subdivide_short2bits_write0(match_global[pw - pos - 1], 3); subdivide_short2bits_write1(match_global[pw - 1], 0); }
			else if (subdivide_int3bits_read(marker_vert, 6) == 1) { subdivide_int3bits_write(marker_vert, 6, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 0); subdivide_short2bits_write1(match_global[pw - 1], 3); }
			else writeCrit(crit_global[pw - 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 5) == 1) {
			if (subdivide_int3bits_read(marker_vert, 3) == 1) { subdivide_int3bits_write(marker_vert, 3, 3); subdivide_short2bits_write0(match_global[pw - pos + 1], 3); subdivide_short2bits_write1(match_global[pw + 1], 0); }
			else if (subdivide_int3bits_read(marker_vert, 7) == 1) { subdivide_int3bits_write(marker_vert, 7, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 0); subdivide_short2bits_write1(match_global[pw + 1], 3); }
			else writeCrit(crit_global[pw + 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 9) == 1) {
			if (subdivide_int3bits_read(marker_vert, 6) == 1) { subdivide_int3bits_write(marker_vert, 6, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1); }
			else if (subdivide_int3bits_read(marker_vert, 7) == 1) { subdivide_int3bits_write(marker_vert, 7, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2); }
			else writeCrit(crit_global[pw + pos], 2);
		}

		// Mark all vertices in L(x) at border but not matched as critical
		if (subdivide_int3bits_read(marker_vert, 2) == 1) writeCrit(crit_global[pw - pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 3) == 1) writeCrit(crit_global[pw - pos + 1], 1);
		if (subdivide_int3bits_read(marker_vert, 6) == 1) writeCrit(crit_global[pw + pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 7) == 1) writeCrit(crit_global[pw + pos + 1], 1);
	}

	// Chunk lower border handling
	if (py == chunkSizeH - 1) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of imediate upper voxel L(x) with total ordering enforced
		value = tex3D<type>(chunk, px + 1, chunkSizeH + 2, pz + 2);															// load value of immediate lower voxel
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px + 1,	chunkSizeH + 2, pz + 1))  subdivide_int3bits_write(marker_face, 0, 1);		// front face
		if (value < tex3D<type>(chunk, px,		chunkSizeH + 2, pz + 2))  subdivide_int3bits_write(marker_face, 1, 1);		// left face
		if (value <= tex3D<type>(chunk, px + 2, chunkSizeH + 2, pz + 2))  subdivide_int3bits_write(marker_face, 2, 1);		// right face
		if (value <= tex3D<type>(chunk, px + 1, chunkSizeH + 2, pz + 3))  subdivide_int3bits_write(marker_face, 3, 1);		// back face
		if (value < tex3D<type>(chunk, px + 1,	chunkSizeH + 1, pz + 2))  subdivide_int3bits_write(marker_face, 4, 1);		// top face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 1, chunkSizeH + 1, pz + 1))  subdivide_int3bits_write(marker_vert, 8, 1);		// front-top edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, chunkSizeH + 2, pz + 1))	   subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 2, pz + 1))  subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, chunkSizeH + 1, pz + 2))	   subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 1, pz + 2))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 4) && value <= tex3D<type>(chunk, px + 1, chunkSizeH + 1, pz + 3)) subdivide_int3bits_write(marker_edge, 6, 1);		// back-top edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px, chunkSizeH + 2, pz + 3))	   subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px + 2, chunkSizeH + 2, pz + 3)) subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 2) && value < tex3D<type>(chunk, px, chunkSizeH + 1, pz + 1))	  subdivide_int3bits_write(marker_vert, 0, 1);	// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 3) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 1, pz + 1))  subdivide_int3bits_write(marker_vert, 1, 1);	// front-top-right vertex
		if (subdivide_int3bits_read(marker_edge, 2) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 7) && value <= tex3D<type>(chunk, px, chunkSizeH + 1, pz + 3))	  subdivide_int3bits_write(marker_vert, 4, 1);	// back-top-left vertex
		if (subdivide_int3bits_read(marker_edge, 3) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 8) && value <= tex3D<type>(chunk, px + 2, chunkSizeH + 1, pz + 3)) subdivide_int3bits_write(marker_vert, 5, 1);	// back-top-right vertex

		pos = (STRIDE_Y) * (chunkSizeH * 2 + 1);
		// Coordinate of bottom face of the current thread in the global grid
		pw = pos * (pz * 2 + 1) + STRIDE_Y * (chunkSizeH * 2) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		// 2-cell
		if (subdivide_int3bits_read(marker_face, 4)) { match_global[pw] = 0x500;			writeCubi(crit_global[pw], 5); }				// bottom-face of current voxel (not immediate lower voxel)
		// 1-cells
		if (subdivide_int3bits_read(marker_vert, 8)) { match_global[pw - pos] = 0x541;		writeCubi(crit_global[pw - pos], 7); }			// front-bottom edge
		if (subdivide_int3bits_read(marker_edge, 2)) { match_global[pw - 1] = 0x514;		writeCubi(crit_global[pw - 1], 11); }			// bottom-left edge
		if (subdivide_int3bits_read(marker_edge, 3)) { match_global[pw + 1] = 0x514;		writeCubi(crit_global[pw + 1], 12); }			// bottom-right edge
		if (subdivide_int3bits_read(marker_edge, 6)) { match_global[pw + pos] = 0x541;		writeCubi(crit_global[pw + pos], 15); }			// back-bottom edge
		// 0-cells
		if (subdivide_int3bits_read(marker_vert, 0)) { match_global[pw - pos - 1] = 0x555;	writeCubi(crit_global[pw - pos - 1], 19); }		// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 1)) { match_global[pw - pos + 1] = 0x555;	writeCubi(crit_global[pw - pos + 1], 20); }		// front-bottom-right vertex
		if (subdivide_int3bits_read(marker_vert, 4)) { match_global[pw + pos - 1] = 0x555;	writeCubi(crit_global[pw + pos - 1], 23); }		// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 5)) { match_global[pw + pos + 1] = 0x555;	writeCubi(crit_global[pw + pos + 1], 24); }		// back-bottom-right vertex

		// Decide 4-strata edges
		if (threadIdx.z == 0 && subdivide_int3bits_read(marker_vert, 8)) {																	// front-top | front-bottom edge
			subdivide_int3bits_write(marker_vert, 8, 2); writeCrit(crit_global[pw - pos], 2);
		}
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_edge, 2)) {												// top-left | bottom-left edge
			subdivide_int3bits_write(marker_edge, 2, 2); writeCrit(crit_global[pw - 1], 2);
		}
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_edge, 3)) {						// top-right | bottom-right edge
			subdivide_int3bits_write(marker_edge, 3, 2); writeCrit(crit_global[pw + 1], 2);
		}
		if ((LAST_Z || pz == chunkSizeD - 1) && subdivide_int3bits_read(marker_edge, 6)) {			// back-top | back-bottom edge
			subdivide_int3bits_write(marker_edge, 6, 2); writeCrit(crit_global[pw + pos], 2);
		}
		// Match top face to one of the edges
		if (subdivide_int3bits_read(marker_face, 4)) {
			if (subdivide_int3bits_read(marker_vert, 8) == 1) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_short2bits_write1(match_global[pw], 0); subdivide_short2bits_write0(match_global[pw - pos], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 2) == 1) {
				subdivide_int3bits_write(marker_edge, 2, 3); subdivide_short2bits_write1(match_global[pw], 1); subdivide_short2bits_write0(match_global[pw - 1], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 3) == 1) {
				subdivide_int3bits_write(marker_edge, 3, 3); subdivide_short2bits_write1(match_global[pw], 2); subdivide_short2bits_write0(match_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 6) == 1) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_short2bits_write1(match_global[pw], 3); subdivide_short2bits_write0(match_global[pw + pos], 0);
			}
			else writeCrit(crit_global[pw], 3);
		}
		// Re-match eligible 4-strata edges to vertices
		// Collect vertices strata information before making changes to the edges
		if (subdivide_int3bits_read(marker_vert, 0)) subdivide_int3bits_write(marker_face, 6, (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_edge, 2) == 2));
		if (subdivide_int3bits_read(marker_vert, 1)) subdivide_int3bits_write(marker_face, 7, (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_edge, 3) == 2));
		if (subdivide_int3bits_read(marker_vert, 4)) subdivide_int3bits_write(marker_face, 8, (subdivide_int3bits_read(marker_edge, 2) == 2) + (subdivide_int3bits_read(marker_edge, 6) == 2));
		if (subdivide_int3bits_read(marker_vert, 5)) subdivide_int3bits_write(marker_face, 9, (subdivide_int3bits_read(marker_edge, 3) == 2) + (subdivide_int3bits_read(marker_edge, 6) == 2));
		// Match 4-strata edges to vertices
		if (subdivide_int3bits_read(marker_face, 6) == 2) { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 6) == 1) {
			if (subdivide_int3bits_read(marker_vert, 8) == 2) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 2); subdivide_short2bits_write1(match_global[pw - pos], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 2) == 2) {
				subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 3); subdivide_short2bits_write1(match_global[pw - 1], 0);
			}
			else { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 7) == 2) { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 7) == 1) {
			if (subdivide_int3bits_read(marker_vert, 8) == 2) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 1); subdivide_short2bits_write1(match_global[pw - pos], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 3) == 2) {
				subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 3); subdivide_short2bits_write1(match_global[pw + 1], 0);
			}
			else { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 8) == 2) { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 8) == 1) {
			if (subdivide_int3bits_read(marker_edge, 2) == 2) {
				subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 0); subdivide_short2bits_write1(match_global[pw - 1], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 6) == 2) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1);
			}
			else { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 9) == 2) { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 9) == 1) {
			if (subdivide_int3bits_read(marker_edge, 3) == 2) {
				subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 0); subdivide_short2bits_write1(match_global[pw + 1], 3);
			}
			else if (subdivide_int3bits_read(marker_edge, 6) == 2) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2);
			}
			else { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		}

		// Match non-4-strata edges to non-4-starta vertices, only top-left, top-right, back-top edges are included, as front-top edge either has been matched or is 4-strata
		if (subdivide_int3bits_read(marker_edge, 2) == 1) {
			if (subdivide_int3bits_read(marker_vert, 0) == 1) { subdivide_int3bits_write(marker_vert, 0, 3); subdivide_short2bits_write0(match_global[pw - pos - 1], 3); subdivide_short2bits_write1(match_global[pw - 1], 0); }
			else if (subdivide_int3bits_read(marker_vert, 4) == 1) { subdivide_int3bits_write(marker_vert, 4, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 0); subdivide_short2bits_write1(match_global[pw - 1], 3); }
			else writeCrit(crit_global[pw - 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 3) == 1) {
			if (subdivide_int3bits_read(marker_vert, 1) == 1) { subdivide_int3bits_write(marker_vert, 1, 3); subdivide_short2bits_write0(match_global[pw - pos + 1], 3); subdivide_short2bits_write1(match_global[pw + 1], 0); }
			else if (subdivide_int3bits_read(marker_vert, 5) == 1) { subdivide_int3bits_write(marker_vert, 5, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 0); subdivide_short2bits_write1(match_global[pw + 1], 3); }
			else writeCrit(crit_global[pw + 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 6) == 1) {
			if (subdivide_int3bits_read(marker_vert, 4) == 1) { subdivide_int3bits_write(marker_vert, 4, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1); }
			else if (subdivide_int3bits_read(marker_vert, 5) == 1) { subdivide_int3bits_write(marker_vert, 5, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2); }
			else writeCrit(crit_global[pw + pos], 2);
		}

		// Mark all vertices in L(x) at border but not matched as critical
		if (subdivide_int3bits_read(marker_vert, 0) == 1) writeCrit(crit_global[pw - pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 1) == 1) writeCrit(crit_global[pw - pos + 1], 1);
		if (subdivide_int3bits_read(marker_vert, 4) == 1) writeCrit(crit_global[pw + pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 5) == 1) writeCrit(crit_global[pw + pos + 1], 1);
	}

	// Chunk front border handling
	if (pz == 0) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of imediate front voxel L(x) with total ordering enforced
		value = tex3D<type>(chunk, px + 1, py + 2, 1);															// load value of immediate front voxel
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px, py + 2, 1)) subdivide_int3bits_write(marker_face, 1, 1);				// left face
		if (value <= tex3D<type>(chunk, px + 2, py + 2, 1)) subdivide_int3bits_write(marker_face, 2, 1);		// right face
		if (value <= tex3D<type>(chunk, px + 1, py + 2, 2)) subdivide_int3bits_write(marker_face, 3, 1);		// back face
		if (value < tex3D<type>(chunk, px + 1, py + 1, 1)) subdivide_int3bits_write(marker_face, 4, 1);			// top face
		if (value <= tex3D<type>(chunk, px + 1, py + 3, 1)) subdivide_int3bits_write(marker_face, 5, 1);		// bottom face
		// Decide the ownership of edges (1-cells)	
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, py + 1, 1))      subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, py + 1, 1))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, py + 3, 1))	  subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, py + 3, 1)) subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 4) && value <= tex3D<type>(chunk, px + 1, py + 1, 2)) subdivide_int3bits_write(marker_edge, 6, 1);		// back-top edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px, py + 2, 2))	  subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px + 2, py + 2, 2)) subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 1, py + 3, 2)) subdivide_int3bits_write(marker_edge, 9, 1);		// back-bottom edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_edge, 2) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 7) && value <= tex3D<type>(chunk, px, py + 1, 2))		subdivide_int3bits_write(marker_vert, 4, 1);	// back-top-left vertex
		if (subdivide_int3bits_read(marker_edge, 3) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 8) && value <= tex3D<type>(chunk, px + 2, py + 1, 2))	subdivide_int3bits_write(marker_vert, 5, 1);	// back-top-right vertex
		if (subdivide_int3bits_read(marker_edge, 4) && subdivide_int3bits_read(marker_edge, 7) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px, py + 3, 2))		subdivide_int3bits_write(marker_vert, 6, 1);	// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 5) && subdivide_int3bits_read(marker_edge, 8) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px + 2, py + 3, 2))	subdivide_int3bits_write(marker_vert, 7, 1);	// back-bottom-right vertex

		pos = STRIDE_Y;
		// Coordinate of front face of the current thread in the global grid
		pw = pos * (py * 2 + 1) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		// 2-cell
		if (subdivide_int3bits_read(marker_face, 3)) { match_global[pw] = 0x41;				writeCubi(crit_global[pw], 4); }				// front-face of current voxel (not immediate front voxel)
		// 1-cells
		if (subdivide_int3bits_read(marker_edge, 6)) { match_global[pw - pos] = 0x541;		writeCubi(crit_global[pw - pos], 15); }			// front-top edge
		if (subdivide_int3bits_read(marker_edge, 7)) { match_global[pw - 1] = 0x55;			writeCubi(crit_global[pw - 1], 16); }			// front-left edge
		if (subdivide_int3bits_read(marker_edge, 8)) { match_global[pw + 1] = 0x55;			writeCubi(crit_global[pw + 1], 17); }			// front-right edge
		if (subdivide_int3bits_read(marker_edge, 9)) { match_global[pw + pos] = 0x541;		writeCubi(crit_global[pw + pos], 18); }			// front-bottom edge
		// 0-cells
		if (subdivide_int3bits_read(marker_vert, 4)) { match_global[pw - pos - 1] = 0x555;	writeCubi(crit_global[pw - pos - 1], 23); }		// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 5)) { match_global[pw - pos + 1] = 0x555;	writeCubi(crit_global[pw - pos + 1], 24); }		// front-top-right vertex
		if (subdivide_int3bits_read(marker_vert, 6)) { match_global[pw + pos - 1] = 0x555;	writeCubi(crit_global[pw + pos - 1], 25); }		// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 7)) { match_global[pw + pos + 1] = 0x555;	writeCubi(crit_global[pw + pos + 1], 26); }		// front-bottom-right vertex

		// Decide 4-strata edges
		if (threadIdx.y == 0 && subdivide_int3bits_read(marker_edge, 6)) {																	// back-top edge | front-top edge
			subdivide_int3bits_write(marker_edge, 6, 2); writeCrit(crit_global[pw - pos], 2);
		}
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_edge, 7)) {												// back-left edge | front-left edge
			subdivide_int3bits_write(marker_edge, 7, 2); writeCrit(crit_global[pw - 1], 2);
		}
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_edge, 8)) {						// back-right edge | front-right edge
			subdivide_int3bits_write(marker_edge, 8, 2); writeCrit(crit_global[pw + 1], 2);
		}
		if ((LAST_Y || py == chunkSizeH - 1) && subdivide_int3bits_read(marker_edge, 9)) {							// back-bottom edge | front-bottom edge
			subdivide_int3bits_write(marker_edge, 9, 2); writeCrit(crit_global[pw + pos], 2);
		}
		// Match back face to one of the edges
		if (subdivide_int3bits_read(marker_face, 3)) {
			if (subdivide_int3bits_read(marker_edge, 6) == 1) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_short2bits_write1(match_global[pw], 4); subdivide_short2bits_write0(match_global[pw - pos], 5);
			}
			else if (subdivide_int3bits_read(marker_edge, 7) == 1) {
				subdivide_int3bits_write(marker_edge, 7, 3); subdivide_short2bits_write1(match_global[pw], 1); subdivide_short2bits_write0(match_global[pw - 1], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 8) == 1) {
				subdivide_int3bits_write(marker_edge, 8, 3); subdivide_short2bits_write1(match_global[pw], 2); subdivide_short2bits_write0(match_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 1) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_short2bits_write1(match_global[pw], 5); subdivide_short2bits_write0(match_global[pw + pos], 4);
			}
			else writeCrit(crit_global[pw], 3);
		}
		// Re-match eligible 4-strata edges to vertices
		// Collect vertices strata information before making changes to the edges
		if (subdivide_int3bits_read(marker_vert, 4)) subdivide_int3bits_write(marker_face, 6, (subdivide_int3bits_read(marker_edge, 6) == 2) + (subdivide_int3bits_read(marker_edge, 7) == 2));
		if (subdivide_int3bits_read(marker_vert, 5)) subdivide_int3bits_write(marker_face, 7, (subdivide_int3bits_read(marker_edge, 6) == 2) + (subdivide_int3bits_read(marker_edge, 8) == 2));
		if (subdivide_int3bits_read(marker_vert, 6)) subdivide_int3bits_write(marker_face, 8, (subdivide_int3bits_read(marker_edge, 7) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2));
		if (subdivide_int3bits_read(marker_vert, 7)) subdivide_int3bits_write(marker_face, 9, (subdivide_int3bits_read(marker_edge, 8) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2));
		// Match 4-strata edges to vertices
		if (subdivide_int3bits_read(marker_face, 6) == 2) { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 6) == 1) {
			if (subdivide_int3bits_read(marker_edge, 6) == 2) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 2); subdivide_short2bits_write1(match_global[pw - pos], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 7) == 2) {
				subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 5); subdivide_short2bits_write1(match_global[pw - 1], 4);
			}
			else { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 7) == 2) { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 7) == 1) {
			if (subdivide_int3bits_read(marker_edge, 6) == 2) {
				subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 1); subdivide_short2bits_write1(match_global[pw - pos], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 8) == 2) {
				subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 5); subdivide_short2bits_write1(match_global[pw + 1], 4);
			}
			else { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 8) == 2) { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 8) == 1) {
			if (subdivide_int3bits_read(marker_edge, 7) == 2) {
				subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 4); subdivide_short2bits_write1(match_global[pw - 1], 5);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1);
			}
			else { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 9) == 2) { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 9) == 1) {
			if (subdivide_int3bits_read(marker_edge, 8) == 2) {
				subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 4); subdivide_short2bits_write1(match_global[pw + 1], 5);
			}
			else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
				subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2);
			}
			else { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		}

		// Match non-4-strata edges to non-4-starta vertices, only back-left, back-right, back-bottom edges are included, as back-top edge either has been matched or is 4-strata
		if (subdivide_int3bits_read(marker_edge, 7) == 1) {
			if (subdivide_int3bits_read(marker_vert, 4) == 1) { subdivide_int3bits_write(marker_vert, 4, 3); subdivide_short2bits_write0(match_global[pw - pos - 1], 5); subdivide_short2bits_write1(match_global[pw - 1], 4); }
			else if (subdivide_int3bits_read(marker_vert, 6) == 1) { subdivide_int3bits_write(marker_vert, 6, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 4); subdivide_short2bits_write1(match_global[pw - 1], 5); }
			else writeCrit(crit_global[pw - 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 8) == 1) {
			if (subdivide_int3bits_read(marker_vert, 5) == 1) { subdivide_int3bits_write(marker_vert, 5, 3); subdivide_short2bits_write0(match_global[pw - pos + 1], 5); subdivide_short2bits_write1(match_global[pw + 1], 4); }
			else if (subdivide_int3bits_read(marker_vert, 7) == 1) { subdivide_int3bits_write(marker_vert, 7, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 4); subdivide_short2bits_write1(match_global[pw + 1], 5); }
			else writeCrit(crit_global[pw + 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 9) == 1) {
			if (subdivide_int3bits_read(marker_vert, 6) == 1) { subdivide_int3bits_write(marker_vert, 6, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1); }
			else if (subdivide_int3bits_read(marker_vert, 7) == 1) { subdivide_int3bits_write(marker_vert, 7, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2); }
			else writeCrit(crit_global[pw + pos], 2);
		}

		// Mark all vertices in L(x) at border but not matched as critical
		if (subdivide_int3bits_read(marker_vert, 4) == 1) writeCrit(crit_global[pw - pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 5) == 1) writeCrit(crit_global[pw - pos + 1], 1);
		if (subdivide_int3bits_read(marker_vert, 6) == 1) writeCrit(crit_global[pw + pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 7) == 1) writeCrit(crit_global[pw + pos + 1], 1);
	}

	// Chunk back border handling
	if (pz == chunkSizeD - 1) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of imediate back voxel L(x) with total ordering enforced
		value = tex3D<type>(chunk, px + 1, py + 2, chunkSizeD + 2);																// load value of immediate back voxel
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px + 1, py + 2, chunkSizeD + 1))		subdivide_int3bits_write(marker_face, 0, 1);		// front face
		if (value < tex3D<type>(chunk, px, py + 2, chunkSizeD + 2))			subdivide_int3bits_write(marker_face, 1, 1);		// left face
		if (value <= tex3D<type>(chunk, px + 2, py + 2, chunkSizeD + 2))	subdivide_int3bits_write(marker_face, 2, 1);		// right face
		if (value < tex3D<type>(chunk, px + 1, py + 1, chunkSizeD + 2))		subdivide_int3bits_write(marker_face, 4, 1);		// top face
		if (value <= tex3D<type>(chunk, px + 1, py + 3, chunkSizeD + 2))	subdivide_int3bits_write(marker_face, 5, 1);		// bottom face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 1, py + 1, chunkSizeD + 1))  subdivide_int3bits_write(marker_vert, 8, 1);		// front-top edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, py + 2, chunkSizeD + 1))      subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, py + 2, chunkSizeD + 1))  subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 5) && value < tex3D<type>(chunk, px + 1, py + 3, chunkSizeD + 1))  subdivide_int3bits_write(marker_edge, 1, 1);		// front-bottom edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, py + 1, chunkSizeD + 2))      subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, py + 1, chunkSizeD + 2))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, py + 3, chunkSizeD + 2))     subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, py + 3, chunkSizeD + 2)) subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 2) && value < tex3D<type>(chunk, px, py + 1, chunkSizeD + 1))	  subdivide_int3bits_write(marker_vert, 0, 1);	// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 3) && value < tex3D<type>(chunk, px + 2, py + 1, chunkSizeD + 1))  subdivide_int3bits_write(marker_vert, 1, 1);	// front-top-right vertex
		if (subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 4) && value < tex3D<type>(chunk, px, py + 3, chunkSizeD + 1))	  subdivide_int3bits_write(marker_vert, 2, 1);	// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 5) && value < tex3D<type>(chunk, px + 2, py + 3, chunkSizeD + 1))  subdivide_int3bits_write(marker_vert, 3, 1);	// front-bottom-right vertex

		pos = STRIDE_Y;
		// Coordinate of back face of the current thread in the global grid
		pw = STRIDE_Y * (chunkSizeH * 2 + 1) * (chunkSizeD * 2) + pos * (py * 2 + 1) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		// 2-cell
		if (subdivide_int3bits_read(marker_face, 0)) { match_global[pw] = 0x41;				writeCubi(crit_global[pw], 1); }				// back-face of current voxel (not immediate front voxel)
		// 1-cells
		if (subdivide_int3bits_read(marker_vert, 8)) { match_global[pw - pos] = 0x541;		writeCubi(crit_global[pw - pos], 7); }			// back-top edge
		if (subdivide_int3bits_read(marker_vert, 9)) { match_global[pw - 1] = 0x55;			writeCubi(crit_global[pw - 1], 8); }			// back-left edge
		if (subdivide_int3bits_read(marker_edge, 0)) { match_global[pw + 1] = 0x55;			writeCubi(crit_global[pw + 1], 9); }			// back-right edge
		if (subdivide_int3bits_read(marker_edge, 1)) { match_global[pw + pos] = 0x541;		writeCubi(crit_global[pw + pos], 10); }			// back-bottom edge
		// 0-cells
		if (subdivide_int3bits_read(marker_vert, 0)) { match_global[pw - pos - 1] = 0x555;	writeCubi(crit_global[pw - pos - 1], 19); }		// back-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 1)) { match_global[pw - pos + 1] = 0x555;	writeCubi(crit_global[pw - pos + 1], 20); }		// back-top-right vertex
		if (subdivide_int3bits_read(marker_vert, 2)) { match_global[pw + pos - 1] = 0x555;	writeCubi(crit_global[pw + pos - 1], 21); }		// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 3)) { match_global[pw + pos + 1] = 0x555;	writeCubi(crit_global[pw + pos + 1], 22); }		// back-bottom-right vertex

		// Decide 4-strata edges
		if (threadIdx.y == 0 && subdivide_int3bits_read(marker_vert, 8)) {																	// front-top edge | back-top edge
			subdivide_int3bits_write(marker_vert, 8, 2); writeCrit(crit_global[pw - pos], 2);
		}
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_vert, 9)) {												// front-left edge | back-left edge
			subdivide_int3bits_write(marker_vert, 9, 2); writeCrit(crit_global[pw - 1], 2);
		}
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_edge, 0)) {						// front-right edge | back-right edge
			subdivide_int3bits_write(marker_edge, 0, 2); writeCrit(crit_global[pw + 1], 2);
		}
		if ((LAST_Y || py == chunkSizeH - 1) && subdivide_int3bits_read(marker_edge, 1)) {			// front-bottom edge | back-bottom edge
			subdivide_int3bits_write(marker_edge, 1, 2); writeCrit(crit_global[pw + pos], 2);
		}
		// Match front face to one of the edges
		if (subdivide_int3bits_read(marker_face, 0)) {
			if (subdivide_int3bits_read(marker_vert, 8) == 1) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_short2bits_write1(match_global[pw], 4); subdivide_short2bits_write0(match_global[pw - pos], 5);
			}
			else if (subdivide_int3bits_read(marker_vert, 9) == 1) {
				subdivide_int3bits_write(marker_vert, 9, 3); subdivide_short2bits_write1(match_global[pw], 1); subdivide_short2bits_write0(match_global[pw - 1], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 0) == 1) {
				subdivide_int3bits_write(marker_edge, 0, 3); subdivide_short2bits_write1(match_global[pw], 2); subdivide_short2bits_write0(match_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_edge, 1) == 1) {
				subdivide_int3bits_write(marker_edge, 1, 3); subdivide_short2bits_write1(match_global[pw], 5); subdivide_short2bits_write0(match_global[pw + pos], 4);
			}
			else writeCrit(crit_global[pw], 3);
		}
		// Re-match eligible 4-strata edges to vertices
		// Collect vertices strata information before making changes to the edges
		if (subdivide_int3bits_read(marker_vert, 0)) subdivide_int3bits_write(marker_face, 6, (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_vert, 9) == 2));
		if (subdivide_int3bits_read(marker_vert, 1)) subdivide_int3bits_write(marker_face, 7, (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_edge, 0) == 2));
		if (subdivide_int3bits_read(marker_vert, 2)) subdivide_int3bits_write(marker_face, 8, (subdivide_int3bits_read(marker_vert, 9) == 2) + (subdivide_int3bits_read(marker_edge, 1) == 2));
		if (subdivide_int3bits_read(marker_vert, 3)) subdivide_int3bits_write(marker_face, 9, (subdivide_int3bits_read(marker_edge, 0) == 2) + (subdivide_int3bits_read(marker_edge, 1) == 2));
		// Match 4-strata edges to vertices
		if (subdivide_int3bits_read(marker_face, 6) == 2) { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 6) == 1) {
			if (subdivide_int3bits_read(marker_vert, 8) == 2) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 2); subdivide_short2bits_write1(match_global[pw - pos], 1);
			}
			else if (subdivide_int3bits_read(marker_vert, 9) == 2) {
				subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos - 1], 5); subdivide_short2bits_write1(match_global[pw - 1], 4);
			}
			else { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_global[pw - pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 7) == 2) { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 7) == 1) {
			if (subdivide_int3bits_read(marker_vert, 8) == 2) {
				subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_global[pw - pos] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 1); subdivide_short2bits_write1(match_global[pw - pos], 2);
			}
			else if (subdivide_int3bits_read(marker_edge, 0) == 2) {
				subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw - pos + 1], 5); subdivide_short2bits_write1(match_global[pw + 1], 4);
			}
			else { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_global[pw - pos + 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 8) == 2) { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 8) == 1) {
			if (subdivide_int3bits_read(marker_vert, 9) == 2) {
				subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_global[pw - 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 4); subdivide_short2bits_write1(match_global[pw - 1], 5);
			}
			else if (subdivide_int3bits_read(marker_edge, 1) == 2) {
				subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1);
			}
			else { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_global[pw + pos - 1], 1); }
		}

		if (subdivide_int3bits_read(marker_face, 9) == 2) { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		else if (subdivide_int3bits_read(marker_face, 9) == 1) {
			if (subdivide_int3bits_read(marker_edge, 0) == 2) {
				subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_global[pw + 1] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 4); subdivide_short2bits_write1(match_global[pw + 1], 5);
			}
			else if (subdivide_int3bits_read(marker_edge, 1) == 2) {
				subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_global[pw + pos] &= 248;
				subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2);
			}
			else { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_global[pw + pos + 1], 1); }
		}

		// Match non-4-strata edges to non-4-starta vertices, only front-left, front-right, front-bottom edges are included, as front-top edge either has been matched or is 4-strata
		if (subdivide_int3bits_read(marker_vert, 9) == 1) {
			if (subdivide_int3bits_read(marker_vert, 0) == 1) { subdivide_int3bits_write(marker_vert, 0, 3); subdivide_short2bits_write0(match_global[pw - pos - 1], 5); subdivide_short2bits_write1(match_global[pw - 1], 4); }
			else if (subdivide_int3bits_read(marker_vert, 2) == 1) { subdivide_int3bits_write(marker_vert, 2, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 4); subdivide_short2bits_write1(match_global[pw - 1], 5); }
			else writeCrit(crit_global[pw - 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 0) == 1) {
			if (subdivide_int3bits_read(marker_vert, 1) == 1) { subdivide_int3bits_write(marker_vert, 1, 3); subdivide_short2bits_write0(match_global[pw - pos + 1], 5); subdivide_short2bits_write1(match_global[pw + 1], 4); }
			else if (subdivide_int3bits_read(marker_vert, 3) == 1) { subdivide_int3bits_write(marker_vert, 3, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 4); subdivide_short2bits_write1(match_global[pw + 1], 5); }
			else writeCrit(crit_global[pw + 1], 2);
		}
		if (subdivide_int3bits_read(marker_edge, 1) == 1) {
			if (subdivide_int3bits_read(marker_vert, 2) == 1) { subdivide_int3bits_write(marker_vert, 2, 3); subdivide_short2bits_write0(match_global[pw + pos - 1], 2); subdivide_short2bits_write1(match_global[pw + pos], 1); }
			else if (subdivide_int3bits_read(marker_vert, 3) == 1) { subdivide_int3bits_write(marker_vert, 3, 3); subdivide_short2bits_write0(match_global[pw + pos + 1], 1); subdivide_short2bits_write1(match_global[pw + pos], 2); }
			else writeCrit(crit_global[pw + pos], 2);
		}

		// Mark all vertices in L(x) at border but not matched as critical
		if (subdivide_int3bits_read(marker_vert, 0) == 1) writeCrit(crit_global[pw - pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 1) == 1) writeCrit(crit_global[pw - pos + 1], 1);
		if (subdivide_int3bits_read(marker_vert, 2) == 1) writeCrit(crit_global[pw + pos - 1], 1);
		if (subdivide_int3bits_read(marker_vert, 3) == 1) writeCrit(crit_global[pw + pos + 1], 1);
	}

	// Chunk front top border handling
	if (py == 0 && pz == 0) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of immediate front-top neighbor with total ordering enforced
		value = tex3D<type>(chunk, px + 1, 1, 1);
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px, 1, 1))		subdivide_int3bits_write(marker_face, 1, 1);																							// left face
		if (value <= tex3D<type>(chunk, px + 2, 1, 1))	subdivide_int3bits_write(marker_face, 2, 1);																							// right face
		if (value <= tex3D<type>(chunk, px + 1, 1, 2))	subdivide_int3bits_write(marker_face, 3, 1);																							// back face
		if (value <= tex3D<type>(chunk, px + 1, 2, 1))	subdivide_int3bits_write(marker_face, 5, 1);																							// bottom face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, 2, 1))	  subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, 2, 1))  subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px, 1, 2))	  subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px + 2, 1, 2))  subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 1, 2, 2))  subdivide_int3bits_write(marker_edge, 9, 1);		// back-bottom edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_edge, 4) && subdivide_int3bits_read(marker_edge, 7) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px, 2, 2))		subdivide_int3bits_write(marker_vert, 6, 1);	// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 5) && subdivide_int3bits_read(marker_edge, 8) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px + 2, 2, 2))	subdivide_int3bits_write(marker_vert, 7, 1);	// back-bottom-right vertex
	
		// Coordinate of front-top edge of the current thread in the global grid
		pw = px * 2 + 1;
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		if (subdivide_int3bits_read(marker_edge, 9)) { match_global[pw] = 0x541;	 writeCubi(crit_global[pw], 18); }																			// front-top edge
		if (subdivide_int3bits_read(marker_vert, 6)) { match_global[pw - 1] = 0x555; writeCubi(crit_global[pw - 1], 25); }																		// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 7)) { match_global[pw + 1] = 0x555; writeCubi(crit_global[pw + 1], 26); }																		// front-top-right vertex
		// Decide 4-strata vertices
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_vert, 6)) { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_global[pw - 1], 1); }
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_vert, 7)) { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_global[pw + 1], 1); }
		// Match 4-strata edges with eligible vertices
		if (subdivide_int3bits_read(marker_edge, 9)) {
			if (subdivide_int3bits_read(marker_vert, 6) == 1) {
				subdivide_short2bits_write0(match_global[pw - 1], 2); subdivide_short2bits_write1(match_global[pw], 1);
				if (subdivide_int3bits_read(marker_vert, 7) == 1) writeCrit(crit_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_vert, 7) == 1) { subdivide_short2bits_write0(match_global[pw + 1], 1); subdivide_short2bits_write1(match_global[pw], 2); }
			else writeCrit(crit_global[pw], 2);
		}
	}

	// Chunk front bottom border handling
	if (py == chunkSizeH - 1 && pz == 0) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of immediate front-bottom neighbor with total ordering enforced
		value = tex3D<type>(chunk, px + 1, chunkSizeH + 2, 1);
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px, chunkSizeH + 2, 1))		subdivide_int3bits_write(marker_face, 1, 1);																				// left face
		if (value <= tex3D<type>(chunk, px + 2, chunkSizeH + 2, 1))	subdivide_int3bits_write(marker_face, 2, 1);																				// right face
		if (value <= tex3D<type>(chunk, px + 1, chunkSizeH + 2, 2))	subdivide_int3bits_write(marker_face, 3, 1);																				// back face
		if (value < tex3D<type>(chunk, px + 1, chunkSizeH + 1, 1))  subdivide_int3bits_write(marker_face, 4, 1);																				// top face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, chunkSizeH + 1, 1))	  subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 1, 1))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
		if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 4) && value <= tex3D<type>(chunk, px + 1, chunkSizeH + 1, 2)) subdivide_int3bits_write(marker_edge, 6, 1);		// back-top edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px, chunkSizeH + 2, 2))	  subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 3) && value <= tex3D<type>(chunk, px + 2, chunkSizeH + 2, 2)) subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_edge, 2) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 7) && value <= tex3D<type>(chunk, px, chunkSizeH + 1, 2))	 subdivide_int3bits_write(marker_vert, 4, 1);	// back-top-left vertex
		if (subdivide_int3bits_read(marker_edge, 3) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 8) && value <= tex3D<type>(chunk, px + 2, chunkSizeH + 1, 2)) subdivide_int3bits_write(marker_vert, 5, 1);	// back-top-right vertex
	
		// Coordinate of front-bottom edge of the current thread in the global grid
		pw = STRIDE_Y * (chunkSizeH * 2) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		if (subdivide_int3bits_read(marker_edge, 6)) { match_global[pw] = 0x541;	 writeCubi(crit_global[pw], 15); }																			// front-bottom edge
		if (subdivide_int3bits_read(marker_vert, 4)) { match_global[pw - 1] = 0x555; writeCubi(crit_global[pw - 1], 23); }																		// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 5)) { match_global[pw + 1] = 0x555; writeCubi(crit_global[pw + 1], 24); }																		// front-bottom-right vertex
		// Decide 4-strata vertices
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_vert, 4)) { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_global[pw - 1], 1); }
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_vert, 5)) { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_global[pw + 1], 1); }
		// Match 4-strata edges with eligible vertices
		if (subdivide_int3bits_read(marker_edge, 6)) {
			if (subdivide_int3bits_read(marker_vert, 4) == 1) {
				subdivide_short2bits_write0(match_global[pw - 1], 2); subdivide_short2bits_write1(match_global[pw], 1);
				if (subdivide_int3bits_read(marker_vert, 5) == 1) writeCrit(crit_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_vert, 5) == 1) { subdivide_short2bits_write0(match_global[pw + 1], 1); subdivide_short2bits_write1(match_global[pw], 2); }
			else writeCrit(crit_global[pw], 2);
		}
	}

	// Chunk back top border handling
	if (py == 0 && pz == chunkSizeD - 1) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of immediate back-top neighbor with total ordering enforced
		value = tex3D<type>(chunk, px + 1, 1, chunkSizeD + 2);
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px + 1, 1, chunkSizeD + 1))  subdivide_int3bits_write(marker_face, 0, 1);																							// front face
		if (value < tex3D<type>(chunk, px, 1, chunkSizeD + 2))      subdivide_int3bits_write(marker_face, 1, 1);																							// left face
		if (value <= tex3D<type>(chunk, px + 2, 1, chunkSizeD + 2)) subdivide_int3bits_write(marker_face, 2, 1);																							// right face
		if (value <= tex3D<type>(chunk, px + 1, 2, chunkSizeD + 2)) subdivide_int3bits_write(marker_face, 5, 1);																							// bottom face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, 1, chunkSizeD + 1))      subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, 1, chunkSizeD + 1))  subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 5) && value < tex3D<type>(chunk, px + 1, 2, chunkSizeD + 1))  subdivide_int3bits_write(marker_edge, 1, 1);		// front-bottom edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, 2, chunkSizeD + 2))	  subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, 2, chunkSizeD + 2)) subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 4) && value < tex3D<type>(chunk, px, 2, chunkSizeD + 1))		  subdivide_int3bits_write(marker_vert, 2, 1); 	// front-bottom-left vertex
		if (subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 5) && value < tex3D<type>(chunk, px + 2, 2, chunkSizeD + 1))   subdivide_int3bits_write(marker_vert, 3, 1); 	// front-bottom-right vertex
	
		// Coordinate of back-top edge of the current thread in the global grid
		pw = STRIDE_Y * (chunkSizeH * 2 + 1) * (chunkSizeD * 2) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		if (subdivide_int3bits_read(marker_edge, 1)) { match_global[pw] = 0x541;		writeCubi(crit_global[pw], 10); }																					// back-top edge
		if (subdivide_int3bits_read(marker_vert, 2)) { match_global[pw - 1] = 0x555;	writeCubi(crit_global[pw - 1], 21); }																				// back-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 3)) { match_global[pw + 1] = 0x555;	writeCubi(crit_global[pw + 1], 22); }																				// back-top-right vertex
		// Decide 4-strata vertices
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_vert, 2)) { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_global[pw - 1], 1); }
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_vert, 3)) { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_global[pw + 1], 1); }
		// Match 4-strata edges with eligible vertices
		if (subdivide_int3bits_read(marker_edge, 1)) {
			if (subdivide_int3bits_read(marker_vert, 2) == 1) {
				subdivide_short2bits_write0(match_global[pw - 1], 2); subdivide_short2bits_write1(match_global[pw], 1);
				if (subdivide_int3bits_read(marker_vert, 3) == 1) writeCrit(crit_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_vert, 3) == 1) { subdivide_short2bits_write0(match_global[pw + 1], 1); subdivide_short2bits_write1(match_global[pw], 2); }
			else writeCrit(crit_global[pw], 2);
		}
	}

	// Chunk back bottom border handling
	if (py == chunkSizeH - 1 && pz == chunkSizeD - 1) {
		marker_vert = 0;
		marker_edge = 0;
		marker_face = 0;
		// Decide lower star of immediate back-bottom neighbor with total ordering enforced
		value = tex3D<type>(chunk, px + 1, chunkSizeH + 2, chunkSizeD + 2);
		// Decide the ownership of faces (2-cells)
		if (value < tex3D<type>(chunk, px + 1, chunkSizeH + 2, chunkSizeD + 1))  subdivide_int3bits_write(marker_face, 0, 1);	// front face
		if (value < tex3D<type>(chunk, px, chunkSizeH + 2, chunkSizeD + 2))      subdivide_int3bits_write(marker_face, 1, 1);	// left face
		if (value <= tex3D<type>(chunk, px + 2, chunkSizeH + 2, chunkSizeD + 2)) subdivide_int3bits_write(marker_face, 2, 1);	// right face
		if (value < tex3D<type>(chunk, px + 1, chunkSizeH + 1, chunkSizeD + 2))  subdivide_int3bits_write(marker_face, 4, 1);	// top face
		// Decide the ownership of edges (1-cells)
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 1, chunkSizeH + 1, chunkSizeD + 1))  subdivide_int3bits_write(marker_vert, 8, 1);		// front-top edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, chunkSizeH + 2, chunkSizeD + 1))      subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
		if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 2, chunkSizeD + 1))  subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
		if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, chunkSizeH + 1, chunkSizeD + 2))     subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
		if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 1, chunkSizeD + 2))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
		// Decide the ownership of vertices (0-cells)
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 2) && value < tex3D<type>(chunk, px, chunkSizeH + 1, chunkSizeD + 1))     subdivide_int3bits_write(marker_vert, 0, 1);	// front-top-left vertex
		if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 3) && value < tex3D<type>(chunk, px + 2, chunkSizeH + 1, chunkSizeD + 1)) subdivide_int3bits_write(marker_vert, 1, 1);	// front-top-right vertex

		// Coordinate of back-bottom edge of the current thread in the global grid
		pw = STRIDE_Y * (chunkSizeH * 2 + 1) * (chunkSizeD * 2) + STRIDE_Y * (chunkSizeH * 2) + (px * 2 + 1);
		// Initialize the global match grid and global offset mask (part of crit mask, refer to manual)
		if (subdivide_int3bits_read(marker_vert, 8)) { match_global[pw] = 0x541;		writeCubi(crit_global[pw], 7); }																								// back-bottom edge
		if (subdivide_int3bits_read(marker_vert, 0)) { match_global[pw - 1] = 0x555;	writeCubi(crit_global[pw - 1], 19); }																							// back-bottom-left vertex
		if (subdivide_int3bits_read(marker_vert, 1)) { match_global[pw + 1] = 0x555;	writeCubi(crit_global[pw + 1], 20); }																							// back-bottom-right vertex
		// Decide 4-strata vertices
		if (threadIdx.x == 0 && NOT_FIRST_BLK_X && subdivide_int3bits_read(marker_vert, 0)) { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_global[pw - 1], 1); }
		if (LAST_X && NOT_LAST_BLK_X && subdivide_int3bits_read(marker_vert, 1)) { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_global[pw + 1], 1); }
		// Match 4-strata edges with eligible vertices
		if (subdivide_int3bits_read(marker_vert, 8)) {
			if (subdivide_int3bits_read(marker_vert, 0) == 1) {
				subdivide_short2bits_write0(match_global[pw - 1], 2); subdivide_short2bits_write1(match_global[pw], 1);
				if (subdivide_int3bits_read(marker_vert, 1) == 1) writeCrit(crit_global[pw + 1], 1);
			}
			else if (subdivide_int3bits_read(marker_vert, 1) == 1) { subdivide_short2bits_write0(match_global[pw + 1], 1); subdivide_short2bits_write1(match_global[pw], 2); }
			else writeCrit(crit_global[pw], 2);
		}
	}
	// ================================================================

	marker_vert = 0;
	marker_edge = 0;
	marker_face = 0;
	// Decide lower star of current voxel L(x) with total ordering enforced
	value = tex3D<type>(chunk, px + 1, py + 2, pz + 2);															// load value of voxel
	// Decide the ownership of faces (2-cells)
	if (value < tex3D<type>(chunk, px + 1, py + 2, pz + 1))  subdivide_int3bits_write(marker_face, 0, 1);		// front face
	if (value < tex3D<type>(chunk, px, py + 2, pz + 2))		 subdivide_int3bits_write(marker_face, 1, 1);		// left face
	if (value <= tex3D<type>(chunk, px + 2, py + 2, pz + 2)) subdivide_int3bits_write(marker_face, 2, 1);		// right face
	if (value <= tex3D<type>(chunk, px + 1, py + 2, pz + 3)) subdivide_int3bits_write(marker_face, 3, 1);		// back face
	if (value < tex3D<type>(chunk, px + 1, py + 1, pz + 2))  subdivide_int3bits_write(marker_face, 4, 1);		// top face
	if (value <= tex3D<type>(chunk, px + 1, py + 3, pz + 2)) subdivide_int3bits_write(marker_face, 5, 1);		// bottom face
	// Decide the ownership of edges (1-cells)
	if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 1, py + 1, pz + 1))  subdivide_int3bits_write(marker_vert, 8, 1);		// front-top edge
	if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 1) && value < tex3D<type>(chunk, px, py + 2, pz + 1))	   subdivide_int3bits_write(marker_vert, 9, 1);		// front-left edge
	if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 2) && value < tex3D<type>(chunk, px + 2, py + 2, pz + 1))  subdivide_int3bits_write(marker_edge, 0, 1);		// front-right edge
	if (subdivide_int3bits_read(marker_face, 0) && subdivide_int3bits_read(marker_face, 5) && value < tex3D<type>(chunk, px + 1, py + 3, pz + 1))  subdivide_int3bits_write(marker_edge, 1, 1);		// front-bottom edge
	if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px, py + 1, pz + 2))	   subdivide_int3bits_write(marker_edge, 2, 1);		// top-left edge
	if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 4) && value < tex3D<type>(chunk, px + 2, py + 1, pz + 2))  subdivide_int3bits_write(marker_edge, 3, 1);		// top-right edge
	if (subdivide_int3bits_read(marker_face, 1) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px, py + 3, pz + 2))	   subdivide_int3bits_write(marker_edge, 4, 1);		// bottom-left edge
	if (subdivide_int3bits_read(marker_face, 2) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 2, py + 3, pz + 2)) subdivide_int3bits_write(marker_edge, 5, 1);		// bottom-right edge
	if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 4) && value <= tex3D<type>(chunk, px + 1, py + 1, pz + 3)) subdivide_int3bits_write(marker_edge, 6, 1);		// back-top edge
	if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 1) && value <= tex3D<type>(chunk, px, py + 2, pz + 3))	   subdivide_int3bits_write(marker_edge, 7, 1);		// back-left edge
	if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 2) && value <= tex3D<type>(chunk, px + 2, py + 2, pz + 3)) subdivide_int3bits_write(marker_edge, 8, 1);		// back-right edge
	if (subdivide_int3bits_read(marker_face, 3) && subdivide_int3bits_read(marker_face, 5) && value <= tex3D<type>(chunk, px + 1, py + 3, pz + 3)) subdivide_int3bits_write(marker_edge, 9, 1);		// back-bottom edge
	// Decide the ownership of vertices (0-cells)
	if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 2) && value < tex3D<type>(chunk, px, py + 1, pz + 1))	  subdivide_int3bits_write(marker_vert, 0, 1);	// front-top-left vertex
	if (subdivide_int3bits_read(marker_vert, 8) && subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 3) && value < tex3D<type>(chunk, px + 2, py + 1, pz + 1))  subdivide_int3bits_write(marker_vert, 1, 1);	// front-top-right vertex
	if (subdivide_int3bits_read(marker_vert, 9) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 4) && value < tex3D<type>(chunk, px, py + 3, pz + 1))	  subdivide_int3bits_write(marker_vert, 2, 1);	// front-bottom-left vertex
	if (subdivide_int3bits_read(marker_edge, 0) && subdivide_int3bits_read(marker_edge, 1) && subdivide_int3bits_read(marker_edge, 5) && value < tex3D<type>(chunk, px + 2, py + 3, pz + 1))  subdivide_int3bits_write(marker_vert, 3, 1);	// front-bottom-right vertex
	if (subdivide_int3bits_read(marker_edge, 2) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 7) && value <= tex3D<type>(chunk, px, py + 1, pz + 3))	  subdivide_int3bits_write(marker_vert, 4, 1);	// back-top-left vertex
	if (subdivide_int3bits_read(marker_edge, 3) && subdivide_int3bits_read(marker_edge, 6) && subdivide_int3bits_read(marker_edge, 8) && value <= tex3D<type>(chunk, px + 2, py + 1, pz + 3)) subdivide_int3bits_write(marker_vert, 5, 1);	// back-top-right vertex
	if (subdivide_int3bits_read(marker_edge, 4) && subdivide_int3bits_read(marker_edge, 7) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px, py + 3, pz + 3))	  subdivide_int3bits_write(marker_vert, 6, 1);	// back-bottom-left vertex
	if (subdivide_int3bits_read(marker_edge, 5) && subdivide_int3bits_read(marker_edge, 8) && subdivide_int3bits_read(marker_edge, 9) && value <= tex3D<type>(chunk, px + 2, py + 3, pz + 3)) subdivide_int3bits_write(marker_vert, 7, 1);	// back-bottom-right vertex

	// Repurpose varialbes pz for storing the coordinate of the current thread in the grid
	uint_& coord = pz;
	coord = (blockDim.x * 2 + 1) * (blockDim.y * 2 + 1) * (threadIdx.z * 2 + 1) + (blockDim.x * 2 + 1) * (threadIdx.y * 2 + 1) + (threadIdx.x * 2 + 1);

	// Initialize the match grid and critical mask
	// 3-cell
	match_shared[coord] = 0;
	// 2-cells
	if (subdivide_int3bits_read(marker_face, 0)) { match_shared[cube_offset(blkDimSetting, coord, 1)] = 0x41;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 1)], 1); }		// front-face
	if (subdivide_int3bits_read(marker_face, 1)) { match_shared[cube_offset(blkDimSetting, coord, 2)] = 0x14;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 2)], 2); }		// left-face
	if (subdivide_int3bits_read(marker_face, 2)) { match_shared[cube_offset(blkDimSetting, coord, 3)] = 0x14;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 3)], 3); }		// right-face
	if (subdivide_int3bits_read(marker_face, 3)) { match_shared[cube_offset(blkDimSetting, coord, 4)] = 0x41;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 4)], 4); }		// back-face
	if (subdivide_int3bits_read(marker_face, 4)) { match_shared[cube_offset(blkDimSetting, coord, 5)] = 0x500;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 5)], 5); }		// top-face
	if (subdivide_int3bits_read(marker_face, 5)) { match_shared[cube_offset(blkDimSetting, coord, 6)] = 0x500;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 6)], 6); }		// bottom-face
	// 1-cells
	if (subdivide_int3bits_read(marker_vert, 8)) { match_shared[cube_offset(blkDimSetting, coord, 7)] = 0x541;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 7)], 7); }		// front-top edge
	if (subdivide_int3bits_read(marker_vert, 9)) { match_shared[cube_offset(blkDimSetting, coord, 8)] = 0x55;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 8)], 8); }		// front-left edge
	if (subdivide_int3bits_read(marker_edge, 0)) { match_shared[cube_offset(blkDimSetting, coord, 9)] = 0x55;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 9)], 9); }		// front-right edge
	if (subdivide_int3bits_read(marker_edge, 1)) { match_shared[cube_offset(blkDimSetting, coord, 10)] = 0x541;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 10)], 10); }	// front-bottom edge
	if (subdivide_int3bits_read(marker_edge, 2)) { match_shared[cube_offset(blkDimSetting, coord, 11)] = 0x514;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 11)], 11); }	// top-left edge
	if (subdivide_int3bits_read(marker_edge, 3)) { match_shared[cube_offset(blkDimSetting, coord, 12)] = 0x514;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 12)], 12); }	// top-right edge
	if (subdivide_int3bits_read(marker_edge, 4)) { match_shared[cube_offset(blkDimSetting, coord, 13)] = 0x514;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 13)], 13); }	// bottom-left edge
	if (subdivide_int3bits_read(marker_edge, 5)) { match_shared[cube_offset(blkDimSetting, coord, 14)] = 0x514;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 14)], 14); }	// bottom-right edge
	if (subdivide_int3bits_read(marker_edge, 6)) { match_shared[cube_offset(blkDimSetting, coord, 15)] = 0x541;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 15)], 15); }	// back-top edge
	if (subdivide_int3bits_read(marker_edge, 7)) { match_shared[cube_offset(blkDimSetting, coord, 16)] = 0x55;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 16)], 16); }	// back-left edge
	if (subdivide_int3bits_read(marker_edge, 8)) { match_shared[cube_offset(blkDimSetting, coord, 17)] = 0x55;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 17)], 17); }	// back-right edge
	if (subdivide_int3bits_read(marker_edge, 9)) { match_shared[cube_offset(blkDimSetting, coord, 18)] = 0x541;	writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 18)], 18); }	// back-bottom edge
	// 0-cells
	if (subdivide_int3bits_read(marker_vert, 0)) { match_shared[cube_offset(blkDimSetting, coord, 19)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 19)], 19); }	// front-top-left vertex
	if (subdivide_int3bits_read(marker_vert, 1)) { match_shared[cube_offset(blkDimSetting, coord, 20)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 20)], 20); }	// front-top-right vertex
	if (subdivide_int3bits_read(marker_vert, 2)) { match_shared[cube_offset(blkDimSetting, coord, 21)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 21)], 21); }	// front-bottom-left vertex
	if (subdivide_int3bits_read(marker_vert, 3)) { match_shared[cube_offset(blkDimSetting, coord, 22)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 22)], 22); }	// front-bottom-right vertex
	if (subdivide_int3bits_read(marker_vert, 4)) { match_shared[cube_offset(blkDimSetting, coord, 23)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 23)], 23); }	// back-top-left vertex
	if (subdivide_int3bits_read(marker_vert, 5)) { match_shared[cube_offset(blkDimSetting, coord, 24)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 24)], 24); }	// back-top-right vertex
	if (subdivide_int3bits_read(marker_vert, 6)) { match_shared[cube_offset(blkDimSetting, coord, 25)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 25)], 25); }	// back-bottom-left vertex
	if (subdivide_int3bits_read(marker_vert, 7)) { match_shared[cube_offset(blkDimSetting, coord, 26)] = 0x555; writeCubi(crit_shared[cube_offset(blkDimSetting, coord, 26)], 26); }	// back-bottom-right vertex

	// Stop boundary cells from crossing boundary
	uint_& subcells_num = pw;
	subcells_num = 0; // 000 000 000 000 000 000 (to_be_processed_faces, f5, f4, f3, f2, f1, f0)
	// ========== Boundary process for 2-cells ==========
	if (threadIdx.z == 0 && subdivide_int3bits_read(marker_face, 0)) {											// Decide front-face and its faces
		subdivide_int3bits_write(subcells_num, 0, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 0)) subdivide_int3bits_write(marker_vert, 0, 4);
		if (subdivide_int3bits_read(marker_vert, 1)) subdivide_int3bits_write(marker_vert, 1, 4);
		if (subdivide_int3bits_read(marker_vert, 2)) subdivide_int3bits_write(marker_vert, 2, 4);
		if (subdivide_int3bits_read(marker_vert, 3)) subdivide_int3bits_write(marker_vert, 3, 4);
	}
	pos = blockDim.z * blockIdx.z + threadIdx.z + 1;
	if ((LAST_Z || pos == chunkSizeD) && subdivide_int3bits_read(marker_face, 3)) {								// Decide back-face and its faces
		subdivide_int3bits_write(subcells_num, 3, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 4)) subdivide_int3bits_write(marker_vert, 4, 4);
		if (subdivide_int3bits_read(marker_vert, 5)) subdivide_int3bits_write(marker_vert, 5, 4);
		if (subdivide_int3bits_read(marker_vert, 6)) subdivide_int3bits_write(marker_vert, 6, 4);
		if (subdivide_int3bits_read(marker_vert, 7)) subdivide_int3bits_write(marker_vert, 7, 4);
	}
	if (threadIdx.y == 0 && subdivide_int3bits_read(marker_face, 4)) {											// Decide top-face and its faces
		subdivide_int3bits_write(subcells_num, 4, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 0)) subdivide_int3bits_write(marker_vert, 0, 4);
		if (subdivide_int3bits_read(marker_vert, 1)) subdivide_int3bits_write(marker_vert, 1, 4);
		if (subdivide_int3bits_read(marker_vert, 4)) subdivide_int3bits_write(marker_vert, 4, 4);
		if (subdivide_int3bits_read(marker_vert, 5)) subdivide_int3bits_write(marker_vert, 5, 4);
	}
	pos = blockDim.y * blockIdx.y + threadIdx.y + 1;
	if ((LAST_Y || pos == chunkSizeH) && subdivide_int3bits_read(marker_face, 5)) {								// Decide bottom-face and its faces
		subdivide_int3bits_write(subcells_num, 5, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 2)) subdivide_int3bits_write(marker_vert, 2, 4);
		if (subdivide_int3bits_read(marker_vert, 3)) subdivide_int3bits_write(marker_vert, 3, 4);
		if (subdivide_int3bits_read(marker_vert, 6)) subdivide_int3bits_write(marker_vert, 6, 4);
		if (subdivide_int3bits_read(marker_vert, 7)) subdivide_int3bits_write(marker_vert, 7, 4);
	}
	if (threadIdx.x == 0 && subdivide_int3bits_read(marker_face, 1) && NOT_FIRST_BLK_X) {						// Decide left-face and its faces
		subdivide_int3bits_write(subcells_num, 1, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 0)) subdivide_int3bits_write(marker_vert, 0, 4);
		if (subdivide_int3bits_read(marker_vert, 2)) subdivide_int3bits_write(marker_vert, 2, 4);
		if (subdivide_int3bits_read(marker_vert, 4)) subdivide_int3bits_write(marker_vert, 4, 4);
		if (subdivide_int3bits_read(marker_vert, 6)) subdivide_int3bits_write(marker_vert, 6, 4);
	}
	if (LAST_X && subdivide_int3bits_read(marker_face, 2) && NOT_LAST_BLK_X) { 									// Decide right-face and its faces
		subdivide_int3bits_write(subcells_num, 2, 1);
		// Mark boundary vertices
		if (subdivide_int3bits_read(marker_vert, 1)) subdivide_int3bits_write(marker_vert, 1, 4);
		if (subdivide_int3bits_read(marker_vert, 3)) subdivide_int3bits_write(marker_vert, 3, 4);
		if (subdivide_int3bits_read(marker_vert, 5)) subdivide_int3bits_write(marker_vert, 5, 4);
		if (subdivide_int3bits_read(marker_vert, 7)) subdivide_int3bits_write(marker_vert, 7, 4);
	}
	// Mark boundary edges and 4-strata edges, which cannot match to any 2-cell. (refer to design manual)
	if (subdivide_int3bits_read(marker_vert, 8))																												// Decide front-top edge
		if (subdivide_int3bits_read(subcells_num, 0) && subdivide_int3bits_read(subcells_num, 4)) { subdivide_int3bits_write(marker_vert, 8, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 7)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 0) || subdivide_int3bits_read(subcells_num, 4)) subdivide_int3bits_write(marker_vert, 8, 4);
	if (subdivide_int3bits_read(marker_vert, 9))																												// Decide front-left edge
		if (subdivide_int3bits_read(subcells_num, 0) && subdivide_int3bits_read(subcells_num, 1)) { subdivide_int3bits_write(marker_vert, 9, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 8)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 0) || subdivide_int3bits_read(subcells_num, 1)) subdivide_int3bits_write(marker_vert, 9, 4);
	if (subdivide_int3bits_read(marker_edge, 0))																												// Decide front-right edge
		if (subdivide_int3bits_read(subcells_num, 0) && subdivide_int3bits_read(subcells_num, 2)) { subdivide_int3bits_write(marker_edge, 0, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 9)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 0) || subdivide_int3bits_read(subcells_num, 2)) subdivide_int3bits_write(marker_edge, 0, 4);
	if (subdivide_int3bits_read(marker_edge, 1))																												// Decide front-bottom edge
		if (subdivide_int3bits_read(subcells_num, 0) && subdivide_int3bits_read(subcells_num, 5)) { subdivide_int3bits_write(marker_edge, 1, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 10)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 0) || subdivide_int3bits_read(subcells_num, 5)) subdivide_int3bits_write(marker_edge, 1, 4);
	if (subdivide_int3bits_read(marker_edge, 2))																												// Decide top-left edge
		if (subdivide_int3bits_read(subcells_num, 1) && subdivide_int3bits_read(subcells_num, 4)) { subdivide_int3bits_write(marker_edge, 2, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 11)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 1) || subdivide_int3bits_read(subcells_num, 4)) subdivide_int3bits_write(marker_edge, 2, 4);
	if (subdivide_int3bits_read(marker_edge, 3))																												// Decide top-right edge
		if (subdivide_int3bits_read(subcells_num, 2) && subdivide_int3bits_read(subcells_num, 4)) { subdivide_int3bits_write(marker_edge, 3, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 12)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 2) || subdivide_int3bits_read(subcells_num, 4)) subdivide_int3bits_write(marker_edge, 3, 4);
	if (subdivide_int3bits_read(marker_edge, 4)) 																												// Decide bottom-left edge
		if (subdivide_int3bits_read(subcells_num, 1) && subdivide_int3bits_read(subcells_num, 5)) { subdivide_int3bits_write(marker_edge, 4, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 13)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 1) || subdivide_int3bits_read(subcells_num, 5)) subdivide_int3bits_write(marker_edge, 4, 4);
	if (subdivide_int3bits_read(marker_edge, 5)) 																												// Decide bottom-right edge
		if (subdivide_int3bits_read(subcells_num, 2) && subdivide_int3bits_read(subcells_num, 5)) { subdivide_int3bits_write(marker_edge, 5, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 14)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 2) || subdivide_int3bits_read(subcells_num, 5)) subdivide_int3bits_write(marker_edge, 5, 4);
	if (subdivide_int3bits_read(marker_edge, 6)) 																												// Decide back-top edge
		if (subdivide_int3bits_read(subcells_num, 3) && subdivide_int3bits_read(subcells_num, 4)) { subdivide_int3bits_write(marker_edge, 6, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 15)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 3) || subdivide_int3bits_read(subcells_num, 4)) subdivide_int3bits_write(marker_edge, 6, 4);
	if (subdivide_int3bits_read(marker_edge, 7)) 																												// Decide back-left edge
		if (subdivide_int3bits_read(subcells_num, 1) && subdivide_int3bits_read(subcells_num, 3)) { subdivide_int3bits_write(marker_edge, 7, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 16)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 1) || subdivide_int3bits_read(subcells_num, 3)) subdivide_int3bits_write(marker_edge, 7, 4);
	if (subdivide_int3bits_read(marker_edge, 8)) 																												// Decide back-right edge
		if (subdivide_int3bits_read(subcells_num, 2) && subdivide_int3bits_read(subcells_num, 3)) { subdivide_int3bits_write(marker_edge, 8, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 17)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 2) || subdivide_int3bits_read(subcells_num, 3)) subdivide_int3bits_write(marker_edge, 8, 4);
	if (subdivide_int3bits_read(marker_edge, 9)) 																												// Decide back-bottom edge
		if (subdivide_int3bits_read(subcells_num, 3) && subdivide_int3bits_read(subcells_num, 5)) { subdivide_int3bits_write(marker_edge, 9, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 18)], 2); }
		else if (subdivide_int3bits_read(subcells_num, 3) || subdivide_int3bits_read(subcells_num, 5)) subdivide_int3bits_write(marker_edge, 9, 4);
	// boundary morse matching between faces and edges
	if (subdivide_int3bits_read(subcells_num, 0)) {
		if (subdivide_int3bits_read(marker_vert, 8) == 4) {
			subdivide_int3bits_write(marker_vert, 8, 3);
			subdivide_int3bits_write(marker_face, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 7)], 5);
		}
		else if (subdivide_int3bits_read(marker_vert, 9) == 4) {
			subdivide_int3bits_write(marker_vert, 9, 3);
			subdivide_int3bits_write(marker_face, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 8)], 2);
		}
		else if (subdivide_int3bits_read(marker_edge, 0) == 4) {
			subdivide_int3bits_write(marker_edge, 0, 3);
			subdivide_int3bits_write(marker_face, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 9)], 1);
		}
		else if (subdivide_int3bits_read(marker_edge, 1) == 4) {
			subdivide_int3bits_write(marker_edge, 1, 3);
			subdivide_int3bits_write(marker_face, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 10)], 4);
		}
		else { subdivide_int3bits_write(marker_face, 0, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 1)], 3); }
	}
	if (subdivide_int3bits_read(subcells_num, 1)) {
		if (subdivide_int3bits_read(marker_vert, 9) == 4) {
			subdivide_int3bits_write(marker_vert, 9, 3);
			subdivide_int3bits_write(marker_face, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 8)], 3);
		}
		else if (subdivide_int3bits_read(marker_edge, 2) == 4) {
			subdivide_int3bits_write(marker_edge, 2, 3);
			subdivide_int3bits_write(marker_face, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 11)], 5);
		}
		else if (subdivide_int3bits_read(marker_edge, 4) == 4) {
			subdivide_int3bits_write(marker_edge, 4, 3);
			subdivide_int3bits_write(marker_face, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 13)], 4);
		}
		else if (subdivide_int3bits_read(marker_edge, 7) == 4) {
			subdivide_int3bits_write(marker_edge, 7, 3);
			subdivide_int3bits_write(marker_face, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 16)], 0);
		}
		else { subdivide_int3bits_write(marker_face, 1, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 2)], 3); }
	}
	if (subdivide_int3bits_read(subcells_num, 2)) {
		if (subdivide_int3bits_read(marker_edge, 0) == 4) {
			subdivide_int3bits_write(marker_edge, 0, 3);
			subdivide_int3bits_write(marker_face, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 9)], 3);
		}
		else if (subdivide_int3bits_read(marker_edge, 3) == 4) {
			subdivide_int3bits_write(marker_edge, 3, 3);
			subdivide_int3bits_write(marker_face, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 12)], 5);
		}
		else if (subdivide_int3bits_read(marker_edge, 5) == 4) {
			subdivide_int3bits_write(marker_edge, 5, 3);
			subdivide_int3bits_write(marker_face, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 14)], 4);
		}
		else if (subdivide_int3bits_read(marker_edge, 8) == 4) {
			subdivide_int3bits_write(marker_edge, 8, 3);
			subdivide_int3bits_write(marker_face, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 17)], 0);
		}
		else { subdivide_int3bits_write(marker_face, 2, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 3)], 3); }
	}
	if (subdivide_int3bits_read(subcells_num, 3)) {
		if (subdivide_int3bits_read(marker_edge, 6) == 4) {
			subdivide_int3bits_write(marker_edge, 6, 3);
			subdivide_int3bits_write(marker_face, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 15)], 5);
		}
		else if (subdivide_int3bits_read(marker_edge, 7) == 4) {
			subdivide_int3bits_write(marker_edge, 7, 3);
			subdivide_int3bits_write(marker_face, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 16)], 2);
		}
		else if (subdivide_int3bits_read(marker_edge, 8) == 4) {
			subdivide_int3bits_write(marker_edge, 8, 3);
			subdivide_int3bits_write(marker_face, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 17)], 1);
		}
		else if (subdivide_int3bits_read(marker_edge, 9) == 4) {
			subdivide_int3bits_write(marker_edge, 9, 3);
			subdivide_int3bits_write(marker_face, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 18)], 4);
		}
		else { subdivide_int3bits_write(marker_face, 3, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 4)], 3); }
	}
	if (subdivide_int3bits_read(subcells_num, 4)) {
		if (subdivide_int3bits_read(marker_vert, 8) == 4) {
			subdivide_int3bits_write(marker_vert, 8, 3);
			subdivide_int3bits_write(marker_face, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 7)], 3);
		}
		else if (subdivide_int3bits_read(marker_edge, 2) == 4) {
			subdivide_int3bits_write(marker_edge, 2, 3);
			subdivide_int3bits_write(marker_face, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 11)], 2);
		}
		else if (subdivide_int3bits_read(marker_edge, 3) == 4) {
			subdivide_int3bits_write(marker_edge, 3, 3);
			subdivide_int3bits_write(marker_face, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 12)], 1);
		}
		else if (subdivide_int3bits_read(marker_edge, 6) == 4) {
			subdivide_int3bits_write(marker_edge, 6, 3);
			subdivide_int3bits_write(marker_face, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 15)], 0);
		}
		else { subdivide_int3bits_write(marker_face, 4, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 5)], 3); }
	}
	if (subdivide_int3bits_read(subcells_num, 5)) {
		if (subdivide_int3bits_read(marker_edge, 1) == 4) {
			subdivide_int3bits_write(marker_edge, 1, 3);
			subdivide_int3bits_write(marker_face, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 10)], 3);
		}
		else if (subdivide_int3bits_read(marker_edge, 4) == 4) {
			subdivide_int3bits_write(marker_edge, 4, 3);
			subdivide_int3bits_write(marker_face, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 13)], 2);
		}
		else if (subdivide_int3bits_read(marker_edge, 5) == 4) {
			subdivide_int3bits_write(marker_edge, 5, 3);
			subdivide_int3bits_write(marker_face, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 14)], 1);
		}
		else if (subdivide_int3bits_read(marker_edge, 9) == 4) {
			subdivide_int3bits_write(marker_edge, 9, 3);
			subdivide_int3bits_write(marker_face, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 18)], 0);
		}
		else { subdivide_int3bits_write(marker_face, 5, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 6)], 3); }
	}

	// ========== Match 4-strata edges to 1-cells ==========
	/*
		pos accumulates the number of 1-cells that are 4-strata edges for the current vertex
		In case of 1: the vertex belongs to v2 (refer to manual), it matches to the only 1-cell that is 4-strata
		In case of 3: the vertex belongs to v1 (refer to manual), it can't be matched to any 1-cell
		In case of 0: the vertex belongs to v3 (refer to manual), it matches to one of the 2 1-cells in the border, or becomes a critical cell if no such 1-cell exists
	*/
	px = 0;
	for (subcells_num = 0; subcells_num < 8; subcells_num++) {
		if (subdivide_int3bits_read(marker_vert, subcells_num) == 4) {
			switch (subcells_num) {
			case 0: pos = (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_vert, 9) == 2) + (subdivide_int3bits_read(marker_edge, 2) == 2); break;
			case 1: pos = (subdivide_int3bits_read(marker_vert, 8) == 2) + (subdivide_int3bits_read(marker_edge, 0) == 2) + (subdivide_int3bits_read(marker_edge, 3) == 2); break;
			case 2: pos = (subdivide_int3bits_read(marker_vert, 9) == 2) + (subdivide_int3bits_read(marker_edge, 1) == 2) + (subdivide_int3bits_read(marker_edge, 4) == 2); break;
			case 3: pos = (subdivide_int3bits_read(marker_edge, 0) == 2) + (subdivide_int3bits_read(marker_edge, 1) == 2) + (subdivide_int3bits_read(marker_edge, 5) == 2); break;
			case 4: pos = (subdivide_int3bits_read(marker_edge, 2) == 2) + (subdivide_int3bits_read(marker_edge, 6) == 2) + (subdivide_int3bits_read(marker_edge, 7) == 2); break;
			case 5: pos = (subdivide_int3bits_read(marker_edge, 3) == 2) + (subdivide_int3bits_read(marker_edge, 6) == 2) + (subdivide_int3bits_read(marker_edge, 8) == 2); break;
			case 6: pos = (subdivide_int3bits_read(marker_edge, 4) == 2) + (subdivide_int3bits_read(marker_edge, 7) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2); break;
			case 7: pos = (subdivide_int3bits_read(marker_edge, 5) == 2) + (subdivide_int3bits_read(marker_edge, 8) == 2) + (subdivide_int3bits_read(marker_edge, 9) == 2);
			}
			if (pos == 1) subdivide_int3bits_write(px, subcells_num, 1);
			else if (pos == 3) { subdivide_int3bits_write(marker_vert, subcells_num, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, subcells_num + 19)], 1); }
		}
	}

	for (subcells_num = 0; subcells_num < 8; subcells_num++) {
		if (subdivide_int3bits_read(px, subcells_num)) {
			switch (subcells_num) {
			case 0:
				if (subdivide_int3bits_read(marker_vert, 8) == 2) {
					subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_shared[cube_offset(blkDimSetting, coord, 7)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 2); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 7)], 1);
				}
				else if (subdivide_int3bits_read(marker_vert, 9) == 2) {
					subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_shared[cube_offset(blkDimSetting, coord, 8)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 5); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 4);
				}
				else if (subdivide_int3bits_read(marker_edge, 2) == 2) {
					subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 0, 3); crit_shared[cube_offset(blkDimSetting, coord, 11)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 3); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 0);
				}
				else { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 19)], 1); }
				break;
			case 1:
				if (subdivide_int3bits_read(marker_vert, 8) == 2) {
					subdivide_int3bits_write(marker_vert, 8, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_shared[cube_offset(blkDimSetting, coord, 7)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 1); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 7)], 2);
				}
				else if (subdivide_int3bits_read(marker_edge, 0) == 2) {
					subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_shared[cube_offset(blkDimSetting, coord, 9)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 5); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 4);
				}
				else if (subdivide_int3bits_read(marker_edge, 3) == 2) {
					subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 1, 3); crit_shared[cube_offset(blkDimSetting, coord, 12)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 3); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 0);
				}
				else { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 20)], 1); }
				break;
			case 2:
				if (subdivide_int3bits_read(marker_vert, 9) == 2) {
					subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_shared[cube_offset(blkDimSetting, coord, 8)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 4); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 5);
				}
				else if (subdivide_int3bits_read(marker_edge, 1) == 2) {
					subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_shared[cube_offset(blkDimSetting, coord, 10)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 2); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 1);
				}
				else if (subdivide_int3bits_read(marker_edge, 4) == 2) {
					subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 2, 3); crit_shared[cube_offset(blkDimSetting, coord, 13)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 3); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 0);
				}
				else { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 21)], 1); }
				break;
			case 3:
				if (subdivide_int3bits_read(marker_edge, 0) == 2) {
					subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_shared[cube_offset(blkDimSetting, coord, 9)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 4); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 5);
				}
				else if (subdivide_int3bits_read(marker_edge, 1) == 2) {
					subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_shared[cube_offset(blkDimSetting, coord, 10)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 1); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 2);
				}
				else if (subdivide_int3bits_read(marker_edge, 5) == 2) {
					subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 3, 3); crit_shared[cube_offset(blkDimSetting, coord, 14)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 3); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 0);
				}
				else { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 22)], 1); }
				break;
			case 4:
				if (subdivide_int3bits_read(marker_edge, 2) == 2) {
					subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_shared[cube_offset(blkDimSetting, coord, 11)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 0); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 3);
				}
				else if (subdivide_int3bits_read(marker_edge, 6) == 2) {
					subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_shared[cube_offset(blkDimSetting, coord, 15)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 2); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 1);
				}
				else if (subdivide_int3bits_read(marker_edge, 7) == 2) {
					subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 4, 3); crit_shared[cube_offset(blkDimSetting, coord, 16)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 5); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 4);
				}
				else { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 23)], 1); }
				break;
			case 5:
				if (subdivide_int3bits_read(marker_edge, 3) == 2) {
					subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_shared[cube_offset(blkDimSetting, coord, 12)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 0); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 3);
				}
				else if (subdivide_int3bits_read(marker_edge, 6) == 2) {
					subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_shared[cube_offset(blkDimSetting, coord, 15)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 1); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 2);
				}
				else if (subdivide_int3bits_read(marker_edge, 8) == 2) {
					subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 5, 3); crit_shared[cube_offset(blkDimSetting, coord, 17)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 5); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 4);
				}
				else { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 24)], 1); }
				break;
			case 6:
				if (subdivide_int3bits_read(marker_edge, 4) == 2) {
					subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_shared[cube_offset(blkDimSetting, coord, 13)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 0); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 3);
				}
				else if (subdivide_int3bits_read(marker_edge, 7) == 2) {
					subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_shared[cube_offset(blkDimSetting, coord, 16)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 4); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 5);
				}
				else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
					subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 6, 3); crit_shared[cube_offset(blkDimSetting, coord, 18)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 2); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 1);
				}
				else { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 25)], 1); }
				break;
			case 7:
				if (subdivide_int3bits_read(marker_edge, 5) == 2) {
					subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_shared[cube_offset(blkDimSetting, coord, 14)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 0); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 3);
				}
				else if (subdivide_int3bits_read(marker_edge, 8) == 2) {
					subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_shared[cube_offset(blkDimSetting, coord, 17)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 4); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 5);
				}
				else if (subdivide_int3bits_read(marker_edge, 9) == 2) {
					subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 7, 3); crit_shared[cube_offset(blkDimSetting, coord, 18)] &= 248;
					subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 1); subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 2);
				}
				else { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 26)], 1); }
			}
		}
	}
	// ========== Boundary process for 1-cells ==========
	if (subdivide_int3bits_read(marker_vert, 9) == 4) {
		if (subdivide_int3bits_read(marker_vert, 0) == 4) {
			subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 5);
		}
		else if (subdivide_int3bits_read(marker_vert, 2) == 4) {
			subdivide_int3bits_write(marker_vert, 9, 3); subdivide_int3bits_write(marker_vert, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 4);
		}
		else {
			subdivide_int3bits_write(marker_vert, 9, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 8)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 0) == 4) {
		if (subdivide_int3bits_read(marker_vert, 1) == 4) {
			subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 5);
		}
		else if (subdivide_int3bits_read(marker_vert, 3) == 4) {
			subdivide_int3bits_write(marker_edge, 0, 3); subdivide_int3bits_write(marker_vert, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 4);
		}
		else {
			subdivide_int3bits_write(marker_edge, 0, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 9)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 1) == 4) {
		if (subdivide_int3bits_read(marker_vert, 2) == 4) {
			subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 2);
		}
		else if (subdivide_int3bits_read(marker_vert, 3) == 4) {
			subdivide_int3bits_write(marker_edge, 1, 3); subdivide_int3bits_write(marker_vert, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 1);
		}
		else {
			subdivide_int3bits_write(marker_edge, 1, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 10)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 2) == 4) {
		if (subdivide_int3bits_read(marker_vert, 0) == 4) {
			subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 0, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 3);
		}
		else if (subdivide_int3bits_read(marker_vert, 4) == 4) {
			subdivide_int3bits_write(marker_edge, 2, 3); subdivide_int3bits_write(marker_vert, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 0);
		}
		else {
			subdivide_int3bits_write(marker_edge, 2, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 11)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 3) == 4) {
		if (subdivide_int3bits_read(marker_vert, 1) == 4) {
			subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 1, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 3);
		}
		else if (subdivide_int3bits_read(marker_vert, 5) == 4) {
			subdivide_int3bits_write(marker_edge, 3, 3); subdivide_int3bits_write(marker_vert, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 0);
		}
		else {
			subdivide_int3bits_write(marker_edge, 3, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 12)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 4) == 4) {
		if (subdivide_int3bits_read(marker_vert, 2) == 4) {
			subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 2, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 3);
		}
		else if (subdivide_int3bits_read(marker_vert, 6) == 4) {
			subdivide_int3bits_write(marker_edge, 4, 3); subdivide_int3bits_write(marker_vert, 6, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 0);
		}
		else {
			subdivide_int3bits_write(marker_edge, 4, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 13)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 5) == 4) {
		if (subdivide_int3bits_read(marker_vert, 3) == 4) {
			subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 3, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 3);
		}
		else if (subdivide_int3bits_read(marker_vert, 7) == 4) {
			subdivide_int3bits_write(marker_edge, 5, 3); subdivide_int3bits_write(marker_vert, 7, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 0);
		}
		else {
			subdivide_int3bits_write(marker_edge, 5, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 14)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 6) == 4) {
		if (subdivide_int3bits_read(marker_vert, 4) == 4) {
			subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 2);
		}
		else if (subdivide_int3bits_read(marker_vert, 5) == 4) {
			subdivide_int3bits_write(marker_edge, 6, 3); subdivide_int3bits_write(marker_vert, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 1);
		}
		else {
			subdivide_int3bits_write(marker_edge, 6, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 15)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 7) == 4) {
		if (subdivide_int3bits_read(marker_vert, 4) == 4) {
			subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 4, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 5);
		}
		else if (subdivide_int3bits_read(marker_vert, 6) == 4) {
			subdivide_int3bits_write(marker_edge, 7, 3); subdivide_int3bits_write(marker_vert, 6, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 4);
		}
		else {
			subdivide_int3bits_write(marker_edge, 7, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 16)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 8) == 4) {
		if (subdivide_int3bits_read(marker_vert, 5) == 4) {
			subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 5, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 5);
		}
		else if (subdivide_int3bits_read(marker_vert, 7) == 4) {
			subdivide_int3bits_write(marker_edge, 8, 3); subdivide_int3bits_write(marker_vert, 7, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 4);
		}
		else {
			subdivide_int3bits_write(marker_edge, 8, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 17)], 2);
		}
	}
	if (subdivide_int3bits_read(marker_edge, 9) == 4) {
		if (subdivide_int3bits_read(marker_vert, 6) == 4) {
			subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 6, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 2);
		}
		else if (subdivide_int3bits_read(marker_vert, 7) == 4) {
			subdivide_int3bits_write(marker_edge, 9, 3); subdivide_int3bits_write(marker_vert, 7, 3);
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 1);
		}
		else {
			subdivide_int3bits_write(marker_edge, 9, 2);
			writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 18)], 2);
		}
	}

	// Mark all verticels in L(x) at border but not matched as critical
	if (subdivide_int3bits_read(marker_vert, 0) == 4) { subdivide_int3bits_write(marker_vert, 0, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 19)], 1); }
	if (subdivide_int3bits_read(marker_vert, 1) == 4) { subdivide_int3bits_write(marker_vert, 1, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 20)], 1); }
	if (subdivide_int3bits_read(marker_vert, 2) == 4) { subdivide_int3bits_write(marker_vert, 2, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 21)], 1); }
	if (subdivide_int3bits_read(marker_vert, 3) == 4) { subdivide_int3bits_write(marker_vert, 3, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 22)], 1); }
	if (subdivide_int3bits_read(marker_vert, 4) == 4) { subdivide_int3bits_write(marker_vert, 4, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 23)], 1); }
	if (subdivide_int3bits_read(marker_vert, 5) == 4) { subdivide_int3bits_write(marker_vert, 5, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 24)], 1); }
	if (subdivide_int3bits_read(marker_vert, 6) == 4) { subdivide_int3bits_write(marker_vert, 6, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 25)], 1); }
	if (subdivide_int3bits_read(marker_vert, 7) == 4) { subdivide_int3bits_write(marker_vert, 7, 2); writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 26)], 1); }
	// End of border manipulation

	// ========== Start of Vanessa's algorithm ==========
	uint_& pq0_num = px; pq0_num = 0;
	uint_& pq1_num = py; pq1_num = 0;
	for (pos = 0; pos < 6; pos++) if (subdivide_int3bits_read(marker_face, pos) == 1) break;
	// voxel (3-cell) is matched to one of its 2-cells
	if (pos < 6) {
		switch (pos) {
		case 0:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 0);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 1)], 3);
			if (subdivide_int3bits_read(marker_vert, 8) == 1 && subdivide_int3bits_read(marker_face, 4) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_vert, 9) == 1 && subdivide_int3bits_read(marker_face, 1) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 0) == 1 && subdivide_int3bits_read(marker_face, 2) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 1) == 1 && subdivide_int3bits_read(marker_face, 5) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
			break;
		case 1:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 1);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 2)], 2);
			if (subdivide_int3bits_read(marker_vert, 9) == 1 && subdivide_int3bits_read(marker_face, 0) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 2) == 1 && subdivide_int3bits_read(marker_face, 4) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 4) == 1 && subdivide_int3bits_read(marker_face, 5) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 7) == 1 && subdivide_int3bits_read(marker_face, 3) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
			break;
		case 2:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 2);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 3)], 1);
			if (subdivide_int3bits_read(marker_edge, 0) == 1 && subdivide_int3bits_read(marker_face, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 3) == 1 && subdivide_int3bits_read(marker_face, 4) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 5) == 1 && subdivide_int3bits_read(marker_face, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 8) == 1 && subdivide_int3bits_read(marker_face, 3) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
			break;
		case 3:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 3);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 4)], 0);
			if (subdivide_int3bits_read(marker_edge, 6) == 1 && subdivide_int3bits_read(marker_face, 4) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 7) == 1 && subdivide_int3bits_read(marker_face, 1) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 8) == 1 && subdivide_int3bits_read(marker_face, 2) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 9) == 1 && subdivide_int3bits_read(marker_face, 5) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
			break;
		case 4:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 4);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 5)], 5);
			if (subdivide_int3bits_read(marker_vert, 8) == 1 && subdivide_int3bits_read(marker_face, 0) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 2) == 1 && subdivide_int3bits_read(marker_face, 1) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 3) == 1 && subdivide_int3bits_read(marker_face, 2) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 6) == 1 && subdivide_int3bits_read(marker_face, 3) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
			break;
		case 5:
			subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 0)], 5);
			subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 6)], 4);
			if (subdivide_int3bits_read(marker_edge, 1) == 1 && subdivide_int3bits_read(marker_face, 0) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 4) == 1 && subdivide_int3bits_read(marker_face, 1) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 5) == 1 && subdivide_int3bits_read(marker_face, 2) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
			if (subdivide_int3bits_read(marker_edge, 9) == 1 && subdivide_int3bits_read(marker_face, 3) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
			break;
		default:
			printf("Morse matching error: face -> cube matching.\n");
		}
		subdivide_int3bits_write(marker_face, pos++, 3);
		for (; pos < 6; pos++) if (subdivide_int3bits_read(marker_face, pos) == 1) { subdivide_int3bits_write(marker_face, pos, 4); pq0_num++; }

		// Process elements in PQ0 and PQ1
		while (pq0_num > 0 || pq1_num > 0) {
			// Process elements in PQ1 (only contains 1-cells and 0-cells)
			while (pq1_num > 0) {
				pos = 0;
				// First search for 1-cells in PQ1
				if (subdivide_int3bits_read(marker_vert, 8) == 5) pos = 7;
				else if (subdivide_int3bits_read(marker_vert, 9) == 5) pos = 8;
				else for (subcells_num = 0; subcells_num < 10; subcells_num++) if (subdivide_int3bits_read(marker_edge, subcells_num) == 5) { pos = subcells_num + 9; break; }
				// If no 1-cell is found, search for 0-cell in PQ1
				if (pos == 0) for (subcells_num = 0; subcells_num < 8; subcells_num++) if (subdivide_int3bits_read(marker_vert, subcells_num) == 5) { pos = subcells_num + 19; break; }
				pq1_num--;
				switch (pos) {
				// 1-cells
				case 7: if (subdivide_int3bits_read(marker_face, 0) == 4) subcells_num = 1; else if (subdivide_int3bits_read(marker_face, 4) == 4) subcells_num = 5;  else subcells_num = 0; break;
				case 8: if (subdivide_int3bits_read(marker_face, 0) == 4) subcells_num = 1; else if (subdivide_int3bits_read(marker_face, 1) == 4) subcells_num = 2;  else subcells_num = 0; break;
				case 9: if (subdivide_int3bits_read(marker_face, 0) == 4) subcells_num = 1; else if (subdivide_int3bits_read(marker_face, 2) == 4) subcells_num = 3;  else subcells_num = 0; break;
				case 10: if (subdivide_int3bits_read(marker_face, 0) == 4) subcells_num = 1; else if (subdivide_int3bits_read(marker_face, 5) == 4) subcells_num = 6; else subcells_num = 0; break;
				case 11: if (subdivide_int3bits_read(marker_face, 1) == 4) subcells_num = 2; else if (subdivide_int3bits_read(marker_face, 4) == 4) subcells_num = 5; else subcells_num = 0; break;
				case 12: if (subdivide_int3bits_read(marker_face, 2) == 4) subcells_num = 3; else if (subdivide_int3bits_read(marker_face, 4) == 4) subcells_num = 5; else subcells_num = 0; break;
				case 13: if (subdivide_int3bits_read(marker_face, 1) == 4) subcells_num = 2; else if (subdivide_int3bits_read(marker_face, 5) == 4) subcells_num = 6; else subcells_num = 0; break;
				case 14: if (subdivide_int3bits_read(marker_face, 2) == 4) subcells_num = 3; else if (subdivide_int3bits_read(marker_face, 5) == 4) subcells_num = 6; else subcells_num = 0; break;
				case 15: if (subdivide_int3bits_read(marker_face, 3) == 4) subcells_num = 4; else if (subdivide_int3bits_read(marker_face, 4) == 4) subcells_num = 5; else subcells_num = 0; break;
				case 16: if (subdivide_int3bits_read(marker_face, 1) == 4) subcells_num = 2; else if (subdivide_int3bits_read(marker_face, 3) == 4) subcells_num = 4; else subcells_num = 0; break;
				case 17: if (subdivide_int3bits_read(marker_face, 2) == 4) subcells_num = 3; else if (subdivide_int3bits_read(marker_face, 3) == 4) subcells_num = 4; else subcells_num = 0; break;
				case 18: if (subdivide_int3bits_read(marker_face, 3) == 4) subcells_num = 4; else if (subdivide_int3bits_read(marker_face, 5) == 4) subcells_num = 6; else subcells_num = 0; break;
				// 0-cells
				case 19: if (subdivide_int3bits_read(marker_vert, 8) == 4) subcells_num = 7; else if (subdivide_int3bits_read(marker_vert, 9) == 4) subcells_num = 8; else if (subdivide_int3bits_read(marker_edge, 2) == 4) subcells_num = 11; else subcells_num = 0; break;
				case 20: if (subdivide_int3bits_read(marker_vert, 8) == 4) subcells_num = 7; else if (subdivide_int3bits_read(marker_edge, 0) == 4) subcells_num = 9; else if (subdivide_int3bits_read(marker_edge, 3) == 4) subcells_num = 12; else subcells_num = 0; break;
				case 21: if (subdivide_int3bits_read(marker_vert, 9) == 4) subcells_num = 8; else if (subdivide_int3bits_read(marker_edge, 1) == 4) subcells_num = 10; else if (subdivide_int3bits_read(marker_edge, 4) == 4) subcells_num = 13; else subcells_num = 0; break;
				case 22: if (subdivide_int3bits_read(marker_edge, 0) == 4) subcells_num = 9; else if (subdivide_int3bits_read(marker_edge, 1) == 4) subcells_num = 10; else if (subdivide_int3bits_read(marker_edge, 5) == 4) subcells_num = 14; else subcells_num = 0; break;
				case 23: if (subdivide_int3bits_read(marker_edge, 2) == 4) subcells_num = 11; else if (subdivide_int3bits_read(marker_edge, 6) == 4) subcells_num = 15; else if (subdivide_int3bits_read(marker_edge, 7) == 4) subcells_num = 16; else subcells_num = 0; break;
				case 24: if (subdivide_int3bits_read(marker_edge, 3) == 4) subcells_num = 12; else if (subdivide_int3bits_read(marker_edge, 6) == 4) subcells_num = 15; else if (subdivide_int3bits_read(marker_edge, 8) == 4) subcells_num = 17; else subcells_num = 0; break;
				case 25: if (subdivide_int3bits_read(marker_edge, 4) == 4) subcells_num = 13; else if (subdivide_int3bits_read(marker_edge, 7) == 4) subcells_num = 16; else if (subdivide_int3bits_read(marker_edge, 9) == 4) subcells_num = 18; else subcells_num = 0; break;
				case 26: if (subdivide_int3bits_read(marker_edge, 5) == 4) subcells_num = 14; else if (subdivide_int3bits_read(marker_edge, 8) == 4) subcells_num = 17; else if (subdivide_int3bits_read(marker_edge, 9) == 4) subcells_num = 18; else subcells_num = 0; break;
				default: printf("Morse matching error: PQ1 has 3-cell or 2-cells!\n");
				}
				// PQ1 cell can't find co-face to pair
				if (subcells_num == 0) {
					switch (pos) {
					case 7: case 8: subdivide_int3bits_write(marker_vert, pos + 1, 4); break;
					case 9: case 10: case 11: case 12: case 13: case 14: case 15: case 16: case 17: case 18: subdivide_int3bits_write(marker_edge, pos - 9, 4); break;
					case 19: case 20: case 21: case 22: case 23: case 24: case 25: case 26: subdivide_int3bits_write(marker_vert, pos - 19, 4); break;
					}
					pq0_num++;
				}
				// PQ1 cell is matched to co-face
				else {
					// Process faces of the matched co-face of PQ1 cell
					switch (subcells_num) {
					case 1: case 2: case 3: case 4: case 5: case 6: subdivide_int3bits_write(marker_face, subcells_num - 1, 3); break;
					case 7: case 8: subdivide_int3bits_write(marker_vert, subcells_num + 1, 3); break;
					case 9: case 10: case 11: case 12: case 13: case 14: case 15: case 16: case 17: case 18: subdivide_int3bits_write(marker_edge, subcells_num - 9, 3);
					}
					switch (pos) {
					case 7: case 8: subdivide_int3bits_write(marker_vert, pos + 1, 3); break;
					case 9: case 10: case 11: case 12: case 13: case 14: case 15: case 16: case 17: case 18: subdivide_int3bits_write(marker_edge, pos - 9, 3); break;
					case 19: case 20: case 21: case 22: case 23: case 24: case 25: case 26: subdivide_int3bits_write(marker_vert, pos - 19, 3);
					}
					pq0_num--;
					
					switch (subcells_num) {
					// Cell in PQ1 matched to 2-cell co-face
					case 1:
						if (pos == 7) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 7)], 5);
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }

							// Add faces of E0 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
						}
						else if (pos == 8) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 8)], 2);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }

							// Add faces of E1 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
						}
						else if (pos == 9) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 9)], 1);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }

							// Add faces of E2 to PQ1
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 1)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 10)], 4);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }

							// Add faces of E3 to PQ1
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						break;
					case 2:
						if (pos == 8) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 8)], 3);
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }

							// Add faces of E1 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
						}
						else if (pos == 11) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 11)], 5);
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }

							// Add faces of E4 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_vert, 9) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_vert, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
						}
						else if (pos == 13) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 13)], 4);
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }

							// Add faces of E6 to PQ1
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 7) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 7) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 2)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 16)], 0);
							if (subdivide_int3bits_read(marker_vert, 9) == 1) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 9) == 5) { subdivide_int3bits_write(marker_vert, 9, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }

							// Add faces of E9 to PQ1
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						break;
					case 3:
						if (pos == 9) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 9)], 3);
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }

							// Add faces of E2 to PQ1
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						else if (pos == 12) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 12)], 5);
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }

							// Add faces of E5 to PQ1
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 0) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 0) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						else if (pos == 14) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 14)], 4);
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }

							// Add faces of E7 to PQ1
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 8) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 8) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 3)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 17)], 0);
							if (subdivide_int3bits_read(marker_edge, 0) == 1) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 0) == 5) { subdivide_int3bits_write(marker_edge, 0, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }

							// Add faces of E10 to PQ1
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						break;
					case 4:
						if (pos == 15) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 15)], 5);
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E8 to PQ1
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						else if (pos == 16) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 16)], 2);
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E9 to PQ1
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						else if (pos == 17) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 17)], 1);
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E10 to PQ1
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 4)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 18)], 4);
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 7) == 1) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 7) == 5) { subdivide_int3bits_write(marker_edge, 7, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 8) == 1) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 8) == 5) { subdivide_int3bits_write(marker_edge, 8, 4); pq1_num--; pq0_num++; }

							// Add faces of E11 to PQ1
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						break;
					case 5:
						if (pos == 7) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 7)], 3);
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }

							// Add faces of E0 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
						}
						else if (pos == 11) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 11)], 2);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }

							// Add faces of E4 to PQ1
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_vert, 9) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_vert, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
						}
						else if (pos == 12) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 12)], 1);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 6) == 1) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 6) == 5) { subdivide_int3bits_write(marker_edge, 6, 4); pq1_num--; pq0_num++; }

							// Add faces of E5 to PQ1
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 0) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 0) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 5)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 15)], 0);
							if (subdivide_int3bits_read(marker_vert, 8) == 1) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_vert, 8) == 5) { subdivide_int3bits_write(marker_vert, 8, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 2) == 1) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 2) == 5) { subdivide_int3bits_write(marker_edge, 2, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 3) == 1) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 3) == 5) { subdivide_int3bits_write(marker_edge, 3, 4); pq1_num--; pq0_num++; }

							// Add faces of E8 to PQ1
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						break;
					case 6:
						if (pos == 10) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 10)], 3);
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E3 to PQ1
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						else if (pos == 13) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 13)], 2);
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E6 to PQ1
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 7) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 7) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						else if (pos == 14) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 14)], 1);
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 9) == 1) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 9) == 5) { subdivide_int3bits_write(marker_edge, 9, 4); pq1_num--; pq0_num++; }

							// Add faces of E7 to PQ1
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 8) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 8) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 6)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 18)], 0);
							if (subdivide_int3bits_read(marker_edge, 1) == 1) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 1) == 5) { subdivide_int3bits_write(marker_edge, 1, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 4) == 1) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 4) == 5) { subdivide_int3bits_write(marker_edge, 4, 4); pq1_num--; pq0_num++; }
							if (subdivide_int3bits_read(marker_edge, 5) == 1) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
							else if (subdivide_int3bits_read(marker_edge, 5) == 5) { subdivide_int3bits_write(marker_edge, 5, 4); pq1_num--; pq0_num++; }

							// Add faces of E11 to PQ1
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						break;
					// Cell in PQ1 matched to 1-cell co-face
					case 7:
						if (pos == 19) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 7)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 2);
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) { 
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++; 
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 7)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 1);
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
						}
						break;
					case 8:
						if (pos == 19) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 5);
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 8)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 4);
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
						}
						break;
					case 9:
						if (pos == 20) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 5);
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 9)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 4);
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
						}
						break;
					case 10:
						if (pos == 21) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 2);
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 10)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 1);
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
						}
						break;
					case 11:
						if (pos == 19) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 19)], 3);
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 11)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 0);
							if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_vert, 9) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_vert, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
							}
						}
						break;
					case 12:
						if (pos == 20) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 20)], 3);
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 12)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 0);
							if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 0) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 0) == 4))) {
								subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
							}
						}
						break;
					case 13:
						if (pos == 21) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 21)], 3);
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 7) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 7) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 13)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 0);
							if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
							}
						}
						break;
					case 14:
						if (pos == 22) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 0); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 22)], 3);
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 8) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 8) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 14)], 3); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 0);
							if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
								subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
							}
						}
						break;
					case 15:
						if (pos == 23) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 2);
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 15)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 1);
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
						}
						break;
					case 16:
						if (pos == 23) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 23)], 5);
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 16)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 4);
							if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
							}
						}
						break;
					case 17:
						if (pos == 24) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 4); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 24)], 5);
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 17)], 5); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 4);
							if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
								subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
							}
						}
						break;
					case 18:
						if (pos == 25) {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 1); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 25)], 2);
							if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
								subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
							}
						}
						else {
							subdivide_short2bits_write1(match_shared[cube_offset(blkDimSetting, coord, 18)], 2); subdivide_short2bits_write0(match_shared[cube_offset(blkDimSetting, coord, 26)], 1);
							if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
								subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
							}
						}
						break;
					default: printf("Morse matching error: matched co-face has vertices.\n");
					}
				}
			}
			// Process elements in PQ0 (contains 2-cells, 1-cells, and 0-cells)
			if (pq0_num > 0) {
				// Search for element in PQ0 starting from 2-cell, 1-cell, to 0-cell
				pos = 0;
				for (subcells_num = 0; subcells_num < 6; subcells_num++) if (subdivide_int3bits_read(marker_face, subcells_num) == 4) { pos = subcells_num + 1; break; }
				if (pos == 0) { 
					if (subdivide_int3bits_read(marker_vert, 8) == 4) pos = 7;
					else if (subdivide_int3bits_read(marker_vert, 9) == 4) pos = 8;
					else for (subcells_num = 0; subcells_num < 10; subcells_num++) if (subdivide_int3bits_read(marker_edge, subcells_num) == 4) { pos = subcells_num + 9; break; }
				}
				if (pos == 0) for (subcells_num = 0; subcells_num < 8; subcells_num++) if (subdivide_int3bits_read(marker_vert, subcells_num) == 4) { pos = subcells_num + 19; break; }
				pq0_num--;

				switch (pos) {
				// Process 2-cells
				case 1:
					subdivide_int3bits_write(marker_face, 0, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 1)], 3);
					if (subdivide_int3bits_read(marker_vert, 8) == 1 && subdivide_int3bits_read(marker_face, 4) == 4) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_vert, 9) == 1 && subdivide_int3bits_read(marker_face, 1) == 4) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 0) == 1 && subdivide_int3bits_read(marker_face, 2) == 4) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 1) == 1 && subdivide_int3bits_read(marker_face, 5) == 4) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
					break;
				case 2:
					subdivide_int3bits_write(marker_face, 1, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 2)], 3);
					if (subdivide_int3bits_read(marker_vert, 9) == 1 && subdivide_int3bits_read(marker_face, 0) == 4) { subdivide_int3bits_write(marker_vert, 9, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 2) == 1 && subdivide_int3bits_read(marker_face, 4) == 4) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 4) == 1 && subdivide_int3bits_read(marker_face, 5) == 4) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 7) == 1 && subdivide_int3bits_read(marker_face, 3) == 4) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
					break;
				case 3:
					subdivide_int3bits_write(marker_face, 2, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 3)], 3);
					if (subdivide_int3bits_read(marker_edge, 0) == 1 && subdivide_int3bits_read(marker_face, 0) == 4) { subdivide_int3bits_write(marker_edge, 0, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 3) == 1 && subdivide_int3bits_read(marker_face, 4) == 4) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 5) == 1 && subdivide_int3bits_read(marker_face, 5) == 4) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 8) == 1 && subdivide_int3bits_read(marker_face, 3) == 4) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
					break;
				case 4:
					subdivide_int3bits_write(marker_face, 3, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 4)], 3);
					if (subdivide_int3bits_read(marker_edge, 6) == 1 && subdivide_int3bits_read(marker_face, 4) == 4) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 7) == 1 && subdivide_int3bits_read(marker_face, 1) == 4) { subdivide_int3bits_write(marker_edge, 7, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 8) == 1 && subdivide_int3bits_read(marker_face, 2) == 4) { subdivide_int3bits_write(marker_edge, 8, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 9) == 1 && subdivide_int3bits_read(marker_face, 5) == 4) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
					break;
				case 5:
					subdivide_int3bits_write(marker_face, 4, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 5)], 3);
					if (subdivide_int3bits_read(marker_vert, 8) == 1 && subdivide_int3bits_read(marker_face, 0) == 4) { subdivide_int3bits_write(marker_vert, 8, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 2) == 1 && subdivide_int3bits_read(marker_face, 1) == 4) { subdivide_int3bits_write(marker_edge, 2, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 3) == 1 && subdivide_int3bits_read(marker_face, 2) == 4) { subdivide_int3bits_write(marker_edge, 3, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 6) == 1 && subdivide_int3bits_read(marker_face, 3) == 4) { subdivide_int3bits_write(marker_edge, 6, 5); pq1_num++; }
					break;
				case 6:
					subdivide_int3bits_write(marker_face, 5, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 6)], 3);
					if (subdivide_int3bits_read(marker_edge, 1) == 1 && subdivide_int3bits_read(marker_face, 0) == 4) { subdivide_int3bits_write(marker_edge, 1, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 4) == 1 && subdivide_int3bits_read(marker_face, 1) == 4) { subdivide_int3bits_write(marker_edge, 4, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 5) == 1 && subdivide_int3bits_read(marker_face, 2) == 4) { subdivide_int3bits_write(marker_edge, 5, 5); pq1_num++; }
					if (subdivide_int3bits_read(marker_edge, 9) == 1 && subdivide_int3bits_read(marker_face, 3) == 4) { subdivide_int3bits_write(marker_edge, 9, 5); pq1_num++; }
					break;
				// Process 1-cells
				case 7:
					subdivide_int3bits_write(marker_vert, 8, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 7)], 2);
					if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
						subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
						subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
					}
					break;
				case 8:
					subdivide_int3bits_write(marker_vert, 9, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 8)], 2);
					if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 2) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 2) == 4))) {
						subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
						subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
					}
					break;
				case 9:
					subdivide_int3bits_write(marker_edge, 0, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 9)], 2);
					if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 3) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 3) == 4))) {
						subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 1) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 1) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
						subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
					}
					break;
				case 10:
					subdivide_int3bits_write(marker_edge, 1, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 10)], 2);
					if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 4) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 4) == 4))) {
						subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 5) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 5) == 4))) {
						subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
					}
					break;
				case 11:
					subdivide_int3bits_write(marker_edge, 2, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 11)], 2);
					if (subdivide_int3bits_read(marker_vert, 0) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_vert, 9) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_vert, 9) == 4))) {
						subdivide_int3bits_write(marker_vert, 0, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
						subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
					}
					break;
				case 12:
					subdivide_int3bits_write(marker_edge, 3, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 12)], 2);
					if (subdivide_int3bits_read(marker_vert, 1) == 1 && ((subdivide_int3bits_read(marker_vert, 8) == 4 && subdivide_int3bits_read(marker_edge, 0) != 4) || (subdivide_int3bits_read(marker_vert, 8) != 4 && subdivide_int3bits_read(marker_edge, 0) == 4))) {
						subdivide_int3bits_write(marker_vert, 1, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 6) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 6) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
						subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
					}
					break;
				case 13:
					subdivide_int3bits_write(marker_edge, 4, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 13)], 2);
					if (subdivide_int3bits_read(marker_vert, 2) == 1 && ((subdivide_int3bits_read(marker_vert, 9) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_vert, 9) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
						subdivide_int3bits_write(marker_vert, 2, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 7) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 7) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
						subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
					}
					break;
				case 14:
					subdivide_int3bits_write(marker_edge, 5, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 14)], 2);
					if (subdivide_int3bits_read(marker_vert, 3) == 1 && ((subdivide_int3bits_read(marker_edge, 0) == 4 && subdivide_int3bits_read(marker_edge, 1) != 4) || (subdivide_int3bits_read(marker_edge, 0) != 4 && subdivide_int3bits_read(marker_edge, 1) == 4))) {
						subdivide_int3bits_write(marker_vert, 3, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 8) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 8) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
						subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
					}
					break;
				case 15:
					subdivide_int3bits_write(marker_edge, 6, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 15)], 2);
					if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
						subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
						subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
					}
					break;
				case 16:
					subdivide_int3bits_write(marker_edge, 7, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 16)], 2);
					if (subdivide_int3bits_read(marker_vert, 4) == 1 && ((subdivide_int3bits_read(marker_edge, 2) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 2) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
						subdivide_int3bits_write(marker_vert, 4, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
						subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
					}
					break;
				case 17:
					subdivide_int3bits_write(marker_edge, 8, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 17)], 2);
					if (subdivide_int3bits_read(marker_vert, 5) == 1 && ((subdivide_int3bits_read(marker_edge, 3) == 4 && subdivide_int3bits_read(marker_edge, 6) != 4) || (subdivide_int3bits_read(marker_edge, 3) != 4 && subdivide_int3bits_read(marker_edge, 6) == 4))) {
						subdivide_int3bits_write(marker_vert, 5, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 9) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 9) == 4))) {
						subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
					}
					break;
				case 18:
					subdivide_int3bits_write(marker_edge, 9, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 18)], 2);
					if (subdivide_int3bits_read(marker_vert, 6) == 1 && ((subdivide_int3bits_read(marker_edge, 4) == 4 && subdivide_int3bits_read(marker_edge, 7) != 4) || (subdivide_int3bits_read(marker_edge, 4) != 4 && subdivide_int3bits_read(marker_edge, 7) == 4))) {
						subdivide_int3bits_write(marker_vert, 6, 5); pq1_num++;
					}
					if (subdivide_int3bits_read(marker_vert, 7) == 1 && ((subdivide_int3bits_read(marker_edge, 5) == 4 && subdivide_int3bits_read(marker_edge, 8) != 4) || (subdivide_int3bits_read(marker_edge, 5) != 4 && subdivide_int3bits_read(marker_edge, 8) == 4))) {
						subdivide_int3bits_write(marker_vert, 7, 5); pq1_num++;
					}
					break;
				// Process 0-cells
				case 19:
					subdivide_int3bits_write(marker_vert, 0, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 19)], 1);
					break;
				case 20:
					subdivide_int3bits_write(marker_vert, 1, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 20)], 1);
					break;
				case 21:
					subdivide_int3bits_write(marker_vert, 2, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 21)], 1);
					break;
				case 22:
					subdivide_int3bits_write(marker_vert, 3, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 22)], 1);
					break;
				case 23:
					subdivide_int3bits_write(marker_vert, 4, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 23)], 1);
					break;
				case 24:
					subdivide_int3bits_write(marker_vert, 5, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 24)], 1);
					break;
				case 25:
					subdivide_int3bits_write(marker_vert, 6, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 25)], 1);
					break;
				case 26:
					subdivide_int3bits_write(marker_vert, 7, 2);
					writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 26)], 1);
				}
			}
		}
	}
	// voxel (3-cell) is critical
	else writeCrit(crit_shared[cube_offset(blkDimSetting, coord, 0)], 4);

	// Copy from shared memory to global memory
	pos = ((blockIdx.z * blockDim.z + threadIdx.z) * 2 + 1) * STRIDE_Y * (chunkSizeH * 2 + 1) + ((blockIdx.y * blockDim.y + threadIdx.y) * 2 + 1) * STRIDE_Y + (blockIdx.x * blockDim.x + threadIdx.x) * 2 + 1;
	px  = pos - STRIDE_Y * (chunkSizeH * 2 + 1);
	py  = pos + STRIDE_Y * (chunkSizeH * 2 + 1);
	pw  = STRIDE_Y;

	// Write 3-cell
	match_global[pos] = match_shared[coord];
	crit_global[pos]  = crit_shared[coord];
	// Write 2-cells
	if (subdivide_int3bits_read(marker_face, 0) > 0) { match_global[px]			  = match_shared[cube_offset(blkDimSetting, coord, 1)]; crit_global[px]			   = crit_shared[cube_offset(blkDimSetting, coord, 1)]; }
	if (subdivide_int3bits_read(marker_face, 1) > 0) { match_global[pos - 1]	  = match_shared[cube_offset(blkDimSetting, coord, 2)]; crit_global[pos - 1]	   = crit_shared[cube_offset(blkDimSetting, coord, 2)]; }
	if (subdivide_int3bits_read(marker_face, 2) > 0) { match_global[pos + 1]	  = match_shared[cube_offset(blkDimSetting, coord, 3)]; crit_global[pos + 1]	   = crit_shared[cube_offset(blkDimSetting, coord, 3)]; }
	if (subdivide_int3bits_read(marker_face, 3) > 0) { match_global[py]			  = match_shared[cube_offset(blkDimSetting, coord, 4)]; crit_global[py]			   = crit_shared[cube_offset(blkDimSetting, coord, 4)]; }
	if (subdivide_int3bits_read(marker_face, 4) > 0) { match_global[pos - pw]	  = match_shared[cube_offset(blkDimSetting, coord, 5)]; crit_global[pos - pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 5)]; }
	if (subdivide_int3bits_read(marker_face, 5) > 0) { match_global[pos + pw]	  = match_shared[cube_offset(blkDimSetting, coord, 6)]; crit_global[pos + pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 6)]; }
	// Write 1-cells
	if (subdivide_int3bits_read(marker_vert, 8) > 0) { match_global[px - pw]	  = match_shared[cube_offset(blkDimSetting, coord, 7)]; crit_global[px - pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 7)]; }
	if (subdivide_int3bits_read(marker_vert, 9) > 0) { match_global[px - 1]		  = match_shared[cube_offset(blkDimSetting, coord, 8)]; crit_global[px - 1]		   = crit_shared[cube_offset(blkDimSetting, coord, 8)]; }
	if (subdivide_int3bits_read(marker_edge, 0) > 0) { match_global[px + 1]		  = match_shared[cube_offset(blkDimSetting, coord, 9)]; crit_global[px + 1]		   = crit_shared[cube_offset(blkDimSetting, coord, 9)]; }
	if (subdivide_int3bits_read(marker_edge, 1) > 0) { match_global[px + pw]	  = match_shared[cube_offset(blkDimSetting, coord, 10)]; crit_global[px + pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 10)]; }
	if (subdivide_int3bits_read(marker_edge, 2) > 0) { match_global[pos - pw - 1] = match_shared[cube_offset(blkDimSetting, coord, 11)]; crit_global[pos - pw - 1] = crit_shared[cube_offset(blkDimSetting, coord, 11)]; }
	if (subdivide_int3bits_read(marker_edge, 3) > 0) { match_global[pos - pw + 1] = match_shared[cube_offset(blkDimSetting, coord, 12)]; crit_global[pos - pw + 1] = crit_shared[cube_offset(blkDimSetting, coord, 12)]; }
	if (subdivide_int3bits_read(marker_edge, 4) > 0) { match_global[pos + pw - 1] = match_shared[cube_offset(blkDimSetting, coord, 13)]; crit_global[pos + pw - 1] = crit_shared[cube_offset(blkDimSetting, coord, 13)]; }
	if (subdivide_int3bits_read(marker_edge, 5) > 0) { match_global[pos + pw + 1] = match_shared[cube_offset(blkDimSetting, coord, 14)]; crit_global[pos + pw + 1] = crit_shared[cube_offset(blkDimSetting, coord, 14)]; }
	if (subdivide_int3bits_read(marker_edge, 6) > 0) { match_global[py - pw]	  = match_shared[cube_offset(blkDimSetting, coord, 15)]; crit_global[py - pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 15)]; }
	if (subdivide_int3bits_read(marker_edge, 7) > 0) { match_global[py - 1]		  = match_shared[cube_offset(blkDimSetting, coord, 16)]; crit_global[py - 1]	   = crit_shared[cube_offset(blkDimSetting, coord, 16)]; }
	if (subdivide_int3bits_read(marker_edge, 8) > 0) { match_global[py + 1]		  = match_shared[cube_offset(blkDimSetting, coord, 17)]; crit_global[py + 1]	   = crit_shared[cube_offset(blkDimSetting, coord, 17)]; }
	if (subdivide_int3bits_read(marker_edge, 9) > 0) { match_global[py + pw]	  = match_shared[cube_offset(blkDimSetting, coord, 18)]; crit_global[py + pw]	   = crit_shared[cube_offset(blkDimSetting, coord, 18)]; }
	// Write 0-cells
	if (subdivide_int3bits_read(marker_vert, 0) > 0) { match_global[px - pw - 1]  = match_shared[cube_offset(blkDimSetting, coord, 19)]; crit_global[px - pw - 1]  = crit_shared[cube_offset(blkDimSetting, coord, 19)]; }
	if (subdivide_int3bits_read(marker_vert, 1) > 0) { match_global[px - pw + 1]  = match_shared[cube_offset(blkDimSetting, coord, 20)]; crit_global[px - pw + 1]  = crit_shared[cube_offset(blkDimSetting, coord, 20)]; }
	if (subdivide_int3bits_read(marker_vert, 2) > 0) { match_global[px + pw - 1]  = match_shared[cube_offset(blkDimSetting, coord, 21)]; crit_global[px + pw - 1]  = crit_shared[cube_offset(blkDimSetting, coord, 21)]; }
	if (subdivide_int3bits_read(marker_vert, 3) > 0) { match_global[px + pw + 1]  = match_shared[cube_offset(blkDimSetting, coord, 22)]; crit_global[px + pw + 1]  = crit_shared[cube_offset(blkDimSetting, coord, 22)]; }
	if (subdivide_int3bits_read(marker_vert, 4) > 0) { match_global[py - pw - 1]  = match_shared[cube_offset(blkDimSetting, coord, 23)]; crit_global[py - pw - 1]  = crit_shared[cube_offset(blkDimSetting, coord, 23)]; }
	if (subdivide_int3bits_read(marker_vert, 5) > 0) { match_global[py - pw + 1]  = match_shared[cube_offset(blkDimSetting, coord, 24)]; crit_global[py - pw + 1]  = crit_shared[cube_offset(blkDimSetting, coord, 24)]; }
	if (subdivide_int3bits_read(marker_vert, 6) > 0) { match_global[py + pw - 1]  = match_shared[cube_offset(blkDimSetting, coord, 25)]; crit_global[py + pw - 1]  = crit_shared[cube_offset(blkDimSetting, coord, 25)]; }
	if (subdivide_int3bits_read(marker_vert, 7) > 0) { match_global[py + pw + 1]  = match_shared[cube_offset(blkDimSetting, coord, 26)]; crit_global[py + pw + 1]  = crit_shared[cube_offset(blkDimSetting, coord, 26)]; }
}

template <typename type>
__host__ void procLowerStars_tile2D(
	cudaTextureObject_t& chunk,
	const uchar_			chunkID,
	uchar_* match,
	uchar_* crit,
	const uint2				chunkSize,
	const uint2				blockSize,
	const uint2				blockSizeX,
	cudaStream_t& stream
)
{
	/*
	Descriptions:
		Launch morse matching kernels enabled with tiling and boundary manipulation. Note
		this function supports ONLY pixel/voxel as 2-cells.

		chunkSize is without halo. match and crit have the same size: (2 x chunkSize.x + 1) x (2 x chunkSize.y + 1)
		@chunk: texture object already loaded with data in device
		@match: device memory to store output matching grid
		@crit	  : size of (2 x h + 1) x (2 x w + 1), dim + 1 marks the critical node, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
		@chunkSize: size of the chunk, [height, width]
		@blockSize: size of the block, block is assumed to have equal size for x and y
		@stream: the CUDA stream into which this operation is pushed
	*/
	// define block size
	dim3 block(blockSize.x, blockSize.y);
	// define grid size
	dim3 grid(iDivUp(chunkSize.y, blockSize.x), iDivUp(chunkSize.x, blockSize.y));
	size_t sharedMem_size = 2 * PRODUCT2(blockSizeX.x, blockSizeX.y) * sizeof(uchar_);

	// Generate block.x: 2, 4, 8, 16, 32
#define GEN_CASE(BX) \
  case (BX):         \
    procLowerStars_voxFace_kernel2D<type, BX> <<<grid, block, sharedMem_size, stream>>>(chunk, chunkID, match, crit); break;

#define FOR_EACH_BX(OP) OP(2) OP(4) OP(8) OP(16) OP(32)

// launch kernel
	switch (static_cast<int>(blockSize.x)) {
		FOR_EACH_BX(GEN_CASE)
	default:
		printf("ERROR: unsupported blockDim.x setting: %d\n", static_cast<int>(blockSize.x));
		exit(1);
	}

#undef FOR_EACH_BX
#undef GEN_CASE
}
template __host__ void procLowerStars_tile2D<uchar_>(cudaTextureObject_t& chunk, const uchar_ chunkID, uchar_* match, uchar_* crit, const uint2 chunkSize, const uint2 blockSize, const uint2 blockSizeX, cudaStream_t& stream);
template __host__ void procLowerStars_tile2D<ushort_>(cudaTextureObject_t& chunk, const uchar_ chunkID, uchar_* match, uchar_* crit, const uint2 chunkSize, const uint2 blockSize, const uint2 blockSizeX, cudaStream_t& stream);
template __host__ void procLowerStars_tile2D<int>(cudaTextureObject_t& chunk, const uchar_ chunkID, uchar_* match, uchar_* crit, const uint2 chunkSize, const uint2 blockSize, const uint2 blockSizeX, cudaStream_t& stream);
template __host__ void procLowerStars_tile2D<float>(cudaTextureObject_t& chunk, const uchar_ chunkID, uchar_* match, uchar_* crit, const uint2 chunkSize, const uint2 blockSize, const uint2 blockSizeX, cudaStream_t& stream);

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
)
{
	/*
	Descriptions:
		Launch morse matching kernels enabled with tiling and boundary manipulation. Note
		this function supports ONLY pixel/voxel as 3-cells.

		chunkSize is without halo. match and crit_mask have the same size: (2 x chunkSize.x + 1) x (2 x chunkSize.y + 1) x (2 x chunkSize.z + 1)
		@chunk: texture object loaded with data in device
		@match: device memory to store output matching grid
		@crit_mask: size of (2 x h + 1) x (2 x w + 1) x (2 x d + 1), dim + 1 marks the critical node, 0 otherwise. E.g. a dim 1 critical cell is marked 2.
		@chunkSize: size of the chunk
		@blockSize: size of the block
		@stream: the CUDA stream into which this operation is pushed
	*/
	// define block size
	dim3 block(blockSize.y, blockSize.x, blockSize.z);
	// define grid size
	dim3 grid(iDivUp(chunkSize.y, blockSize.y), iDivUp(chunkSize.x, blockSize.x), iDivUp(chunkSize.z, blockSize.z));
	size_t sharedMemSize = PRODUCT3(blockSizeX.x, blockSizeX.y, blockSizeX.z) * (sizeof(uchar_) + sizeof(ushort_));

	// Generate block.x block.y combinations: (2, 2) - (2, 8); (4, 2) - (4, 8); (8, 2) - (8, 8); (16, 2) - (16, 8)
#define GEN_CASE(BX,BY) \
  case ((BX)*10 + (BY)): \
    procLowerStars_voxFace_kernel3D<type, ((BX)*10 + (BY))> \
      <<<grid, block, sharedMemSize, stream>>>(chunk, chunkID, match, crit); break;

#define GEN_BY(BX) GEN_CASE(BX,2) GEN_CASE(BX,4) GEN_CASE(BX,8)
#define FOR_EACH_BX(OP) OP(2) OP(4) OP(8) OP(16)
	// launch kernel
	switch (int(blockSize.x) * 10 + int(blockSize.y)) {
		FOR_EACH_BX(GEN_BY)
	default: { printf("ERROR: unsupported blockDim settings\n"); exit(1); }
	}

#undef FOR_EACH_BX
#undef GEN_BY
#undef GEN_CASE
}
template __host__ void procLowerStars_tile3D<uchar_>(cudaTextureObject_t&, const ushort_, ushort_*, uchar_*, const uint3, const uint3, const uint3, cudaStream_t&);
template __host__ void procLowerStars_tile3D<ushort_>(cudaTextureObject_t&, const ushort_, ushort_*, uchar_*, const uint3, const uint3, const uint3, cudaStream_t&);
template __host__ void procLowerStars_tile3D<int>(cudaTextureObject_t&, const ushort_, ushort_*, uchar_*, const uint3, const uint3, const uint3, cudaStream_t&);
template __host__ void procLowerStars_tile3D<float>(cudaTextureObject_t&, const ushort_, ushort_*, uchar_*, const uint3, const uint3, const uint3, cudaStream_t&);