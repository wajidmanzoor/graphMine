#include "crown.hpp"
#include "hopcroft_karp.hpp"
#include <stdio.h>
#include <cstdlib> // For malloc, free, realloc
#include <cstring> // For memset
#include <cstdlib>   // for std::rand and std::srand
#include <ctime>     // for std::time
#include <list>
#include "helperFunctions.h"

#include <vector>
#include <algorithm>

struct Edge {
    int u;
    int v;
    int edgeDegree;
    Edge(int u, int v, int edgeDegree) : u(u), v(v), edgeDegree(edgeDegree) {}
};

static bool compare_edges(const Edge& a, const Edge& b) {
    return a.edgeDegree > b.edgeDegree;
}

static unsigned int maximal_matching(const CSRGraph& graph, unsigned int* isMatched, int *vertexDegrees) {
    unsigned int numVertices = graph.vertexNum;
    unsigned int outsiders = 0;
    unsigned int realMatches = 0;
    std::vector<Edge> edges;

    for (unsigned int u=0; u<numVertices; ++u) {
        if (vertexDegrees[u]<1) {
            isMatched[u] = 1;
            ++outsiders;
            continue;
        }
        for (unsigned int j=graph.srcPtr[u]; j<graph.srcPtr[u]+graph.degree[u]; ++j) {
            unsigned int v = graph.dst[j];
            if (vertexDegrees[v]>0 && u<v) {
                Edge edge(u,v,vertexDegrees[u]+vertexDegrees[v]);
                edges.push_back(edge);
            }
        }
    }

    std::sort(edges.begin(), edges.end(), compare_edges);

    for (unsigned int i=0; i<edges.size(); ++i) {
        Edge edge = edges[i];
        if (!isMatched[edge.u] && !isMatched[edge.v]) {
            isMatched[edge.u] = 1;
            isMatched[edge.v] = 1;
            ++realMatches;
        }
    }
    //printf("Matches number is: %d\n",realMatches);
    return (realMatches*2) + outsiders;
}

// For Debugging Purposes
// Random way for selecting maximal matching
/*static unsigned int maximal_matching(const CSRGraph& graph, unsigned int* isMatched, int *vertexDegrees) {
    
	// tracking the number of matches
	unsigned int numOfMatches = 0;
    unsigned int realMatches = 0;
    unsigned int outsiders = 0;
    
    // std::srand(std::time(0));
    // unsigned int start = std::rand() % graph.vertexNum;
    // printf("Start:%d\n",start);
    //unsigned int start = 1163;

	// looping over the neighbors of each currently unmatched vertex that has neighbors (degree>0)
	// break when unmatched neighbor is found after marking both vertices as matched
	// proceed to another vertex
	for (unsigned int i=start; i<graph.vertexNum; ++i) {
        if (vertexDegrees[i]<1) {
            isMatched[i]=1;
            numOfMatches++;
            outsiders++;
            continue;
        }
		if (!isMatched[i]) {
			for (unsigned int j=graph.srcPtr[i]; j<graph.srcPtr[i]+graph.degree[i]; ++j) {
				unsigned int neighbor = graph.dst[j];
				if (vertexDegrees[neighbor]>0 && !isMatched[neighbor]) {
					isMatched[i]=1;
					isMatched[neighbor]=1;
					// updating the number of matches
					numOfMatches += 2;
                    realMatches++;
					break;
				}	
			}
		}
	}
    
    for (unsigned int i=0; i<start; ++i) {
        if (vertexDegrees[i]<1) {
            isMatched[i]=1;
            numOfMatches++;
            outsiders++;
            continue;
        }
		if (!isMatched[i]) {
			for (unsigned int j=graph.srcPtr[i]; j<graph.srcPtr[i]+graph.degree[i]; ++j) {
				unsigned int neighbor = graph.dst[j];
				if (vertexDegrees[neighbor]>0 && !isMatched[neighbor]) {
					isMatched[i]=1;
					isMatched[neighbor]=1;
					// updating the number of matches
					numOfMatches += 2;
                    realMatches++;
					break;
				}	
			}
		}
	}
    //printf("Matches number is: %d\n",realMatches);
    return numOfMatches;
}*/

