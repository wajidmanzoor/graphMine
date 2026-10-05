#!/usr/bin/env python3
"""Clean build from the pinned local artifact, checked repair, and native adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-checkout', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=HERE.parents[2] / 'library')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arch', type=int, default=89)
    parser.add_argument('--poison-allocations', action='store_true')
    parser.add_argument('--host-asan', action='store_true')
    parser.add_argument('--targets', nargs='+', choices=['probe', 'core_probe', 'parallel_mcp_on_gpus'],
                        default=['probe', 'core_probe', 'parallel_mcp_on_gpus'])
    args = parser.parse_args()
    provenance = json.loads((HERE / 'provenance.json').read_text())
    patch = HERE / 'repair.patch'
    if sha(patch) != provenance['patch_sha256']:
        raise RuntimeError('repair.patch hash mismatch')
    library = args.library.resolve()
    for name, expected in provenance['library_source_sha256'].items():
        if sha(library / name) != expected:
            raise RuntimeError(f'Library source hash mismatch: {name}')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    source.mkdir()
    with (output / 'upstream.tar').open('wb') as stream:
        subprocess.run(['git', '-C', str(args.source_checkout.resolve()), 'archive', provenance['commit']], stdout=stream, check=True)
    with tarfile.open(output / 'upstream.tar') as archive:
        archive.extractall(source, filter='data')
    subprocess.run(['git', 'init', '--quiet', str(source)], check=True)
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True)
    for name, expected in provenance['patched_source_sha256'].items():
        if sha(source / name) != expected:
            raise RuntimeError(f'Patched source hash mismatch: {name}')
    backend = output / 'maximum_clique_on_gpu_backend.cu'
    backend.write_bytes((library / 'src/backends/maximum_clique_on_gpu_backend.cu').read_bytes())
    instrumentation = []
    if args.poison_allocations:
        poison = output / 'poison.cuh'
        poison.write_text('''#pragma once
#include <cuda_runtime.h>
template<class T> inline cudaError_t mcp_validation_malloc(T** p, size_t n) {
  auto error = cudaMalloc(p, n);
  if (error == cudaSuccess && n) error = cudaMemset(*p, 0xa5, n);
  return error;
}
template<class T> inline cudaError_t mcp_validation_managed(T** p, size_t n,
                                                          unsigned flags = cudaMemAttachGlobal) {
  auto error = cudaMallocManaged(p, n, flags);
  if (error == cudaSuccess && n) error = cudaMemset(*p, 0xa5, n);
  return error;
}
''')
        for path in [*source.rglob('*.cu'), *source.rglob('*.cuh'), backend]:
            raw = path.read_bytes()
            path.write_bytes(raw.replace(b'cudaMalloc(', b'mcp_validation_malloc(')
                             .replace(b'cudaMallocManaged(', b'mcp_validation_managed('))
        instrumentation = ['-include', str(poison)]
    common = ['nvcc', '-O3', '-lineinfo', '-std=c++20', f'-arch=sm_{args.arch}',
              '-Xcompiler', '-fopenmp', '-I' + str(source / 'include'),
              '-I' + str(source / 'mcp'), *instrumentation]
    if args.host_asan:
        common += ['-Xcompiler=-fsanitize=address', '-Xcompiler=-fno-omit-frame-pointer', '-g']
    commands = {
        'probe': common + ['-DGRAPHMINE_LIBRARY', '-I' + str(library / 'include'),
                           '-I' + str(library / 'src'), str(backend),
                           str(library / 'src/backends/cuda_ms_stub.cpp'),
                           str(library / 'src/backends/gpu_maximum_clique_stub.cpp'),
                           str(library / 'src/core/graph.cpp'),
                           str(library / 'src/problems/maximum_clique.cpp'), str(HERE / 'probe.cpp')],
        'core_probe': common + [str(HERE / 'core_probe.cu')],
        'parallel_mcp_on_gpus': common + [str(source / 'src/main.cu')],
    }
    binaries = {}
    commands = {name: command for name, command in commands.items() if name in args.targets}
    for name, command in commands.items():
        command += ['-o', str(output / name)]
        with (output / (name + '.build.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        binaries[name] = sha(output / name)
        print(f'Built {name}', flush=True)
    result = dict(commit=provenance['commit'], patch_sha256=sha(patch),
                  archive_sha256=sha(output / 'upstream.tar'), architecture=args.arch,
                  poison_allocations=args.poison_allocations, commands=commands,
                  host_asan=args.host_asan,
                  compiled_source_sha256={str(p.relative_to(source)): sha(p) for p in sorted(source.rglob('*'))
                                          if p.is_file() and '.git' not in p.parts},
                  backend_sha256=sha(backend), binaries=binaries)
    (output / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(binaries=binaries, output=str(output))), flush=True)


if __name__ == '__main__':
    main()
