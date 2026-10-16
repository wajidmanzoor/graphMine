# GraphMine documentation site

The static GitHub Pages site organizes the library as **problem families →
formal problems → algorithms and implementations**. Its catalog includes the
current native operation profiles, graph-record query utilities, and collected
research algorithm references. Research references are labeled separately from
executable implementations. Device support, quality and GPU profile limits are
visible in each algorithm's details.

The site uses plain HTML, CSS and JavaScript, with no external assets or runtime
API dependency. `docs/catalog.json` ships with the site, so its data and UI are
published together. Counts come from that catalog rather than fixed HTML text.

## Update the catalog

Build the native runtime after changing its operation registry or taxonomy,
then regenerate the site catalog:

```bash
python3 tools/build_site_catalog.py
python3 tools/build_site_catalog.py --check
```

The default binary is `library/build/runtime/graphmine-native`. For another
build, pass `--binary build/native/graphmine-native`. The script reads the
native `catalog` response, the authoritative taxonomy in
`library/manifests/problem_families.json`, each formal `problem.json`, and
`catalog/artifact_sources.json`. It checks their relationships and records
source hashes and the native implementation fingerprint. It does not run any
algorithms or modify the runtime catalogs.

Compiled backends describe the binary used to generate the documentation.
Actual execution additionally depends on compatible inputs, hardware and the
application's matching validation evidence. Use your own `graphmine-native
catalog` to inspect your build.

## Preview locally

From the repository root:

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000/docs/>. Serving `docs/` as the web root also works.
Check family navigation, problem deep links, search, CPU/GPU filters, algorithm
details and narrow screens. Useful links include `#family/cliques` and
`#problem/maximum_clique`.

## Publish with GitHub Pages

Use the repository's Pages deployment from the `main` branch and `/docs` folder.
Commit the generated catalog together with its site changes. The published site
is <https://wajidmanzoor.github.io/graphMine/>.

## Runtime and source documentation

- [Native runtime and build guide](NATIVE_CORE_MIGRATION.md)
- [Current analytics workspace](ANALYTICS_WORKSPACE.md)
- [Native completion profiles](NATIVE_COMPLETION_PROFILES.md)
- [Record query utilities](RECORD_QUERIES.md)

The generated reference under `reference/` documents the earlier typed library
and imported research sources. It is a source documentation snapshot; the main
catalog describes the current native runtime. Rebuild source documentation
when those APIs or source artifacts change:

```bash
doxygen --version
node tools/build_code_docs.mjs
```

Set `DOXYGEN_EXECUTABLE=/path/to/doxygen` when needed. Rebuilding the family
catalog does not regenerate the Doxygen snapshot.