static void flared_crown_checker(const BipGraph& bipGraph, unsigned int* SetIn, unsigned int& sizeIn,
								 unsigned int* SetHn, unsigned int& sizeHn,
								 unsigned int sizeOfSetO, unsigned int sizeOfSetONeighbs) {

	// "pairU" array of size "sizeOfSetO", has 0 for unmatched vertices (in the maximum match)
    // "pairV" array of size "sizeOfSetONeighbs", has 0 for unmatched vertices (in the maximum match)
	// "adj_u" adjacency list of the indexes of vertices in "SetO", and the indexes of their neighbors in "NeighborsOfSetO"
	int* pairU = bipGraph.getPtrPairU();
    int* pairV = bipGraph.getPtrPairV();
	std::list<int> *adj_u = bipGraph.getPtrAdjU();

	// "tempUniqueSetO" and "tempUniqueSetONeighbs" for not to repeat neighbors
	unsigned int* tempUniqueSetO = (unsigned int*) malloc(sizeof(unsigned int)*sizeOfSetO);
	unsigned int* tempUniqueSetONeighbs = (unsigned int*) malloc(sizeof(unsigned int)*sizeOfSetONeighbs);
	memset(tempUniqueSetO, 0, sizeof(unsigned int)*sizeOfSetO);
	memset(tempUniqueSetONeighbs, 0, sizeof(unsigned int)*sizeOfSetONeighbs);

	// "SetI0" is the set of unmatched vertices in "SetO", i.e. 0 in "pairU"
	// initializing "SetIn" with "SetI0"
	for (unsigned int i=0; i<sizeOfSetO; ++i) {
		if (!pairU[i+1]) {
			SetIn[sizeIn++] = i+1;
			tempUniqueSetO[i] = 1;
		}
	}

	// "SetI0" is empty; no crown
	if (!sizeIn) {
        free(tempUniqueSetO);
        free(tempUniqueSetONeighbs);
		return;
	}

	// "oldSizeIn", "oldSizeHn"
	// to start from them checking for new neighbors to add in ("SetHn", "SetIn")
	// to track if new vertices where added to ("SetIn", "SetHn")
	unsigned int oldSizeIn = 0;
	unsigned int oldSizeHn = 0;

	while(true) {
		// adding to "SetHn" unique neighbors of "SetIn"
		// updating "sizeHn" alongside
		for(unsigned int i=oldSizeIn; i<sizeIn; ++i) {
			unsigned int vertexOfIn = SetIn[i];
			std::list<int>::iterator j;
			for(j=adj_u[vertexOfIn].begin(); j!=adj_u[vertexOfIn].end(); ++j) {
					int neighborIndex = *j;
					if(!tempUniqueSetONeighbs[neighborIndex-1]) {
						SetHn[sizeHn++] = neighborIndex;
						tempUniqueSetONeighbs[neighborIndex-1] = 1;
					}
			}
        }
		// updating "oldSizeIn" for next iteration
		oldSizeIn = sizeIn;

		// adding to "SetIn" unique neighbors of "SetHn" that are in the maximum matching
		// updating "sizeIn" alongside
		for(unsigned int i=oldSizeHn; i<sizeHn; ++i) {
			unsigned int vertexOfHn = SetHn[i];
            int matchingPair = pairV[vertexOfHn];
            if(!tempUniqueSetO[matchingPair-1]) {
                SetIn[sizeIn++] = matchingPair;
                tempUniqueSetO[matchingPair-1] = 1;
            }
		}
		// updating "oldSizeHn" for next iteration
		oldSizeHn = sizeHn;

		// terminate if no vertcies where added (SetIn+1 == SetIn)
		if(oldSizeIn == sizeIn) {
            free(tempUniqueSetO);
            free(tempUniqueSetONeighbs);
			return;
		}
	}
}

