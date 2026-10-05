#!/usr/bin/env python3
"""Build the CDS repair from a pinned local upstream commit and checked patch."""
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
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gpu', type=int, default=1)
    parser.add_argument('--arch', type=int, default=89)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--capacity-scale', type=int, default=1)
    parser.add_argument('--poison-allocations', action='store_true')
    args = parser.parse_args()
    if not 0 < args.capacity_scale < (1 << 64):
        parser.error('capacity scale must be a positive uint64')
    provenance = json.loads((HERE / 'provenance.json').read_text())
    patch = HERE / 'repair.patch'
    if sha(patch) != provenance['patch_sha256']:
        raise RuntimeError('Patch hash mismatch')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    source.mkdir()
    with (output / 'upstream.tar').open('wb') as stream:
        subprocess.run(['git', '-C', str(args.source_checkout.resolve()), 'archive',
                        provenance['commit'], 'cudaCode'], stdout=stream, check=True)
    with tarfile.open(output / 'upstream.tar') as archive:
        archive.extractall(source, filter='data')
    subprocess.run(['git', 'init', '--quiet', str(source)], check=True)
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True)
    for name, expected in provenance['patched_source_sha256'].items():
        if sha(source / name) != expected:
            raise RuntimeError(f'Patched source hash mismatch: {name}')
    if args.poison_allocations:
        # Instrument only project-owned allocation calls, without changing
        # Thrust/CUDA internals. Every allocation is dirty before initialization.
        for name in ['main.cu', 'src/gpuMemoryAllocation.cu', 'inc/exactFlow.cuh']:
            path = source / 'cudaCode' / name
            raw = path.read_bytes()
            path.write_bytes(raw.replace(b'cudaMalloc(', b'cds_validation_malloc('))
        path = source / 'cudaCode/utils/cuda_utils.cuh'
        with path.open('a') as stream:
            stream.write('''
inline cudaError_t cds_validation_malloc(void **pointer, size_t bytes) {
  cudaError_t error = cudaMalloc(pointer, bytes);
  if (error == cudaSuccess && bytes) error = cudaMemset(*pointer, 0xa5, bytes);
  return error;
}
''')
    build = output / 'build'
    flags = f'-lineinfo -DCDS_CAPACITY_SCALE={args.capacity_scale}ULL'
    commands = [
        ['cmake', '-S', str(source / 'cudaCode'), '-B', str(build),
         '-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_CUDA_ARCHITECTURES={args.arch}',
         f'-DCMAKE_CUDA_FLAGS={flags}'],
        ['cmake', '--build', str(build), '--parallel', str(args.jobs)],
    ]
    for label, command in zip(['configure', 'build'], commands):
        with (output / f'{label}.log').open('w') as stream:
            subprocess.run(command, env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu)),
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = dict(commit=provenance['commit'], patch_sha256=sha(patch),
        archive_sha256=sha(output / 'upstream.tar'), commands=commands,
        gpu=args.gpu, architecture=args.arch, capacity_scale=args.capacity_scale,
        poison_allocations=args.poison_allocations,
        compiled_source_sha256={str(p.relative_to(source)): sha(p)
            for p in sorted((source / 'cudaCode').rglob('*')) if p.is_file()},
        binary=str(build / 'main'), binary_sha256=sha(build / 'main'))
    (output / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['compiled_source_sha256', 'commands']}), flush=True)


if __name__ == '__main__':
    main()
