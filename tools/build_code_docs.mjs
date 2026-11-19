#!/usr/bin/env node
// Doxygen extracts declarations; the shared site renders reviewed function docs.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'build/docs-reference');
const publicOutput = path.join(root, 'docs-src/library/api');
const config = `
PROJECT_NAME = "GraphMine native runtime"
OUTPUT_DIRECTORY = "${output}"
INPUT = library/include library/runtime library/src
RECURSIVE = YES
FILE_PATTERNS = *.h *.hpp *.cuh *.cpp *.cc *.cu
EXTENSION_MAPPING = cu=C++ cuh=C++
EXCLUDE_PATTERNS = */tests/* */upstream/* */build/* */third_party/*
EXCLUDE_SYMLINKS = YES
EXTRACT_ALL = YES
EXTRACT_PRIVATE = YES
EXTRACT_STATIC = YES
EXTRACT_ANON_NSPACES = YES
ENABLE_PREPROCESSING = NO
SOURCE_BROWSER = YES
FULL_PATH_NAMES = NO
STRIP_FROM_PATH = "${root}/"
STRIP_FROM_INC_PATH = "${root}/library/include/" "${root}/"
GENERATE_HTML = NO
GENERATE_LATEX = NO
GENERATE_XML = YES
HAVE_DOT = NO
QUIET = YES
WARN_IF_UNDOCUMENTED = NO
WARN_IF_DOC_ERROR = YES
WARN_AS_ERROR = FAIL_ON_WARNINGS
`;
fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(output, { recursive: true });
const extract = spawnSync(process.env.DOXYGEN_EXECUTABLE || 'doxygen', ['-'], {
  cwd: root, input: config, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024
});
if (extract.error) throw extract.error;
if (extract.status !== 0) {
  process.stderr.write(extract.stderr || extract.stdout);
  process.exit(extract.status || 1);
}
const allowed = new Set(['--draft', '--refresh-source-binding']);
const options = process.argv.slice(2);
if (options.some(arg => !allowed.has(arg))) throw new Error('Unknown reference build option');
// Keep the previous reference if extraction fails, but never mix old and new pages.
fs.rmSync(publicOutput, { recursive: true, force: true });
const render = spawnSync(process.env.PYTHON || 'python3', [
  'tools/build_native_reference.py', '--xml', path.join(output, 'xml'), ...options
], { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
if (render.error) throw render.error;
process.stdout.write(render.stdout);
process.stderr.write(render.stderr);
process.exit(render.status ?? 1);
