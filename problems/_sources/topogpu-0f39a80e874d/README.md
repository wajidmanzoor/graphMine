# TopoGPU: GPU-Accelerated Computation of Persistent Homology for Image Data

[![Documentation Status](https://app.readthedocs.org/projects/gpu-computation-of-persistent-homology-for-image-data/badge/?version=latest)](https://gpu-computation-of-persistent-homology-for-image-data.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/github/license/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data)](LICENSE)
[![Release](https://img.shields.io/github/v/release/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data)](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/releases)
[![build-wheels](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/actions/workflows/wheels.yml/badge.svg)](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/actions/workflows/wheels.yml)
[![Docker](https://img.shields.io/docker/v/seravee08/topogpu?label=docker)](https://hub.docker.com/r/seravee08/topogpu)
[![Code Ocean](https://img.shields.io/badge/Code%20Ocean-reproducible%20capsule-2b6cb0?logo=codeocean&logoColor=white)](https://codeocean.com/capsule/d7f31487-b169-4cc0-a4e0-73b487cffe60/)
[![Paper](https://img.shields.io/badge/TPAMI-10.1109%2FTPAMI.2026.3741473-blue)](https://doi.org/10.1109/TPAMI.2026.3741473)

CUDA-accelerated persistent homology for 2D/3D image data using cubical complexes. TopoGPU streams the input chunk by chunk through the GPU (Morse matching, parallel topological sorting, parallel path-parity computation) and reduces the resulting boundary matrix on the CPU, achieving large speedups over CPU tools such as Cubical Ripser while supporting inputs larger than GPU memory.

> **📖 Documentation:** the full user guide and Python API reference (installation, quick start, batch mode, 2D/3D API, command-line tool) is available at **https://gpu-computation-of-persistent-homology-for-image-data.readthedocs.io/**

## 📄 Paper
This repository is the official implementation of:

> Fan Wang, Hubert Wagner, Rezaul Chowdhury, and Chao Chen, **"GPU-Accelerated Computation of Persistent Homology for Topological Analysis of Image Data,"** *IEEE Transactions on Pattern Analysis and Machine Intelligence*, 2026 (accepted). DOI: [10.1109/TPAMI.2026.3741473](https://doi.org/10.1109/TPAMI.2026.3741473)

The paper will appear on IEEE Xplore (Early Access) shortly; an author-accepted preprint will be posted on arXiv.

- 📰 IEEE Xplore: https://doi.org/10.1109/TPAMI.2026.3741473
- 📝 arXiv: http://arxiv.org/abs/2610.10959
- 📚 Supplementary material: *[link coming soon]*
- 🧪 Code Ocean reproducible capsule: https://codeocean.com/capsule/d7f31487-b169-4cc0-a4e0-73b487cffe60/

If you use TopoGPU in your research, please cite:
```bibtex
@article{wang2026topogpu,
  author  = {Wang, Fan and Wagner, Hubert and Chowdhury, Rezaul and Chen, Chao},
  title   = {GPU-Accelerated Computation of Persistent Homology for Topological Analysis of Image Data},
  journal = {IEEE Transactions on Pattern Analysis and Machine Intelligence},
  year    = {2026},
  doi     = {10.1109/TPAMI.2026.3741473}
}
```

## 1️⃣ Google Colab

We provide a **TopoGPU_demo** notebook on Google Colab that demonstrates how to use TopoGPU (set the runtime's hardware accelerator to GPU).

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/blob/main/examples/TopoGPU_demo.ipynb)

Prefer a fully reproducible environment? The same demo is published as a [Code Ocean capsule](https://codeocean.com/capsule/d7f31487-b169-4cc0-a4e0-73b487cffe60/) that runs on a cloud GPU with one click.

The notebook provides a step-by-step workflow:

1. **Environment setup**
   - Installs the precompiled `topogpu` wheel matching Colab's Python version.
   - Installs `cripser` (which provides the `tcripser` interface).

2. **Data loading**
   - Downloads sample 3D grayscale volumes (`.raw`) from this repository.

3. **Running TopoGPU**
   - Demonstrates `topogpu.create3D(...)` and explains its key parameters.
   - Runs persistent homology on the sample volumes from files and from NumPy arrays and retrieves the resulting pairs.

4. **Batch mode**
   - Demonstrates `topogpu.create2D_batch(...)`, processing many same-sized images per call from arrays and from files.

5. **Running Cubical Ripser (tcripser)**
   - Computes persistence with `tcripser.computePH(...)` on the same volume.

6. **Result comparison**
   - Compares TopoGPU and Cubical Ripser outputs (up to 3 decimal places) and reports any persistence pairs that differ.

## 2️⃣ Docker Image

The image `seravee08/topogpu:v2.0.0` (alias `latest`) contains the pre-built C++ binary, all source files, the build scripts, a CUDA 12.6 toolchain, Python 3.10–3.13 and Jupyter, so you can run, rebuild, or develop TopoGPU without installing anything on the host.

### 📌 Prerequisites
**Windows 10/11**
- Docker Desktop with WSL 2 backend enabled.
- NVIDIA GPU + up-to-date Windows NVIDIA driver (≥ 525).
- User in the local `docker-users` group.
- Verify in Windows PowerShell: ```docker run --rm --gpus=all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi```

**Linux**
- NVIDIA GPU + driver (≥ 525) installed on the host.
- NVIDIA Container Toolkit installed and configured for Docker.
- Verify: ```docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi```

### 📌 Run Docker
**Windows 10/11**
- Pull image: ```docker pull seravee08/topogpu:v2.0.0```
- Create container and enter shell (replace `PATH_TO_DATA` with an absolute Windows path):
```command
docker run --name topogpu -it --gpus=all -p 8888:8888 `
  --mount type=bind,source="PATH_TO_DATA",target=/data `
  seravee08/topogpu:v2.0.0
```

**Linux**
- Pull image: ```docker pull seravee08/topogpu:v2.0.0```
- Create container and enter shell (replace `/abs/path/to/data` with your absolute path):
```command
docker run --name topogpu -it --gpus all -p 8888:8888 \
  -v /abs/path/to/data:/data \
  seravee08/topogpu:v2.0.0
```
- Re-enter the container later: ```docker start -ai topogpu```

### 📌 Inside the container
The shell starts in `/opt/topogpu`.

- Run the C++ binary on your data (write outputs to `/data` so they persist on the host):
```
./build/topoGPU -help
./build/topoGPU -filename /data/mrt_angio_416x512x112_uint16.raw -datatype ushort -height 512 -width 416 -depth 112 -bufSize 3000 -out /data/result.txt
```
- Use the Python module: install the wheel for the container's default Python (3.12) as in Section 3, then run the notebooks in `examples/` with Jupyter (open `http://localhost:8888` on the host):
```
jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root --NotebookApp.token='' --NotebookApp.password=''
```
- Rebuild the binary and the wheels from source: ```bash scripts/build.sh``` (see Section 4).

### 📌 Common failure messages
- `readArrayFromBin: failure!` — the input file path is wrong or not mounted at `/data`. Verify your host path and the `-v`/`--mount` mapping.
- `Error: boundary matrix buffer limit reached...` — increase the per-block buffer, e.g. `-bufSize 3000` (default 2000). Noisy or high-detail data needs larger values.

## 3️⃣ Python Module

Pre-built wheels of TopoGPU are available for **Python 3.10–3.13 on Linux x86_64** (manylinux_2_28; works on Ubuntu, Rocky/RHEL, conda environments, and Google Colab). The CUDA runtime is installed automatically as a pip dependency; the only host requirement is an NVIDIA driver (≥ 525).

### 📌 Install
Pick the wheel matching your Python version from the [Releases page](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/releases) (`cp310` = Python 3.10, `cp311` = 3.11, …) and install it with pip, e.g. for Python 3.12:
```
pip install https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/releases/download/v2.0.0/topogpu-2.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
```
Verify:
```
python -c "import topogpu; print(topogpu.__file__)"
```

### 📌 Usage
See the Google Colab notebook in [Section 1](#1️⃣-google-colab) for complete examples: single-image / single-volume computation from files and NumPy arrays, batch mode for processing many same-sized images per call, and validation against Cubical Ripser. The full API reference is in [`docs/PYTHON_API.md`](docs/PYTHON_API.md).

## 4️⃣ Compile from Source

### 📌 Linux (native, without Docker)
**Dependencies**
- NVIDIA driver ≥ 525 and CUDA Toolkit 12.x (`nvcc` on `PATH`, `CUDA_HOME=/usr/local/cuda`)
- GCC ≥ 11 with OpenMP (`build-essential`, `libgomp1`)
- CMake ≥ 3.24 (binary only) — or, for wheels, Python ≥ 3.10 with `pip`, and [`uv`](https://docs.astral.sh/uv/) to build for several Python versions (`curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.10 3.11 3.12 3.13`)
- Python build tools: `pip install "cython>=3.0.11" "numpy>=2.1" setuptools wheel build auditwheel patchelf`

**Build the C++ binary (CMake)**
```
git clone https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data.git
cd GPU-Computation-of-Persistent-Homology-for-Image-Data
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES="89"
cmake --build build -j
./build/topoGPU -help
```
Set `CMAKE_CUDA_ARCHITECTURES` to your GPU (`61` Pascal, `75` Turing, `80`/`86` Ampere, `89` Ada, `90` Hopper) or omit it to build for all.

**Build the binary and the Python wheels**
```
bash scripts/build.sh
```
`scripts/build.sh` compiles the C++ binary to `build/topoGPU`, then builds one Python wheel per installed Python version into `dist/` (3.10–3.13 by default; edit the version list in the script to build fewer). Install a wheel with `pip install dist/topogpu-2.0.0-cp3XX-*.whl`.

### 📌 Windows 10/11 (native, CMake + Visual Studio)
Only the C++ binary is built on Windows; the Python wheels are Linux-only (use WSL 2 or the Docker image for the Python module).

**Dependencies**
- Visual Studio 2022 with the *Desktop development with C++* workload
- CUDA Toolkit 12.x (installed with Visual Studio integration)
- CMake ≥ 3.24 (bundled with Visual Studio, or from cmake.org)
- NVIDIA driver ≥ 525

**Build** (Developer PowerShell for VS 2022, from the repository root)
```
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_CUDA_ARCHITECTURES="89"
cmake --build build --config Release
```
The first command also writes `build\topoGPU.sln`, which you can open in Visual Studio instead of using the second command.

**Run**
```
build\Release\topoGPU.exe -help
build\Release\topoGPU.exe -filename data\lobster_301x324x56_uint8.raw -datatype uchar -height 324 -width 301 -depth 56 -bufSize 3000 -out result.txt
```

## 5️⃣ License and Third-Party Code
TopoGPU is released under the [MIT License](LICENSE). It bundles [PHAT](https://bitbucket.org/phat-code/phat) (LGPL-3.0), [CTPL](https://github.com/vit-vit/CTPL) (Apache-2.0) and [stb_image](https://github.com/nothings/stb) (MIT) under `third_party/`; see [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

## Acknowledgments
TopoGPU was developed by Fan Wang in collaboration with Hubert Wagner, Rezaul Chowdhury, and Chao Chen. We thank Hubert Wagner for valuable discussions that informed the design of this work. This work was supported in part by NSF Grants CCF-2318633 and CCF-2144901 and NIH Grants R01NS143143 and R01CA297843.
