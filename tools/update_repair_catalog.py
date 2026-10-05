#!/usr/bin/env python3
"""Regenerate checked-in repair profiles and runtime/agent JSON contracts."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = "validation/repaired_library/REPORT.md"
API_EVIDENCE = "validation/repaired_library/results/native-summary.json"


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, value):
    (ROOT / path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def parameter(flag, kind, **rest):
    return dict(flag=flag, type=kind, **rest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "library/build/graphmine")
    args = parser.parse_args()
    runtime = json.loads(
        subprocess.check_output([str(args.binary.resolve()), "list"], text=True)
    )
    runtime_ops = {o["id"]: o for o in runtime["operations"]}
    definitions = [
        (
            "k-truss",
            "k_truss_decomposition",
            "acctd",
            "KTruss",
            ["truss_number_by_edge", "maximum_truss_number"],
            {},
            "Exact full k-truss decomposition of unweighted undirected input; loops removed and parallel edges collapse to the smallest typed external edge ID.",
        ),
        (
            "densest-subgraph",
            "densest_subgraph",
            "cds",
            "DensestSubgraph",
            ["vertices", "density", "induced_edge_value", "optimal"],
            {},
            "Exact unweighted edge density |E(S)|/|S| on a nonempty undirected graph. No fixed cardinality, minimum-size constraint, weighted objective, or higher-order clique-density mode.",
        ),
        (
            "maximal-biclique-counting",
            "maximal_biclique_enumeration",
            "mbe-gpu",
            "MaximalBicliqueCounting",
            ["total_count", "complete"],
            {},
            "Exact count of nonempty maximal bicliques on one GPU; every vertex declares attributes.side=left|right. Count only: no vertex-set enumeration, size filters, bitmap variant, or multi-GPU mode.",
        ),
        (
            "personalized-pagerank",
            "personalized_pagerank_rwr",
            "kpar",
            "PersonalizedPageRank",
            [
                "ranked_vertices",
                "restart_probability_used",
                "complete",
                "approximate",
                "epsilon_used",
                "error_bound",
                "error_bound_certified",
            ],
            {
                "seed_vertex": parameter("--seed-vertex", "vertex_id", required=True),
                "top_k": parameter(
                    "--top-k", "integer", required=True, minimum=1, maximum=1000000
                ),
                "restart_probability": parameter(
                    "--restart-probability", "number", required=True, choices=[0.2]
                ),
                "solution_quality": parameter(
                    "--solution-quality",
                    "string",
                    default="approximate",
                    choices=["approximate"],
                ),
                "epsilon": parameter(
                    "--epsilon", "number", default=0.01, minimum=0.01, maximum=0.5
                ),
                "random_seed": parameter(
                    "--random-seed",
                    "integer",
                    default=20261004,
                    minimum=0,
                    maximum=2147483647,
                ),
            },
            "Approximate top-k outgoing PPR on a directed unweighted multigraph, one seed, explicitly requested restart probability 0.2, dangling mass returned to that seed. Epsilon controls sampling; error_bound=null and error_bound_certified=false. No exact/converged guarantee, weighted walks, multiple seeds, reverse edges, or seed exclusion.",
        ),
        (
            "group-steiner-tree",
            "group_steiner_tree",
            "gpu4gst",
            "GroupSteinerTree",
            ["tree_edges", "tree_weight", "selected_vertices", "feasible", "optimal"],
            {"groups": parameter("--groups", "vertex_groups", required=True)},
            "Exact undirected group Steiner tree with checked edge/vertex certificate; 1..16 nonempty groups, nonnegative integer weights <=2^53-1, tree cost bound below 2^58. Parallel edges use the cheapest edge, with typed edge-ID tie break. Required terminals can be singleton groups. No hop or diameter constraint.",
        ),
        (
            "influence-maximization",
            "influence_maximization",
            "superfuser",
            "InfluenceMaximization",
            [
                "seed_set",
                "expected_spread",
                "guarantee_met",
                "sample_count",
                "prefix_spread",
                "diffusion_model",
            ],
            {
                "diffusion_model": parameter(
                    "--diffusion-model",
                    "string",
                    required=True,
                    choices=["independent_cascade"],
                ),
                "seed_set_size": parameter(
                    "--seed-set-size",
                    "integer",
                    required=True,
                    minimum=1,
                    maximum=1000000,
                ),
                "sample_count": parameter(
                    "--sample-count",
                    "integer",
                    default=256,
                    minimum=32,
                    maximum=65536,
                    multiple_of=32,
                ),
                "random_seed": parameter(
                    "--random-seed", "integer", default=42, minimum=0, maximum=2**64 - 1
                ),
                "require_guarantee": parameter(
                    "--require-guarantee", "boolean", default=False, choices=[False]
                ),
            },
            "Approximate independent-cascade seed selection on a directed graph with explicit edge probabilities in weight. Independent holdout spread; guarantee_met=false. No certified approximation ratio/failure probability, linear threshold model, or physical multi-GPU execution.",
        ),
    ]
    repairs = {
        "acctd": ("acctd", "2020_accelerating_truss_heterogeneous"),
        "mbe-gpu": ("mbe_gpu", "2023_efficient_mbe_gpus"),
        "cds": ("cds", "2026_bound_tightened_dsd"),
        "cuda-ms": ("cuda_ms", "2019_maximum_clique_cuda"),
        "maximum-clique-on-gpu": (
            "maximum_clique_on_gpu",
            "2024_maximum_clique_many_core_gpu",
        ),
        "kpar": ("kpar", "2020_kpar"),
        "gamma-butterfly": ("gamma_butterfly", "2022_gamma_reuse"),
        "gpu4gst": ("gpu4gst", "2025_gpu4gst"),
        "superfuser": ("superfuser", "2021_superfuser"),
    }
    manifest = read("graphmine_manifest.json")
    instructions = read("agent/program_instructions.json")
    registry = read("catalog/backend_registry.json")
    operations = {o["id"]: o for o in manifest["operations"]}
    programs = {o["id"]: o for o in instructions["operations"]}
    registered = {o["id"]: o for o in registry["operations"]}
    profiles = {
        "schema_version": "1.0.0",
        "routing_contract_version": "repaired-37-v2",
        "integration_report": REPORT,
        "public_api_evidence": API_EVIDENCE,
        "operations": {},
        "backends": [],
    }
    for operation, problem, backend, cls, outputs, parameters, profile in definitions:
        native = runtime_ops[operation]
        cpp = dict(
            header="graphmine/problems/repaired_algorithms.hpp",
            **{"class": "graphmine::" + cls},
            options_type="graphmine::" + cls + "Options",
        )
        profiles["operations"][operation] = {
            "problem_id": problem,
            "backend_id": backend,
            "profile": profile,
            "cpp": cpp,
        }
        operations[operation] = {
            "id": operation,
            "research_problem_id": problem,
            "cpp_class": cpp["class"],
            "cpp_header": cpp["header"],
            "cmake_component": "GraphMine::repaired_algorithms",
            "backends": [backend],
            "command": native["usage"],
            "parameters": [p["flag"] for p in parameters.values()]
            + ["--timeout-seconds N", "--worker-directory PATH"],
            "optional_output_flags": {},
            "required_outputs": outputs,
            "validated_profile": profile,
            "validation_report": REPORT,
        }
        programs[operation] = {
            "id": operation,
            "problem_id": problem,
            "default_backend": backend,
            "parameters": parameters,
            "optional_outputs": {},
            "auxiliary_inputs": {},
            "required_outputs": outputs,
            "validated_profile": profile,
            "visualization_candidates": ["table", "metric_cards", "network"],
        }
        registered[operation] = {
            k: native[k] for k in ["id", "research_problem", "usage"]
        }
        registered[operation]["backends"] = [
            {k: v for k, v in b.items() if k != "compiled"} for b in native["backends"]
        ]
    # GAMMA is an alternative for the existing global butterfly operation.
    for collection in [operations, registered]:
        collection["butterfly-counting"]["backends"] = (
            ["graphminer", "gamma-butterfly"]
            if collection is operations
            else [
                {k: v for k, v in b.items() if k != "compiled"}
                for b in runtime_ops["butterfly-counting"]["backends"]
            ]
        )
    operations["butterfly-counting"]["parameters"] = [
        "--timeout-seconds N",
        "--worker-directory PATH",
    ]
    operations["butterfly-counting"]["command"] = runtime_ops["butterfly-counting"][
        "usage"
    ]
    registered["butterfly-counting"]["usage"] = runtime_ops["butterfly-counting"][
        "usage"
    ]
    # Keep the established default until repaired-backend timings are benchmarked.
    programs["maximum-clique"]["default_backend"] = "gpu-maximum-clique"
    operations["maximum-clique"]["validation_report"] = REPORT
    artifacts = read("catalog/artifact_sources.json")
    known = {(a["problem_id"], a["paper_id"]) for a in artifacts["artifacts"]}
    for operation, native in runtime_ops.items():
        for backend in native["backends"]:
            name = backend["id"]
            if name not in repairs:
                continue
            repair, paper = repairs[name]
            profile = operations[operation].get(
                "validated_profile",
                "Exact single maximum-clique witness; single GPU; no all-ties mode.",
            )
            if name == "gamma-butterfly":
                profile = "Exact global butterfly count on an undirected graph with declared sides; C4 injective embedding count divided by eight. No participation, listing, or core decomposition."
            evidence = {
                "workload_id": "repaired_" + name,
                "implementation": name,
                "status": "validated_profile",
                "note": profile,
                "checks": {
                    "standalone_report": f"validation/algorithm_repairs/{repair}/README.md",
                    "public_api_suite": API_EVIDENCE,
                },
                "paper_artifacts": [paper],
            }
            profiles["backends"].append(
                {
                    "problem_id": native["research_problem"],
                    "backend_id": name,
                    "operation_id": operation,
                    "repair_directory": repair,
                    "validation": evidence,
                }
            )
            if name in ["cuda-ms", "maximum-clique-on-gpu"]:
                old = next(
                    b for b in registered[operation]["backends"] if b["id"] == name
                )
                old.update({k: v for k, v in backend.items() if k != "compiled"})
            key = (native["research_problem"], paper)
            if key not in known:
                metadata_path = next(
                    (ROOT / "problems").glob(f"*/papers/{paper}/metadata.json")
                )
                metadata = json.loads(metadata_path.read_text())
                status_path = metadata_path.with_name("artifact_status.json")
                if metadata.get("code"):
                    code = metadata["code"]
                elif status_path.exists():
                    code = json.loads(status_path.read_text())["code"]
                else:
                    code = next(
                        item["code"]
                        for item in read(
                            "validation/gpu_correctness_expansion/results/summary.json"
                        )["artifacts"]
                        if item["paper_id"] == paper
                    )
                artifacts["artifacts"].append(
                    {
                        "problem_id": key[0],
                        "paper_id": paper,
                        "title": metadata.get("title", paper),
                        "year": metadata.get("year"),
                        "venue": metadata.get("venue"),
                        "publication_url": metadata.get(
                            "publication_url",
                            metadata.get("doi_url", metadata.get("url")),
                        ),
                        "code_url": code.get("source_url"),
                        "code_commit": code.get("commit"),
                        "license_file": code.get("license_file"),
                        "license_note": code.get("license_note"),
                    }
                )
                known.add(key)
            if name not in ["cuda-ms", "maximum-clique-on-gpu"]:
                artifact = next(
                    a
                    for a in artifacts["artifacts"]
                    if (a["problem_id"], a["paper_id"]) == key
                )
                artifact.update(
                    source_distribution="external_checkout",
                    repair_report=f"validation/algorithm_repairs/{repair}/README.md",
                    repair_manifest=f"validation/algorithm_repairs/{repair}/"
                    + (
                        "provenance.json"
                        if repair in ["acctd", "mbe_gpu", "cds"]
                        else "manifest.json"
                    ),
                )
    assert len(profiles["backends"]) == 9
    manifest["operations"] = list(operations.values())
    instructions["operations"] = list(programs.values())
    registry["operations"] = list(registered.values())
    supported = {o["research_problem_id"] for o in manifest["operations"]}
    count = sum(len(o["backends"]) for o in manifest["operations"])
    manifest["scope"].update(
        research_problem_count=len(supported),
        runnable_operation_count=len(operations),
        validated_backend_count=count,
        selection_rule="Validated baseline and expansion profiles plus the nine repaired integrations in validation/repaired_library. Only each explicit executable profile is supported.",
        operation_count_note="Triangle and dynamic-triangle operations share a family; maximal-biclique enumeration and count-only operations also share a family.",
    )
    manifest["included_problem_specs"] = [
        {"source": str(p.relative_to(ROOT)), "spec": json.loads(p.read_text())}
        for p in sorted((ROOT / "problems").glob("*/problem.json"))
        if json.loads(p.read_text())["problem_id"] in supported
    ]
    prepare = "python3 library/tools/prepare_repaired_workers.py --fetch --gpu 1"
    manifest["build_once_run_many"]["build"] = [prepare] + [
        c
        for c in manifest["build_once_run_many"]["build"]
        if "prepare_repaired_workers" not in c
    ]
    registry.update(operation_count=len(operations), validated_backend_count=count)
    for path in [
        "graphmine_manifest.json",
        "library/manifests/graphmine_manifest.json",
    ]:
        write(path, manifest)
    write("agent/program_instructions.json", instructions)
    write("catalog/backend_registry.json", registry)
    write("catalog/artifact_sources.json", artifacts)
    write("catalog/repaired_profiles.json", profiles)
    print(
        f"{len(operations)} operations, {len(supported)} problem families, {count} backend choices; nine repaired profiles"
    )


if __name__ == "__main__":
    main()
