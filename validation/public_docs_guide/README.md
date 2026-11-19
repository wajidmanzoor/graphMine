# Public guide and original design checks

Checked November 19, 2026. The original homepage, navigation, colors, cards, and terminal example are retained while MkDocs supplies the content hierarchy and search. `acceptance.json` records the final local checks.

The four requested mobile accessibility checks scored 100. Browser checks cover catalog search, CPU/GPU filters, operation details, old family/problem fragments, site-wide search, math, conceptual diagrams, redirects, dark mode, and the mobile drawer at 375 pixels. The strict build, current native reference generation, catalog consistency, local links, and public-content exclusions pass.

The external-link check reached 278 of 299 destinations successfully. The remaining 21 publisher destinations return HTTP 403 to the automated checker and remain unverified; no HTTP error is silently accepted. The author-hosted maximum-common-subgraph paper now uses its working proceedings URL. Complete local tool reports and screenshots are retained with the validation workspace.

The two public screenshots show the current application using an isolated test account and anonymized example data. Saved computed fixtures are replayed through the actual viewer; these screenshots are not evidence of model routing accuracy. No production account, application configuration, or load test was changed.

Legacy HTML was removed only after PR #3's replacement site was successfully deployed. The current C++/CUDA reference is generated at build time; the separate family guides explain the problems and how to call their compiled operations.
