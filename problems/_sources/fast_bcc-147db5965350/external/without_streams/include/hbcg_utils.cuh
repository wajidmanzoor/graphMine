
#include "../parlay/sequence.h"

struct graph_data_host{
    int* V;
    long* E;
    parlay::sequence<uint64_t> edges;
    long* edges_size;
    parlay::sequence<int> temp_label;
    parlay::sequence<int> label;
    parlay::sequence<uint64_t> sptree;
    parlay::sequence<int> first_occ;
    parlay::sequence<int> last_occ;
    parlay::sequence<int> parent;
    long* edge_list_size;
    parlay::sequence<int> w1;
    parlay::sequence<int> w2;
};

struct graph_data{
    uint64_t* edges;
    uint64_t* edges2;
    int* temp_label;
    int* label;
    int* V;
    long* E;
    long* size;
    long* size2;
    uint64_t* T1edges;
    uint64_t* T2edges;
    int* first_occ;
    int* last_occ;
    int* parent;
    int* w1;
    int* w2;
    int* w1_copy;
    int* w2_copy;
    uint64_t* SpanningForest;
    int* low;
    int* high;
    bool* fg1;
};