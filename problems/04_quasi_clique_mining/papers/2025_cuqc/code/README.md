# cuQC: Accelerating Maximal Quasi-Clique Mining using GPUs
This repository contains the code for the "cuQC: Accelerating Maximal Quasi-Clique Mining using the GPU" paper, as well as related graph formatting tools. The cuQC algorithm is a powerful maximal quasi-clique miner for the GPU.
## Obtaining the Latest Version
Visit the [cuQC Github](https://github.com/Mike12041204/cuQC) to obtain the latest version of this program.
## Package Requirements
## Hardware Requirements
* Nvidia Ampere GPU with 80GB of global memory
* CPU with 80GB of memory
  
Less memory can be used, but not all tests displayed on paper will be able to be run.
## Software Requirements
* CUDA(>=12.2.0)
* OpenMPI(>=4.1.5)
* GNU Make(>=3.82)
* GCC (>=8.2.0)
* Python (>=3.6.8)

For running a single GPU version without preparing graphs, only CUDA is needed.

## Preparing Datasets
Our program runs off graphs represented in a custom serialized format, designed to prevent duplicate processing of graphs. We provide tools to convert graphs to this format.
### Edge List to Adjacency List
Given a graph *input* provided in an edge list format where each line contains two numbers separated by whitespace representing an edge, with the first number being the source vertex and the second number being the destination vertex, for example:
```
0  1
1  0
2  7
.
.
.
```
We can convert *input* to an adjacency list format by using the edgeToAdj.py code.

We noticed that some unweighted undirected graphs represented in an edge list format had one line per undirected edge, while others had two lines, the second where the source and destination are reversed. To handle this we adjusted the code to have the option to duplicate all edges. This option is either `0 - no duplication` or `1 - duplication` and is taken on the command line when running the program as the second parameter.

The program also uses output redirection to write the generated graph into a file.

We could use this code and *input* to generate the adjacency list representation of the graph, *output*, without duplicating edges with the following line:
```
python3 edgeToAdj.py input 0 >output
```
### Adjacency List to Serialized Format
Given a graph *input* in the format of an adjacency list, where line 1 in the graph's text file contains all the adjacencies of vertex 0 in the graph, and the adjacencies are represented as space-separated integers, for example:
```
1 2 6 9 15
0 2
0 1 7 9
.
.
.
```
We can convert *input* to the serialized format by using the adjToSer.cpp code.

This program should first be compiled using `g++` to an executable file, if this executable were to be named *AtoS* then the line would be as such:
```
g++ adjToSer.cpp -o AtoS
```

We could then use *input* and *AtoS* to generate our serialized graph representation, *output*, with the following line:
```
./AtoS input output
```
# Single GPU Guide
## Build Instructions
The program can be built using `nvcc`:
```
nvcc main.cu -o cuQC
```
This will compile the program and produce the `cuQC` executable.

When using cuQC it should be noted that most data structure sizes and their related memory usage are determined statically at the start of the program through definitions, for example:
```
#define TASKS_SIZE 10000
```
We have set the program with default definitions which should work on a CPU and GPU with `40GB` for most graphs.

However, if a `segmentation fault` or `bus error` occurs during cuQC's run, these definitions may not be suitable for the graph. These definitions should be corrected by running the program again, this time in debug mode. This mode can be toggled on for cuQC by changing a definition within the program. This definition has the name of `DEBUG_MODE` and has two options: `0 - off` and `1 - on`. When debug mode is on, the program will display information indicating the size of the data within the data structures at each partial step and will provide information on which of these data structures might be causing the memory issue. This mode should allow the fine-tuning of the data structure definitions to allow cuQC to work on numerous graphs of considerable size. As explained in the paper, tuning the definition `TASKS_PER_WARP` may also decrease the memory usage of the program. Of course, at some point, a graph will become too large to run, no matter what definitions are chosen.
## Experiments
For running the experiments presented in the paper with cuQC, the host should have at least `80GB` of memory, and the device should have at least `80GB` of global memory. If the machine doesn't have that much memory, cuQC will still be able to run some experiment scenarios on smaller graphs. However, it may run out of memory, throw an error, and terminate the program in other cases. For some cases, the program may be able to run with the given amount of memory but require tuning of the data structures to do so; refer to the `Build Instructions` section for how to proceed with this.

The program takes 5 parameters:
1. graph_file, the file to find cliques in
2. gamma, the gamma of the cliques to be found, must be `>= .5`
3. min_size, the minimum size of the cliques to be found, must be `> 1`
4. output_file, the file to output the resulting cliques to
5. scheduling_toggle, the program task scheduling can run in two modes, `0 - dynamic` and `1 - static`

The program might be run as:
```
./cuQC GSE1730 .9 30 results.txt 0
```
Sample output:
```
>:PRE-PROCESSING
--->:LOADING TIME: 33 ms
>:INITIALIZING TASKS
>:BEGINNING EXPANSION
--->:ENUMERATION TIME: 171 ms
>:REMOVING NON-MAXIMAL CLIQUES
>:NUMBER OF MAXIMAL CLIQUES: 1602
--->:REMOVE NON-MAX TIME: 21 ms
--->:TOTAL TIME: 495 ms
>:PROGRAM END
```
cuQC will write output to a file named results.txt. 
Sample results.txt:
```
33 0 1 2 3 4 5 8 9 10 11 12 18 19 20 21 23 24 27 30 33 38 40 44 47 48 50 53 56 57 58 73 105 157
33 0 1 2 3 4 5 8 9 10 11 12 18 19 20 21 23 24 27 30 33 38 40 44 47 48 50 53 56 57 58 73 105 304
33 0 1 2 3 4 5 8 9 10 11 12 18 19 20 21 23 24 27 30 33 38 40 44 47 48 50 53 56 57 58 73 157 304
33 0 1 2 3 4 5 8 9 10 11 12 18 19 20 21 23 24 27 30 33 38 40 44 47 48 50 53 56 57 58 105 157 304
32 0 1 2 3 4 5 8 9 10 11 12 18 19 20 21 23 24 27 30 33 38 40 44 47 48 50 53 57 58 61 73 157
.
.
.
```
The first number in each line represents the number of vertices within the clique, and the next numbers in the line represent their IDs.

Also note that if the program finds no cliques at completion, it will post an error and terminate.

Sample debug mode output (refer to `Build Instructions` section):
```
>:PRE-PROCESSING
--->:LOADING TIME: 4 ms
>:INITIALIZING TASKS
L: 0 T1: 1 55 T2: 0 0 B: 0 0 C: 0 0
L: 1 T1: 1 55 T2: 1 55 B: 0 0 C: 0 0
L: 2 T1: 24 1044 T2: 1 55 B: 0 0 C: 0 0
>:BEGINNING EXPANSION
WTasks( TC: 192 TS: 7212 MC: 12 MS: 515) WCliques ( TC: 0 TS: 0 MC: 0 MS: 0)
L: 3 T1: 24 1044 T2: 192 7212 B: 0 0 C: 0 0

WTasks( TC: 624 TS: 22060 MC: 12 MS: 452) WCliques ( TC: 21 TS: 640 MC: 3 MS: 91)
L: 4 T1: 624 22060 T2: 192 7212 B: 0 0 C: 21 640
.
.
.
WTasks( TC: 0 TS: 0 MC: 0 MS: 0) WCliques ( TC: 4 TS: 128 MC: 1 MS: 32)
L: 18 T1: 0 0 T2: 4 128 B: 0 0 C: 3163 98216

--->:ENUMERATION TIME: 1834 ms

TASKS SIZE: 53617
BUFFER SIZE: 0
BUFFER OFFSET SIZE: 0
CLIQUES SIZE: 98216
CLIQUES OFFSET SIZE: 3163
WCLIQUES SIZE: 124
WCLIQUES OFFSET SIZE: 4
WTASKS SIZE: 515
WTASKS OFFSET SIZE: 12
VERTICES SIZE: 55

>:REMOVING NON-MAXIMAL CLIQUES
>:NUMBER OF MAXIMAL CLIQUES: 1602
--->:REMOVE NON-MAX TIME: 22 ms
--->:TOTAL TIME: 2144 ms
>:PROGRAM END
```
# Multiple GPU Guide
## Accessing Distributed Memory Version
To acquire the distributed version of cuQC, access the GitHub repository and switch to the `Distributed` branch.
## Build Instructions
We provide a Makefile to automatically build the program. Running `make` will compile and link the program and produce the `DcuQC` executable.

Like the single GPU version, data structure sizes are determined statically, and if the program encounters a memory error, you can try to tune the data structures to fit the data. Unlike the single GPU version, the data structure sizes are passed as a parameter file rather than internal code. This means the program does not need to be rebuilt every time for dataset tuning. Debug mode is still an internal setting and works the same way; however, it is located in the `inc/common.h` file rather than `main.cu`.

Also important for the distributed version is the internal definition `NUMBER_OF_PROCESSES`, which indicates how many nodes the program will run on.
## Experiments
For running experiments presented in the paper with the distributed version of cuQC, on each node, the host should have `80GB` of memory, and the device should have `80GB` of global memory.

The same tuning described in the single GPU version applies to the distributed version. However, the modification of sizes is different and specified in the above `Build Instructions` section.

The program takes 5 parameters:
1. graph_file, the file to find cliques in
2. gamma, the gamma of the cliques to be found, must be `>= .5`
3. min_size, the minimum size of the cliques to be found, must be `> 1`
4. ds_sizes_file, a file specifying the size of each data structure as well as the expanded threshold
5. output_file, the output tag for files produced by cuQC

In the distributed version, the program is always run with dynamic scheduling, and thus, the parameter is removed.

As this version will use multiple nodes, running it requires running cross-node synchronization software on your server. Our server uses the `Slurm` program.

On an individual node, the program can be run as:
```
./DcuQC GSE1730 .9 30 DS_Sizes.csv Dist_GSE
```

We provide 2 scripts to pass parameters to and use Slurm.

First, slurm.sh will take the same parameters as cuQC and create an `SBATCH` script to run cuQC across multiple nodes. This script will have to be modified to use the correct configuration on your server; the path to the graph file will also have to be modified for your setup.

This slurm.sh script does not have to be used directly as the second script run.sh calls it and uses its output to submit a Slurm task directly. It takes 1 additional parameter before the same 5 from cuQC the program's name. Unless you have changed the name of the DcuQC executable, it could be run as such:
```
./run DcuQC GSE1730 .9 30 DS_Sizes.csv Dist_GSE
```
Running run.sh like this will use Slurm to run cuQC across the node configuration set in slurm.sh.

As multiple nodes are used, there will be significantly more files generated, they have a first letter in the file name which indicates their purpose:
1. o - output files. The main output will be written to the o file without a tailing number. This tailing number for the other files indicates that it is the output for a specific node. These files will contain debugging information if the toggle is set to on.
2. e - the error file generated with every Slurm task, which contains all writes to stderr
3. r - the results file, comparable to results.txt from the single GPU version
4. t - temp files, containing the temporary results from each node before combining. These files can be ignored unless you need to debug the results.

The files generated might look like:
```
e_Dist_GSE.txt  o_Dist_GSE_0.txt  o_Dist_GSE_2.txt  r_Dist_GSE.txt  t_Dist_GSE_0.txt  t_Dist_GSE_2.txt
o_Dist_GSE.txt  o_Dist_GSE_1.txt  o_Dist_GSE_3.txt  t_Dist_GSE.txt  t_Dist_GSE_1.txt  t_Dist_GSE_3.txt
```

Printing all output can be done with:
```
cat o_*
```
For non-debugging, the output and results will look the same.

In debugging mode, the results will look the same, but the output will be formatted to show all nodes processing:
```
>:PRE-PROCESSING
--->:LOADING TIME: 4 ms
>:INITIALIZING TASKS
>:BEGINNING EXPANSION
--->:ENUMERATION TIME: 1744 ms
>:REMOVING NON-MAXIMAL CLIQUES
>:NUMBER OF MAXIMAL CLIQUES: 1602
--->:REMOVE NON-MAX TIME: 59 ms
--->:TOTAL TIME: 2833 ms
>:PROGRAM END

>:OUTPUT FROM PROCESS: 0

CPU START
L: 0 T1: 1 55 T2: 0 0 B: 0 0 C: 0 0

L: 1 T1: 1 55 T2: 1 55 B: 0 0 C: 0 0

L: 2 T1: 24 1044 T2: 1 55 B: 0 0 C: 0 0

GPU START
L: 2 T: 6 270 B: 0 0 C: 0 0

T: 48(12) 1824(464) C: 0(0) 0(0)
L: 3 T: 48 1824 B: 0 0 C: 0 0

T: 151(9) 5359(342) C: 6(3) 183(91)
L: 4 T: 151 5359 B: 0 0 C: 6 183
.
.
.
>:OUTPUT FROM PROCESS: 3

CPU START
L: 0 T1: 1 55 T2: 0 0 B: 0 0 C: 0 0

L: 1 T1: 1 55 T2: 1 55 B: 0 0 C: 0 0

L: 2 T1: 24 1044 T2: 1 55 B: 0 0 C: 0 0

GPU START
L: 2 T: 6 252 B: 0 0 C: 0 0

T: 51(12) 1961(515) C: 0(0) 0(0)
L: 3 T: 51 1961 B: 0 0 C: 0 0

T: 154(9) 5509(348) C: 4(1) 121(31)
L: 4 T: 154 5509 B: 0 0 C: 4 121
.
.
.
TASKS SIZE: 12360
BUFFER SIZE: 0
BUFFER OFFSET SIZE: 0
CLIQUES SIZE: 20104
CLIQUES OFFSET SIZE: 648
WCLIQUES SIZE: 124
WCLIQUES OFFSET SIZE: 4
WTASKS SIZE: 515
WTASKS OFFSET SIZE: 12
VERTICES SIZE: 55
```
# Video Demonstration
[![Watch the video](https://github.com/Mike12041204/cuQC/blob/cuQC/thumbnail.JPG)](https://www.youtube.com/watch?v=GJLzgyHo1_Q)

# Benchmarking Platform and Dataset
## Machine
* CPU: AMD Epyc 7742 Rome
* GPU: Nvidia Ampere A100 (108SMs, 80GB)

We ran distributed tests using `4` of these nodes.
## Software
* OS: Red Hat Enterprise Linux Server release 7.9 (Maipo)
* CUDA: 12.2.0
* MPI: OpenMPI 4.1.5
* Make: GNU Make 3.82
## Dataset
All datasets used in the paper's experiments were taken from:
* [SNAP](https://snap.stanford.edu/data/)
* [Network Repository](https://networkrepository.com/index.php)
* [Netzschleuder](https://networks.skewed.de/)
* [GEO](https://www.ncbi.nlm.nih.gov/geo/)

See the related paper for specific links to all the used data sets, and refer to the `Preparing Datasets` section on how to prepare them or other graphs for running by cuQC.
# DOI
[![DOI](https://zenodo.org/badge/617138667.svg)](https://zenodo.org/doi/10.5281/zenodo.10963361)
# License
Refer to LICENSE.md in the root directory.
