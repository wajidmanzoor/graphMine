# HGNN-Part: A High-Quality Hypergraph Partitioner Based on Hypergraph Generative Model

[![Python 3.10.16](https://img.shields.io/badge/python-3.10.16-blue.svg)](https://www.python.org/downloads/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0.1-red.svg)](https://pytorch.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

HGNN-Part is a deep learning framework for hypergraph partitioning that leverages Variational Graph Autoencoders (VGAE) with hypergraph convolutions. This project provides an end-to-end solution for partitioning large-scale hypergraphs, commonly used in VLSI circuit design, using graph neural networks to learn optimal partition assignments while minimizing cut size and maintaining balance constraints.

### Key Features

- **Deep Learning-Based Partitioning**: Uses Variational Graph Autoencoders (VGAE) with specialized hypergraph convolutions
- **Multi-Objective Optimization**: Simultaneously optimizes for minimum cut, partition balance, and reconstruction quality
- **Scalable Architecture**: Handles large-scale hypergraphs with thousands of nodes and hyperedges
- **Flexible Framework**: Supports both graph and hypergraph inputs with configurable model architectures
- **Integration with Traditional Methods**: Can be combined with traditional partitioners (KaHyPar, hMETIS) for refinement

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Dataset Format](#dataset-format)
- [Model Architecture](#model-architecture)
- [Training](#training)
- [Evaluation](#evaluation)
- [Project Structure](#project-structure)
- [Configuration](#configuration)

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/THU-numbda/HGNN-Part.git
cd HGNN-Part
```

### Step 2: Create Virtual Environment (Recommended)

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Prepare Your Data

Place your hypergraph files (`.hgr` format) in the `data/` directory. The project includes ISPD benchmark circuits (ibm01-ibm18) for testing.

### 2. Train a Model

```bash
python train.py --lr 5e-4 --epochs 50 --latent_dim 64 --hidden_dim 256
```

### 3. Test the Model

```bash
python test.py --filename ibm02.hgr --modelname model.pt --use_sketch
```

### 4. Batch Testing

```bash
bash script.sh  # Tests on all IBM98 benchmark circuits
```

## Dataset Format

### Hypergraph Format (.hgr)

The project uses the standard hypergraph format:

```
<num_hyperedges> <num_nodes>
<node_1_of_edge_1> <node_2_of_edge_1> ...
<node_1_of_edge_2> <node_2_of_edge_2> ...
...
```

Example:
```
3 4
1 2 3
2 4
1 3 4
```

This represents a hypergraph with 4 nodes and 3 hyperedges.

### PyTorch Geometric Format

For training, hypergraphs are converted to PyTorch Geometric `HyperData` objects with:
- `x`: Node features (7-dimensional by default)
- `hyperedge_index`: Sparse representation of hyperedge connections

## Model Architecture

### Core Components

1. **VariationalEncoder**: 
   - Multi-layer hypergraph convolutions
   - Masked node feature learning (20% masking during training)
   - Outputs mean (μ) and standard deviation (σ) for latent distribution

2. **PartitionDecoder**:
   - MLP-based decoder
   - Maps latent representations to partition assignments
   - Softmax output for probabilistic partition assignment

3. **Loss Functions**:
   - **KL Divergence Loss**: Regularizes the latent space
   - **Normalized Cut Loss**: Minimizes hyperedge cuts
   - **Balance Loss**: Ensures balanced partition sizes
   - Combined loss: `α * KL + β * NCut + γ * Balance`

### Model Variants

- **GraphPartitionModel**: Standard VGAE with configurable depth
- **NewVariationalEncoder**: Enhanced version with LayerNorm and residual connections

## Training

### Basic Training

```bash
python train.py \
    --lr 5e-4 \
    --alpha 5e-4 \      # KL loss weight
    --beta 0.5 \        # Normalized cut loss weight
    --gamma 100 \       # Balance loss weight
    --epochs 50 \
    --latent_dim 64 \
    --hidden_dim 256 \
    --cuda 0
```

### Training Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--lr` | 5e-4 | Learning rate |
| `--alpha` | 5e-4 | KL divergence loss weight |
| `--beta` | 0.5 | Normalized cut loss weight |
| `--gamma` | 100 | Balance loss weight |
| `--epochs` | 50 | Number of training epochs |
| `--latent_dim` | 64 | Latent space dimensionality |
| `--hidden_dim` | 256 | Hidden layer dimensionality |
| `--cuda` | 0 | GPU device ID |

### Training Features

- **Early Stopping**: Automatically stops when validation loss plateaus
- **Best Model Saving**: Saves the model with minimum normalized cut loss
- **Memory Monitoring**: Tracks peak GPU memory usage
- **Loss Tracking**: Monitors individual loss components

## Evaluation

### Single File Testing

```bash
python test.py \
    --filename ibm02.hgr \
    --modelname model.pt \
    --num_partitions 2 \
    --latent_dim 64 \
    --hidden_dim 256 \
    --use_sketch \      # Enable sketch-based preprocessing
    --cuda 0
```

### Evaluation Metrics

- **Cutsize**: Number of hyperedges cut by the partition
- **Imbalance**: Deviation from perfectly balanced partitions
- **Runtime**: Preprocessing, inference, and refinement times

### Multi-Sample Inference

The test script performs:
1. Initial partitioning with spectral methods
2. Multiple samples from the learned model (default: 12 samples per iteration)
3. V-Cycle refinement using traditional partitioners
4. Iterative improvement over multiple rounds (default: 11 iterations)

## Project Structure

```
HGNN-Part/
├── config.py           # Path configuration and management
├── models.py           # Neural network architectures
├── train.py            # Training script
├── test.py             # Evaluation script
├── utils.py            # Utility functions (preprocessing, evaluation)
├── script.sh           # Batch testing script
├── requirements.txt    # Python dependencies
├── data/               # Hypergraph datasets (.hgr files)
│   ├── ibm01.hgr
│   ├── ibm02.hgr
│   └── ...
├── exec/              # External partitioning tools
│   ├── KaHyPar
│   ├── hmetis
│   └── ...
└── models/            # Saved model checkpoints
```

## Configuration

### Path Configuration (config.py)

The project uses a centralized path configuration system:

```python
from config import paths

# Access data files
data_file = paths.get_data_path("ibm01.hgr")

# Access model files
model_file = paths.get_model_path("model.pt")

# Access partition files
partition_file = paths.get_partition_file_path("ibm01", suffix="part.2")
```

### Model Configuration

Models are saved with configuration in filename:
```
model.<lr>.<alpha>.<beta>.<gamma>.<latent_dim>.<hidden_dim>.pt
```

Example: `model.5e-04.5e-04.5e-01.1e+02.64.256.pt`

## Publication

[1] Shengbo Tong, Rufan Zhou, Chunyan Pei, and Wenjian Yu, "HGNN-Part: A high-quality hypergraph partitioner based on hypergraph generative model," in Proc. Design, Automation & Test in Europe Conference (DATE), Verona, Italy, Apr. 2026.
