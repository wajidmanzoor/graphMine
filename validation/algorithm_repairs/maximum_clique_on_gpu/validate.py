#!/usr/bin/env python3
"""Deterministic, independent correctness checks for the repaired native backend."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import time

import networkx as nx

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exhaustive(n, edges):
    """Enumerate every vertex subset, using bit masks only to check its edges."""
    adjacency = [0] * n
    for u, v in edges:
        adjacency[u] |= 1 << v
        adjacency[v] |= 1 << u
    clique = bytearray(1 << n)
    clique[0] = 1
    best = 0
    for mask in range(1, 1 << n):
        bit = mask & -mask
        rest = mask ^ bit
        if clique[rest] and (rest & ~adjacency[bit.bit_length() - 1]) == 0:
            clique[mask] = 1
            best = max(best, mask.bit_count())
    return best


def generate():
    rng = random.Random(6270889)
    cases = []

    def add(name, g, expected=None, group='family'):
        g = nx.convert_node_labels_to_integers(g)
        edges = sorted((min(u, v), max(u, v)) for u, v in g.edges())
        if len(g) <= 12:
            value = exhaustive(len(g), edges)
            bk = max(map(len, nx.find_cliques(g)), default=0)
            assert value == bk, (name, value, bk)
            oracle = 'all vertex subsets; cross-checked Bron-Kerbosch'
        elif expected is None:
            value = max(map(len, nx.find_cliques(g)), default=0)
            oracle = 'NetworkX Bron-Kerbosch maximal cliques'
        else:
            value = expected
            oracle = 'analytic graph family'
        if expected is not None:
            assert value == expected, (name, value, expected)
        cases.append(dict(id=name, n=len(g), edges=edges, expected=value,
                          oracle=oracle, group=group))

    regression = nx.cycle_graph(8)
    regression.add_edge(0, 2)
    add('cycle_chords-01', regression, 3, 'regression')
    add('mixed-core', nx.disjoint_union(regression, nx.complete_bipartite_graph(3, 3)), 3, 'regression')
    for i, graph in enumerate(nx.graph_atlas_g()):
        add(f'atlas-{i:04d}', graph, group='atlas')
    for i in range(400):
        n = rng.randint(8, 12)
        graph = nx.gnp_random_graph(n, rng.choice([.08, .2, .35, .5, .65, .8, .95]), seed=rng.randrange(1 << 30))
        add(f'random-small-{i:04d}', graph, group='random-small')
    for i in range(100):
        n = rng.randint(13, 90)
        graph = nx.gnp_random_graph(n, rng.choice([.05, .12, .25, .4, .55]), seed=rng.randrange(1 << 30))
        add(f'random-medium-{i:03d}', graph, group='random-medium')
    for n in [0, 1, 2, 3, 7, 8, 31, 32, 33, 63, 64, 65, 127, 128, 129, 257]:
        add(f'empty-{n}', nx.empty_graph(n), 1 if n else 0)
        add(f'complete-{n}', nx.complete_graph(n), n)
        if n >= 3:
            add(f'cycle-{n}', nx.cycle_graph(n), 3 if n == 3 else 2)
            add(f'wheel-{n}', nx.wheel_graph(n), 4 if n == 4 else 3)
            add(f'star-{n}', nx.star_graph(n - 1), 2)
    for n in [3, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127]:
        add(f'bipartite-{n}', nx.complete_bipartite_graph(n, n + 1), 2)
    for parts, size in [(3, 11), (4, 9), (5, 13), (8, 9), (17, 4)]:
        add(f'multipartite-{parts}-{size}', nx.complete_multipartite_graph(*([size] * parts)), parts)
    for n in [8, 16, 32, 64, 128, 256]:
        add(f'matching-{n}', nx.from_edgelist((i, i + 1) for i in range(0, n, 2)), 2)
        add(f'book-{n}', nx.compose(nx.star_graph(n - 1), nx.Graph([(1, v) for v in range(2, n)])), 3)
    for n, d in [(32, 3), (64, 5), (128, 7), (256, 4), (512, 3)]:
        add(f'regular-{n}-{d}', nx.random_regular_graph(d, n, seed=n + d))
    for n, p in [(31, .6), (32, .6), (33, .6), (63, .4), (64, .4), (65, .4), (128, .1), (257, .025), (513, .01)]:
        add(f'boundary-random-{n}', nx.gnp_random_graph(n, p, seed=n))
    # A low-core triangle can be better than every clique in a high-core component.
    for n in [3, 8, 17, 33, 65]:
        add(f'low-core-optimum-{n}', nx.disjoint_union(regression, nx.complete_bipartite_graph(n, n)), 3)
    for name, g in [('petersen', nx.petersen_graph()), ('icosahedron', nx.icosahedral_graph()),
                    ('octahedron', nx.octahedral_graph()), ('dodecahedron', nx.dodecahedral_graph()),
                    ('karate', nx.karate_club_graph())]:
        add(name, g)
    # Metamorphic cases preserve omega while changing all index and degree orders.
    originals = rng.sample([x for x in cases if 3 <= x['n'] <= 90], 240)
    for i, original in enumerate(originals):
        labels = list(range(original['n']))
        rng.shuffle(labels)
        graph = nx.empty_graph(original['n'])
        graph.add_edges_from((labels[u], labels[v]) for u, v in original['edges'])
        add(f'permuted-{i:03d}', graph, original['expected'], 'permuted')
        if i < 100:
            graph.add_nodes_from(range(original['n'], original['n'] + rng.randint(1, 12)))
            add(f'isolates-{i:03d}', graph, original['expected'], 'isolates')
    header = json.dumps(dict(seed=6270889, networkx=nx.__version__))[:-1]
    (HERE / 'manifest.json').write_text(header + ', "cases": [\n' +
        ',\n'.join(json.dumps(c, separators=(',', ':')) for c in cases) + '\n]}\n')
    print(json.dumps(dict(graphs=len(cases), max_vertices=max(x['n'] for x in cases),
                          max_edges=max(len(x['edges']) for x in cases))))


def write_input(path, cases):
    with path.open('w') as output:
        for case in cases:
            output.write(f"{case['run_id']} {case['n']} {len(case['edges'])} {case.get('lower_bound', -1)}\n")
            for u, v in case['edges']:
                output.write(f'{u} {v}\n')


def verify(lines, cases):
    results = []
    for i, case in enumerate(cases):
        fields = lines[i].split() if i < len(lines) else []
        error = None
        witness = []
        if len(fields) < 2 or fields[0] != case['run_id']:
            error = 'missing or misaligned output'
        elif case.get('reject', False):
            if fields[1] != 'ERROR':
                error = 'invalid lower bound was accepted'
        elif fields[1] != 'OK' or len(fields) < 5:
            error = ' '.join(fields[1:])
        else:
            size, optimal, upper = map(int, fields[2:5])
            witness = list(map(int, fields[5:]))
            edges = set(map(tuple, case['edges']))
            if size != case['expected']:
                error = f"maximum size {size} != {case['expected']}"
            elif optimal != 1 or upper < size:
                error = 'invalid optimality or upper-bound output'
            elif len(witness) != size or len(set(witness)) != size:
                error = 'wrong witness length or duplicate vertices'
            elif any(v < 0 or v >= case['n'] for v in witness):
                error = 'out-of-range witness vertex'
            elif any((min(u, v), max(u, v)) not in edges for u, v in itertools.combinations(witness, 2)):
                error = 'witness is not a clique in the original graph'
        results.append(dict(id=case['run_id'], graph=case['id'], expected=case['expected'],
                            status='pass' if error is None else 'fail', error=error, witness=witness))
    if len(lines) != len(cases):
        results.append(dict(id='output-length', status='fail', error=f'{len(lines)} != {len(cases)}'))
    return results


def verify_cores(lines, cases):
    results = []
    for i, case in enumerate(cases):
        graph = nx.empty_graph(case['n'])
        graph.add_edges_from(case['edges'])
        expected = list(nx.core_number(graph).values())
        fields = lines[i].split() if i < len(lines) else []
        observed = list(map(int, fields[1:])) if fields else []
        ok = bool(fields) and fields[0] == case['run_id'] and observed == expected
        results.append(dict(id=case['run_id'], graph=case['id'], status='pass' if ok else 'fail',
                            error=None if ok else 'per-vertex core-number mismatch',
                            expected=expected, observed=observed))
    if len(lines) != len(cases):
        results.append(dict(id='output-length', status='fail', error=f'{len(lines)} != {len(cases)}'))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true')
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--gpu', type=int, default=1)
    parser.add_argument('--suite', choices=['full', 'stress', 'bounds', 'sanitizer', 'core'], default='full')
    parser.add_argument('--tool', choices=['memcheck', 'racecheck', 'initcheck', 'synccheck'])
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--batch', type=int, default=64)
    args = parser.parse_args()
    if args.generate:
        generate()
        return
    if not args.binary or not args.output:
        parser.error('--binary and --output are required')
    cases = json.loads((HERE / 'manifest.json').read_text())['cases']
    if args.suite == 'stress':
        cases = [c for c in cases if c['group'] in ['regression', 'random-medium'] or c['id'].startswith(('boundary-', 'low-core-'))]
        cases = cases * 5
    elif args.suite == 'bounds':
        sample = [cases[0]] + [c for c in cases if c['group'] == 'random-small'][:50]
        cases = [dict(c, lower_bound=b) for c in sample for b in sorted({0, c['expected']})]
        cases += [dict(c, lower_bound=c['expected'] + 1, reject=True) for c in sample]
    elif args.suite == 'sanitizer':
        names = {'cycle_chords-01', 'mixed-core', 'low-core-optimum-17', 'cycle-65',
                 'bipartite-33', 'multipartite-5-13', 'random-medium-000', 'random-medium-001',
                 'boundary-random-33', 'boundary-random-65', 'regular-64-5', 'complete-33'}
        cases = [c for c in cases if c['id'] in names]
    cases = [dict(c, run_id=f"{i:05d}-{c['id']}") for i, c in enumerate(cases)]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    all_results, batches = [], []
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), OMP_NUM_THREADS='4')
    batch_size = 1 if args.tool else args.batch
    started = time.monotonic()
    for offset in range(0, len(cases), batch_size):
        batch = cases[offset:offset + batch_size]
        label = f'{offset:05d}'
        input_file, result_file, log_file = [output / (label + suffix) for suffix in ['.txt', '.out', '.log']]
        write_input(input_file, batch)
        command = [str(args.binary.resolve()), str(input_file), str(result_file)]
        if args.tool:
            prefix = ['compute-sanitizer', '--tool', args.tool, '--error-exitcode', '97']
            if args.tool == 'memcheck':
                prefix += ['--leak-check', 'full']
            command = prefix + command
        timeout = False
        with log_file.open('w') as log:
            try:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=args.timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                returncode, timeout = None, True
        lines = result_file.read_text().splitlines() if result_file.exists() else []
        results = (verify_cores if args.suite == 'core' else verify)(lines, batch)
        sanitizer_clean = not args.tool or ('ERROR SUMMARY: 0 errors' in log_file.read_text() if args.tool != 'racecheck' else 'RACECHECK SUMMARY: 0 hazards displayed' in log_file.read_text())
        if returncode != 0 or not sanitizer_clean:
            results.append(dict(id=label + '-process', status='fail', error=f'exit={returncode}; timeout={timeout}; sanitizer_clean={sanitizer_clean}'))
        all_results.extend(results)
        batches.append(dict(id=label, command=command, exit=returncode, timeout=timeout, log_sha256=sha(log_file)))
        print(f'{offset + len(batch)}/{len(cases)} cases; {sum(x["status"] == "fail" for x in all_results)} failures', flush=True)
        # Preserve the first corrupted CUDA context; continue with fresh processes.
    summary = dict(suite=args.suite, tool=args.tool, binary_sha256=sha(args.binary.resolve()),
                   manifest_sha256=sha(HERE / 'manifest.json'), gpu=args.gpu,
                   cases=len(cases), passed=sum(x['status'] == 'pass' for x in all_results),
                   failed=sum(x['status'] == 'fail' for x in all_results),
                   elapsed_seconds=time.monotonic() - started, results=all_results, batches=batches)
    (output / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ['results', 'batches']}), flush=True)
    raise SystemExit(bool(summary['failed']))


if __name__ == '__main__':
    main()
