#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const readJson = (relativePath) =>
  JSON.parse(fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8"));

const runtimeManifest = readJson("graphmine_manifest.json");
const backendRegistry = readJson("catalog/backend_registry.json");
const artifactSources = readJson("catalog/artifact_sources.json");
const validationResults = readJson(
  "validation/gpu_correctness/results/results.json",
);
const graphSchema = readJson("problems/graph_input.schema.json");

const problemDirectories = fs
  .readdirSync(path.join(repositoryRoot, "problems"), { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && /^\d{2}_/.test(entry.name))
  .map((entry) => entry.name)
  .sort();

const problemSources = problemDirectories.map((directory) => {
  const source = `problems/${directory}/problem.json`;
  return { source, spec: readJson(source) };
});

const intentSignals = {
  maximal_clique_enumeration: [
    "enumerate every maximal clique",
    "find all inclusion-maximal complete vertex sets",
    "list maximal complete subgraphs",
  ],
  maximum_clique: [
    "find the largest clique",
    "maximum complete vertex set",
    "maximum clique size or vertices",
  ],
  k_clique_counting_enumeration: [
    "count k-cliques",
    "enumerate cliques of exactly size k",
    "triangle, 4-clique, or 5-clique count as a fixed-k query",
  ],
  quasi_clique_mining: [
    "find near-cliques",
    "dense groups controlled by a minimum degree ratio",
    "gamma quasi-cliques",
  ],
  densest_subgraph: [
    "find the subgraph with maximum density",
    "unconstrained densest subgraph",
  ],
  densest_k_subgraph: [
    "find the densest subgraph with exactly k vertices",
    "fixed-cardinality dense subgraph",
  ],
  k_core_decomposition: [
    "compute core numbers",
    "graph degeneracy",
    "vertices in the k-core",
  ],
  k_truss_decomposition: [
    "compute edge trussness",
    "find the k-truss",
    "triangle-supported edge decomposition",
  ],
  maximal_biclique_enumeration: [
    "enumerate maximal bicliques",
    "complete bipartite subgraphs",
    "maximal left-right vertex pairs",
  ],
  triangle_counting_listing: [
    "count or list triangles",
    "per-vertex or per-edge triangle counts",
    "triangle changes after edge updates",
  ],
  graph_motif_counting: [
    "count supplied small motif patterns",
    "induced or non-induced motif occurrences",
    "three- or four-vertex structural patterns",
  ],
  graphlet_counting: [
    "count graphlets",
    "graphlet orbit counts",
    "small induced graphlet census",
  ],
  subgraph_isomorphism: [
    "match a query graph inside a data graph",
    "count embeddings of a pattern graph",
    "subgraph pattern matching with labels",
  ],
  frequent_subgraph_mining: [
    "discover subgraphs frequent across a graph collection",
    "minimum support graph patterns",
  ],
  temporal_motif_mining: [
    "count time-ordered edge-event patterns",
    "temporal motifs within a duration window",
    "feed-forward temporal triangles",
  ],
  community_detection: [
    "partition vertices into disjoint communities",
    "Louvain or Leiden modularity clustering",
  ],
  overlapping_community_detection: [
    "find communities whose vertex sets overlap",
    "k-clique percolation communities",
  ],
  centrality_influential_node_mining: [
    "rank influential vertices",
    "compute centrality scores",
    "betweenness centrality",
  ],
  link_prediction: [
    "score missing edges",
    "recommend likely future links",
    "rank candidate vertex pairs",
  ],
  graph_anomaly_detection: [
    "detect anomalous vertices, edges, subgraphs, or whole graphs",
    "rank graph entities by anomaly score",
  ],
};

const cppContracts = {
  "maximal-cliques": {
    header: "graphmine/problems/maximal_cliques.hpp",
    class: "graphmine::MaximalCliques",
    options_type: "graphmine::MaximalCliqueOptions",
    backend_enum: "graphmine::MaximalCliqueBackend",
  },
  "maximum-clique": {
    header: "graphmine/problems/maximum_clique.hpp",
    class: "graphmine::MaximumClique",
    options_type: "graphmine::MaximumCliqueOptions",
    backend_enum: "graphmine::MaximumCliqueBackend",
  },
  "k-cliques": {
    header: "graphmine/problems/k_cliques.hpp",
    class: "graphmine::KCliques",
    options_type: "graphmine::KCliqueOptions",
    backend_enum: "graphmine::KCliqueBackend",
  },
  "quasi-cliques": {
    header: "graphmine/problems/quasi_cliques.hpp",
    class: "graphmine::QuasiCliques",
    options_type: "graphmine::QuasiCliqueOptions",
    backend_enum: "graphmine::QuasiCliqueBackend",
  },
  "k-core": {
    header: "graphmine/problems/k_core.hpp",
    class: "graphmine::KCore",
    options_type: "graphmine::KCoreOptions",
    backend_enum: "graphmine::KCoreBackend",
  },
  "maximal-bicliques": {
    header: "graphmine/problems/maximal_bicliques.hpp",
    class: "graphmine::MaximalBicliques",
    options_type: "graphmine::MaximalBicliqueOptions",
    backend_enum: "graphmine::MaximalBicliqueBackend",
  },
  "triangle-counting": {
    header: "graphmine/problems/triangle_counting.hpp",
    class: "graphmine::TriangleCounting",
    options_type: "graphmine::TriangleOptions",
    backend_enum: "graphmine::TriangleBackend",
  },
  "dynamic-triangle-counting": {
    header: "graphmine/problems/dynamic_triangle_counting.hpp",
    class: "graphmine::DynamicTriangleCounting",
    options_type: "graphmine::DynamicTriangleOptions",
    backend_enum: "graphmine::DynamicTriangleBackend",
  },
  "graph-motifs": {
    header: "graphmine/problems/graph_motifs.hpp",
    class: "graphmine::GraphMotifs",
    options_type: "graphmine::GraphMotifOptions",
    backend_enum: "graphmine::GraphMotifBackend",
  },
  "subgraph-isomorphism": {
    header: "graphmine/problems/subgraph_isomorphism.hpp",
    class: "graphmine::SubgraphIsomorphism",
    options_type: "graphmine::SubgraphIsomorphismOptions",
    backend_enum: "graphmine::SubgraphIsomorphismBackend",
  },
  "temporal-motif-mining": {
    header: "graphmine/problems/temporal_motif_mining.hpp",
    class: "graphmine::TemporalMotifMining",
    options_type: "graphmine::TemporalMotifOptions",
    backend_enum: "graphmine::TemporalMotifBackend",
  },
  "community-detection": {
    header: "graphmine/problems/community_detection.hpp",
    class: "graphmine::CommunityDetection",
    options_type: "graphmine::CommunityDetectionOptions",
    backend_enum: "graphmine::CommunityDetectionBackend",
  },
  "betweenness-centrality": {
    header: "graphmine/problems/betweenness_centrality.hpp",
    class: "graphmine::BetweennessCentrality",
    options_type: "graphmine::BetweennessCentralityOptions",
    backend_enum: "graphmine::BetweennessCentralityBackend",
  },
};

const validationImplementation = {
  "mce-gpu": "mce-gpu",
  "g2-aimd": "G2-AIMD",
  rdmce: "RDMCE",
  "cuda-ms": "CUDA-MS",
  "gpu-maximum-clique": "GPUMaximumClique",
  "maximum-clique-on-gpu": "Maximum-Clique-on-GPU",
  kcgpu: "KCGPU",
  graphset: "GraphSet",
  gamma: "GAMMA",
  cuqc: "cuQC",
  "kcore-gpu": "KCoreGPU",
  cumbe: "cuMBE",
  tot: "ToT",
  wetric: "WeTriC",
  edtc: "EDTC",
  graphminer: "GraphMiner/G2Miner",
  dumato: "DuMato",
  gmatch: "gMatch",
  everest: "Everest",
  mayura: "Mayura",
  gleiden: "gLeiden",
  "parallel-louvain": "pLouvain/pLeiden/pLeiden+",
  "parallel-leiden": "pLouvain/pLeiden/pLeiden+",
  "parallel-leiden-plus": "pLouvain/pLeiden/pLeiden+",
  "turbo-bc": "TurboBC",
};

const registryOperations = new Map(
  backendRegistry.operations.map((operation) => [operation.id, operation]),
);
const problemsById = new Map(
  problemSources.map((entry) => [entry.spec.problem_id, entry]),
);
const artifactsByProblemAndPaper = new Map(
  artifactSources.artifacts.map((artifact) => [
    `${artifact.problem_id}:${artifact.paper_id}`,
    artifact,
  ]),
);

const workloadsByProblem = new Map();
for (const workload of validationResults.workloads) {
  const entries = workloadsByProblem.get(workload.problem) || [];
  entries.push(workload);
  workloadsByProblem.set(workload.problem, entries);
}

function validationForBackend(problemId, backendId) {
  const implementation = validationImplementation[backendId];
  assert(implementation, `No validation implementation mapping for ${backendId}`);
  const workload = validationResults.workloads.find(
    (entry) =>
      entry.problem === problemId &&
      entry.implementation === implementation &&
      entry.status === "pass",
  );
  assert(
    workload,
    `No passing validation workload for ${problemId}/${backendId}`,
  );
  return workload;
}

const operations = runtimeManifest.operations.map((operation) => {
  const registryOperation = registryOperations.get(operation.id);
  assert(registryOperation, `Missing backend registry entry for ${operation.id}`);
  const problem = problemsById.get(operation.research_problem_id)?.spec;
  assert(problem, `Missing problem specification for ${operation.research_problem_id}`);
  const problemPosition = problemSources.findIndex(
    (entry) => entry.spec.problem_id === operation.research_problem_id,
  );
  assert.notEqual(problemPosition, -1);
  const cpp = cppContracts[operation.id];
  assert(cpp, `Missing C++ contract for ${operation.id}`);

  const backendDetails = operation.backends.map((backendId) => {
    const registryBackend = registryOperation.backends.find(
      (backend) => backend.id === backendId,
    );
    assert(
      registryBackend,
      `Missing backend registry entry for ${operation.id}/${backendId}`,
    );
    const validation = validationForBackend(
      operation.research_problem_id,
      backendId,
    );
    const sources = (validation.paper_artifacts || []).map((paperId) => {
      const source = artifactsByProblemAndPaper.get(
        `${operation.research_problem_id}:${paperId}`,
      );
      assert(source, `Missing artifact source for ${operation.id}/${paperId}`);
      return source;
    });
    return {
      ...registryBackend,
      validation: {
        workload_id: validation.workload_id,
        implementation: validation.implementation,
        status: validation.status,
        note: validation.note,
        checks: validation.checks,
      },
      source_artifacts: sources,
    };
  });

  return {
    ...operation,
    problem_contract_ref: `#/problems/${problemPosition}`,
    problem_inputs: problem.problem_inputs.map((input) => input.name),
    cpp: {
      ...cpp,
      cmake_component: operation.cmake_component,
      lifecycle: [
        "construct options",
        "construct algorithm object",
        "optionally call supports(graph)",
        "call run(...) and inspect ExecutionResult",
      ],
    },
    cli: {
      command_example: operation.command,
      required_auxiliary_inputs: operation.required_auxiliary_inputs || [],
      parameters: operation.parameters || [],
      optional_output_flags: operation.optional_output_flags || {},
    },
    backend_details: backendDetails,
  };
});

const operationsByProblem = new Map();
for (const operation of operations) {
  const entries = operationsByProblem.get(operation.research_problem_id) || [];
  entries.push(operation);
  operationsByProblem.set(operation.research_problem_id, entries);
}

const problems = problemSources.map(({ source, spec }) => {
  const problemOperations = operationsByProblem.get(spec.problem_id) || [];
  const validationWorkloads = workloadsByProblem.get(spec.problem_id) || [];
  const validatedBackendCount = problemOperations.reduce(
    (count, operation) => count + operation.backends.length,
    0,
  );
  const available = problemOperations.length > 0;

  return {
    source,
    intent_signals: intentSignals[spec.problem_id] || [],
    library_support: {
      available,
      status: available ? "validated" : "no_validated_backend",
      operation_ids: problemOperations.map((operation) => operation.id),
      validated_backend_count: validatedBackendCount,
      reason: available
        ? "At least one implementation passed the GPU correctness validation and is exposed by GraphMine."
        : "No implementation for this problem passed the validation gate, so GraphMine does not expose an operation for it.",
    },
    validation_workloads: validationWorkloads,
    spec,
  };
});

const supportedProblems = problems.filter(
  (problem) => problem.library_support.available,
);
const validatedBackendCount = operations.reduce(
  (count, operation) => count + operation.backends.length,
  0,
);
const passingWorkloadCount = validationResults.workloads.filter(
  (workload) => workload.status === "pass",
).length;

const problemIndex = Object.fromEntries(
  problems.map((problem, index) => [
    problem.spec.problem_id,
    {
      name: problem.spec.name,
      category: problem.spec.category,
      library_status: problem.library_support.status,
      operation_ids: problem.library_support.operation_ids,
      problem_ref: `#/problems/${index}`,
    },
  ]),
);

const operationIndex = Object.fromEntries(
  operations.map((operation, index) => [
    operation.id,
    {
      research_problem_id: operation.research_problem_id,
      backends: operation.backends,
      operation_ref: `#/operations/${index}`,
    },
  ]),
);

const catalog = {
  schema_version: "2.0.0",
  catalog_id: "graphmine_problem_first_catalog_v2",
  library_version: runtimeManifest.library_version,
  purpose:
    "Problem-first context for mapping a user request to a formal graph problem, a validated GraphMine operation, a backend, parameters, and optional outputs.",
  source_of_truth: {
    problem_contracts:
      "Each problems/*/problem.json object is embedded exactly and remains authoritative for semantics, inputs, outputs, validation rules, and edge cases.",
    runtime_contract: "graphmine_manifest.json",
    validation_results: "validation/gpu_correctness/results/results.json",
    backend_registry: "catalog/backend_registry.json",
    artifact_sources: "catalog/artifact_sources.json",
    regeneration_command: "node tools/build_catalog.mjs",
  },
  scope: {
    catalog_problem_count: problems.length,
    library_supported_problem_count: supportedProblems.length,
    library_unsupported_problem_count: problems.length - supportedProblems.length,
    runnable_operation_count: operations.length,
    validated_backend_count: validatedBackendCount,
    passing_validation_workload_count: passingWorkloadCount,
    operation_count_note:
      "Triangle counting and dynamic triangle counting share one research problem but are separate runnable operations.",
  },
  routing: {
    workflow: [
      {
        step: 1,
        action: "identify_problem",
        instruction:
          "Compare the user request with problem_statement, intent_signals, graph_input, problem_inputs, solution_semantics, and edge_cases. Select exactly one problem_id or report ambiguity.",
        output: "selected_problem_id",
      },
      {
        step: 2,
        action: "check_library_support",
        instruction:
          "Inspect library_support. If status is no_validated_backend, report that faithfully and do not substitute a nearby problem.",
        output: "library_support_status",
      },
      {
        step: 3,
        action: "select_operation",
        instruction:
          "Choose among library_support.operation_ids. Respect each operation's validated_profile and backend_constraints; these can be narrower than the general problem contract.",
        output: "selected_operation_id",
      },
      {
        step: 4,
        action: "resolve_inputs_and_parameters",
        instruction:
          "Use spec.graph_input and spec.problem_inputs for semantic requirements, then use operation.cli for their concrete command-line encoding. Ask for any required graph or auxiliary input that is missing.",
        output: "resolved_parameters_and_missing_inputs",
      },
      {
        step: 5,
        action: "select_backend",
        instruction:
          "Honor an explicit supported backend choice. Otherwise use auto or choose from backend_details only when capabilities, constraints, or available hardware justify it. Never silently replace an explicitly selected backend.",
        output: "selected_backend_id",
      },
      {
        step: 6,
        action: "select_outputs",
        instruction:
          "Always return required_outputs. Enable optional fields only through operation.cli.optional_output_flags when the user requests them or they are necessary for the task.",
        output: "requested_optional_output_flags",
      },
    ],
    hard_rules: [
      "Do not route an unsupported problem to a superficially similar supported operation.",
      "Do not claim support outside an operation's validated_profile or backend_constraints.",
      "Do not invent parameter values for required inputs; request them from the user.",
      "Use canonical external vertex and edge IDs at the public boundary.",
      "Prefer the generic run/supports/result lifecycle; use problem-specific fields only where the contract requires them.",
    ],
    disambiguation: [
      {
        candidates: ["maximal_clique_enumeration", "maximum_clique"],
        rule: "Maximal means enumerate inclusion-maximal cliques; maximum means find a largest clique.",
      },
      {
        candidates: ["densest_subgraph", "densest_k_subgraph"],
        rule: "Use densest_k_subgraph only when the vertex cardinality k is fixed.",
      },
      {
        candidates: [
          "triangle_counting_listing",
          "graph_motif_counting",
          "graphlet_counting",
          "subgraph_isomorphism",
        ],
        rule: "Triangles are a fixed 3-cycle query; motifs count supplied small patterns; graphlets request a graphlet/orbit census; subgraph isomorphism matches a specific query graph and its embeddings.",
      },
      {
        candidates: ["community_detection", "overlapping_community_detection"],
        rule: "Use community_detection for one assignment per vertex and overlapping community detection when vertices may belong to several communities.",
      },
      {
        candidates: ["graph_motif_counting", "temporal_motif_mining"],
        rule: "Use temporal motifs when edge-event order or a time window is part of the query.",
      },
    ],
    selection_output_contract: {
      required_fields: [
        "selected_problem_id",
        "library_support_status",
        "selected_operation_id",
        "selected_backend_id",
        "resolved_parameters",
        "requested_optional_output_flags",
        "missing_inputs",
      ],
      nullable_when_unsupported: [
        "selected_operation_id",
        "selected_backend_id",
      ],
    },
  },
  build_once_run_many: runtimeManifest.build_once_run_many,
  common_cli: runtimeManifest.common_cli,
  canonical_graph_input: {
    ...runtimeManifest.canonical_graph_input,
    schema_file: "problems/graph_input.schema.json",
    repository_schema_source: "problems/graph_input.schema.json",
    json_schema: graphSchema,
  },
  auxiliary_input_formats: runtimeManifest.auxiliary_input_formats,
  validation: {
    source: "validation/gpu_correctness/results/results.json",
    selection_rule: runtimeManifest.scope.selection_rule,
    classification_policy: validationResults.classification_policy,
    summary: validationResults.summary,
  },
  problem_index: problemIndex,
  operation_index: operationIndex,
  problems,
  operations,
  artifacts: artifactSources.artifacts,
};

assert.equal(problems.length, 20, "Expected all 20 problem specifications");
assert.equal(supportedProblems.length, 12, "Expected 12 supported problems");
assert.equal(operations.length, 13, "Expected 13 runnable operations");
assert.equal(validatedBackendCount, 26, "Expected 26 backend choices");
assert.equal(passingWorkloadCount, 24, "Expected 24 passing workloads");
assert.equal(
  Object.keys(problemIndex).length,
  problems.length,
  "Problem IDs must be unique",
);
assert.equal(
  Object.keys(operationIndex).length,
  operations.length,
  "Operation IDs must be unique",
);

for (const { source, spec } of problemSources) {
  const embedded = problems.find(
    (problem) => problem.spec.problem_id === spec.problem_id,
  );
  assert(embedded, `Missing embedded problem ${spec.problem_id}`);
  assert.deepEqual(embedded.spec, readJson(source));
}

const serialized = `${JSON.stringify(catalog, null, 2)}\n`;
for (const output of [
  "graphmine_catalog.json",
  "library/manifests/graphmine_catalog.json",
]) {
  fs.writeFileSync(path.join(repositoryRoot, output), serialized);
}

console.log(
  `Wrote ${problems.length} problems, ${operations.length} operations, ` +
    `${validatedBackendCount} backend choices to graphmine_catalog.json`,
);
