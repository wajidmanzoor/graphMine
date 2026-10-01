#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <set>
#include <iostream>
#include <fstream>
#include <string>
#include <cstdio>
#include <sstream>
#include <cmath>
#include <time.h>
#include <chrono>
#include <sys/timeb.h>
#include <cuda_runtime.h>
#include <cuda.h>
#include <device_launch_parameters.h>
#include <sm_30_intrinsics.h>
#include <device_atomic_functions.h>
#ifdef GRAPHMINE_LIBRARY
#include <algorithm>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include "backends/quasi_clique_backend.hpp"
#endif
using namespace std;

#ifdef GRAPHMINE_LIBRARY
namespace graphmine_cuqc_upstream {
#endif



// GPU KERNEL LAUNCH
#ifndef BLOCK_SIZE
#define BLOCK_SIZE 1024
#endif
#ifndef NUM_OF_BLOCKS
#define NUM_OF_BLOCKS 216
#endif
#define WARP_SIZE 32

// GPU INFORMATION
#define IDX ((blockIdx.x * blockDim.x) + threadIdx.x)
#define WARP_IDX (IDX / WARP_SIZE)
#define LANE_IDX (IDX % WARP_SIZE)
#define WIB_IDX (threadIdx.x / WARP_SIZE)
#define WARPS_PER_BLOCK (BLOCK_SIZE / WARP_SIZE)
#define NUMBER_OF_WARPS (NUM_OF_BLOCKS * WARPS_PER_BLOCK)
#define NUMBER_OF_THREADS (NUM_OF_BLOCKS * BLOCK_SIZE)

// DATA STRUCTURE SIZE
#ifndef TASKS_SIZE
#define TASKS_SIZE 250000000
#endif
#ifndef TASKS_PER_WARP
#define TASKS_PER_WARP 100
#endif
#ifndef BUFFER_SIZE
#define BUFFER_SIZE 900000000
#endif
#ifndef BUFFER_OFFSET_SIZE
#define BUFFER_OFFSET_SIZE 90000000
#endif
#ifndef CLIQUES_SIZE
#define CLIQUES_SIZE 10000000
#endif
#ifndef CLIQUES_OFFSET_SIZE
#define CLIQUES_OFFSET_SIZE 1000000
#endif
#define CLIQUES_PERCENT 50
// per warp
#ifndef WCLIQUES_SIZE
#define WCLIQUES_SIZE 10000
#endif
#ifndef WCLIQUES_OFFSET_SIZE
#define WCLIQUES_OFFSET_SIZE 1000
#endif
#ifndef WTASKS_SIZE
#define WTASKS_SIZE 150000L
#endif
#ifndef WTASKS_OFFSET_SIZE
#define WTASKS_OFFSET_SIZE 10000
#endif
// global memory vertices, should be a multiple of 32 as to not waste space
#ifndef WVERTICES_SIZE
#define WVERTICES_SIZE 32000
#endif
// shared memory vertices
#define VERTICES_SIZE 70

#define EXPAND_THRESHOLD (TASKS_PER_WARP * NUMBER_OF_WARPS)
#define CLIQUES_DUMP (CLIQUES_SIZE * (CLIQUES_PERCENT / 100.0))
 
// PROGRAM RUN SETTINGS
// cpu settings
#define CPU_LEVELS 1
#define CPU_EXPAND_THRESHOLD 1
// whether the program will run entirely on the CPU or not, 0-CPU/GPU 1-CPU only
#define CPU_MODE 0

// debug toggle 0-normal/1-debug
#define DEBUG_TOGGLE 0



// VERTEX DATA
struct Vertex
{
    int vertexid;
    // labels: 0 -> candidate, 1 -> member, 2 -> covered vertex, 3 -> cover vertex, 4 -> critical adjacent vertex
    int label;
    int indeg;
    int exdeg;
    int lvl2adj;
};

// CPU GRAPH / CONSTRUCTOR
class CPU_Graph
{
    public:

    int number_of_vertices;
    int number_of_edges;
    uint64_t number_of_lvl2adj;

    // one dimentional arrays of 1hop and 2hop neighbors and the offsets for each vertex
    int* onehop_neighbors;
    uint64_t* onehop_offsets;
    int* twohop_neighbors;
    uint64_t* twohop_offsets;

    CPU_Graph(ifstream& graph_stream)
    {
        graph_stream >> number_of_vertices;
        graph_stream >> number_of_edges;
        graph_stream >> number_of_lvl2adj;

        onehop_neighbors = new int[number_of_edges];
        onehop_offsets = new uint64_t[number_of_vertices + 1];
        twohop_neighbors = new int[number_of_lvl2adj];
        twohop_offsets = new uint64_t[number_of_vertices + 1];

        for (int i = 0; i < number_of_edges; i++) {
            graph_stream >> onehop_neighbors[i];
        }

        for (int i = 0; i < number_of_vertices + 1; i++) {
            graph_stream >> onehop_offsets[i];
        }

        for (int i = 0; i < number_of_lvl2adj; i++) {
            graph_stream >> twohop_neighbors[i];
        }

        for (int i = 0; i < number_of_vertices + 1; i++) {
            graph_stream >> twohop_offsets[i];
        }
    }

#ifdef GRAPHMINE_LIBRARY
    CPU_Graph(int vertex_count, const vector<uint64_t>& onehop_row_offsets,
              const vector<int>& onehop_destinations,
              const vector<uint64_t>& twohop_row_offsets,
              const vector<int>& twohop_destinations)
        : number_of_vertices(vertex_count),
          number_of_edges(static_cast<int>(onehop_destinations.size())),
          number_of_lvl2adj(twohop_destinations.size())
    {
        onehop_neighbors = new int[number_of_edges];
        onehop_offsets = new uint64_t[number_of_vertices + 1];
        twohop_neighbors = new int[number_of_lvl2adj];
        twohop_offsets = new uint64_t[number_of_vertices + 1];
        copy(onehop_destinations.begin(), onehop_destinations.end(),
             onehop_neighbors);
        copy(onehop_row_offsets.begin(), onehop_row_offsets.end(),
             onehop_offsets);
        copy(twohop_destinations.begin(), twohop_destinations.end(),
             twohop_neighbors);
        copy(twohop_row_offsets.begin(), twohop_row_offsets.end(),
             twohop_offsets);
    }
#endif

    ~CPU_Graph() 
    {
        delete[] onehop_neighbors;
        delete[] onehop_offsets;
        delete[] twohop_neighbors;
        delete[] twohop_offsets;
    }
};

// CPU DATA
struct CPU_Data
{
    uint64_t* tasks1_count;
    uint64_t* tasks1_offset;
    Vertex* tasks1_vertices;

    uint64_t* tasks2_count;
    uint64_t* tasks2_offset;
    Vertex* tasks2_vertices;

    uint64_t* buffer_count;
    uint64_t* buffer_offset;
    Vertex* buffer_vertices;

    uint64_t* current_level;
    bool* maximal_expansion;
    bool* dumping_cliques;

    int* vertex_order_map;
    int* remaining_candidates;
    int* removed_candidates;
    int* remaining_count;
    int* removed_count;
    int* candidate_indegs;
};

// CPU CLIQUES
struct CPU_Cliques
{
    uint64_t* cliques_count;
    uint64_t* cliques_offset;
    int* cliques_vertex;
};

// DEVICE DATA
struct GPU_Data
{
    // GPU DATA
    uint64_t* current_level;

    uint64_t* tasks1_count;
    uint64_t* tasks1_offset;
    Vertex* tasks1_vertices;

    uint64_t* tasks2_count;
    uint64_t* tasks2_offset;
    Vertex* tasks2_vertices;

    uint64_t* buffer_count;
    uint64_t* buffer_offset;
    Vertex* buffer_vertices;

    uint64_t* wtasks_count;
    uint64_t* wtasks_offset;
    Vertex* wtasks_vertices;

    Vertex* global_vertices;

    int* removed_candidates;
    int* lane_removed_candidates;

    Vertex* remaining_candidates;
    int* lane_remaining_candidates;

    int* candidate_indegs;
    int* lane_candidate_indegs;

    int* adjacencies;

    int* total_tasks;

    double* minimum_degree_ratio;
    int* minimum_degrees;
    int* minimum_clique_size;
    int* scheduling_toggle;

    uint64_t* buffer_offset_start;
    uint64_t* buffer_start;
    uint64_t* cliques_offset_start;
    uint64_t* cliques_start;

    // GPU GRAPH
    int* number_of_vertices;
    int* number_of_edges;

    int* onehop_neighbors;
    uint64_t* onehop_offsets;
    int* twohop_neighbors;
    uint64_t* twohop_offsets;

    // GPU CLIQUES
    uint64_t* cliques_count;
    uint64_t* cliques_offset;
    int* cliques_vertex;

    uint64_t* wcliques_count;
    uint64_t* wcliques_offset;
    int* wcliques_vertex;

    int* total_cliques;

    // moved from local
    Vertex* read_vertices;
    uint64_t* read_offsets;
    uint64_t* read_count;

    uint64_t* write_count;
    uint64_t* write_offsets;
    Vertex* write_vertices;

    // task scheduling
    int* current_task;
};

// WARP DATA
struct Warp_Data
{
    uint64_t start[WARPS_PER_BLOCK];
    uint64_t end[WARPS_PER_BLOCK];
    int tot_vert[WARPS_PER_BLOCK];
    int num_mem[WARPS_PER_BLOCK];
    int num_cand[WARPS_PER_BLOCK];
    int expansions[WARPS_PER_BLOCK];

    int number_of_members[WARPS_PER_BLOCK];
    int number_of_candidates[WARPS_PER_BLOCK];
    int total_vertices[WARPS_PER_BLOCK];

    Vertex shared_vertices[VERTICES_SIZE * WARPS_PER_BLOCK];

    int removed_count[WARPS_PER_BLOCK];
    int remaining_count[WARPS_PER_BLOCK];
    int num_val_cands[WARPS_PER_BLOCK];
    int rw_counter[WARPS_PER_BLOCK];

    int min_ext_deg[WARPS_PER_BLOCK];
    int lower_bound[WARPS_PER_BLOCK];
    int upper_bound[WARPS_PER_BLOCK];

    int tightened_upper_bound[WARPS_PER_BLOCK];
    int min_clq_indeg[WARPS_PER_BLOCK];
    int min_indeg_exdeg[WARPS_PER_BLOCK];
    int min_clq_totaldeg[WARPS_PER_BLOCK];
    int sum_clq_indeg[WARPS_PER_BLOCK];
    int sum_candidate_indeg[WARPS_PER_BLOCK];

    bool invalid_bounds[WARPS_PER_BLOCK];
    bool success[WARPS_PER_BLOCK];

    int number_of_crit_adj[WARPS_PER_BLOCK];

    // for dynamic intersection
    int count[WARPS_PER_BLOCK];
};

// LOCAL DATA
struct Local_Data
{
    Vertex* vertices;
};



// METHODS
// general
void calculate_minimum_degrees(CPU_Graph& hg);
void search(CPU_Graph& hg, ostream& temp_results);
void allocate_memory(CPU_Data& hd, GPU_Data& dd, CPU_Cliques& hc, CPU_Graph& hg);
void initialize_tasks(CPU_Graph& hg, CPU_Data& hd);
void move_to_gpu(CPU_Data& hd, GPU_Data& dd);
void dump_cliques(CPU_Cliques& hc, GPU_Data& dd, ostream& output_file);
void flush_cliques(CPU_Cliques& hc, ostream& temp_results);
void free_memory(CPU_Data& hd, GPU_Data& dd, CPU_Cliques& hc);
void RemoveNonMax(const char* szset_filename, char* szoutput_filename);

// expansion
void h_expand_level(CPU_Graph& hg, CPU_Data& hd, CPU_Cliques& hc);
int h_lookahead_pruning(CPU_Graph& hg, CPU_Cliques& hc, CPU_Data& hd, Vertex* read_vertices, int tot_vert, int num_mem, int num_cand, uint64_t start);
int h_remove_one_vertex(CPU_Graph& hg, CPU_Data& hd, Vertex* read_vertices, int& tot_vert, int& num_cand, int& num_vert, uint64_t start);
int h_add_one_vertex(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int& number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg);
void h_diameter_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int pvertexid, int& total_vertices, int& number_of_candidates, int number_of_members);
bool h_degree_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg);
bool h_calculate_LU_bounds(CPU_Data& hd, int& upper_bound, int& lower_bound, int& min_ext_deg, Vertex* vertices, int number_of_members, int number_of_candidates);
void h_check_for_clique(CPU_Cliques& hc, Vertex* vertices, int number_of_members);
int h_critical_vertex_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int& number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg);
void h_write_to_tasks(CPU_Data& hd, Vertex* vertices, int total_vertices, Vertex* write_vertices, uint64_t* write_offsets, uint64_t* write_count);
void h_fill_from_buffer(CPU_Data& hd, Vertex* write_vertices, uint64_t* write_offsets, uint64_t* write_count, int threshold);

// helper
int h_sort_vert_cv(const void* a, const void* b);
int h_sort_vert_Q(const void* a, const void* b);
int h_sort_desc(const void* a, const void* b);
inline int h_get_mindeg(int clique_size);
inline bool h_cand_isvalid_LU(Vertex vertex, int clique_size, int upper_bound, int lower_bound, int min_ext_deg);
inline bool  h_vert_isextendable_LU(Vertex vertex, int clique_size, int upper_bound, int lower_bound, int min_ext_deg);
inline void chkerr(cudaError_t code);

// debug
void print_CPU_Data(CPU_Data& hd);
void print_GPU_Data(GPU_Data& dd);
void print_CPU_Graph(CPU_Graph& hg);
void print_GPU_Graph(GPU_Data& dd, CPU_Graph& hg);
void print_WTask_Buffers(GPU_Data& dd);
void print_WClique_Buffers(GPU_Data& dd);
void print_GPU_Cliques(GPU_Data& dd); 
void print_CPU_Cliques(CPU_Cliques& hc);
bool print_Data_Sizes(GPU_Data& dd);
void h_print_Data_Sizes(CPU_Data& hd, CPU_Cliques& hc);
void print_vertices(Vertex* vertices, int size);
bool print_Data_Sizes_Every(GPU_Data& dd, int every);
bool print_Warp_Data_Sizes(GPU_Data& dd);
void print_All_Warp_Data_Sizes(GPU_Data& dd);
bool print_Warp_Data_Sizes_Every(GPU_Data& dd, int every);
void print_All_Warp_Data_Sizes_Every(GPU_Data& dd, int every);
void initialize_maxes();
void print_maxes();



// KERNELS
// general
__global__ void d_expand_level(GPU_Data dd);
__global__ void transfer_buffers(GPU_Data dd);
__global__ void fill_from_buffer(GPU_Data dd);

