Saved calculation views
======================

Results open with a deterministic view of the retained calculation. The 82
problem contracts map to 25 presentation profiles. Normal and Expert are the
only calculation modes; visualization actions do not add another mode or change
the native result. The completion card and saved-work dashboard remain removed.

`view_contracts.py` declares field roles and identity namespaces. `view_profile.py`
scans at most 10,000 output rows, 20,000 graph records and 100,000 memberships.
`view_rules.py` chooses a versioned `ViewSpec` with applied rules, immutable input
and result fingerprints, a layout seed, encodings and declared display limits.
Successful calculations save `step-<id>.views.json`; historical runs acquire this
presentation sidecar when first opened. Profiling failures do not fail a completed
calculation. Rendering uses the current server rules while retaining the recorded
rule version in provenance. Explorations store presentation overrides, not a copy
of the spec or graph. Native JSON artifacts are never rewritten by a view action.

The renderer consumes that contract. Labels remain 12 screen pixels, nodes
14–36 pixels and edges 1–4 pixels. One fit routine uses 32-pixel padding and clamps
zoom to 0.8–1.8, with panning for larger scenes. It runs after layouts, filtering,
expansion and Fit. Above 60 nodes, labels
prioritize a small selection and the 20 largest nodes. Category palettes use at
most eight hues; smaller categories share gray without merging their identity.
Signed scores use an orange/neutral/blue ramp around zero. Directions, parallel
records, loops, shared memberships and result/context differences remain visible.

The answer card states the question, a server-generated sentence shared with chat,
profile metrics and recorded quality/device. Its Details disclosure contains the
plan, input snapshot and applied rules. Count-only results have a large value and
no canvas. Item-based results open on Result only, with all members emphasized.

One toolbar provides the supported primary views, three recommended layouts,
the item stepper, search, Fit, Fullscreen, Download and More. Additional layouts
are in More layouts. Matrix and Gallery hide graph-only controls. Clicking a
node toggles entity selection; Shift-drag or Lasso draws a polygon. Item membership
and explicitly selected entities are separate; entity selection clears when the
workflow, step or port changes. The entity list and result
table provide keyboard access, Left/Right step through retained items, F fits,
and Escape clears selection/focus. Dragging a node pins its position. The
overview supports click, drag and arrow-key panning. Reduced-motion preferences
disable transitions. These interactions operate on retained records.

| Profile family | Main views and evidence rules |
|---|---|
| Partition/groups/colors | Group hulls, sizes and connection matrix; meta-graphs require disjoint membership. Comparison shows recorded membership transitions. |
| Bicliques | Adaptive named sides, item stepper, size scatter, adjacency matrix and item gallery. |
| Subgraphs/vertices/edges | Exact retained members or edges, optional input context, recorded metrics and degree/core distributions when available. |
| Scores | Ranked values and histogram with shared selection. Signal vectors explicitly use their first component; edge anomalies retain the edge namespace. |
| Paths/order/flow | Retained predecessor or edge witnesses, ordered route details, hierarchical/radial views, temporal departure/arrival plots and flow/capacity bars. Cut-side layout requires recorded sides. |
| Instances/patterns | Paged item thumbnails, bounded retained connections and explicit occurrence overlay. Pattern IDs remain local to the pattern. |
| Pairs/mapping | Clickable matrices and separate graph namespaces. Predicted-edge views are offered only for link prediction. Merged mapping changes presentation only. |
| Intervals/spectrum | Barcode, birth/death diagram, filtration skeleton and retained eigenvector coloring. Null death can mean right censoring; it does not prove infinite persistence. |
| Samples/walks | Histograms, retained visit counts, step playback and heat overlay. |
| Locations/positions | Actual coordinates with uniform layout scaling. Geographic maps require a configured provider. |
| Predictions/embeddings | Recorded predictions and metrics, confusion only from retained truth, and explicit cached PCA. Raw first two embedding dimensions are identified as such. |
| Scalars/returned graphs | Number cards and explicit enumeration follow-ups; returned-graph degree distribution and input comparison. |

Neighbor expansion reads the immutable saved input, adds at most 50 neighbors per
request, pins existing geometry during layout, and reports current counts and
remaining neighbors. Degree means connections in the saved input, including for
expanded context. Restored context is checked against the
same input and revision. Context displays are bounded to 2,000 vertices and 5,000
edges. **Shortest connection** is a separate shortest-hop exploration, respects
direction, ignores weights explicitly, and has hop, record and time budgets.
**Ask about selection** and **Run on selection** create an owned induced input
before using the existing Normal/Expert calculation flow. Run shows only problems
whose input requirements match that selection. Count-to-enumeration
follow-ups also create a separate calculation; they do not change a saved count.

