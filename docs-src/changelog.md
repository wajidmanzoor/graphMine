# User-visible changes

See the recent milestones that affect using GraphMine or calling the library. These are dated implementation milestones, not promises of semantic version compatibility.

## November 2026

- Normal and Expert are the two analysis modes.
- Choice cards distinguish a family, formal problem, operation, parameters, and quality. Duplicate densest-subgraph choices with a misleading approximate label were removed.
- Saved conversations remain in the sidebar. The repeated completion and recent-work cards were removed from the main flow.
- Result views keep input scope, algorithm quality, collection completeness, and display limits separate.
- The public documentation explains the current app and native runtime, with family guides, an interactive catalog, and a regenerated code reference.

## October–November 2026

- The native runtime gained the shared family/problem taxonomy and expanded operation profiles across the formal contracts.
- Typed record queries, saved datasets, graph construction from tables, and query-derived input snapshots became part of the workflow.
- Projects support selected input/result snapshots, annotations, saved views, and expiring read-only links.
- Exploration settings and linked result views gained recovery and completeness handling.

Milestone sources: [current commit history](https://github.com/wajidmanzoor/graphMine/commits/main/), the shared catalog, and the implementation records retained in the repository. The [evaluation page](problem/evaluation.md) gives dated validation evidence without treating development test totals as end-to-end accuracy.