// expansion
__device__ int d_lookahead_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ int d_remove_one_vertex(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ int d_add_one_vertex(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ int d_critical_vertex_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ void d_check_for_clique(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ void d_write_to_tasks(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ void d_diameter_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int pvertexid);
__device__ void d_diameter_pruning_cv(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int number_of_crit_adj);
__device__ void d_calculate_LU_bounds(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int number_of_candidates);
__device__ bool d_degree_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld);

// helper
__device__ void d_sort(Vertex* target, int size, int (*func)(Vertex&, Vertex&));
__device__ void d_sort_i(int* target, int size, int (*func)(int, int));
__device__ int d_sort_vert_Q(Vertex& v1, Vertex& v2);
__device__ int d_sort_vert_cv(Vertex& v1, Vertex& v2);
__device__ int d_sort_degs(int n1, int n2);
__device__ int d_bsearch_array(int* search_array, int array_size, int search_number);
__device__ bool d_cand_isvalid_LU(Vertex& vertex, GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ bool d_vert_isextendable_LU(Vertex& vertex, GPU_Data& dd, Warp_Data& wd, Local_Data& ld);
__device__ int d_get_mindeg(int number_of_members, GPU_Data& dd);

// debug
__device__ void d_print_vertices(Vertex* vertices, int size);



// TODO (HIGH PRIORITY)
// - 

// TODO (LOW PRIORITY - these are all not worth the time to do)
// - reevaluate and change where uint64_t's are used
// - label for vertices can be a byte rather than int
// - don't need lvl2adj in all places anymore
// - look for places where we can break early
// - examine code for unnecessary syncs on the GPU
// - in degree pruning see if we can remove failed_found by consolidating with success
// - see whether it's possible to parallelize some of calculate_LU_bounds
// - remove device expand level code duplication by using a method



// DEBUG - MAX TRACKER VARIABLES
uint64_t mts, mbs, mbo, mcs, mco, wts, wto, wcs, wco, mvs;



// COMMAND LINE INPUT VARIABLES
double minimum_degree_ratio;
int minimum_clique_size;
int* minimum_degrees;
int scheduling_toggle;



// MAIN
#ifndef GRAPHMINE_LIBRARY
int main(int argc, char* argv[])
{
    // DEBUG - rm
    cout << TASKS_PER_WARP << endl;

    // TIME
    auto start2 = chrono::high_resolution_clock::now();



    // DEBUG
    if (DEBUG_TOGGLE) {
        initialize_maxes();
    }



    // ENSURE PROPER USAGE
    if (argc != 6) {
        printf("Usage: ./main <graph_file> <gamma> <min_size> <output_file.txt> <scheduling toggle 0-dyanmic/1-static>\n");
        return 1;
    }
    ifstream graph_stream(argv[1], ios::in);
    if (!graph_stream.is_open()) {
        printf("invalid graph file\n");
        return 1;
    }
    minimum_degree_ratio = atof(argv[2]);
    if (minimum_degree_ratio < .5 || minimum_degree_ratio>1) {
        printf("minimum degree ratio must be between .5 and 1 inclusive\n");
        return 1;
    }
    minimum_clique_size = atoi(argv[3]);
    if (minimum_clique_size <= 1) {
        printf("minimum size must be greater than 1\n");
        return 1;
    }
    scheduling_toggle = atoi(argv[5]);
    if (!(scheduling_toggle == 0 || scheduling_toggle == 1)) {
        cout << "scheduling toggle must be 0 or 1" << endl;
    }
    if (CPU_EXPAND_THRESHOLD > EXPAND_THRESHOLD) {
        cout << "CPU_EXPAND_THRESHOLD must be less than the EXPAND_THRESHOLD" << endl;
        return 1;
    }



    // TIME
    auto start = chrono::high_resolution_clock::now();



    // GRAPH / MINDEGS
    cout << ">:PRE-PROCESSING" << endl;
    CPU_Graph hg(graph_stream);
    graph_stream.close();
    calculate_minimum_degrees(hg);

    // generate random name for temp file so multiple programs can be run simultaneously without files overwriting
    auto now = chrono::system_clock::now();
    auto now_us = chrono::time_point_cast<chrono::microseconds>(now);
    auto epoch = now_us.time_since_epoch();
    auto value = chrono::duration_cast<chrono::microseconds>(epoch);
    long long tduration = value.count();
    ostringstream oss;
    oss << "t_" << tduration << ".txt";
    string temp_filename = oss.str();
    ofstream temp_results(temp_filename);



    // TIME
    auto stop = chrono::high_resolution_clock::now();
    auto duration = chrono::duration_cast<chrono::milliseconds>(stop - start);
    cout << "--->:LOADING TIME: " << duration.count() << " ms" << endl;



    // SEARCH
    search(hg, temp_results);

    temp_results.close();



    // DEBUG
    if (DEBUG_TOGGLE) {
        print_maxes();
    }



    // TIME
    auto start1 = chrono::high_resolution_clock::now();



    // RM NON-MAX
    RemoveNonMax(temp_filename.c_str(), argv[4]);



    // TIME
    auto stop1 = chrono::high_resolution_clock::now();
    auto duration1 = chrono::duration_cast<chrono::milliseconds>(stop1 - start1);
    cout << "--->:REMOVE NON-MAX TIME: " << duration1.count() << " ms" << endl;

    auto stop2 = chrono::high_resolution_clock::now();
    auto duration2 = chrono::duration_cast<chrono::milliseconds>(stop2 - start2);
    cout << "--->:TOTAL TIME: " << duration2.count() << " ms" << endl;



    cout << ">:PROGRAM END" << endl;
    return 0;
}
#endif



// --- HOST METHODS --- 

// initializes minimum degrees array 
void calculate_minimum_degrees(CPU_Graph& hg)
{
    minimum_degrees = new int[hg.number_of_vertices + 1];
    minimum_degrees[0] = 0;
    for (int i = 1; i <= hg.number_of_vertices; i++) {
        minimum_degrees[i] = ceil(minimum_degree_ratio * (i - 1));
    }
}

void search(CPU_Graph& hg, ostream& temp_results) 
{
    // DATA STRUCTURES
    CPU_Data hd;
    CPU_Cliques hc;
    GPU_Data dd;



    // HANDLE MEMORY
    allocate_memory(hd, dd, hc, hg);
    cudaDeviceSynchronize();



    // TIME
    auto start = chrono::high_resolution_clock::now();



    // INITIALIZE TASKS
#ifndef GRAPHMINE_LIBRARY
    cout << ">:INITIALIZING TASKS" << endl;
#endif
    initialize_tasks(hg, hd);



    // DEBUG
    if (DEBUG_TOGGLE) {
        mvs = (*(hd.tasks1_offset + (*hd.tasks1_count)));
        if ((*(hd.tasks1_offset + (*hd.tasks1_count))) > WVERTICES_SIZE) {
            cout << "!!! VERTICES SIZE ERROR !!!" << endl;
            return;
        }
        h_print_Data_Sizes(hd, hc);
    }



    // CPU EXPANSION
    // cpu levels is multiplied by two to ensure that data ends up in tasks1, this allows us to always copy tasks1 without worry like before hybrid cpu approach
    // cpu expand must be called atleast one time to handle first round cover pruning as the gpu code cannot do this
    for (int i = 0; i < CPU_LEVELS + 1 && !(*hd.maximal_expansion); i++) {
        h_expand_level(hg, hd, hc);
    
        // if cliques is more than threshold dump
        if (hc.cliques_offset[(*hc.cliques_count)] > CLIQUES_DUMP) {
            flush_cliques(hc, temp_results);
        }



        // DEBUG
        if (DEBUG_TOGGLE) {
            h_print_Data_Sizes(hd, hc);
        }
    }

    flush_cliques(hc, temp_results);



    // TRANSFER TO GPU
    if (!CPU_MODE) {
        move_to_gpu(hd, dd);
        cudaDeviceSynchronize();
    }



    // EXPAND LEVEL
#ifndef GRAPHMINE_LIBRARY
    cout << ">:BEGINNING EXPANSION" << endl;
#endif
    while (!(*hd.maximal_expansion))
    {
        (*(hd.maximal_expansion)) = true;
        chkerr(cudaMemset(dd.current_task, 0, sizeof(int)));
        cudaDeviceSynchronize();

        // expand all tasks in 'tasks' array, each warp will write to their respective warp tasks buffer in global memory
        d_expand_level<<<NUM_OF_BLOCKS, BLOCK_SIZE>>>(dd);
        chkerr(cudaGetLastError());
        chkerr(cudaDeviceSynchronize());



        // DEBUG
        if (DEBUG_TOGGLE) {
            if (print_Warp_Data_Sizes_Every(dd, 1)) { break; }
        }



        // consolidate all the warp tasks/cliques buffers into the next global tasks array, buffer, and cliques
        transfer_buffers<<<NUM_OF_BLOCKS, BLOCK_SIZE>>>(dd);
        chkerr(cudaGetLastError());
        chkerr(cudaDeviceSynchronize());



        // determine whether maximal expansion has been accomplished
        uint64_t current_level, write_count, buffer_count;
        chkerr(cudaMemcpy(&current_level, dd.current_level, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        chkerr(cudaMemcpy(&buffer_count, dd.buffer_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        if (current_level % 2 == 0) {
            chkerr(cudaMemcpy(&write_count, dd.tasks2_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        }
        else {
            chkerr(cudaMemcpy(&write_count, dd.tasks1_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        }

        if (write_count > 0 || buffer_count > 0) {
            (*(hd.maximal_expansion)) = false;
        }



        chkerr(cudaMemset(dd.wtasks_count, 0, sizeof(uint64_t) * NUMBER_OF_WARPS));
        chkerr(cudaMemset(dd.wcliques_count, 0, sizeof(uint64_t) * NUMBER_OF_WARPS));
        if (write_count < EXPAND_THRESHOLD && buffer_count > 0) {
            // if not enough tasks were generated when expanding the previous level to fill the next tasks array the program will attempt to fill the tasks array by popping tasks from the buffer
            fill_from_buffer<<<NUM_OF_BLOCKS, BLOCK_SIZE>>>(dd);
            chkerr(cudaGetLastError());
            chkerr(cudaDeviceSynchronize());
        }
        current_level++;
        chkerr(cudaMemcpy(dd.current_level, &current_level, sizeof(uint64_t), cudaMemcpyHostToDevice));




        // determine whether cliques has exceeded defined threshold, if so dump them to a file
        uint64_t cliques_size, cliques_count;
        chkerr(cudaMemcpy(&cliques_count, dd.cliques_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        chkerr(cudaMemcpy(&cliques_size, dd.cliques_offset + cliques_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
        cudaDeviceSynchronize();

        // if cliques is more than threshold dump
        if (cliques_size > CLIQUES_DUMP) {
            dump_cliques(hc, dd, temp_results);
        }



        // DEBUG
        if (DEBUG_TOGGLE) {
            if (print_Data_Sizes_Every(dd, 1)) { break; }
        }
    }



    // TIME
    auto stop = chrono::high_resolution_clock::now();
    auto duration = chrono::duration_cast<chrono::milliseconds>(stop - start);
#ifndef GRAPHMINE_LIBRARY
    cout << "--->:ENUMERATION TIME: " << duration.count() << " ms" << endl;
#endif



    dump_cliques(hc, dd, temp_results);

    free_memory(hd, dd, hc);
}

// allocates memory for the data structures on the host and device   
void allocate_memory(CPU_Data& hd, GPU_Data& dd, CPU_Cliques& hc, CPU_Graph& hg)
{
    // GPU GRAPH
    chkerr(cudaMalloc((void**)&dd.number_of_vertices, sizeof(int)));
    chkerr(cudaMalloc((void**)&dd.number_of_edges, sizeof(int)));
    chkerr(cudaMalloc((void**)&dd.onehop_neighbors, sizeof(int) * hg.number_of_edges));
    chkerr(cudaMalloc((void**)&dd.onehop_offsets, sizeof(uint64_t) * (hg.number_of_vertices + 1)));
    chkerr(cudaMalloc((void**)&dd.twohop_neighbors, sizeof(int) * hg.number_of_lvl2adj));
    chkerr(cudaMalloc((void**)&dd.twohop_offsets, sizeof(uint64_t) * (hg.number_of_vertices + 1)));

    chkerr(cudaMemcpy(dd.number_of_vertices, &(hg.number_of_vertices), sizeof(int), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.number_of_edges, &(hg.number_of_edges), sizeof(int), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.onehop_neighbors, hg.onehop_neighbors, sizeof(int) * hg.number_of_edges, cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.onehop_offsets, hg.onehop_offsets, sizeof(uint64_t) * (hg.number_of_vertices + 1), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.twohop_neighbors, hg.twohop_neighbors, sizeof(int) * hg.number_of_lvl2adj, cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.twohop_offsets, hg.twohop_offsets, sizeof(uint64_t) * (hg.number_of_vertices + 1), cudaMemcpyHostToDevice));

    // CPU DATA
    hd.tasks1_count = new uint64_t;
    hd.tasks1_offset = new uint64_t[EXPAND_THRESHOLD + 1];
    hd.tasks1_vertices = new Vertex[TASKS_SIZE];

    hd.tasks1_offset[0] = 0;
    (*(hd.tasks1_count)) = 0;

    hd.tasks2_count = new uint64_t;
    hd.tasks2_offset = new uint64_t[EXPAND_THRESHOLD + 1];
    hd.tasks2_vertices = new Vertex[TASKS_SIZE];

    hd.tasks2_offset[0] = 0;
    (*(hd.tasks2_count)) = 0;

    hd.buffer_count = new uint64_t;
    hd.buffer_offset = new uint64_t[BUFFER_OFFSET_SIZE];
    hd.buffer_vertices = new Vertex[BUFFER_SIZE];

    hd.buffer_offset[0] = 0;
    (*(hd.buffer_count)) = 0;

    hd.current_level = new uint64_t;
    hd.maximal_expansion = new bool;
    hd.dumping_cliques = new bool;

    (*hd.current_level) = 0;
    (*hd.maximal_expansion) = false;
    (*hd.dumping_cliques) = false;

    hd.vertex_order_map = new int[hg.number_of_vertices];
    hd.remaining_candidates = new int[hg.number_of_vertices];
    hd.removed_candidates = new int[hg.number_of_vertices];
    hd.remaining_count = new int;
    hd.removed_count = new int;
    hd.candidate_indegs = new int[hg.number_of_vertices];

    memset(hd.vertex_order_map, -1, sizeof(int) * hg.number_of_vertices);

    // GPU DATA
    chkerr(cudaMalloc((void**)&dd.current_level, sizeof(uint64_t)));

    chkerr(cudaMalloc((void**)&dd.tasks1_count, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.tasks1_offset, sizeof(uint64_t) * (EXPAND_THRESHOLD + 1)));
    chkerr(cudaMalloc((void**)&dd.tasks1_vertices, sizeof(Vertex) * TASKS_SIZE));

    chkerr(cudaMemset(dd.tasks1_offset, 0, sizeof(uint64_t)));
    chkerr(cudaMemset(dd.tasks1_count, 0, sizeof(uint64_t)));

    chkerr(cudaMalloc((void**)&dd.tasks2_count, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.tasks2_offset, sizeof(uint64_t) * (EXPAND_THRESHOLD + 1)));
    chkerr(cudaMalloc((void**)&dd.tasks2_vertices, sizeof(Vertex) * TASKS_SIZE));

    chkerr(cudaMemset(dd.tasks2_offset, 0, sizeof(uint64_t)));
    chkerr(cudaMemset(dd.tasks2_count, 0, sizeof(uint64_t)));

    chkerr(cudaMalloc((void**)&dd.buffer_count, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.buffer_offset, sizeof(uint64_t) * BUFFER_OFFSET_SIZE));
    chkerr(cudaMalloc((void**)&dd.buffer_vertices, sizeof(Vertex) * BUFFER_SIZE));

    chkerr(cudaMemset(dd.buffer_offset, 0, sizeof(uint64_t)));
    chkerr(cudaMemset(dd.buffer_count, 0, sizeof(uint64_t)));

    chkerr(cudaMalloc((void**)&dd.wtasks_count, sizeof(uint64_t) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.wtasks_offset, (sizeof(uint64_t) * WTASKS_OFFSET_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.wtasks_vertices, (sizeof(Vertex) * WTASKS_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMemset(dd.wtasks_offset, 0, (sizeof(uint64_t) * WTASKS_OFFSET_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMemset(dd.wtasks_count, 0, sizeof(uint64_t) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.global_vertices, (sizeof(Vertex) * WVERTICES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.removed_candidates, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.lane_removed_candidates, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.remaining_candidates, (sizeof(Vertex) * WVERTICES_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.lane_remaining_candidates, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.candidate_indegs, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.lane_candidate_indegs, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.adjacencies, (sizeof(int) * WVERTICES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.minimum_degree_ratio, sizeof(double)));
    chkerr(cudaMalloc((void**)&dd.minimum_degrees, sizeof(int) * (hg.number_of_vertices + 1)));
    chkerr(cudaMalloc((void**)&dd.minimum_clique_size, sizeof(int)));
    chkerr(cudaMalloc((void**)&dd.scheduling_toggle, sizeof(int)));

    chkerr(cudaMemcpy(dd.minimum_degree_ratio, &minimum_degree_ratio, sizeof(double), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.minimum_degrees, minimum_degrees, sizeof(int) * (hg.number_of_vertices + 1), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.minimum_clique_size, &minimum_clique_size, sizeof(int), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.scheduling_toggle, &scheduling_toggle, sizeof(int), cudaMemcpyHostToDevice));

    chkerr(cudaMalloc((void**)&dd.total_tasks, sizeof(int)));

    chkerr(cudaMemset(dd.total_tasks, 0, sizeof(int)));

    // CPU CLIQUES
    hc.cliques_count = new uint64_t;
    hc.cliques_vertex = new int[CLIQUES_SIZE];
    hc.cliques_offset = new uint64_t[CLIQUES_OFFSET_SIZE];

    hc.cliques_offset[0] = 0;
    (*(hc.cliques_count)) = 0;

    // GPU CLIQUES
    chkerr(cudaMalloc((void**)&dd.cliques_count, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.cliques_vertex, sizeof(int) * CLIQUES_SIZE));
    chkerr(cudaMalloc((void**)&dd.cliques_offset, sizeof(uint64_t) * CLIQUES_OFFSET_SIZE));

    chkerr(cudaMemset(dd.cliques_offset, 0, sizeof(uint64_t)));
    chkerr(cudaMemset(dd.cliques_count, 0, sizeof(uint64_t)));

    chkerr(cudaMalloc((void**)&dd.wcliques_count, sizeof(uint64_t) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.wcliques_offset, (sizeof(uint64_t) * WCLIQUES_OFFSET_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMalloc((void**)&dd.wcliques_vertex, (sizeof(int) * WCLIQUES_SIZE) * NUMBER_OF_WARPS));

    chkerr(cudaMemset(dd.wcliques_offset, 0, (sizeof(uint64_t) * WCLIQUES_OFFSET_SIZE) * NUMBER_OF_WARPS));
    chkerr(cudaMemset(dd.wcliques_count, 0, sizeof(uint64_t) * NUMBER_OF_WARPS));

    chkerr(cudaMalloc((void**)&dd.total_cliques, sizeof(int)));

    chkerr(cudaMemset(dd.total_cliques, 0, sizeof(int)));

    chkerr(cudaMalloc((void**)&dd.buffer_offset_start, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.buffer_start, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.cliques_offset_start, sizeof(uint64_t)));
    chkerr(cudaMalloc((void**)&dd.cliques_start, sizeof(uint64_t)));

    // task scheduling
    chkerr(cudaMalloc((void**)&dd.current_task, sizeof(int)));
}

// processes 0th level of expansion
void initialize_tasks(CPU_Graph& hg, CPU_Data& hd)
{
    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;

    // cover pruning
    int maximum_degree;
    int maximum_degree_index;

    // vertices information
    int total_vertices;
    int number_of_candidates;
    Vertex* vertices;



    (*hd.remaining_count) = 0;
    (*hd.removed_count) = 0;

    // initialize vertices
    total_vertices = hg.number_of_vertices;
    vertices = new Vertex[total_vertices];
    number_of_candidates = total_vertices;
    for (int i = 0; i < total_vertices; i++) {
        vertices[i].vertexid = i;
        vertices[i].indeg = 0;
        vertices[i].exdeg = hg.onehop_offsets[i + 1] - hg.onehop_offsets[i];
        vertices[i].lvl2adj = hg.twohop_offsets[i + 1] - hg.twohop_offsets[i];
        if (vertices[i].exdeg >= minimum_degrees[minimum_clique_size] && vertices[i].lvl2adj >= minimum_clique_size - 1) {
            vertices[i].label = 0;
            hd.remaining_candidates[(*hd.remaining_count)++] = i;
        }
        else {
            vertices[i].label = -1;
            hd.removed_candidates[(*hd.removed_count)++] = i;
        }
    }

    

    // DEGREE-BASED PRUNING
    // update while half of vertices have been removed
    while ((*hd.remaining_count) < number_of_candidates / 2) {
        number_of_candidates = (*hd.remaining_count);
        
        for (int i = 0; i < number_of_candidates; i++) {
            vertices[hd.remaining_candidates[i]].exdeg = 0;
        }

        for (int i = 0; i < number_of_candidates; i++) {
            // in 0th level id is same as position in vertices as all vertices are in vertices, see last block
            pvertexid = hd.remaining_candidates[i];
            pneighbors_start = hg.onehop_offsets[pvertexid];
            pneighbors_end = hg.onehop_offsets[pvertexid + 1];
            for (int j = pneighbors_start; j < pneighbors_end; j++) {
                phelper1 = hg.onehop_neighbors[j];
                if (vertices[phelper1].label == 0) {
                    vertices[phelper1].exdeg++;
                }
            }
        }

        (*hd.remaining_count) = 0;
        (*hd.removed_count) = 0;

        // remove more vertices based on updated degrees
        for (int i = 0; i < number_of_candidates; i++) {
            phelper1 = hd.remaining_candidates[i];
            if (vertices[phelper1].exdeg >= minimum_degrees[minimum_clique_size]) {
                hd.remaining_candidates[(*hd.remaining_count)++] = phelper1;
            }
            else {
                vertices[phelper1].label = -1;
                hd.removed_candidates[(*hd.removed_count)++] = phelper1;
            }
        }
    }
    number_of_candidates = (*hd.remaining_count);

    // update degrees based on last round of removed vertices
    int removed_start = 0;
    while((*hd.removed_count) > removed_start) {
        pvertexid = hd.removed_candidates[removed_start];
        pneighbors_start = hg.onehop_offsets[pvertexid];
        pneighbors_end = hg.onehop_offsets[pvertexid + 1];

        for (int j = pneighbors_start; j < pneighbors_end; j++) {
            phelper1 = hg.onehop_neighbors[j];

            if (vertices[phelper1].label == 0) {
                vertices[phelper1].exdeg--;

                if (vertices[phelper1].exdeg < minimum_degrees[minimum_clique_size]) {
                    vertices[phelper1].label = -1;
                    number_of_candidates--;
                    hd.removed_candidates[(*hd.removed_count)++] = phelper1;
                }
            }
        }
        removed_start++;
    }


    
    // FIRST ROUND COVER PRUNING
    // find cover vertex
    maximum_degree = 0;
    maximum_degree_index = 0;
    for (int i = 0; i < total_vertices; i++) {
        if (vertices[i].label == 0) {
            if (vertices[i].exdeg > maximum_degree) {
                maximum_degree = vertices[i].exdeg;
                maximum_degree_index = i;
            }
        }
    }
    vertices[maximum_degree_index].label = 3;

    // find all covered vertices
    pneighbors_start = hg.onehop_offsets[maximum_degree_index];
    pneighbors_end = hg.onehop_offsets[maximum_degree_index + 1];
    for (int i = pneighbors_start; i < pneighbors_end; i++) {
        pvertexid = hg.onehop_neighbors[i];
        if (vertices[pvertexid].label == 0) {
            vertices[pvertexid].label = 2;
        }
    }

    // sort enumeration order before writing to tasks
    qsort(vertices, total_vertices, sizeof(Vertex), h_sort_vert_Q);
    total_vertices = number_of_candidates;



    // WRITE TO TASKS
    if (total_vertices > 0)
    {
        for (int j = 0; j < total_vertices; j++) {
            hd.tasks1_vertices[j].vertexid = vertices[j].vertexid;
            hd.tasks1_vertices[j].label = vertices[j].label;
            hd.tasks1_vertices[j].indeg = vertices[j].indeg;
            hd.tasks1_vertices[j].exdeg = vertices[j].exdeg;
            hd.tasks1_vertices[j].lvl2adj = 0;
        }
        (*(hd.tasks1_count))++;
        hd.tasks1_offset[(*(hd.tasks1_count))] = total_vertices;
    }

    delete[] vertices;
}

void h_expand_level(CPU_Graph& hg, CPU_Data& hd, CPU_Cliques& hc)
{
    // initiate the variables containing the location of the read and write task vectors, done in an alternating, odd-even manner like the c-intersection of cuTS
    uint64_t* read_count;
    uint64_t* read_offsets;
    Vertex* read_vertices;
    uint64_t* write_count;
    uint64_t* write_offsets;
    Vertex* write_vertices;

    // old vertices information
    uint64_t start;
    uint64_t end;
    int tot_vert;
    int num_mem;
    int num_cand;
    int expansions;
    int number_of_covered;

    // new vertices information
    Vertex* vertices;
    int number_of_members;
    int number_of_candidates;
    int total_vertices;

    // calculate lower-upper bounds
    int min_ext_deg;
    int lower_bound;
    int upper_bound;

    int method_return;
    int index;



    if ((*hd.current_level) % 2 == 0) {
        read_count = hd.tasks1_count;
        read_offsets = hd.tasks1_offset;
        read_vertices = hd.tasks1_vertices;
        write_count = hd.tasks2_count;
        write_offsets = hd.tasks2_offset;
        write_vertices = hd.tasks2_vertices;
    }
    else {
        read_count = hd.tasks2_count;
        read_offsets = hd.tasks2_offset;
        read_vertices = hd.tasks2_vertices;
        write_count = hd.tasks1_count;
        write_offsets = hd.tasks1_offset;
        write_vertices = hd.tasks1_vertices;
    }
    *write_count = 0;
    write_offsets[0] = 0;

    // set to false later if task is generated indicating non-maximal expansion
    (*hd.maximal_expansion) = true;



    // CURRENT LEVEL
    for (int i = 0; i < *read_count; i++)
    {
        // get information of vertices being handled within tasks
        start = read_offsets[i];
        end = read_offsets[i + 1];
        tot_vert = end - start;
        num_mem = 0;
        for (uint64_t j = start; j < end; j++) {
            if (read_vertices[j].label != 1) {
                break;
            }
            num_mem++;
        }
        number_of_covered = 0;
        for (uint64_t j = start + num_mem; j < end; j++) {
            if (read_vertices[j].label != 2) {
                break;
            }
            number_of_covered++;
        }
        num_cand = tot_vert - num_mem;
        expansions = num_cand;



        // LOOKAHEAD PRUNING
        method_return = h_lookahead_pruning(hg, hc, hd, read_vertices, tot_vert, num_mem, num_cand, start);
        if (method_return) {
            continue;
        }



        // NEXT LEVEL
        for (int j = number_of_covered; j < expansions; j++) {



            // REMOVE ONE VERTEX
            if (j != number_of_covered) {
                method_return = h_remove_one_vertex(hg, hd, read_vertices, tot_vert, num_cand, num_mem, start);
                if (method_return) {
                    break;
                }
            }



            // NEW VERTICES
            vertices = new Vertex[tot_vert];
            number_of_members = num_mem;
            number_of_candidates = num_cand;
            total_vertices = tot_vert;
            for (index = 0; index < number_of_members; index++) {
                vertices[index] = read_vertices[start + index];
            }
            vertices[number_of_members] = read_vertices[start + total_vertices - 1];
            for (; index < total_vertices - 1; index++) {
                vertices[index + 1] = read_vertices[start + index];
            }

            if (number_of_covered > 0) {
                // set all covered vertices from previous level as candidates
                for (int j = num_mem + 1; j <= num_mem + number_of_covered; j++) {
                    vertices[j].label = 0;
                }
            }



            // ADD ONE VERTEX
            method_return = h_add_one_vertex(hg, hd, vertices, total_vertices, number_of_candidates, number_of_members, upper_bound, lower_bound, min_ext_deg);

            // if vertex in x found as not extendable, check if current set is clique and continue to next iteration
            if (method_return == 1) {
                if (number_of_members >= minimum_clique_size) {
                    h_check_for_clique(hc, vertices, number_of_members);
                }

                delete[] vertices;
                continue;
            }



            // CRITICAL VERTEX PRUNING
            method_return = h_critical_vertex_pruning(hg, hd, vertices, total_vertices, number_of_candidates, number_of_members, upper_bound, lower_bound, min_ext_deg);

            // if critical fail continue onto next iteration
            if (method_return == 2) {
                delete[] vertices;
                continue;
            }



            // CHECK FOR CLIQUE
            if (number_of_members >= minimum_clique_size) {
                h_check_for_clique(hc, vertices, number_of_members);
            }

            // if vertex in x found as not extendable, check if current set is clique and continue to next iteration
            if (method_return == 1) {
                delete[] vertices;
                continue;
            }



            // WRITE TO TASKS
            //sort vertices so that lowest degree vertices are first in enumeration order before writing to tasks
            qsort(vertices, total_vertices, sizeof(Vertex), h_sort_vert_Q);

            if (number_of_candidates > 0) {
                h_write_to_tasks(hd, vertices, total_vertices, write_vertices, write_offsets, write_count);
            }



            delete[] vertices;
        }
    }



    // FILL TASKS FROM BUFFER
    // if last CPU round copy enough tasks for GPU expansion
    if ((*hd.current_level) == CPU_LEVELS && CPU_EXPAND_THRESHOLD < EXPAND_THRESHOLD && (*hd.buffer_count) > 0) {
        h_fill_from_buffer(hd, write_vertices, write_offsets, write_count, EXPAND_THRESHOLD);
    }
    // if not enough generated to fully populate fill from buffer
    if (*write_count < CPU_EXPAND_THRESHOLD && (*hd.buffer_count) > 0){
        h_fill_from_buffer(hd, write_vertices, write_offsets, write_count, CPU_EXPAND_THRESHOLD);
    }

    (*hd.current_level)++;
}

void move_to_gpu(CPU_Data& hd, GPU_Data& dd)
{
    if (CPU_LEVELS % 2 == 1) {
        chkerr(cudaMemcpy(dd.tasks1_count, hd.tasks1_count, sizeof(uint64_t), cudaMemcpyHostToDevice));
        chkerr(cudaMemcpy(dd.tasks1_offset, hd.tasks1_offset, (EXPAND_THRESHOLD + 1) * sizeof(uint64_t), cudaMemcpyHostToDevice));
        chkerr(cudaMemcpy(dd.tasks1_vertices, hd.tasks1_vertices, (TASKS_SIZE) * sizeof(Vertex), cudaMemcpyHostToDevice));
    }
    else {
        chkerr(cudaMemcpy(dd.tasks2_count, hd.tasks2_count, sizeof(uint64_t), cudaMemcpyHostToDevice));
        chkerr(cudaMemcpy(dd.tasks2_offset, hd.tasks2_offset, (EXPAND_THRESHOLD + 1) * sizeof(uint64_t), cudaMemcpyHostToDevice));
        chkerr(cudaMemcpy(dd.tasks2_vertices, hd.tasks2_vertices, (TASKS_SIZE) * sizeof(Vertex), cudaMemcpyHostToDevice));
    }

    chkerr(cudaMemcpy(dd.buffer_count, hd.buffer_count, sizeof(uint64_t), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.buffer_offset, hd.buffer_offset, (BUFFER_OFFSET_SIZE) * sizeof(uint64_t), cudaMemcpyHostToDevice));
    chkerr(cudaMemcpy(dd.buffer_vertices, hd.buffer_vertices, (BUFFER_SIZE) * sizeof(int), cudaMemcpyHostToDevice));

    chkerr(cudaMemcpy(dd.current_level, hd.current_level, sizeof(uint64_t), cudaMemcpyHostToDevice));
}

void dump_cliques(CPU_Cliques& hc, GPU_Data& dd, ostream& temp_results)
{
    // gpu cliques to cpu cliques
    chkerr(cudaMemcpy(hc.cliques_count, dd.cliques_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(hc.cliques_offset, dd.cliques_offset, sizeof(uint64_t) * CLIQUES_OFFSET_SIZE, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(hc.cliques_vertex, dd.cliques_vertex, sizeof(int) * CLIQUES_SIZE, cudaMemcpyDeviceToHost));
    cudaDeviceSynchronize();

    // DEBUG
    //print_CPU_Cliques(hc);

    flush_cliques(hc, temp_results);

    cudaMemset(dd.cliques_count, 0, sizeof(uint64_t));
}

void flush_cliques(CPU_Cliques& hc, ostream& temp_results) 
{
    for (int i = 0; i < ((*hc.cliques_count)); i++) {
        uint64_t start = hc.cliques_offset[i];
        uint64_t end = hc.cliques_offset[i + 1];
        temp_results << end - start << " ";
        for (uint64_t j = start; j < end; j++) {
            temp_results << hc.cliques_vertex[j] << " ";
        }
        temp_results << "\n";
    }
    ((*hc.cliques_count)) = 0;
}

void free_memory(CPU_Data& hd, GPU_Data& dd, CPU_Cliques& hc)
{
    // GPU GRAPH
    chkerr(cudaFree(dd.number_of_vertices));
    chkerr(cudaFree(dd.number_of_edges));
    chkerr(cudaFree(dd.onehop_neighbors));
    chkerr(cudaFree(dd.onehop_offsets));
    chkerr(cudaFree(dd.twohop_neighbors));
    chkerr(cudaFree(dd.twohop_offsets));

    // CPU DATA
    delete hd.tasks1_count;
    delete[] hd.tasks1_offset;
    delete[] hd.tasks1_vertices;

    delete hd.tasks2_count;
    delete[] hd.tasks2_offset;
    delete[] hd.tasks2_vertices;

    delete hd.buffer_count;
    delete[] hd.buffer_offset;
    delete[] hd.buffer_vertices;

    delete hd.current_level;
    delete hd.maximal_expansion;
    delete hd.dumping_cliques;

    delete[] hd.vertex_order_map;
    delete[] hd.remaining_candidates;
    delete hd.remaining_count;
    delete[] hd.removed_candidates;
    delete hd.removed_count;
    delete[] hd.candidate_indegs;

    // GPU DATA
    chkerr(cudaFree(dd.current_level));

    chkerr(cudaFree(dd.tasks1_count));
    chkerr(cudaFree(dd.tasks1_offset));
    chkerr(cudaFree(dd.tasks1_vertices));

    chkerr(cudaFree(dd.tasks2_count));
    chkerr(cudaFree(dd.tasks2_offset));
    chkerr(cudaFree(dd.tasks2_vertices));

    chkerr(cudaFree(dd.buffer_count));
    chkerr(cudaFree(dd.buffer_offset));
    chkerr(cudaFree(dd.buffer_vertices));

    chkerr(cudaFree(dd.wtasks_count));
    chkerr(cudaFree(dd.wtasks_offset));
    chkerr(cudaFree(dd.wtasks_vertices));

    chkerr(cudaFree(dd.global_vertices));

    chkerr(cudaFree(dd.remaining_candidates));
    chkerr(cudaFree(dd.lane_remaining_candidates));

    chkerr(cudaFree(dd.removed_candidates));
    chkerr(cudaFree(dd.lane_removed_candidates));

    chkerr(cudaFree(dd.candidate_indegs));
    chkerr(cudaFree(dd.lane_candidate_indegs));

    chkerr(cudaFree(dd.adjacencies));

    chkerr(cudaFree(dd.minimum_degree_ratio));
    chkerr(cudaFree(dd.minimum_degrees));
    chkerr(cudaFree(dd.minimum_clique_size));
    chkerr(cudaFree(dd.scheduling_toggle));

    chkerr(cudaFree(dd.total_tasks));

    // CPU CLIQUES
    delete hc.cliques_count;
    delete[] hc.cliques_vertex;
    delete[] hc.cliques_offset;

    // GPU CLIQUES
    chkerr(cudaFree(dd.cliques_count));
    chkerr(cudaFree(dd.cliques_vertex));
    chkerr(cudaFree(dd.cliques_offset));

    chkerr(cudaFree(dd.wcliques_count));
    chkerr(cudaFree(dd.wcliques_vertex));
    chkerr(cudaFree(dd.wcliques_offset));

    chkerr(cudaFree(dd.buffer_offset_start));
    chkerr(cudaFree(dd.buffer_start));
    chkerr(cudaFree(dd.cliques_offset_start));
    chkerr(cudaFree(dd.cliques_start));

    // tasks scheduling
    chkerr(cudaFree(dd.current_task));
}



// --- HOST EXPANSION METHODS ---

// returns 1 if lookahead was a success, else 0
int h_lookahead_pruning(CPU_Graph& hg, CPU_Cliques& hc, CPU_Data& hd, Vertex* read_vertices, int tot_vert, int num_mem, int num_cand, uint64_t start)
{
    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;


    // check if members meet degree requirement, dont need to check 2hop adj as diameter pruning guarentees all members will be within 2hops of eveything
    for (int i = 0; i < num_mem; i++) {
        if (read_vertices[start + i].indeg + read_vertices[start + i].exdeg < minimum_degrees[tot_vert]) {
            return 0;
        }
    }

    // initialize vertex order map
    for (int i = num_mem; i < tot_vert; i++) {
        hd.vertex_order_map[read_vertices[start + i].vertexid] = i;
    }

    // update lvl2adj to candidates for all vertices
    for (int i = num_mem; i < tot_vert; i++) {
        pvertexid = read_vertices[start + i].vertexid;
        pneighbors_start = hg.twohop_offsets[pvertexid];
        pneighbors_end = hg.twohop_offsets[pvertexid + 1];
        for (int j = pneighbors_start; j < pneighbors_end; j++) {
            phelper1 = hd.vertex_order_map[hg.twohop_neighbors[j]];

            if (phelper1 >= num_mem) {
                read_vertices[start + phelper1].lvl2adj++;
            }
        }
    }

    // reset vertex order map
    for (int i = num_mem; i < tot_vert; i++) {
        hd.vertex_order_map[read_vertices[start + i].vertexid] = -1;
    }

    // check for lookahead
    for (int j = num_mem; j < tot_vert; j++) {
        if (read_vertices[start + j].lvl2adj < num_cand - 1 || read_vertices[start + j].indeg + read_vertices[start + j].exdeg < minimum_degrees[tot_vert]) {
            return 0;
        }
    }

    // write to cliques
    uint64_t start_write = hc.cliques_offset[(*hc.cliques_count)];
    for (int j = 0; j < tot_vert; j++) {
        hc.cliques_vertex[start_write + j] = read_vertices[start + j].vertexid;
    }
    (*hc.cliques_count)++;
    hc.cliques_offset[(*hc.cliques_count)] = start_write + tot_vert;

    return 1;
}

// returns 1 is failed found or not enough vertices, else 0
int h_remove_one_vertex(CPU_Graph& hg, CPU_Data& hd, Vertex* read_vertices, int& tot_vert, int& num_cand, int& num_mem, uint64_t start)
{
    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;

    // helper variables
    int mindeg;
    bool failed_found;



    mindeg = h_get_mindeg(num_mem);

    // remove one vertex
    num_cand--;
    tot_vert--;

    // initialize vertex order map
    for (int i = 0; i < tot_vert; i++) {
        hd.vertex_order_map[read_vertices[start + i].vertexid] = i;
    }

    failed_found = false;

    // update info of vertices connected to removed cand
    pvertexid = read_vertices[start + tot_vert].vertexid;
    pneighbors_start = hg.onehop_offsets[pvertexid];
    pneighbors_end = hg.onehop_offsets[pvertexid + 1];
    for (int i = pneighbors_start; i < pneighbors_end; i++) {
        phelper1 = hd.vertex_order_map[hg.onehop_neighbors[i]];

        if (phelper1 > -1) {
            read_vertices[start + phelper1].exdeg--;

            if (phelper1 < num_mem && read_vertices[start + phelper1].indeg + read_vertices[start + phelper1].exdeg < mindeg) {
                failed_found = true;
                break;
            }
        }
    }

    // reset vertex order map
    for (int i = 0; i < tot_vert; i++) {
        hd.vertex_order_map[read_vertices[start + i].vertexid] = -1;
    }

    if (failed_found) {
        return 1;
    }

    return 0;
}

// returns 1 if failed found or invalid bound, 0 otherwise
int h_add_one_vertex(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int& number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg)
{
    // helper variables
    bool method_return;

    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int pneighbors_count;
    int phelper1;



    // ADD ONE VERTEX
    pvertexid = vertices[number_of_members].vertexid;

    vertices[number_of_members].label = 1;
    number_of_members++;
    number_of_candidates--;

    // initialize vertex order map
    for (int i = 0; i < total_vertices; i++) {
        hd.vertex_order_map[vertices[i].vertexid] = i;
    }

    pneighbors_start = hg.onehop_offsets[pvertexid];
    pneighbors_end = hg.onehop_offsets[pvertexid + 1];
    pneighbors_count = pneighbors_end - pneighbors_start;
    for (int i = 0; i < pneighbors_count; i++) {
        phelper1 = hd.vertex_order_map[hg.onehop_neighbors[pneighbors_start + i]];

        if (phelper1 > -1) {
            vertices[phelper1].indeg++;
            vertices[phelper1].exdeg--;
        }
    }



    // DIAMETER PRUNING
    h_diameter_pruning(hg, hd, vertices, pvertexid, total_vertices, number_of_candidates, number_of_members);



    // DEGREE-BASED PRUNING
    method_return = h_degree_pruning(hg, hd, vertices, total_vertices, number_of_candidates, number_of_members, upper_bound, lower_bound, min_ext_deg);

    for (int i = 0; i < hg.number_of_vertices; i++) {
        hd.vertex_order_map[i] = -1;
    }

    // if vertex in x found as not extendable, check if current set is clique and continue to next iteration
    if (method_return) {
        return 1;
    }

    return 0;
}

// returns 2 if too many vertices pruned or a critical vertex fail, returns 1 if failed found or invalid bounds, else 0
int h_critical_vertex_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int& number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg)
{
    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;

    bool critical_fail;
    int number_of_crit_adj;
    int* adj_counters;

    bool method_return;



    // initialize vertex order map
    for (int i = 0; i < total_vertices; i++) {
        hd.vertex_order_map[vertices[i].vertexid] = i;
    }

    // CRITICAL VERTEX PRUNING
    // adj_counter[0] = 10, means that the vertex at position 0 in new_vertices has 10 critical vertices neighbors within 2 hops
    adj_counters = new int[total_vertices];
    memset(adj_counters, 0, sizeof(int) * total_vertices);

    // iterate through all vertices in clique
    for (int k = 0; k < number_of_members; k++)
    {
        // if they are a critical vertex
        if (vertices[k].indeg + vertices[k].exdeg == minimum_degrees[number_of_members + lower_bound] && vertices[k].exdeg > 0) {
            pvertexid = vertices[k].vertexid;

            // iterate through all neighbors
            pneighbors_start = hg.onehop_offsets[pvertexid];
            pneighbors_end = hg.onehop_offsets[pvertexid + 1];
            for (uint64_t l = pneighbors_start; l < pneighbors_end; l++) {
                phelper1 = hd.vertex_order_map[hg.onehop_neighbors[l]];

                // if neighbor is cand
                if (phelper1 >= number_of_members) {
                    vertices[phelper1].label = 4;
                }
            }
        }
    }



    // reset vertex order map
    for (int i = 0; i < total_vertices; i++) {
        hd.vertex_order_map[vertices[i].vertexid] = -1;
    }

    // sort vertices so that critical vertex adjacent candidates are immediately after vertices within the clique
    qsort(vertices + number_of_members, number_of_candidates, sizeof(Vertex), h_sort_vert_cv);

    // calculate number of critical adjacent vertices
    number_of_crit_adj = 0;
    for (int i = number_of_members; i < total_vertices; i++) {
        if (vertices[i].label == 4) {
            number_of_crit_adj++;
        }
        else {
            break;
        }
    }



    // if there were any neighbors of critical vertices
    if (number_of_crit_adj > 0)
    {
        // initialize vertex order map
        for (int i = 0; i < total_vertices; i++) {
            hd.vertex_order_map[vertices[i].vertexid] = i;
        }

        // iterate through all neighbors
        for (int i = number_of_members; i < number_of_members + number_of_crit_adj; i++) {
            pvertexid = vertices[i].vertexid;

            // update 1hop adj
            pneighbors_start = hg.onehop_offsets[pvertexid];
            pneighbors_end = hg.onehop_offsets[pvertexid + 1];
            for (uint64_t k = pneighbors_start; k < pneighbors_end; k++) {
                phelper1 = hd.vertex_order_map[hg.onehop_neighbors[k]];

                if (phelper1 > -1) {
                    vertices[phelper1].indeg++;
                    vertices[phelper1].exdeg--;
                }
            }

            // track 2hop adj
            pneighbors_start = hg.twohop_offsets[pvertexid];
            pneighbors_end = hg.twohop_offsets[pvertexid + 1];
            for (uint64_t k = pneighbors_start; k < pneighbors_end; k++) {
                phelper1 = hd.vertex_order_map[hg.twohop_neighbors[k]];

                if (phelper1 > -1) {
                    adj_counters[phelper1]++;
                }
            }
        }

        critical_fail = false;

        // all vertices within the clique must be within 2hops of the newly added critical vertex adj vertices
        for (int k = 0; k < number_of_members; k++) {
            if (adj_counters[k] != number_of_crit_adj) {
                critical_fail = true;
            }
        }

        if (critical_fail) {
            // reset vertex order map
            for (int i = 0; i < total_vertices; i++) {
                hd.vertex_order_map[vertices[i].vertexid] = -1;
            }
            delete[] adj_counters;
            return 2;
        }

        // all critical adj vertices must all be within 2 hops of each other
        for (int k = number_of_members; k < number_of_members + number_of_crit_adj; k++) {
            if (adj_counters[k] < number_of_crit_adj - 1) {
                critical_fail = true;
            }
        }

        if (critical_fail) {
            // reset vertex order map
            for (int i = 0; i < total_vertices; i++) {
                hd.vertex_order_map[vertices[i].vertexid] = -1;
            }
            delete[] adj_counters;
            return 2;
        }

        // no failed vertices found so add all critical vertex adj candidates to clique
        for (int k = number_of_members; k < number_of_members + number_of_crit_adj; k++) {
            vertices[k].label = 1;
        }
        number_of_members += number_of_crit_adj;
        number_of_candidates -= number_of_crit_adj;
    }



    // DIAMTER PRUNING
    (*hd.remaining_count) = 0;

    // remove all cands who are not within 2hops of all newly added cands
    for (int k = number_of_members; k < total_vertices; k++) {
        if (adj_counters[k] == number_of_crit_adj) {
            hd.candidate_indegs[(*hd.remaining_count)++] = vertices[k].indeg;
        }
        else {
            vertices[k].label = -1;
        }
    }

    

    // DEGREE-BASED PRUNING
    method_return = h_degree_pruning(hg, hd, vertices, total_vertices, number_of_candidates, number_of_members, upper_bound, lower_bound, min_ext_deg);

    // reset vertex order map
    for (int i = 0; i < total_vertices; i++) {
        hd.vertex_order_map[vertices[i].vertexid] = -1;
    }

    delete[] adj_counters;

    // if vertex in x found as not extendable, check if current set is clique and continue to next iteration
    if (method_return) {
        return 1;
    }

    return 0;
}

void h_diameter_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int pvertexid, int& total_vertices, int& number_of_candidates, int number_of_members)
{
    // intersection
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;

    (*hd.remaining_count) = 0;

    for (int i = number_of_members; i < total_vertices; i++) {
        vertices[i].label = -1;
    }

    pneighbors_start = hg.twohop_offsets[pvertexid];
    pneighbors_end = hg.twohop_offsets[pvertexid + 1];
    for (int i = pneighbors_start; i < pneighbors_end; i++) {
        phelper1 = hd.vertex_order_map[hg.twohop_neighbors[i]];

        if (phelper1 >= number_of_members) {
            vertices[phelper1].label = 0;
            hd.candidate_indegs[(*hd.remaining_count)++] = vertices[phelper1].indeg;
        }
    }
}

// returns true is invalid bounds calculated or a failed vertex was found, else false
bool h_degree_pruning(CPU_Graph& hg, CPU_Data& hd, Vertex* vertices, int& total_vertices, int& number_of_candidates, int number_of_members, int& upper_bound, int& lower_bound, int& min_ext_deg)
{
    // intersection
    int pvertexid;
    uint64_t pneighbors_start;
    uint64_t pneighbors_end;
    int phelper1;

    // helper variables
    int num_val_cands;

    qsort(hd.candidate_indegs, (*hd.remaining_count), sizeof(int), h_sort_desc);

    // if invalid bounds found while calculating lower and upper bounds
    if (h_calculate_LU_bounds(hd, upper_bound, lower_bound, min_ext_deg, vertices, number_of_members, (*hd.remaining_count))) {
        return true;
    }

    // check for failed vertices
    for (int k = 0; k < number_of_members; k++) {
        if (!h_vert_isextendable_LU(vertices[k], number_of_members, upper_bound, lower_bound, min_ext_deg)) {
            return true;
        }
    }

    (*hd.remaining_count) = 0;
    (*hd.removed_count) = 0;

    // check for invalid candidates
    for (int i = number_of_members; i < total_vertices; i++) {
        if (vertices[i].label == 0 && h_cand_isvalid_LU(vertices[i], number_of_members, upper_bound, lower_bound, min_ext_deg)) {
            hd.remaining_candidates[(*hd.remaining_count)++] = i;
        }
        else {
            hd.removed_candidates[(*hd.removed_count)++] = i;
        }
    }

    while ((*hd.remaining_count) > 0 && (*hd.removed_count) > 0) {
        // update degrees
        if ((*hd.remaining_count) < (*hd.removed_count)) {
            // reset exdegs
            for (int i = 0; i < total_vertices; i++) {
                vertices[i].exdeg = 0;
            }

            for (int i = 0; i < (*hd.remaining_count); i++) {
                pvertexid = vertices[hd.remaining_candidates[i]].vertexid;
                pneighbors_start = hg.onehop_offsets[pvertexid];
                pneighbors_end = hg.onehop_offsets[pvertexid + 1];
                for (int j = pneighbors_start; j < pneighbors_end; j++) {
                    phelper1 = hd.vertex_order_map[hg.onehop_neighbors[j]];

                    if (phelper1 > -1) {
                        vertices[phelper1].exdeg++;
                    }
                }
            }
        }
        else {
            for (int i = 0; i < (*hd.removed_count); i++) {
                pvertexid = vertices[hd.removed_candidates[i]].vertexid;
                pneighbors_start = hg.onehop_offsets[pvertexid];
                pneighbors_end = hg.onehop_offsets[pvertexid + 1];
                for (int j = pneighbors_start; j < pneighbors_end; j++) {
                    phelper1 = hd.vertex_order_map[hg.onehop_neighbors[j]];

                    if (phelper1 > -1) {
                        vertices[phelper1].exdeg--;
                    }
                }
            }
        }

        num_val_cands = 0;

        for (int k = 0; k < (*hd.remaining_count); k++) {
            if (h_cand_isvalid_LU(vertices[hd.remaining_candidates[k]], number_of_members, upper_bound, lower_bound, min_ext_deg)) {
                hd.candidate_indegs[num_val_cands++] = vertices[hd.remaining_candidates[k]].indeg;
            }
        }

        qsort(hd.candidate_indegs, num_val_cands, sizeof(int), h_sort_desc);

        // if invalid bounds found while calculating lower and upper bounds
        if (h_calculate_LU_bounds(hd, upper_bound, lower_bound, min_ext_deg, vertices, number_of_members, num_val_cands)) {
            return true;
        }

        // check for failed vertices
        for (int k = 0; k < number_of_members; k++) {
            if (!h_vert_isextendable_LU(vertices[k], number_of_members, upper_bound, lower_bound, min_ext_deg)) {
                return true;
            }
        }

        num_val_cands = 0;
        (*hd.removed_count) = 0;

        // check for invalid candidates
        for (int k = 0; k < (*hd.remaining_count); k++) {
            if (h_cand_isvalid_LU(vertices[hd.remaining_candidates[k]], number_of_members, upper_bound, lower_bound, min_ext_deg)) {
                hd.remaining_candidates[num_val_cands++] = hd.remaining_candidates[k];
            }
            else {
                hd.removed_candidates[(*hd.removed_count)++] = hd.remaining_candidates[k];
            }
        }

        (*hd.remaining_count) = num_val_cands;
    }

    for (int i = 0; i < (*hd.remaining_count); i++) {
        vertices[number_of_members + i] = vertices[hd.remaining_candidates[i]];
    }

    total_vertices = total_vertices - number_of_candidates + (*hd.remaining_count);
    number_of_candidates = (*hd.remaining_count);

    return false;
}

bool h_calculate_LU_bounds(CPU_Data& hd, int& upper_bound, int& lower_bound, int& min_ext_deg, Vertex* vertices, int number_of_members, int number_of_candidates)
{
    bool invalid_bounds = false;
    int index;

    int sum_candidate_indeg = 0;
    int tightened_upper_bound = 0;

    int min_clq_indeg = vertices[0].indeg;
    int min_indeg_exdeg = vertices[0].exdeg;
    int min_clq_totaldeg = vertices[0].indeg + vertices[0].exdeg;
    int sum_clq_indeg = vertices[0].indeg;

    for (index = 1; index < number_of_members; index++) {
        sum_clq_indeg += vertices[index].indeg;

        if (vertices[index].indeg < min_clq_indeg) {
            min_clq_indeg = vertices[index].indeg;
            min_indeg_exdeg = vertices[index].exdeg;
        }
        else if (vertices[index].indeg == min_clq_indeg) {
            if (vertices[index].exdeg < min_indeg_exdeg) {
                min_indeg_exdeg = vertices[index].exdeg;
            }
        }

        if (vertices[index].indeg + vertices[index].exdeg < min_clq_totaldeg) {
            min_clq_totaldeg = vertices[index].indeg + vertices[index].exdeg;
        }
    }

    min_ext_deg = h_get_mindeg(number_of_members + 1);

    if (min_clq_indeg < minimum_degrees[number_of_members])
    {
        // lower
        lower_bound = h_get_mindeg(number_of_members) - min_clq_indeg;

        while (lower_bound <= min_indeg_exdeg && min_clq_indeg + lower_bound < minimum_degrees[number_of_members + lower_bound]) {
            lower_bound++;
        }

        if (min_clq_indeg + lower_bound < minimum_degrees[number_of_members + lower_bound]) {
            lower_bound = number_of_candidates + 1;
            invalid_bounds = true;
        }

        // upper
        upper_bound = floor(min_clq_totaldeg / minimum_degree_ratio) + 1 - number_of_members;

        if (upper_bound > number_of_candidates) {
            upper_bound = number_of_candidates;
        }

        // tighten
        if (lower_bound < upper_bound) {
            // tighten lower
            for (index = 0; index < lower_bound; index++) {
                sum_candidate_indeg += hd.candidate_indegs[index];
            }

            while (index < upper_bound && sum_clq_indeg + sum_candidate_indeg < number_of_members * minimum_degrees[number_of_members + index]) {
                sum_candidate_indeg += hd.candidate_indegs[index];
                index++;
            }

            if (sum_clq_indeg + sum_candidate_indeg < number_of_members * minimum_degrees[number_of_members + index]) {
                lower_bound = upper_bound + 1;
                invalid_bounds = true;
            }
            else {
                lower_bound = index;

                tightened_upper_bound = index;

                while (index < upper_bound) {
                    sum_candidate_indeg += hd.candidate_indegs[index];

                    index++;

                    if (sum_clq_indeg + sum_candidate_indeg >= number_of_members * minimum_degrees[number_of_members + index]) {
                        tightened_upper_bound = index;
                    }
                }

                if (upper_bound > tightened_upper_bound) {
                    upper_bound = tightened_upper_bound;
                }

                if (lower_bound > 1) {
                    min_ext_deg = h_get_mindeg(number_of_members + lower_bound);
                }
            }
        }
    }
    else {
        upper_bound = number_of_candidates;

        if (number_of_members < minimum_clique_size) {
            lower_bound = minimum_clique_size - number_of_members;
        }
        else {
            lower_bound = 0;
        }
    }

    if (number_of_members + upper_bound < minimum_clique_size) {
        invalid_bounds = true;
    }

    if (upper_bound < 0 || upper_bound < lower_bound) {
        invalid_bounds = true;
    }

    return invalid_bounds;
}

void h_check_for_clique(CPU_Cliques& hc, Vertex* vertices, int number_of_members)
{
    bool clique = true;

    int degree_requirement = minimum_degrees[number_of_members];
    for (int k = 0; k < number_of_members; k++) {
        if (vertices[k].indeg < degree_requirement) {
            clique = false;
            break;
        }
    }

    // if clique write to cliques array
    if (clique) {
        uint64_t start_write = hc.cliques_offset[(*hc.cliques_count)];
        for (int k = 0; k < number_of_members; k++) {
            hc.cliques_vertex[start_write + k] = vertices[k].vertexid;
        }
        (*hc.cliques_count)++;
        hc.cliques_offset[(*hc.cliques_count)] = start_write + number_of_members;
    }
}

void h_write_to_tasks(CPU_Data& hd, Vertex* vertices, int total_vertices, Vertex* write_vertices, uint64_t* write_offsets, uint64_t* write_count)
{
    (*hd.maximal_expansion) = false;

    if ((*write_count) < CPU_EXPAND_THRESHOLD) {
        uint64_t start_write = write_offsets[*write_count];

        for (int k = 0; k < total_vertices; k++) {
            write_vertices[start_write + k].vertexid = vertices[k].vertexid;
            write_vertices[start_write + k].label = vertices[k].label;
            write_vertices[start_write + k].indeg = vertices[k].indeg;
            write_vertices[start_write + k].exdeg = vertices[k].exdeg;
            write_vertices[start_write + k].lvl2adj = 0;
        }
        (*write_count)++;
        write_offsets[*write_count] = start_write + total_vertices;
    }
    else {
        uint64_t start_write = hd.buffer_offset[(*hd.buffer_count)];

        for (int k = 0; k < total_vertices; k++) {
            hd.buffer_vertices[start_write + k].vertexid = vertices[k].vertexid;
            hd.buffer_vertices[start_write + k].label = vertices[k].label;
            hd.buffer_vertices[start_write + k].indeg = vertices[k].indeg;
            hd.buffer_vertices[start_write + k].exdeg = vertices[k].exdeg;
            hd.buffer_vertices[start_write + k].lvl2adj = 0;
        }
        (*hd.buffer_count)++;
        hd.buffer_offset[(*hd.buffer_count)] = start_write + total_vertices;
    }
}

void h_fill_from_buffer(CPU_Data& hd, Vertex* write_vertices, uint64_t* write_offsets, uint64_t* write_count, int threshold)
{
    // read from end of buffer, write to end of tasks, decrement buffer
    (*hd.maximal_expansion) = false;

    // get read and write locations
    int write_amount = ((*hd.buffer_count) >= (threshold - *write_count)) ? threshold - *write_count : (*hd.buffer_count);
    uint64_t start_buffer = hd.buffer_offset[(*hd.buffer_count) - write_amount];
    uint64_t end_buffer = hd.buffer_offset[(*hd.buffer_count)];
    uint64_t size_buffer = end_buffer - start_buffer;
    uint64_t start_write = write_offsets[*write_count];

    // copy tasks data from end of buffer to end of tasks
    memcpy(&write_vertices[start_write], &hd.buffer_vertices[start_buffer], sizeof(Vertex) * size_buffer);

    // handle offsets
    for (int j = 1; j <= write_amount; j++) {
        write_offsets[*write_count + j] = start_write + (hd.buffer_offset[(*hd.buffer_count) - write_amount + j] - start_buffer);
    }

    // update counts
    (*write_count) += write_amount;
    (*hd.buffer_count) -= write_amount;
}



// --- HELPER METHODS ---

// update how this method looks
int h_sort_vert_Q(const void* a, const void* b)
{
    // order is: member -> covered -> cands -> cover
    // keys are: indeg -> exdeg -> lvl2adj -> vertexid
    
    Vertex* v1;
    Vertex* v2;

    v1 = (Vertex*)a;
    v2 = (Vertex*)b;

    if (v1->label == 1 && v2->label != 1)
        return -1;
    else if (v1->label != 1 && v2->label == 1)
        return 1;
    else if (v1->label == 2 && v2->label != 2)
        return -1;
    else if (v1->label != 2 && v2->label == 2)
        return 1;
    else if (v1->label == 0 && v2->label != 0)
        return -1;
    else if (v1->label != 0 && v2->label == 0)
        return 1;
    else if (v1->label == 3 && v2->label != 3)
        return -1;
    else if (v1->label != 3 && v2->label == 3)
        return 1;
    else if (v1->indeg > v2->indeg)
        return -1;
    else if (v1->indeg < v2->indeg)
        return 1;
    else if (v1->exdeg > v2->exdeg)
        return -1;
    else if (v1->exdeg < v2->exdeg)
        return 1;
    else if (v1->lvl2adj > v2->lvl2adj)
        return -1;
    else if (v1->lvl2adj < v2->lvl2adj)
        return 1;
    else if (v1->vertexid > v2->vertexid)
        return -1;
    else if (v1->vertexid < v2->vertexid)
        return 1;
    else
        return 0;
}

int h_sort_vert_cv(const void* a, const void* b)
{
    // but crit adj vertices before candidates

    Vertex* v1;
    Vertex* v2;

    v1 = (Vertex*)a;
    v2 = (Vertex*)b;

    if (v1->label == 4 && v2->label != 4)
        return -1;
    else if (v1->label != 4 && v2->label == 4)
        return 1;
    else
        return 0;
}

// sorts degrees in descending order
int h_sort_desc(const void* a, const void* b) 
{
    int n1;
    int n2;

    n1 = *(int*)a;
    n2 = *(int*)b;

    if (n1 > n2) {
        return -1;
    }
    else if (n1 < n2) {
        return 1;
    }
    else {
        return 0;
    }
}

inline int h_get_mindeg(int clique_size) {
    if (clique_size < minimum_clique_size) {
        return minimum_degrees[minimum_clique_size];
    }
    else {
        return minimum_degrees[clique_size];
    }
}

inline bool h_cand_isvalid_LU(Vertex vertex, int clique_size, int upper_bound, int lower_bound, int min_ext_deg) 
{
    if (vertex.indeg + vertex.exdeg < minimum_degrees[minimum_clique_size]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < h_get_mindeg(clique_size + vertex.exdeg + 1)) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < min_ext_deg) {
        return false;
    }
    else if (vertex.indeg + upper_bound - 1 < minimum_degrees[clique_size + lower_bound]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < h_get_mindeg(clique_size + lower_bound)) {
        return false;
    }
    else {
        return true;
    }
}

inline bool h_vert_isextendable_LU(Vertex vertex, int clique_size, int upper_bound, int lower_bound, int min_ext_deg)
{
    if (vertex.indeg + vertex.exdeg < minimum_degrees[minimum_clique_size]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < h_get_mindeg(clique_size + vertex.exdeg)) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < min_ext_deg) {
        return false;
    }
    else if (vertex.exdeg == 0 && vertex.indeg < h_get_mindeg(clique_size + vertex.exdeg)) {
        return false;
    }
    else if (vertex.indeg + upper_bound < minimum_degrees[clique_size + upper_bound]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < h_get_mindeg(clique_size + lower_bound)) {
        return false;
    }
    else {
        return true;
    }
}

inline void chkerr(cudaError_t code)
{
    if (code != cudaSuccess)
    {
#ifdef GRAPHMINE_LIBRARY
        throw runtime_error(string("cuQC CUDA call failed: ") +
                            cudaGetErrorString(code));
#else
        cout << cudaGetErrorString(code) << endl;
        exit(-1);
#endif
    }
}



// --- DEBUG METHODS ---

void print_CPU_Graph(CPU_Graph& hg) {
    cout << endl << " --- (CPU_Graph)host_graph details --- " << endl;
    cout << endl << "|V|: " << hg.number_of_vertices << " |E|: " << hg.number_of_edges << endl;
    cout << endl << "Onehop Offsets:" << endl;
    for (uint64_t i = 0; i <= hg.number_of_vertices; i++) {
        cout << hg.onehop_offsets[i] << " ";
    }
    cout << endl << "Onehop Neighbors:" << endl;
    for (uint64_t i = 0; i < hg.number_of_edges * 2; i++) {
        cout << hg.onehop_neighbors[i] << " ";
    }
    cout << endl << "Twohop Offsets:" << endl;
    for (uint64_t i = 0; i <= hg.number_of_vertices; i++) {
        cout << hg.twohop_offsets[i] << " ";
    }
    cout << endl << "Twohop Neighbors:" << endl;
    for (uint64_t i = 0; i < hg.number_of_lvl2adj; i++) {
        cout << hg.twohop_neighbors[i] << " ";
    }
    cout << endl << endl;
}

void print_GPU_Graph(GPU_Data& dd, CPU_Graph& hg)
{
    int* number_of_vertices = new int;
    int* number_of_edges = new int;

    int* onehop_neighbors = new int[hg.number_of_edges * 2];
    uint64_t * onehop_offsets = new uint64_t[(hg.number_of_vertices)+1];
    int* twohop_neighbors = new int[hg.number_of_lvl2adj];
    uint64_t * twohop_offsets = new uint64_t[(hg.number_of_vertices)+1];

    chkerr(cudaMemcpy(number_of_vertices, dd.number_of_vertices, sizeof(int), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(number_of_edges, dd.number_of_edges, sizeof(int), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(onehop_neighbors, dd.onehop_neighbors, sizeof(int)*hg.number_of_edges * 2, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(onehop_offsets, dd.onehop_offsets, sizeof(uint64_t)*(hg.number_of_vertices+1), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(twohop_neighbors, dd.twohop_neighbors, sizeof(int)*hg.number_of_lvl2adj, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(twohop_offsets, dd.twohop_offsets, sizeof(uint64_t)*(hg.number_of_vertices+1), cudaMemcpyDeviceToHost));

    cout << endl << " --- (GPU_Graph)device_graph details --- " << endl;
    cout << endl << "|V|: " << (*number_of_vertices) << " |E|: " << (*number_of_edges) << endl;
    cout << endl << "Onehop Offsets:" << endl;
    for (uint64_t i = 0; i <= (*number_of_vertices); i++) {
        cout << onehop_offsets[i] << " ";
    }
    cout << endl << "Onehop Neighbors:" << endl;
    for (uint64_t i = 0; i < hg.number_of_edges * 2; i++) {
        cout << onehop_neighbors[i] << " ";
    }
    cout << endl << "Twohop Offsets:" << endl;
    for (uint64_t i = 0; i <= (*number_of_vertices); i++) {
        cout << twohop_offsets[i] << " ";
    }
    cout << endl << "Twohop Neighbors:" << endl;
    for (uint64_t i = 0; i < hg.number_of_lvl2adj; i++) {
        cout << twohop_neighbors[i] << " ";
    }
    cout << endl << endl;

    delete number_of_vertices;
    delete number_of_edges;

    delete onehop_offsets;
    delete onehop_neighbors;
    delete twohop_offsets;
    delete twohop_neighbors;
}

void print_CPU_Data(CPU_Data& hd)
{
    cout << endl << " --- (CPU_Data)host_data details --- " << endl;
    cout << endl << "Tasks1: " << "Size: " << (*(hd.tasks1_count)) << endl;
    cout << endl << "Offsets:" << endl;
    for (uint64_t i = 0; i <= (*(hd.tasks1_count)); i++) {
        cout << hd.tasks1_offset[i] << " ";
    }
    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < hd.tasks1_offset[(*(hd.tasks1_count))]; i++) {
        cout << hd.tasks1_vertices[i].vertexid << " ";
    }
    cout << endl << "Label:" << endl;
    for (uint64_t i = 0; i < hd.tasks1_offset[(*(hd.tasks1_count))]; i++) {
        cout << hd.tasks1_vertices[i].label << " ";
    }
    cout << endl << "Indeg:" << endl;
    for (uint64_t i = 0; i < hd.tasks1_offset[(*(hd.tasks1_count))]; i++) {
        cout << hd.tasks1_vertices[i].indeg << " ";
    }
    cout << endl << "Exdeg:" << endl;
    for (uint64_t i = 0; i < hd.tasks1_offset[(*(hd.tasks1_count))]; i++) {
        cout << hd.tasks1_vertices[i].exdeg << " ";
    }
    cout << endl << "Lvl2adj:" << endl;
    for (uint64_t i = 0; i < hd.tasks1_offset[(*(hd.tasks1_count))]; i++) {
        cout << hd.tasks1_vertices[i].lvl2adj << " ";
    }

    cout << endl << endl << "Tasks2: " << "Size: " << (*(hd.tasks2_count)) << endl;
    cout << endl << "Offsets:" << endl;
    for (uint64_t i = 0; i <= (*(hd.tasks2_count)); i++) {
        cout << hd.tasks2_offset[i] << " ";
    }
    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < hd.tasks2_offset[(*(hd.tasks2_count))]; i++) {
        cout << hd.tasks2_vertices[i].vertexid << " ";
    }
    cout << endl << "Label:" << endl;
    for (uint64_t i = 0; i < hd.tasks2_offset[(*(hd.tasks2_count))]; i++) {
        cout << hd.tasks2_vertices[i].label << " ";
    }
    cout << endl << "Indeg:" << endl;
    for (uint64_t i = 0; i < hd.tasks2_offset[(*(hd.tasks2_count))]; i++) {
        cout << hd.tasks2_vertices[i].indeg << " ";
    }
    cout << endl << "Exdeg:" << endl;
    for (uint64_t i = 0; i < hd.tasks2_offset[(*(hd.tasks2_count))]; i++) {
        cout << hd.tasks2_vertices[i].exdeg << " ";
    }
    cout << endl << "Lvl2adj:" << endl;
    for (uint64_t i = 0; i < hd.tasks2_offset[(*(hd.tasks2_count))]; i++) {
        cout << hd.tasks2_vertices[i].lvl2adj << " ";
    }

    cout << endl << endl << "Buffer: " << "Size: " << (*(hd.buffer_count)) << endl;
    cout << endl << "Offsets:" << endl;
    for (uint64_t i = 0; i <= (*(hd.buffer_count)); i++) {
        cout << hd.buffer_offset[i] << " ";
    }
    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < hd.buffer_offset[(*(hd.buffer_count))]; i++) {
        cout << hd.buffer_vertices[i].vertexid << " ";
    }
    cout << endl << "Label:" << endl;
    for (uint64_t i = 0; i < hd.buffer_offset[(*(hd.buffer_count))]; i++) {
        cout << hd.buffer_vertices[i].label << " ";
    }
    cout << endl << "Indeg:" << endl;
    for (uint64_t i = 0; i < hd.buffer_offset[(*(hd.buffer_count))]; i++) {
        cout << hd.buffer_vertices[i].indeg << " ";
    }
    cout << endl << "Exdeg:" << endl;
    for (uint64_t i = 0; i < hd.buffer_offset[(*(hd.buffer_count))]; i++) {
        cout << hd.buffer_vertices[i].exdeg << " ";
    }
    cout << endl << "Lvl2adj:" << endl;
    for (uint64_t i = 0; i < hd.buffer_offset[(*(hd.buffer_count))]; i++) {
        cout << hd.buffer_vertices[i].lvl2adj << " ";
    }
    cout << endl << endl;
}

void print_GPU_Data(GPU_Data& dd)
{
    uint64_t* current_level = new uint64_t;

    uint64_t* tasks1_count = new uint64_t;
    uint64_t* tasks1_offset = new uint64_t[EXPAND_THRESHOLD + 1];
    Vertex* tasks1_vertices = new Vertex[TASKS_SIZE];

    uint64_t* tasks2_count = new uint64_t;
    uint64_t* tasks2_offset = new uint64_t[EXPAND_THRESHOLD + 1];
    Vertex* tasks2_vertices = new Vertex[TASKS_SIZE];


    uint64_t* buffer_count = new uint64_t;
    uint64_t* buffer_offset = new uint64_t[BUFFER_OFFSET_SIZE];
    Vertex* buffer_vertices = new Vertex[BUFFER_SIZE];


    chkerr(cudaMemcpy(current_level, dd.current_level, sizeof(uint64_t), cudaMemcpyDeviceToHost));

    chkerr(cudaMemcpy(tasks1_count, dd.tasks1_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks1_offset, dd.tasks1_offset, (EXPAND_THRESHOLD + 1) * sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks1_vertices, dd.tasks1_vertices, (TASKS_SIZE) * sizeof(Vertex), cudaMemcpyDeviceToHost));

    chkerr(cudaMemcpy(tasks2_count, dd.tasks2_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks2_offset, dd.tasks2_offset, (EXPAND_THRESHOLD + 1) * sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks2_vertices, dd.tasks2_vertices, (TASKS_SIZE) * sizeof(Vertex), cudaMemcpyDeviceToHost));

    chkerr(cudaMemcpy(buffer_count, dd.buffer_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(buffer_offset, dd.buffer_offset, (BUFFER_OFFSET_SIZE) * sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(buffer_vertices, dd.buffer_vertices, (BUFFER_SIZE) * sizeof(Vertex), cudaMemcpyDeviceToHost));

    cout << " --- (GPU_Data)device_data details --- " << endl;
    cout << endl << "Tasks1: Level: " << (*current_level) << " Size: " << (*tasks1_count) << endl;
    cout << endl << "Offsets:" << endl;
    for (int i = 0; i <= (*tasks1_count); i++) {
        cout << tasks1_offset[i] << " " << flush;
    }
    cout << endl << "Vertex:" << endl;
    for (int i = 0; i < tasks1_offset[*tasks1_count]; i++) {
        cout << tasks1_vertices[i].vertexid << " " << flush;
    }
    cout << endl << "Label:" << endl;
    for (int i = 0; i < tasks1_offset[*tasks1_count]; i++) {
        cout << tasks1_vertices[i].label << " " << flush;
    }
    cout << endl << "Indeg:" << endl;
    for (int i = 0; i < tasks1_offset[*tasks1_count]; i++) {
        cout << tasks1_vertices[i].indeg << " " << flush;
    }
    cout << endl << "Exdeg:" << endl;
    for (int i = 0; i < tasks1_offset[*tasks1_count]; i++) {
        cout << tasks1_vertices[i].exdeg << " " << flush;
    }
    cout << endl << "Lvl2adj:" << endl;
    for (int i = 0; i < tasks1_offset[*tasks1_count]; i++) {
        cout << tasks1_vertices[i].lvl2adj << " " << flush;
    }
    cout << endl;

    cout << endl << "Tasks2: " << "Size: " << (*tasks2_count) << endl;
    cout << endl << "Offsets:" << endl;
    for (int i = 0; i <= (*tasks2_count); i++) {
        cout << tasks2_offset[i] << " " << flush;
    }
    cout << endl << "Vertex:" << endl;
    for (int i = 0; i < tasks2_offset[*tasks2_count]; i++) {
        cout << tasks2_vertices[i].vertexid << " " << flush;
    }
    cout << endl << "Label:" << endl;
    for (int i = 0; i < tasks2_offset[*tasks2_count]; i++) {
        cout << tasks2_vertices[i].label << " " << flush;
    }
    cout << endl << "Indeg:" << endl;
    for (int i = 0; i < tasks2_offset[*tasks2_count]; i++) {
        cout << tasks2_vertices[i].indeg << " " << flush;
    }
    cout << endl << "Exdeg:" << endl;
    for (int i = 0; i < tasks2_offset[*tasks2_count]; i++) {
        cout << tasks2_vertices[i].exdeg << " " << flush;
    }
    cout << endl << "Lvl2adj:" << endl;
    for (int i = 0; i < tasks2_offset[*tasks2_count]; i++) {
        cout << tasks2_vertices[i].lvl2adj << " " << flush;
    }
    cout << endl << endl;

    cout << endl << "Buffer: " << "Size: " << (*buffer_count) << endl;
    cout << endl << "Offsets:" << endl;
    for (int i = 0; i <= (*buffer_count); i++) {
        cout << buffer_offset[i] << " " << flush;
    }
    cout << endl << "Vertex:" << endl;
    for (int i = 0; i < buffer_offset[*buffer_count]; i++) {
        cout << buffer_vertices[i].vertexid << " " << flush;
    }
    cout << endl << "Label:" << endl;
    for (int i = 0; i < buffer_offset[*buffer_count]; i++) {
        cout << buffer_vertices[i].label << " " << flush;
    }
    cout << endl << "Indeg:" << endl;
    for (int i = 0; i < buffer_offset[*buffer_count]; i++) {
        cout << buffer_vertices[i].indeg << " " << flush;
    }
    cout << endl << "Exdeg:" << endl;
    for (int i = 0; i < buffer_offset[*buffer_count]; i++) {
        cout << buffer_vertices[i].exdeg << " " << flush;
    }
    cout << endl << "Lvl2adj:" << endl;
    for (int i = 0; i < buffer_offset[*buffer_count]; i++) {
        cout << buffer_vertices[i].lvl2adj << " " << flush;
    }
    cout << endl;

    delete current_level;

    delete tasks1_count;
    delete tasks1_offset;
    delete tasks1_vertices;

    delete tasks2_count;
    delete tasks2_offset;
    delete tasks2_vertices;

    delete buffer_count;
    delete buffer_offset;
    delete buffer_vertices;
}

// returns true if warp buffer was too small causing error
bool print_Warp_Data_Sizes(GPU_Data& dd)
{
    uint64_t* tasks_counts = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* tasks_sizes = new uint64_t[NUMBER_OF_WARPS];
    int tasks_tcount = 0;
    int tasks_tsize = 0;
    int tasks_mcount = 0;
    int tasks_msize = 0;
    uint64_t* cliques_counts = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* cliques_sizes = new uint64_t[NUMBER_OF_WARPS];
    int cliques_tcount = 0;
    int cliques_tsize = 0;
    int cliques_mcount = 0;
    int cliques_msize = 0;

    chkerr(cudaMemcpy(tasks_counts, dd.wtasks_count, sizeof(uint64_t) * NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_counts, dd.wcliques_count, sizeof(uint64_t) * NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        chkerr(cudaMemcpy(tasks_sizes + i, dd.wtasks_offset + (i * WTASKS_OFFSET_SIZE) + tasks_counts[i], sizeof(uint64_t), cudaMemcpyDeviceToHost));
        chkerr(cudaMemcpy(cliques_sizes + i, dd.wcliques_offset + (i * WCLIQUES_OFFSET_SIZE) + cliques_counts[i], sizeof(uint64_t), cudaMemcpyDeviceToHost));
    }

    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        tasks_tcount += tasks_counts[i];
        if (tasks_counts[i] > tasks_mcount) {
            tasks_mcount = tasks_counts[i];
        }
        tasks_tsize += tasks_sizes[i];
        if (tasks_sizes[i] > tasks_msize) {
            tasks_msize = tasks_sizes[i];
        }
        cliques_tcount += cliques_counts[i];
        if (cliques_counts[i] > cliques_mcount) {
            cliques_mcount = cliques_counts[i];
        }
        cliques_tsize += cliques_sizes[i];
        if (cliques_sizes[i] > cliques_msize) {
            cliques_msize = cliques_sizes[i];
        }
    }

    cout << "WTasks( TC: " << tasks_tcount << " TS: " << tasks_tsize << " MC: " << tasks_mcount << " MS: " << tasks_msize << ") WCliques ( TC: " << cliques_tcount << " TS: " << cliques_tsize << " MC: " << cliques_mcount << " MS: " << cliques_msize << ")" << endl;

    if (tasks_mcount > wto) {
        wto = tasks_mcount;
    }
    if (tasks_msize > wts) {
        wts = tasks_msize;
    }
    if (cliques_mcount > wco) {
        wco = cliques_mcount;
    }
    if (cliques_msize > wcs) {
        wcs = cliques_msize;
    }

    if (tasks_mcount > WTASKS_OFFSET_SIZE || tasks_msize > WTASKS_SIZE || cliques_mcount > WCLIQUES_OFFSET_SIZE || cliques_msize > WCLIQUES_SIZE) {
        cout << "!!! WBUFFER SIZE ERROR !!!" << endl;
        return true;
    }

    delete tasks_counts;
    delete tasks_sizes;
    delete cliques_counts;
    delete cliques_sizes;

    return false;
}

void print_All_Warp_Data_Sizes(GPU_Data& dd)
{
    uint64_t* tasks_counts = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* tasks_sizes = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* cliques_counts = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* cliques_sizes = new uint64_t[NUMBER_OF_WARPS];

    chkerr(cudaMemcpy(tasks_counts, dd.wtasks_count, sizeof(uint64_t) * NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_counts, dd.wcliques_count, sizeof(uint64_t) * NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        chkerr(cudaMemcpy(tasks_sizes + i, dd.wtasks_offset + (i * WTASKS_OFFSET_SIZE) + tasks_counts[i], sizeof(uint64_t), cudaMemcpyDeviceToHost));
        chkerr(cudaMemcpy(cliques_sizes + i, dd.wcliques_offset + (i * WCLIQUES_OFFSET_SIZE) + cliques_counts[i], sizeof(uint64_t), cudaMemcpyDeviceToHost));
    }

    cout << "WTasks Sizes: " << flush;
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        cout << i << ":" << tasks_counts[i] << " " << tasks_sizes[i] << " " << flush;
    }
    cout << "\nWCliques Sizez: " << flush;
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        cout << i << ":" << cliques_counts[i] << " " << cliques_sizes[i] << " " << flush;
    }

    delete tasks_counts;
    delete tasks_sizes;
    delete cliques_counts;
    delete cliques_sizes;
}

bool print_Warp_Data_Sizes_Every(GPU_Data& dd, int every)
{
    bool result = false;
    int level;
    chkerr(cudaMemcpy(&level, dd.current_level, sizeof(int), cudaMemcpyDeviceToHost));
    if (level % every == 0) {
        result = print_Warp_Data_Sizes(dd);
    }
    return result;
}

void print_All_Warp_Data_Sizes_Every(GPU_Data& dd, int every)
{
    int level;
    chkerr(cudaMemcpy(&level, dd.current_level, sizeof(int), cudaMemcpyDeviceToHost));
    if (level % every == 0) {
        print_All_Warp_Data_Sizes(dd);
    }
}

bool print_Data_Sizes_Every(GPU_Data& dd, int every)
{
    bool result = false;
    int level;
    chkerr(cudaMemcpy(&level, dd.current_level, sizeof(int), cudaMemcpyDeviceToHost));
    if (level % every == 0) {
        result = print_Data_Sizes(dd);
    }
    return result;
}

bool print_Data_Sizes(GPU_Data& dd)
{
    uint64_t* current_level = new uint64_t;
    uint64_t* tasks1_count = new uint64_t;
    uint64_t* tasks2_count = new uint64_t;
    uint64_t* buffer_count = new uint64_t;
    uint64_t* cliques_count = new uint64_t;
    uint64_t* tasks1_size = new uint64_t;
    uint64_t* tasks2_size = new uint64_t;
    uint64_t* buffer_size = new uint64_t;
    uint64_t* cliques_size = new uint64_t;

    chkerr(cudaMemcpy(current_level, dd.current_level, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks1_count, dd.tasks1_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks2_count, dd.tasks2_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(buffer_count, dd.buffer_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_count, dd.cliques_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks1_size, dd.tasks1_offset + (*tasks1_count), sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(tasks2_size, dd.tasks2_offset + (*tasks2_count), sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(buffer_size, dd.buffer_offset + (*buffer_count), sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_size, dd.cliques_offset + (*cliques_count), sizeof(uint64_t), cudaMemcpyDeviceToHost));

    cout << "L: " << (*current_level) << " T1: " << (*tasks1_count) << " " << (*tasks1_size) << " T2: " << (*tasks2_count) << " " << (*tasks2_size) << " B: " << (*buffer_count) << " " << (*buffer_size) << " C: " << 
        (*cliques_count) << " " << (*cliques_size) << endl << endl;

    if (*tasks1_size > mts) {
        mts = *tasks1_size;
    }
    if (*tasks2_size > mts) {
        mts = *tasks2_size;
    }
    if (*buffer_size > mbs) {
        mbs = *buffer_size;
    }
    if (*buffer_count > mbo) {
        mbo = *buffer_count;
    }
    if (*cliques_size > mcs) {
        mcs = *cliques_size;
    }
    if (*cliques_count > mco) {
        mco = *cliques_count;
    }

    if ((*tasks1_count) > EXPAND_THRESHOLD || (*tasks1_size) > TASKS_SIZE || (*tasks2_count) > EXPAND_THRESHOLD || (*tasks2_size) > TASKS_SIZE || (*buffer_count) > BUFFER_OFFSET_SIZE || (*buffer_size) > BUFFER_SIZE || (*cliques_count) > CLIQUES_OFFSET_SIZE ||
        (*cliques_size) > CLIQUES_SIZE) {
        cout << "!!! ARRAY SIZE ERROR !!!" << endl;
        return true;
    }

    delete current_level;
    delete tasks1_count;
    delete tasks2_count;
    delete buffer_count;
    delete cliques_count;
    delete tasks1_size;
    delete tasks2_size;
    delete buffer_size;
    delete cliques_size;
    
    return false;
}

void h_print_Data_Sizes(CPU_Data& hd, CPU_Cliques& hc)
{
    cout << "L: " << (*hd.current_level) << " T1: " << (*hd.tasks1_count) << " " << (*(hd.tasks1_offset + (*hd.tasks1_count))) << " T2: " << (*hd.tasks2_count) << " " << 
        (*(hd.tasks2_offset + (*hd.tasks2_count))) << " B: " << (*hd.buffer_count) << " " << (*(hd.buffer_offset + (*hd.buffer_count))) << " C: " << 
        (*hc.cliques_count) << " " << (*(hc.cliques_offset + (*hc.cliques_count))) << endl;

    if ((*(hd.tasks1_offset + (*hd.tasks1_count))) > mts) {
        mts = (*(hd.tasks1_offset + (*hd.tasks1_count)));
    }
    if ((*(hd.tasks2_offset + (*hd.tasks2_count))) > mts) {
        mts = (*(hd.tasks2_offset + (*hd.tasks2_count)));
    }
    if ((*(hd.buffer_offset + (*hd.buffer_count))) > mbs) {
        mbs = (*(hd.buffer_offset + (*hd.buffer_count)));
    }
    if ((*hd.buffer_count) > mbo) {
        mbo = (*hd.buffer_count);
    }
    if ((*(hc.cliques_offset + (*hc.cliques_count))) > mcs) {
        mcs = (*(hc.cliques_offset + (*hc.cliques_count)));
    }
    if ((*hc.cliques_count) > mco) {
        mco = (*hc.cliques_count);
    }
}

void print_WTask_Buffers(GPU_Data& dd)
{
    uint64_t* wtasks_count = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* wtasks_offset = new uint64_t[NUMBER_OF_WARPS*WTASKS_OFFSET_SIZE];
    Vertex* wtasks_vertices = new Vertex[NUMBER_OF_WARPS*WTASKS_SIZE];

    chkerr(cudaMemcpy(wtasks_count, dd.wtasks_count, sizeof(uint64_t)*NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(wtasks_offset, dd.wtasks_offset, sizeof(uint64_t) * (NUMBER_OF_WARPS*WTASKS_OFFSET_SIZE), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(wtasks_vertices, dd.wtasks_vertices, sizeof(Vertex) * (NUMBER_OF_WARPS*WTASKS_SIZE), cudaMemcpyDeviceToHost));

    cout << endl << " --- Warp Task Buffers details --- " << endl;
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        int wtasks_offset_start = WTASKS_OFFSET_SIZE * i;
        int wtasks_start = WTASKS_SIZE * i;

        cout << endl << "Warp " << i << ": " << "Size : " << wtasks_count[i] << endl;
        if (wtasks_count[i] == 0) {
            continue;
        }
        cout << "Offsets:" << endl;
        for (int j = 0; j <= wtasks_count[i]; j++) {
            cout << wtasks_offset[wtasks_offset_start+j] << " ";
        }
        cout << endl << "Vertex:" << endl;
        for (int j = 0; j < wtasks_offset[wtasks_offset_start+wtasks_count[i]]; j++) {
            cout << wtasks_vertices[wtasks_start+j].vertexid << " ";
        }
        cout << endl << "Label:" << endl;
        for (int j = 0; j < wtasks_offset[wtasks_offset_start + wtasks_count[i]]; j++) {
            cout << wtasks_vertices[wtasks_start + j].label << " ";
        }
        cout << endl << "Indeg:" << endl;
        for (int j = 0; j < wtasks_offset[wtasks_offset_start + wtasks_count[i]]; j++) {
            cout << wtasks_vertices[wtasks_start + j].indeg << " ";
        }
        cout << endl << "Exdeg:" << endl;
        for (int j = 0; j < wtasks_offset[wtasks_offset_start + wtasks_count[i]]; j++) {
            cout << wtasks_vertices[wtasks_start + j].exdeg << " ";
        }
        cout << endl << "Lvl2adj:" << endl;
        for (int j = 0; j < wtasks_offset[wtasks_offset_start + wtasks_count[i]]; j++) {
            cout << wtasks_vertices[wtasks_start + j].lvl2adj << " ";
        }
        cout << endl;
    }
    cout << endl << endl;

    delete wtasks_count;
    delete wtasks_offset;
    delete wtasks_vertices;
}

void print_WClique_Buffers(GPU_Data& dd)
{
    uint64_t* wcliques_count = new uint64_t[NUMBER_OF_WARPS];
    uint64_t* wcliques_offset = new uint64_t[NUMBER_OF_WARPS * WCLIQUES_OFFSET_SIZE];
    int* wcliques_vertex = new int[NUMBER_OF_WARPS * WCLIQUES_SIZE];

    chkerr(cudaMemcpy(wcliques_count, dd.wcliques_count, sizeof(uint64_t) * NUMBER_OF_WARPS, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(wcliques_offset, dd.wcliques_offset, sizeof(uint64_t) * (NUMBER_OF_WARPS * WTASKS_OFFSET_SIZE), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(wcliques_vertex, dd.wcliques_vertex, sizeof(int) * (NUMBER_OF_WARPS * WTASKS_SIZE), cudaMemcpyDeviceToHost));

    cout << endl << " --- Warp Clique Buffers details --- " << endl;
    for (int i = 0; i < NUMBER_OF_WARPS; i++) {
        int wcliques_offset_start = WTASKS_OFFSET_SIZE * i;
        int wcliques_start = WTASKS_SIZE * i;

        cout << endl << "Warp " << i << ": " << "Size : " << wcliques_count[i] << endl;
        cout << "Offsets:" << endl;
        for (int j = 0; j <= wcliques_count[i]; j++) {
            cout << wcliques_offset[wcliques_offset_start + j] << " ";
        }
        cout << endl << "Vertex:" << endl;
        for (int j = 0; j < wcliques_offset[wcliques_offset_start + wcliques_count[i]]; j++) {
            cout << wcliques_vertex[wcliques_start + j] << " ";
        }
    }
    cout << endl << endl;

    delete wcliques_count;
    delete wcliques_offset;
    delete wcliques_vertex;
}

void print_GPU_Cliques(GPU_Data& dd)
{
    uint64_t* cliques_count = new uint64_t;
    uint64_t* cliques_offset = new uint64_t[CLIQUES_OFFSET_SIZE];
    int* cliques_vertex = new int[CLIQUES_SIZE];

    chkerr(cudaMemcpy(cliques_count, dd.cliques_count, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_offset, dd.cliques_offset, sizeof(uint64_t) * CLIQUES_OFFSET_SIZE, cudaMemcpyDeviceToHost));
    chkerr(cudaMemcpy(cliques_vertex, dd.cliques_vertex, sizeof(int) * CLIQUES_SIZE, cudaMemcpyDeviceToHost));

    cout << endl << " --- (GPU_Cliques)device_cliques details --- " << endl;
    cout << endl << "Cliques: " << "Size: " << (*cliques_count) << endl;
    cout << endl << "Offsets:" << endl;
    for (uint64_t i = 0; i <= (*cliques_count); i++) {
        cout << cliques_offset[i] << " ";
    }

    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < (*cliques_count); i++) {
        cout << i << " S: " << cliques_offset[i] << " E: " << cliques_offset[i+1] << " " << flush;
        for (uint64_t j = cliques_offset[i]; j < cliques_offset[i + 1]; j++) {
            cout << cliques_vertex[j] << " " << flush;
        }
        cout << endl;
    }

    delete cliques_count;
    delete cliques_offset;
    delete cliques_vertex;

    return;

    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < cliques_offset[(*cliques_count)]; i++) {
        cout << cliques_vertex[i] << " ";
    }
    cout << endl;
}

void print_CPU_Cliques(CPU_Cliques& hc)
{
    cout << endl << " --- (CPU_Cliques)host_cliques details --- " << endl;
    cout << endl << "Cliques: " << "Size: " << (*(hc.cliques_count)) << endl;
    cout << endl << "Offsets:" << endl;
    for (uint64_t i = 0; i <= (*(hc.cliques_count)); i++) {
        cout << hc.cliques_offset[i] << " ";
    }
    cout << endl << "Vertex:" << endl;
    for (uint64_t i = 0; i < hc.cliques_offset[(*(hc.cliques_count))]; i++) {
        cout << hc.cliques_vertex[i] << " ";
    }
    cout << endl;
}

void print_vertices(Vertex* vertices, int size)
{
    cout << " --- level 0 details --- " << endl;
    cout << endl << "Tasks1: Level: " << 0 << " Size: " << size << endl;
    cout << endl << "Offsets:" << endl;
    cout << "0 " << size << flush;
    cout << endl << "Vertex:" << endl;
    for (int i = 0; i < size; i++) {
        cout << vertices[i].vertexid << " " << flush;
    }
    cout << endl << "Label:" << endl;
    for (int i = 0; i < size; i++) {
        cout << vertices[i].label << " " << flush;
    }
    cout << endl << "Indeg:" << endl;
    for (int i = 0; i < size; i++) {
        cout << vertices[i].indeg << " " << flush;
    }
    cout << endl << "Exdeg:" << endl;
    for (int i = 0; i < size; i++) {
        cout << vertices[i].exdeg << " " << flush;
    }
    cout << endl << "Lvl2adj:" << endl;
    for (int i = 0; i < size; i++) {
        cout << vertices[i].lvl2adj << " " << flush;
    }
    cout << endl;
}

void initialize_maxes()
{
    mts = 0;
    mbs = 0;
    mbo = 0;
    mcs = 0;
    mco = 0;
    wts = 0;
    wto = 0;
    wcs = 0;
    wco = 0;
    mvs = 0;
}

void print_maxes()
{
    cout << endl
        << "TASKS SIZE: " << mts << endl
        << "BUFFER SIZE: " << mbs << endl
        << "BUFFER OFFSET SIZE: " << mbo << endl
        << "CLIQUES SIZE: " << mcs << endl
        << "CLIQUES OFFSET SIZE: " << mco << endl
        << "WCLIQUES SIZE: " << wcs << endl
        << "WCLIQUES OFFSET SIZE: " << wco << endl
        << "WTASKS SIZE: " << wts << endl
        << "WTASKS OFFSET SIZE: " << wto << endl
        << "VERTICES SIZE: " << mvs << endl
        << endl;
}



// --- DEVICE KERNELS ---

__global__ void d_expand_level(GPU_Data dd)
{
    // data is stored in data structures to reduce the number of variables that need to be passed to methods
    __shared__ Warp_Data wd;
    Local_Data ld;

    // helper variables, not passed through to any methods
    int num_mem;
    int method_return;
    int index;



    /*
    * The program alternates between reading and writing between to 'tasks' arrays in device global memory. The program will read from one tasks, expand to the next level by generating and pruning, then it will write to the
    * other tasks array. It will write the first EXPAND_THRESHOLD to the tasks array and the rest to the top of the buffer. The buffers acts as a stack containing the excess data not being expanded from tasks. Since the 
    * buffer acts as a stack, in a last-in first-out manner, a subsection of the search space will be expanded until completion. This system allows the problem to essentially be divided into smaller problems and thus 
    * require less memory to handle.
    */
    if ((*(dd.current_level)) % 2 == 0) {
        dd.read_count = dd.tasks1_count;
        dd.read_offsets = dd.tasks1_offset;
        dd.read_vertices = dd.tasks1_vertices;
    }
    else {
        dd.read_count = dd.tasks2_count;
        dd.read_offsets = dd.tasks2_offset;
        dd.read_vertices = dd.tasks2_vertices;
    }



    // --- CURRENT LEVEL ---

    // scheduling toggle = 0, dynamic intersection
    if (*dd.scheduling_toggle == 0) {
        // initialize i for each warp
        int i = 0;
        if (LANE_IDX == 0) {
            i = atomicAdd(dd.current_task, 1);
        }
        i = __shfl_sync(0xFFFFFFFF, i, 0);

        while (i < (*(dd.read_count)))
        {
            // get information on vertices being handled within tasks
            if (LANE_IDX == 0) {
                wd.start[WIB_IDX] = dd.read_offsets[i];
                wd.end[WIB_IDX] = dd.read_offsets[i + 1];
                wd.tot_vert[WIB_IDX] = wd.end[WIB_IDX] - wd.start[WIB_IDX];
            }
            __syncwarp();

            // each warp gets partial number of members
            num_mem = 0;
            for (uint64_t j = wd.start[WIB_IDX] + LANE_IDX; j < wd.end[WIB_IDX]; j += WARP_SIZE) {
                if (dd.read_vertices[j].label != 1) {
                    break;
                }
                num_mem++;
            }
            // sum members across warp
            for (int k = 1; k < 32; k *= 2) {
                num_mem += __shfl_xor_sync(0xFFFFFFFF, num_mem, k);
            }

            if (LANE_IDX == 0) {
                wd.num_mem[WIB_IDX] = num_mem;
                wd.num_cand[WIB_IDX] = wd.tot_vert[WIB_IDX] - wd.num_mem[WIB_IDX];
                wd.expansions[WIB_IDX] = wd.num_cand[WIB_IDX];
            }
            __syncwarp();




            // LOOKAHEAD PRUNING
            method_return = d_lookahead_pruning(dd, wd, ld);
            if (method_return) {
                // schedule warps next task
                if (LANE_IDX == 0) {
                    i = atomicAdd(dd.current_task, 1);
                }
                i = __shfl_sync(0xFFFFFFFF, i, 0);
                continue;
            }



            // --- NEXT LEVEL ---
            for (int j = 0; j < wd.expansions[WIB_IDX]; j++)
            {



                // REMOVE ONE VERTEX
                if (j > 0) {
                    method_return = d_remove_one_vertex(dd, wd, ld);
                    if (method_return) {
                        break;
                    }
                }



                // INITIALIZE NEW VERTICES
                if (LANE_IDX == 0) {
                    wd.number_of_members[WIB_IDX] = wd.num_mem[WIB_IDX];
                    wd.number_of_candidates[WIB_IDX] = wd.num_cand[WIB_IDX];
                    wd.total_vertices[WIB_IDX] = wd.tot_vert[WIB_IDX];
                }
                __syncwarp();

                // select whether to store vertices in global or shared memory based on size
                if (wd.total_vertices[WIB_IDX] <= VERTICES_SIZE) {
                    ld.vertices = wd.shared_vertices + (VERTICES_SIZE * WIB_IDX);
                }
                else {
                    ld.vertices = dd.global_vertices + (WVERTICES_SIZE * WARP_IDX);
                }

                for (index = LANE_IDX; index < wd.number_of_members[WIB_IDX]; index += WARP_SIZE) {
                    ld.vertices[index] = dd.read_vertices[wd.start[WIB_IDX] + index];
                }
                for (; index < wd.total_vertices[WIB_IDX] - 1; index += WARP_SIZE) {
                    ld.vertices[index + 1] = dd.read_vertices[wd.start[WIB_IDX] + index];
                }

                if (LANE_IDX == 0) {
                    ld.vertices[wd.number_of_members[WIB_IDX]] = dd.read_vertices[wd.start[WIB_IDX] + wd.total_vertices[WIB_IDX] - 1];
                }
                __syncwarp();



                // ADD ONE VERTEX
                method_return = d_add_one_vertex(dd, wd, ld);

                // if failed found check for clique and continue on to the next iteration
                if (method_return == 1) {
                    if (wd.number_of_members[WIB_IDX] >= (*dd.minimum_clique_size)) {
                        d_check_for_clique(dd, wd, ld);
                    }
                    continue;
                }



                // CRITICAL VERTEX PRUNING
                method_return = d_critical_vertex_pruning(dd, wd, ld);

                // critical fail, cannot be clique continue onto next iteration
                if (method_return == 2) {
                    continue;
                }



                // HANDLE CLIQUES
                if (wd.number_of_members[WIB_IDX] >= (*dd.minimum_clique_size)) {
                    d_check_for_clique(dd, wd, ld);
                }

                // if vertex in x found as not extendable continue to next iteration
                if (method_return == 1) {
                    continue;
                }



                // WRITE TASKS TO BUFFERS
                // sort vertices in Quick efficient enumeration order before writing
                d_sort(ld.vertices, wd.total_vertices[WIB_IDX], d_sort_vert_Q);

                if (wd.number_of_candidates[WIB_IDX] > 0) {
                    d_write_to_tasks(dd, wd, ld);
                }
            }



            // schedule warps next task
            if (LANE_IDX == 0) {
                i = atomicAdd(dd.current_task, 1);
            }
            i = __shfl_sync(0xFFFFFFFF, i, 0);
        }
    }
    else {
        for (int i = WARP_IDX; i < (*(dd.read_count)); i += NUMBER_OF_WARPS)
        {
            // get information on vertices being handled within tasks
            if (LANE_IDX == 0) {
                wd.start[WIB_IDX] = dd.read_offsets[i];
                wd.end[WIB_IDX] = dd.read_offsets[i + 1];
                wd.tot_vert[WIB_IDX] = wd.end[WIB_IDX] - wd.start[WIB_IDX];
            }
            __syncwarp();

            // each warp gets partial number of members
            num_mem = 0;
            for (uint64_t j = wd.start[WIB_IDX] + LANE_IDX; j < wd.end[WIB_IDX]; j += WARP_SIZE) {
                if (dd.read_vertices[j].label != 1) {
                    break;
                }
                num_mem++;
            }
            // sum members across warp
            for (int k = 1; k < 32; k *= 2) {
                num_mem += __shfl_xor_sync(0xFFFFFFFF, num_mem, k);
            }

            if (LANE_IDX == 0) {
                wd.num_mem[WIB_IDX] = num_mem;
                wd.num_cand[WIB_IDX] = wd.tot_vert[WIB_IDX] - wd.num_mem[WIB_IDX];
                wd.expansions[WIB_IDX] = wd.num_cand[WIB_IDX];
            }
            __syncwarp();




            // LOOKAHEAD PRUNING
            method_return = d_lookahead_pruning(dd, wd, ld);
            if (method_return) {
                continue;
            }



            // --- NEXT LEVEL ---
            for (int j = 0; j < wd.expansions[WIB_IDX]; j++)
            {



                // REMOVE ONE VERTEX
                if (j > 0) {
                    method_return = d_remove_one_vertex(dd, wd, ld);
                    if (method_return) {
                        break;
                    }
                }



                // INITIALIZE NEW VERTICES
                if (LANE_IDX == 0) {
                    wd.number_of_members[WIB_IDX] = wd.num_mem[WIB_IDX];
                    wd.number_of_candidates[WIB_IDX] = wd.num_cand[WIB_IDX];
                    wd.total_vertices[WIB_IDX] = wd.tot_vert[WIB_IDX];
                }
                __syncwarp();

                // select whether to store vertices in global or shared memory based on size
                if (wd.total_vertices[WIB_IDX] <= VERTICES_SIZE) {
                    ld.vertices = wd.shared_vertices + (VERTICES_SIZE * WIB_IDX);
                }
                else {
                    ld.vertices = dd.global_vertices + (WVERTICES_SIZE * WARP_IDX);
                }

                for (index = LANE_IDX; index < wd.number_of_members[WIB_IDX]; index += WARP_SIZE) {
                    ld.vertices[index] = dd.read_vertices[wd.start[WIB_IDX] + index];
                }
                for (; index < wd.total_vertices[WIB_IDX] - 1; index += WARP_SIZE) {
                    ld.vertices[index + 1] = dd.read_vertices[wd.start[WIB_IDX] + index];
                }

                if (LANE_IDX == 0) {
                    ld.vertices[wd.number_of_members[WIB_IDX]] = dd.read_vertices[wd.start[WIB_IDX] + wd.total_vertices[WIB_IDX] - 1];
                }
                __syncwarp();



                // ADD ONE VERTEX
                method_return = d_add_one_vertex(dd, wd, ld);

                // if failed found check for clique and continue on to the next iteration
                if (method_return == 1) {
                    if (wd.number_of_members[WIB_IDX] >= (*dd.minimum_clique_size)) {
                        d_check_for_clique(dd, wd, ld);
                    }
                    continue;
                }



                // CRITICAL VERTEX PRUNING
                method_return = d_critical_vertex_pruning(dd, wd, ld);

                // critical fail, cannot be clique continue onto next iteration
                if (method_return == 2) {
                    continue;
                }



                // HANDLE CLIQUES
                if (wd.number_of_members[WIB_IDX] >= (*dd.minimum_clique_size)) {
                    d_check_for_clique(dd, wd, ld);
                }

                // if vertex in x found as not extendable continue to next iteration
                if (method_return == 1) {
                    continue;
                }



                // WRITE TASKS TO BUFFERS
                // sort vertices in Quick efficient enumeration order before writing
                d_sort(ld.vertices, wd.total_vertices[WIB_IDX], d_sort_vert_Q);

                if (wd.number_of_candidates[WIB_IDX] > 0) {
                    d_write_to_tasks(dd, wd, ld);
                }
            }
        }
    }



    if (LANE_IDX == 0) {
        // sum to find tasks count
        atomicAdd(dd.total_tasks, dd.wtasks_count[WARP_IDX]);
        atomicAdd(dd.total_cliques, dd.wcliques_count[WARP_IDX]);
    }

    if (IDX == 0) {
        (*(dd.buffer_offset_start)) = (*(dd.buffer_count)) + 1;
        (*(dd.buffer_start)) = dd.buffer_offset[(*(dd.buffer_count))];
        (*(dd.cliques_offset_start)) = (*(dd.cliques_count)) + 1;
        (*(dd.cliques_start)) = dd.cliques_offset[(*(dd.cliques_count))];
    }
}

__global__ void transfer_buffers(GPU_Data dd)
{
    __shared__ uint64_t tasks_write[WARPS_PER_BLOCK];
    __shared__ int tasks_offset_write[WARPS_PER_BLOCK];
    __shared__ uint64_t cliques_write[WARPS_PER_BLOCK];
    __shared__ int cliques_offset_write[WARPS_PER_BLOCK];

    __shared__ int twarp;
    __shared__ int toffsetwrite;
    __shared__ int twrite;
    __shared__ int tasks_end;

    if ((*(dd.current_level)) % 2 == 0) {
        dd.write_count = dd.tasks2_count;
        dd.write_offsets = dd.tasks2_offset;
        dd.write_vertices = dd.tasks2_vertices;
    }
    else {
        dd.write_count = dd.tasks1_count;
        dd.write_offsets = dd.tasks1_offset;
        dd.write_vertices = dd.tasks1_vertices;
    }

    // point of this is to find how many vertices will be transfered to tasks, it is easy to know how many tasks as it will just
    // be the expansion threshold, but to find how many vertices we must now the total size of all the tasks that will be copied.
    // each block does this but really could be done by one thread outside the GPU
    if (threadIdx.x == 0) {
        toffsetwrite = 0;
        twrite = 0;

        for (int i = 0; i < NUMBER_OF_WARPS; i++) {
            // if next warps count is more than expand threshold mark as such and break
            if (toffsetwrite + dd.wtasks_count[i] >= EXPAND_THRESHOLD) {
                twarp = i;
                break;
            }
            // else adds its size and count
            twrite += dd.wtasks_offset[(WTASKS_OFFSET_SIZE * i) + dd.wtasks_count[i]];
            toffsetwrite += dd.wtasks_count[i];
        }
        // final size is the size of all tasks up until last warp and the remaining tasks in the last warp until expand threshold is satisfied
        tasks_end = twrite + dd.wtasks_offset[(WTASKS_OFFSET_SIZE * twarp) + (EXPAND_THRESHOLD - toffsetwrite)];
    }
    __syncthreads();

    // warp level
    if (LANE_IDX == 0)
    {
        tasks_write[WIB_IDX] = 0;
        tasks_offset_write[WIB_IDX] = 1;
        cliques_write[WIB_IDX] = 0;
        cliques_offset_write[WIB_IDX] = 1;

        for (int i = 0; i < WARP_IDX; i++) {
            tasks_offset_write[WIB_IDX] += dd.wtasks_count[i];
            tasks_write[WIB_IDX] += dd.wtasks_offset[(WTASKS_OFFSET_SIZE * i) + dd.wtasks_count[i]];

            cliques_offset_write[WIB_IDX] += dd.wcliques_count[i];
            cliques_write[WIB_IDX] += dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * i) + dd.wcliques_count[i]];
        }
    }
    __syncwarp();
    
    // move to tasks and buffer
    for (int i = LANE_IDX + 1; i <= dd.wtasks_count[WARP_IDX]; i += WARP_SIZE)
    {
        if (tasks_offset_write[WIB_IDX] + i - 1 <= EXPAND_THRESHOLD) {
            // to tasks
            dd.write_offsets[tasks_offset_write[WIB_IDX] + i - 1] = dd.wtasks_offset[(WTASKS_OFFSET_SIZE * WARP_IDX) + i] + tasks_write[WIB_IDX];
        }
        else {
            // to buffer
            dd.buffer_offset[tasks_offset_write[WIB_IDX] + i - 2 - EXPAND_THRESHOLD + (*(dd.buffer_offset_start))] = dd.wtasks_offset[(WTASKS_OFFSET_SIZE * WARP_IDX) + i] +
                tasks_write[WIB_IDX] - tasks_end + (*(dd.buffer_start));
        }
    }

    for (int i = LANE_IDX; i < dd.wtasks_offset[(WTASKS_OFFSET_SIZE * WARP_IDX) + dd.wtasks_count[WARP_IDX]]; i += WARP_SIZE) {
        if (tasks_write[WIB_IDX] + i < tasks_end) {
            // to tasks
            dd.write_vertices[tasks_write[WIB_IDX] + i] = dd.wtasks_vertices[(WTASKS_SIZE * WARP_IDX) + i];
        }
        else {
            // to buffer
            dd.buffer_vertices[(*(dd.buffer_start)) + tasks_write[WIB_IDX] + i - tasks_end] = dd.wtasks_vertices[(WTASKS_SIZE * WARP_IDX) + i];
        }
    }

    //move to cliques
    for (int i = LANE_IDX + 1; i <= dd.wcliques_count[WARP_IDX]; i += WARP_SIZE) {
        dd.cliques_offset[(*(dd.cliques_offset_start)) + cliques_offset_write[WIB_IDX] + i - 2] = dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + i] + (*(dd.cliques_start)) + 
            cliques_write[WIB_IDX];
    }
    for (int i = LANE_IDX; i < dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + dd.wcliques_count[WARP_IDX]]; i += WARP_SIZE) {
        dd.cliques_vertex[(*(dd.cliques_start)) + cliques_write[WIB_IDX] + i] = dd.wcliques_vertex[(WCLIQUES_SIZE * WARP_IDX) + i];
    }

    if (IDX == 0) {
        // handle tasks and buffer counts
        if ((*dd.total_tasks) <= EXPAND_THRESHOLD) {
            (*dd.write_count) = (*(dd.total_tasks));
        }
        else {
            (*dd.write_count) = EXPAND_THRESHOLD;
            (*(dd.buffer_count)) += ((*(dd.total_tasks)) - EXPAND_THRESHOLD);
        }
        (*(dd.cliques_count)) += (*(dd.total_cliques));

        (*(dd.total_tasks)) = 0;
        (*(dd.total_cliques)) = 0;
    }
}

__global__ void fill_from_buffer(GPU_Data dd)
{
    if ((*(dd.current_level)) % 2 == 0) {
        dd.write_count = dd.tasks2_count;
        dd.write_offsets = dd.tasks2_offset;
        dd.write_vertices = dd.tasks2_vertices;
    }
    else {
        dd.write_count = dd.tasks1_count;
        dd.write_offsets = dd.tasks1_offset;
        dd.write_vertices = dd.tasks1_vertices;
    }

    // get read and write locations
    int write_amount = ((*(dd.buffer_count)) >= (EXPAND_THRESHOLD - (*dd.write_count))) ? EXPAND_THRESHOLD - (*dd.write_count) : (*(dd.buffer_count));
    uint64_t start_buffer = dd.buffer_offset[(*(dd.buffer_count)) - write_amount];
    uint64_t end_buffer = dd.buffer_offset[(*(dd.buffer_count))];
    uint64_t size_buffer = end_buffer - start_buffer;
    uint64_t start_write = dd.write_offsets[(*dd.write_count)];

    // handle offsets
    for (int i = IDX + 1; i <= write_amount; i += NUMBER_OF_THREADS) {
        dd.write_offsets[(*dd.write_count) + i] = start_write + (dd.buffer_offset[(*(dd.buffer_count)) - write_amount + i] - start_buffer);
    }

    // handle data
    for (int i = IDX; i < size_buffer; i += NUMBER_OF_THREADS) {
        dd.write_vertices[start_write + i] = dd.buffer_vertices[start_buffer + i];
    }

    if (IDX == 0) {
        (*dd.write_count) += write_amount;
        (*(dd.buffer_count)) -= write_amount;
    }
}



// --- DEVICE EXPANSION KERNELS ---

// returns 1 if lookahead succesful, 0 otherwise 
__device__ int d_lookahead_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    int pvertexid;
    int phelper1;
    int phelper2;

    if (LANE_IDX == 0) {
        wd.success[WIB_IDX] = true;
    }
    __syncwarp();

    // check if members meet degree requirement, dont need to check 2hop adj as diameter pruning guarentees all members will be within 2hops of eveything
    for (int i = LANE_IDX; i < wd.num_mem[WIB_IDX] && wd.success[WIB_IDX]; i += WARP_SIZE) {
        if (dd.read_vertices[wd.start[WIB_IDX] + i].indeg + dd.read_vertices[wd.start[WIB_IDX] + i].exdeg < dd.minimum_degrees[wd.tot_vert[WIB_IDX]]) {
            wd.success[WIB_IDX] = false;
            break;
        }
    }
    __syncwarp();

    if (!wd.success[WIB_IDX]) {
        return 0;
    }

    // update lvl2adj to candidates for all vertices
    for (int i = wd.num_mem[WIB_IDX] + LANE_IDX; i < wd.tot_vert[WIB_IDX]; i += WARP_SIZE) {
        pvertexid = dd.read_vertices[wd.start[WIB_IDX] + i].vertexid;
        
        for (int j = wd.num_mem[WIB_IDX]; j < wd.tot_vert[WIB_IDX]; j++) {
            if (j == i) {
                continue;
            }

            phelper1 = dd.read_vertices[wd.start[WIB_IDX] + j].vertexid;
            phelper2 = d_bsearch_array(dd.twohop_neighbors + dd.twohop_offsets[phelper1], dd.twohop_offsets[phelper1 + 1] - dd.twohop_offsets[phelper1], pvertexid);
        
            if (phelper2 > -1) {
                dd.read_vertices[wd.start[WIB_IDX] + i].lvl2adj++;
            }
        }
    }
    __syncwarp();

    // compares all vertices to the lemmas from Quick
    for (int j = wd.num_mem[WIB_IDX] + LANE_IDX; j < wd.tot_vert[WIB_IDX] && wd.success[WIB_IDX]; j += WARP_SIZE) {
        if (dd.read_vertices[wd.start[WIB_IDX] + j].lvl2adj < wd.num_cand[WIB_IDX] - 1 || dd.read_vertices[wd.start[WIB_IDX] + j].indeg + dd.read_vertices[wd.start[WIB_IDX] + j].exdeg < dd.minimum_degrees[wd.tot_vert[WIB_IDX]]) {
            wd.success[WIB_IDX] = false;
            break;
        }
    }
    __syncwarp();

    if (wd.success[WIB_IDX]) {
        // write to cliques
        uint64_t start_write = (WCLIQUES_SIZE * WARP_IDX) + dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + (dd.wcliques_count[WARP_IDX])];
        for (int j = LANE_IDX; j < wd.tot_vert[WIB_IDX]; j += WARP_SIZE) {
            dd.wcliques_vertex[start_write + j] = dd.read_vertices[wd.start[WIB_IDX] + j].vertexid;
        }
        if (LANE_IDX == 0) {
            (dd.wcliques_count[WARP_IDX])++;
            dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + (dd.wcliques_count[WARP_IDX])] = start_write - (WCLIQUES_SIZE * WARP_IDX) + wd.tot_vert[WIB_IDX];
        }
        return 1;
    }

    return 0;
}

// returns 1 if failed found after removing, 0 otherwise
__device__ int d_remove_one_vertex(GPU_Data& dd, Warp_Data& wd, Local_Data& ld) 
{
    int pvertexid;
    int phelper1;
    int phelper2;

    int mindeg;

    mindeg = d_get_mindeg(wd.num_mem[WIB_IDX], dd);

    // remove the last candidate in vertices
    if (LANE_IDX == 0) {
        wd.num_cand[WIB_IDX]--;
        wd.tot_vert[WIB_IDX]--;
        wd.success[WIB_IDX] = false;
    }
    __syncwarp();

    // update info of vertices connected to removed cand
    pvertexid = dd.read_vertices[wd.start[WIB_IDX] + wd.tot_vert[WIB_IDX]].vertexid;

    for (int i = LANE_IDX; i < wd.tot_vert[WIB_IDX] && !wd.success[WIB_IDX]; i += WARP_SIZE) {
        phelper1 = dd.read_vertices[wd.start[WIB_IDX] + i].vertexid;
        phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[pvertexid], dd.onehop_offsets[pvertexid + 1] - dd.onehop_offsets[pvertexid], phelper1);

        if (phelper2 > -1) {
            dd.read_vertices[wd.start[WIB_IDX] + i].exdeg--;

            if (phelper1 < wd.num_mem[WIB_IDX] && dd.read_vertices[wd.start[WIB_IDX] + phelper1].indeg + dd.read_vertices[wd.start[WIB_IDX] + phelper1].exdeg < mindeg) {
                wd.success[WIB_IDX] = true;
                break;
            }
        }
    }
    __syncwarp();

    if (wd.success[WIB_IDX]) {
        return 1;
    }

    return 0;
}

// returns 1 if failed found or invalid bound, 0 otherwise
__device__ int d_add_one_vertex(GPU_Data& dd, Warp_Data& wd, Local_Data& ld) 
{
    int pvertexid;
    int phelper1;
    int phelper2;
    bool failed_found;



    // ADD ONE VERTEX
    pvertexid = ld.vertices[wd.number_of_members[WIB_IDX]].vertexid;

    if (LANE_IDX == 0) {
        ld.vertices[wd.number_of_members[WIB_IDX]].label = 1;
        wd.number_of_members[WIB_IDX]++;
        wd.number_of_candidates[WIB_IDX]--;
    }
    __syncwarp();

    for (int i = LANE_IDX; i < wd.tot_vert[WIB_IDX]; i += WARP_SIZE) {
        phelper1 = ld.vertices[i].vertexid;
        phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[pvertexid], dd.onehop_offsets[pvertexid + 1] - dd.onehop_offsets[pvertexid], phelper1);

        if (phelper2 > -1) {
            ld.vertices[i].exdeg--;
            ld.vertices[i].indeg++;
        }
    }
    __syncwarp();



    // DIAMETER PRUNING
    d_diameter_pruning(dd, wd, ld, pvertexid);



    // DEGREE BASED PRUNING
    failed_found = d_degree_pruning(dd, wd, ld);

    // if vertex in x found as not extendable continue to next iteration
    if (failed_found) {
        return 1;
    }
   
    return 0;
}

// returns 2, if critical fail, 1 if failed found or invalid bound, 0 otherwise
__device__ int d_critical_vertex_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    // intersection
    int phelper1;

    // pruning
    int number_of_crit_adj;
    bool failed_found;



    // CRITICAL VERTEX PRUNING 
    // iterate through all vertices in clique
    for (int k = 0; k < wd.number_of_members[WIB_IDX]; k++) {

        // if they are a critical vertex
        if (ld.vertices[k].indeg + ld.vertices[k].exdeg == dd.minimum_degrees[wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX]] && ld.vertices[k].exdeg > 0) {
            phelper1 = ld.vertices[k].vertexid;

            // iterate through all candidates
            for (int i = wd.number_of_members[WIB_IDX] + LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
                if (ld.vertices[i].label != 4) {
                    // if candidate is neighbor of critical vertex mark as such
                    if (d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], ld.vertices[i].vertexid) > -1) {
                        ld.vertices[i].label = 4;
                    }
                }
            }
        }
        __syncwarp();
    }



    // sort vertices so that critical vertex adjacent candidates are immediately after vertices within the clique
    d_sort(ld.vertices + wd.number_of_members[WIB_IDX], wd.number_of_candidates[WIB_IDX], d_sort_vert_cv);

    // count number of critical adjacent vertices
    number_of_crit_adj = 0;
    for (int i = wd.number_of_members[WIB_IDX] + LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
        if (ld.vertices[i].label == 4) {
            number_of_crit_adj++;
        }
        else {
            break;
        }
    }
    // get sum
    for (int i = 1; i < 32; i *= 2) {
        number_of_crit_adj += __shfl_xor_sync(0xFFFFFFFF, number_of_crit_adj, i);
    }



    failed_found = false;

    // reset adjacencies
    for (int i = LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
        dd.adjacencies[(WVERTICES_SIZE * WARP_IDX) + i] = 0;
    }

    // if there were any neighbors of critical vertices
    if (number_of_crit_adj > 0)
    {
        // iterate through all vertices and update their degrees as if critical adjacencies were added and keep track of how many critical adjacencies they are adjacent to
        for (int k = LANE_IDX; k < wd.total_vertices[WIB_IDX]; k += WARP_SIZE) {
            phelper1 = ld.vertices[k].vertexid;

            for (int i = wd.number_of_members[WIB_IDX]; i < wd.number_of_members[WIB_IDX] + number_of_crit_adj; i++) {
                if (d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], ld.vertices[i].vertexid) > -1) {
                    ld.vertices[k].indeg++;
                    ld.vertices[k].exdeg--;
                }

                if (d_bsearch_array(dd.twohop_neighbors + dd.twohop_offsets[phelper1], dd.twohop_offsets[phelper1 + 1] - dd.twohop_offsets[phelper1], ld.vertices[i].vertexid) > -1) {
                    dd.adjacencies[(WVERTICES_SIZE * WARP_IDX) + k]++;
                }
            }
        }
        __syncwarp();

        // all vertices within the clique must be within 2hops of the newly added critical vertex adj vertices
        for (int k = LANE_IDX; k < wd.number_of_members[WIB_IDX]; k += WARP_SIZE) {
            if (dd.adjacencies[(WVERTICES_SIZE * WARP_IDX) + k] != number_of_crit_adj) {
                failed_found = true;
                break;
            }
        }
        failed_found = __any_sync(0xFFFFFFFF, failed_found);
        if (failed_found) {
            return 2;
        }

        // all critical adj vertices must all be within 2 hops of each other
        for (int k = wd.number_of_members[WIB_IDX] + LANE_IDX; k < wd.number_of_members[WIB_IDX] + number_of_crit_adj; k += WARP_SIZE) {
            if (dd.adjacencies[(WVERTICES_SIZE * WARP_IDX) + k] < number_of_crit_adj - 1) {
                failed_found = true;
                break;
            }
        }
        failed_found = __any_sync(0xFFFFFFFF, failed_found);
        if (failed_found) {
            return 2;
        }

        // no failed vertices found so add all critical vertex adj candidates to clique
        for (int k = wd.number_of_members[WIB_IDX] + LANE_IDX; k < wd.number_of_members[WIB_IDX] + number_of_crit_adj; k += WARP_SIZE) {
            ld.vertices[k].label = 1;
        }

        if (LANE_IDX == 0) {
            wd.number_of_members[WIB_IDX] += number_of_crit_adj;
            wd.number_of_candidates[WIB_IDX] -= number_of_crit_adj;
        }
        __syncwarp();
    }



    // DIAMTER PRUNING
    d_diameter_pruning_cv(dd, wd, ld, number_of_crit_adj);



    // DEGREE BASED PRUNING
    failed_found = d_degree_pruning(dd, wd, ld);

    // if vertex in x found as not extendable continue to next iteration
    if (failed_found) {
        return 1;
    }

    return 0;
}

// diameter pruning intitializes vertices labels and candidate indegs array for use in iterative degree pruning
__device__ void d_diameter_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int pvertexid)
{
    // vertices size * warp idx + (vertices size / warp size) * lane idx
    int lane_write = ((WVERTICES_SIZE * WARP_IDX) + ((WVERTICES_SIZE / WARP_SIZE) * LANE_IDX));

    // intersection
    int phelper1;
    int phelper2;

    // vertex iteration
    int lane_remaining_count;

    lane_remaining_count = 0;

    for (int i = wd.number_of_members[WIB_IDX] + LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
        ld.vertices[i].label = -1;
    }
    __syncwarp();

    for (int i = wd.number_of_members[WIB_IDX] + LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
        phelper1 = ld.vertices[i].vertexid;
        phelper2 = d_bsearch_array(dd.twohop_neighbors + dd.twohop_offsets[pvertexid], dd.twohop_offsets[pvertexid + 1] - dd.twohop_offsets[pvertexid], phelper1);

        if (phelper2 > -1) {
            ld.vertices[i].label = 0;
            dd.lane_candidate_indegs[lane_write + lane_remaining_count++] = ld.vertices[i].indeg;
        }
    }
    __syncwarp();

    // scan to calculate write postion in warp arrays
    phelper2 = lane_remaining_count;
    for (int i = 1; i < WARP_SIZE; i *= 2) {
        phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_remaining_count, i, WARP_SIZE);
        if (LANE_IDX >= i) {
            lane_remaining_count += phelper1;
        }
        __syncwarp();
    }
    // lane remaining count sum is scan for last lane and its value
    if (LANE_IDX == WARP_SIZE - 1) {
        wd.remaining_count[WIB_IDX] = lane_remaining_count;
    }
    // make scan exclusive
    lane_remaining_count -= phelper2;
    __syncwarp();

    // parallel write lane arrays to warp array
    for (int i = 0; i < phelper2; i++) {
        dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + lane_remaining_count + i] = dd.lane_candidate_indegs[lane_write + i];
    }
    __syncwarp();
}

__device__ void d_diameter_pruning_cv(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int number_of_crit_adj)
{
    // (WVERTICES_SIZE * WARP_IDX) /warp write location to adjacencies
    // vertices size * warp idx + (vertices size / warp size) * lane idx
    int lane_write = ((WVERTICES_SIZE * WARP_IDX) + ((WVERTICES_SIZE / WARP_SIZE) * LANE_IDX));

    // vertex iteration
    int lane_remaining_count;

    // intersection
    int phelper1;
    int phelper2;



    lane_remaining_count = 0;

    // remove all cands who are not within 2hops of all newly added cands
    for (int k = wd.number_of_members[WIB_IDX] + LANE_IDX; k < wd.total_vertices[WIB_IDX]; k += WARP_SIZE) {
        if (dd.adjacencies[(WVERTICES_SIZE * WARP_IDX) + k] == number_of_crit_adj) {
            dd.lane_candidate_indegs[lane_write + lane_remaining_count++] = ld.vertices[k].indeg;
        }
        else {
            ld.vertices[k].label = -1;
        }
    }

    // scan to calculate write postion in warp arrays
    phelper2 = lane_remaining_count;
    for (int i = 1; i < WARP_SIZE; i *= 2) {
        phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_remaining_count, i, WARP_SIZE);
        if (LANE_IDX >= i) {
            lane_remaining_count += phelper1;
        }
        __syncwarp();
    }
    // lane remaining count sum is scan for last lane and its value
    if (LANE_IDX == WARP_SIZE - 1) {
        wd.remaining_count[WIB_IDX] = lane_remaining_count;
    }
    // make scan exclusive
    lane_remaining_count -= phelper2;
    __syncwarp();

    // parallel write lane arrays to warp array
    for (int i = 0; i < phelper2; i++) {
        dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + lane_remaining_count + i] = dd.lane_candidate_indegs[lane_write + i];
    }
    __syncwarp();
}

// returns true if invalid bounds or failed found
__device__ bool d_degree_pruning(GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    // vertices size * warp idx + (vertices size / warp size) * lane idx
    int lane_write = ((WVERTICES_SIZE * WARP_IDX) + ((WVERTICES_SIZE / WARP_SIZE) * LANE_IDX));

    // helper variables used throughout method to store various values, names have no meaning
    int pvertexid;
    int phelper1;
    int phelper2;
    Vertex* read;
    Vertex* write;

    // counter for lane intersection results
    int lane_remaining_count;
    int lane_removed_count;



    d_sort_i(dd.candidate_indegs + (WVERTICES_SIZE * WARP_IDX), wd.remaining_count[WIB_IDX], d_sort_degs);

    d_calculate_LU_bounds(dd, wd, ld, wd.remaining_count[WIB_IDX]);
    if (wd.invalid_bounds[WIB_IDX]) {
        return true;
    }

    // check for failed vertices
    if (LANE_IDX == 0) {
        wd.success[WIB_IDX] = false;
    }
    __syncwarp();
    for (int k = LANE_IDX; k < wd.number_of_members[WIB_IDX] && !wd.success[WIB_IDX]; k += WARP_SIZE) {
        if (!d_vert_isextendable_LU(ld.vertices[k], dd, wd, ld)) {
            wd.success[WIB_IDX] = true;
            break;
        }

    }
    __syncwarp();
    if (wd.success[WIB_IDX]) {
        return true;
    }

    if (LANE_IDX == 0) {
        wd.remaining_count[WIB_IDX] = 0;
        wd.removed_count[WIB_IDX] = 0;
        wd.rw_counter[WIB_IDX] = 0;
    }



    lane_remaining_count = 0;
    lane_removed_count = 0;
    
    for (int i = wd.number_of_members[WIB_IDX] + LANE_IDX; i < wd.total_vertices[WIB_IDX]; i += WARP_SIZE) {
        if (ld.vertices[i].label == 0 && d_cand_isvalid_LU(ld.vertices[i], dd, wd, ld)) {
            dd.lane_remaining_candidates[lane_write + lane_remaining_count++] = i;
        }
        else {
            dd.lane_removed_candidates[lane_write + lane_removed_count++] = i;
        }
    }
    __syncwarp();

    // scan to calculate write postion in warp arrays
    phelper2 = lane_remaining_count;
    pvertexid = lane_removed_count;
    for (int i = 1; i < WARP_SIZE; i *= 2) {
        phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_remaining_count, i, WARP_SIZE);
        if (LANE_IDX >= i) {
            lane_remaining_count += phelper1;
        }
        phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_removed_count, i, WARP_SIZE);
        if (LANE_IDX >= i) {
            lane_removed_count += phelper1;
        }
        __syncwarp();
    }
    // lane remaining count sum is scan for last lane and its value
    if (LANE_IDX == WARP_SIZE - 1) {
        wd.remaining_count[WIB_IDX] = lane_remaining_count;
        wd.removed_count[WIB_IDX] = lane_removed_count;
    }
    // make scan exclusive
    lane_remaining_count -= phelper2;
    lane_removed_count -= pvertexid;

    // parallel write lane arrays to warp array
    for (int i = 0; i < phelper2; i++) {
        dd.remaining_candidates[(WVERTICES_SIZE * WARP_IDX) + lane_remaining_count + i] = ld.vertices[dd.lane_remaining_candidates[lane_write + i]];
    }
    // only need removed if going to be using removed to update degrees
    if (!(wd.remaining_count[WIB_IDX] < wd.removed_count[WIB_IDX])) {
        for (int i = 0; i < pvertexid; i++) {
            dd.removed_candidates[(WVERTICES_SIZE * WARP_IDX) + lane_removed_count + i] = ld.vertices[dd.lane_removed_candidates[lane_write + i]].vertexid;
        }
    }
    __syncwarp();


    
    while (wd.remaining_count[WIB_IDX] > 0 && wd.removed_count[WIB_IDX] > 0) {
        // different blocks for the read and write locations, vertices and remaining, this is done to avoid using extra variables and only one condition
        if (wd.rw_counter[WIB_IDX] % 2 == 0) {
            read = dd.remaining_candidates + (WVERTICES_SIZE * WARP_IDX);
            write = ld.vertices + wd.number_of_members[WIB_IDX];
        }
        else {
            read = ld.vertices + wd.number_of_members[WIB_IDX];
            write = dd.remaining_candidates + (WVERTICES_SIZE * WARP_IDX);
        }

        // update degrees
        if (wd.remaining_count[WIB_IDX] < wd.removed_count[WIB_IDX]) {
            // via remaining, reset exdegs
            for (int i = LANE_IDX; i < wd.number_of_members[WIB_IDX]; i += WARP_SIZE) {
                ld.vertices[i].exdeg = 0;
            }
            for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
                read[i].exdeg = 0;
            }
            __syncwarp();



            // update exdeg based on remaining candidates, every lane should get the next vertex to intersect dynamically
            for (int i = LANE_IDX; i < wd.number_of_members[WIB_IDX]; i += WARP_SIZE) {
                pvertexid = ld.vertices[i].vertexid;

                for (int j = 0; j < wd.remaining_count[WIB_IDX]; j++) {
                    phelper1 = read[j].vertexid;
                    phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], pvertexid);

                    if (phelper2 > -1) {
                        ld.vertices[i].exdeg++;
                    }
                }
            }

            for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
                pvertexid = read[i].vertexid;

                for (int j = 0; j < wd.remaining_count[WIB_IDX]; j++) {
                    if (j == i) {
                        continue;
                    }

                    phelper1 = read[j].vertexid;
                    phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], pvertexid);

                    if (phelper2 > -1) {
                        read[i].exdeg++;
                    }
                }
            }
        }
        else {
            // via removed, update exdeg based on remaining candidates, again lane scheduling should be dynamic
            for (int i = LANE_IDX; i < wd.number_of_members[WIB_IDX]; i += WARP_SIZE) {
                pvertexid = ld.vertices[i].vertexid;

                for (int j = 0; j < wd.removed_count[WIB_IDX]; j++) {
                    phelper1 = dd.removed_candidates[(WVERTICES_SIZE * WARP_IDX) + j];
                    phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], pvertexid);

                    if (phelper2 > -1) {
                        ld.vertices[i].exdeg--;
                    }
                }
            }

            for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
                pvertexid = read[i].vertexid;

                for (int j = 0; j < wd.removed_count[WIB_IDX]; j++) {
                    phelper1 = dd.removed_candidates[(WVERTICES_SIZE * WARP_IDX) + j];
                    phelper2 = d_bsearch_array(dd.onehop_neighbors + dd.onehop_offsets[phelper1], dd.onehop_offsets[phelper1 + 1] - dd.onehop_offsets[phelper1], pvertexid);

                    if (phelper2 > -1) {
                        read[i].exdeg--;
                    }
                }
            }
        }
        __syncwarp();

        lane_remaining_count = 0;

        for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
            if (d_cand_isvalid_LU(read[i], dd, wd, ld)) {
                dd.lane_candidate_indegs[lane_write + lane_remaining_count++] = read[i].indeg;
            }
        }
        __syncwarp();

        // scan to calculate write postion in warp arrays
        phelper2 = lane_remaining_count;
        for (int i = 1; i < WARP_SIZE; i *= 2) {
            phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_remaining_count, i, WARP_SIZE);
            if (LANE_IDX >= i) {
                lane_remaining_count += phelper1;
            }
            __syncwarp();
        }
        // lane remaining count sum is scan for last lane and its value
        if (LANE_IDX == WARP_SIZE - 1) {
            wd.num_val_cands[WIB_IDX] = lane_remaining_count;
        }
        // make scan exclusive
        lane_remaining_count -= phelper2;

        // parallel write lane arrays to warp array
        for (int i = 0; i < phelper2; i++) {
            dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + lane_remaining_count + i] = dd.lane_candidate_indegs[lane_write + i];
        }
        __syncwarp();



        d_sort_i(dd.candidate_indegs + (WVERTICES_SIZE * WARP_IDX), wd.num_val_cands[WIB_IDX], d_sort_degs);

        d_calculate_LU_bounds(dd, wd, ld, wd.num_val_cands[WIB_IDX]);
        if (wd.invalid_bounds[WIB_IDX]) {
            return true;
        }

        // check for failed vertices
        for (int k = LANE_IDX; k < wd.number_of_members[WIB_IDX] && !wd.success[WIB_IDX]; k += WARP_SIZE) {
            if (!d_vert_isextendable_LU(ld.vertices[k], dd, wd, ld)) {
                wd.success[WIB_IDX] = true;
                break;
            }

        }
        __syncwarp();
        if (wd.success[WIB_IDX]) {
            return true;
        }



        lane_remaining_count = 0;
        lane_removed_count = 0;

        // check for failed candidates
        for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
            if (d_cand_isvalid_LU(read[i], dd, wd, ld)) {
                dd.lane_remaining_candidates[lane_write + lane_remaining_count++] = i;
            }
            else {
                dd.lane_removed_candidates[lane_write + lane_removed_count++] = i;
            }
        }
        __syncwarp();

        // scan to calculate write postion in warp arrays
        phelper2 = lane_remaining_count;
        pvertexid = lane_removed_count;
        for (int i = 1; i < WARP_SIZE; i *= 2) {
            phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_remaining_count, i, WARP_SIZE);
            if (LANE_IDX >= i) {
                lane_remaining_count += phelper1;
            }
            phelper1 = __shfl_up_sync(0xFFFFFFFF, lane_removed_count, i, WARP_SIZE);
            if (LANE_IDX >= i) {
                lane_removed_count += phelper1;
            }
            __syncwarp();
        }
        // lane remaining count sum is scan for last lane and its value
        if (LANE_IDX == WARP_SIZE - 1) {
            wd.num_val_cands[WIB_IDX] = lane_remaining_count;
            wd.removed_count[WIB_IDX] = lane_removed_count;
        }
        // make scan exclusive
        lane_remaining_count -= phelper2;
        lane_removed_count -= pvertexid;

        // parallel write lane arrays to warp array
        for (int i = 0; i < phelper2; i++) {
            write[lane_remaining_count + i] = read[dd.lane_remaining_candidates[lane_write + i]];
        }
        // only need removed if going to be using removed to update degrees
        if (!(wd.num_val_cands[WIB_IDX] < wd.removed_count[WIB_IDX])) {
            for (int i = 0; i < pvertexid; i++) {
                dd.removed_candidates[(WVERTICES_SIZE * WARP_IDX) + lane_removed_count + i] = read[dd.lane_removed_candidates[lane_write + i]].vertexid;
            }
        }



        if (LANE_IDX == 0) {
            wd.remaining_count[WIB_IDX] = wd.num_val_cands[WIB_IDX];
            wd.rw_counter[WIB_IDX]++;
        }
    }



    // condense vertices so remaining are after members, only needs to be done if they were not written into vertices last time
    if (wd.rw_counter[WIB_IDX] % 2 == 0) {
        for (int i = LANE_IDX; i < wd.remaining_count[WIB_IDX]; i += WARP_SIZE) {
            ld.vertices[wd.number_of_members[WIB_IDX] + i] = dd.remaining_candidates[(WVERTICES_SIZE * WARP_IDX) + i];
        }
    }

    if (LANE_IDX == 0) {
        wd.total_vertices[WIB_IDX] = wd.total_vertices[WIB_IDX] - wd.number_of_candidates[WIB_IDX] + wd.remaining_count[WIB_IDX];
        wd.number_of_candidates[WIB_IDX] = wd.remaining_count[WIB_IDX];
    }

    return false;
}

