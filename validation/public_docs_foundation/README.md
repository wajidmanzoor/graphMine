# Public documentation foundation checks

Checked November 19, 2026. `acceptance.json` records the strict build, catalog consistency, local-link/content scan, browser interactions, mobile width checks, and Lighthouse accessibility scores. The CLI and Python triangle-counting examples also ran against the current native runtime on CPU.

The first external-link pass found publisher bot blocks and two unavailable author-hosted links. The maximum-common-subgraph PDF now points to the author's proceedings version. The unavailable HGA code link is omitted from the public catalog, with an explicit note; the historical source catalog remains intact. `publisher-blocks.json` preserves the URLs that could not be verified automatically. Pre-publication canonical URLs were checked locally; the live URLs are checked after deployment. No blanket acceptance of HTTP errors is used.

The complete local reports and screenshots are retained in the documentation validation workspace. This change does not run load tests or alter the application runtime.
