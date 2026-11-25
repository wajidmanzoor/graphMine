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
const expansion = readJson("catalog/expansion_profiles.json");
const repairs = readJson("catalog/repaired_profiles.json");
const expansionScreening = readJson(expansion.screening_source);
const validationResults = readJson(
  "validation/gpu_correctness/results/results.json",
);
// Historical evidence is immutable; its research heading key predates topics.
for (const row of validationResults.workloads) row.topic ??= row.problem;
const graphSchema = readJson("problems/graph_input.schema.json");

const problemDirectories = fs
  .readdirSync(path.join(repositoryRoot, "problems"), { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && /^\d{2}_/.test(entry.name))
  .map((entry) => entry.name)
  .sort();

const problemSources = problemDirectories.map((directory) => {
  const source = `problems/${directory}/problem.json`;
  const collectionSource = `problems/${directory}/collection_status.json`;
  const collection = fs.existsSync(path.join(repositoryRoot, collectionSource))
    ? readJson(collectionSource)
    : null;
  return { source, spec: readJson(source), collection, collectionSource };
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

const registryProblems = new Map(
  backendRegistry.problems.map((problem) => [problem.id, problem]),
);
const problemsById = new Map(
  problemSources.map((entry) => [entry.spec.topic_id, entry]),
);
const artifactsByProblemAndPaper = new Map(
  artifactSources.artifacts.map((artifact) => [
    `${artifact.topic_id}:${artifact.paper_id}`,
    artifact,
  ]),
);

const workloadsByProblem = new Map();
for (const workload of validationResults.workloads) {
  const entries = workloadsByProblem.get(workload.topic) || [];
  entries.push(workload);
  workloadsByProblem.set(workload.topic, entries);
}

function validationForBackend(problemId, backendId) {
  const repaired = repairs.backends.find((entry) => entry.topic_id === problemId && entry.backend_id === backendId);
  if (repaired) {
    const evidence = readJson(repairs.public_api_evidence);
    assert(evidence.status === "passed" && evidence.failures === 0, "Repaired profiles require a passing native integration report");
    return repaired.validation;
  }
  const profile = Object.values(expansion.problems).find(
    (entry) => entry.topic_id === problemId && entry.backend_id === backendId,
  );
  if (profile) {
    assert(expansionScreening.artifacts.some((entry) =>
      entry.paper_id === profile.paper_id && entry.validation_status === "validated_profile"),
      `Missing expansion validation for ${problemId}/${backendId}`);
    return profile.validation;
  }
  const implementation = validationImplementation[backendId];
  assert(implementation, `No validation implementation mapping for ${backendId}`);
  const workload = validationResults.workloads.find(
    (entry) =>
      entry.topic === problemId &&
      entry.implementation === implementation &&
      entry.status === "pass",
  );
  assert(
    workload,
    `No passing validation workload for ${problemId}/${backendId}`,
  );
  return workload;
}

const problems = runtimeManifest.problems.map((problem) => {
  const registryProblem = registryProblems.get(problem.id);
  assert(registryProblem, `Missing backend registry entry for ${problem.id}`);
  const topic = problemsById.get(problem.topic_id)?.spec;
  assert(topic, `Missing topic specification for ${problem.topic_id}`);
  const problemPosition = problemSources.findIndex(
    (entry) => entry.spec.topic_id === problem.topic_id,
  );
  assert.notEqual(problemPosition, -1);
  const cpp = cppContracts[problem.id] || expansion.problems[problem.id]?.cpp || repairs.problems[problem.id]?.cpp;
  assert(cpp, `Missing C++ contract for ${problem.id}`);

  const backendDetails = problem.backends.map((backendId) => {
    const registryBackend = registryProblem.backends.find(
      (backend) => backend.id === backendId,
    );
    assert(
      registryBackend,
      `Missing backend registry entry for ${problem.id}/${backendId}`,
    );
    const validation = validationForBackend(
      problem.topic_id,
      backendId,
    );
    const sources = (validation.paper_artifacts || []).map((paperId) => {
      const source = artifactsByProblemAndPaper.get(
        `${problem.topic_id}:${paperId}`,
      );
      assert(source, `Missing artifact source for ${problem.id}/${paperId}`);
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
    ...problem,
    topic_reference: `#/problems/${problemPosition}`,
    problem_inputs: topic.problem_inputs.map((input) => input.name),
    cpp: {
      ...cpp,
      cmake_component: problem.cmake_component,
      lifecycle: [
        "construct options",
        "construct algorithm object",
        "optionally call supports(graph)",
        "call run(...) and inspect ExecutionResult",
      ],
    },
    cli: {
      command_example: problem.command,
      required_auxiliary_inputs: problem.required_auxiliary_inputs || [],
      parameters: problem.parameters || [],
      optional_output_flags: problem.optional_output_flags || {},
    },
    backend_details: backendDetails,
  };
});

const problemsByProblem = new Map();
for (const problem of problems) {
  const entries = problemsByProblem.get(problem.topic_id) || [];
  entries.push(problem);
  problemsByProblem.set(problem.topic_id, entries);
}

const topics = problemSources.map(({ source, spec, collection, collectionSource }) => {
  const problemProblems = problemsByProblem.get(spec.topic_id) || [];
  const validationWorkloads = workloadsByProblem.get(spec.topic_id) || [];
  const validatedBackendCount = problemProblems.reduce(
    (count, problem) => count + problem.backends.length,
    0,
  );
  const available = problemProblems.length > 0;
  const screening = expansionScreening.artifacts.filter(
    (entry) => entry.problem_dir === path.basename(path.dirname(source)),
  );
  const profiles = problemProblems.filter((problem) => expansion.problems[problem.id] || repairs.problems[problem.id])
    .map((problem) => ({ problem_id: problem.id, supported_profile: problem.validated_profile }));

  return {
    source,
    intent_signals: intentSignals[spec.topic_id] || expansion.intent_signals[spec.topic_id] ||
      spec.intent_signals || [spec.name.toLowerCase(), spec.topic_id.replaceAll("_", " ")],
    ...(collection ? {
      research_collection: {
        source: collectionSource,
        algorithm_records: collection.entries,
        local_gpu_source_entries: collection.local_gpu_code_entries,
        local_paper_entries: collection.local_paper_entries,
        eligible_local_pairs: collection.eligible_local_code_and_paper_pairs,
        collection_target_met: collection.target_met,
      },
    } : {}),
    library_support: {
      available,
      status: available ? "validated" : "no_validated_backend",
      problem_ids: problemProblems.map((problem) => problem.id),
      validated_backend_count: validatedBackendCount,
      ...(profiles.length ? { validation_scope: "bounded_profiles_only", profiles } : {}),
      reason: available
        ? (profiles.length
          ? "Only the listed profiles are executable; broader research modes remain unsupported."
          : "At least one implementation passed the GPU correctness validation and is exposed by GraphMine.")
        : (collection?.entries
          ? `${collection.entries} research/implementation records are cataloged, including ${collection.eligible_local_code_and_paper_pairs} eligible local source-and-paper pairs. No implementation is exposed as a validated GraphMine backend for this topic.` +
            (screening.length ? ` Prior implementation screening: ${screening.map((entry) => `${entry.paper_id}: ${entry.note}`).join(" ")}` : "")
          : screening.length
          ? screening.map((entry) => `${entry.paper_id}: ${entry.note}`).join(" ")
          : (expansion.intent_signals[spec.topic_id]
            ? "No local paper/code artifact is cataloged for this definition, so there is no implementation to validate or execute."
            : "No implementation for this topic passed the validation gate, so GraphMine does not expose an problem for it.")),
    },
    validation_workloads: validationWorkloads,
    ...(expansion.intent_signals[spec.topic_id] ? { expansion_screening: screening } : {}),
    spec,
  };
});

const supportedProblems = topics.filter(
  (topic) => topic.library_support.available,
);
const validatedBackendCount = problems.reduce(
  (count, problem) => count + problem.backends.length,
  0,
);
const passingWorkloadCount = validationResults.workloads.filter(
  (workload) => workload.status === "pass",
).length;

const topicIndex = Object.fromEntries(
  topics.map((topic, index) => [
    topic.spec.topic_id,
    {
      name: topic.spec.name,
      category: topic.spec.category,
      library_status: topic.library_support.status,
      problem_ids: topic.library_support.problem_ids,
      problem_ref: `#/problems/${index}`,
    },
  ]),
);

const problemIndex = Object.fromEntries(
  problems.map((problem, index) => [
    problem.id,
    {
      topic_id: problem.topic_id,
      backends: problem.backends,
      problem_ref: `#/problems/${index}`,
    },
  ]),
);

const catalog = {
  schema_version: "2.0.0",
  catalog_id: "graphmine_problem_first_catalog_v2",
  library_version: runtimeManifest.library_version,
  purpose:
    "Topic-first context for mapping a user request to a formal graph topic, a validated GraphMine problem, a backend, parameters, and optional outputs.",
  source_of_truth: {
    problem_contracts:
      "Each problems/*/problem.json object is embedded exactly and remains authoritative for semantics, inputs, outputs, validation rules, and edge cases.",
    runtime_contract: "graphmine_manifest.json",
    validation_results: "validation/gpu_correctness/results/results.json",
    backend_registry: "catalog/backend_registry.json",
    artifact_sources: "catalog/artifact_sources.json",
    expansion_profiles: "catalog/expansion_profiles.json",
    repaired_profiles: "catalog/repaired_profiles.json",
    repaired_integration: repairs.integration_report,
    expansion_screening: expansion.screening_source,
    regeneration_command: "node tools/build_catalog.mjs",
  },
  scope: {
    catalog_topic_count: topics.length,
    library_supported_topic_count: supportedProblems.length,
    library_unsupported_topic_count: topics.length - supportedProblems.length,
    runnable_problem_count: problems.length,
    validated_backend_count: validatedBackendCount,
    passing_validation_workload_count: passingWorkloadCount,
    validated_expansion_profile_count: Object.keys(expansion.problems).length,
    validated_repaired_backend_count: repairs.backends.length,
    problem_count_note:
      "Triangle counting and dynamic triangle counting share one research topic but are separate runnable problems.",
  },
  routing: {
    contract_version: repairs.routing_contract_version,
    model_policy: "Supply this catalog to the base router. The frozen legacy routing adapter was evaluated on the earlier 20-topic contract; do not silently extend its evaluation claims.",
    workflow: [
      {
        step: 1,
        action: "identify_problem",
        instruction:
          "Compare the user request with problem_statement, intent_signals, graph_input, problem_inputs, solution_semantics, and edge_cases. Select exactly one topic_id or report ambiguity.",
        output: "selected_topic_id",
      },
      {
        step: 2,
        action: "check_library_support",
        instruction:
          "Inspect library_support. If status is no_validated_backend, report that faithfully and do not substitute a nearby topic.",
        output: "library_support_status",
      },
      {
        step: 3,
        action: "select_problem",
        instruction:
          "Choose among library_support.problem_ids. Respect each problem's validated_profile and backend_constraints; these can be narrower than the general topic contract.",
        output: "selected_problem_id",
      },
      {
        step: 4,
        action: "resolve_inputs_and_parameters",
        instruction:
          "Use spec.graph_input and spec.problem_inputs for semantic requirements, then use problem.cli for their concrete command-line encoding. Ask for any required graph or auxiliary input that is missing.",
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
          "Always return required_outputs. Enable optional fields only through problem.cli.optional_output_flags when the user requests them or they are necessary for the task.",
        output: "requested_optional_output_flags",
      },
    ],
    hard_rules: [
      "Do not route an unsupported topic to a superficially similar supported problem.",
      "Do not claim support outside an problem's validated_profile or backend_constraints.",
      "Do not invent parameter values for required inputs; request them from the user.",
      "Use canonical external vertex and edge IDs at the public boundary.",
      "Prefer the generic run/supports/result lifecycle; use topic-specific fields only where the contract requires them.",
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
        "selected_topic_id",
        "library_support_status",
        "selected_problem_id",
        "selected_backend_id",
        "resolved_parameters",
        "requested_optional_output_flags",
        "missing_inputs",
      ],
      nullable_when_unsupported: [
        "selected_problem_id",
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
    expansion_source: expansion.screening_source,
    expansion_profiles: expansion.problems,
    repaired_profiles: repairs.backends,
  },
  topic_index: topicIndex,
  problem_index: problemIndex,
  topics,
  problems,
  artifacts: artifactSources.artifacts,
};

assert(topics.length > 0 && problems.length > 0, "Catalog must not be empty");
assert.equal(supportedProblems.length, runtimeManifest.scope.topic_count);
assert.equal(problems.length, runtimeManifest.scope.runnable_problem_count);
assert.equal(problems.length, backendRegistry.problem_count);
assert.equal(validatedBackendCount, runtimeManifest.scope.validated_backend_count);
assert.equal(validatedBackendCount, backendRegistry.validated_backend_count);
assert.deepEqual(new Set(registryProblems.keys()), new Set(problems.map((problem) => problem.id)));
assert.equal(
  Object.keys(topicIndex).length,
  topics.length,
  "Topic IDs must be unique",
);
assert.equal(
  Object.keys(problemIndex).length,
  problems.length,
  "Problem IDs must be unique",
);

for (const { source, spec } of problemSources) {
  const embedded = topics.find(
    (topic) => topic.spec.topic_id === spec.topic_id,
  );
  assert(embedded, `Missing embedded topic ${spec.topic_id}`);
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
  `Wrote ${topics.length} topics, ${problems.length} problems, ` +
    `${validatedBackendCount} backend choices to graphmine_catalog.json`,
);
