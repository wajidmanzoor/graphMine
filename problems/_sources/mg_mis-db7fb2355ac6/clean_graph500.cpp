/*
MG-MIS: This code computes a maximal independent set using multiple GPUs.

Copyright (c) 2025, Anju Mongandampulath Akathoott and Martin Burtscher

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

URL: The latest version of this code is available at https://cs.txstate.edu/~burtscher/research/MG-MIS/ and at https://github.com/burtscher/MG-MIS.

Publication: This work is described in detail in the following paper.
Anju Mongandampulath Akathoott, Benila Jerald, and Martin Burtscher. "A Multi-GPU Algorithm for Computing Maximal Independent Sets in Large Graphs." Proceedings of the 2025 ACM International Conference on Supercomputing. June 2025.
*/


#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>
#include <utility>
#include <fstream>
#include <sstream>
#include <string>
#include <algorithm>
#include <set>
#include "ECLgraph.h"

int main(int argc, char* argv[]) {
  printf("Graph500 to ECL converter (%s)\n", argv[1]);

  if (argc != 3) {fprintf(stderr, "Usage: %s input_file _name output_file_name\n\n", argv[0]); exit(-1);}

  std::ifstream fin(argv[1]);
  if (!fin.is_open()) {
    fprintf(stderr, "ERROR: could not open input file %s\n\n", argv[1]); exit(-1);
  }
  std::string line;
  long nodes = -1, edges = -1;

  // read lines until word Nodes: is found
  while (std::getline(fin, line)) {
    if (line.find("Nodes:") != std::string::npos) {
      break; // line with Nodes: is found
    }
  }

  // check if the data read in line is valid
  if (line.empty() || line.find("Nodes:") == std::string::npos || line.find("Edges:") == std::string::npos) {
    fprintf(stderr, "ERROR: could not find line with node and edge information\n\n");
  }

  std::istringstream iss(line);
  std::string word1, word2; 
  if (iss >> word1 >> nodes >> word2 >> edges) {
    if (word1 == "Nodes:" && word2 == "Edges:") {
      printf("Nodes: %ld\nEdges: %ld\n", nodes, edges);
    }
  } else {
    fprintf(stderr, "Failed to read the nodes and edge count\n\n"); exit(-1);
  }


  ECLgraph g;
  long src, dst;
  long cnt = 0;
  std::vector<std::pair<long, long> > v;

  if (fin >> src >> dst) {
    cnt++;
    if ((src < 0) || (src >= nodes)) {
      fprintf(stderr, "ERROR: source out of range"); exit(-1);
    }
    if ((dst < 0) || (dst >= nodes)) {
      fprintf(stderr, "ERROR: destination out of range"); exit(-1);
    }
    v.push_back(std::make_pair(src, dst));
  }

  while (fin >> src >> dst) {
    cnt++;
    if ((src < 0) || (src >= nodes)) {
      fprintf(stderr, "ERROR: source out of range"); exit(-1);
    }
    if ((dst < 0) || (dst >= nodes)) {
      fprintf(stderr, "ERROR: destination out of range"); exit(-1);
    }
    v.push_back(std::make_pair(src, dst));
  }

  fin.close();

  printf("Number of edges read: %ld\n", cnt);

  std::sort(v.begin(), v.end());
  std::vector<std::pair<long, long> > v_new;
  std::set<std::pair<long, long>> edge_set; // set for unique edges
  for (long i = 0; i < v.size(); i++) {
    long src = v[i].first;
    long dst = v[i].second;
    if (src == dst) {
      continue;
    } 
    std::pair<long, long> edge = (src < dst) ? std::make_pair(src, dst) : std::make_pair(dst, src);
    if (edge_set.find(edge) == edge_set.end()) {
      edge_set.insert(edge); // add edge to set
      v_new.push_back(std::make_pair(src, dst));
      v_new.push_back(std::make_pair(dst, src));
    }
  }

  edges = v_new.size();
  printf("#edges counted in one dir = %ld\n", edge_set.size());
  printf("Edge count after removing self loop and multiple edges %ld\n", edges);
  std::sort(v_new.begin(), v_new.end());

  g.nodes = nodes;
  g.edges = v_new.size();
  g.nindex = (long*)calloc(nodes + 1, sizeof(long));
  g.nlist = (long*)malloc(v_new.size() * sizeof(long));
  g.eweight = NULL;
  if ((g.nindex == NULL) || (g.nlist == NULL)) {fprintf(stderr, "ERROR: memory allocation failed\n\n"); exit(-1);}

  g.nindex[0] = 0;
  for (long i = 0; i < v_new.size(); i++) {
    long src = v_new[i].first;
    long dst = v_new[i].second;
    g.nindex[src + 1] = i + 1;
    g.nlist[i] = dst;
  }

  for (long i = 1; i < (nodes + 1); i++) {
    g.nindex[i] = std::max(g.nindex[i - 1], g.nindex[i]);
  }

  writeECLgraph(g, argv[2]);
  freeECLgraph(g);

  printf("Graph500 conversion to ECL graph successful!\n\n");

  return 0;
}
