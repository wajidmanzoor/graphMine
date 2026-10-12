all: gpu cpu

gpu:
	nvcc gpuSteiner6-oddAgainWithKtimer2Sh3.cu -o gpuSteiner6-oddAgainWithKtimer2Sh3.out -Wno-deprecated-gpu-targets -std=c++11 

cpu:
	g++ -Wall -o "2approxCpu2.out" "2approxCpu2.cpp" -O3
	
