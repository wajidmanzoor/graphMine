// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 8
CALL apoc.periodic.iterate(
    '
    MATCH (m:Movie)
    WHERE m.directedBy IS NOT NULL AND trim(m.directedBy) <> ""
    UNWIND split(m.directedBy, ",") AS raw_director_name
    WITH m.item_id AS movie_id, trim(raw_director_name) AS director_name
    WHERE director_name <> ""
    RETURN movie_id, director_name
    ',
    '
    MATCH (m:Movie {item_id: movie_id})
    MERGE (d:Director {name: director_name})
    MERGE (d)-[:DIRECTED]->(m)
    ',
    {batchSize: 1000, parallel: false}
);