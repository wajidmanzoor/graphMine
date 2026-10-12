# MG-MIS v1.0

MG-MIS is a fast single-node multi-GPU (CUDA) implementation for computing maximal independent sets (MIS) in large undirected graphs. The algorithm is optimized for graphs that do not fit in the global memory of a single GPU but fit in the combined global memory of all GPUs in a compute node. MG-MIS operates on graphs stored in binary CSR format.


## Input generation

### Generate inputs using Graph500

Download the code from `https://github.com/graph500/graph500`.

Navigate to the `src` directory and compile the code:

```
  cd src
  make
```

Ensure that `mpicc` is installed and the path to `openmpi` is specified in the `PATH` and `LD_LIBRARY_PATH` environment variables.

Run the code:

```
  ./graph500_reference_bfs <scale> <edgefactor> graph.txt
```

#### Clean the generated graphs (remove self-loops and duplicate edges)

Compile the code:
```
  g++ -O3 clean_graph500.cpp -o clean
```

Run the code:
```
  ./clean graph.txt graph.egr
```

### Generate inputs using Indigo3

Follow the instructions at `https://github.com/burtscher/Indigo3Suite`.


## Using MG-MIS

The MG-MIS CUDA code consists of the source files MG-MIS_10.cu and ECLgraph.h, located in the root directory of this repository. See the paper listed below for a description of MG-MIS. Note that MG-MIS is protected by the 3-Clause BSD license.

The MG-MIS code can be compiled as follows:
```
  nvcc -O3 -arch=sm_70 -Xcompiler -fopenmp MG-MIS_10.cu -o mis
```

To compute a MIS of the input file `graph.egr`, enter:
```
  ./mis graph.egr <number of GPUs>
```


## Publication

Anju Mongandampulath Akathoott, Benila Virgin Jerald Xavier, and Martin Burtscher. "A Multi-GPU Algorithm for Computing Maximal Independent Sets in Large Graphs." Proceedings of the 2025 ACM International Conference on Supercomputing. June 2025. [pdf](https://userweb.cs.txstate.edu/~mb92/papers/ics25.pdf)

**Summary**: MG-MIS is a single-node multi-GPU algorithm for computing maximal independent sets in large graphs. It is particularly useful when the graphs do not fit in the global memory of a single GPU. It distributes the graph and the computation among the GPUs in a compute node and applies novel techniques to minimize inter-GPU communication. Key features such as dividing the computation into mutually exclusive local and remote phases, employing data transfers only in bulk mode, and avoiding the communication of priority values altogether make MG-MIS very efficient for computing maximal independent sets in large graphs.

*This work has been supported in part by the National Science Foundation under Award Number 1955367.*