__device__ void d_calculate_LU_bounds(GPU_Data& dd, Warp_Data& wd, Local_Data& ld, int number_of_candidates)
{
    int index;

    int min_clq_indeg;
    int min_indeg_exdeg;
    int min_clq_totaldeg;
    int sum_clq_indeg;

    // initialize the values of the LU calculation variables to the first vertices values so they can be compared to other vertices without error
    min_clq_indeg = ld.vertices[0].indeg;
    min_indeg_exdeg = ld.vertices[0].exdeg;
    min_clq_totaldeg = ld.vertices[0].indeg + ld.vertices[0].exdeg;
    sum_clq_indeg = 0;

    // each warp also has a copy of these variables to allow for intra-warp comparison of these variables.
    if (LANE_IDX == 0) {
        wd.invalid_bounds[WIB_IDX] = false;

        wd.sum_candidate_indeg[WIB_IDX] = 0;
        wd.tightened_upper_bound[WIB_IDX] = 0;

        wd.min_clq_indeg[WIB_IDX] = ld.vertices[0].indeg;
        wd.min_indeg_exdeg[WIB_IDX] = ld.vertices[0].exdeg;
        wd.min_clq_totaldeg[WIB_IDX] = ld.vertices[0].indeg + ld.vertices[0].exdeg;
        wd.sum_clq_indeg[WIB_IDX] = ld.vertices[0].indeg;

        wd.min_ext_deg[WIB_IDX] = d_get_mindeg(wd.number_of_members[WIB_IDX] + 1, dd);
    }
    __syncwarp();

    // each warp finds these values on their subsection of vertices
    for (index = 1 + LANE_IDX; index < wd.number_of_members[WIB_IDX]; index += WARP_SIZE) {
        sum_clq_indeg += ld.vertices[index].indeg;

        if (ld.vertices[index].indeg < min_clq_indeg) {
            min_clq_indeg = ld.vertices[index].indeg;
            min_indeg_exdeg = ld.vertices[index].exdeg;
        }
        else if (ld.vertices[index].indeg == min_clq_indeg) {
            if (ld.vertices[index].exdeg < min_indeg_exdeg) {
                min_indeg_exdeg = ld.vertices[index].exdeg;
            }
        }

        if (ld.vertices[index].indeg + ld.vertices[index].exdeg < min_clq_totaldeg) {
            min_clq_totaldeg = ld.vertices[index].indeg + ld.vertices[index].exdeg;
        }
    }

    // get sum
    for (int i = 1; i < 32; i *= 2) {
        sum_clq_indeg += __shfl_xor_sync(0xFFFFFFFF, sum_clq_indeg, i);
    }
    if (LANE_IDX == 0) {
        // add to shared memory sum
        wd.sum_clq_indeg[WIB_IDX] += sum_clq_indeg;
    }
    __syncwarp();

    // CRITICAL SECTION - each lane then compares their values to the next to get a warp level value
    for (int i = 0; i < WARP_SIZE; i++) {
        if (LANE_IDX == i) {
            if (min_clq_indeg < wd.min_clq_indeg[WIB_IDX]) {
                wd.min_clq_indeg[WIB_IDX] = min_clq_indeg;
                wd.min_indeg_exdeg[WIB_IDX] = min_indeg_exdeg;
            }
            else if (min_clq_indeg == wd.min_clq_indeg[WIB_IDX]) {
                if (min_indeg_exdeg < wd.min_indeg_exdeg[WIB_IDX]) {
                    wd.min_indeg_exdeg[WIB_IDX] = min_indeg_exdeg;
                }
            }

            if (min_clq_totaldeg < wd.min_clq_totaldeg[WIB_IDX]) {
                wd.min_clq_totaldeg[WIB_IDX] = min_clq_totaldeg;
            }
        }
        __syncwarp();
    }

    if (LANE_IDX == 0) {
        if (wd.min_clq_indeg[WIB_IDX] < dd.minimum_degrees[wd.number_of_members[WIB_IDX]])
        {
            // lower
            wd.lower_bound[WIB_IDX] = d_get_mindeg(wd.number_of_members[WIB_IDX], dd) - min_clq_indeg;

            while (wd.lower_bound[WIB_IDX] <= wd.min_indeg_exdeg[WIB_IDX] && wd.min_clq_indeg[WIB_IDX] + wd.lower_bound[WIB_IDX] <
                dd.minimum_degrees[wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX]]) {
                wd.lower_bound[WIB_IDX]++;
            }

            if (wd.min_clq_indeg[WIB_IDX] + wd.lower_bound[WIB_IDX] < dd.minimum_degrees[wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX]]) {
                wd.invalid_bounds[WIB_IDX] = true;
            }

            // upper
            wd.upper_bound[WIB_IDX] = floor(wd.min_clq_totaldeg[WIB_IDX] / (*(dd.minimum_degree_ratio))) + 1 - wd.number_of_members[WIB_IDX];

            if (wd.upper_bound[WIB_IDX] > number_of_candidates) {
                wd.upper_bound[WIB_IDX] = number_of_candidates;
            }

            // tighten
            if (wd.lower_bound[WIB_IDX] < wd.upper_bound[WIB_IDX]) {
                // tighten lower
                for (index = 0; index < wd.lower_bound[WIB_IDX]; index++) {
                    wd.sum_candidate_indeg[WIB_IDX] += dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + index];
                }

                while (index < wd.upper_bound[WIB_IDX] && wd.sum_clq_indeg[WIB_IDX] + wd.sum_candidate_indeg[WIB_IDX] < wd.number_of_members[WIB_IDX] *
                    dd.minimum_degrees[wd.number_of_members[WIB_IDX] + index]) {
                    wd.sum_candidate_indeg[WIB_IDX] += dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + index];
                    index++;
                }

                if (wd.sum_clq_indeg[WIB_IDX] + wd.sum_candidate_indeg[WIB_IDX] < wd.number_of_members[WIB_IDX] * dd.minimum_degrees[wd.number_of_members[WIB_IDX] + index]) {
                    wd.invalid_bounds[WIB_IDX] = true;
                }
                else {
                    wd.lower_bound[WIB_IDX] = index;

                    wd.tightened_upper_bound[WIB_IDX] = index;

                    while (index < wd.upper_bound[WIB_IDX]) {
                        wd.sum_candidate_indeg[WIB_IDX] += dd.candidate_indegs[(WVERTICES_SIZE * WARP_IDX) + index];

                        index++;

                        if (wd.sum_clq_indeg[WIB_IDX] + wd.sum_candidate_indeg[WIB_IDX] >= wd.number_of_members[WIB_IDX] *
                            dd.minimum_degrees[wd.number_of_members[WIB_IDX] + index]) {
                            wd.tightened_upper_bound[WIB_IDX] = index;
                        }
                    }

                    if (wd.upper_bound[WIB_IDX] > wd.tightened_upper_bound[WIB_IDX]) {
                        wd.upper_bound[WIB_IDX] = wd.tightened_upper_bound[WIB_IDX];
                    }

                    if (wd.lower_bound[WIB_IDX] > 1) {
                        wd.min_ext_deg[WIB_IDX] = d_get_mindeg(wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX], dd);
                    }
                }
            }
        }
        else {
            wd.min_ext_deg[WIB_IDX] = d_get_mindeg(wd.number_of_members[WIB_IDX] + 1,
                dd);

            wd.upper_bound[WIB_IDX] = number_of_candidates;

            if (wd.number_of_members[WIB_IDX] < (*(dd.minimum_clique_size))) {
                wd.lower_bound[WIB_IDX] = (*(dd.minimum_clique_size)) - wd.number_of_members[WIB_IDX];
            }
            else {
                wd.lower_bound[WIB_IDX] = 0;
            }
        }

        if (wd.number_of_members[WIB_IDX] + wd.upper_bound[WIB_IDX] < (*(dd.minimum_clique_size))) {
            wd.invalid_bounds[WIB_IDX] = true;
        }

        if (wd.upper_bound[WIB_IDX] < 0 || wd.upper_bound[WIB_IDX] < wd.lower_bound[WIB_IDX]) {
            wd.invalid_bounds[WIB_IDX] = true;
        }
    }
    __syncwarp();
}

