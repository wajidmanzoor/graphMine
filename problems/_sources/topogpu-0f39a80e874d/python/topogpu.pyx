# topogpu.pyx

# distutils: language = c++
# distutils: include_dirs = ["/path/to/cuda/includes"]
# distutils: library_dirs = ["/path/to/cuda/libs"]
# distutils: libraries = ["cudart"]

from libcpp cimport bool
from libcpp.string cimport string
from libcpp.vector cimport vector
import numpy as np
cimport numpy as cnp
cnp.import_array()

# -------------------- C/C++ interop types --------------------
cdef extern from "topo.cuh":
    ctypedef unsigned int uint_
    
    ctypedef struct uint2:
        unsigned int x
        unsigned int y

    ctypedef struct uint3:
        unsigned int x
        unsigned int y
        unsigned int z
        
    cdef inline uint2 make_uint2c(unsigned int x, unsigned int y):
        cdef uint2 u
        u.x = x; u.y = y;
        return u

    cdef inline uint3 make_uint3c(unsigned int x, unsigned int y, unsigned int z):
        cdef uint3 u
        u.x = x; u.y = y; u.z = z
        return u

# -------------------- PH_multiThread<T> specializations --------------------
cdef extern from "topo.cuh" namespace "":
    cdef cppclass PH2D_multiThread_ushort "PH2D_multiThread<unsigned short>":
        PH2D_multiThread_ushort(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()
        
    cdef cppclass PH2D_multiThread_int "PH2D_multiThread<int>":
        PH2D_multiThread_int(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()
        
    cdef cppclass PH2D_multiThread_float "PH2D_multiThread<float>":
        PH2D_multiThread_float(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()
    
    cdef cppclass PH3D_multiThread_ushort "PH3D_multiThread<unsigned short>":
        PH3D_multiThread_ushort(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()              # rows x 9, float32

    cdef cppclass PH3D_multiThread_int "PH3D_multiThread<int>":
        PH3D_multiThread_int(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()

    cdef cppclass PH3D_multiThread_float "PH3D_multiThread<float>":
        PH3D_multiThread_float(bool computePH, bool write2HDD)
        double bndmat_reduction()
        void reset()
        uint_ return_pairNum()
        float* return_results()

# -------------------- TopoGPU3D<T> specializations --------------------
cdef extern from "topo.cuh" namespace "":
    cdef cppclass TopoGPU2D_ushort "TopoGPU2D<unsigned short>":
        TopoGPU2D_ushort(uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint2 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH2D_multiThread_ushort& ph)
        void run_frmArr(unsigned short* src, PH2D_multiThread_ushort& ph)
        uint2 return_blockDims()
        uint2 return_chunkDims()
    
    cdef cppclass TopoGPU2D_int "TopoGPU2D<int>":
        TopoGPU2D_int(uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint2 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH2D_multiThread_int& ph)
        void run_frmArr(int* src, PH2D_multiThread_int& ph)
        uint2 return_blockDims()
        uint2 return_chunkDims()
        
    cdef cppclass TopoGPU2D_float "TopoGPU2D<float>":
        TopoGPU2D_float(uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint2 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH2D_multiThread_float& ph)
        void run_frmArr(float* src, PH2D_multiThread_float& ph)
        uint2 return_blockDims()
        uint2 return_chunkDims()
    
    cdef cppclass TopoGPU3D_ushort "TopoGPU3D<unsigned short>":
        TopoGPU3D_ushort(uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint3 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH3D_multiThread_ushort& ph)
        void run_frmArr(unsigned short* src, PH3D_multiThread_ushort& ph)
        uint3 return_blockDims()
        uint3 return_chunkDims()

    cdef cppclass TopoGPU3D_int "TopoGPU3D<int>":
        TopoGPU3D_int(uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint3 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH3D_multiThread_int& ph)
        void run_frmArr(int* src, PH3D_multiThread_int& ph)
        uint3 return_blockDims()
        uint3 return_chunkDims()

    cdef cppclass TopoGPU3D_float "TopoGPU3D<float>":
        TopoGPU3D_float(uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void configure(uint3 imgSize, uint_ maxDim)
        void run_frmFile(const string& filename, const string& datatype, PH3D_multiThread_float& ph)
        void run_frmArr(float* src, PH3D_multiThread_float& ph)
        uint3 return_blockDims()
        uint3 return_chunkDims()

# -------------------- helpers --------------------
cdef inline string _to_string(object o):
    cdef bytes b
    if isinstance(o, bytes):
        b = o
    else:
        b = (<str>o).encode('utf-8')
    return b
    
cdef inline cnp.ndarray _results_to_numpy2D(float* ptr, uint_ rows) except *:
    cdef cnp.npy_intp dims[2]
    dims[0] = <cnp.npy_intp> rows
    dims[1] = 7
    return cnp.PyArray_SimpleNewFromData(2, dims, cnp.NPY_FLOAT, <void*>ptr)

cdef inline cnp.ndarray _results_to_numpy3D(float* ptr, uint_ rows) except *:
    cdef cnp.npy_intp dims[2]
    dims[0] = <cnp.npy_intp> rows
    dims[1] = 9
    return cnp.PyArray_SimpleNewFromData(2, dims, cnp.NPY_FLOAT, <void*>ptr)

# -------------------- Python wrappers --------------------
# 2D Mapping rules requested:
#   Python 'uchar'  -> backend: unsigned short (PH2D_multiThread_ushort + TopoGPU2D_ushort)
#   Python 'ushort' -> backend: int            (PH2D_multiThread_int    + TopoGPU2D_int)
#   Python 'int'    -> backend: int            (PH2D_multiThread_int    + TopoGPU2D_int)
#   Python 'float'  -> backend: float          (PH2D_multiThread_float  + TopoGPU2D_float)

# 3D Mapping rules requested:
#   Python 'uchar'  -> backend: unsigned short (PH3D_multiThread_ushort + TopoGPU3D_ushort)
#   Python 'ushort' -> backend: int            (PH3D_multiThread_int    + TopoGPU3D_int)
#   Python 'int'    -> backend: int            (PH3D_multiThread_int    + TopoGPU3D_int)
#   Python 'float'  -> backend: float          (PH3D_multiThread_float  + TopoGPU3D_float)

cdef class PyTopoGPU2D_ushort:   # backend T = unsigned short
    cdef TopoGPU2D_ushort* gpu
    cdef PH2D_multiThread_ushort* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_ushort(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH2D_multiThread_ushort(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY):
        cdef uint2 img = make_uint2c(imgX, imgY)
        self.gpu.configure(img, 2)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])   # pass C++ reference via pointer indexing
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.uint16)
        cdef unsigned short* ptr = <unsigned short*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU2D_ushort::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy2D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)
		
    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)
        
cdef class PyTopoGPU2D_int:   # backend T = int
    cdef TopoGPU2D_int* gpu
    cdef PH2D_multiThread_int* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_int(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH2D_multiThread_int(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY):
        cdef uint2 img = make_uint2c(imgX, imgY)
        self.gpu.configure(img, 2)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])   # pass C++ reference via pointer indexing
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.int32)
        cdef int* ptr = <int*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU2D_int::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy2D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)
		
    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)
        
