# Makefile for compiling programs

# Compiler
NVCC = nvcc

# Compiler flags
CXXFLAGS = -Xcompiler -pthread -std=c++17 -O3 -arch=sm_89

# Source files
SRC = graph.cu main.cu host_spanning_tree.cu ExternalSpanningTree.cu GPUSpanningTree.cu eulerian_tour.cu list_ranking.cu SpanningForest.cu CC.cu sparse_table_max.cu sparse_table_min.cu Timer.cpp

# Output executable
TARGET = ext-bcc

# Default target
all: $(TARGET)

# Build the target
$(TARGET): $(SRC)
	$(NVCC) $(CXXFLAGS) $(SRC) -o $(TARGET)

# Clean up
clean:
	rm -f $(TARGET)