__device__ void d_check_for_clique(GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    bool clique = true;

    for (int k = LANE_IDX; k < wd.number_of_members[WIB_IDX]; k += WARP_SIZE) {
        if (ld.vertices[k].indeg < dd.minimum_degrees[wd.number_of_members[WIB_IDX]]) {
            clique = false;
            break;
        }
    }
    // set to false if any threads in warp do not meet degree requirement
    clique = !(__any_sync(0xFFFFFFFF, !clique));

    // if clique write to warp buffer for cliques
    if (clique) {
        uint64_t start_write = (WCLIQUES_SIZE * WARP_IDX) + dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + (dd.wcliques_count[WARP_IDX])];
        for (int k = LANE_IDX; k < wd.number_of_members[WIB_IDX]; k += WARP_SIZE) {
            dd.wcliques_vertex[start_write + k] = ld.vertices[k].vertexid;
        }
        if (LANE_IDX == 0) {
            (dd.wcliques_count[WARP_IDX])++;
            dd.wcliques_offset[(WCLIQUES_OFFSET_SIZE * WARP_IDX) + (dd.wcliques_count[WARP_IDX])] = start_write - (WCLIQUES_SIZE * WARP_IDX) + wd.number_of_members[WIB_IDX];
        }
    }
}

__device__ void d_write_to_tasks(GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    uint64_t start_write = (WTASKS_SIZE * WARP_IDX) + dd.wtasks_offset[WTASKS_OFFSET_SIZE * WARP_IDX + (dd.wtasks_count[WARP_IDX])];

    for (int k = LANE_IDX; k < wd.total_vertices[WIB_IDX]; k += WARP_SIZE) {
        dd.wtasks_vertices[start_write + k].vertexid = ld.vertices[k].vertexid;
        dd.wtasks_vertices[start_write + k].label = ld.vertices[k].label;
        dd.wtasks_vertices[start_write + k].indeg = ld.vertices[k].indeg;
        dd.wtasks_vertices[start_write + k].exdeg = ld.vertices[k].exdeg;
        dd.wtasks_vertices[start_write + k].lvl2adj = 0;
    }
    if (LANE_IDX == 0) {
        (dd.wtasks_count[WARP_IDX])++;
        dd.wtasks_offset[(WTASKS_OFFSET_SIZE * WARP_IDX) + (dd.wtasks_count[WARP_IDX])] = start_write - (WTASKS_SIZE * WARP_IDX) + wd.total_vertices[WIB_IDX];
    }
}



