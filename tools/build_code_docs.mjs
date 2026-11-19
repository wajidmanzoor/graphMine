#!/usr/bin/env node
// Generate current native documentation. Generated HTML is never a source input.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'docs-src/library/api');
const config = `
PROJECT_NAME = "GraphMine native runtime"
PROJECT_BRIEF = "Current C++/CUDA API and implementation"
OUTPUT_DIRECTORY = "${output}"
HTML_OUTPUT = .
INPUT = tools/code_docs/native-main.dox library/include library/runtime library/src/core library/src/backends library/src/problems
RECURSIVE = YES
FILE_PATTERNS = *.h *.hpp *.cuh *.cpp *.cc *.cu *.dox
EXCLUDE_PATTERNS = */tests/* */upstream/* */build/* */third_party/*
EXCLUDE_SYMLINKS = YES
EXTRACT_ALL = YES
EXTRACT_PRIVATE = NO
EXTRACT_STATIC = YES
SOURCE_BROWSER = YES
INLINE_SOURCES = NO
STRIP_CODE_COMMENTS = NO
FULL_PATH_NAMES = NO
STRIP_FROM_PATH = "${root}/"
STRIP_FROM_INC_PATH = "${root}/library/include/" "${root}/"
GENERATE_TREEVIEW = YES
GENERATE_LATEX = NO
GENERATE_XML = NO
HAVE_DOT = NO
QUIET = YES
WARN_IF_UNDOCUMENTED = NO
WARN_IF_DOC_ERROR = YES
WARN_AS_ERROR = FAIL_ON_WARNINGS
HTML_COLORSTYLE = AUTO_LIGHT
PROJECT_LOGO = tools/code_docs/graphmine-mark.svg
`;
fs.rmSync(output, {recursive:true, force:true});
fs.mkdirSync(output, {recursive:true});
const result = spawnSync(process.env.DOXYGEN_EXECUTABLE || 'doxygen', ['-'], {
  cwd:root, input:config, encoding:'utf8', maxBuffer:16*1024*1024
});
if (result.error) throw result.error;
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout);
  process.exit(result.status || 1);
}
for (const required of ['index.html','files.html','namespaces.html']) {
  if (!fs.existsSync(path.join(output,required))) throw new Error('Missing generated page: '+required);
}
console.log('Built current native API and source reference in docs-src/library/api');