bool crown_rule(CSRGraph& graph, int *vertexDegrees, unsigned int *numDeletedVertices) {

	unsigned int vertexNum = graph.vertexNum;

	// Finding a maximal match of graph
	// "isMatched" array (1 for matched vertices, 0 for unmatched vertices)
	unsigned int* isMatched = (unsigned int*)malloc(sizeof(unsigned int)*vertexNum);

	// initializing "isMatched" with 0s
	memset(isMatched, 0, sizeof(unsigned int)*vertexNum);

	// maximal_matching returns number of matches, and it updates "isMatched"
	unsigned int matchesNum = maximal_matching(graph, isMatched, vertexDegrees);
    //printf("NumMatches=%d\n", matchesNum);

	// Finding a maximum match of graph
	// finding "sizeOfSetO", "SetO" is the set of unmatched vertices
	int sizeOfSetO = vertexNum - matchesNum;

    // threshold for using crown
    if (sizeOfSetO<1) {
        free(isMatched);
        return false;
    }

	// adding the unmatched vertices to "SetO" using "isMatched"
	unsigned int SetO[sizeOfSetO];
	unsigned int counter = 0;
	for (unsigned int i=0; i<vertexNum; ++i) {
		if (!isMatched[i]) {
			SetO[counter++] = i;
		}
	}
	free(isMatched);

	// "NeighborsOfSetO" array stores the neighbors of "SetO"
	// "matchesNum" the maximum size it can reaches, since we still don't know its actual size
	unsigned int* NeighborsOfSetO = (unsigned int*)malloc(sizeof(unsigned int)*matchesNum);

	// initializing a bipartite graph with "sizeOfSetO" for the leftSide, and "matchesNum" for the rightSide
	// we need to initialize the bipGraph to add the edges between the two sets ("SetO" and "NeighborsOfSetO")
	BipGraph bipGraph(sizeOfSetO, matchesNum);

	// creating "tempNeighborsChecker" for not repeating common neighbors
	// it stores the position in "NeighborsOfSetO" for the added neighbor
	// tracking poistions of neighbors in "NeighborsOfSetO" is necessary for adding edges in the bipGraph
	unsigned int* tempNeighborsChecker = (unsigned int*)malloc(sizeof(unsigned int)*vertexNum);

	// initializing "tempNeighborsChecker" with 0s
	memset(tempNeighborsChecker, 0, sizeof(unsigned int)*vertexNum);

	// "sizeOfSetONeighbs" actual size of "NeighborsOfSetO"
	unsigned int sizeOfSetONeighbs = 0;

	// looping over the neighbors of each vertex in "SetO"
	for (unsigned int i=0; i<sizeOfSetO; ++i) {
		unsigned int sourceVertex = SetO[i];
		for (unsigned int edge = graph.srcPtr[sourceVertex]; edge<graph.srcPtr[sourceVertex]+graph.degree[sourceVertex]; ++edge) {
			unsigned int neighbor = graph.dst[edge];
            if (vertexDegrees[neighbor]>0) {
                if (!tempNeighborsChecker[neighbor]) {
                    // adding the neighbor to "NeighborsOfSetO", and increamenting "sizeOfSetONeighbs"
                    NeighborsOfSetO[sizeOfSetONeighbs++] = neighbor;

                    // stores in "tempNeighborsChecker" the position in "NeighborsOfSetO"
                    tempNeighborsChecker[neighbor] = sizeOfSetONeighbs;
                }
                // connecting the vertices in the bipartite graph between the two sets
                // i+1 position of sourceVertex in "SetO"
                // tempNeighborsChecker[neighbor] position of neighbor in "NeighborsOfSetO"
                bipGraph.addEdge(i+1, tempNeighborsChecker[neighbor]);
            }
		}
	}
	free(tempNeighborsChecker);

	// freeing the unused memeory in "NeighborsOfSetO"
	NeighborsOfSetO = (unsigned int*)realloc(NeighborsOfSetO, sizeof(unsigned int)*sizeOfSetONeighbs);

	// fixing the size of the rightSide in the bipartite graph
	// leftSide "SetO" of size "sizeOfSetO", rightSide "NeighborsOfSetO" of size "sizeOfSetONeighbs"
	bipGraph.setSizeOfRightSide(sizeOfSetONeighbs);

	// calling the hopcroft_karp algorithm to get a maximum matching
	unsigned int maxMatches = bipGraph.hopcroftKarp();

	// if all Neighbors are matched (straight crown), terminate by adding all Neighbors to the vertex cover
	if (maxMatches == sizeOfSetONeighbs) {
	    for (unsigned int i=0; i<sizeOfSetONeighbs; ++i) {
			unsigned int neighbor = NeighborsOfSetO[i];
	        deleteVertex(graph, neighbor, vertexDegrees, numDeletedVertices);
			//printf("%d ",neighbor); //printing the deleted vertices
	    }

		// printing the number of deleted vertices
        //printf("\nstraight_crown_");
        //printf("%d_%d\n",sizeOfSetONeighbs,sizeOfSetO);

		free(NeighborsOfSetO);
		return true;
	}

	// else we proceed by checking for a flared crown
	// "SetIn" and "SetHn" will store the index of the vertices in "SetO" and "NeighborsOfSetO" respectively
	// declaring "SetIn" and "SetHn" with the max sizes they can reach (sizeOfSetO, sizeOfSetONeighbs)
	// so, they will not store the actual vertex (better to make use of the "bipGraph")
	unsigned int SetIn[sizeOfSetO];
	unsigned int* SetHn = (unsigned int*)malloc(sizeof(unsigned int)*sizeOfSetONeighbs);
	unsigned int sizeIn = 0;
	unsigned int sizeHn = 0;

	// initializing "SetIn" with "SetI0" (set of unmatched vertices in "SetO" after running the hopcroft_karp)
	// "SetHn" = Neighbers of "SetIn" ("SetHn" is a subset of "NeighborsOfSetO")
	// SetIn+1 = "SetIn" U (Neighbors of "SetHn" in "SetO" that are in the maximum match)
	// Repeat till SetIn+1 == "SetIn"
	// these steps are performed by "flared_crown_checker"
	flared_crown_checker(bipGraph, SetIn, sizeIn, SetHn, sizeHn, sizeOfSetO, sizeOfSetONeighbs);   

	// if (!sizeIn or !sizeHn), then no crown exists
	if (sizeIn && sizeHn) {
		// terminate by adding all vertices in "SetHn" to the vertex cover
		for (unsigned int i=0; i<sizeHn; ++i) {
			int neighborIndex = SetHn[i];
			unsigned int neighbor = NeighborsOfSetO[neighborIndex-1];
            //printf("%d ",neighbor); //printing the deleted vertices
			deleteVertex(graph, neighbor, vertexDegrees, numDeletedVertices);
			
		}
	}
    
    free(NeighborsOfSetO);
	free(SetHn);

	// printing the number of deleted vertices
    if (sizeHn) {
        //printf("\nflared_crown_");
        //printf("%d_%d\n",sizeHn,sizeIn);
        return true;
    }
    return false;
}