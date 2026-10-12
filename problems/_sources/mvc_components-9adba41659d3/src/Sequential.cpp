#include "Sequential.h"

#include "helperFunctions.h"
#include "stack.h"
#include "crown.hpp"
#include <stdlib.h>
#include <stdio.h>
#include <queue>
//#include <set>

static unsigned int compSequential(CSRGraph graph, unsigned int minimum, int *rootVertexDegrees, unsigned int left, unsigned int right)
{
    Stack stack;
    stack.size = minimum + 1;
    stack.stack = (int*)calloc((long long)stack.size * (long long)graph.vertexNum, sizeof(int));
    stack.stackNumDeletedVertices = (unsigned int*)calloc(stack.size, sizeof(unsigned int));
    
    for(unsigned int v = left; v < right + 1; ++v) {
        stack.stack[v] = rootVertexDegrees[v];
    }
    
    stack.stackNumDeletedVertices[0] = 0;
    stack.top = 0;
    bool popNextItr = true;

    int* vertexDegrees = (int*)calloc(sizeof(int),graph.vertexNum);
    unsigned int numDeletedVertices;
 
    while (stack.top != -1)
    {
        unsigned int left_temp = left;
        unsigned int right_temp = right;
        if (popNextItr)
        {
            unsigned short fl_temp = 0;
            numDeletedVertices = stack.stackNumDeletedVertices[stack.top];
            for (unsigned int j = left; j < right+1; ++j)
            {
                vertexDegrees[j] = stack.stack[(long long)stack.top * (long long)graph.vertexNum + (long long)j];
                
                if(vertexDegrees[j] > 0){
                    
                    if(!fl_temp){
                        left_temp = j;
                        fl_temp = 1;
                    }
                    right_temp = j;
                }
            }
            --stack.top;
        }     
        
        bool leafHasChanged = false, highDegreeHasChanged = false, triangleHasChanged = false;
        unsigned int iterationCounter = 0;

        do
        {
            leafHasChanged = leafReductionRule(graph, vertexDegrees, &numDeletedVertices, left_temp, right_temp);
            if (iterationCounter==0 || leafHasChanged || highDegreeHasChanged) {
                triangleHasChanged = triangleReductionRule(graph, vertexDegrees, &numDeletedVertices, left_temp, right_temp);
            } else {
                triangleHasChanged = false;
            }
            if (iterationCounter==0 || leafHasChanged || triangleHasChanged) {
                highDegreeHasChanged = highDegreeReductionRule(graph, vertexDegrees, &numDeletedVertices, minimum, left_temp, right_temp);
            } else {
                highDegreeHasChanged = false;
            }
            ++iterationCounter;
        } while (triangleHasChanged || highDegreeHasChanged);

        unsigned int maxVertex= left_temp;
        int maxDegree = 0;
        unsigned int numEdges = 0;

        for (unsigned int i = left_temp; i < right_temp + 1; ++i)
        {
            int degree = vertexDegrees[i];
            if (degree > maxDegree)
            {
                maxDegree = degree;
                maxVertex = i;
            }
            if (degree > 0)
            {
                numEdges += degree;
            }
        }

        numEdges /= 2;
        if (numDeletedVertices >= minimum || numEdges >= squareSequential(minimum - numDeletedVertices - 1) + 1)
        {
            popNextItr = true;
        }
        else
        {
            if (maxDegree == 0)
            {
                minimum = numDeletedVertices;
                popNextItr = true;
            }
            else
            { 
                unsigned int inside_remaining_vertices = 0;
                int* inside_components = (int*)malloc(sizeof(int)*graph.vertexNum);
                bool inside_found = true;
                std::queue<unsigned int> inside_q;
                for(unsigned int i = left_temp; i < right_temp + 1; ++i) {
                    if(vertexDegrees[i] > 0) {
                        ++inside_remaining_vertices;
                        inside_components[i] = 0;
                        if(inside_found) {
                            inside_q.push(i);
                            inside_components[i] = 1;
                            inside_found = false;
                            --inside_remaining_vertices;
                        }
                    } else {
                        inside_components[i] = -1;
                    }
                }                           
                unsigned int inside_counter = 1;
                while(inside_remaining_vertices > 0) {
                    if(!inside_q.empty()) {
                        unsigned int vertex = inside_q.front();
                        inside_q.pop();
                        for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                            unsigned int neigh = graph.dst[edge];
                            if( vertexDegrees[neigh] > 0 && inside_components[neigh] == 0) {
                                inside_components[neigh] = inside_counter;
                                inside_q.push(neigh);
                                --inside_remaining_vertices;   
                            }
                        } 
                    } else {
                        ++inside_counter;
                        for(unsigned int i = left_temp; i < right_temp + 1; ++i ) {
                            if(inside_components[i] == 0) {
                                inside_q.push(i);
                                inside_components[i] = inside_counter;
                                --inside_remaining_vertices;
                                break;
                            }
                        }
                    }
                }
                
                if (inside_counter==1) {
                
                    popNextItr = false;
                    ++stack.top;

                    for (unsigned int j = left_temp; j < right_temp + 1; ++j)
                    {  
                         stack.stack[(long long)stack.top * (long long)graph.vertexNum + (long long)j] = vertexDegrees[j];
                    }

                    stack.stackNumDeletedVertices[stack.top] = numDeletedVertices;

                    for (unsigned int i = graph.srcPtr[maxVertex]; i < graph.degree[maxVertex] + graph.srcPtr[maxVertex]; ++i)
                    {
                        deleteVertex(graph, graph.dst[i], &stack.stack[(long long)stack.top * (long long)graph.vertexNum],
                                     &stack.stackNumDeletedVertices[stack.top]);
                    }

                    deleteVertex(graph, maxVertex, vertexDegrees, &numDeletedVertices);

               } else {

                    popNextItr = true;
                    if (minimum-numDeletedVertices<=inside_counter) {
                        continue;
                    }
                    int *inside_vertexDegrees = (int*)calloc(sizeof(int),graph.vertexNum);
                    unsigned int minim;
                    for(unsigned int i=1; i <= inside_counter; ++i) {
                        unsigned int inside_compSize = 0;
                        unsigned int inside_l = left_temp;
                        unsigned int inside_r = left_temp;
                        unsigned int fl = 0;
                        unsigned int first_vertex = 0;

                        for(unsigned int v = left_temp; v < right_temp + 1; ++v) {
                            if(inside_components[v] != i) {
                                inside_vertexDegrees[v] = 0;
                            } else {
                                unsigned int degree = vertexDegrees[v];
                                inside_vertexDegrees[v] = degree;
                                if(!fl){
                                    first_vertex = degree;
                                    inside_l = v;
                                    fl = 1;
                                }
                                if(degree != first_vertex){
                                    first_vertex = 0;
                                }
                                inside_r = v;
                                ++inside_compSize;
                            }
                        }
                        if (numDeletedVertices<minimum) {
                            minim = (minimum-numDeletedVertices<inside_compSize-1)?minimum-numDeletedVertices:inside_compSize-1;
                            if(first_vertex == 2){
                                numDeletedVertices += (inside_compSize + 1) / 2;
                            }else if(first_vertex == inside_compSize - 1){
                                numDeletedVertices += first_vertex;
                            }else{
                                numDeletedVertices += compSequential(graph, minim, inside_vertexDegrees, inside_l, inside_r);
                            }
                            
                        } else {
                            break;
                        }
                    }
                    free(inside_vertexDegrees);
                    if (minimum>numDeletedVertices) {
                        minimum = numDeletedVertices;
                    }
                }
                
                free(inside_components);
            }
        }
    }
    free(stack.stack);
    free(stack.stackNumDeletedVertices);
    free(vertexDegrees);

    return minimum;
}

