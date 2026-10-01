#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const doxygen = process.env.DOXYGEN_EXECUTABLE || "doxygen";
const referenceRoot = path.join(repositoryRoot, "docs/reference");
const researchRoot = path.join(referenceRoot, "research");
const artifactCatalogPath = path.join(
  repositoryRoot,
  "catalog/artifact_sources.json",
);
const commonConfig = path.join(
  repositoryRoot,
  "tools/code_docs/Doxyfile.common",
);
const logoPath = path.join(repositoryRoot, "tools/code_docs/graphmine-mark.svg");

// These paths intentionally describe only the implementation used by each
// validated GraphMine adapter. They omit bundled test suites, benchmarks,
// generated experiment variants, and generic third-party packages that are
// not part of the selected algorithm path.
const artifactInputs = {
  "2021_turbobc": ["TurboBC"],
  "2026_gleiden": ["."],
  "2026_multilevel_graph_clustering": ["interface", "src"],
  "2022_g2miner": ["include", "src/common", "src/motif"],
  "2023_graphset": ["include", "gpu", "src"],
  "2024_dumato": ["src/main"],
  "2022_parallel_k_clique_counting": ["include", "kclique", "src/main.cu"],
  "2024_gamma": ["."],
  "2023_accelerating_k_core_gpu": ["inc", "src"],
  "2024_cumbe": ["src"],
  "2023_parallelizing_mce": ["include", "mce", "src/main.cu"],
  "2024_g2_aimd": [
    "app_BK",
    "common",
    "device",
    "system",
    "view",
    "third_party/MPMCQueue/include",
    "third_party/bliss-0.73/bliss",
  ],
  "2026_rdmce": ["RDMCE/include", "RDMCE/src", "RDMCE/main.cc"],
  "2019_maximum_clique_cuda": ["."],
  "2023_maximum_clique_enumeration_gpu": [
    "cliqueMerging.cu",
    "cliqueMerging.cuh",
    "jsonwriter.cuh",
  ],
  "2024_maximum_clique_many_core_gpu": ["include", "mcp", "src/main.cu"],
  "2025_cuqc": ["main.cu"],
  "2026_gmatch": ["bitmap"],
  "2024_everest": ["include", "system/.tmp/GPUWorkerDyn.cu"],
  "2025_mayura": [
    "GPU-co-mining/include",
    "GPU-co-mining/system/.tmp/GPUWorkerDyn.cu",
  ],
  "2025_tot_tensor_cores": ["tot"],
  "2025_wetric": ["tc.cu"],
  "2026_edtc": ["."],
};

const sourceExtensions = new Set([
  ".c",
  ".cc",
  ".cpp",
  ".cxx",
  ".cu",
  ".cuh",
  ".h",
  ".hh",
  ".hpp",
  ".hxx",
]);

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function assertSafeOutput(output) {
  const resolved = path.resolve(output);
  if (
    resolved === referenceRoot ||
    !resolved.startsWith(`${referenceRoot}${path.sep}`)
  ) {
    throw new Error(`Refusing to replace unsafe documentation path: ${resolved}`);
  }
  return resolved;
}

function runDoxygen(config, label) {
  const result = spawnSync(doxygen, [config], {
    cwd: repositoryRoot,
    env: {
      ...process.env,
      GRAPHMINE_SOURCE_ROOT: repositoryRoot,
    },
    encoding: "utf8",
    stdio: ["ignore", "inherit", "inherit"],
  });
  if (result.status !== 0) {
    throw new Error(`Doxygen failed while generating ${label}`);
  }
}

function requireGeneratedFiles(output, files, label) {
  for (const file of files) {
    const generated = path.join(output, file);
    if (!fs.existsSync(generated)) {
      throw new Error(`${label} did not produce ${generated}`);
    }
  }
}

