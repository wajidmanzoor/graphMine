# Static Parallel GPU BCC

## Description
This repository contains the source code for a Static Parallel GPU-accelerated Biconnected Components (BCC) algorithm. It leverages CUDA for efficient parallel computation, making it suitable for large-scale graph analysis.

## Structure
- src/: 	Contains all source .cu and .cpp files.
- include/: 	Contains all header files.
- obj/: 	Contains compiled object files.
- bin/: 	Contains the executables.
## Dependencies

* CUDA Toolkit (Recommended version: [11 or above])

* A CUDA-capable GPU (Compute Capability 8.0 or higher recommended)

* GNU Compiler Collection (GCC) for compiling C++ code

## Compilation
- To compile the project, use the following Makefile command:
```shell
make all
```
This will compile all necessary components and produce the required executables.

For detailed information on all available build commands and options, you can refer to the help section of the Makefile:
```shell
make help
```
<!-- Note make opt compiles the optimized version of the code, while make will compile an unoptimized version of the code. -->
- Cleaning Build
To clean the build artifacts:

```shell
make clean
```
## Usage
After compiling, to run the program, you will need to use the command line interface. Here's the basic syntax for executing the program:
```shell
bin/cuda_bcc [options]
```
### Command Line Arguments
The program accepts several command-line arguments to control its behavior:

- -i $input: Sets the input file to $input. This is a mandatory argument as the program needs an input file to operate.

- -o $output: Sets the output directory to $output. This is optional. If not specified, the program will use the default output directory output/. The program will save its output files to this directory.

- -a $algo: Chooses the algorithm to run. The available options are:
  - cv for cut_vertex
  - ce for cut_edges
  - ibcc for implicit_bcc
  - ebcc for explicit_bcc
  - sbcc for serial-bcc

This is optional. If not specified, the program will run the explicit_bcc algorithm by default.
- -d $device: Sets the CUDA device to $device. This is the ID of the CUDA device you want to use. This is optional. If not provided, the program uses the default CUDA device 0.
### Example
```shell
bin/cuda_bcc -i input_file -o output_directory -a algorithm -d cuda_device
```
### Getting Help
To view the help message explaining all available command-line arguments, run:
```shell
bin/cuda_bcc -help
```

## Contributing
Contributions to this project are welcome. Please follow the standard Git workflow - fork the repository, make your changes, and submit a pull request.

## License
Unlicensed
