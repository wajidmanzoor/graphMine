#!/usr/bin/env python3
"""Differential CDS validation: exact closure oracle, brute force and witnesses."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import time

import networkx as nx

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_graph(path, graph):
    path.write_text(f"{len(graph)} {graph.number_of_edges()}\n" + ''.join(
        str(v) + ''.join(f" {u}" for u in sorted(graph[v])) + '\n'
        for v in range(len(graph))))


def read_graph(path):
    lines = path.read_text().splitlines()
    n, m = map(int, lines[0].split())
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    for line in lines[1:]:
        v, *neighbors = map(int, line.split())
        graph.add_edges_from((v, u) for u in neighbors)
    assert graph.number_of_edges() == m
    return graph


def enumerate_cliques(graph, k):
    result = []
    for clique in nx.enumerate_all_cliques(graph):
        if len(clique) > k:
            break
        if len(clique) == k:
            result.append(tuple(clique))
    return result


def closure_oracle(graph, cliques):
    """Maximum closure with integer capacities; distinct from CDS's reduction."""
    if not cliques:
        return Fraction(0)
    best = Fraction(0)
    # A clique cannot cross graph components. Solving each component also
    # makes thousands of disconnected stress gadgets inexpensive to check.
    by_vertex = {}
    for i, component in enumerate(nx.connected_components(graph)):
        for v in component:
            by_vertex[v] = i
    grouped = {}
    for clique in cliques:
        grouped.setdefault(by_vertex[clique[0]], []).append(clique)
    for component_cliques in grouped.values():
        vertices = set(itertools.chain.from_iterable(component_cliques))
        density = max(best, Fraction(len(component_cliques), len(vertices)))
        while True:
            p, q = density.numerator, density.denominator
            network = nx.DiGraph()
            source, sink = 'source', 'sink'
            inf = q * len(component_cliques) + p * len(vertices) + 1
            for v in vertices:
                network.add_edge(v, sink, capacity=p)
            for i, clique in enumerate(component_cliques):
                node = ('clique', i)
                network.add_edge(source, node, capacity=q)
                for v in clique:
                    network.add_edge(node, v, capacity=inf)
            cut, (left, _) = nx.minimum_cut(network, source, sink,
                                            flow_func=nx.algorithms.flow.preflow_push)
            gain = q * len(component_cliques) - cut
            if gain == 0:
                best = max(best, density)
                break
            selected = vertices & left
            count = sum(set(c).issubset(selected) for c in component_cliques)
            assert q * count - p * len(selected) == gain > 0
            density = Fraction(count, len(selected))
    return best


def brute_oracle(n, cliques):
    """Exhaust every vertex subset, using a subset-sum transform for counts."""
    counts = [0] * (1 << n)
    for clique in cliques:
        counts[sum(1 << v for v in clique)] += 1
    for bit in range(n):
        for mask in range(1 << n):
            if mask & (1 << bit):
                counts[mask] += counts[mask ^ (1 << bit)]
    return max((Fraction(counts[mask], mask.bit_count()) for mask in range(1, 1 << n)),
               default=Fraction(0))


