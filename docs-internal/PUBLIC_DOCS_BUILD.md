# Public documentation build

Public content source is exclusively `docs-src/`. The original visual design is retained through `overrides/` templates and `docs-src/assets/original*.css`; MkDocs supplies the documentation hierarchy, search, and build. The old `docs/` HTML and typed-library reference snapshot were removed after the replacement went live. Internal records and the original October technical note stay outside the public build.

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

Doxygen 1.9.8 extracts XML from all first-party public headers, the native runtime, and library sources, including CUDA and conditional definitions. The site renders those symbols as ordinary documentation pages, using reviewed contracts in `tools/code_docs/function-notes/`. The generator rejects missing function descriptions, incomplete parameter coverage, and stale source bindings. It does not infer explanations from function names.

After changing library code, review affected notes, then run `node tools/build_code_docs.mjs --refresh-source-binding`. Commit the reviewed notes and updated `tools/code_docs/source-manifest.json` together. `--draft` is available only for local editing; CI always requires complete documentation. The Actions build uses Ubuntu 24.04 to keep the Doxygen parser version consistent.

The reference pages and public reading-edition PDF are generated during the Actions build. They are not hand-maintained HTML snapshots. The public note's original is retained in `docs-internal/research-note/`.
