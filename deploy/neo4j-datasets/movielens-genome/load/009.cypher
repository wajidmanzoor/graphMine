// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 9
CALL apoc.periodic.iterate(
    '
    MATCH (m:Movie)
    WHERE m.starring IS NOT NULL AND trim(m.starring) <> ""
    RETURN m, split(m.starring, ",") AS actors
    ',
    '
    UNWIND actors AS actorName
    WITH m, trim(actorName) AS name
    WHERE name <> ""
    MERGE (a:Actor {name: name})
    MERGE (a)-[:ACTED_IN]->(m)
    ',
    {batchSize: 1000, parallel: false}
)