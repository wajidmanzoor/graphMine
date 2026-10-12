#pragma once
#include <limits.h>
#include <sys/time.h>
#include <fstream>

#define PRINT_RESULT 0
#define COMPARE_RESULT 0

#define E_PRIORITY(hgr) 0 * hgr->hedgeNum
#define E_RAND(hgr)     1 * hgr->hedgeNum
#define E_IDNUM(hgr)    2 * hgr->hedgeNum
#define E_OFFSET(hgr)   3 * hgr->hedgeNum
#define E_DEGREE(hgr)   4 * hgr->hedgeNum
#define E_ELEMID(hgr)   5 * hgr->hedgeNum
#define E_MATCHED(hgr)  6 * hgr->hedgeNum
#define E_INBAG(hgr)    7 * hgr->hedgeNum
#define E_NEXTID(hgr)   8 * hgr->hedgeNum

#define N_PRIORITY(hgr)    0 * hgr->nodeNum
#define N_RAND(hgr)        1 * hgr->nodeNum
// #define N_ID(hgr)          2 * hgr->nodeNum
// #define N_DEGREE(hgr)      2 * hgr->nodeNum
// #define N_HEDGEID(hgr)     3 * hgr->nodeNum
// #define N_ELEMID(hgr)      4 * hgr->nodeNum
// #define N_MATCHED(hgr)     5 * hgr->nodeNum
// #define N_FOR_UPDATE(hgr)  6 * hgr->nodeNum
// #define N_MORE_UPDATE(hgr) 7 * hgr->nodeNum
// #define N_WEIGHT(hgr)      8 * hgr->nodeNum
// #define N_TMPW(hgr)        9 * hgr->nodeNum
// #define N_PARENT(hgr)      10 * hgr->nodeNum
// #define N_MAP_PARENT(hgr)  11 * hgr->nodeNum
// #define N_INBAG(hgr)       12 * hgr->nodeNum
// #define N_FS(hgr)          13 * hgr->nodeNum
// #define N_TE(hgr)          14 * hgr->nodeNum
// #define N_COUNTER(hgr)     15 * hgr->nodeNum
// #define N_TMPBAG(hgr)      16 * hgr->nodeNum
// #define N_PARTITION(hgr)   17 * hgr->nodeNum

#define N_DEGREE(hgr)      2 * hgr->nodeNum
#define N_OFFSET(hgr)      3 * hgr->nodeNum
#define N_HEDGEID(hgr)     4 * hgr->nodeNum
#define N_ELEMID(hgr)      5 * hgr->nodeNum
#define N_MATCHED(hgr)     6 * hgr->nodeNum
#define N_FOR_UPDATE(hgr)  7 * hgr->nodeNum
#define N_MORE_UPDATE(hgr) 8 * hgr->nodeNum
#define N_WEIGHT(hgr)      9 * hgr->nodeNum
#define N_TMPW(hgr)        10 * hgr->nodeNum
#define N_PARENT(hgr)      11 * hgr->nodeNum
#define N_MAP_PARENT(hgr)  12 * hgr->nodeNum
#define N_INBAG(hgr)       13 * hgr->nodeNum
#define N_FS(hgr)          14 * hgr->nodeNum
#define N_TE(hgr)          15 * hgr->nodeNum
#define N_COUNTER(hgr)     16 * hgr->nodeNum
#define N_TMPBAG(hgr)      17 * hgr->nodeNum
#define N_PARTITION(hgr)   18 * hgr->nodeNum
#define N_NETCOUNT(hgr)    19 * hgr->nodeNum

#define E_LENGTH(hgr)   9 * hgr->hedgeNum
#define N_LENGTH(hgr)  20 * hgr->nodeNum

struct Hypergraph {
    int nodeNum = 0;
    int hedgeNum = 0;
    int totalEdgeDegree = 0;
    int totalNodeDegree = 0;
    int graphSize = 0;
    int minDegree = INT_MAX;
    int maxDegree = 0;
    int totalWeight = 0;
    int minWeight = INT_MAX;
    int maxWeight = 0;
    int minVertDeg = INT_MAX;
    int maxVertDeg = 0;
    unsigned maxdeg_nodeIdx = 0;
    unsigned maxwt_nodeIdx = 0;
    int bit_length = 0;
    int num_hedges = 0;
    long double avgHedgeSize = 0;
    long double sdHedgeSize = 0;
    long double avgHNdegree = 0.0;
    long double sdHNdegree = 0.0;

    int* nodes;
    int* hedges;
    unsigned int* adj_list;
    unsigned int* incident_nets;
    bool* par_list;
    unsigned* pins_hedgeid_list;
    int* adj_node_parList;
    int* adj_part_list;
};

