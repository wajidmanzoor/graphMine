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


#ifndef ECL_GRAPHLONGCPU
#define ECL_GRAPHLONGCPU

#include <cstdlib>
#include <cstdio>

struct ECLgraph {
  long nodes;
  long edges;
  long* nindex;
  long* nlist;
  long* eweight;
};

ECLgraph readECLgraph(const char* const fname)
{
  ECLgraph g;
  long cnt;

  FILE* f = fopen(fname, "rb");  if (f == NULL) {fprintf(stderr, "ERROR: could not open file %s\n\n", fname);  exit(-1);}
  cnt = fread(&g.nodes, sizeof(g.nodes), 1, f);  if (cnt != 1) {fprintf(stderr, "ERROR: failed to read nodes\n\n");  exit(-1);}
  cnt = fread(&g.edges, sizeof(g.edges), 1, f);  if (cnt != 1) {fprintf(stderr, "ERROR: failed to read edges\n\n");  exit(-1);}
  if ((g.nodes < 1) || (g.edges < 0)) {fprintf(stderr, "ERROR: node or edge count too low\n\n");  exit(-1);}

  g.nindex = (long*)malloc((g.nodes + 1) * sizeof(g.nindex[0]));
  g.nlist = (long*)malloc(g.edges * sizeof(g.nlist[0]));
  g.eweight = (long*)malloc(g.edges * sizeof(g.eweight[0]));
  if ((g.nindex == NULL) || (g.nlist == NULL) || (g.eweight == NULL)) {fprintf(stderr, "ERROR: memory allocation failed\n\n");  exit(-1);}

  cnt = fread(g.nindex, sizeof(g.nindex[0]), g.nodes + 1, f);  if (cnt != g.nodes + 1) {fprintf(stderr, "ERROR: failed to read neighbor index list\n\n");  exit(-1);}
  cnt = fread(g.nlist, sizeof(g.nlist[0]), g.edges, f);  if (cnt != g.edges) {fprintf(stderr, "ERROR: failed to read neighbor list\n\n");  exit(-1);}
  cnt = fread(g.eweight, sizeof(g.eweight[0]), g.edges, f);
  if (cnt == 0) {
    free(g.eweight);
    g.eweight = NULL;
  } else {
    if (cnt != g.edges) {fprintf(stderr, "ERROR: failed to read edge weights\n\n");  exit(-1);}
  }
  fclose(f);

  return g;
}

void writeECLgraph(const ECLgraph g, const char* const fname)
{
  if ((g.nodes < 1) || (g.edges < 0)) {fprintf(stderr, "ERROR: node or edge count too low\n\n");  exit(-1);}
  long cnt;
  FILE* f = fopen(fname, "wb");  if (f == NULL) {fprintf(stderr, "ERROR: could not open file %s\n\n", fname);  exit(-1);}
  cnt = fwrite(&g.nodes, sizeof(g.nodes), 1, f);  if (cnt != 1) {fprintf(stderr, "ERROR: failed to write nodes\n\n");  exit(-1);}
  cnt = fwrite(&g.edges, sizeof(g.edges), 1, f);  if (cnt != 1) {fprintf(stderr, "ERROR: failed to write edges\n\n");  exit(-1);}

  cnt = fwrite(g.nindex, sizeof(g.nindex[0]), g.nodes + 1, f);  if (cnt != g.nodes + 1) {fprintf(stderr, "ERROR: failed to write neighbor index list\n\n");  exit(-1);}
  cnt = fwrite(g.nlist, sizeof(g.nlist[0]), g.edges, f);  if (cnt != g.edges) {fprintf(stderr, "ERROR: failed to write neighbor list\n\n");  exit(-1);}
  if (g.eweight != NULL) {
    cnt = fwrite(g.eweight, sizeof(g.eweight[0]), g.edges, f);  if (cnt != g.edges) {fprintf(stderr, "ERROR: failed to write edge weights\n\n");  exit(-1);}
  }
  fclose(f);
}

void freeECLgraph(ECLgraph &g)
{
  if (g.nindex != NULL) free(g.nindex);
  if (g.nlist != NULL) free(g.nlist);
  if (g.eweight != NULL) free(g.eweight);
  g.nindex = NULL;
  g.nlist = NULL;
  g.eweight = NULL;
}

#endif
