# Public documentation build

Public source is exclusively `docs-src/`. The old `docs/` tree is retained only until the replacement is live; it is not a build input. Internal records and the original October technical note stay outside the public build.

Install `requirements-docs.txt`, Doxygen, and `pdftotext`, then run:

```sh
python3 tools/build_site_catalog.py --check
node tools/build_code_docs.mjs
python3 tools/build_public_note.py
mkdocs build --strict
python3 tools/check_public_site.py
```

`--check` verifies generated family pages, backend tables, catalog data, authoritative taxonomy hashes, and the native source hashes bound to `catalog/site_runtime_snapshot.json`. It does not compile or validate a new binary. After native changes, rebuild and regenerate with `python3 tools/build_site_catalog.py --binary PATH`, using a build whose source revision matches the checkout.

`catalog/problem_reading_guide.json` supplies mathematical notation and example questions. Contracts and runtime metadata remain authoritative. `catalog/site_reference_links.json` records public-link corrections without rewriting historical source provenance.

Doxygen output and the public reading-edition PDF are generated during the Actions build. They are not hand-maintained snapshots. The public note's original is retained in `docs-internal/research-note/`.
