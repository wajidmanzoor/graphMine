#include <chrono> 
#include <time.h>
#include <math.h>
#include "config.h"
#include "stack.cuh"
#include "compArray.cuh"
#include "Sequential.h"
#include "auxFunctions.h"
#include "CSRGraphRep.cuh"

#define USE_SHORT_DEGREE 0

    #define USE_GLOBAL_MEMORY 0
        #include "LocalStacks.cuh"
        #include "GlobalWorkList.cuh"
        #include "LocalStacksParameterized.cuh"
        #include "GlobalWorkListParameterized.cuh"
    #undef USE_GLOBAL_MEMORY

    #define USE_GLOBAL_MEMORY 1
        #include "LocalStacks.cuh"
        #include "GlobalWorkList.cuh"
        #include "LocalStacksParameterized.cuh"
        #include "GlobalWorkListParameterized.cuh"
    #undef USE_GLOBAL_MEMORY

#undef USE_SHORT_DEGREE

#define USE_SHORT_DEGREE 1

    #define USE_GLOBAL_MEMORY 0
        #include "LocalStacks.cuh"
        #include "GlobalWorkList.cuh"
        #include "LocalStacksParameterized.cuh"
        #include "GlobalWorkListParameterized.cuh"
    #undef USE_GLOBAL_MEMORY

    #define USE_GLOBAL_MEMORY 1
        #include "LocalStacks.cuh"
        #include "GlobalWorkList.cuh"
        #include "LocalStacksParameterized.cuh"
        #include "GlobalWorkListParameterized.cuh"
    #undef USE_GLOBAL_MEMORY
  
#undef USE_SHORT_DEGREE

#include "SequentialParameterized.h"