function validateLocalReferences(root, forbiddenPaths = []) {
  const htmlFiles = [];
  const searchableTextFiles = [];
  const searchableExtensions = new Set([".css", ".html", ".js", ".svg"]);
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(candidate);
      else {
        if (entry.name.endsWith(".html")) htmlFiles.push(candidate);
        if (searchableExtensions.has(path.extname(entry.name))) {
          searchableTextFiles.push(candidate);
        }
      }
    }
  };
  visit(root);

  const broken = [];
  const leakedPaths = [];
  let checked = 0;
  for (const file of searchableTextFiles) {
    const contents = fs.readFileSync(file, "utf8");
    for (const forbiddenPath of forbiddenPaths) {
      if (contents.includes(forbiddenPath)) {
        leakedPaths.push(`${path.relative(root, file)} contains ${forbiddenPath}`);
      }
    }
  }
  for (const file of htmlFiles) {
    const contents = fs.readFileSync(file, "utf8");
    for (const match of contents.matchAll(/(?:href|src)="([^"]+)"/g)) {
      let reference = match[1];
      if (
        !reference ||
        reference.startsWith("#") ||
        /^(?:https?:|mailto:|data:|javascript:)/.test(reference)
      ) {
        continue;
      }
      reference = reference.split("#")[0].split("?")[0];
      if (!reference) continue;

      let decoded;
      try {
        decoded = decodeURIComponent(reference);
      } catch {
        broken.push(`${path.relative(root, file)} -> ${reference} (invalid URL encoding)`);
        continue;
      }
      let target = path.resolve(path.dirname(file), decoded);
      if (decoded.endsWith("/")) target = path.join(target, "index.html");
      checked += 1;
      if (!fs.existsSync(target)) {
        broken.push(
          `${path.relative(root, file)} -> ${reference} (${path.relative(root, target)})`,
        );
      }
    }
  }

  if (broken.length > 0) {
    throw new Error(
      `Generated documentation has ${broken.length} broken local references:\n${broken
        .slice(0, 20)
        .join("\n")}`,
    );
  }
  if (leakedPaths.length > 0) {
    throw new Error(
      `Generated documentation exposes machine-local paths:\n${leakedPaths
        .slice(0, 20)
        .join("\n")}`,
    );
  }
  console.log(
    `Validated ${checked.toLocaleString("en-US")} local references across ${htmlFiles.length.toLocaleString("en-US")} HTML pages`,
  );
}

function normalizeGeneratedText(root) {
  const textExtensions = new Set([".css", ".html", ".js", ".svg"]);
  let normalizedFiles = 0;
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(candidate);
      } else if (textExtensions.has(path.extname(entry.name))) {
        const contents = fs.readFileSync(candidate, "utf8");
        // Doxygen 1.9.x can emit unusable absolute links for Markdown
        // headings found inside C++ comments. Drop only those search-index
        // records; the owning class/file documentation remains available.
        const portableContents =
          path.extname(entry.name) === ".js" &&
          candidate.includes(`${path.sep}search${path.sep}`)
            ? contents
                .split("\n")
                .filter((line) => !line.includes(repositoryRoot))
                .join("\n")
            : contents;
        const normalized = portableContents
          .replaceAll("\r\n", "\n")
          .replace(/^ +\t/gm, "\t")
          .replace(/[ \t]+(?=\n|$)/g, "")
          .replace(/\n+$/, "\n");
        if (normalized !== contents) {
          fs.writeFileSync(candidate, normalized);
          normalizedFiles += 1;
        }
      }
    }
  };
  visit(root);
  console.log(`Normalized ${normalizedFiles.toLocaleString("en-US")} generated text files`);
}

