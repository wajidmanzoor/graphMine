# Named IU databases

The first IU rollout registered only the server's `neo4j` database, which is
empty. It also discarded `neo4j_database` in the IU resolver, so adding named
connections alone would still have queried that empty default database.

The resolver now retains the selected configured database (and the selected
database for an IU HTTP connector routed through Bolt). Curated inventory accepts
explicit IU source IDs, deduplicates aliases, and keeps `default` tied to `neo4j`.
Each selected dataset shows its own name in query scope and snapshot metadata.
Source fingerprints and connection pools already include the database name.

The operator discovery script prepares private configured sources from a bounded
read-only `SHOW DATABASES` query. It neither wakes the service nor publishes
configuration. Existing local entries remain intact. Page-load inventory still
reads only local metadata; no remote discovery or wake is added to page loads.

The rollout registers Amazon, FARS, FARS 20–22, MovieLens 32M, MovieLens Genome,
Neo4j, OnTime, LDBC SNB (snb100), Stack Overflow and Yelp. The system database is
excluded. The private environment allowlists retain all existing local choices.

Validation before deployment:

- 78 backend tests passed: named driver sessions, source access, allowlists,
  dataset/query/schema routing, stable provenance, pools and existing local paths.
- Two real Firefox picker checks passed at desktop and mobile widths; all ten
  names are selectable and Yelp/Amazon previews use their respective source IDs.
- Five release-gate checks passed; the new suite is automatically included.
- Read-only count-store queries succeeded on all ten live IU databases through
  the application session helper. Counts and names are in live-databases.json.

No remote configuration or data was changed, no SSH command was run, and local
Neo4j remained parked. The native/GPU runtime is unchanged; the previously
authorized GPU revalidation deferral remains documented separately under
validation/iu-neo4j/DEFERRED_GPU_CHECKS.md. Deployment evidence is recorded outside
the checkout in graphmine-data/environments/state/iu-named-datasets-20261126.
