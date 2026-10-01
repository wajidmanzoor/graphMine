# Build
Load the conda environment mayura with,
```
conda activate mayura
```

First change line 5-7 in `CMakeLists.txt`, such that they are pointing to your compilers.
If there a problem during compilation, see Troubleshooting section.

Then use the following commands to build the system
```
mkdir build && cd build
cmake ..
make -j
```

The code assumes the GPUs support `SM86`.
If they do not, change all the places with `SM86`, `sm_86` and any other related things to the supported architecture number.
- line 28, 29, 82 in `CMakeLists.txt`
- line 24 in `system/tmin/utils.py`

Look up the number here: https://developer.nvidia.com/cuda-gpus#compute

# Prepare Inputs
Please follow the README in `inputs` directory.

# Running Experiments

To run all the experiments, go to system/.

For the baseline experiments run,
```
python3 run_OG_exp.py
```

For the co-mining experiments run,
```
python3 run_exp_new.py
```