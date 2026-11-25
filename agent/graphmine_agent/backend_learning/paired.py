"""Paired, randomized offline collection under controlled CPU-load regimes."""
from __future__ import annotations

import asyncio
import json
import os
import random
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from .features import graph_features, safe_parameters
from .hardware import hardware_snapshot
from .storage import atomic_json


@asynccontextmanager
async def cpu_load(regime, *, workers=2, warmup=65.):
    if regime not in {'idle', 'busy_cpu'} or not 1 <= workers <= (os.cpu_count() or 1) or not 0 <= warmup <= 600:
        raise ValueError('Invalid controlled CPU load')
    processes = []
    try:
        if regime == 'busy_cpu':
            # Explicit offline benchmark workload; each child is owned and reaped.
            for _ in range(workers):
                processes.append(subprocess.Popen([sys.executable, '-c', 'while True: sum(i*i for i in range(10000))'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True))
        # Load average is measured over one minute. The warmup is configurable
        # and used for idle cooldown too; the actual snapshot is always retained.
        await asyncio.sleep(warmup)
        yield
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait)


def preflight(request_path):
    from graphmine import evidence
    from graphmine.dispatch import native_request, implementation_hash
    from graphmine.registry import algorithm
    from .feasibility import filter_candidates
    from ..evidence_cache import install
    request = json.loads(Path(request_path).read_text())
    data = json.loads(Path(request['graph_path']).read_text())
    if implementation_hash() != request['implementation_sha256']:
        raise ValueError('Implementation changed before pair admission')
    install(evidence, Path(request['data_dir']) / 'reports/paired-evidence.json')
    card = next(c for c in evidence.capabilities(Path(request['repository_root']))['problems'] if c['id'] == request['problem'])
    allowed = [b['id'] for b in card['backends'] if b.get('verified') and
               (b['device'] == 'cpu' or request['gpu_uuid'] in b.get('verified_devices', []))]
    parameters = safe_parameters(request['parameters'], algorithm(request['problem']).parameters)
    features = graph_features(data, input_kind=card.get('input_kind', 'graph'))
    caps = native_request(dict(command='backend_capabilities', problem=request['problem'], graph=data,
        parameters=request['parameters'], budget=request['budget'], device='auto', backend='auto',
        allowed_backends=allowed, gpu_device=0))
    hw = hardware_snapshot(leased_gpu_uuid=request['gpu_uuid'])
    hw['backend_memory_safety'] = request['memory_safety']
    candidates = filter_candidates(request['problem'], caps['candidates'], features, parameters, hw,
        output_estimate=request['budget'].get('max_output_items') or max(100000, features['n'], features['m']),
        implementation=request['implementation_sha256'], data_dir=request['data_dir'])
    value = dict(eligible=[c['id'] for c in candidates if c['feasible']], candidates=candidates,
        context=dict(problem=request['problem'], parameters=parameters, graph_features=features, hardware=hw,
                     execution_isolated=True))
    atomic_json(Path(request_path).with_name('preflight.json'), value)


