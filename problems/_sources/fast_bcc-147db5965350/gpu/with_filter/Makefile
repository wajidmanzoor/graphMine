# CUDA Compiler
NVCC = nvcc

# Compiler flags
CXXFLAGS = -O3 -std=c++17 -arch=sm_89
DEBUGFLAGS = $(CXXFLAGS) -DDEBUG

# Executable names
TARGET = main
DEBUG_TARGET = main_debug

# Source files
SRCS = main.cu euler.cu tags.cu sparse_table_max.cu sparse_table_min.cu

# Object files
OBJS = $(SRCS:.cu=.o)
DEBUG_OBJS = $(SRCS:.cu=_debug.o)

# Header dependencies
HEADERS = common.hxx euler.hxx graph.hxx rst.hxx list_ranking.hxx tags.hxx sparse_table_max.hxx sparse_table_min.hxx cc.hxx

# Default target
all: $(TARGET)

# Release build
$(TARGET): $(OBJS)
	$(NVCC) $(CXXFLAGS) -o $@ $^

# Debug build
debug: $(DEBUG_TARGET)

$(DEBUG_TARGET): $(DEBUG_OBJS)
	$(NVCC) $(DEBUGFLAGS) -o $@ $^

# Compile each .cu file into an object file (release)
%.o: %.cu $(HEADERS)
	$(NVCC) $(CXXFLAGS) -c $< -o $@

# Compile each .cu file into a debug object file
%_debug.o: %.cu $(HEADERS)
	$(NVCC) $(DEBUGFLAGS) -c $< -o $@

# Clean target: remove object files and executables
clean:
	rm -f $(OBJS) $(DEBUG_OBJS) $(TARGET) $(DEBUG_TARGET)

.PHONY: all clean debug
