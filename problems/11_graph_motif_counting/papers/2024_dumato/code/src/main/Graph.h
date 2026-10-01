#ifndef GRAPH_H
#define GRAPH_H

#include <map>
#include <set>
#include <vector>
#include <stdio.h>
#ifdef GRAPHMINE_LIBRARY
#include <cstdint>
#endif



class Graph {
	private:
		FILE* fp;
		std::map<int,std::set<int>*>* vertexes;
		std::set<int>* vertexIds;
		std::vector<std::map<int,int>*>* edgeWeight;
		int numberOfEdges;
		int maxVertexId;
		int maxDegree;
		bool full;

	public:
		Graph();
		Graph(const char*);
#ifdef GRAPHMINE_LIBRARY
		Graph(const std::vector<std::int64_t>& offsets,
		      const std::vector<std::int32_t>& neighbours);
#endif
		void addEdge(int src, int dst);
		std::set<int>* getNeighbours(int vertex);
		bool areNeighbours(int vertex1, int vertex2);
		int getMaxVertexId();
		int getNumberOfEdges();
		int getNumberOfVertices();
		int getCurrentNumberOfEdges();
		int getMaxDegree();
		void addEdgeWeight(int src, int dst, int amount);
		int getEdgeWeight(int src, int dst);
		int calculateWeight(unsigned int* subgraph, int k);
		std::map<int,std::set<int>*>* getVertexes();
		std::set<int>* getVertexIds();
		void print();
		void printToFile(const char *filename);
		long unsigned int stats();
		
		~Graph();
};

#endif