function quoteConfig(value) {
  return `"${String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function slug(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function listProblemRecords() {
  const problemsRoot = path.join(repositoryRoot, "problems");
  return fs
    .readdirSync(problemsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const directory = path.join(problemsRoot, entry.name);
      const problem = readJson(path.join(directory, "problem.json"));
      return [problem.problem_id, { ...problem, directory }];
    });
}

function artifactSlug(artifact) {
  return `${slug(artifact.problem_id)}--${slug(artifact.paper_id)}`;
}

function collectSourceFiles(inputs) {
  const files = new Set();
  const visit = (candidate) => {
    const stat = fs.statSync(candidate);
    if (stat.isDirectory()) {
      for (const entry of fs.readdirSync(candidate, { withFileTypes: true })) {
        if (!entry.isSymbolicLink()) {
          visit(path.join(candidate, entry.name));
        }
      }
      return;
    }
    if (sourceExtensions.has(path.extname(candidate).toLowerCase())) {
      files.add(candidate);
    }
  };
  for (const input of inputs) visit(input);
  return files.size;
}

function mainPage(artifact, problem, relativeCodeRoot, sourceCount) {
  const title = escapeHtml(artifact.title);
  const problemName = escapeHtml(problem.name || artifact.problem_id);
  const problemStatement = escapeHtml(problem.problem_statement);
  const publicationUrl = escapeHtml(artifact.publication_url);
  const codeUrl = escapeHtml(artifact.code_url);
  const sourcePath = escapeHtml(relativeCodeRoot.split(path.sep).join("/"));
  const githubPath = `https://github.com/wajidmanzoor/graphMine/tree/main/${sourcePath}`;
  return `# ${title}

<div class="graphmine-intro"><strong>Validated research artifact</strong> · ${problemName} · ${artifact.year}<br/>${problemStatement}</div>

## Navigate this reference

- <a href="functions.html">Class members and methods</a>
- <a href="globals.html">Free functions, globals, and CUDA kernels</a>
- <a href="annotated.html">Classes and data structures</a>
- <a href="files.html">Files and annotated source</a>
- <a href="../">All research artifacts</a>
- <a href="../../library/">GraphMine library and adapter reference</a>
- <a href="../../../">High-level documentation</a>

## Documented source scope

This reference covers **${sourceCount} C, C++, CUDA, or header files** from
<code>${sourcePath}</code>. It follows the implementation path selected by the
validated GraphMine adapter. Bundled test programs, generated experimental
variants, and unrelated third-party packages are intentionally omitted.

CUDA qualifiers are normalized only for Doxygen's parser. Open a file's
source view to see the exact preserved <code>__global__</code>,
<code>__device__</code>, and <code>__host__</code> declarations.

## Paper and source provenance

- **Paper:** <a href="${publicationUrl}">${title}</a>
- **Venue:** ${escapeHtml(artifact.venue)}
- **Upstream repository:** <a href="${codeUrl}">${codeUrl}</a>
- **Pinned commit:** <code>${escapeHtml(artifact.code_commit)}</code>
- **Vendored source:** <a href="${githubPath}">${sourcePath}</a>
- **License:** See <a href="https://github.com/wajidmanzoor/graphMine/blob/main/THIRD_PARTY.md">THIRD_PARTY.md</a> and the retained artifact license where available.

The code and its existing comments are preserved from the cited artifact.
Doxygen supplies signatures, declarations, definitions, references, include
relationships, and line-numbered source when the upstream code has no prose
comment for a function.
`;
}

function artifactConfig({
  artifact,
  codeRoot,
  inputs,
  output,
  mainPagePath,
  warningLogPath,
}) {
  return `@INCLUDE = ${quoteConfig(commonConfig)}

PROJECT_NAME           = "GraphMine research code"
PROJECT_NUMBER         = ${quoteConfig(artifact.code_commit.slice(0, 12))}
PROJECT_BRIEF          = ${quoteConfig(artifact.title)}
PROJECT_LOGO           = ${quoteConfig(logoPath)}
OUTPUT_DIRECTORY       = ${quoteConfig(output)}
CREATE_SUBDIRS         = YES
ALLOW_UNICODE_NAMES    = YES
FULL_SIDEBAR           = YES
HTML_OUTPUT            = .
INPUT                  = ${[mainPagePath, ...inputs].map(quoteConfig).join(" \\\n                         ")}
USE_MDFILE_AS_MAINPAGE = ${quoteConfig(mainPagePath)}
FULL_PATH_NAMES        = NO
STRIP_FROM_PATH        = ${quoteConfig(path.dirname(mainPagePath))} ${quoteConfig(codeRoot)} ${quoteConfig(repositoryRoot)}
STRIP_FROM_INC_PATH    = ${quoteConfig(codeRoot)} ${quoteConfig(repositoryRoot)}
EXCLUDE_PATTERNS      += */test/* */tests/* */unittests/* */auto/* */tianhe/*
WARN_LOGFILE           = ${quoteConfig(warningLogPath)}
`;
}

