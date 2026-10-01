
CXX=g++
CXXFLAGS= -std=c++14 -fopenmp -DOFFSET_32 -O3
NVCC=nvcc

NVCCFLAGS=--gpu-architecture=compute_70 --gpu-code=sm_70  -lcudart -Xcompiler  -std=c++14 -DOFFSET_32 -O3

all : tricount

tricount : main.o tricount_cu.o gpu.o
	$(CXX) $(CXXFLAGS) -fstack-protector-all -o tricount main.o tricount_cu.o gpu.o -L ~/wangz/cuda-12.2/lib64 -lcudart

tricount_cu.o : tricount.cu
	$(NVCC) $(NVCCFLAGS) -dc tricount.cu -o tricount_cu.o

gpu.o : tricount_cu.o
	$(NVCC) $(NVCCFLAGS) -dlink tricount_cu.o -o gpu.o

main.o : main.cpp
	$(CXX) $(CXXFLAGS) -fstack-protector-all -c main.cpp

.PHONY : clean
clean :
	rm tricount *.o

