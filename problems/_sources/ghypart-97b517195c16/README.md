# gHyPart_TACO
This is the source code repo for the original work "gHyPart: GPU-friendly End-to-End Hypergraph Partitioner" accepted by ACM TACO.

# Benchmarks
The benchmark set used in our work is available on [zenodo](https://zenodo.org/records/14822691) and can also be downloaded from [here](https://hkustgz-my.sharepoint.com/:u:/g/personal/zwu065_connect_hkust-gz_edu_cn/EUE2L_acRZdOsALyzbGZ018Bg-KzptQwsxrokg5ws9z3zA?e=CZ2CeA).

# Build CPU Baseline Works
`git clone --recurse-submodules https://github.com/zlwu92/gHyPart_TACO.git`

`cd cpu_works/BiPart/` and `cd cpu_works/Mt-KaHyPar-SDet/`

`mkdir build && cd build/`

`cmake .. -DCMAKE_BUILD_TYPE=RELEASE`

`make bipart-cpu -j` and `make MtKaHyPar -j`

# Build gHyPart
Go to gHyPart's root dir.

`mkdir build && cd build/ && cmake ..`

`make -j`

# Run experiments
Go to `scripts/` folder and use `python run-xxx.py` to run all experiments.

# Plot figures in paper
Go to `figure_plotting` folder and run all scripts, you can get the figures plotted in paper. 
