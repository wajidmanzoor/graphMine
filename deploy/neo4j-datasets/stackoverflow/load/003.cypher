// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 4
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/badges.csv' AS row RETURN row",
    "
    MERGE (b:Badge {badge_id: toInteger(row.id)})
    SET b.name      = row.name,
        b.date      = row.date,
        b.user_id   = toInteger(row.user_id),
        b.class     = toInteger(row.class),
        b.tag_based = CASE WHEN row.tag_based = 'true' THEN true ELSE false END
    ",
    {batchSize: 20000, parallel: false, retries: 2}
);