# Add an algorithm or operation

Extend the native runtime while preserving the problem contract and verifiable output behavior.

1. Identify an existing formal problem or define a new contract under `problems/`. Specify input assumptions, normalization, parameters, required outputs, exactness, edge cases, and validation rules before implementation.
2. Add the implementation to the appropriate native family. Keep parsing, parameter checks, dispatch, and computation in the compiled runtime. Reuse the declared graph views; exporters should change layout without silently changing graph meaning.
3. Register the operation and its parameter schema. Update the authoritative family/problem catalog and generated catalog artifacts. Keep research-paper references separate from executable backend entries.
4. Declare output-port types, optional materialization, completeness, and provenance. Supply the view profile that lets the application interpret the output's type and shape.
5. Add independent correctness evidence. Include small oracle cases, input rejection, edge cases, and bounded-output behavior. For a GPU profile, compare against CPU/reference semantics under the supported parameters and declared numerical tolerances.
6. Rebuild and regenerate evidence for the changed native code. Update the reading guide, operation documentation, and source-bound site snapshot. Review the affected function contracts and add documentation for every new function and parameter before refreshing the code-reference source binding.

## Checks to run

```sh
ctest --test-dir build/native-cpu --output-on-failure
python -m pytest -q library/tests/test_family_taxonomy.py
python3 tools/build_site_catalog.py --binary build/native-cpu/graphmine-native
python3 tools/build_site_catalog.py --check
node tools/build_code_docs.mjs --refresh-source-binding
python3 tools/build_public_note.py
mkdocs build --strict
python3 tools/check_public_site.py
```

Run the operation-specific oracle and completion suites as well. A CPU-only catalog refresh intentionally records only that build's compiled backends; do not publish it as evidence of GPU coverage. Use a representative verified build for the public catalog.

A new algorithm should be tested against a reference or independently checkable property, not just its own implementation. Enumeration tests should check uniqueness and completeness; optimization tests should check feasibility and objective or bound validity. Stochastic and learned methods need explicit seeds, evaluation splits where applicable, and honest quality labels.

The [native source reference](code-reference.md) and [graph-view guide](graph-format.md) identify the main types. Public docs should describe user or developer behavior; keep working records outside the public source tree.