def cases(full):
    for n in [0, 1, 2, 3, 5, 8, 16, 65]:
        yield f'empty_{n}', nx.empty_graph(n), 'named', [2, 3, 4]
    for n in [2, 3, 4, 5, 7, 9, 12, 16]:
        yield f'complete_{n}', nx.complete_graph(n), 'named', [2, 3, 4, 5, 6]
    for n in [3, 5, 8, 17, 33, 65, 129]:
        for label, graph in [('path', nx.path_graph(n)), ('cycle', nx.cycle_graph(n)),
                             ('star', nx.star_graph(n - 1))]:
            yield f'{label}_{n}', graph, 'named', [2, 3, 4]
    for n in [2, 3, 5, 17]:
        yield f'bipartite_{n}', nx.complete_bipartite_graph(n, n + 1), 'named', [2, 3, 4]
    for n in [2, 5, 17, 65]:
        yield f'windmill_{n}', nx.windmill_graph(n, 3), 'named', [2, 3, 4]
    for n in [3, 5, 9]:
        yield f'barbell_{n}', nx.barbell_graph(n, n + 1), 'named', [2, 3, 4]
    workspace = HERE.parents[3]
    for name in ['small', 'medium']:
        fixture = HERE / f'fixtures/original_{name}.adj'
        if not fixture.exists():
            fixture = workspace / f'validation/gpu_correctness/datasets/undirected/{name}.cds.adj'
        if fixture.exists():
            yield f'original_{name}', read_graph(fixture), 'original', [2, 3, 4]
    rng = random.Random(20261004)
    for i in range(300 if full else 40):
        n = rng.randint(2, 45 if full else 14)
        probability = rng.choice([0.03, 0.1, 0.25, 0.45, 0.7, 0.9])
        graph = nx.gnp_random_graph(n, probability, seed=rng.randrange(1 << 32))
        # Keep clique listing/closure workloads bounded in the dense tail.
        ks = [2, 3, 4] if n < 25 or probability < 0.5 else [2, 3]
        yield f'random_{i:03}', graph, 'random', ks
        if full and i < 100:
            order = list(range(n))
            rng.shuffle(order)
            relabeled = nx.relabel_nodes(graph, dict(enumerate(order)))
            yield f'relabel_{i:03}', relabeled, 'relabel', ks
        if full and i < 50:
            yield f'isolates_{i:03}', nx.disjoint_union(graph, nx.empty_graph(13)), 'isolates', ks
    if full:
        for i, graph in enumerate(nx.graph_atlas_g()):
            yield f'atlas_{i:04}', graph, 'atlas', [2, 3, 4]
        # More than 32 initial peeling vertices per block, plus cascading
        # removals, bitmap word boundaries and many connected components.
        triangles = nx.disjoint_union_all([nx.complete_graph(3) for _ in range(2800)])
        yield 'large_disjoint_triangles', nx.disjoint_union(triangles, nx.complete_graph(4)), 'stress', [2, 3, 4]
        yield 'large_windmill', nx.windmill_graph(2048, 3), 'stress', [2, 3, 4]
        for n in [128, 257, 1025]:
            yield f'large_path_{n}', nx.path_graph(n), 'stress', [2]
            graph = nx.barbell_graph(8, n)
            yield f'large_barbell_{n}', graph, 'stress', [2, 3, 4]
        for i in range(15):
            graph = nx.gnp_random_graph(100 + i * 17, 0.015 + i * 0.001,
                                        seed=9000 + i)
            yield f'large_sparse_{i:02}', graph, 'stress', [2, 3, 4]
        for n in [7, 9, 11, 13]:
            yield f'higher_k_{n}', nx.gnp_random_graph(n, 0.8, seed=n), 'higher_k', [5, 6]
    for name, tail in [('triangle', nx.complete_graph(3)), ('cycle4', nx.cycle_graph(4))]:
        graph = nx.disjoint_union(nx.complete_graph(4), tail)
        graph.add_edge(3, 4)
        yield f'clique4_{name}_bridge', graph, 'regression', [2]


def generate(full):
    fixtures = HERE / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    manifest = []
    for name, graph, group, ks in cases(full):
        path = fixtures / f'{name}.adj'
        write_graph(path, graph)
        degree = max(dict(graph.degree()).values(), default=0)
        for k in ks:
            cliques = enumerate_cliques(graph, k)
            optimum = closure_oracle(graph, cliques)
            brute = len(graph) <= 10
            if brute:
                assert brute_oracle(len(graph), cliques) == optimum, (name, k)
            prefix_tasks = len(graph) if k <= 3 else len(enumerate_cliques(graph, k - 2))
            per_warp = max(1, math.ceil(prefix_tasks / 6912))
            psize = max(64, per_warp * max(1, degree) * max(1, k - 1))
            cpsize = max(128, per_warp * max(1, degree) ** (1 if k <= 3 else 2))
            if not cliques or k == 2:
                psize, cpsize = 64, 128
            manifest.append(dict(name=f'{name}_k{k}', graph=name, group=group, k=k,
                n=len(graph), m=graph.number_of_edges(), cliques=len(cliques),
                numerator=optimum.numerator, denominator=optimum.denominator,
                brute_crosscheck=brute, fixture=f'fixtures/{path.name}', sha256=sha(path),
                parameters=[psize, cpsize, max(1024, len(graph)), 1024, -1]))
        if len(manifest) % 100 < len(ks):
            print(f'generated {len(manifest)} cases', flush=True)
    (HERE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'manifest: {len(manifest)} cases', flush=True)


