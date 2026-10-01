# Catalog sources

This directory contains the small authored registries used to generate the
repository-root [`graphmine_catalog.json`](../graphmine_catalog.json).

- `backend_registry.json` records the public operation usage, backend IDs,
  display names, pinned commits, and capabilities exposed by the library.
- `artifact_sources.json` records the paper, upstream repository, pinned
  commit, and detected license metadata for every passing artifact.

`../tools/build_catalog.mjs` combines these registries with:

- all 20 `problems/*/problem.json` files;
- `problems/graph_input.schema.json`;
- `graphmine_manifest.json`; and
- `validation/gpu_correctness/results/results.json`.

Run the generator from the repository root:

```bash
node tools/build_catalog.mjs
```

The generator validates the expected 20 problem definitions, 12 supported
problems, 13 operations, 26 backend selections, and 24 passing validation
workloads. It writes identical copies to the repository root and
`library/manifests/` for installation with GraphMine.
