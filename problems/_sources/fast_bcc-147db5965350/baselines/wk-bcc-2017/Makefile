# _*_Makefile_*_
# target: dependency
# 	action

NVCCFLAGS := -std=c++17 -arch=sm_89 -Iinclude
CPPFLAGS := -std=c++17 -Iinclude

OBJDIR := obj
SRCDIR := src
INCDIR := include
BINDIR := bin

# Create the obj directory if it doesn't exist
$(shell mkdir -p $(OBJDIR))
$(shell mkdir -p $(BINDIR))

# All object files
OBJECTS := $(OBJDIR)/main.o $(OBJDIR)/bcc.o $(OBJDIR)/utility.o $(OBJDIR)/graph.o $(OBJDIR)/bfs.o \
		   $(OBJDIR)/lca.o $(OBJDIR)/cut_vertex.o $(OBJDIR)/cc.o $(OBJDIR)/bcc_memory_utils.o

# all: cuda_bcc serial_BCC checker
all: opt-parallel

cuda_bcc: $(OBJECTS)
	nvcc $(NVCCFLAGS) $(OBJECTS) -o $(BINDIR)/cuda_bcc

$(OBJDIR)/main.o: main.cu $(OBJDIR)/bcc.o $(OBJDIR)/graph.o $(OBJDIR)/bcc_memory_utils.o
	nvcc $(NVCCFLAGS) -c main.cu -o $(OBJDIR)/main.o

$(OBJDIR)/bcc.o: $(SRCDIR)/bcc.cu $(INCDIR)/bcc.cuh $(OBJDIR)/utility.o $(OBJDIR)/graph.o \
				 $(OBJDIR)/bfs.o $(OBJDIR)/lca.o
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/bcc.cu -o $(OBJDIR)/bcc.o

$(OBJDIR)/bcc_memory_utils.o: $(SRCDIR)/bcc_memory_utils.cu $(INCDIR)/bcc_memory_utils.cuh
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/bcc_memory_utils.cu -o $(OBJDIR)/bcc_memory_utils.o

$(OBJDIR)/bfs.o: $(SRCDIR)/bfs.cu $(INCDIR)/bfs.cuh
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/bfs.cu -o $(OBJDIR)/bfs.o

$(OBJDIR)/utility.o: $(SRCDIR)/utility.cpp $(INCDIR)/utility.hpp
	g++ $(CPPFLAGS) -c $(SRCDIR)/utility.cpp -o $(OBJDIR)/utility.o

$(OBJDIR)/graph.o: $(INCDIR)/graph.hpp $(SRCDIR)/graph.cpp
	g++ $(CPPFLAGS) -c $(SRCDIR)/graph.cpp -o $(OBJDIR)/graph.o

$(OBJDIR)/lca.o: $(SRCDIR)/lca.cu $(INCDIR)/lca.cuh $(OBJDIR)/cc.o $(OBJDIR)/cut_vertex.o
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/lca.cu -o $(OBJDIR)/lca.o

$(OBJDIR)/cc.o: $(SRCDIR)/connected_components.cu $(INCDIR)/connected_components.cuh
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/connected_components.cu -o $(OBJDIR)/cc.o

$(OBJDIR)/cut_vertex.o: $(SRCDIR)/cut_vertex.cu $(INCDIR)/cut_vertex.cuh
	nvcc $(NVCCFLAGS) -c $(SRCDIR)/cut_vertex.cu -o $(OBJDIR)/cut_vertex.o

serial_BCC: src/Serial_BCC_v1.cpp
	g++ -std=c++17 -O3 src/Serial_BCC_v1.cpp -o $(BINDIR)/serial_BCC

checker: implicit_bcc_checker.o explicit_bcc_checker.o

implicit_bcc_checker.o:
	g++ -std=c++17 -O3 src/checker_v1.cpp -o $(BINDIR)/implicit_bcc_checker

explicit_bcc_checker.o:
	g++ -std=c++17 -O3 src/explicit_bcc_checker.cpp -o $(BINDIR)/explicit_bcc_checker

clean:
	rm -rf $(OBJDIR)/*.o $(BINDIR)/*

# Target to add -O3 optimization flag
opt: NVCCFLAGS += -O3
opt: CPPFLAGS += -O3
opt: cuda_bcc serial_BCC checker

opt-parallel:
	make opt -j$(nproc)

# Help target for displaying usage information
help:
	@echo "Available commands:"
	@echo "  all          - Compiles the main CUDA program and associated utilities"
	@echo "  cuda_bcc     - Compiles the CUDA Biconnected Components program"
	@echo "  checker      - Compiles the implicit BCC checker"
	@echo "  serial_BCC   - Compiles the serial BCC algorithm implementation"
	@echo "  opt          - Builds all targets with optimization (-O3)"
	@echo "  opt-parallel - Builds all targets with optimization (-O3) using Accelerated compilation"
	@echo "  clean        - Removes all compiled files"
	@echo "  help         - Shows this help message"
	@echo ""
	@echo "Usage:"
	@echo "  make [command]"
	@echo "  make opt-parallel - Executes 'make opt -j$$(nproc)' for efficient parallel building"

.PHONY: all opt clean help opt-parallel