async def admit_pair(job, directory, *, python, library):
    from .benchmark import _native_environment
    path = directory / 'preflights' / job['comparison_id']
    path.mkdir(parents=True, exist_ok=True)
    request = path / 'request.json'
    atomic_json(request, job)
    process = await asyncio.create_subprocess_exec(str(python), '-m', __name__, str(request),
        env=_native_environment(Path(job['repository_root']), library, gpu_uuid=job['gpu_uuid']),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True)
    try:
        await asyncio.wait_for(process.wait(), job['budget']['timeout_seconds'])
        if process.returncode:
            raise ValueError('Paired native preflight failed')
        return json.loads((path / 'preflight.json').read_text())
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def collect_pairs(*, cards, selection, config, settings, arguments, directory, logger,
                        data_dir, library, gpu, implementation, identifier, is_evaluation, mode,
                        rows, seen, totals, frozen_code):
    from . import benchmark as bench
    from .benchmark_graphs import prepare_graph, digest
    from .benchmark_profiles import bind_parameters, parameter_grid, attempt_keys
    from .leases import GPULock
    from graphmine.dispatch import implementation_hash

    regimes = arguments.load_regimes.split(',') if arguments.load_regimes else (['idle', 'busy_cpu'] if arguments.full else ['idle'])
    if set(regimes) - {'idle', 'busy_cpu'} or len(set(regimes)) != len(regimes):
        raise ValueError('Load regimes must be unique idle,busy_cpu values')
    if config['timeout_seconds'] is None:
        raise ValueError('Paired benchmarks require a finite configured timeout')
    python = arguments.python or sys.executable
    for regime in regimes:
        async with cpu_load(regime, workers=arguments.busy_cpu_workers, warmup=arguments.load_warmup_seconds):
            for card in sorted(cards, key=lambda c: c['id']):
                problem = card['id']
                limit = None if arguments.full else config['bootstrap_examples_per_problem']
                for spec in selection[problem]:
                    if limit is not None and totals[problem] >= limit:
                        break
                    graph_path, graph_meta = prepare_graph(directory, spec, settings)
                    graph = json.loads(graph_path.read_text())
                    for options in parameter_grid(config['problems'][problem]):
                        parameters = bind_parameters(problem, graph, options)
                        budget = {k: config[k] for k in ('timeout_seconds', 'max_candidates', 'max_output_items')}
                        for repetition in range(config['repeats']):
                            base, _, _ = attempt_keys(implementation, problem, 'cpp', graph_meta['snapshot_fingerprint'], parameters, budget, repetition)
                            comparison = digest([base, regime, repetition])
                            job = dict(benchmark_id=identifier, benchmark_mode=mode, problem=problem,
                                parameters=parameters, budget=budget, graph_path=str(graph_path), graph_id=spec['id'],
                                graph_fingerprint=graph_meta['snapshot_fingerprint'], comparison_id=comparison,
                                repetition=repetition, is_evaluation=is_evaluation, data_dir=str(data_dir),
                                repository_root=str(bench.ROOT), implementation_sha256=implementation, gpu_uuid=gpu['uuid'],
                                memory_safety=settings.backend_memory_safety, load_regime=regime)
                            lock = None
                            try:
                                while lock is None:
                                    lock = GPULock.acquire(data_dir)
                                    if lock is None:
                                        await asyncio.sleep(1)
                                admission = await admit_pair(job, directory, python=python, library=library)
                                backends = admission['eligible']
                                if not backends or limit is not None and totals[problem] + len(backends) > limit:
                                    continue  # A bootstrap cap must never truncate a pair.
                                random.Random(digest([comparison, config['generated_grid']['seed']])).shuffle(backends)
                                job.update(pair_context=admission['context'], paired_eligible_backends=backends)
                                for order, backend in enumerate(backends):
                                    key = digest([comparison, backend])
                                    if key in seen:
                                        continue
                                    if bench.code_hash() != frozen_code or implementation_hash() != implementation:
                                        raise ValueError('Benchmark code or implementation changed')
                                    attempt = dict(job, run_id=str(uuid4()), backend=backend,
                                        benchmark_pair_id=digest([base, regime, backend]), benchmark_attempt_key=key,
                                        backend_order=order, gpu_uuid=None if backend == 'cpp' else gpu['uuid'])
                                    row = bench.initial_row(attempt, graph, card, attempt['gpu_uuid'])
                                    row = await bench.run_attempt(attempt, row, directory, python=python, library=library, lock=lock)
                                    await bench.publish(logger, row, directory)
                                    rows.append(row)
                                    seen.add(key)
                                    totals[problem] += 1
                                    print(f"{problem} {regime} {backend} {row['outcome']} {row['runtime_seconds']:.4f}s", flush=True)
                                    if row.get('benchmark_cancelled'):
                                        raise asyncio.CancelledError()
                            finally:
                                if lock:
                                    lock.close()


if __name__ == '__main__':
    preflight(sys.argv[1])
