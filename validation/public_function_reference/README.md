# Function reference and shared site style checks

Checked November 19, 2026. The site keeps the original homepage design and applies its typography, colors, navigation, and spacing to the guides and references. Native function documentation uses the same site layout with a white reading surface in light mode.

The native reference contains 1,101 documented functions from the public headers, runtime, graph core, algorithms, native adapters, and optional typed-library command line. Doxygen extracts C++ and CUDA with conditional definitions visible; reviewed function notes provide purpose, parameters, outputs, ownership, errors, and implementation context. Generated pages are not committed HTML snapshots.

`acceptance.json` records strict generation/build checks, public-content and local-link checks, browser interactions, mobile width checks, six Lighthouse accessibility scores, and compiled C++ example results. Missing function notes, missing parameter notes, and stale source bindings were each confirmed to fail validation without changing runtime code.

Source review corrected three documentation issues before publication: ordinary-versus-fixed density parameter keys, overbroad unknown-key rejection wording in small helpers, and reference lifetimes after moving or assigning the owner. The descriptions preserve algorithm quality and bounded-output distinctions.

Complete local reports, screenshots, extraction inventories, and the example executable remain in the public-reference-refresh-20261119 validation workspace. No application runtime or calculation behavior was changed. This check does not replace algorithm correctness suites or re-certify publisher URLs; the previous external-link report remains applicable.
