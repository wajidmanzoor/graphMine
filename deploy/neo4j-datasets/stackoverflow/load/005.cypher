// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 7
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/votes.csv' AS row RETURN row",
    "
        MERGE (v:Vote {vote_id: toInteger(row.id)})
        SET v.creation_date  = row.creation_date,
        v.post_id        = toInteger(row.post_id),
        v.vote_type_id   = toInteger(row.vote_type_id)
    ",
    {batchSize: 20000, parallel: false, retries: 2}
);