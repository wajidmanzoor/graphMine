// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 6
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/comments.csv' AS row RETURN row",
    "
    MERGE (c:Comment {comment_id: toInteger(row.id)})
    SET c.text              = row.text,
        c.creation_date      = row.creation_date,
        c.post_id            = toInteger(row.post_id),
        c.user_id            = toInteger(row.user_id),
        c.user_display_name  = row.user_display_name,
        c.score             = toInteger(row.score)
    ",
    {batchSize: 20000, parallel: false, retries: 2}
);