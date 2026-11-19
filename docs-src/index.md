# GraphMine

Ask a question about connected data, then inspect the computation behind the answer. GraphMine maps plain English to a formal graph problem, runs a compatible compiled CPU or GPU algorithm, and explains the returned facts. The language model helps choose and explain the calculation; it does not supply the numerical results. Each operation states whether its answer is exact, heuristic, or learned.

<div class="grid cards" markdown>

- **[The problem](problem/index.md)**

    Why translating a question into the right graph computation is difficult.

- **[Use the app](guide/getting-started.md)**

    Bring data, ask a question, and explore the result.

- **[Use the library](library/install.md)**

    Build the native runtime and call it from C++, Python, or the command line.

- **[How it works](how-it-works/index.md)**

    Follow the boundaries between understanding, calculation, and explanation.

</div>

## What can I do with it?

Find connected groups, compare paths, measure importance, count patterns, or select a set of vertices under a precise constraint. You can inspect the selected problem and parameters before a calculation, explore its returned graph and tables, and download the evidence. The [catalog](problem/explorer.md) explains the supported questions and their input requirements.

<p class="catalog-counts" aria-live="polite"><span data-stat="families">—</span> families · <span data-stat="formal_problems">—</span> formal problems · <span data-stat="operations">—</span> operations · <span data-stat="research_algorithms">—</span> research references</p>

Counts come from the [current catalog](catalog.json). Research references are separate from executable implementations.

[Open GraphMine](https://graphmine.autographmine.com/#){ .md-button .md-button--primary }
[Read the public technical note](research-note/graphmine.pdf){ .md-button }

## Watch a complete example

<div class="demo-video"><iframe src="https://www.youtube.com/embed/F5bJvpa3gdQ?playsinline=1&amp;rel=0" title="GraphMine system demo" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>

[Watch on YouTube](https://youtu.be/F5bJvpa3gdQ). The recording is a walkthrough; the guides describe the current interface.
