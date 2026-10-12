# graphB+
graphB+ is a balancing algorithm for signed social network graphs. It operates on graphs stored in CSV format. A sample input graph is available in graph.csv.

graphBplus_02.cu contains the CUDA code and graphBplus_02.cpp contains the OpenMP C++ code (with g++ intrinsics).

The CUDA code can be compiled as follows:

`  nvcc -O3 -arch=sm_70 graphBplus_02.cu -o graphBplus`

The OpenMP C++ code can be compiled as follows:

`  g++ -O3 -march=native -fopenmp graphBplus_02.cpp -o graphBplus`

To run the code on the input file graph.csv with 100 samples and save the results of the balanced solutions in out.csv, enter:

`  ./graphBplus graph.csv 100 out.csv`

To obtain the inputs used in the publication listed below and convert them to our format, download the file input_script.sh from this repository and run it. Note that this script takes about an hour to run and requires a large amount of disk space.

This work has been supported in part by the National Science Foundation under Award Number 1955367, by the Department of Energy, National Nuclear Security Administration under Award Number DE-NA0003969, and by a hardware donation from NVIDIA Corporation.

Publication
G. Alabandi, J. Tesic, L. Rusnak, and M. Burtscher. "Discovering and Balancing Fundamental Cycles in Large Signed Graphs." Proceedings of the 2021 ACM/IEEE International Conference for High-Performance Computing, Networking, Storage and Analysis. November 2021.