cdef class PyTopoGPU2D_float:   # backend T = float
    cdef TopoGPU2D_float* gpu
    cdef PH2D_multiThread_float* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_float(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH2D_multiThread_float(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY):
        cdef uint2 img = make_uint2c(imgX, imgY)
        self.gpu.configure(img, 2)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])   # pass C++ reference via pointer indexing
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.float32)
        cdef float* ptr = <float*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU2D_float::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy2D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)
		
    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)

cdef class PyTopoGPU3D_ushort:   # backend T = unsigned short
    cdef TopoGPU3D_ushort* gpu
    cdef PH3D_multiThread_ushort* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_ushort(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH3D_multiThread_ushort(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        self.gpu.configure(img, 3)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])   # pass C++ reference via pointer indexing
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.uint16)
        cdef unsigned short* ptr = <unsigned short*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU3D_ushort::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy3D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)
		
    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

cdef class PyTopoGPU3D_int:      # backend T = int
    cdef TopoGPU3D_int* gpu
    cdef PH3D_multiThread_int* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_int(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH3D_multiThread_int(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        self.gpu.configure(img, 3)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.int32)
        cdef int* ptr = <int*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU3D_int::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy3D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)
		
    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

cdef class PyTopoGPU3D_float:    # backend T = float
    cdef TopoGPU3D_float* gpu
    cdef PH3D_multiThread_float* ph

    def __cinit__(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_float(img, bndmat_num, bs, deviceID, debug, verbose)
        self.ph  = new PH3D_multiThread_float(True, False)

    def __dealloc__(self):
        if self.ph is not NULL:  del self.ph
        if self.gpu is not NULL: del self.gpu

    def configure(self, unsigned int imgX, unsigned int imgY, unsigned int imgZ):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        self.gpu.configure(img, 3)

    def compute_PH_from_file(self, filename, datatype):
        cdef string fn = _to_string(filename)
        cdef string dt = _to_string(datatype)
        self.gpu.run_frmFile(fn, dt, self.ph[0])
        self.ph.bndmat_reduction()
		
    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.float32)
        cdef float* ptr = <float*> buf.data

        self.gpu.run_frmArr(ptr, self.ph[0])   # C++: TopoGPU3D_float::run_frmArr
        self.ph.bndmat_reduction()

    def reset(self):
        self.ph.reset()

    def get_pairNum(self):
        return self.ph.return_pairNum()

    def get_results(self):
        return _results_to_numpy3D(self.ph.return_results(), self.ph.return_pairNum())
		
    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)
		
    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