using namespace std;
int main(int argc, char *argv[]) {

    Config config = parseArgs(argc,argv);
    printf("\nGraph file: %s\n",config.graphFileName);
    //printf("\nUUID: %s\n",config.outputFilePrefix);

    CSRGraph graph = createCSRGraphFromFile(config.graphFileName);
    performChecks(graph, config);
    
    unsigned int originalVertexNum = graph.vertexNum;
    unsigned int originalEdgeNum = graph.edgeNum;

    chrono::time_point<std::chrono::system_clock> begin, end;
	std::chrono::duration<double> elapsed_seconds_max, elapsed_seconds_edge, elapsed_seconds_mvc, elapsed_seconds_shrink;

    begin = std::chrono::system_clock::now(); 
    unsigned int RemoveMaxMinimum = RemoveMaxApproximateMVC(graph);
    end = std::chrono::system_clock::now(); 
	elapsed_seconds_max = end - begin; 

    printf("\nElapsed Time for Approximate Remove Max: %f\n",elapsed_seconds_max.count());
    printf("Approximate Remove Max Minimum is: %u\n", RemoveMaxMinimum);
    fflush(stdout);

    begin = std::chrono::system_clock::now();
    unsigned int RemoveEdgeMinimum = RemoveEdgeApproximateMVC(graph);
    end = std::chrono::system_clock::now(); 
	elapsed_seconds_edge = end - begin; 

    printf("Elapsed Time for Approximate Remove Edge: %f\n",elapsed_seconds_edge.count());
    printf("Approximate Remove Edge Minimum is: %u\n", RemoveEdgeMinimum);
    fflush(stdout);

    unsigned int minimum = (RemoveMaxMinimum < RemoveEdgeMinimum) ? RemoveMaxMinimum : RemoveEdgeMinimum;
    
    unsigned int k = config.k; 
    unsigned int kFound = 0;
    if(config.instance == PVC) {
        minimum = k+1;
    }

    printf("\nOriginal graph size = %d\n", graph.vertexNum);

    unsigned int reducedRootNumDelVertices = 0;
    unsigned int rootNumDelVertices = 0;
    unsigned int maxDegree = 0;
    if (config.reduceInduce) {
        int* reducedRootVertexDegrees = (int*)malloc(sizeof(int)*graph.vertexNum);

        if(config.instance == PVC) {
            begin = std::chrono::system_clock::now();
            seqRootReduction(graph, k+1, reducedRootVertexDegrees, &reducedRootNumDelVertices, &maxDegree);
            rootNumDelVertices = reducedRootNumDelVertices;
            if (reducedRootNumDelVertices>=0 && reducedRootNumDelVertices<k) {
                maxDegree = 0;
                graph = shrinkCSRGraph(graph, reducedRootVertexDegrees, &maxDegree);
                k -= reducedRootNumDelVertices;
                minimum = k+1;
            } else {
                reducedRootNumDelVertices = 0;
            }
            end = std::chrono::system_clock::now();
        } else {
            begin = std::chrono::system_clock::now();

            seqRootReduction(graph, minimum, reducedRootVertexDegrees, &reducedRootNumDelVertices, &maxDegree);
            rootNumDelVertices = reducedRootNumDelVertices;
            if (reducedRootNumDelVertices>=0 && reducedRootNumDelVertices<minimum) {
                maxDegree = 0;
                graph = shrinkCSRGraph(graph, reducedRootVertexDegrees, &maxDegree);
                minimum -= reducedRootNumDelVertices;
            } else {
                reducedRootNumDelVertices = 0;
            }

            end = std::chrono::system_clock::now(); 
        }
        free(reducedRootVertexDegrees);
        printf("Induced graph size = %d\n", graph.vertexNum);

        elapsed_seconds_shrink = end - begin;
        printf("Reduce and Induce time : %fs\n",(elapsed_seconds_shrink).count());
    }

    if(config.version == SEQUENTIAL) {
        //printf("\nrootNumDelVertices = %d\n", rootNumDelVertices);
        if(config.instance == PVC){
            begin = std::chrono::system_clock::now();
            SequentialParameterized(graph, k, &kFound);
            end = std::chrono::system_clock::now(); 
            elapsed_seconds_mvc = end - begin; 
        } else {
            begin = std::chrono::system_clock::now();
            minimum = Sequential(graph, minimum);
            minimum += reducedRootNumDelVertices;
            end = std::chrono::system_clock::now(); 
            elapsed_seconds_mvc = end - begin; 
        }
        
        if(config.instance == PVC) {
            printResults(config, RemoveMaxMinimum, RemoveEdgeMinimum, elapsed_seconds_max.count(), elapsed_seconds_edge.count(), 0, (elapsed_seconds_mvc+elapsed_seconds_shrink).count(), originalVertexNum, originalEdgeNum, kFound);
        } else {
            printResults(config, RemoveMaxMinimum, RemoveEdgeMinimum, elapsed_seconds_max.count(), elapsed_seconds_edge.count(), minimum, (elapsed_seconds_mvc+elapsed_seconds_shrink).count(), originalVertexNum, originalEdgeNum, kFound);
        }

        printf("\nElapsed time: %fs\n",(elapsed_seconds_mvc+elapsed_seconds_shrink).count());
    } else {
        cudaDeviceSynchronize();

        cudaDeviceProp prop;
        cudaGetDeviceProperties(&prop, 0);
        printf("\nDevice name: %s\n", prop.name);

        int numOfMultiProcessors;
        cudaDeviceGetAttribute(&numOfMultiProcessors,cudaDevAttrMultiProcessorCount,0);
        printf("NumOfMultiProcessors : %d\n",numOfMultiProcessors);

        int maxThreadsPerMultiProcessor;
        cudaDeviceGetAttribute(&maxThreadsPerMultiProcessor,cudaDevAttrMaxThreadsPerMultiProcessor,0);
        printf("MaxThreadsPerMultiProcessor : %d\n",maxThreadsPerMultiProcessor);

        int maxThreadsPerBlock;
        cudaDeviceGetAttribute(&maxThreadsPerBlock,cudaDevAttrMaxThreadsPerBlock,0);
        printf("MaxThreadsPerBlock : %d\n",maxThreadsPerBlock);

        int maxSharedMemPerMultiProcessor;
        cudaDeviceGetAttribute(&maxSharedMemPerMultiProcessor,cudaDevAttrMaxSharedMemoryPerMultiprocessor,0);
        printf("MaxSharedMemPerMultiProcessor : %d\n\n",maxSharedMemPerMultiProcessor);
        
        bool useShort = false;
        if (config.reduceInduce) {
            //printf("\nMaxDegree = %d\n", maxDegree);
            if (maxDegree>32767) {
                printf("DataType 'int' was used for vertexDegrees\n");
                useShort = false;
            } else {
                printf("DataType 'short' was used for vertexDegrees\n");
                useShort = true;
            }
            //printf("rootNumDelVertices = %d\n\n", rootNumDelVertices);
        }

        cudaFuncAttributes attr;
        if (useShort) {
            if (config.version == HYBRID && config.instance==PVC){
            cudaFuncGetAttributes(&attr, GlobalWorkListParameterized_shared_kernel_short);
            } else if(config.version == HYBRID && config.instance==MVC) {
                cudaFuncGetAttributes(&attr, GlobalWorkList_shared_kernel_short);
            } else if(config.version == STACK_ONLY && config.instance==PVC){
                cudaFuncGetAttributes(&attr, LocalStacksParameterized_shared_kernel_short);
            } else if(config.version == STACK_ONLY && config.instance==MVC) {
                cudaFuncGetAttributes(&attr, LocalStacks_shared_kernel_short);
            }

        } else {
            if (config.version == HYBRID && config.instance==PVC){
            cudaFuncGetAttributes(&attr, GlobalWorkListParameterized_shared_kernel_int);
            } else if(config.version == HYBRID && config.instance==MVC) {
                cudaFuncGetAttributes(&attr, GlobalWorkList_shared_kernel_int);
            } else if(config.version == STACK_ONLY && config.instance==PVC){
                cudaFuncGetAttributes(&attr, LocalStacksParameterized_shared_kernel_int);
            } else if(config.version == STACK_ONLY && config.instance==MVC) {
                cudaFuncGetAttributes(&attr, LocalStacks_shared_kernel_int);
            }
        }

        int computeCapability = prop.major*10 + prop.minor;
        size_t reservedSharedMemPerBlock = computeCapability >= 80 ? 1024 : 0;
        size_t staticSharedBytes = attr.sharedSizeBytes;
        size_t alreadyUsedSharedMemPerBlock = staticSharedBytes + reservedSharedMemPerBlock;

        setBlockDimAndUseGlobalMemory(config,graph,maxSharedMemPerMultiProcessor,prop.totalGlobalMem, maxThreadsPerMultiProcessor, maxThreadsPerBlock, maxThreadsPerMultiProcessor, numOfMultiProcessors, minimum, useShort, alreadyUsedSharedMemPerBlock);
        performChecks(graph, config);

        int numThreadsPerBlock = config.blockDim;
        int numBlocksPerSm; 
        if (config.useGlobalMemory){
            if (useShort) {
                if (config.version == HYBRID && config.instance==PVC){
                cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkListParameterized_global_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkList_global_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacksParameterized_global_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacks_global_kernel_short, numThreadsPerBlock, 0);
                }

            } else {
                if (config.version == HYBRID && config.instance==PVC){
                cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkListParameterized_global_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkList_global_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacksParameterized_global_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacks_global_kernel_int, numThreadsPerBlock, 0);
                }
            }
            
        } else {

            if (useShort) {
                if (config.version == HYBRID && config.instance==PVC){
                cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkListParameterized_shared_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkList_shared_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacksParameterized_shared_kernel_short, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacks_shared_kernel_short, numThreadsPerBlock, 0);
                }
                
            } else {
                if (config.version == HYBRID && config.instance==PVC){
                cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkListParameterized_shared_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, GlobalWorkList_shared_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacksParameterized_shared_kernel_int, numThreadsPerBlock, 0);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaOccupancyMaxActiveBlocksPerMultiprocessor(&numBlocksPerSm, LocalStacks_shared_kernel_int, numThreadsPerBlock, 0);
                }
            }
        }

        unsigned int tempNumBlocks;
        if(config.numBlocks){
            tempNumBlocks = config.numBlocks;
        } else {
            tempNumBlocks = numBlocksPerSm*numOfMultiProcessors;
            config.numBlocks = tempNumBlocks;
        }

        if(config.version == STACK_ONLY) {
            if (config.startingDepth==-1) {
                config.startingDepth = floor(log2((double)tempNumBlocks));
            }
            printf("startingDepth : %d\n",config.startingDepth);
        }
        printf("\nOur Config :\n");

        const unsigned int numBlocks = tempNumBlocks;
        int numThreadsPerSM = numBlocksPerSm * numThreadsPerBlock;
        printf("NumOfThreadPerBlocks : %d\n",numThreadsPerBlock);
        printf("NumOfBlocks : %u\n",numBlocks);
        printf("NumOfBlockPerSM : %d\n",numBlocksPerSm);
        printf("NumOfThreadsPerSM : %d\n\n",numThreadsPerSM);
        fflush(stdout);

        //Allocate NODES_PER_SM
        unsigned long long * NODES_PER_SM_d;
        #if USE_COUNTERS
            unsigned long long * NODES_PER_SM;
            NODES_PER_SM = (unsigned long long *)malloc(sizeof(unsigned long long)*numOfMultiProcessors);
            for (unsigned int i = 0;i<numOfMultiProcessors;++i){
                NODES_PER_SM[i]=0x0ULL;
            }
            cudaMalloc((void**)&NODES_PER_SM_d, numOfMultiProcessors*sizeof(unsigned long long));
            cudaMemcpy(NODES_PER_SM_d, NODES_PER_SM, numOfMultiProcessors*sizeof(unsigned long long), cudaMemcpyHostToDevice);
        #endif

        //Allocate COUNT_BRANCHING_ON_COMPONENTS
        unsigned int * numBranches_d;
        unsigned int * numBranchesFreq_d;
        #if COUNT_BRANCHING_ON_COMPONENTS
        unsigned int numBranches_h = 0;
        cudaMalloc((void**) &numBranches_d, sizeof(unsigned int));
        cudaMemset(numBranches_d, 0, sizeof(unsigned int));
        
        unsigned int * numBranchesFreq_h = (unsigned int*)malloc(graph.vertexNum*sizeof(unsigned int));
        for(unsigned int i=0; i<graph.vertexNum; ++i) {
           numBranchesFreq_h[i] = 0;
        }
        cudaMalloc((void**) &numBranchesFreq_d, sizeof(unsigned int)*graph.vertexNum);
        cudaMemset(numBranchesFreq_d, 0, sizeof(unsigned int) * graph.vertexNum);
        #endif

        // Allocate GPU graph
        CSRGraph graph_d = allocateGraph(graph);

        // Allocate GPU stack
        Stacks<short> stacks_short_d;
        Stacks<int> stacks_int_d;
        if (useShort) {
            stacks_short_d = allocateStacks<short>(graph.vertexNum,numBlocks,minimum);
        } else {
            stacks_int_d = allocateStacks<int>(graph.vertexNum,numBlocks,minimum);
        }

        // Allocate GPU CompArray
        CompArray compArray_d;
        unsigned int compArraySize = config.compArraySize;
        unsigned int * compArraySize_d;
        if(config.version == HYBRID) {
            compArray_d = allocateCompArray(compArraySize);
            cudaMalloc((void**) &compArraySize_d, sizeof(unsigned int));
            cudaMemcpy(compArraySize_d, &compArraySize, sizeof(unsigned int), cudaMemcpyHostToDevice);
        }

        //Global Entries Memory Allocation
        short * global_memory_short_d;
        int * global_memory_int_d;
        if(config.useGlobalMemory) {
            if (useShort) {
                cudaMalloc((void**)&global_memory_short_d, sizeof(short)*graph.vertexNum*numBlocks*2);
            } else {
                cudaMalloc((void**)&global_memory_int_d, sizeof(int)*graph.vertexNum*numBlocks*2);
            }
        }

        unsigned int * minimum_d;
        cudaMalloc((void**) &minimum_d, sizeof(unsigned int));
        cudaMemcpy(minimum_d, &minimum, sizeof(unsigned int), cudaMemcpyHostToDevice);

        // Allocate counter for each block
        Counters* counters_d;
        #if USE_COUNTERS
        cudaMalloc((void**)&counters_d, numBlocks*sizeof(Counters));
        #endif

        unsigned int *k_d = NULL;
        unsigned int *kFound_d = NULL;
        if(config.instance == PVC) {
            cudaMalloc((void**)&k_d, sizeof(unsigned int));
            cudaMemcpy(k_d, &k, sizeof(unsigned int), cudaMemcpyHostToDevice);

            cudaMalloc((void**)&kFound_d, sizeof(unsigned int));
            cudaMemcpy(kFound_d, &kFound, sizeof(unsigned int), cudaMemcpyHostToDevice);
        }

        // HYBRID
        // Allocate GPU queue
        WorkList<short> workList_short_d;
        WorkList<int> workList_int_d;
        //First to dequeue flag
        int *first_to_dequeue_global_d;
        int first_to_dequeue_global=0;

        // stackOnly
        unsigned int * pathCounter_d;
        unsigned int pathCounter = 0;

        if(config.version == HYBRID) {
            cudaMalloc((void**)&first_to_dequeue_global_d, sizeof(int));
            cudaMemcpy(first_to_dequeue_global_d, &first_to_dequeue_global, sizeof(int), cudaMemcpyHostToDevice);
            if (useShort) {
                workList_short_d = allocateWorkList<short>(graph, config, numBlocks);
            } else {
                workList_int_d = allocateWorkList<int>(graph, config, numBlocks);
            }
        } else {
            cudaMalloc((void**)&pathCounter_d, sizeof(unsigned int));
            cudaMemcpy(pathCounter_d, &pathCounter, sizeof(unsigned int), cudaMemcpyHostToDevice);
        }

        // If useSharedMem
        int sharedMemNeeded = graph.vertexNum;
        if(graph.vertexNum > numThreadsPerBlock*2){
            sharedMemNeeded+=graph.vertexNum;
        } else {
            sharedMemNeeded+=numThreadsPerBlock*2;
        }
        if (useShort) {
            sharedMemNeeded *= sizeof(short);
        } else {
            sharedMemNeeded *= sizeof(int);
        }

        cudaEvent_t start, stop;
        cudaDeviceSynchronize();
        cudaEventCreate(&start);
        cudaEventCreate(&stop);
        cudaEventRecord(start);

        if (config.useGlobalMemory) {

            if (useShort) {
                if (config.version == HYBRID && config.instance==PVC) {
                GlobalWorkListParameterized_global_kernel_short <<< numBlocks , numThreadsPerBlock >>> (stacks_short_d, workList_short_d, graph_d, counters_d, first_to_dequeue_global_d, global_memory_short_d, k_d, kFound_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    GlobalWorkList_global_kernel_short <<< numBlocks , numThreadsPerBlock >>> (stacks_short_d, minimum_d, workList_short_d, graph_d, counters_d, first_to_dequeue_global_d, global_memory_short_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound, numBranches_d, numBranchesFreq_d);
                } else if(config.version == STACK_ONLY && config.instance==PVC) {
                    LocalStacksParameterized_global_kernel_short <<< numBlocks , numThreadsPerBlock >>> (stacks_short_d, graph_d, global_memory_short_d, k_d, kFound_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    LocalStacks_global_kernel_short <<< numBlocks , numThreadsPerBlock >>> (stacks_short_d, graph_d, minimum_d, global_memory_short_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                }
     
            } else {
                if (config.version == HYBRID && config.instance==PVC){
                GlobalWorkListParameterized_global_kernel_int <<< numBlocks , numThreadsPerBlock >>> (stacks_int_d, workList_int_d, graph_d, counters_d, first_to_dequeue_global_d, global_memory_int_d, k_d, kFound_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    GlobalWorkList_global_kernel_int <<< numBlocks , numThreadsPerBlock >>> (stacks_int_d, minimum_d, workList_int_d, graph_d, counters_d, first_to_dequeue_global_d, global_memory_int_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound, numBranches_d, numBranchesFreq_d);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    LocalStacksParameterized_global_kernel_int <<< numBlocks , numThreadsPerBlock >>> (stacks_int_d, graph_d, global_memory_int_d, k_d, kFound_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    LocalStacks_global_kernel_int <<< numBlocks , numThreadsPerBlock >>> (stacks_int_d, graph_d, minimum_d, global_memory_int_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                }
            
            }
        
        } else {
        
            if (useShort) {
                if (config.version == HYBRID && config.instance==PVC){
                cudaFuncSetAttribute(GlobalWorkListParameterized_shared_kernel_short,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                GlobalWorkListParameterized_shared_kernel_short <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_short_d, workList_short_d, graph_d, counters_d, first_to_dequeue_global_d, k_d, kFound_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaFuncSetAttribute(GlobalWorkList_shared_kernel_short,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    GlobalWorkList_shared_kernel_short <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_short_d, minimum_d, workList_short_d, graph_d, counters_d, first_to_dequeue_global_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound, numBranches_d, numBranchesFreq_d);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaFuncSetAttribute(LocalStacksParameterized_shared_kernel_short,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    LocalStacksParameterized_shared_kernel_short <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_short_d, graph_d, k_d, kFound_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaFuncSetAttribute(LocalStacks_shared_kernel_short,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    LocalStacks_shared_kernel_short <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_short_d, graph_d, minimum_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                }
            
            } else {
                if (config.version == HYBRID && config.instance==PVC){
                cudaFuncSetAttribute(GlobalWorkListParameterized_shared_kernel_int,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                GlobalWorkListParameterized_shared_kernel_int <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_int_d, workList_int_d, graph_d, counters_d, first_to_dequeue_global_d, k_d, kFound_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound);
                } else if(config.version == HYBRID && config.instance==MVC) {
                    cudaFuncSetAttribute(GlobalWorkList_shared_kernel_int,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    GlobalWorkList_shared_kernel_int <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_int_d, minimum_d, workList_int_d, graph_d, counters_d, first_to_dequeue_global_d, NODES_PER_SM_d, compArray_d, compArraySize_d, config.findBound, numBranches_d, numBranchesFreq_d);
                } else if(config.version == STACK_ONLY && config.instance==PVC){
                    cudaFuncSetAttribute(LocalStacksParameterized_shared_kernel_int,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    LocalStacksParameterized_shared_kernel_int <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_int_d, graph_d, k_d, kFound_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                } else if(config.version == STACK_ONLY && config.instance==MVC) {
                    cudaFuncSetAttribute(LocalStacks_shared_kernel_int,cudaFuncAttributeMaxDynamicSharedMemorySize,sharedMemNeeded);
                    LocalStacks_shared_kernel_int <<< numBlocks , numThreadsPerBlock, sharedMemNeeded >>> (stacks_int_d, graph_d, minimum_d, counters_d, pathCounter_d, NODES_PER_SM_d, config.startingDepth, config.findBound);
                }
            }

        }

        cudaEventRecord(stop);
        cudaEventSynchronize(stop);

        cudaError_t err = cudaDeviceSynchronize();
        if(err != cudaSuccess) {
            printf("GPU Error: %s\n", cudaGetErrorString(err));
            exit(1);
        }

        // Copy back result
        if(config.instance == PVC){
            cudaMemcpy(&kFound, kFound_d, sizeof(unsigned int), cudaMemcpyDeviceToHost);
        } else {
            cudaMemcpy(&minimum, minimum_d, sizeof(unsigned int), cudaMemcpyDeviceToHost);
            minimum += reducedRootNumDelVertices;
        }
        
        if(config.version == HYBRID) {
            unsigned int compArrayIndex;
            cudaMemcpy(&compArrayIndex, (int*)compArray_d.globalArrayIndex, sizeof(unsigned int), cudaMemcpyDeviceToHost);
            if (compArrayIndex<compArraySize) {
                printf("compArrayIndex = %d\n\n", compArrayIndex);
            } else {
                printf("compArrayIndex = %d (FULL SIZE!)\n\n", compArraySize);
            }
        }

        float milliseconds = 0;
        cudaEventElapsedTime(&milliseconds, start, stop);
        double shrink_milliseconds = elapsed_seconds_shrink.count() * 1000.0;
        double total_milliseconds = milliseconds+shrink_milliseconds;
        printf("Elapsed time: %fms \n", total_milliseconds);
        
        if(config.instance == PVC) {
            printResults(config, RemoveMaxMinimum, RemoveEdgeMinimum, elapsed_seconds_max.count(), elapsed_seconds_edge.count(), 0, total_milliseconds, numBlocks, numBlocksPerSm, numThreadsPerSM, originalVertexNum, originalEdgeNum, kFound);
        } else {
            printResults(config, RemoveMaxMinimum, RemoveEdgeMinimum, elapsed_seconds_max.count(), elapsed_seconds_edge.count(), minimum, total_milliseconds, numBlocks, numBlocksPerSm, numThreadsPerSM, originalVertexNum, originalEdgeNum, kFound);
        }

        #if USE_COUNTERS
        printCountersInFile(config,counters_d,numBlocks,shrink_milliseconds,milliseconds);
        printNodesPerSM(config,NODES_PER_SM_d,numOfMultiProcessors);
        free(NODES_PER_SM);
        cudaFree(NODES_PER_SM_d);
        cudaFree(counters_d);
        #endif

        #if COUNT_BRANCHING_ON_COMPONENTS
        cudaMemcpy(numBranchesFreq_h, numBranchesFreq_d, sizeof(unsigned int)*graph.vertexNum, cudaMemcpyDeviceToHost);
        cudaMemcpy(&numBranches_h, numBranches_d, sizeof(unsigned int), cudaMemcpyDeviceToHost);
        printNumBranchesInFile(config, numBranches_h, numBranchesFreq_h, graph.vertexNum);
        cudaFree(numBranches_d);
        cudaFree(numBranchesFreq_d);
        free(numBranchesFreq_h);
        #endif

        if(config.instance == PVC) {
            cudaFree(k_d);
            cudaFree(kFound_d);
        }
        graph.del();
        cudaFree(minimum_d);
        cudaFreeGraph(graph_d);

        if (useShort) {
            cudaFreeStacks(stacks_short_d);
        } else {
            cudaFreeStacks(stacks_int_d);
        }

        if(config.version == HYBRID) {
            cudaFreeCompArray(compArray_d);
            cudaFree(compArraySize_d);
            cudaFree(first_to_dequeue_global_d);
            if (useShort) {
                cudaFreeWorkList(workList_short_d);
            } else {
                cudaFreeWorkList(workList_int_d);
            }
        } else {
            cudaFree(pathCounter_d);
        }
        
        if(config.useGlobalMemory) {
            if (useShort) {
                cudaFree(global_memory_short_d);
            } else {
                cudaFree(global_memory_int_d);
            }
        }
    }

    if(config.instance == PVC) {
        if(kFound) {
            printf("Minimum is less than or equal to K: %u\n\n",config.k);
        } else {
            printf("Minimum is greater than K: %u\n\n",config.k);
        }
    } else {
        printf("Size of minimum vertex cover: %u\n\n", minimum);
    }

    return 0;
}