def run(args):
    manifest = json.loads((HERE / 'manifest.json').read_text())
    selected = [c for c in manifest if not args.group or c['group'] in args.group]
    if args.case:
        selected = [c for c in selected if any(re.search(p, c['name']) for p in args.case)]
    if args.sanitizer:
        # Empty/no-clique cases are covered numerically. Some return before
        # CUDA initialization, which Compute Sanitizer treats as exit 255.
        selected = [c for c in selected if c['cliques'] > 0]
    if args.limit:
        selected = selected[:args.limit]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    logs = output / 'logs'
    logs.mkdir(exist_ok=True)
    records = []
    started = time.time()
    for case in selected:
        path = HERE / case['fixture']
        assert sha(path) == case['sha256']
        graph = read_graph(path)
        cliques = enumerate_cliques(graph, case['k'])
        params = list(case['parameters'])
        if args.buffer_factor:
            params[:4] = [v * args.buffer_factor for v in params[:4]]
        command = [str(args.binary.resolve()), str(path), str(case['k']), *map(str, params)]
        if args.sanitizer:
            command = ['compute-sanitizer', '--tool', args.sanitizer, '--error-exitcode', '99',
                       '--target-processes', 'all', *command]
        record = dict(name=case['name'], command=command, expected=[case['numerator'], case['denominator']])
        begin = time.time()
        try:
            proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu)),
                                  timeout=args.timeout, text=True)
            stdout = proc.stdout
            record['returncode'] = proc.returncode
            (logs / f"{case['name']}.log").write_text(stdout)
            assert proc.returncode == 0, f'exit {proc.returncode}'
            match = re.search(r'^CDS_RESULT (.+)$', stdout, re.M)
            if args.baseline:
                scalar = re.search(r'(?:Final )?Max Density\s+([0-9.eE+-]+)', stdout)
                assert scalar, 'missing density'
                record['observed'] = float(scalar[1])
                expected = case['numerator'] / case['denominator']
                # Upstream prints only six significant digits. Distinguish
                # that formatting loss from an actual algorithm failure.
                tolerance = 0.50001 * 10 ** (math.floor(math.log10(expected)) - 5) if expected else 1e-12
                assert abs(float(scalar[1]) - expected) <= tolerance, 'wrong density'
            else:
                assert match, 'missing exact result'
                result = json.loads(match[1])
                record['observed'] = result
                vertices = result['vertices']
                assert len(vertices) == len(set(vertices)) == result['vertex_count'], 'duplicate/wrong vertex count'
                assert all(isinstance(v, int) and 0 <= v < case['n'] for v in vertices), 'invalid vertex IDs'
                assert vertices or not case['n'], 'empty nonempty-graph witness'
                members = set(vertices)
                count = sum(set(c).issubset(members) for c in cliques)
                actual = Fraction(count, len(vertices)) if vertices else Fraction(0)
                assert count == result['clique_count'], 'incorrect witness clique count'
                assert actual == Fraction(case['numerator'], case['denominator']), f'wrong density: {actual}'
                assert result['density'] == float(actual) and result['optimal'] is True, 'incorrect result metadata'
                total = re.search(r'Total Cliques=(\d+)', stdout)
                assert total and int(total[1]) == case['cliques'], 'wrong total clique enumeration'
                if args.sanitizer:
                    assert re.search(r'(?:ERROR SUMMARY: 0 errors|RACECHECK SUMMARY: 0 hazards)', stdout), 'missing clean sanitizer summary'
            record['pass'] = True
        except subprocess.TimeoutExpired as exc:
            record.update({'pass': False, 'error': 'timeout'})
            data = exc.stdout or b''
            (logs / f"{case['name']}.log").write_bytes(data if isinstance(data, bytes) else data.encode())
        except (AssertionError, ValueError) as exc:
            record.update({'pass': False, 'error': str(exc)})
        record['seconds'] = round(time.time() - begin, 6)
        records.append(record)
        if not record['pass']:
            print(json.dumps(record), flush=True)
        if len(records) % 100 == 0:
            print(f"{len(records)}/{len(selected)}: {sum(r['pass'] for r in records)} passed", flush=True)
        if args.stop_on_failure and not record['pass']:
            break
    summary = dict(binary=str(args.binary.resolve()), binary_sha256=sha(args.binary),
        manifest_sha256=sha(HERE / 'manifest.json'), gpu=args.gpu, sanitizer=args.sanitizer,
        baseline=args.baseline, cases=len(records), passed=sum(r['pass'] for r in records),
        failed=sum(not r['pass'] for r in records), elapsed_seconds=round(time.time()-started, 3),
        brute_crosschecked=sum(c['brute_crosscheck'] for c in selected[:len(records)]),
        buffer_factor=args.buffer_factor or 1, results=records)
    (output / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k:v for k,v in summary.items() if k != 'results'}), flush=True)
    return int(summary['failed'] > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', choices=['smoke', 'full'])
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--gpu', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--group', nargs='+')
    parser.add_argument('--case', nargs='+')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--stop-on-failure', action='store_true')
    parser.add_argument('--buffer-factor', type=int)
    parser.add_argument('--sanitizer', choices=['memcheck', 'initcheck', 'racecheck', 'synccheck'])
    args = parser.parse_args()
    if args.generate:
        generate(args.generate == 'full')
        return 0
    if not args.binary or not args.output:
        parser.error('--binary and --output are required to run validation')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
