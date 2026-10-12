# Makefile for GPU Biconnected Components Project

# Compiler settings
NVCC := nvcc
CXX := g++
NVCC_FLAGS := -arch=sm_89 -std=c++17
NVCC_DEBUG_FLAGS := $(NVCC_FLAGS) -g -G
NVCC_RELEASE_FLAGS := $(NVCC_FLAGS) -O3
CXX_FLAGS := -std=c++17 -O3
CXX_DEBUG_FLAGS := $(CXX_FLAGS) -g
CXX_RELEASE_FLAGS := $(CXX_FLAGS) -O3

# Directories
INCLUDE_DIR := include
SRC_DIR := src
OBJ_DIR := obj
BIN_DIR := bin

# Target
TARGET := $(BIN_DIR)/main

# Main source file
MAIN_SRC := main.cu

# CUDA source files
CUDA_SRCS := $(SRC_DIR)/cuda_bcc/bcc.cu \
             $(SRC_DIR)/cuda_bcc/bcc_memory_utils.cu \
             $(SRC_DIR)/cuda_bcc/bfs.cu \
             $(SRC_DIR)/cuda_bcc/connected_components.cu \
             $(SRC_DIR)/cuda_bcc/cut_vertex.cu \
             $(SRC_DIR)/cuda_bcc/lca.cu \
             $(SRC_DIR)/sampling/gpu-csr.cu \
             $(SRC_DIR)/sampling/sampling.cu \
			 $(SRC_DIR)/final_bcc/vertex_merging.cu \
			 $(SRC_DIR)/utility/graph.cu \
             $(SRC_DIR)/utility/cuda_utility.cu

# C++ source files (non-CUDA)
CPP_SRCS := $(SRC_DIR)/cuda_bcc/utility.cpp

# Object files
CUDA_OBJS := $(patsubst $(SRC_DIR)/%.cu,$(OBJ_DIR)/%.o,$(CUDA_SRCS))
CPP_OBJS := $(patsubst $(SRC_DIR)/%.cpp,$(OBJ_DIR)/%.o,$(CPP_SRCS))
MAIN_OBJ := $(OBJ_DIR)/main.o
ALL_OBJS := $(MAIN_OBJ) $(CUDA_OBJS) $(CPP_OBJS)

# Default target
all: release

# Build targets
.PHONY: release debug clean help

release: NVCC_FLAGS := $(NVCC_RELEASE_FLAGS)
release: CXX_FLAGS := $(CXX_RELEASE_FLAGS)
release: $(TARGET)

debug: NVCC_FLAGS := $(NVCC_DEBUG_FLAGS)
debug: CXX_FLAGS := $(CXX_DEBUG_FLAGS)
debug: $(TARGET)

# Link object files
$(TARGET): $(ALL_OBJS) | $(BIN_DIR)
	$(NVCC) $(NVCC_FLAGS) -o $@ $^
	@echo "Build complete: $@"

# Compile main CUDA file
$(OBJ_DIR)/main.o: $(MAIN_SRC) | $(OBJ_DIR)
	$(NVCC) $(NVCC_FLAGS) -I$(INCLUDE_DIR) -c $< -o $@

# Compile CUDA source files
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.cu | $(OBJ_DIR)
	@mkdir -p $(dir $@)
	$(NVCC) $(NVCC_FLAGS) -I$(INCLUDE_DIR) -c $< -o $@

# Compile C++ source files
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.cpp | $(OBJ_DIR)
	@mkdir -p $(dir $@)
	$(CXX) $(CXX_FLAGS) -I$(INCLUDE_DIR) -c $< -o $@

# Create directories
$(BIN_DIR):
	@mkdir -p $(BIN_DIR)

$(OBJ_DIR):
	@mkdir -p $(OBJ_DIR)

# Clean build artifacts
clean:
	@rm -rf $(OBJ_DIR) $(BIN_DIR)
	@echo "Cleaned up build artifacts"

# Help target
help:
	@echo "Available targets:"
	@echo "  make release  - Build optimized release version (default)"
	@echo "  make debug    - Build debug version with symbols"
	@echo "  make clean    - Remove all build artifacts"
	@echo "  make help     - Display this help message"
	@echo ""
	@echo "Usage:"
	@echo "  $(TARGET) <input_file> [k]"
	@echo "  <input_file>  : Path to the graph file"
	@echo "  [k]           : Max edges per vertex to sample (default: 2)"

.PHONY: all release debug clean help
