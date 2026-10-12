#pragma once
#include "../include/graph.h"
#include "use_no_uvm.cuh"


struct candidate {
    unsigned nodeid;
    unsigned key;
};

struct myEqual {
  __host__ __device__
    bool operator()(candidate x, candidate y)
    {
      return ( x.key == y.key && x.nodeid == y.nodeid );
    }
};


__global__ void setHyperedgePriority(int* hedges, int* nodes, unsigned* adj_list, int nodeN,
                                     int hedgeN, unsigned matching_policy, int* eRand, int* ePrior);

__global__ void multiNodeMatching1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior);

__global__ void multiNodeMatching2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* ePrior, int* nPrior, int* nRand);

__global__ void multiNodeMatching3(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* nRand, int* nHedgeId);

__global__ void assignPriorityToNode(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* ePrior, int* nPrior);

__global__ void assignHashHedgeIdToNode(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* ePrior, int* nPrior, int* nRand);

__global__ void assignNodeToIncidentHedgeWithMinimalID(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* nRand, int* nHedgeId);

__global__ void selectCandidatesTest(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                    int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                    int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId);

__global__ void collectCandidateWeights(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                        int* weights, unsigned* hedge_id, int* nHedgeId, int totalsize, long long* timer, int* real_work_cnt);

__global__ void collectCandidateNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int totalsize, int* weights, int* candidates, int* flag, int* nodeid, int* cand_count, long long* timer, int* real_work_cnt);

__global__ void assignMatchStatusAndSuperNodeToCandidates(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter,
                                                        int totalsize, unsigned* hedge_id, int* nHedgeId, int* newHedgeN, int* newNodeN, 
                                                        int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent,
                                                        int* candidates, int* flag, int* nodeid, int* cand_count, long long* timer);

__global__ void mergeNodesInsideHyperedges(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                        int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                        /*int* counts, unsigned* pnodes, int* flags,*/ long long* timer, long long* timer1, long long* timer2, int* real_work_cnt, int* real_work_cnt1);

__global__ void mergeNodesInsideHyperedges_split1(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* counts, unsigned* pnodes, int* flags);

__global__ void mergeNodesInsideHyperedges_split2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* counts, unsigned* pnodes, int* flags);

__global__ void PrepareForFurtherMatching(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int* eMatch, int* nMatch, int* nPrior/*, int* best, int* represent, int* count*/);

__global__ void resetAlreadyMatchedNodePriorityInUnmatchedHedge(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int hedgeN, int nodeN, 
                                                                int totalsize, int* eMatch, int* nMatch, int* nPrior/*,
                                                                int* counts, int* keys, int* weight_vals, int* num_items, tmp_nodes* tNodesAttr*/);

__global__ void parallelFindingCandsWithAtomicMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                            int* eMatch, int* nMatch, int* cand_counts, int* candidates, int totalsize/*, int* nPrior
                                            int* counts, int* keys, int* weight_vals, int* num_items*/);

__global__ void collectNodeAttrForFurtherReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id,
                                                int* eMatch, int* nMatch, int totalsize, tmp_nodes* tNodesAttr);
// template<int block_thread_num>
__global__ void parallelFindingRepresentWithReduceMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* weight_vals, int* keys, int totalsize);

__global__ void parallelSelectMinWeightMinNodeId(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT,
                                                int* eMatch, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, int* nBag1,
                                                int* represents, int* bests);

__global__ void parallelFindingRepresentWithAtomicMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* weight_vals, int totalsize, int* keys);

__global__ void collectRepresentNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* cand_counts, int* candidates, int totalsize,
                                        int* counts, int* keys, int* weight_vals, int* num_items, tmp_nodes* tNodesAttr);

__global__ void assignMatchStatusAndSuperNodeToNewCands(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, unsigned* hedge_id, int* nHedgeId, 
                                                        int* nMatch, int* nBag1, int* accW, int* cand_counts, int* candidates, int totalsize, int* keys, int* weight_vals);

__global__ void selectRepresentNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                    int* eMatch, int* nMatch, int* nPrior, 
                                    int* t_best, int* t_rep, int* t_count, int* keys, int* weight_vals, tmp_nodes* tNodesAttr);

__global__ void parallelFindingCandidatesForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId,// int* nPrior, int* parents,
                                                    int* cand_counts/*, int* represents, int* best, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/);

__global__ void parallelMergingNodesForEachHedges0(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nMatch, int* candidates, int* nHedgeId, int* cand_counts);

__global__ void parallelFindingRepresentForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, int* nBag1,// int* parents,
                                                    int* cand_counts, int* represents, int* best/*, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/);

__global__ void parallelMergingNodesForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId, // int* nPrior, int* parents,
                                                    int* cand_counts, int* represents, int* bests/*, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/);

__global__ void parallelMergingNodesForEachAdjElement(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT,
                                                int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId,// int* nPrior, int* parents,
                                                int* cand_counts, int* represents, int* bests, unsigned* hedge_id, int totalsize);

__global__ void mergeMoreNodesAcrossHyperedges(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                            int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId/*, 
                                            int* t_best, int* t_rep, int* t_count, int lo, int hi, int* hedgelist*/);

