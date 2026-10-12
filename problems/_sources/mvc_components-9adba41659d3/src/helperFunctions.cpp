#include "helperFunctions.h"
#include <vector>
#include <set>
#include <stdio.h>
#include <algorithm>
#include <queue>

long long int squareSequential(int num)
{
    return num * num;
}

bool binarySearchSequential(unsigned int *arr, int l, int r, unsigned int x)
{
    while (l <= r)
    {
        int m = l + (r - l) / 2;

        if (arr[m] == x)
            return true;

        if (arr[m] < x)
            l = m + 1;

        else
            r = m - 1;
    }

    return false;
}

int *deleteVertex(CSRGraph &graph, unsigned int vertex, int *vertexDegrees, unsigned int *numDeletedVertices)
{
    if (vertexDegrees[vertex] <= 0)
    {
        return vertexDegrees;
    }

    for (unsigned int i = graph.srcPtr[vertex]; i < graph.srcPtr[vertex] + graph.degree[vertex]; ++i)
    {
        unsigned int neighbor = graph.dst[i];

        if (vertexDegrees[neighbor] > 0)
        {
            --vertexDegrees[neighbor];
        }
    }

    vertexDegrees[vertex] = -1;
    ++(*numDeletedVertices);
    return vertexDegrees;
}

bool leafReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right)
{
    bool hasDeleted = false;
    bool hasChanged;
    do
    {
        hasChanged = false;
        for (unsigned int i = left; i < right + 1; ++i)
        {
            if (vertexDegrees[i] == 1)
            {
                hasChanged = true;
                for (unsigned int j = graph.srcPtr[i]; j < graph.srcPtr[i] + graph.degree[i]; ++j)
                {
                    if (vertexDegrees[graph.dst[j]] > 0)
                    {
                        hasDeleted = true;
                        unsigned int neighbor = graph.dst[j];
                        deleteVertex(graph, neighbor, vertexDegrees, numDeletedVertices);
                    }
                }
            }
        }
    } while (hasChanged);

    return hasDeleted;
}

bool highDegreeReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, int minimum, unsigned int left, unsigned int right)
{
    bool hasDeleted = false;
    bool hasChanged;
    do
    {
        hasChanged = false;
        for (unsigned int i = left; i < right + 1; ++i)
        {
            if (vertexDegrees[i] > 0 && vertexDegrees[i] + *numDeletedVertices >= minimum)
            {
                hasChanged = true;
                hasDeleted = true;
                deleteVertex(graph, i, vertexDegrees, numDeletedVertices);
            }
        }
    } while (hasChanged);

    return hasDeleted;
}

bool triangleReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right)
{
    bool hasDeleted = false;
    bool hasChanged;
    do
    {
        hasChanged = false;
        for (unsigned int i = left; i < right + 1; ++i)
        {
            if (vertexDegrees[i] == 2)
            {

                unsigned int neighbor1, neighbor2;
                bool foundNeighbor1 = false, keepNeighbors = false;
                for (unsigned int edge = graph.srcPtr[i]; edge < graph.srcPtr[i] + graph.degree[i]; ++edge)
                {
                    unsigned int neighbor = graph.dst[edge];
                    int neighborDegree = vertexDegrees[neighbor];
                    if ( neighborDegree > 0)
                    {
                        if (neighborDegree == 1 || neighborDegree == 2 && neighbor < i)
                        {
                            keepNeighbors = true;
                            break;
                        }
                        else if (!foundNeighbor1)
                        {
                            foundNeighbor1 = true;
                            neighbor1 = neighbor;
                        }
                        else
                        {
                            neighbor2 = neighbor;
                            break;
                        }
                    }
                }

                if (!keepNeighbors)
                {
                    bool found = binarySearchSequential(graph.dst, graph.srcPtr[neighbor2], graph.srcPtr[neighbor2 + 1] - 1, neighbor1);

                    if (found)
                    {
                        hasChanged = true;
                        hasDeleted = true;
                        deleteVertex(graph, neighbor1, vertexDegrees, numDeletedVertices);
                        deleteVertex(graph, neighbor2, vertexDegrees, numDeletedVertices);
                        break;
                    }
                }
            }
        }
    } while (hasChanged);

    return hasDeleted;
}

