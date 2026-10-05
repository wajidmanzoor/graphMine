# Catalog sources

These authored registries generate the repository-root [catalog](../graphmine_catalog.json):

- `backend_registry.json`: operation/backend IDs, usage, provenance and capabilities.
- `artifact_sources.json`: paper, upstream commit, license metadata and external-source status.
- `repaired_profiles.json`: nine repaired profiles, six new APIs and linked validation evidence.

`tools/build_catalog.mjs` combines them with all 37 authoritative problem definitions,
the canonical graph schema, runtime manifest, original validation classifications,
expansion profiles and repair evidence. Current totals are **22 supported families,
24 operations and 38 backend choices**; all 37 problem specifications remain intact.
Historical failures remain linked to the old binaries. Availability applies only
to the explicitly described executable profile.

After building the repaired workers and native CLI:

```bash
python3 tools/update_repair_catalog.py
node tools/build_catalog.mjs
.venv/bin/graphmine-agent export-schemas agent/schemas
```

The repair updater refreshes the manifests, backend registry, repair profiles and
`agent/program_instructions.json` from the validated native contract. The catalog
builder verifies passing public API evidence and writes identical root and
`library/manifests/` copies. It does not promote newly discovered artifacts.
The routing contract is `repaired-37-v2`; the legacy adapter contract remains frozen.
See the [current integration guide](../library/docs/repaired_algorithms.md).
