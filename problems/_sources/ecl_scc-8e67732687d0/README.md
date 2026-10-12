# ECL-SCC v1.0

ECL-SCC is a new parallel algorithm for detecting strongly connected components in directed graphs. The CUDA implementation is quite fast, especially on mesh graphs. It operates on graphs stored in binary CSR format. Converters to this format can be found at https://cs.txstate.edu/~burtscher/research/ECLgraph/.

The CUDA code consists of the source files ECL-SCC_10.cu and ECLgraph.h. The paper referenced below explains the ECL-SCC algorithm. Note that ECL-SCC is protected by the 3-clause BSD license.

The code can be compiled as follows:

    nvcc -O3 -arch=sm_70 ECL-SCC_10.cu -o ecl-scc

To compute the SCC of the file mesh.egr, enter:

    ./ecl-scc mesh.egr

The repository includes three sample inputs:
- toroid-wedge.mesh.egr (196608 vertices, 487798 edges, 4 MB)
- star.mesh.egr (327680 vertices, 654080 edges, 6 MB)
- cold-flow.mesh.egr (2112512 vertices, 6295941 edges, 57 MB)


### Publication

Ghadeer Alabandi, William Sands, George Biros, and Martin Burtscher. "A GPU Algorithm for Detecting Strongly Connected Components." Proceedings of the 2023 ACM/IEEE International Conference for High Performance Computing, Networking, Storage, and Analysis. Article 17, pp. 1-13. November 2023. DOI: https://dl.acm.org/doi/10.1145/3581784.3607071

Slides: https://cs.txstate.edu/~burtscher/research/ECL-SCC/ECL-SCC.pptx

Talk: https://sc23.conference-program.com/presentation/?id=pap326&sess=sess155


**Summary**: ECL-SCC is an efficient data-driven, edge-centric parallel algorithm for computing SCCs of a directed graph on GPUs. It is based on the observation that, in each SCC, there is a unique vertex with the maximum ID among the vertices in that SCC. Identifying this maximum-ID-vertex on the incoming and outgoing paths of each vertex has the potential to demarcate multiple SCCs simultaneously. This approach of allowing all vertices to simultaneously act as pivots increases the parallelism. Not following a depth- or breadth-first search order, avoiding recursion, and eliding atomic operations by exploiting the monotonicity of the maximum-ID propagation make ECL-SCC particularly GPU-friendly. On average, ECL-SCC outperforms state-of-the-art parallel SCC algorithms by about 2x on power-law graphs and by 6.5x on mesh graphs from radiation transport simulations.


*This work has been supported in part by the Department of Energy, National Nuclear Security Administration under Award Number DE-NA0003969, by the National Science Foundation under Award Number 1955367, and by equipment donations from NVIDIA Corporation.*