bool cliqueReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right)
{
    unsigned int maxK = 100;
    bool hasDeleted = false;
    bool inClique;
    std::vector<unsigned int> visited(graph.vertexNum,0);
    
    for (unsigned int vertex = left; vertex < right + 1; ++vertex) {
        
        int k = vertexDegrees[vertex]+1;
        if(k<=maxK && vertexDegrees[vertex]>2 && !visited[vertex]) {
            inClique = true;
            for (unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex]+graph.degree[vertex]; ++edge) {
                unsigned int neigh = graph.dst[edge];
                if(neigh <= right && neigh >= left && vertexDegrees[neigh]>0) {
                    if(vertexDegrees[neigh]!=k-1 || visited[neigh]) {
                        inClique = false;
                        visited[neigh] = 1;
                        break;
                    }
                } else {
                    visited[neigh] = 1;
                }
            }
            if(inClique) {
                std::set<unsigned int> cliqueVertices;
                cliqueVertices.insert(vertex);
                for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex]+graph.degree[vertex]; ++edge) {
                    unsigned int neigh = graph.dst[edge];
                    if(neigh <= right && neigh >= left && vertexDegrees[neigh]>0) {
                        cliqueVertices.insert(neigh);
                    }
                }
                for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex]+graph.degree[vertex]; ++edge) {
                    unsigned int subject = graph.dst[edge];
                    if(subject <= right && subject >= left && vertexDegrees[subject]>0) {
                        for(unsigned int v = graph.srcPtr[subject]; v<graph.srcPtr[subject]+graph.degree[subject]; ++v) {
                            unsigned int neigh = graph.dst[v];
                            if(neigh <= right && neigh >= left && vertexDegrees[neigh]>0) {
                                if (cliqueVertices.find(neigh) == cliqueVertices.end()) {
                                    inClique = false;
                                    break;
                                }
                            }
                        }
                        if(!inClique) {
                            break;
                        }
                    }  
                }
                if (inClique) {
                    hasDeleted = true;
                    unsigned int counter = 0;
                    vertexDegrees[vertex] = 0;
                    //printf("Clique: %d, ",vertex);
                    for (unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex]+graph.degree[vertex]; ++edge) {
                        unsigned int neighbor = graph.dst[edge];
                        
                        if(neighbor <= right && neighbor >= left && vertexDegrees[neighbor]>0) {
                            //printf("%d, ",neighbor);
                            vertexDegrees[neighbor] = -1;
                            ++(*numDeletedVertices);  
                            ++counter;
                        }
                    }
                    //printf("\n");
                    //printf("Clique Deletion = %d\n",counter);
                }
            }
            
        }
        visited[vertex] = 1;
    }
    return hasDeleted;
}


bool cycleReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right)
{
    bool hasDeleted = false;
    std::vector<unsigned int> visited(graph.vertexNum,0);
    
    for(unsigned int i = left; i < right + 1; ++i) {
        if(visited[i] == 0) {
            visited[i] = 1;
            if(vertexDegrees[i]!=2) {
                if (vertexDegrees[i]>0) {
                    for(unsigned int edge = graph.srcPtr[i]; edge<graph.srcPtr[i]+graph.degree[i]; ++edge) {
                        visited[graph.dst[edge]] = 1;
                    }
                }
            } else {
                bool x = false;
                unsigned int second;
                unsigned int last;
                for(unsigned int edge=graph.srcPtr[i]; edge<graph.srcPtr[i]+graph.degree[i]; ++edge) {
                    unsigned int neigh = graph.dst[edge];
                    if(neigh >= left && neigh <= right && vertexDegrees[neigh]>0) {
                        if(x) {
                            last = neigh;
                        } else {
                            second = neigh;
                            x = true; 
                        }
                    } else {
                        visited[neigh] = 1;
                    }
                }
                if(vertexDegrees[last] != 2) {
                    visited[last] = 1;
                    visited[second] = 1;
                    continue;
                }
                
                unsigned int first = i;
                std::vector<unsigned int> cycle;
                cycle.push_back(first);
                bool isCycle = true;
                bool done = false;

                while(isCycle) {
                    visited[second] = 1;
                    if(vertexDegrees[second] == 2) {
                        cycle.push_back(second);
                        for(unsigned int edge=graph.srcPtr[second]; edge<graph.srcPtr[second]+graph.degree[second]; ++edge) {
                            unsigned int neigh = graph.dst[edge];
                            if(neigh!=first && neigh >= left && neigh <= right && vertexDegrees[neigh]>0) {
                                if(vertexDegrees[neigh] != 2 || visited[neigh]) {
                                    isCycle = false;
                                    visited[neigh] = 1;
                                    break;
                                } else {
                                    if(neigh!=last) {
                                        first = second;
                                        second = neigh;
                                        break;
                                    } else {
                                        done = true;
                                        cycle.push_back(neigh);
                                        break;
                                    }
                                }
                            }
                            visited[neigh]=1;
                        }
                        if(done) {
                            /*printf("%d\n", i);
                            std::set<unsigned int> hi;
                            for (unsigned int i = 0; i < graph.vertexNum; ++i) {
                                if (vertexDegrees[i]>0) {
                                    for(unsigned int edge = graph.srcPtr[i]; edge<graph.srcPtr[i] + graph.degree[i]; ++edge){
                                        unsigned int neigh = graph.dst[edge];
                                        if(vertexDegrees[neigh]>0) {
                                            if(hi.find(neigh)==hi.end())
                                                printf("%d %d\n",i,neigh);
                                        }
                                    }
                                    hi.insert(i);
                                }
                            }*/
                            
                            //printf("Cycle: ");
                            for(unsigned int j=0; j<cycle.size(); j+=2) {
                                vertexDegrees[cycle[j]] = -1;
                                //printf("%d, ",cycle[j]);
                                if(j<cycle.size()-1) {
                                    vertexDegrees[cycle[j+1]] = 0;
                                    //printf("%d, ",cycle[j+1]);
                                }
                                ++(*numDeletedVertices);  
                            }
                            //printf("\n");
                            //printf("Cycle Deletion = %d\n",cycle.size());
                            hasDeleted = true;
                            break;
                        }    
                    } else {
                        isCycle = false;
                    }
                }
            }
        }
    }
    return hasDeleted;
}
