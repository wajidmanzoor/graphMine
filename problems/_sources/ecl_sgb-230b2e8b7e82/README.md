# ECL-SGB: Signed Graph Balancing in Linear Time

ECL-SGB is a fast and work-efficient algorithm for balancing signed graphs. This repository hosts our CUDA implementation of the algorithm for GPUs. A full description of the algorithm can be found in our paper (see below).

If you use ECL-SGB, please cite the following publication:

>Avery VanAusdal, Lucas Rusnak, and Martin Burtscher. "Signed Graph Balancing in Linear Time." Proceedings of the 18th Workshop on General Purpose Processing Using GPUs. March 2026. <!--[[doi]]()-->[[abstract]](https://userweb.cs.txstate.edu/~burtscher/abstracts.html#GPGPU26) [[PDF]](https://userweb.cs.txstate.edu/~burtscher/papers/gpgpu26.pdf)

### Compilation

The code can be compiled as follows:

    make

To target a specific GPU architecture for best performance, replace DEVICE_CC in the Makefile with the appropriate [Compute Capability](https://developer.nvidia.com/cuda-gpus).

### Execution

The code takes the following positional arguments:

    ./eclsgb <input_graph_path> <tree_count> <output_file_name> 

* input_graph_path: path to input graph in edge list format
* tree_count: the number of trees to be sampled (1000 recommended)
* output_file_name: prefix of the name of the output CSVs containing the vertex and edge metrics

### Input graphs

ECL-SGB operates on graphs stored in edge list format. It expects a starting index of 0 and integer weights from -1 to 1. A weight of 0 is interpreted as positive.

To download and prepare the inputs used in the paper, run `bash ./download_paper_inputs.sh`. The preprocessing scripts require Python. The processed inputs take around 2.8 GB of storage and will be stored in `./paper_inputs/`. Additional Amazon review graphs can be acquired [here](https://nijianmo.github.io/amazon/index.html).


*This work has been supported in part by the National Science Foundation under Award #1955367 and by an equipment donation from NVIDIA Corporation.*