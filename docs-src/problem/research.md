# Research

Read the system's public technical note and follow the algorithm literature behind each formal problem.

## Public technical note

**GraphMine: from questions to checked graph computations** is a public reading edition dated November 19, 2026. It describes the current separation between language understanding, formal problem selection, native execution, and result explanation. It is a technical note, not a peer-reviewed evaluation paper.

**Abstract.** GraphMine turns questions about connected records into explicit graph computations. A language model helps interpret the question and select a formal problem. A compiled C++/CUDA runtime checks the input and parameters, executes a supported algorithm, and returns structured results. The application uses those facts to construct explanations and views. A shared taxonomy distinguishes problem families, formal contracts, callable operations, and implementation profiles. Quality, completeness, and provenance remain visible so that a candidate solution, a bounded collection, and a proven optimum are not confused.

[Read or download the PDF](../research-note/graphmine.pdf)

!!! tip "How to cite"
    GraphMine contributors. *GraphMine: from questions to checked graph computations*. Public technical note, November 19, 2026. Include the repository revision when citing a particular implementation or catalog.

```bibtex
@techreport{graphmine2026public,
  author = {{GraphMine contributors}},
  title = {GraphMine: From Questions to Checked Graph Computations},
  year = {2026},
  month = nov,
  note = {Public reading edition, November 19, 2026},
  url = {https://wajidmanzoor.github.io/graphMine/research-note/graphmine.pdf}
}
```

This edition replaces an older implementation snapshot on the public site. It makes no new numerical performance or accuracy claim.

## Algorithm references

The [catalog](explorer.md) contains research references grouped by formal problem. Each [family page](taxonomy.md#browse-the-families) links the corresponding papers and available author repositories. Those references provide definitions, algorithms, proofs, and comparisons. The executable operation table separately records what the native build provides.

## Related work

Clique and dense-subgraph research studies precise objectives that sound similar in ordinary language. Graph traversal and connectivity research handles different direction and reachability semantics. Community methods optimize declared objectives, often heuristically. Graph-learning work produces predictions or representations rather than exact structural answers. GraphMine brings these distinctions into the question-routing and result interface; the underlying algorithms retain their own assumptions and guarantees.
