#!/usr/bin/env bash
# Usage inside the container:  bash scripts/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

GENCODE=(-gencode arch=compute_61,code=sm_61 -gencode arch=compute_75,code=sm_75
         -gencode arch=compute_80,code=sm_80 -gencode arch=compute_86,code=sm_86
         -gencode arch=compute_89,code=sm_89 -gencode arch=compute_90,code=sm_90
         -gencode arch=compute_90,code=compute_90)                 # PTX for future GPUs
HOST="-fopenmp -O3 -DNDEBUG -march=x86-64-v2"                      # portable, no -march=native
INC="-I. -Isrc -Ithird_party -Ithird_party/phat/include -I/usr/local/cuda/include"
CU="morse_boundary morse_matching topo topo_batch util_cu"

echo "== [1/3] C++ command-line binary -> build/topoGPU"
mkdir -p build
nvcc -O3 -use_fast_math -std=c++17 -DENABLE_THRUST=1 -Xcompiler "$HOST" "${GENCODE[@]}" $INC \
     src/fileIO.cpp src/main.cpp src/util.cpp $(for f in $CU; do echo src/$f.cu; done) \
     -lcudart -o build/topoGPU

echo "== [2/3] CUDA objects for the Python extension (built once, Python-independent)"
mkdir -p build-python dist-raw dist
for f in $CU; do
  nvcc -O3 -use_fast_math -std=c++17 -DENABLE_THRUST=1 -Xcompiler "-fPIC $HOST" "${GENCODE[@]}" $INC \
       -c src/$f.cu -o build-python/$f.o
done

echo "== [3/3] One wheel per Python version, then make them manylinux"
rm -f dist-raw/* dist/*
for v in 3.10 3.11 3.12 3.13; do
  PY="$(uv python find $v)"
  "$PY" -m build --wheel --no-isolation -o dist-raw
done
for w in dist-raw/*.whl; do
  python -m auditwheel repair --plat manylinux_2_28_x86_64 \
      --exclude libcudart.so.12 -w dist "$w"       # cudart comes from pip, don't vendor it
done
echo "== done:"; ls -1 dist/