struct Auxillary {
    int* eInBag;
    int* eMatch;
    int* eNextId;
    int* eRand;
    int* ePriori;

    int* nRand;
    int* nPriori;
    int* nMatchHedgeId;
    int* nMatch;
    int* nInBag;
    int* nInBag1;
    int* nNextId;
    int* canBeCandidates;
    int* canBeCandidates1;
    int* tmpW;
    int* tmpW1;

    int* d_maxWeight;
    int* d_minWeight;
    int* d_maxPinSize;
    int* d_minPinSize;
    int* d_totalNodeDeg;
    int* d_totalPinSize;
    int* d_edgeCnt;
    int* d_nodeCnt;

    unsigned* pins_hedgeid_list;
    unsigned* next_hedgeid_list;
    unsigned* isDuplica;
    unsigned* bitset;
    int* d_newAdjListCounter;
    void* d_temp_storage = NULL;
    int* d_off;
    int* cand_weight_list;
    int* flags;
    int* cand_counts;
    int* nodeid;

    int* key_counts;
    int* nodeid_keys;
    int* weight_vals;
    int* num_items;
    int* best;
    int* represent;

    int* thread_num_each_hedge;
    int* hedgeid_each_thread;

    int* s_counter;
    int* m_counter;
    int* l_counter;
    int* u_counter;
    int* s_hedgeidList;
    int* m_hedgeidList;
    int* l_hedgeidList;
    int* u_hedgeidList;
    int* mark_sHedge;
    int* mark_mHedge;
    int* mark_lHedge;
    int* mark_uHedge;
    int* adj_node_parList;
    unsigned* isSelfMergeNodes;
    int* dupCnts;
    int* correspond_hedgeid;
    int* correspond_hoffset;
    int* nodes_dup_degree;
    int* nodes_dup_offset;

    int* hedge_off_per_thread;
    int total_thread_num;
};

struct tmp_nodes {
    int prior;
    int id_key;
    int w_vals;
    int eMatch;
    int nMatch;
    int hedgeid;
    int hedgesize;
    int real_access_size;
};

struct tmp_hedge {
    int id_key;
    int size;
    int eMatch;
};

#define E_IDNUM1(hedgeNum)    0 * hedgeNum
#define E_OFFSET1(hedgeNum)   1 * hedgeNum
#define E_DEGREE1(hedgeNum)   2 * hedgeNum
#define E_PARTITION1(hedgeNum) 3 * hedgeNum
// #define E_PRIORITY1(hedgeNum) 0 * hedgeNum
// #define E_RAND1(hedgeNum)     1 * hedgeNum
// #define E_ELEMID1(hedgeNum)   5 * hedgeNum
// #define E_MATCHED1(hedgeNum)  6 * hedgeNum
// #define E_INBAG1(hedgeNum)    7 * hedgeNum
// #define E_NEXTID1(hedgeNum)   8 * hedgeNum

#define E_LENGTH1(hedgeNum)   4 * hedgeNum

#define N_DEGREE1(nodeNum)      0 * nodeNum
#define N_OFFSET1(nodeNum)      1 * nodeNum
#define N_ELEMID1(nodeNum)      2 * nodeNum
#define N_WEIGHT1(nodeNum)      3 * nodeNum
#define N_PARENT1(nodeNum)      4 * nodeNum
#define N_FS1(nodeNum)          5 * nodeNum
#define N_TE1(nodeNum)          6 * nodeNum
#define N_COUNTER1(nodeNum)     7 * nodeNum
#define N_PARTITION1(nodeNum)   8 * nodeNum
// #define N_NETCOUNT1(nodeNum)    9 * nodeNum
#define N_GAIN1(nodeNum)        9 * nodeNum

// #define N_PRIORITY1(nodeNum)    10 * nodeNum
// #define N_RAND1(nodeNum)        11 * nodeNum
// #define N_HEDGEID1(nodeNum)     12 * nodeNum
// #define N_FOR_UPDATE1(nodeNum)  13 * nodeNum
// #define N_MORE_UPDATE1(nodeNum) 14 * nodeNum
// #define N_MATCHED1(nodeNum)     15 * nodeNum
// #define N_TMPW1(nodeNum)        16 * nodeNum
// #define N_MAP_PARENT1(nodeNum)  17 * nodeNum
// #define N_INBAG1(nodeNum)       18 * nodeNum
// #define N_TMPBAG1(nodeNum)      19 * nodeNum

#define N_LENGTH1(nodeNum)  10 * nodeNum