// --- HELPER KERNELS ---

// searches an int array for a certain int, returns the position in the array that item was found, or -1 if not found
__device__ int d_bsearch_array(int* search_array, int array_size, int search_number)
{
    // ALGO - binary
    // TYPE - serial
    // SPEED - 0(log(n))

    int low = 0;
    int high = array_size - 1;

    while (low <= high) {
        int mid = (low + high) / 2;

        if (search_array[mid] == search_number) {
            return mid;
        }
        else if (search_array[mid] > search_number) {
            high = mid - 1;
        }
        else {
            low = mid + 1;
        }
    }

    return -1;
}

// consider using merge
__device__ void d_sort(Vertex* target, int size, int (*func)(Vertex&, Vertex&))
{
    // ALGO - ODD/EVEN
    // TYPE - PARALLEL
    // SPEED - O(n^2)

    Vertex vertex1;
    Vertex vertex2;

    for (int i = 0; i < size; i++) {
        for (int j = (i % 2) + (LANE_IDX * 2); j < size - 1; j += (WARP_SIZE * 2)) {
            vertex1 = target[j];
            vertex2 = target[j + 1];

            if (func(vertex1, vertex2) == 1) {
                target[j] = vertex2;
                target[j + 1] = vertex1;
            }
        }
        __syncwarp();
    }
}

