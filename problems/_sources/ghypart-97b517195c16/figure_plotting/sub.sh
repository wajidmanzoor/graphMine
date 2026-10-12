#!/bin/bash
#SBATCH -p queue
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 48
module load anaconda/3-Python-3.8.3-phonopy-phono3py
source activate py310
export PYTHONUNBUFFERED=1
python run-bipart.py
