# C++ and CUDA code reference

Find a function, understand its contract, and read the implementation behind the compiled GraphMine runtime.

[Find a function](api/index.md){ .md-button .md-button--primary }
[Browse source files](api/files.md){ .md-button }

Each function entry explains its purpose, parameters, return value, ownership, and relevant validation or failure behavior. Examples accompany key entry points. Expand **Implementation** to read the body, or follow **Read in source** for the surrounding file at the documented revision.

The reference covers the public C++ and C APIs, graph records and views, runtime utilities, algorithm implementations, and CPU/CUDA adapters. Public interfaces and implementation helpers are labelled separately. Optional backends describe their enabled and unavailable paths where builds differ.

Declarations are extracted from the current source, including CUDA files and conditional implementations. Written descriptions are checked for function and parameter coverage. A source change requires the affected documentation to be reviewed before the reference can be published.

For a conceptual explanation and runnable command templates, start with the [family guides](../problem/taxonomy.md#browse-the-families). For a particular signature, type, or source file, use the generated reference. Research-paper repositories remain linked as [research references](../problem/research.md), separately from the current implementation.

The [C++ guide](cpp-api.md), [Python guide](python.md), and [CLI guide](cli.md) show the supported entry points. Generated symbol documentation does not replace the operation's formal input and output contract.
