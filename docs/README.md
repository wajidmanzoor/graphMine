# GraphMine documentation site

The static GitHub Pages site organizes the library as **topic families →
formal topics → algorithms and implementations**. Its catalog includes the
current native problem profiles, graph-record query utilities, and collected
research algorithm references. Research references are labeled separately from
executable implementations. Device support, quality and GPU profile limits are
visible in each algorithm's details.

The site uses plain HTML, CSS and JavaScript. `docs/catalog.json` ships with the
site, so its data and UI are published together without a runtime API dependency.
Counts come from that catalog rather than fixed HTML text. The demo section
embeds the YouTube walkthrough linked in the main README; playback requires
access to YouTube. The player supports inline mobile playback and fullscreen,
with a direct YouTube link below it.

## Update the catalog

Build the native runtime after changing its problem registry or taxonomy,
then regenerate the site catalog:

```bash
python3 tools/build_site_catalog.py
python3 tools/build_site_catalog.py --check
```

The default binary is `library/build/runtime/graphmine-native`. For another
build, pass `--binary build/native/graphmine-native`. The script reads the
native `catalog` response, the authoritative taxonomy in
`catalog/family.json`, `catalog/problems.json`, generated `catalog/algo.json`, each formal `problem.json`, and
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
Check family navigation, topic deep links, search, CPU/GPU filters, algorithm
details and narrow screens. Useful links include `#family/dense` and
`#topic/maximum_clique`.

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