__device__ void d_sort_i(int* target, int size, int (*func)(int, int))
{
    // ALGO - ODD/EVEN
    // TYPE - PARALLEL
    // SPEED - O(n^2)

    int num1;
    int num2;

    for (int i = 0; i < size; i++) {
        for (int j = (i % 2) + (LANE_IDX * 2); j < size - 1; j += (WARP_SIZE * 2)) {
            num1 = target[j];
            num2 = target[j + 1];

            if (func(num1, num2) == 1) {
                target[j] = num2;
                target[j + 1] = num1;
            }
        }
        __syncwarp();
    }
}

// Quick enumeration order sort keys
__device__ int d_sort_vert_Q(Vertex& v1, Vertex& v2)
{
    // order is: member -> covered -> cands -> cover
    // keys are: indeg -> exdeg -> lvl2adj -> vertexid

    if (v1.label == 1 && v2.label != 1)
        return -1;
    else if (v1.label != 1 && v2.label == 1)
        return 1;
    else if (v1.label == 2 && v2.label != 2)
        return -1;
    else if (v1.label != 2 && v2.label == 2)
        return 1;
    else if (v1.label == 0 && v2.label != 0)
        return -1;
    else if (v1.label != 0 && v2.label == 0)
        return 1;
    else if (v1.label == 3 && v2.label != 3)
        return -1;
    else if (v1.label != 3 && v2.label == 3)
        return 1;
    else if (v1.indeg > v2.indeg)
        return -1;
    else if (v1.indeg < v2.indeg)
        return 1;
    else if (v1.exdeg > v2.exdeg)
        return -1;
    else if (v1.exdeg < v2.exdeg)
        return 1;
    else if (v1.lvl2adj > v2.lvl2adj)
        return -1;
    else if (v1.lvl2adj < v2.lvl2adj)
        return 1;
    else if (v1.vertexid > v2.vertexid)
        return -1;
    else if (v1.vertexid < v2.vertexid)
        return 1;
    else
        return 0;
}

