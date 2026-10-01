# GraphMine

GraphMine is a C++17/CUDA library interface for graph-mining implementations
that passed the project’s GPU correctness validation. It provides one canonical
graph model, typed problem APIs, runtime backend selection, and a build-once
JSON command-line runner.

- **12** validated research problem groups
- **13** runnable library operations
- **26** selectable validated backends
- Canonical JSON graph input and structured JSON results

## Library manifest

[`graphmine_manifest.json`](graphmine_manifest.json) is the global,
machine-readable contract. It embeds the original validated problem
specifications and documents each operation’s input, parameters, backends,
optional-output flags, required outputs, and CLI command.

## Documentation

The static documentation site lives in [`docs/`](docs/) and is ready to publish
with GitHub Pages from the `main` branch’s `/docs` directory.

Once Pages is enabled, the site is available at:

<https://wajidmanzoor.github.io/graphMine/>

The site has no framework or build dependency. It reads the global manifest at
runtime to generate the searchable algorithm catalog.