__global__ void countingHyperedgesRetainInCoarserLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int* newHedgeN, int* eInBag, int* eMatch, int* nMatch);

__global__ void selfMergeSingletonNodes(int* nodes, int nodeN, int hedgeN, int* newNodeN, int* nBag1, int* nBag, int* accW, int* nMatch, int* nHedgeId, unsigned* isSelfMergeNodes);

__global__ void setupNodeMapping(int* nodes, int nodeN, int hedgeN, int* newNodes, int newNodeN, int newHedgeN, int* nBag, int* nNextId, int* accW, int* accW1);

__global__ void updateCoarsenNodeId(int* nodes, int nodeN, int hedgeN, int* nNextId);

// __global__ void markParentsForPinsLists(int* hedges, int* nodes, unsigned* adj_list, bool* par_list, int hedgeN, int nodeN, 
//                                         int* newHedges, int newHedgeN, int* newTotalPinSize);

// __global__ void setupNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, bool* par_list, int hedgeN, int nodeN,
//                                             int* newHedges, int* newNodes, unsigned* newAdjList, 
//                                             int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
//                                             int* maxDegree, int* minDegree, int* maxWeight, int* minWeight);

__global__ void markParentsForPinsLists(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, 
                                        int maxHedgeSize, /*int* checkCounts, int* adj_elem_cnt*/unsigned* isSelfMergeNodes, int* dupCnts);

__global__ void markParentsForPinsLists1(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int maxHedgeSize);

__global__ void setupNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, 
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight);

__global__ void setupNextLevelAdjacentList1(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight);

__global__ void markDuplicasInNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize);



__global__ void fillNextLevelAdjacentListWithoutDuplicates0(
                                            int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight, int* sdv, long double avg);

__global__ void fillNextLevelAdjacentListWithoutDuplicates(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter);

__global__ void fillNextLevelAdjacentListWithoutDuplicates1(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter);

__global__ void fillNextLevelAdjacentListWithoutDuplicates2(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, int* sdv, long double avg);


__global__ void fillNextLevelAdjacentList(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, unsigned* offset);

__global__ void setCoarsenNodesProperties(int* newNodes, int newNodeN, int newHedgeN, int* maxWeight, int* minWeight, int* accW1);


__global__ void markDuplicasInNextLevelAdjacentList_1(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize);

__global__ void markDuplicasInNextLevelAdjacentList_2(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize);

__global__ void markDuplicasInNextLevelAdjacentList_3(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int maxHedgeSize/*, int* checkCounts*/);
                                                    

__global__ void assignEachHedgeToCorrespondingKernel(int* hedge, int hedgeN, int* eMatch, int* s_cnt, int* m_cnt, int* l_cnt, int* u_cnt, 
                                                    int* s_list, int* m_list, int* l_list, int* u_list);

__global__ void assignTWCHedgeWorkListsWithTunableThresholds(int* hedge, int hedgeN, int* eMatch, int* s_cnt, int* m_cnt, int* l_cnt, 
                                                    int* s_list, int* m_list, int* l_list,
                                                    int s_threshod, int m_threshold/*, int* hedgesize*/);

__global__ void processHedgesInThreadLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int* s_list, int* s_cnt,
                                        int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId);

__global__ void processHedgesInBlockLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);

__global__ void processHedgesInBlockLevelWithSharedMemReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);

__global__ void processHedgesInWarpLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);

// __global__ void processSmallSizeHedges1(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int s_threshod,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId);

// __global__ void processHedgesInBlockLevel2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int lo, int hi,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
//                                         int* cand_counts, int* represents, int* bests);

// __global__ void processHedgesInBlockLevel3(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int lo, int hi,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
//                                         int* cand_counts, int* represents, int* bests);

__global__ void processHedgesInWarpLevelWithSharedMemReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);
                                        
__global__ void markHedgeInCorrespondingWorkLists(int* hedge, int hedgeN, int* eMatch, int* s_list, int* m_list, int* l_list, int* u_list);

__global__ void markHedgeInCorrespondingWorkLists1(int* hedge, int hedgeN, int* eMatch, int* s_list, int* m_list, int* l_list, int s_threshod, int m_threshold/*, int* hedgesize*/);

// __global__ void putValidHedgeIntoCorrespondingList(int* hedge, int hedgeN, int* mark_list, int* hedge_list);

__global__ void putValidHedgeIntoCorrespondingList(int* hedge, int hedgeN, int* mark_list1, int* hedge_list1, int* mark_list2, int* hedge_list2, 
                                                    int* mark_list3, int* hedge_list3, int* mark_list4, int* hedge_list4);

__global__ void assignHedgeInfo(int* hedge, int hedgeN, int* eMatch, tmp_hedge* hedgelist);

__global__ void processHedgesInThreadLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, tmp_hedge* s_list, int s_cnt,
                                        int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId);

__global__ void processHedgesInWarpLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        tmp_hedge* hedge_list, int hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);

__global__ void processHedgesInBlockLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        tmp_hedge* hedge_list, int hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests);

