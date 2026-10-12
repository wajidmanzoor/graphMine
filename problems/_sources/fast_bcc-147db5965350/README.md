# Fast-BCC on GPUs

This repository accompanies the paper:

**“GPU Algorithms for Biconnected Components on Large Graphs”**
Published in **IPDPS 2026**.

It contains GPU implementations of the **Fast-BCC** family of algorithms for computing **biconnected components (BCCs)** on large-scale graphs.

Our work presents the **first GPU BCC algorithm that uses an arbitrary spanning tree instead of a BFS tree**, eliminating the sequential bottlenecks inherent in BFS-based approaches.

We provide:

* **Fast-BCC-Filter** – Optimized for graphs that fit entirely in GPU memory.
* **PEA-BCC** – External-memory version for graphs that do not fit in GPU memory.
* Baseline implementations for comparison.

For full algorithmic details, please refer to the paper.

---

## Project Structure

```
.
├── baselines/              # Baseline implementations for comparison
│   ├── cpu/                # Multicore Fast-BCC (CPU implementation)
│   ├── uvm/                # GPU Fast-BCC using Unified Virtual Memory
│   ├── wk-bcc-2017/        # Wadekar-Kothapalli BCC (2017 IC3)
│   └── wk-bcc-2018/        # Wadekar-Kothapalli BCC (2018 HiPC)
│
├── depth/                  # Approximate diameter computation using serial BFS
├── external/               # For graphs that do NOT fit in GPU memory
│   ├── streams/            # Version with CUDA streams (overlap copy & compute)
│   └── without_streams/    # Version without CUDA streams
│
└── in-memory/              # For graphs that fit entirely in GPU memory
    ├── with_filter/        # Fast-BCC-Filter (proposed method)
    └── without_filter/     # GPU adaptation of multicore Fast-BCC
```

---

## Building

### Build All Projects

From the root directory:

```bash
make
```

This builds all subprojects.

---

### Build Individual Components

Each subdirectory contains its own Makefile:

```bash
cd <directory>
make
```

Example:

```bash
cd in-memory/with_filter
make
```

---

### Clean Build Artifacts

```bash
make clean
```

---

## Datasets

For quick validation, small test graphs
(#vertices < 100, #edges < 10,000) are available in:

```
datasets/
```

The full datasets used in the paper experiments are publicly available.
Where necessary, we:

* Converted graphs to undirected form
* Removed self-loops
* Added minimal edges to ensure a single connected component

The basic experimental datasets can be downloaded from:

 [FAST-BCC-Dataset](https://tinyurl.com/fast-BCC-Filter-datasets)

---

## Input Graph Format

All implementations expect graphs in **edge list format**:

```
num_vertices num_edges
u1 v1
u2 v2
...
```

* Vertices are **0-indexed**
* Each line represents an undirected edge
* Either include both (u, v) and (v, u), or only one — the implementation handles both

---

## Running

### Quick Start – Run Everything

From the root directory:

```bash
bash run_all.sh
```

This builds and runs all implementations on available datasets.

Optional configuration:

```bash
CPU_ROUNDS=5 BATCH_SIZE=500000 bash run_all.sh
```

---

## Individual Implementations

### 1. CPU Baseline (Multicore Fast-BCC)

```bash
cd baselines/cpu/src
./FAST_BCC <graph_file> [num_rounds]
```

Example:

```bash
./FAST_BCC ../../../datasets/input.txt 3
```

---

### 2. Wadekar–Kothapalli BCC (2017)

```bash
cd baselines/wk-bcc-2017
./bin/cuda_bcc -i <graph_file> -a ebcc [-o output_dir] [-d device]
```

Options:

* `-a`: Algorithm (`cv`, `ce`, `ibcc`, `ebcc`)
* `-o`: Output directory
* `-d`: CUDA device (default: 0)

---

### 3. Wadekar–Kothapalli BCC (2018)

```bash
cd baselines/wk-bcc-2018
./bin/main <graph_file> [k] [verbose]
```

---

### 4. Fast-BCC-Filter (In-Memory, Proposed)

```bash
cd in-memory/with_filter
./main <graph_file>
```

---

### 5. GPU Without Filter (In-Memory)

```bash
cd in-memory/without_filter
./main <graph_file>
```

---

### 6. External Memory – With Streams (PEA-BCC)

```bash
cd external/streams
./ext-bcc <graph_file> <batch_size>
```

---

### 7. External Memory – Without Streams

```bash
cd external/without_streams
./ext-bcc <graph_file> <batch_size>
```

---

### 8. Graph Diameter (Depth BFS)

```bash
cd depth
./bfs <graph_file> [source_vertex]
```

---

## Requirements

* NVIDIA CUDA Toolkit (≥ 11.0 recommended)
* C++ compiler with C++17 support
* CUDA-capable GPU (compute capability ≥ 7.0 recommended)
* ParlayLib (included as submodule for CPU baseline)

---

## Troubleshooting

### CUDA Architecture Errors

Update the `-arch` flag in the Makefile:

```makefile
CXXFLAGS += -arch=sm_XX
```

Replace `XX` with your GPU’s compute capability.

---

### Out-of-Memory Issues

For large graphs:

* Use `external/streams` or `external/without_streams`
* Adjust:

  * `GPU_SHARE`
  * `BATCH_SIZE`

---

### CUDA Not Found

```bash
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
```

---

## Contact

For questions, issues, or collaboration inquiries:

**Abhijeet Kumar**

📧 [cs22s501@iittp.ac.in](mailto:cs22s501@iittp.ac.in)

📧 [abhijeetkumar.071@gmail.com](mailto:abhijeetkumar.071@gmail.com)

Alternatively, please open a GitHub issue for technical discussions or bug reports.

### To open a GitHub Issue, please include:

* GPU model
* CUDA version (`nvcc --version`)
* Graph size (#vertices, #edges)
* Full error message
