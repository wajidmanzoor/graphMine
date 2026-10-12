Graph-Based Geolocation
=======================

Infer geographic coordinates for unlocated vertices using declared graph propagation or supervised graph-learning models.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 2 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2017_gunrock_spatial_median](papers/2017_gunrock_spatial_median/README.md) | local | local | yes |
| [2026_gt_geo](papers/2026_gt_geo/README.md) | missing | local | no |
| [2026_hb_geo](papers/2026_hb_geo/README.md) | local | local | yes |

Gunrock geolocation and HB-Geo are paired. GT-Geo source is available but its associated publisher PDF could not be collected from a verified open source.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
