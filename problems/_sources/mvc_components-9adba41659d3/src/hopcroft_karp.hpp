#ifndef HOPCROFT_KARP_HPP
#define HOPCROFT_KARP_HPP
// Code Source: geeksforgeeks.org
// Hopcroft–Karp Algorithm for Maximum Matching | Set 2 (Implementation)
// this code contains some changes from the original one

// C++ implementation of Hopcroft Karp algorithm for maximum matching
#include <list>
#include <climits>

#define NIL 0
#define INF INT_MAX

// A class to represent Bipartite graph for Hopcroft
// Karp implementation
class BipGraph
{
	// m and n are number of vertices on left
	// and right sides of Bipartite Graph
	int m, n;

	// adj_u[u] stores adjacents of left side
	// vertex 'u'. The value of u ranges from 1 to m.
	// 0 is used for dummy vertex
	std::list<int> *adj_u;

	// These are basically pointers to arrays needed
	// for hopcroftKarp()
	int *pairU, *pairV, *dist;

public:
	BipGraph(int m, int n); // Constructor
	void addEdge(int u, int v); // To add edge

	// Returns true if there is an augmenting path
	bool bfs();

	// Adds augmenting path if there is one beginning
	// with u
	bool dfs(int u);

	// Returns size of maximum matching
	int hopcroftKarp();

	// Return pointer to PairU
	int* getPtrPairU() const;
    
    // Returns pointer PairV
    int* getPtrPairV() const;

	// Return pointer to adj_u
	std::list<int>* getPtrAdjU() const;

	// Change size of the rightSide
	void setSizeOfRightSide(int n);

	~BipGraph(); // Destructor
};

#endif