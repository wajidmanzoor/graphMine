# Installation

## Requirements
- Linux x86_64, NVIDIA GPU with driver ≥ 525
- Python 3.10 – 3.13

## Wheels (pip)
Pick the wheel for your Python version from the
[Releases page](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/releases):
```bash
pip install https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/releases/download/v2.0.0/topogpu-2.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
python -c "import topogpu; print('ok')"
```
The CUDA runtime is installed automatically as a pip dependency.

## Google Colab
Open the demo notebook and set the runtime to GPU:
[TopoGPU_demo.ipynb](https://colab.research.google.com/github/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data/blob/main/examples/TopoGPU_demo.ipynb)

## Docker
```bash
docker pull seravee08/topogpu:v2.0.0
docker run --rm -it --gpus all -p 8888:8888 -v /path/to/data:/data seravee08/topogpu:v2.0.0
```

## From source
See the [README](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data#4%EF%B8%8F%E2%83%A3-compile-from-source).