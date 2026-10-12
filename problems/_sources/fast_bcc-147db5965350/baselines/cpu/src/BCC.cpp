#include "BCC.h"

#include <iostream>
#include "Graph_CSR.h"

#include "graph.h"
#include "hopcroft_tarjan.h"

int NUM_ROUNDS = 3;

//customread
Graph customread(std::string filename) {
  ifstream edgeList(filename);
  if (!edgeList) {
    cerr << "Error opening file " << filename << endl;
    abort();
  }

  Graph g = Graph();
  cout<<"Reading graph from file " << filename << endl;
  unweightedGraph G(filename);
  cout<<"Graph read from file " << filename << endl;
  
  g.n = G.totalVertices;
  g.m = G.totalEdges;

  std::cout << "totalVertices: " << G.totalVertices << " and G.totalEdges: " << G.totalEdges << std::endl;
  
  for(int i = 0; i < G.totalVertices; i++) {
    g.offset.push_back(G.offset[i]);
  }

  g.offset.push_back(G.totalEdges);
  for(int i = 0; i < G.totalEdges; i++) {
    g.E.push_back(G.neighbour[i]);
  }

  return g;
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    cerr << "Usage: " << argv[0] << " filename\n";
    abort();
  }
  char* filename = argv[1];
  if (argc >= 3) {
    NUM_ROUNDS = atoi(argv[2]);
  }

  Graph g = customread(filename);

  std::cout << "Reading the graph completed." << std::endl;

  double total_time = 0;
  for (int i = 0; i <= NUM_ROUNDS; i++) {
    if (i == 0) {
      BCC solver(g);
      internal::timer t_critical;
      solver.biconnectivity();
      t_critical.stop();
      printf("Warmup round: %f secs\n", t_critical.total_time());
    } else {

      BCC solver(g);
      internal::timer t_critical;
      solver.biconnectivity();
      t_critical.stop();
      printf("Round %d: %f\n", i, t_critical.total_time());
      total_time += t_critical.total_time();
    }
  }

  std::cout << "\n\nStarting From Here.\n\n";

  auto start = std::chrono::high_resolution_clock::now();
  
  BCC solver(g);
  auto label = solver.biconnectivity();
  solver.get_articulation_point(label);
  solver.get_num_bcc(label);

  auto end = std::chrono::high_resolution_clock::now();
  auto dur = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
  std::cout << "Fast BCC running time using chrono: " << dur << " ms." << std::endl;
  
  printf("Average time: %f secs\n", total_time / NUM_ROUNDS);
  std::ofstream ofs("fast-bcc.csv", ios_base::app);
  ofs << total_time / NUM_ROUNDS << '\n';
  ofs.close();
  return 0;
}
