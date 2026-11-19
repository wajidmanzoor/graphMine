# Command-line interface

Inspect your compiled catalog and run operations from files or a JSON request stream.

## Inspect the catalog

```sh
graphmine-native families
graphmine-native catalog --family dense
graphmine-native list --family paths
```

`families` returns family metadata. `list` returns operation profiles. `catalog` includes formal problems, schemas, and compiled backend information. A family filter narrows those records; it does not change the algorithms.

## Run a calculation

```sh
graphmine-native run triangle-counting \
  library/examples/data/triangle.json --device cpu
```

For operations with parameters, save a JSON object and supply `--parameters`:

```sh
graphmine-native run maximum-clique graph.json \
  --parameters clique-parameters.json --device cpu
```

For example, `clique-parameters.json` can contain `{"return_all_ties": true}`. The graph must satisfy the selected problem's contract.

`--device` accepts `cpu`, `gpu`, or `auto`. `--backend` selects a particular compiled implementation. `--budget` accepts a JSON budget file. Compatibility and resource limits still apply. A request for an unavailable implementation is an error, not an invented result.

## Request protocol and exit status

```sh
graphmine-native request < request.json
```

This reads one JSON request from standard input. The command protocol also supports declared graph and CSV readers; inspect their availability in your build's catalog.

| Exit code | Meaning |
| --- | --- |
| `0` | The request completed without a structured error. |
| `2` | Invalid arguments/input or a runtime error. Inspect the JSON error. |

Result JSON is written to standard output. Implementation diagnostics go to standard error. Argument/read failures also report their JSON error on standard error. Check both the exit status and the response when integrating the CLI.
