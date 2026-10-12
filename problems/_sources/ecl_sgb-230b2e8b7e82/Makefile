# For best performance, change DEVICE_CC to sm_XX, 
#   where XX is your GPU's Compute Capability without the decimal point:
#   https://developer.nvidia.com/cuda-gpus
DEVICE_CC=sm_75


eclsgb: src/ECL-SGB.cu
	nvcc -O3 -arch=$(DEVICE_CC) src/ECL-SGB.cu -o $@

clean:
	rm eclsgb
