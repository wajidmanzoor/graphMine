# Makefile for CUDA Euler Tour Project

# CUDA Compiler
NVCC = nvcc

# Compiler flags (adjust as needed)
CXXFLAGS = -O3 -std=c++17 -arch=sm_89

# Executable name
TARGET = main

# Source files (all .cu files that need to be compiled)
SRCS = main.cu euler.cu tags.cu sparse_table_max.cu sparse_table_min.cu

# Object files (.o files corresponding to the .cu sources)
OBJS = $(SRCS:.cu=.o)

# Header dependencies
HEADERS = common.hxx euler.hxx graph.hxx rst.hxx list_ranking.hxx tags.hxx sparse_table_max.hxx sparse_table_min.hxx cc.hxx

# Default target
all: $(TARGET)

# Link object files to create the executable
$(TARGET): $(OBJS)
	$(NVCC) $(CXXFLAGS) -o $@ $^

# Compile each .cu file into an object file.
# The header dependencies ensure that changes in any header force recompilation.
%.o: %.cu $(HEADERS)
	$(NVCC) $(CXXFLAGS) -c $< -o $@

# Clean target: remove object files and the executable.
clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
