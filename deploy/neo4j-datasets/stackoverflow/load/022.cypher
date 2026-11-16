// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 27
CALL apoc.periodic.iterate(
    "
    MATCH (c:Comment)
    WHERE c.user_id IS NOT NULL
      AND c.user_id <> 0
    RETURN
        c.comment_id AS comment_id,
        c.user_id AS user_id
    ",
    "
    MATCH (c:Comment {comment_id: comment_id})
    MATCH (u:User {user_id: user_id})
    MERGE (c)-[:COMMENTED_BY]->(u)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);