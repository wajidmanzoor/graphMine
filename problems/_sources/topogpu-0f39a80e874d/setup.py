import os, numpy as np
from setuptools import setup, Extension
from Cython.Build import cythonize

CUDA_HOME = os.environ.get("CUDA_HOME", "/usr/local/cuda")
OBJS = [f"build-python/{f}.o" for f in ("morse_boundary", "morse_matching", "topo", "topo_batch", "util_cu")]

ext = Extension(
    name="topogpu",
    sources=["python/topogpu.pyx", "src/fileIO.cpp", "src/util.cpp"],
    language="c++",
    include_dirs=["src", "third_party", "third_party/phat/include", f"{CUDA_HOME}/include", np.get_include()],
    library_dirs=[f"{CUDA_HOME}/lib64"],
    libraries=["cudart"],
    define_macros=[("ENABLE_THRUST", "1")],
    extra_compile_args=["-O3", "-std=c++17", "-fopenmp", "-march=x86-64-v2"],
    extra_link_args=["-fopenmp", "-Wl,-rpath,$ORIGIN/nvidia/cuda_runtime/lib"],  # find pip-installed libcudart
    extra_objects=OBJS,
)
setup(ext_modules=cythonize([ext], language_level="3"))