__global__ void fillIncidentNetLists(int* hedges, int* nodes, unsigned* adj_list, unsigned* incident_nets, int hedgeN, int nodeN, int* netsListCounter);

__global__ void fillIncidentNetLists1(int* hedges, int* nodes, unsigned* adj_list, unsigned* incident_nets, 
                                    int* newNodes, unsigned* newNetList, int hedgeN, int nodeN, int newHedgeN, int newNodeN, 
                                    int* netsListCounter, int* eInBag, int* nInBag, int* next_eid, int* next_nid);

__global__ void updateAdjParentList(int* nodes, unsigned* adj_list, int* adj_parlist, int* nNextId, int nodeN, int hedgeN, int totalsize, 
                                    int* eInBag, unsigned* hedge_id/*, int* dup_degree, int newHedgeN, unsigned* isSelfMergeNode, unsigned* isDuplica*/);

__global__ void markDuplicateParentInPins(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist);

__global__ void markDuplicateParentInPins1(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize);

__global__ void markDuplicateWithBasePattern(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag);
                                        
__global__ void markDuplicateParentInPins2(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, int maxHedgeSize);

__global__ void markDuplicateParentInPins3(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag, int totalsize,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, int maxHedgeSize);

__global__ void mergeNodesInsideHyperedges_mod(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, unsigned* isDuplica, int* dupCnts);

__global__ void mergeMoreNodesAcrossHyperedges_mod(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int* eMatch,
                                                int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, unsigned* isDuplica, int* dupCnts);

__global__ void selfMergeSingletonNodes_mod(int* nodes, int nodeN, int hedgeN, int* newNodeN, int* nBag1, int* nBag, 
                                            int* accW, int* nMatch, int* nHedgeId, unsigned* isSelfMergeNodes);

__global__ void markParentsForPinsLists_early_duplica(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, unsigned* isSelfMergeNodes, int* dupCnts);

__global__ void markDuplicateParentInPins2_mod(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, unsigned* isSelfMergeNode);
                                        
__global__ void markDuplicateParentInPins1_mod(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize, 
                                        int large_hedge_threshold, int group_work_len);
                                        
__global__ void markDuplicateParentInPins1_workstealing(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize, 
                                        int large_hedge_threshold, int group_work_len);

__global__ void markDuplicateParentInPins1_parallelism(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize);


__global__ void parallel_markDuplicateParentInPins_base(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize);

__global__ void markDuplicateParentInPins1_binsearch(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize);

__global__ void markDuplicateParentInPins_idealcase_test(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize);

__global__ void markDuplicateCoarsePins_nocheck_longest_hedge_test(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int maxDegree,
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize);

__global__ void fillNextLevelAdjList_parallelbynode(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* newHedges, int* newNodes, 
                                        unsigned* newAdjList, unsigned* next_hedge_id, int* next_id, int* eInBag, int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, int* adj_parlist, unsigned* curr_hedge_id, int totalsize,
                                        int* sdv, long double avg);

__global__ void transform_edge_mapping_list_to_csr_format(int hedgeN, int newHedgeN, int* eInBag, int* eNext, int* eCsrOff, int* eCsrCol, float* eCsrVal);

__global__ void transform_node_mapping_list_to_csr_format(int newHedgeN, int* nodes, int nodeN, int* nCsrOff, int* nCsrCol, float* nCsrVal);

__global__ void transform_adjlist_to_csr_format(unsigned* adjlist, int hedgeN, int totalsize, int* adjCsrCol, float* adjCsrVal);

__global__ void computeAxB(int* matA, int* matB, int* matTmp, int hedgeN, int newHedgeN, int nodeN);


__global__ void multiNodeMatching_new(int* hedges, unsigned* adj_list, int hedgeN, int* ePrior, int* nPrior, 
                                    int* hedge_off_per_thread, int total_thread_num);

__global__ void fillNextLevelAdjacentList_new(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight,
                                            int* hedge_off_per_thread, int total_thread_num);

__global__ void mergeNodesInsideHyperedges_new(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* hedge_off_per_thread, int total_thread_num);

__global__ void mergeMoreNodesAcrossHyperedges_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                            int LIMIT, int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, 
                                            int* nPrior, int* nHedgeId, int* cand_counts, int* represents, int* bests);

__global__ void collectCandidateWeights_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, 
                                          int* weights, int* nHedgeId);

__global__ void collectCandidateNodes_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, 
                                          int* weights, int* candidates, int* flag, int* nodeid, int* cand_count);

__global__ void assignSuperNodeToCandidates_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, 
                                          int* nHedgeId, int* newHedgeN, int* newNodeN, 
                                          int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent,
                                          int* candidates, int* flag, int* nodeid, int* cand_count);

__global__ void assignPriorityToNode_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior);
 
__global__ void assignHashHedgeIdToNode_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, 
                                          int* ePrior, int* nPrior, int* nRand);

__global__ void assignNodeToIncidentHedgeWithMinimalID_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, 
                                          int* eRand, int* nRand, int* nHedgeId);
 