# For best performance, change DEVICE_CC to sm_XX, 
#   where XX is your GPU's Compute Capability without the decimal point:
#   https://developer.nvidia.com/cuda-gpus
DEVICE_CC=sm_70

maxflow: src/main.cu src/maxflow.cu src/maxflow.h lib/ECLgraph.h
	nvcc src/main.cu -I./lib -o $@ -O3 -arch=$(DEVICE_CC)

clean:
	rm -f maxflow