Explorations store typed selection, moved-node pins and positions, viewport,
styles, filters, expanded input identities and up to 32 named views within a
512 KiB document budget. The saved Yelp view is under the 20 KiB acceptance target.
Concurrent saves retain the existing explicit conflict/recovery flow. Project
sharing freezes the chosen view, data and any cached projection or alternate's
required context under the existing project permissions. Comparing different
inputs requires an explicit choice; equal IDs in generated or independent
namespaces are not treated as proven correspondences.

One Download menu contains PNG, SVG, the named item table CSV, visible entities
CSV, a full report ZIP and raw result JSON. Graph PNG is twice the canvas size;
both image formats include the legend. Named lists in CSV use semicolons and keep
separate ID columns. Visible CSV omits columns that are empty throughout.
The UI report includes a PNG of the selected output's default view, the question,
answer, metrics, named table and reproduction instructions. Its request references
one input snapshot by hash. The existing GET report API remains available with
a deterministic vector fallback; the UI uses POST to supply its rendered PNG.
HTML-based chart SVG uses a self-contained foreign object, which needs an SVG
viewer with HTML support. PNG is the portable image option. Debug controls
(`?debug=1`) include the compact View JSON viewer, explicit limits and story frames.
Saved Vega specifications
remain replayable; new analyst output can request only one optional validated
chart template using declared fields, after the deterministic defaults.

Canvas is the default up to 2,000 vertices / 5,000 edges. Requests can retain up to
50,000 vertices / 100,000 edges, with an explicit cap banner. Cytoscape 3.34.3's
WebGL path is capability gated and disabled for scenes requiring unsupported
edge dashes. Without that capability, the client requests a 2,000-node view.
No additional renderer is loaded. Layouts above 500 nodes run in a worker:
fCoSE/ELK for bounded scenes and a fixed-iteration spatial spring arrangement
for larger force layouts. These are display layouts; the native force-layout
calculation remains CPU-only.

The recorded Firefox headless benchmark in
`validation/visualization-overhaul-20261118/renderer-benchmark.json` measured
canvas setup at about 0.53 / 2.29 / 12.18 seconds for 2k / 10k / 50k nodes.
Mean pan costs were about 78 / 350 / 1,556 ms. This environment cannot create a
WebGL2 context, including with software/force-enabled preferences, so it does
not certify hardware WebGL performance. The fallback is enforced rather than
advertising those large canvas scenes as responsive. Browser tests exercise all
25 profile fixtures, 17 sanitized saved analyses, worker layout, actual native
workflow selection, exports, pins, filters and saved neighbor restoration.

Map tiles are disabled by default. A deployment can configure
`GRAPHMINE_MAP_TILE_URL=/tiles/.../{z}/{x}/{y}` and `GRAPHMINE_MAP_ATTRIBUTION`
for its own same-origin provider/reverse proxy. No default public OpenStreetMap
tile requests are made. Geographic coordinates are validated before enabling a
map; plain coordinate plots require no provider. PCA is an explicit server action
limited to 5,000 vectors of 2–256 dimensions, uses one BLAS thread and stores a
content-addressed display artifact. It never silently reruns on view open.

Build the offline assets with `npm ci && npm run build` in `agent/frontend`.
`npm run contracts` regenerates the API types; `npm run contracts:check`,
`npm run typecheck` and `npm test` verify the frontend contracts. The implementation
adds no native solver or backend execution changes. Browser fixtures distinguish
authored rendering evidence from the real browser/API/native regression tests.

The results-page acceptance suite is `agent/browser_tests/test_results_page_playwright.py`.
Run `results_page_app:app` from `agent/browser_tests` with
`GRAPHMINE_RESULTS_TEST_ROOT` pointing to an isolated writable directory outside
the repository and `/tmp`. It replays anonymized checked-in native outputs through
the real application; `GRAPHMINE_RESULTS_FIXTURES` optionally selects captured
saved fixtures. Point `GRAPHMINE_RESULTS_CASES` at its `acceptance-cases.json`, set
`GRAPHMINE_RESULTS_URL` to the localhost server, and run the test file with pytest.
Install Playwright's Chromium browser for this suite. Production records are not
modified. The acceptance audit and before/after screenshots are under
`validation/results-page-20261118/`.