unsigned int Sequential(CSRGraph graph, unsigned int minimum)
{
    int *rootVertexDegrees = (int*)calloc(sizeof(int),graph.vertexNum);
    for (unsigned int i = 0; i < graph.vertexNum; ++i)
    {
        rootVertexDegrees[i] = graph.degree[i];
    }
    unsigned int remaining_vertices = 0;
    int* components = (int*)calloc(sizeof(int),graph.vertexNum);
    bool found = true;
    
    std::queue<unsigned int> q;
    for(unsigned int i = 0; i < graph.vertexNum; ++i) {
        if(rootVertexDegrees[i] > 0) {
            ++remaining_vertices;
            components[i] = 0;
            if(found) {
                q.push(i);
                components[i] = 1;
                found = false;
                --remaining_vertices;
            }
        } else {
            components[i] = -1;
        }
    }
    unsigned int counter = 1;

    while(remaining_vertices > 0) {    
        if(!q.empty()) {
            unsigned int vertex = q.front();
            q.pop();
            for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
                unsigned int neigh = graph.dst[edge];
                if(components[neigh] == 0) {
                    components[neigh] = counter;
                    q.push(neigh);
                    --remaining_vertices;   
                }
            }
        } else {
            ++counter;
            for(unsigned int i = 0; i<graph.vertexNum; ++i ) {
                if(components[i] == 0) {
                    q.push(i);
                    components[i] = counter;
                    --remaining_vertices;
                    break;
                }
            }
        }
    }
    // For Debugging Purposes
    //printf("Components at Root = %d \n",counter);

    unsigned int rootNumDeletedVertices = 0;
    unsigned int minim = 0;
    int *vertexDegrees = (int*)calloc(sizeof(int),graph.vertexNum);
    for(unsigned int i=1; i <= counter; ++i) {
        unsigned int compSize = 0;
        unsigned int left = 0;
        unsigned int right = 0;
        unsigned short fl = 0;
        unsigned int first_vertex = 0;
        for(unsigned int v = 0; v < graph.vertexNum; ++v) {
            if(components[v] != i) {
                vertexDegrees[v] = 0;
            } else {
                unsigned int degree =  rootVertexDegrees[v];
                vertexDegrees[v] = degree;
                if (!fl){
                    first_vertex = degree;
                    left = v;
                    fl = 1;
                }
                if(degree != first_vertex){
                    first_vertex = 0;
                }
                right = v;
                ++compSize;
            }
        }

        if (rootNumDeletedVertices<minimum) {
            minim = (minimum-rootNumDeletedVertices<compSize-1)?minimum-rootNumDeletedVertices:compSize-1;
            if(first_vertex == 2){
                rootNumDeletedVertices += (compSize+1)/2;
            }else if(first_vertex == compSize - 1){
                rootNumDeletedVertices += first_vertex;
            }else{
                rootNumDeletedVertices += compSequential(graph, minim, vertexDegrees, left, right);
            }

        } else {
            break;
        }
        // For Debugging Purposes
        //printf("%d and i = %d\n",compSize, i);
        //return rootNumDeletedVertices;
    }
    minimum = (rootNumDeletedVertices<minimum) ? rootNumDeletedVertices : minimum;

    free(vertexDegrees);
    free(components);
    free(rootVertexDegrees);
    graph.del();
    
    return minimum;
}