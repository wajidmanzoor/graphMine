USE_COUNTERS=0
RUN_KILL_TIMEOUT=0
COUNT_BRANCHING_ON_COMPONENTS=0

DEFS= -DUSE_COUNTERS=$(USE_COUNTERS) -DRUN_KILL_TIMEOUT=$(RUN_KILL_TIMEOUT) -DCOUNT_BRANCHING_ON_COMPONENTS=$(COUNT_BRANCHING_ON_COMPONENTS)

NVCC_FLAGS= -maxrregcount=31 -O3 -w -gencode arch=compute_70,code=sm_70 -std=c++11 

output: auxFunctions.o CSRGraphRep.o main.o Sequential.o helperFunctions.o SequentialParameterized.o crown.o hopcroft_karp.o
	nvcc $(NVCC_FLAGS) auxFunctions.o CSRGraphRep.o helperFunctions.o Sequential.o SequentialParameterized.o crown.o hopcroft_karp.o main.o -o output

main.o: main.cu
	nvcc -c $(NVCC_FLAGS) $(DEFS) main.cu

auxFunctions.o: auxFunctions.cpp auxFunctions.h config.h
	g++ -c -O3 $(DEFS) auxFunctions.cpp
	
CSRGraphRep.o: CSRGraphRep.cpp CSRGraphRep.h
	g++ -c -O3 $(DEFS) CSRGraphRep.cpp

Sequential.o: Sequential.cpp Sequential.h helperFunctions.o crown.o
	g++ -c -O3 $(DEFS) Sequential.cpp

SequentialParameterized.o: SequentialParameterized.cpp SequentialParameterized.h helperFunctions.o
	g++ -c -O3 $(DEFS) SequentialParameterized.cpp

helperFunctions.o: helperFunctions.cpp helperFunctions.h
	g++ -c -O3 $(DEFS) helperFunctions.cpp
    
crown.o: crown.cpp crown.hpp hopcroft_karp.o
	g++ -c -O3 $(DEFS) crown.cpp
    
hopcroft_karp.o: hopcroft_karp.cpp hopcroft_karp.hpp
	g++ -c -O3 $(DEFS) hopcroft_karp.cpp

clean:
	rm -f *.o output *.csv
