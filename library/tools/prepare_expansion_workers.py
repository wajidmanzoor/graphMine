#!/usr/bin/env python3
"""Expose upstream GPU results without changing kernels. Emit reviewable patches."""
import difflib
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1] / 'src/backends/expansion/upstream'
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, record in json.loads((root / 'PROVENANCE.json').read_text()).items():
    for file, expected in record['files'].items():
        if hashlib.sha256((root/name/file).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Pinned upstream source changed: ' + name + '/' + file)


def replace(text, before, after, count=1):
    if text.count(before) != count:
        raise RuntimeError('Adaptation anchor changed: ' + before)
    return text.replace(before, after)


def emit(source, dest, transform):
    original=(root/source).read_text()
    adapted=transform(original)
    for path, text in [(out/dest, adapted),
                       (out/(dest+'.patch'), ''.join(difflib.unified_diff(original.splitlines(True),adapted.splitlines(True),fromfile=source,tofile=dest)))]:
        if not path.exists() or path.read_text() != text:
            path.write_text(text)


emit('ecl_scc/source/ECL-SCC_10.cu','ecl_scc.cu',lambda t:replace(t,'  // output SCC sizes and frequency',
    '  if (cudaDeviceSynchronize() != cudaSuccess || cudaGetLastError() != cudaSuccess) return 9;\n'
    '  printf("GRAPHMINE_COMPONENTS");\n'
    '  for (int v=0; v<n; ++v) printf(" %d", iomax[v].x);\n'
    '  printf("\\n");\n  // output SCC sizes and frequency'))
emit('ecl_flow/src/main.cu','ecl_flow.cu',lambda t:replace(t,'  cudaFree(d_g.nindex);',
    '  CheckCuda();\n  printf("GRAPHMINE_FLOW");\n'
    '  for (int e=0; e<g.edges; ++e) printf(" %d", flow[e]);\n'
    '  printf("\\n");\n  cudaFree(d_g.nindex);'))


def flow_launch_guards(t):
    # The upstream do/while enters once with an empty worklist, and initialPush
    # can also have zero work. Skip only those zero-grid launches.
    t=replace(t,'    phase1_pushRelabel<<<blocks, ThreadsPerBlock>>>',
                '    if (blocks > 0) phase1_pushRelabel<<<blocks, ThreadsPerBlock>>>')
    t=replace(t,'  initialPush<<<blocks, ThreadsPerBlock>>>',
                '  if (blocks > 0) initialPush<<<blocks, ThreadsPerBlock>>>')
    # Avoid integer truncation to zero and division by zero on sparse graphs.
    t=replace(t,'const double avgDeg = g.edges / g.nodes;',
                'const double avgDeg = std::max(1.0, double(g.edges) / g.nodes);')
    return t


emit('ecl_flow/src/maxflow.cu','maxflow.cu',flow_launch_guards)


def assignment(t):
    t=replace(t,'int main()','int upstream_main()')
    return t+r'''
// Complete square minimum-cost assignment, padded with zero-cost dummy rows.
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  FILE* input = fopen(argv[1], "r");
  if (!input) return 3;
  int count = 0;
  if (fscanf(input, "%d", &count) != 1 || count < 1 || count > n) return 4;
  for (int c=0; c<n; ++c) for (int r=0; r<n; ++r)
    h_cost[c][r] = (c >= count && r < count) ? 100000000 : 0;
  for (int r=0; r<count; ++r) for (int c=0; c<count; ++c)
    if (fscanf(input, "%d", &h_cost[c][r]) != 1) return 5;
  fclose(input);
  checkCuda(cudaMemcpyToSymbol(slack, h_cost, sizeof(h_cost)));
  Hungarian_Algorithm();
  checkCuda(cudaDeviceSynchronize());
  checkCuda(cudaMemcpyFromSymbol(h_column_of_star_at_row,
      column_of_star_at_row, sizeof(h_column_of_star_at_row)));
  printf("GRAPHMINE_ASSIGNMENT");
  for (int r=0; r<count; ++r) printf(" %d", h_column_of_star_at_row[r]);
  printf("\n");
  return 0;
}
'''


emit('hungarian/HungarianCUDA.cu','hungarian.cu',assignment)

# Retain the relational join/fixpoint computation. Replace the capped diagnostic
# printer with a checked, complete result collector (at most 1024^2 pairs).
collector=r'''
static void graphmine_pairs(GHashRelContainer* relation) {
    if (relation->tuple_counts > 1024ULL*1024ULL) exit(8);
    std::vector<tuple_type> pointers(relation->tuple_counts);
    if (cudaMemcpy(pointers.data(), relation->tuples,
                   pointers.size()*sizeof(tuple_type), cudaMemcpyDeviceToHost) != cudaSuccess) exit(9);
    std::cout << "GRAPHMINE_PAIRS " << pointers.size() << "\n";
    for (auto pointer : pointers) {
        column_type pair[2];
        if (cudaMemcpy(pair, pointer, sizeof(pair), cudaMemcpyDeviceToHost) != cudaSuccess) exit(9);
        std::cout << pair[0] << " " << pair[1] << "\n";
    }
    std::cout << "GRAPHMINE_END\n";
    if (cudaDeviceSynchronize() != cudaSuccess || cudaGetLastError() != cudaSuccess) exit(9);
}
'''


def reachability(t):
    t=t.replace('#include "../include/','#include "')
    t=replace(t,'void analysis_bench(',collector+'\nvoid analysis_bench(')
    t=replace(t,'// print_tuple_rows(path_2__2_1->full, "full");','graphmine_pairs(path_2__1_2->full);',2)
    return replace(t,'    int device_id;','    if (argc != 3) return 2;\n    int device_id;')


emit('gdlog/test/tc.cu','gdlog_tc.cu',reachability)
