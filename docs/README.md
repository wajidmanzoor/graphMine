# GraphMine documentation site

This directory is a self-contained static GitHub Pages site. It uses plain
HTML, CSS, and JavaScript and renders the algorithm catalog from the repository
root `graphmine_catalog.json`. That catalog embeds all 20 local problem
contracts and connects the 12 supported problems to validated operations.

## Preview locally

Run a static server from the repository root:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000/docs/>.

## Publish with GitHub Pages

In the repository settings:

1. Open **Pages** under **Code and automation**.
2. Choose **Deploy from a branch**.
3. Select the `main` branch and `/docs` folder.
4. Save.

The published address is expected to be
<https://wajidmanzoor.github.io/graphMine/>. On GitHub Pages, the site reads the
canonical catalog from the repository’s raw `main` branch, so no committed
duplicate is required inside `docs/`.

## Low-level C++ and CUDA reference

The high-level site links to a generated reference at `docs/reference/`:

- `reference/library/` documents GraphMine public APIs, implementation files,
  backend adapters, examples, and tests function by function;
- `reference/research/` is a searchable portal to one isolated reference for
  each of the 24 validated source artifacts, including its original C, C++,
  and CUDA functions, kernels, types, relationships, and annotated source.

The generated HTML is committed so GitHub Pages can serve it without a custom
build action. Rebuild it after changing public APIs, adapters, vendored source,
or artifact metadata:

```bash
doxygen --version
node tools/build_code_docs.mjs
```

Set `DOXYGEN_EXECUTABLE=/path/to/doxygen` when Doxygen is not on `PATH`.
Warnings emitted from preserved upstream comments do not change or patch the
research implementation; the reference still exposes the parsed signatures
and exact source.