function renderResearchPortal(artifacts, problemMap) {
  const byProblem = new Map();
  for (const artifact of artifacts) {
    const current = byProblem.get(artifact.problem_id) || [];
    current.push(artifact);
    byProblem.set(artifact.problem_id, current);
  }

  const sections = [...byProblem.entries()]
    .map(([problemId, problemArtifacts]) => {
      const problem = problemMap.get(problemId);
      const cards = problemArtifacts
        .map(
          (artifact) => `
            <article class="artifact-card" data-artifact-card data-search="${escapeHtml(
              `${problem.name} ${artifact.paper_id} ${artifact.title} ${artifact.venue}`.toLowerCase(),
            )}">
              <div class="artifact-meta">
                <span>${escapeHtml(String(artifact.year))}</span>
                <span>${escapeHtml(artifact.venue)}</span>
              </div>
              <h3>${escapeHtml(artifact.paper_id)}</h3>
              <p>${escapeHtml(artifact.title)}</p>
              <dl>
                <div><dt>Source files</dt><dd>${artifact.sourceCount}</dd></div>
                <div><dt>Commit</dt><dd><code>${escapeHtml(artifact.code_commit.slice(0, 12))}</code></dd></div>
              </dl>
              <a class="card-action" href="${artifact.outputSlug}/">Open function reference <span aria-hidden="true">→</span></a>
            </article>`,
        )
        .join("");
      return `
        <section class="artifact-section" data-artifact-section>
          <div class="artifact-section-heading">
            <p class="section-label">${problemArtifacts.length} ${
              problemArtifacts.length === 1 ? "artifact" : "artifacts"
            }</p>
            <h2>${escapeHtml(problem.name)}</h2>
            <p>${escapeHtml(problem.problem_statement)}</p>
          </div>
          <div class="artifact-grid">${cards}
          </div>
        </section>`;
    })
    .join("");

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content="Function-by-function reference for the validated C, C++, and CUDA research artifacts used by GraphMine." />
    <meta name="theme-color" content="#ffffff" />
    <title>GraphMine · Research code reference</title>
    <link rel="stylesheet" href="../styles.css" />
  </head>
  <body class="research-portal">
    <header class="reference-header">
      <div class="shell header-inner">
        <a class="brand" href="../">
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <path d="M12 14 25 8l12 8-3 17-13 8-12-10Z" />
            <path d="m12 14 12 12m13-10L24 26m-3 15 3-15" />
            <circle cx="12" cy="14" r="4" /><circle cx="37" cy="16" r="4" />
            <circle cx="21" cy="41" r="4" /><circle cx="24" cy="26" r="4" />
          </svg>
          <span>Graph<span>Mine</span></span>
        </a>
        <nav aria-label="Reference navigation">
          <a href="../">Code reference</a>
          <a href="../../">High-level guide</a>
          <a href="https://github.com/wajidmanzoor/graphMine">GitHub</a>
        </nav>
      </div>
    </header>
    <main class="shell">
      <section class="artifact-hero">
        <p class="eyebrow"><i></i> Original implementation internals</p>
        <h1>Research code, <span>artifact by artifact.</span></h1>
        <p class="lede">Search ${artifacts.length} isolated source references behind GraphMine's validated backends. Each reference covers host functions, CUDA kernels, types, files, callers, and exact annotated source without collisions between papers.</p>
        <label class="artifact-search">
          <span>Search artifact, problem, paper, or venue</span>
          <input type="search" placeholder="Try maximal clique, GraphSet, or SC 2023" data-artifact-search />
        </label>
        <p class="artifact-result-count" data-result-count>${artifacts.length} artifacts shown</p>
      </section>
      <div class="artifact-sections">${sections}
      </div>
      <p class="artifact-empty" data-empty hidden>No research artifact matches that search.</p>
    </main>
    <footer><div class="shell"><span>GraphMine research code reference</span><a href="../library/">Open the GraphMine library reference</a></div></footer>
    <script>
      const input = document.querySelector("[data-artifact-search]");
      const cards = [...document.querySelectorAll("[data-artifact-card]")];
      const sections = [...document.querySelectorAll("[data-artifact-section]")];
      const count = document.querySelector("[data-result-count]");
      const empty = document.querySelector("[data-empty]");
      input.addEventListener("input", () => {
        const query = input.value.trim().toLowerCase();
        let visible = 0;
        for (const card of cards) {
          const matches = !query || card.dataset.search.includes(query);
          card.hidden = !matches;
          if (matches) visible += 1;
        }
        for (const section of sections) {
          section.hidden = !section.querySelector("[data-artifact-card]:not([hidden])");
        }
        count.textContent = visible + (visible === 1 ? " artifact shown" : " artifacts shown");
        empty.hidden = visible !== 0;
      });
    </script>
  </body>
</html>
`;
}

const version = spawnSync(doxygen, ["--version"], {
  cwd: repositoryRoot,
  encoding: "utf8",
});
if (version.status !== 0) {
  console.error(
    "Doxygen is required. Install it or set DOXYGEN_EXECUTABLE to its path.",
  );
  process.exit(version.status || 1);
}

console.log(`Generating code reference with Doxygen ${version.stdout.trim()}`);

const libraryOutput = assertSafeOutput(path.join(referenceRoot, "library"));
fs.rmSync(libraryOutput, { recursive: true, force: true });
runDoxygen("tools/code_docs/Doxyfile.library", "the GraphMine library reference");
requireGeneratedFiles(
  libraryOutput,
  ["index.html", "files.html", "functions_func.html", "globals_func.html"],
  "The GraphMine library reference",
);
console.log("Generated GraphMine library reference");

const artifacts = readJson(artifactCatalogPath).artifacts;
const problemMap = new Map(listProblemRecords());
const knownInputs = new Set(Object.keys(artifactInputs));
for (const artifact of artifacts) knownInputs.delete(artifact.paper_id);
if (knownInputs.size > 0) {
  throw new Error(`Input rules have no matching artifact: ${[...knownInputs].join(", ")}`);
}

assertSafeOutput(researchRoot);
fs.rmSync(researchRoot, { recursive: true, force: true });
fs.mkdirSync(researchRoot, { recursive: true });

const temporaryRoot = path.join(repositoryRoot, "tools/code_docs/.generated");
fs.rmSync(temporaryRoot, { recursive: true, force: true });
fs.mkdirSync(temporaryRoot, { recursive: true });
try {
  for (const [index, artifact] of artifacts.entries()) {
    const problem = problemMap.get(artifact.problem_id);
    if (!problem) throw new Error(`Unknown problem: ${artifact.problem_id}`);
    const selectedInputs = artifactInputs[artifact.paper_id];
    if (!selectedInputs) throw new Error(`Missing input rule for ${artifact.paper_id}`);

    const codeRoot = path.join(
      problem.directory,
      "papers",
      artifact.paper_id,
      "code",
    );
    if (!fs.existsSync(codeRoot)) {
      throw new Error(`Missing vendored source directory: ${codeRoot}`);
    }
    const inputs = selectedInputs.map((input) => path.resolve(codeRoot, input));
    for (const input of inputs) {
      if (!fs.existsSync(input)) throw new Error(`Missing documented source input: ${input}`);
      if (!input.startsWith(`${codeRoot}${path.sep}`) && input !== codeRoot) {
        throw new Error(`Artifact input escapes its code root: ${input}`);
      }
    }

    const outputSlug = artifactSlug(artifact);
    const output = assertSafeOutput(path.join(researchRoot, outputSlug));
    const sourceCount = collectSourceFiles(inputs);
    const relativeCodeRoot = path.relative(repositoryRoot, codeRoot);
    const mainPagePath = path.join(temporaryRoot, `${outputSlug}.md`);
    const configPath = path.join(temporaryRoot, `${outputSlug}.conf`);
    const warningLogPath = path.join(temporaryRoot, `${outputSlug}.warnings`);
    fs.writeFileSync(
      mainPagePath,
      mainPage(artifact, problem, relativeCodeRoot, sourceCount),
    );
    fs.writeFileSync(
      configPath,
      artifactConfig({
        artifact,
        codeRoot,
        inputs,
        output,
        mainPagePath,
        warningLogPath,
      }),
    );

    console.log(`[${index + 1}/${artifacts.length}] ${artifact.problem_id} / ${artifact.paper_id}`);
    runDoxygen(configPath, artifact.paper_id);
    requireGeneratedFiles(
      output,
      ["index.html", "files.html", "globals.html", "functions.html"],
      artifact.paper_id,
    );
    if (
      !fs.existsSync(path.join(output, "globals_func.html")) &&
      !fs.existsSync(path.join(output, "functions_func.html"))
    ) {
      throw new Error(`${artifact.paper_id} produced no function index`);
    }
    if (fs.existsSync(warningLogPath)) {
      const warningCount = fs
        .readFileSync(warningLogPath, "utf8")
        .split("\n")
        .filter(Boolean).length;
      if (warningCount > 0) {
        console.log(`  Preserved upstream documentation warnings: ${warningCount}`);
      }
    }
    Object.assign(artifact, { outputSlug, sourceCount });
  }
} finally {
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
}

fs.writeFileSync(
  path.join(researchRoot, "index.html"),
  renderResearchPortal(artifacts, problemMap),
);
console.log(`Generated ${artifacts.length} isolated research artifact references`);
normalizeGeneratedText(referenceRoot);
validateLocalReferences(referenceRoot, [
  repositoryRoot,
  temporaryRoot,
  "tools/code_docs/.generated",
]);