__device__ int d_sort_vert_cv(Vertex& v1, Vertex& v2)
{
    // put crit adj vertices before candidates

    if (v1.label == 4 && v2.label != 4)
        return -1;
    else if (v1.label != 4 && v2.label == 4)
        return 1;
    else
        return 0;
}

__device__ int d_sort_degs(int n1, int n2)
{
    // descending order

    if (n1 > n2) {
        return -1;
    }
    else if (n1 < n2) {
        return 1;
    }
    else {
        return 0;
    }
}

__device__ int d_get_mindeg(int number_of_members, GPU_Data& dd)
{
    if (number_of_members < (*(dd.minimum_clique_size))) {
        return dd.minimum_degrees[(*(dd.minimum_clique_size))];
    }
    else {
        return dd.minimum_degrees[number_of_members];
    }
}

__device__ bool d_cand_isvalid_LU(Vertex& vertex, GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    if (vertex.indeg + vertex.exdeg < dd.minimum_degrees[(*(dd.minimum_clique_size))]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < d_get_mindeg(wd.number_of_members[WIB_IDX] + vertex.exdeg + 1, dd)) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < wd.min_ext_deg[WIB_IDX]) {
        return false;
    }
    else if (vertex.indeg + wd.upper_bound[WIB_IDX] - 1 < dd.minimum_degrees[wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX]]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < d_get_mindeg(wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX], dd)) {
        return false;
    }
    else {
        return true;
    }
}