# -------------------- Factory (Python) --------------------
def create2D(imgSize_x, imgSize_y, dtype, bndmat_num=2000, 
					 bx=0, by=0,
                     deviceID=-1, debug=False, verbose=False, ):
    """
    dtype rules:
      - 'uchar'  -> unsigned short backend (PyTopoGPU2D_ushort)
      - 'ushort' -> int backend            (PyTopoGPU2D_int)
      - 'int'    -> int backend            (PyTopoGPU2D_int)
      - 'float'  -> float backend          (PyTopoGPU2D_float)
    """
    s = str(dtype).lower()
    if s in ("uint8", "uchar"):
        return PyTopoGPU2D_ushort(imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("uint16", "ushort"):
        return PyTopoGPU2D_int(imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("int32", "int"):
        return PyTopoGPU2D_int(imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("float32", "float"):
        return PyTopoGPU2D_float(imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    else:
        raise TypeError("Unsupported dtype: %r (use uchar/ushort/int/float)" % (dtype,))
    
def create3D(imgSize_x, imgSize_y, imgSize_z, dtype, bndmat_num=2000, 
					 bx=0, by=0, bz=0,
                     deviceID=-1, debug=False, verbose=False, ):
    """
    dtype rules:
      - 'uchar'  -> unsigned short backend (PyTopoGPU3D_ushort)
      - 'ushort' -> int backend            (PyTopoGPU3D_int)
      - 'int'    -> int backend            (PyTopoGPU3D_int)
      - 'float'  -> float backend          (PyTopoGPU3D_float)
    """
    s = str(dtype).lower()
    if s in ("uint8", "uchar"):
        return PyTopoGPU3D_ushort(imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("uint16", "ushort"):
        return PyTopoGPU3D_int(imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("int32", "int"):
        return PyTopoGPU3D_int(imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("float32", "float"):
        return PyTopoGPU3D_float(imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    else:
        raise TypeError("Unsupported dtype: %r (use uchar/ushort/int/float)" % (dtype,))

# ============================================================================
#                              BATCH  BINDINGS
# ============================================================================

cdef extern from "topo_batch.cuh":
    ctypedef unsigned short ushort_

# -------------------- TopoGPU2D_Batch<T> specializations --------------------
cdef extern from "topo_batch.cuh" namespace "":
    cdef cppclass TopoGPU2D_Batch_ushort "TopoGPU2D_Batch<unsigned short>":
        TopoGPU2D_Batch_ushort(ushort_ batchSize, uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(unsigned short* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)          # rows x 7, float32
        void   reset()
        uint2  return_blockDims()
        uint2  return_chunkDims()

    cdef cppclass TopoGPU2D_Batch_int "TopoGPU2D_Batch<int>":
        TopoGPU2D_Batch_int(ushort_ batchSize, uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(int* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)
        void   reset()
        uint2  return_blockDims()
        uint2  return_chunkDims()

    cdef cppclass TopoGPU2D_Batch_float "TopoGPU2D_Batch<float>":
        TopoGPU2D_Batch_float(ushort_ batchSize, uint2 imgSize, uint_ bndmat_num, uint2 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(float* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)
        void   reset()
        uint2  return_blockDims()
        uint2  return_chunkDims()

# -------------------- TopoGPU3D_Batch<T> specializations --------------------
cdef extern from "topo_batch.cuh" namespace "":
    cdef cppclass TopoGPU3D_Batch_ushort "TopoGPU3D_Batch<unsigned short>":
        TopoGPU3D_Batch_ushort(ushort_ batchSize, uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(unsigned short* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)          # rows x 9, float32
        void   reset()
        uint3  return_blockDims()
        uint3  return_chunkDims()

    cdef cppclass TopoGPU3D_Batch_int "TopoGPU3D_Batch<int>":
        TopoGPU3D_Batch_int(ushort_ batchSize, uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(int* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)
        void   reset()
        uint3  return_blockDims()
        uint3  return_chunkDims()

    cdef cppclass TopoGPU3D_Batch_float "TopoGPU3D_Batch<float>":
        TopoGPU3D_Batch_float(ushort_ batchSize, uint3 imgSize, uint_ bndmat_num, uint3 blockSize, int deviceID, bool debug, bool verbose)
        void compute(const vector[string]& filenames, const string& datatype)
        void compute(float* src, ushort_ fileNum)
        uint_  fileNum()
        uint_  pairNum(uint_ fileIdx)
        float* result(uint_ fileIdx)
        void   reset()
        uint3  return_blockDims()
        uint3  return_chunkDims()

# -------------------- batch helpers --------------------
cdef inline vector[string] _to_string_vec(object filenames) except *:
    cdef vector[string] v
    for f in filenames:
        v.push_back(_to_string(f))
    return v

# -------------------- Python wrappers: 2D batch --------------------
# Results of compute_* are valid until the next compute_* call; get_results() returns copies.

cdef class PyTopoGPU2D_Batch_ushort:   # backend T = unsigned short
    cdef TopoGPU2D_Batch_ushort* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_Batch_ushort(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        # arr: (B, H, W), C-contiguous
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.uint16)
        if buf.ndim != 3:
            raise ValueError("expected a (B, H, W) array")
        cdef unsigned short* ptr = <unsigned short*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        """fileIdx given -> (N_f, 7) float32 copy; None -> list of copies for all files."""
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)

    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)

cdef class PyTopoGPU2D_Batch_int:   # backend T = int
    cdef TopoGPU2D_Batch_int* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_Batch_int(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.int32)
        if buf.ndim != 3:
            raise ValueError("expected a (B, H, W) array")
        cdef int* ptr = <int*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)

    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)

cdef class PyTopoGPU2D_Batch_float:   # backend T = float
    cdef TopoGPU2D_Batch_float* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint2 img = make_uint2c(imgX, imgY)
        cdef uint2 bs  = make_uint2c(bx, by)
        self.gpu = new TopoGPU2D_Batch_float(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.float32)
        if buf.ndim != 3:
            raise ValueError("expected a (B, H, W) array")
        cdef float* ptr = <float*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy2D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint2 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y)

    def get_chunkDims(self):
        cdef uint2 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y)

# -------------------- Python wrappers: 3D batch --------------------
cdef class PyTopoGPU3D_Batch_ushort:   # backend T = unsigned short
    cdef TopoGPU3D_Batch_ushort* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_Batch_ushort(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        # arr: (B, X, Y, Z) in the same memory order the single-volume run_frmArr expects, C-contiguous
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.uint16)
        if buf.ndim != 4:
            raise ValueError("expected a (B, X, Y, Z) array")
        cdef unsigned short* ptr = <unsigned short*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        """fileIdx given -> (N_f, 9) float32 copy; None -> list of copies for all files."""
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)

    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

cdef class PyTopoGPU3D_Batch_int:      # backend T = int
    cdef TopoGPU3D_Batch_int* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_Batch_int(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.int32)
        if buf.ndim != 4:
            raise ValueError("expected a (B, X, Y, Z) array")
        cdef int* ptr = <int*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)

    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

cdef class PyTopoGPU3D_Batch_float:    # backend T = float
    cdef TopoGPU3D_Batch_float* gpu

    def __cinit__(self, unsigned int batchSize, unsigned int imgX, unsigned int imgY, unsigned int imgZ,
                  uint_ bndmat_num, unsigned int bx=0, unsigned int by=0, unsigned int bz=0,
                  int deviceID=-1, bint debug=False, bint verbose=False):
        cdef uint3 img = make_uint3c(imgX, imgY, imgZ)
        cdef uint3 bs  = make_uint3c(bx, by, bz)
        self.gpu = new TopoGPU3D_Batch_float(<ushort_>batchSize, img, bndmat_num, bs, deviceID, debug, verbose)

    def __dealloc__(self):
        if self.gpu is not NULL: del self.gpu

    def compute_PH_from_files(self, filenames, datatype):
        cdef vector[string] fns = _to_string_vec(filenames)
        cdef string dt = _to_string(datatype)
        self.gpu.compute(fns, dt)

    def compute_PH_from_array(self, arr):
        cdef cnp.ndarray buf = np.ascontiguousarray(arr, dtype=np.float32)
        if buf.ndim != 4:
            raise ValueError("expected a (B, X, Y, Z) array")
        cdef float* ptr = <float*> buf.data
        self.gpu.compute(ptr, <ushort_>buf.shape[0])

    def reset(self):
        self.gpu.reset()

    def get_fileNum(self):
        return self.gpu.fileNum()

    def get_pairNum(self, unsigned int fileIdx):
        return self.gpu.pairNum(fileIdx)

    def get_results(self, fileIdx=None):
        cdef uint_ f
        if fileIdx is not None:
            f = <uint_>fileIdx
            return _results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy()
        out = []
        for f in range(self.gpu.fileNum()):
            out.append(_results_to_numpy3D(self.gpu.result(f), self.gpu.pairNum(f)).copy())
        return out

    def get_blockDims(self):
        cdef uint3 bs = self.gpu.return_blockDims()
        return (bs.x, bs.y, bs.z)

    def get_chunkDims(self):
        cdef uint3 cs = self.gpu.return_chunkDims()
        return (cs.x, cs.y, cs.z)

# -------------------- Factory (Python): batch --------------------
def create2D_batch(batchSize, imgSize_x, imgSize_y, dtype, bndmat_num=2000,
                   bx=0, by=0,
                   deviceID=-1, debug=False, verbose=False):
    """
    Same dtype rules as create2D. compute_PH_from_files(list_of_paths, datatype) /
    compute_PH_from_array((B,H,W) array); get_results() -> list of (N_f, 7) arrays.
    """
    s = str(dtype).lower()
    if s in ("uint8", "uchar"):
        return PyTopoGPU2D_Batch_ushort(batchSize, imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("uint16", "ushort"):
        return PyTopoGPU2D_Batch_int(batchSize, imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("int32", "int"):
        return PyTopoGPU2D_Batch_int(batchSize, imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    elif s in ("float32", "float"):
        return PyTopoGPU2D_Batch_float(batchSize, imgSize_x, imgSize_y, bndmat_num, bx, by, deviceID, debug, verbose)
    else:
        raise TypeError("Unsupported dtype: %r (use uchar/ushort/int/float)" % (dtype,))

def create3D_batch(batchSize, imgSize_x, imgSize_y, imgSize_z, dtype, bndmat_num=2000,
                   bx=0, by=0, bz=0,
                   deviceID=-1, debug=False, verbose=False):
    """
    Same dtype rules as create3D. compute_PH_from_files(list_of_paths, datatype) /
    compute_PH_from_array((B,X,Y,Z) array); get_results() -> list of (N_f, 9) arrays.
    """
    s = str(dtype).lower()
    if s in ("uint8", "uchar"):
        return PyTopoGPU3D_Batch_ushort(batchSize, imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("uint16", "ushort"):
        return PyTopoGPU3D_Batch_int(batchSize, imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("int32", "int"):
        return PyTopoGPU3D_Batch_int(batchSize, imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    elif s in ("float32", "float"):
        return PyTopoGPU3D_Batch_float(batchSize, imgSize_x, imgSize_y, imgSize_z, bndmat_num, bx, by, bz, deviceID, debug, verbose)
    else:
        raise TypeError("Unsupported dtype: %r (use uchar/ushort/int/float)" % (dtype,))