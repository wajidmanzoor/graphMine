#!/usr/bin/env python3
"""Rebuild CUDA-MS from its pinned upstream commit and the recorded repair."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
COMMIT = 'a0b6b00a1f67b6fe65380b2efcb242cf40889d83'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-checkout', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--library', type=Path, default=HERE.parents[2] / 'library')
    p.add_argument('--snapshot', action='store_true', help='Development only: copy current source')
    p.add_argument('--asan', action='store_true')
    p.add_argument('--poison', action='store_true')
    p.add_argument('--cold', action='store_true', help='Validation: complete search with no relaxation incumbent')
    p.add_argument('--arch', type=int, default=89)
    p.add_argument('--skip-native', action='store_true')
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = out / 'source'
    source.mkdir()
    if args.snapshot:
        for f in args.source_checkout.iterdir():
            if f.suffix in {'.c', '.h', '.cu', '.cuh'}:
                shutil.copy2(f, source / f.name)
    else:
        provenance = json.loads((HERE / 'provenance.json').read_text())
        assert sha(HERE / 'repair.patch') == provenance['patch_sha256']
        for name, expected in provenance.get('library_source_sha256', {}).items():
            assert sha(args.library / name) == expected, name
        with (out / 'upstream.tar').open('wb') as stream:
            subprocess.run(['git', '-C', str(args.source_checkout), 'archive', COMMIT], stdout=stream, check=True)
        with tarfile.open(out / 'upstream.tar') as archive:
            archive.extractall(source, filter='data')
        subprocess.run(['git', 'init', '--quiet', str(source)], check=True)
        subprocess.run(['git', 'apply', '--check', str(HERE / 'repair.patch')], cwd=source, check=True)
        subprocess.run(['git', 'apply', str(HERE / 'repair.patch')], cwd=source, check=True)
        for name, expected in provenance['source_sha256'].items():
            assert sha(source / name) == expected, name
    commands = []
    if args.cold:
        path = source / 'motzkin.c'
        path.write_text(path.read_text().replace('has_edges && !allowed', '0 /* cold validation */'))

    def run(command):
        commands.append(command)
        with (out / 'build.log').open('a') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)

    flags = ['-O3', '-g', '-fopenmp', '-I' + str(source), '-I/usr/local/cuda/include']
    instrument = []
    if args.asan:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        instrument += ['-Xcompiler=-fsanitize=address', '-Xcompiler=-fsanitize=undefined', '-Xcompiler=-fno-omit-frame-pointer']
    if args.poison:
        poison = out / 'poison.cuh'
        poison.write_text('''#include <cuda_runtime.h>
template<class T> cudaError_t ms_poison_malloc(T** p, size_t n) {
  auto e = cudaMalloc(p, n);
  return e == cudaSuccess && n ? cudaMemset(*p, 0xa5, n) : e;
}
template<class T> cudaError_t ms_poison_pitch(T** p, size_t* pitch, size_t w, size_t h) {
  auto e = cudaMallocPitch(p, pitch, w, h);
  return e == cudaSuccess && w && h ? cudaMemset2D(*p, *pitch, 0xa5, *pitch, h) : e;
}
''')
        for file in list(source.glob('*.cu')) + list(source.glob('*.cuh')):
            file.write_text(file.read_text().replace('cudaMalloc(', 'ms_poison_malloc(')
                            .replace('cudaMallocPitch(', 'ms_poison_pitch('))
        instrument += ['-include', str(poison)]
    objects = []
    for name in ['arrays', 'bitops', 'random', 'motzkin', 'motzkin_cpu']:
        obj = out / (name + '.o')
        run(['gcc', '-std=gnu99', '-D_GNU_SOURCE', *flags, '-c', str(source / (name + '.c')), '-o', str(obj)])
        objects.append(str(obj))
    cuda = out / 'motzkin_cuda.o'
    run(['nvcc', '-std=c++17', '-O3', '-lineinfo', f'-arch=sm_{args.arch}',
         '-Xcompiler=-fopenmp', *instrument, '-I' + str(source), '-c',
         str(source / 'motzkin_cuda.cu'), '-o', str(cuda)])
    objects.append(str(cuda))
    ldflags = ['-L/usr/local/cuda/lib64', '-lcudart', '-lcurand', '-lm']
    for name in ['parsers', 'find_cliques']:
        run(['gcc', '-std=gnu99', '-D_GNU_SOURCE', *flags, '-c', str(source / (name + '.c')),
             '-o', str(out / (name + '.o'))])
    run(['g++', *flags, *objects, str(out / 'parsers.o'), str(out / 'find_cliques.o'),
         *ldflags, '-o', str(out / 'find_cliques')])
    run(['g++', '-std=c++17', *flags, str(HERE / 'raw_probe.cpp'), *objects,
         *ldflags, '-o', str(out / 'raw_probe')])
    if not args.skip_native:
        lib = args.library.resolve()
        native_sources = ['src/backends/cuda_ms.cpp', 'src/backends/gpu_maximum_clique_stub.cpp',
                          'src/backends/maximum_clique_on_gpu_stub.cpp', 'src/core/graph.cpp',
                          'src/problems/maximum_clique.cpp']
        run(['g++', '-std=c++17', *flags, '-I' + str(lib / 'include'), '-I' + str(lib / 'src'),
             *[str(lib / n) for n in native_sources], str(HERE / 'native_probe.cpp'),
             *objects, *ldflags, '-o', str(out / 'native_probe')])
    result = dict(commit=COMMIT, snapshot=args.snapshot, arch=args.arch, asan=args.asan,
                  poison=args.poison, cold=args.cold, commands=commands,
                  source_sha256={f.name: sha(f) for f in sorted(source.iterdir()) if f.is_file()},
                  binaries={n: sha(out / n) for n in ['find_cliques', 'raw_probe', 'native_probe'] if (out / n).exists()})
    (out / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(output=str(out), binaries=result['binaries'])), flush=True)


if __name__ == '__main__':
    main()
