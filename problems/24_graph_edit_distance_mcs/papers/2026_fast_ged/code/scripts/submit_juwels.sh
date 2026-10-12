#!/bin/bash
#SBATCH --job-name=fast-ged_%j
#SBATCH --output=slurm_result/job__%j.out
#SBATCH --account=...
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=1
#SBATCH --time=06:00:00
#SBATCH --partition=booster#gpus#develbooster

# Load necessary modules
module load Stages
module load networkx
module load Java
module load NVHPC
module load Python
module load OpenMPI
module load CUDA
module load matplotlib
module load UnZip


python py_scripts/networkx_ged.py 10000000 10