__device__ bool d_vert_isextendable_LU(Vertex& vertex, GPU_Data& dd, Warp_Data& wd, Local_Data& ld)
{
    if (vertex.indeg + vertex.exdeg < dd.minimum_degrees[(*(dd.minimum_clique_size))]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < d_get_mindeg(wd.number_of_members[WIB_IDX] + vertex.exdeg, dd)) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < wd.min_ext_deg[WIB_IDX]) {
        return false;
    }
    else if (vertex.exdeg == 0 && vertex.indeg < d_get_mindeg(wd.number_of_members[WIB_IDX] + vertex.exdeg, dd)) {
        return false;
    }
    else if (vertex.indeg + wd.upper_bound[WIB_IDX] < dd.minimum_degrees[wd.number_of_members[WIB_IDX] + wd.upper_bound[WIB_IDX]]) {
        return false;
    }
    else if (vertex.indeg + vertex.exdeg < d_get_mindeg(wd.number_of_members[WIB_IDX] + wd.lower_bound[WIB_IDX], dd)) {
        return false;
    }
    else {
        return true;
    }
}



// --- DEBUG KERNELS ---

__device__ void d_print_vertices(Vertex* vertices, int size)
{
    printf("\nOffsets:\n0 %i\nVertex:\n", size);
    for (int i = 0; i < size; i++) {
        printf("%i ", vertices[i].vertexid);
    }
    printf("\nLabel:\n");
    for (int i = 0; i < size; i++) {
        printf("%i ", vertices[i].label);
    }
    printf("\nIndeg:\n");
    for (int i = 0; i < size; i++) {
        printf("%i ", vertices[i].indeg);
    }
    printf("\nExdeg:\n");
    for (int i = 0; i < size; i++) {
        printf("%i ", vertices[i].exdeg);
    }
    printf("\nLvl2adj:\n");
    for (int i = 0; i < size; i++) {
        printf("%i ", vertices[i].lvl2adj);
    }
    printf("\n");
}



// --- RM NON-MAX (from Quick) ---

int comp_int(const void* e1, const void* e2)
{
    int n1, n2;
    n1 = *(int*)e1;
    n2 = *(int*)e2;

    if (n1 > n2)
        return 1;
    else if (n1 < n2)
        return -1;
    else
        return 0;
}

extern int gntotal_max_cliques;

struct TREE_NODE
{
    int nid;
    TREE_NODE* pchild;
    TREE_NODE* pright_sib;
    bool bis_max;
};

#define TNODE_PAGE_SIZE (1<<10)

struct TNODE_PAGE
{
    TREE_NODE ptree_nodes[TNODE_PAGE_SIZE];
    TNODE_PAGE* pnext;
};

struct TNODE_BUF
{
    TNODE_PAGE* phead;
    TNODE_PAGE* pcur_page;
    int ncur_pos;
    int ntotal_pages;
};

extern TNODE_BUF gotreenode_buf;

inline TREE_NODE* NewTreeNode()
{
    TREE_NODE* ptnode;
    TNODE_PAGE* pnew_page;

    if (gotreenode_buf.ncur_pos == TNODE_PAGE_SIZE)
    {
        if (gotreenode_buf.pcur_page->pnext == NULL)
        {
            pnew_page = new TNODE_PAGE;
            pnew_page->pnext = NULL;
            gotreenode_buf.pcur_page->pnext = pnew_page;
            gotreenode_buf.pcur_page = pnew_page;
            gotreenode_buf.ntotal_pages++;
        }
        else
            gotreenode_buf.pcur_page = gotreenode_buf.pcur_page->pnext;
        gotreenode_buf.ncur_pos = 0;
    }

    ptnode = &(gotreenode_buf.pcur_page->ptree_nodes[gotreenode_buf.ncur_pos]);
    gotreenode_buf.ncur_pos++;

    ptnode->bis_max = true;

    return ptnode;
}

inline void OutputOneSet(FILE* fp, int* pset, int nlen)
{
    int i;

    gntotal_max_cliques++;

    fprintf(fp, "%d ", nlen);
    for (i = 0; i < nlen; i++)
        fprintf(fp, "%d ", pset[i]);
    fprintf(fp, "\n");

}

int gntotal_max_cliques;

TNODE_BUF gotreenode_buf;

void DelTNodeBuf()
{
    TNODE_PAGE* ppage;

    ppage = gotreenode_buf.phead;
    while (ppage != NULL)
    {
        gotreenode_buf.phead = gotreenode_buf.phead->pnext;
        delete ppage;
        gotreenode_buf.ntotal_pages--;
        ppage = gotreenode_buf.phead;
    }
    if (gotreenode_buf.ntotal_pages != 0)
        printf("Error: inconsistent number of pages\n");
}

void InsertOneSet(int* pset, int nlen, TREE_NODE*& proot)
{
    TREE_NODE* pnode, * pparent, * pleftsib, * pnew_node;
    int i, j;

    i = 0;
    pparent = NULL;
    pnode = proot;
    pleftsib = NULL;

    while (i < nlen)
    {
        while (pnode != NULL && pnode->nid < pset[i])
        {
            pleftsib = pnode;
            pnode = pnode->pright_sib;
        }

        if (pnode == NULL || pnode->nid > pset[i])
        {
            pnew_node = NewTreeNode();
            pnew_node->nid = pset[i];
            pnew_node->pchild = NULL;
            pnew_node->pright_sib = pnode;
            if (pleftsib != NULL)
                pleftsib->pright_sib = pnew_node;
            else if (pparent != NULL)
                pparent->pchild = pnew_node;
            if (i == 0 && pleftsib == NULL)
                proot = pnew_node;
            pparent = pnew_node;
            for (j = i + 1; j < nlen; j++)
            {
                pnew_node = NewTreeNode();
                pnew_node->nid = pset[j];
                pnew_node->pchild = NULL;
                pnew_node->pright_sib = NULL;
                pparent->pchild = pnew_node;
                pparent = pnew_node;
            }
            break;
        }
        else
        {
            pparent = pnode;
            pnode = pnode->pchild;
            pleftsib = NULL;
        }
        i++;
    }
}

int BuildTree(const char* szset_filename, TREE_NODE*& proot)
{
    FILE* fp;
    int nlen, * pset, nset_size, i, nmax_len, num_of_sets;

    fp = fopen(szset_filename, "rt");
    if (fp == NULL)
    {
        printf("Error: cannot open file %s for read\n", szset_filename);
        return 0;
    }

    gotreenode_buf.phead = new TNODE_PAGE;
    gotreenode_buf.phead->pnext = NULL;
    gotreenode_buf.pcur_page = gotreenode_buf.phead;
    gotreenode_buf.ntotal_pages = 1;
    gotreenode_buf.ncur_pos = 0;

    proot = NULL;

    num_of_sets = 0;

    nset_size = 100;
    pset = new int[nset_size];

    nmax_len = 0;
    fscanf(fp, "%d", &nlen);
    while (!feof(fp))
    {
        if (nmax_len < nlen)
            nmax_len = nlen;
        if (nlen > nset_size)
        {
            delete[]pset;
            nset_size *= 2;
            if (nset_size < nlen)
                nset_size = nlen;
            pset = new int[nset_size];
        }
        for (i = 0; i < nlen; i++)
            fscanf(fp, "%d", &pset[i]);
        qsort(pset, nlen, sizeof(int), comp_int);
        InsertOneSet(pset, nlen, proot);

        num_of_sets++;
        fscanf(fp, "%d", &nlen);
    }
    fclose(fp);

    delete[]pset;

    return nmax_len;
}

void SearchSubset(int* pset, int nset_len, TREE_NODE* proot, TREE_NODE** pstack, int* ppos)
{
    TREE_NODE* pnode;
    int ntop, npos;

    if (proot == NULL)
        return;
    ntop = 0;
    npos = 0;
    pnode = proot;

    while (ntop >= 0)
    {
        while (pnode != NULL && npos < nset_len && pnode->nid != pset[npos])
        {
            if (pnode->nid < pset[npos])
                pnode = pnode->pright_sib;
            else
                npos++;
        }
        if (pnode != NULL && npos < nset_len)
        {
            if (pnode->pchild == NULL && pnode->bis_max)
                pnode->bis_max = false;
            pstack[ntop] = pnode;
            ppos[ntop] = npos;
            ntop++;
            pnode = pnode->pchild;
            npos++;
        }
        else
        {
            ntop--;
            if (ntop >= 0)
            {
                pnode = pstack[ntop]->pright_sib;
                npos = ppos[ntop] + 1;
            }
        }
    }

}

void RmNonMax(TREE_NODE* proot, int nmax_len)
{
    TREE_NODE* pnode, ** pstack, ** psearch_stack;
    int* pset, ntop, i, * ppos;

    pset = new int[nmax_len];
    pstack = new TREE_NODE * [nmax_len];
    psearch_stack = new TREE_NODE * [nmax_len];
    ppos = new int[nmax_len];

    pstack[0] = proot;
    pset[0] = proot->nid;
    ntop = 1;
    pnode = proot;

    while (ntop > 0)
    {
        if (pnode->pchild != NULL)
        {
            pnode = pnode->pchild;
            pstack[ntop] = pnode;
            pset[ntop] = pnode->nid;
            ntop++;
        }
        else
        {
            if (ntop >= 2 && pnode->bis_max)
            {
                for (i = ntop - 1; i >= 1; i--)
                {
                    if (pstack[i - 1]->pright_sib != NULL)
                        SearchSubset(&pset[i], ntop - i, pstack[i - 1]->pright_sib, psearch_stack, ppos);
                }
            }

            while (ntop > 0 && pnode->pright_sib == NULL)
            {
                ntop--;
                if (ntop > 0)
                    pnode = pstack[ntop - 1];
            }
            if (ntop == 0)
                break;
            else //if(pnode->pright_sib!=NULL)
            {
                pnode = pnode->pright_sib;
                pstack[ntop - 1] = pnode;
                pset[ntop - 1] = pnode->nid;
            }
        }
    }

    delete[]pset;
    delete[]pstack;
    delete[]psearch_stack;
    delete[]ppos;
}

void OutputMaxSet(TREE_NODE* proot, int nmax_len, char* szoutput_filename)
{
    FILE* fp;
    TREE_NODE** pstack, * pnode;
    int* pset, ntop;

    fp = fopen(szoutput_filename, "wt");
    if (fp == NULL)
    {
        printf("Error: cannot open file %s for write\n", szoutput_filename);
        return;
    }

    pstack = new TREE_NODE * [nmax_len];
    pset = new int[nmax_len];

    pstack[0] = proot;
    pset[0] = proot->nid;
    ntop = 1;
    pnode = proot;

    while (ntop > 0)
    {
        if (pnode->pchild != NULL)
        {
            pnode = pnode->pchild;
            pstack[ntop] = pnode;
            pset[ntop] = pnode->nid;
            ntop++;
        }
        else
        {
            if (pnode->bis_max)
                OutputOneSet(fp, pset, ntop);

            while (ntop > 0 && pnode->pright_sib == NULL)
            {
                ntop--;
                if (ntop > 0)
                    pnode = pstack[ntop - 1];
            }
            if (ntop == 0)
                break;
            else //if(pnode->pright_sib!=NULL)
            {
                pnode = pnode->pright_sib;
                pstack[ntop - 1] = pnode;
                pset[ntop - 1] = pnode->nid;
            }
        }
    }

    delete[]pstack;
    delete[]pset;

    fclose(fp);
}

void RemoveNonMax(const char* szset_filename, char* szoutput_filename)
{
    cout << ">:REMOVING NON-MAXIMAL CLIQUES" << endl;

    TREE_NODE* proot;
    int nmax_len;
    struct timeb start, end;

    ftime(&start);

    gntotal_max_cliques = 0;

    nmax_len = BuildTree(szset_filename, proot);
    RmNonMax(proot, nmax_len);
    OutputMaxSet(proot, nmax_len, szoutput_filename);

    DelTNodeBuf();

    ftime(&end);


    printf(">:NUMBER OF MAXIMAL CLIQUES: %d\n", gntotal_max_cliques);
}

#ifdef GRAPHMINE_LIBRARY

graphmine::detail::QuasiCliqueBackendResult run_graphmine_cuqc(
    const graphmine::CsrGraph& graph, double ratio, size_t requested_minimum,
    bool static_schedule, int device_id)
{
    static mutex execution_mutex;
    lock_guard<mutex> lock(execution_mutex);

    if (graph.vertex_count() < requested_minimum || graph.neighbors.empty()) {
        return {graphmine::Status::success(), {}, 0.0};
    }

    try {
        chkerr(cudaSetDevice(device_id));
        vector<int> onehop;
        onehop.reserve(graph.neighbors.size());
        for (const auto neighbor : graph.neighbors) {
            if (neighbor > static_cast<graphmine::VertexIndex>(INT_MAX)) {
                throw invalid_argument("cuQC uses signed 32-bit vertex IDs");
            }
            onehop.push_back(static_cast<int>(neighbor));
        }

        vector<uint64_t> twohop_offsets;
        vector<int> twohop;
        twohop_offsets.reserve(graph.vertex_count() + 1);
        twohop_offsets.push_back(0);
        vector<int> marks(graph.vertex_count(), -1);
        vector<int> reachable;
        for (size_t vertex = 0; vertex < graph.vertex_count(); ++vertex) {
            reachable.clear();
            const auto mark = static_cast<int>(vertex);
            const auto add = [&](graphmine::VertexIndex candidate) {
                if (candidate != vertex && marks[candidate] != mark) {
                    marks[candidate] = mark;
                    reachable.push_back(static_cast<int>(candidate));
                }
            };
            for (auto edge = graph.offsets[vertex];
                 edge < graph.offsets[vertex + 1]; ++edge) {
                const auto neighbor = graph.neighbors[edge];
                add(neighbor);
                for (auto next = graph.offsets[neighbor];
                     next < graph.offsets[neighbor + 1]; ++next) {
                    add(graph.neighbors[next]);
                }
            }
            sort(reachable.begin(), reachable.end());
            twohop.insert(twohop.end(), reachable.begin(), reachable.end());
            twohop_offsets.push_back(twohop.size());
        }

        minimum_degree_ratio = ratio;
        minimum_clique_size = static_cast<int>(requested_minimum);
        scheduling_toggle = static_schedule ? 1 : 0;
        delete[] minimum_degrees;
        minimum_degrees = nullptr;

        CPU_Graph host_graph(static_cast<int>(graph.vertex_count()),
                             graph.offsets, onehop, twohop_offsets, twohop);
        calculate_minimum_degrees(host_graph);
        ostringstream raw_results;
        const auto started = chrono::steady_clock::now();
        try {
            search(host_graph, raw_results);
        }
        catch (...) {
            delete[] minimum_degrees;
            minimum_degrees = nullptr;
            throw;
        }
        const auto finished = chrono::steady_clock::now();
        delete[] minimum_degrees;
        minimum_degrees = nullptr;

        istringstream input(raw_results.str());
        vector<vector<graphmine::VertexIndex>> candidates;
        uint64_t length = 0;
        while (input >> length) {
            vector<graphmine::VertexIndex> candidate;
            candidate.reserve(static_cast<size_t>(length));
            for (uint64_t index = 0; index < length; ++index) {
                int vertex = -1;
                if (!(input >> vertex) || vertex < 0 ||
                    static_cast<size_t>(vertex) >= graph.vertex_count()) {
                    throw runtime_error("cuQC emitted an invalid vertex set");
                }
                candidate.push_back(
                    static_cast<graphmine::VertexIndex>(vertex));
            }
            sort(candidate.begin(), candidate.end());
            candidate.erase(unique(candidate.begin(), candidate.end()),
                            candidate.end());
            if (candidate.size() >= requested_minimum) {
                candidates.push_back(move(candidate));
            }
        }

        sort(candidates.begin(), candidates.end(),
             [](const auto& lhs, const auto& rhs) {
                 if (lhs.size() != rhs.size()) return lhs.size() > rhs.size();
                 return lhs < rhs;
             });
        vector<vector<graphmine::VertexIndex>> maximal;
        for (const auto& candidate : candidates) {
            bool contained = false;
            for (const auto& accepted : maximal) {
                if (accepted.size() >= candidate.size() &&
                    includes(accepted.begin(), accepted.end(),
                             candidate.begin(), candidate.end())) {
                    contained = true;
                    break;
                }
            }
            if (!contained) maximal.push_back(candidate);
        }
        sort(maximal.begin(), maximal.end(),
             [](const auto& lhs, const auto& rhs) {
                 if (lhs.size() != rhs.size()) return lhs.size() < rhs.size();
                 return lhs < rhs;
             });

        return {graphmine::Status::success(), move(maximal),
                chrono::duration<double, milli>(finished - started).count()};
    }
    catch (const exception& error) {
        delete[] minimum_degrees;
        minimum_degrees = nullptr;
        return {{graphmine::StatusCode::execution_failed,
                 string("cuQC execution failed: ") + error.what()},
                {}, 0.0};
    }
}

}  // namespace graphmine_cuqc_upstream

namespace graphmine::detail {

bool cuqc_backend_compiled() noexcept { return true; }

QuasiCliqueBackendResult run_cuqc(const CsrGraph& graph,
                                  double minimum_degree_ratio,
                                  std::size_t minimum_size,
                                  bool static_scheduling, int device_id) {
    return graphmine_cuqc_upstream::run_graphmine_cuqc(
        graph, minimum_degree_ratio, minimum_size, static_scheduling,
        device_id);
}

}  // namespace graphmine::detail

#endif
